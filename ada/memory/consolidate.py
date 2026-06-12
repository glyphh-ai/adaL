"""
Consolidation — the offline maintenance pass over a space's memory.

A janitor, not a dream. Three deterministic passes over stored facts,
run at rest (never in the answer path):

  P1  re-enrichment        facts with no universal slots get another
                           pass through the enricher (LLM if a key is
                           present, regex fallback if not)
  P2  retroactive identity facts written in the first person before the
                           speaker was known get their entity resolved
                           to the operator-supplied `me` — the same
                           rewrite tell does at write time today
  P3  near-duplicate       unkeyed facts that differ by one misspelled
      supersession         token ("branid"/"brandi") — the newer fact
                           wins, the older is archived out of recall

Content is never rewritten — facts are receipts. Only the structured
slot fill (and the archived flag) changes. Every change is counted and
reported; dry_run previews without writing.

Shipped behind a pre-registered eval (benchmark/consolidation/): if
consolidation can't beat doing nothing on the conversational ask set,
it doesn't run by default.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

_MIN_TOKEN_LEN = 4   # don't fuzzy-match short tokens ("is"/"in")
_MAX_EDIT = 2        # branid → brandi is 2 plain edits (1 transposition)


def _edit_distance(a: str, b: str, cap: int = _MAX_EDIT) -> int:
    """Plain Levenshtein with an early-out cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            c = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(c)
            best = min(best, c)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _near_duplicate(tokens_a: list[str], tokens_b: list[str]) -> bool:
    """Same shape, exactly one token pair differing by ≤2 edits."""
    if len(tokens_a) != len(tokens_b) or not tokens_a:
        return False
    diffs = [(x, y) for x, y in zip(tokens_a, tokens_b) if x != y]
    if len(diffs) != 1:
        return False
    x, y = diffs[0]
    if min(len(x), len(y)) < _MIN_TOKEN_LEN:
        return False
    return _edit_distance(x, y) <= _MAX_EDIT


async def consolidate(
    session_factory: Any,
    space_id: str = "main",
    me: Optional[str] = None,
    enricher: Any = None,
    dry_run: bool = False,
) -> dict:
    """Run the consolidation passes over one space. Returns the report."""
    from datetime import datetime

    from domains.models.db_models import AdaThought, FactSlot
    from ada.memory.thought_persistence import save_thought
    from ada.memory.thought_space import (StoredThought, _resolve_speaker_entity,
                                          _sanitize_universal, _tokenize)

    async with session_factory() as s:
        rows = (await s.execute(
            select(AdaThought).where(AdaThought.space_id == space_id,
                                     AdaThought.archived == 0))).scalars().all()

    report: dict = {
        "space": space_id, "scanned": len(rows), "dry_run": dry_run,
        "re_enriched": 0, "identity_resolved": 0,
        "duplicates_archived": [], "questions_skipped": 0,
    }

    thoughts: list[StoredThought] = []
    changed: set[str] = set()
    for row in rows:
        meta = dict(row.extra_data or {})
        thoughts.append(StoredThought(
            thought_id=row.thought_id, content=row.content,
            speaker=row.speaker, space_id=row.space_id or space_id,
            created_at=row.created_at, metadata=meta))

    for t in thoughts:
        if t.content.strip().endswith("?"):
            report["questions_skipped"] += 1  # never ground recall anyway
            continue

        # P1 — re-enrich facts that never got universal slots
        u = t.metadata.get("_universal") or {}
        if not u and enricher is not None:
            try:
                fresh = enricher.universal(t.content)
            except Exception:
                fresh = None
            if fresh:
                u = _sanitize_universal(fresh)
                if u:
                    t.metadata["_universal"] = u
                    changed.add(t.thought_id)
                    report["re_enriched"] += 1

        # P2 — retroactive speaker resolution (operator asserts identity)
        if me and u:
            resolved = _resolve_speaker_entity(t.content, u, me)
            if resolved != u:
                t.metadata["_universal"] = resolved
                changed.add(t.thought_id)
                report["identity_resolved"] += 1

    # P3 — near-duplicate supersession among unkeyed, non-question facts
    candidates = [t for t in thoughts
                  if not t.metadata.get("_key")
                  and not t.content.strip().endswith("?")]
    tokenized = {t.thought_id: _tokenize(t.content) for t in candidates}
    archived_ids: set[str] = set()
    for i, a in enumerate(candidates):
        if a.thought_id in archived_ids:
            continue
        for b in candidates[i + 1:]:
            if b.thought_id in archived_ids:
                continue
            ta, tb = tokenized[a.thought_id], tokenized[b.thought_id]
            exact = a.content.strip().lower() == b.content.strip().lower()
            if exact or _near_duplicate(ta, tb):
                older, newer = ((a, b) if a.created_at <= b.created_at
                                else (b, a))
                archived_ids.add(older.thought_id)
                report["duplicates_archived"].append({
                    "archived": older.content, "kept": newer.content,
                })
                if older.thought_id == a.thought_id:
                    break

    if dry_run:
        return report

    # write back: refreshed slot fills + archived duplicates
    for t in thoughts:
        if t.thought_id in changed and t.thought_id not in archived_ids:
            await save_thought(session_factory, t)
    if archived_ids:
        ids = list(archived_ids)
        async with session_factory() as s:
            from sqlalchemy import update
            await s.execute(update(AdaThought)
                            .where(AdaThought.thought_id.in_(ids))
                            .values(archived=1))
            await s.execute(update(FactSlot)
                            .where(FactSlot.thought_id.in_(ids))
                            .values(is_current=0))
            await s.commit()
    logger.info("consolidate(%s): %d re-enriched, %d identity-resolved, "
                "%d duplicates archived", space_id, report["re_enriched"],
                report["identity_resolved"], len(report["duplicates_archived"]))
    return report


