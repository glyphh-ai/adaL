"""
Thought persistence — saves and restores Ada's memories from the DB.

ThoughtSpace stays in-memory for fast queries. This module syncs it
to/from the database:

  - Boot: load all non-archived thoughts (content + metadata, including
    the universal-schema slots) and rebuild version chains.
  - Absorb: write new thoughts via the background persistence worker.
  - Archive: set archived=1, keep in DB for restoration.

A thought is fully reconstructable from (content, speaker, metadata) —
there is no derived state to rebuild.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401  (type hint reference)

from ada.memory.thought_space import StoredThought, ThoughtSpace

logger = logging.getLogger(__name__)


def slot_rows(thought: "StoredThought") -> list[dict]:
    """Decompose a thought's universal slots into fact_slots rows.
    The single source of the slot-row shape — used by save_thought and
    any backfill."""
    u = thought.metadata.get("_universal") or {}
    if not isinstance(u, dict):
        u = {}
    entity = None
    ent = u.get("entity")
    if isinstance(ent, dict) and ent.get("name"):
        entity = str(ent["name"]).strip().lower()
    rel = u.get("relational")
    predicate = None
    if isinstance(rel, dict):
        if not entity and rel.get("subject"):
            entity = str(rel["subject"]).strip().lower()
        if rel.get("predicate"):
            predicate = str(rel["predicate"]).strip().lower()
    rows = []
    for layer, roles in u.items():
        if not isinstance(roles, dict):
            continue
        for role, v in roles.items():
            if v is None or not str(v).strip():
                continue
            rows.append({
                "space_id": getattr(thought, "space_id", "main"),
                "thought_id": thought.thought_id,
                "entity": entity,
                "layer": layer,
                "role": role,
                "value": str(v).strip().lower(),
                "predicate": predicate,
                "key": thought.metadata.get("_key"),
                "version": thought.metadata.get("_version", 1),
                "is_current": 1,
            })
    # A keyed thought whose enrichment produced no slots still needs a
    # row — otherwise the indexed key listing (keyed_facts) and
    # supersession can't see it. The _meta layer can't collide with
    # universal-schema layers, so the closed ops ignore it by
    # construction.
    if not rows and thought.metadata.get("_key"):
        rows.append({
            "space_id": getattr(thought, "space_id", "main"),
            "thought_id": thought.thought_id,
            "entity": None,
            "layer": "_meta",
            "role": "key",
            "value": str(thought.metadata["_key"]).lower(),
            "predicate": None,
            "key": thought.metadata.get("_key"),
            "version": thought.metadata.get("_version", 1),
            "is_current": 1,
        })
    return rows


def _json_safe_meta(meta: dict) -> dict:
    """Drop values that aren't JSON-serializable."""
    safe: dict[str, Any] = {}
    for k, v in (meta or {}).items():
        if isinstance(v, (str, int, float, bool, type(None))):
            safe[k] = v
        elif isinstance(v, (list, dict)):
            try:
                json.dumps(v)
                safe[k] = v
            except (TypeError, ValueError):
                continue
        # Anything else (e.g. a StructuredFact) is recomputable — skip.
    return safe


# ── Persistence operations ───────────────────────────────────────────────────

async def count_thoughts(session_factory: Any) -> int:
    """Number of non-archived persisted thoughts (for store-once checks)."""
    from domains.models.db_models import AdaThought

    async with session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(AdaThought).where(AdaThought.archived == 0)
        )
        return int(result.scalar() or 0)


async def load_thoughts(session_factory: Any, space: ThoughtSpace,
                        space_id: str = "main") -> int:
    """Load one space's non-archived thoughts from the DB into `space`.

    Restores the in-memory store, the dedup set, and the versioned-concept
    history chains. Returns the count loaded.
    """
    from domains.models.db_models import AdaThought

    async with session_factory() as session:
        result = await session.execute(
            select(AdaThought).where(AdaThought.archived == 0,
                                     AdaThought.space_id == space_id)
        )
        rows = result.scalars().all()

    # Map existing in-memory seeds by content so a persisted thought replaces
    # its seed instead of duplicating it (the server loads after seeding).
    seed_by_content = {t.content.strip().lower(): tid for tid, t in space._thoughts.items()}

    count = 0
    by_key: dict[str, list[StoredThought]] = {}
    for row in rows:
        # Drop a matching seed so the persisted version wins (no duplicate).
        dup_id = seed_by_content.pop(row.content.strip().lower(), None)
        if dup_id is not None and dup_id != row.thought_id:
            space._thoughts.pop(dup_id, None)

        stored = StoredThought(
            thought_id=row.thought_id,
            content=row.content,
            speaker=row.speaker,
            created_at=row.created_at,
            last_accessed=row.last_accessed,
            access_count=row.access_count,
            metadata=row.extra_data or {},
        )
        space._thoughts[row.thought_id] = stored
        space._absorbed_texts.add(row.content.strip().lower())

        key = (row.extra_data or {}).get("_key")
        if key is not None:
            by_key.setdefault(key, []).append(stored)
        count += 1

    # Rebuild version chains in version order.
    for key, chain in by_key.items():
        chain.sort(key=lambda t: t.metadata.get("_version", 1))
        space._history_by_key[key] = chain

    if count:
        logger.info("Loaded %d thoughts from database", count)
    return count


