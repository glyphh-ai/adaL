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