# ── Entity alias merging — proposals, never auto-merge ────────────────
#
# Detection is deterministic (name similarity + shared slot evidence)
# and only ever PROPOSES. Merging is an operator decision: ada refuses
# to guess that two names are one entity.

async def _entity_profiles_db(session_factory, space_id: str) -> dict:
    """entity -> {'layer.role=value', ...} over current rows."""
    from collections import defaultdict as dd
    from domains.models.db_models import FactSlot
    async with session_factory() as s:
        r = await s.execute(
            select(FactSlot.entity, FactSlot.layer, FactSlot.role,
                   FactSlot.value)
            .where(FactSlot.space_id == space_id,
                   FactSlot.is_current == 1,
                   FactSlot.entity.isnot(None)))
        rows = r.all()
    profiles: dict = dd(set)
    for entity, layer, role, value in rows:
        if layer != "_meta":
            profiles[entity].add(f"{layer}.{role}={value}")
    return dict(profiles)


def _names_alike(a: str, b: str) -> bool:
    """Misspelling-distance OR containment ('bob' in 'bob smith')."""
    if min(len(a), len(b)) >= _MIN_TOKEN_LEN and _edit_distance(a, b) <= _MAX_EDIT:
        return True
    ta, tb = set(a.split()), set(b.split())
    return bool(ta and tb) and (ta <= tb or tb <= ta) and a != b


async def merge_candidates(session_factory, space_id: str = "main",
                           limit: int = 25) -> list[dict]:
    """Deterministic alias proposals: name-alike entity pairs with
    their shared-value evidence and conflicts. Read-only."""
    profiles = await _entity_profiles_db(session_factory, space_id)
    names = sorted(profiles)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not _names_alike(a, b):
                continue
            # exclude self-referential slot values (entity.name=a etc.)
            pa = {v for v in profiles[a] if not v.startswith("entity.name=")}
            pb = {v for v in profiles[b] if not v.startswith("entity.name=")}
            shared = sorted(pa & pb)
            # conflict: same single-valued slot, different values
            slots_a = {v.split("=", 1)[0]: v for v in pa}
            slots_b = {v.split("=", 1)[0]: v for v in pb}
            conflicts = sorted(
                f"{slots_a[k]} vs {slots_b[k].split('=', 1)[1]}"
                for k in slots_a.keys() & slots_b.keys()
                if slots_a[k] != slots_b[k])
            out.append({
                "a": a, "b": b,
                "shared": shared, "conflicts": conflicts,
                "score": round(len(shared) / max(1, len(pa | pb)), 3),
            })
    out.sort(key=lambda c: (-len(c["shared"]), len(c["conflicts"])))
    return out[:limit]


async def merge_entities(session_factory, space_id: str, source: str,
                         target: str, dry_run: bool = True) -> dict:
    """Merge `source` into `target`: re-point slot rows and rewrite
    universal entity references. Content stays verbatim — the original
    sentence is a receipt; only the structured identity changes."""
    from sqlalchemy import update
    from domains.models.db_models import AdaThought, FactSlot
    source, target = source.strip().lower(), target.strip().lower()
    if not source or not target or source == target:
        return {"error": "merge needs two different entity names"}

    async with session_factory() as s:
        r = await s.execute(
            select(FactSlot.thought_id).distinct()
            .where(FactSlot.space_id == space_id,
                   FactSlot.entity == source))
        ids = [row[0] for row in r.all()]
    report = {"space": space_id, "source": source, "target": target,
              "facts": len(ids), "dry_run": dry_run}
    if dry_run or not ids:
        if dry_run:
            report["note"] = ("dry run — nothing changed; confirm to merge")
        return report

    async with session_factory() as s:
        await s.execute(update(FactSlot)
                        .where(FactSlot.space_id == space_id,
                               FactSlot.entity == source)
                        .values(entity=target))
        r = await s.execute(select(AdaThought).where(
            AdaThought.thought_id.in_(ids)))
        for row in r.scalars().all():
            import copy
            # deep copy: mutating shared nested dicts in place would
            # defeat SQLAlchemy's JSON change detection
            meta = copy.deepcopy(dict(row.extra_data or {}))
            u = meta.get("_universal")
            if not isinstance(u, dict):
                continue
            changed = False
            ent = u.get("entity")
            if isinstance(ent, dict) and \
                    str(ent.get("name", "")).strip().lower() == source:
                ent["name"] = target
                changed = True
            rel = u.get("relational")
            if isinstance(rel, dict):
                for k in ("subject", "object", "possessor", "agent"):
                    if str(rel.get(k, "")).strip().lower() == source:
                        rel[k] = target
                        changed = True
            if changed:
                row.extra_data = meta
        await s.commit()
    logger.info("merged entity %r into %r (%d facts)", source, target,
                len(ids))
    return report