async def save_thought(session_factory: Any, thought: StoredThought) -> None:
    """Persist a thought (content + metadata) and its fact_slots rows.

    A new version of a key marks the prior versions' slot rows
    is_current=0 in the same transaction — SQL-mode reads answer over
    current belief without recomputation."""
    from sqlalchemy import delete as sa_delete
    from domains.models.db_models import AdaThought, FactSlot

    space_id = getattr(thought, "space_id", "main")
    async with session_factory() as session:
        row = AdaThought(
            thought_id=thought.thought_id,
            space_id=space_id,
            content=thought.content,
            speaker=thought.speaker,
            access_count=thought.access_count,
            created_at=thought.created_at,
            last_accessed=thought.last_accessed,
            extra_data=_json_safe_meta(thought.metadata),
            archived=0,
        )
        await session.merge(row)  # upsert by primary key — idempotent re-saves

        # Idempotent slot write: replace this thought's rows.
        await session.execute(
            sa_delete(FactSlot).where(FactSlot.thought_id == thought.thought_id))
        for sr in slot_rows(thought):
            session.add(FactSlot(**sr))

        key = thought.metadata.get("_key")
        version = thought.metadata.get("_version", 1)
        if key is not None and version > 1:
            await session.execute(
                update(FactSlot)
                .where(FactSlot.space_id == space_id,
                       FactSlot.key == key,
                       FactSlot.version < version)
                .values(is_current=0))
        await session.commit()


async def amend_thought(session_factory: Any, space_id: str, thought_id: str,
                        *, text: str | None = None,
                        universal: dict | None = None) -> dict | None:
    """Edit a fact IN PLACE — correct the record without versioning.

    Unlike save_thought (which supersedes a chain), this preserves the
    thought_id, key, version, and the row's is_current state: editing a
    superseded v1 keeps it superseded; editing the current version keeps
    it current. Use when a fact was recorded wrong, not when the world
    changed (that's a new `tell key=` version). Returns the updated
    fact, or None if the thought_id isn't in this space."""
    from sqlalchemy import delete as sa_delete, select, update
    from domains.models.db_models import AdaThought, FactSlot
    from ada.memory.thought_space import StoredThought, _sanitize_universal

    async with session_factory() as session:
        row = (await session.execute(select(AdaThought).where(
            AdaThought.thought_id == thought_id,
            AdaThought.space_id == space_id))).scalar_one_or_none()
        if row is None:
            return None
        # preserve this version's place in the chain
        cur = (await session.execute(select(FactSlot.is_current).where(
            FactSlot.thought_id == thought_id).limit(1))).scalar()
        is_current = 1 if cur is None else int(cur)

        meta = dict(row.extra_data or {})
        if universal is not None:
            meta["_universal"] = _sanitize_universal(universal)
        new_content = text if text is not None else row.content

        await session.execute(update(AdaThought)
                              .where(AdaThought.thought_id == thought_id)
                              .values(content=new_content,
                                      extra_data=_json_safe_meta(meta)))
        await session.execute(
            sa_delete(FactSlot).where(FactSlot.thought_id == thought_id))
        stored = StoredThought(thought_id=thought_id, content=new_content,
                               speaker=row.speaker, space_id=space_id,
                               metadata=meta)
        for sr in slot_rows(stored):
            sr["is_current"] = is_current   # don't disturb the chain
            session.add(FactSlot(**sr))
        await session.commit()
    return {"thought_id": thought_id, "content": new_content,
            "key": meta.get("_key"), "version": meta.get("_version")}


async def archive_thought(session_factory: Any, thought_id: str) -> None:
    """Mark a thought as archived."""
    from domains.models.db_models import AdaThought

    async with session_factory() as session:
        await session.execute(
            update(AdaThought).where(AdaThought.thought_id == thought_id).values(archived=1)
        )
        await session.commit()
