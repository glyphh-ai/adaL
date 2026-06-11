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


async def load_thoughts(session_factory: Any, space: ThoughtSpace) -> int:
    """Load all non-archived thoughts from the DB into `space`.

    Restores the in-memory store, the dedup set, and the versioned-concept
    history chains. Returns the count loaded.
    """
    from domains.models.db_models import AdaThought

    async with session_factory() as session:
        result = await session.execute(
            select(AdaThought).where(AdaThought.archived == 0)
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
    """Persist a thought (content + structured metadata)."""
    from domains.models.db_models import AdaThought

    async with session_factory() as session:
        row = AdaThought(
            thought_id=thought.thought_id,
            content=thought.content,
            speaker=thought.speaker,
            access_count=thought.access_count,
            created_at=thought.created_at,
            last_accessed=thought.last_accessed,
            extra_data=_json_safe_meta(thought.metadata),
            archived=0,
        )
        await session.merge(row)  # upsert by primary key — idempotent re-saves
        await session.commit()


async def archive_thought(session_factory: Any, thought_id: str) -> None:
    """Mark a thought as archived."""
    from domains.models.db_models import AdaThought

    async with session_factory() as session:
        await session.execute(
            update(AdaThought).where(AdaThought.thought_id == thought_id).values(archived=1)
        )
        await session.commit()
