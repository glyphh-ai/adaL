"""
SqlFactStore — the SQL-backed storage mode.

Same write surface and query semantics as ThoughtSpace, but nothing is
held in process memory: writes go straight to ada_thoughts + fact_slots,
and the eight closed ops execute as FIXED, parameterized SQL templates
over the indexed slots table. O(1) boot, O(1) RAM, measured-fast at 10M
rows (see benchmark/phase3/sql_bench.py).

The crucial property carried over from the benchmarks: the LLM still
only ever picks an op and fills values — no model-generated SQL exists
anywhere in this path, so the runaway-query class measured in Phase 3
is excluded by construction.

Mode is selected by ADA_STORAGE=sql (default: memory). The
conversational brain pipeline currently requires memory mode; the MCP
tool surface (tell / tell_raw / query / recall / history / stats) is
fully supported in both.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select

from ada.memory.thought_space import (
    RecallResult,
    StoredThought,
    _sanitize_universal,
    _tokenize,
    score_thought,
)

logger = logging.getLogger(__name__)

_CANDIDATE_LIMIT = 400  # recall candidate pool fetched from SQL
_ENTITY_CAP = 1000      # max names returned by `who`; counts are unbounded


class SqlFactStore:
    """Async, SQL-backed fact store for one space."""

    is_sql = True

    def __init__(self, session_factory: Any, space_id: str = "main",
                 enricher: object | None = None):
        self._sf = session_factory
        self.space_id = space_id
        self._enricher = enricher

    # ── Write surface ────────────────────────────────────────────────

    async def absorb(self, text: str, speaker: str = "incoming",
                     metadata: dict | None = None,
                     key: str | None = None,
                     speaker_entity: str | None = None) -> StoredThought | None:
        text_key = text.strip().lower()
        if not text_key:
            return None
        if await self._is_duplicate(text_key):
            return None
        meta = (metadata or {}).copy()
        if self._enricher is not None and "_universal" not in meta:
            try:
                universal = getattr(self._enricher, "universal", None)
                if callable(universal):
                    mapped = universal(text)
                    if mapped:
                        from ada.memory.thought_space import _resolve_speaker_entity
                        clean = _sanitize_universal(mapped)
                        if speaker_entity:
                            clean = _resolve_speaker_entity(text, clean, speaker_entity)
                        meta["_universal"] = clean
                meta["_structured"] = self._enricher.enrich(text)
            except Exception:
                logger.warning("enricher failed for %r", text[:50],
                               exc_info=True)
        return await self._store(text, speaker, meta, key)

    async def tell_raw(self, facts: dict, key: str | None = None,
                       text: str | None = None, speaker: str = "incoming",
                       metadata: dict | None = None) -> StoredThought | None:
        clean = _sanitize_universal(facts or {})
        if not clean:
            return None
        if text is None:
            from ada.memory.thought_space import ThoughtSpace
            text = ThoughtSpace._synthesize_text(clean)
        if await self._is_duplicate(text.strip().lower()):
            return None
        meta = (metadata or {}).copy()
        meta["_universal"] = clean
        meta["_raw"] = True
        return await self._store(text, speaker, meta, key)

    async def _store(self, text: str, speaker: str, meta: dict,
                     key: str | None) -> StoredThought:
        version = 1
        if key is not None:
            version = (await self._max_version(key)) + 1
            from datetime import datetime, timezone
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            thought_id = f"{key}@{stamp}#v{version}"
            meta["_key"] = key
            meta["_version"] = version
        else:
            thought_id = str(uuid.uuid4())[:12]

        stored = StoredThought(
            thought_id=thought_id, content=text, speaker=speaker,
            space_id=self.space_id, metadata=meta,
        )
        from ada.memory.thought_persistence import save_thought
        await save_thought(self._sf, stored)  # writes thought + slot rows
        return stored

    async def _is_duplicate(self, text_lower: str) -> bool:
        from domains.models.db_models import AdaThought
        async with self._sf() as s:
            r = await s.execute(
                select(AdaThought.thought_id)
                .where(AdaThought.space_id == self.space_id,
                       func.lower(AdaThought.content) == text_lower)
                .limit(1))
            return r.first() is not None

    async def _max_version(self, key: str) -> int:
        from domains.models.db_models import AdaThought
        async with self._sf() as s:
            r = await s.execute(
                select(func.max(AdaThought.extra_data["_version"].as_integer()))
                .where(AdaThought.space_id == self.space_id,
                       AdaThought.extra_data["_key"].as_string() == key))
            return int(r.scalar() or 0)

    # ── The closed op set — fixed SQL templates ──────────────────────

    async def execute_op(self, op: dict) -> str:
        kind = op.get("op")
        if kind == "refuse":
            return "I don't know."
        if kind == "count":
            return str(await self._count_entities_where(op["conditions"]))
        if kind == "who":
            names = await self._entities_where(op["conditions"])
            return ", ".join(sorted(names)) if names else "none"
        if kind == "count_not":
            layer, _, role = op["slot"].partition(".")
            v = str(op["value"]).strip().lower()
            filled = await self._entities_with_slot(layer, role)
            having = await self._entities_for(layer, role, v)
            return str(len(filled - having))
        if kind == "top":
            layer, _, role = op["slot"].partition(".")
            dist = await self.distribution_filtered(
                layer, role, int(op.get("k", 5)),
                predicate_contains=op.get("predicate_contains"))
            if not dist:
                return "none"
            return ", ".join(f"{v} ({n})" for v, n in dist)
        if kind == "lookup":
            return await self._lookup(op["person"], op["slot"])
        if kind == "prev":
            prev_v = await self.previous_value(op["person"], op["slot"])
            return str(prev_v) if prev_v is not None else "I don't know."
        if kind == "compare":
            layer, _, role = op["slot"].partition(".")
            ca = await self.count_where(layer, role, op["a"])
            cb = await self.count_where(layer, role, op["b"])
            if ca == cb:
                return f"equal ({ca} each)"
            winner = op["a"] if ca > cb else op["b"]
            return f"{winner} ({max(ca, cb)} vs {min(ca, cb)})"
        raise ValueError(f"unknown op {kind!r}")

    async def _entities_for(self, layer: str, role: str, value: str,
                            predicate_contains: str | None = None) -> set:
        from domains.models.db_models import FactSlot
        q = (select(FactSlot.entity).distinct()
             .where(FactSlot.space_id == self.space_id,
                    FactSlot.is_current == 1,
                    FactSlot.layer == layer, FactSlot.role == role,
                    FactSlot.value == value,
                    FactSlot.entity.is_not(None)))
        if predicate_contains:
            q = q.where(FactSlot.predicate.like(f"%{predicate_contains}%"))
        async with self._sf() as s:
            return {row[0] for row in (await s.execute(q)).all()}

    async def _entities_with_slot(self, layer: str, role: str) -> set:
        from domains.models.db_models import FactSlot
        async with self._sf() as s:
            r = await s.execute(
                select(FactSlot.entity).distinct()
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.is_current == 1,
                       FactSlot.layer == layer, FactSlot.role == role,
                       FactSlot.entity.is_not(None)))
            return {row[0] for row in r.all()}

    async def _entities_where(self, conditions: dict) -> list[str]:
        """Entity intersection done IN SQL via INTERSECT — never fetches
        full per-condition entity lists into Python. A condition on
        relational.predicate uses containment; list values require ALL.
        Returns at most _ENTITY_CAP names (large cohorts answer counts,
        not name lists; see count vs who in the op layer)."""
        from domains.models.db_models import FactSlot
        selects = []
        for lr, v in conditions.items():
            layer, _, role = lr.partition(".")
            values = v if isinstance(v, (list, tuple)) else [v]
            for value in values:
                value = str(value).strip().lower()
                q = (select(FactSlot.entity)
                     .where(FactSlot.space_id == self.space_id,
                            FactSlot.is_current == 1,
                            FactSlot.entity.is_not(None)))
                if lr == "relational.predicate":
                    q = q.where(FactSlot.predicate.like(f"%{value}%"))
                else:
                    q = q.where(FactSlot.layer == layer,
                                FactSlot.role == role, FactSlot.value == value)
                selects.append(q)
        if not selects:
            return []
        stmt = selects[0]
        for q in selects[1:]:
            stmt = stmt.intersect(q)
        stmt = stmt.limit(_ENTITY_CAP)
        async with self._sf() as s:
            rows = (await s.execute(stmt)).all()
        return sorted({row[0] for row in rows})

    async def _count_entities_where(self, conditions: dict) -> int:
        """COUNT of the intersection — never materializes names."""
        from sqlalchemy import func as _f
        names = await self._entities_where_subq(conditions)
        if names is None:
            return 0
        async with self._sf() as s:
            return int((await s.execute(
                select(_f.count()).select_from(names.subquery()))).scalar() or 0)

    async def _entities_where_subq(self, conditions: dict):
        from domains.models.db_models import FactSlot
        selects = []
        for lr, v in conditions.items():
            layer, _, role = lr.partition(".")
            values = v if isinstance(v, (list, tuple)) else [v]
            for value in values:
                value = str(value).strip().lower()
                q = (select(FactSlot.entity)
                     .where(FactSlot.space_id == self.space_id,
                            FactSlot.is_current == 1,
                            FactSlot.entity.is_not(None)))
                if lr == "relational.predicate":
                    q = q.where(FactSlot.predicate.like(f"%{value}%"))
                else:
                    q = q.where(FactSlot.layer == layer,
                                FactSlot.role == role, FactSlot.value == value)
                selects.append(q)
        if not selects:
            return None
        stmt = selects[0]
        for q in selects[1:]:
            stmt = stmt.intersect(q)
        return stmt

    async def _entities_predicate(self, needle: str) -> set:
        from domains.models.db_models import FactSlot
        async with self._sf() as s:
            r = await s.execute(
                select(FactSlot.entity).distinct()
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.is_current == 1,
                       FactSlot.predicate.like(f"%{needle}%"),
                       FactSlot.entity.is_not(None)))
            return {row[0] for row in r.all()}

    async def count_where(self, layer: str, role: str, value: str) -> int:
        from domains.models.db_models import FactSlot
        async with self._sf() as s:
            r = await s.execute(
                select(func.count())
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.is_current == 1,
                       FactSlot.layer == layer, FactSlot.role == role,
                       FactSlot.value == str(value).strip().lower()))
            return int(r.scalar() or 0)

    async def distribution_filtered(self, layer: str, role: str,
                                    top_k: int = 5,
                                    predicate_contains: str | None = None):
        from domains.models.db_models import FactSlot
        q = (select(FactSlot.value, func.count().label("n"))
             .where(FactSlot.space_id == self.space_id,
                    FactSlot.is_current == 1,
                    FactSlot.layer == layer, FactSlot.role == role)
             .group_by(FactSlot.value)
             .order_by(func.count().desc())
             .limit(top_k))
        if predicate_contains:
            q = q.where(FactSlot.predicate.like(f"%{predicate_contains}%"))
        async with self._sf() as s:
            return [(row[0], int(row[1])) for row in (await s.execute(q)).all()]

    async def _lookup(self, person: str, slot: str) -> str:
        """Fetch the entity's slots via the entity index (a handful of
        rows) and filter layer/role in Python — planner-proof: never
        lets SQLite choose the layer/role index and scan millions."""
        from domains.models.db_models import FactSlot
        p = str(person).strip().lower()
        layer, _, role = slot.partition(".")
        async with self._sf() as s:
            r = await s.execute(
                select(FactSlot.layer, FactSlot.role, FactSlot.value)
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.entity == p,
                       FactSlot.is_current == 1))
            rows = r.all()
            if not rows:  # fuzzy fallback: substring entity match, bounded
                r = await s.execute(
                    select(FactSlot.layer, FactSlot.role, FactSlot.value)
                    .where(FactSlot.space_id == self.space_id,
                           FactSlot.entity.like(f"%{p}%"),
                           FactSlot.is_current == 1)
                    .limit(200))
                rows = r.all()
        values = sorted({v for la, ro, v in rows if la == layer and ro == role})
        return ", ".join(values) if values else "I don't know."

    async def previous_value(self, person: str, slot: str) -> str | None:
        from domains.models.db_models import FactSlot
        p = str(person).strip().lower()
        layer, _, role = slot.partition(".")
        async with self._sf() as s:
            r = await s.execute(
                select(FactSlot.key, func.max(FactSlot.version))
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.key.like(f"{p}.%"),
                       FactSlot.layer == layer, FactSlot.role == role)
                .group_by(FactSlot.key))
            for key, max_v in r.all():
                if max_v and max_v > 1:
                    r2 = await s.execute(
                        select(FactSlot.value)
                        .where(FactSlot.space_id == self.space_id,
                               FactSlot.key == key,
                               FactSlot.version == max_v - 1,
                               FactSlot.layer == layer,
                               FactSlot.role == role).limit(1))
                    row = r2.first()
                    if row:
                        return row[0]
        return None

    # ── History / recall / stats ─────────────────────────────────────

    async def history(self, key: str) -> list[StoredThought]:
        from domains.models.db_models import AdaThought
        async with self._sf() as s:
            r = await s.execute(
                select(AdaThought)
                .where(AdaThought.space_id == self.space_id,
                       AdaThought.extra_data["_key"].as_string() == key))
            rows = r.scalars().all()
        thoughts = [self._to_thought(row) for row in rows]
        thoughts.sort(key=lambda t: t.metadata.get("_version", 1))
        return thoughts

    async def keyed_facts(self, limit: int = 60) -> list[dict]:
        """Current belief for every versioned key, newest first.
        Keys come from fact_slots (indexed, is_current=1); contents from
        ada_thoughts by id — same planner-proof shape as _lookup."""
        from domains.models.db_models import AdaThought, FactSlot
        async with self._sf() as s:
            r = await s.execute(
                select(FactSlot.thought_id).distinct()
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.key.isnot(None),
                       FactSlot.is_current == 1)
                .limit(limit * 4))
            ids = [row[0] for row in r.all()]
            if not ids:
                return []
            r = await s.execute(
                select(AdaThought).where(AdaThought.thought_id.in_(ids)))
            rows = r.scalars().all()
        out = []
        for row in rows:
            meta = row.extra_data or {}
            if meta.get("_key"):
                out.append({"key": meta["_key"], "content": row.content,
                            "version": meta.get("_version", 1),
                            "created_at": row.created_at})
        out.sort(key=lambda d: d["created_at"], reverse=True)
        return out[:limit]

    async def recall(self, query: str, top_k: int = 5,
                     exclude_speakers: tuple = ()) -> list[RecallResult]:
        """Candidates from SQL (slot-value matches + content LIKE per
        token, bounded), scored by the same shared scorer as memory
        mode. Bounded candidate pool — documented approximation."""
        from domains.models.db_models import AdaThought, FactSlot
        tokens = _tokenize(query)
        if not tokens:
            return []
        q_tokens = set(tokens)
        q_norm = query.strip().lower().rstrip("?.! ")

        candidate_ids: set[str] = set()
        async with self._sf() as s:
            r = await s.execute(
                select(FactSlot.thought_id).distinct()
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.is_current == 1,
                       FactSlot.value.in_(tokens))
                .limit(_CANDIDATE_LIMIT))
            candidate_ids |= {row[0] for row in r.all()}
            for tok in tokens[:6]:
                r = await s.execute(
                    select(AdaThought.thought_id)
                    .where(AdaThought.space_id == self.space_id,
                           AdaThought.archived == 0,
                           AdaThought.content.like(f"%{tok}%"))
                    .limit(_CANDIDATE_LIMIT // len(tokens[:6]) + 1))
                candidate_ids |= {row[0] for row in r.all()}
            if not candidate_ids:
                return []
            r = await s.execute(
                select(AdaThought)
                .where(AdaThought.thought_id.in_(list(candidate_ids)[:_CANDIDATE_LIMIT])))
            rows = r.scalars().all()

        q_struct = None
        if self._enricher is not None:
            try:
                q_struct = self._enricher.enrich(query)
            except Exception:
                q_struct = None

        # latest version per key wins (current belief). The max version
        # must be AUTHORITATIVE (from fact_slots), not relative to the
        # lexical candidates — a newer version that shares no tokens
        # with the query would otherwise let its superseded predecessor
        # leak back in as the answer.
        latest: dict[str, int] = defaultdict(int)
        for row in rows:
            k = (row.extra_data or {}).get("_key")
            if k:
                latest[k] = max(latest[k], (row.extra_data or {}).get("_version", 1))
        if latest:
            from domains.models.db_models import FactSlot
            async with self._sf() as s:
                r = await s.execute(
                    select(FactSlot.key, func.max(FactSlot.version))
                    .where(FactSlot.space_id == self.space_id,
                           FactSlot.key.in_(list(latest)))
                    .group_by(FactSlot.key))
                for key, maxv in r.all():
                    latest[key] = max(latest[key], int(maxv or 1))

        results: list[RecallResult] = []
        for row in rows:
            if row.speaker in exclude_speakers:
                continue
            if row.content.strip().endswith("?"):
                continue
            if row.content.strip().lower().rstrip("?.! ") == q_norm:
                continue
            k = (row.extra_data or {}).get("_key")
            if k and (row.extra_data or {}).get("_version", 1) < latest[k]:
                continue
            stored = self._to_thought(row)
            score, matched = score_thought(stored, q_tokens, q_struct)
            if score >= 0.05:
                results.append(RecallResult(thought=stored,
                                            global_similarity=score,
                                            matched=matched))
        results.sort(key=lambda r: r.global_similarity, reverse=True)
        return results[:top_k]

    async def stats(self) -> dict:
        from domains.models.db_models import AdaThought, FactSlot
        async with self._sf() as s:
            n = (await s.execute(
                select(func.count()).select_from(AdaThought)
                .where(AdaThought.space_id == self.space_id,
                       AdaThought.archived == 0))).scalar() or 0
            keys = (await s.execute(
                select(FactSlot.key, func.max(FactSlot.version))
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.key.is_not(None))
                .group_by(FactSlot.key))).all()
            fill = (await s.execute(
                select(FactSlot.layer, func.count(func.distinct(FactSlot.thought_id)))
                .where(FactSlot.space_id == self.space_id,
                       FactSlot.is_current == 1)
                .group_by(FactSlot.layer))).all()
        return {
            "count": int(n),
            "versioned_keys": len(keys),
            "multi_version_keys": sum(1 for _, v in keys if (v or 1) > 1),
            "layer_fill": {row[0]: int(row[1]) for row in fill},
            "storage": "sql",
        }

    @staticmethod
    def _to_thought(row) -> StoredThought:
        return StoredThought(
            thought_id=row.thought_id, content=row.content,
            speaker=row.speaker, space_id=row.space_id,
            created_at=row.created_at, last_accessed=row.last_accessed,
            access_count=row.access_count, metadata=row.extra_data or {},
        )
