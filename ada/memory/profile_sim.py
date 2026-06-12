"""
Profile similarity and drift — exact math on the vectors ada already
stores.

An entity's profile IS a sparse binary vector: one dimension per
slot=value fill in fact_slots. Similarity is Jaccard on those exact
dimensions; drift is the same distance taken across time windows plus
version churn on the entity's keys. No projections, no embeddings —
every score decomposes into named slot movements (receipts).

Candidate generation is bounded by construction: similar() only
considers entities sharing at least one indexed slot=value with the
target, capped per dimension and in total — the same discipline as the
closed ops, usable at any store size.

Boundary stated plainly: drift here is DESCRIPTIVE measurement. Using
it to claim churn prediction requires the pre-registered eval in the
task record before any such claim ships.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)

_DIM_CAP = 60          # target profile dims used for candidate lookups
_PER_DIM_CAP = 500     # candidate entities fetched per dimension
_CANDIDATE_CAP = 5000  # total candidate pool


async def _profile(s, space_id: str, name: str, current_only: bool = True
                   ) -> set[str]:
    from domains.models.db_models import FactSlot
    q = select(FactSlot.layer, FactSlot.role, FactSlot.value).where(
        FactSlot.space_id == space_id, FactSlot.entity == name,
        FactSlot.layer != "_meta")
    if current_only:
        q = q.where(FactSlot.is_current == 1)
    rows = (await s.execute(q)).all()
    return {f"{l}.{r}={v}" for l, r, v in rows}


async def similar_entities(session_factory, space_id: str, name: str,
                           k: int = 5) -> dict:
    """k nearest entities by exact Jaccard over current profiles."""
    from domains.models.db_models import FactSlot
    name = name.strip().lower()
    async with session_factory() as s:
        target = await _profile(s, space_id, name)
        if not target:
            return {"error": f"no such entity: {name}"}

        candidates: set[str] = set()
        for dim in sorted(target)[:_DIM_CAP]:
            lr, _, value = dim.partition("=")
            layer, _, role = lr.partition(".")
            r = await s.execute(
                select(FactSlot.entity).distinct()
                .where(FactSlot.space_id == space_id,
                       FactSlot.layer == layer, FactSlot.role == role,
                       FactSlot.value == value,
                       FactSlot.is_current == 1,
                       FactSlot.entity.isnot(None),
                       FactSlot.entity != name)
                .limit(_PER_DIM_CAP))
            candidates |= {row[0] for row in r.all()}
            if len(candidates) >= _CANDIDATE_CAP:
                break

        scored = []
        for other in sorted(candidates)[:_CANDIDATE_CAP]:
            prof = await _profile(s, space_id, other)
            inter = target & prof
            if not inter:
                continue
            union = target | prof
            scored.append({
                "name": other,
                "similarity": round(len(inter) / len(union), 3),
                "shared": sorted(inter),
            })
        scored.sort(key=lambda e: -e["similarity"])
    return {"entity": name, "space": space_id,
            "profile_dims": len(target),
            "candidates_considered": len(candidates),
            "similar": scored[:k]}


async def entity_drift(session_factory, space_id: str, name: str,
                       window_days: int = 30) -> dict:
    """Profile change over the trailing window, decomposed into
    receipts: dimensions added, dimensions dropped (superseded by an
    in-window successor), and which keys churned. The clock is the
    store's own latest write for this entity, so the measure is stable
    against quiet periods."""
    from domains.models.db_models import AdaThought, FactSlot
    name = name.strip().lower()
    window = window_days * 86400
    async with session_factory() as s:
        r = await s.execute(
            select(FactSlot.thought_id).distinct()
            .where(FactSlot.space_id == space_id,
                   FactSlot.entity == name))
        ids = [row[0] for row in r.all()]
        if not ids:
            return {"error": f"no such entity: {name}"}
        r = await s.execute(
            select(AdaThought.thought_id, AdaThought.created_at)
            .where(AdaThought.thought_id.in_(ids)))
        created = dict(r.all())
        now = max(created.values())
        cutoff = now - window
        recent_ids = [t for t, c in created.items() if c > cutoff]
        baseline_ids = [t for t, c in created.items() if c <= cutoff]
        if not baseline_ids:
            # everything the store knows about this entity is younger
            # than the window — there is no baseline to drift FROM
            return {"entity": name, "space": space_id,
                    "window_days": window_days, "drift": 0.0,
                    "added": [], "dropped": [], "churned_keys": [],
                    "facts_in_window": len(recent_ids),
                    "profile_dims": len(await _profile(s, space_id, name)),
                    "note": "no baseline older than the window"}

        current = await _profile(s, space_id, name)

        # added: current dims contributed by in-window facts
        added: set[str] = set()
        if recent_ids:
            r = await s.execute(
                select(FactSlot.layer, FactSlot.role, FactSlot.value)
                .where(FactSlot.space_id == space_id,
                       FactSlot.thought_id.in_(recent_ids),
                       FactSlot.is_current == 1,
                       FactSlot.layer != "_meta"))
            added = {f"{l}.{r_}={v}" for l, r_, v in r.all()}

        # churned keys: a new version arrived in-window; dropped dims
        # are the superseded predecessors' fills
        churned: list[str] = []
        dropped: set[str] = set()
        if recent_ids:
            r = await s.execute(
                select(FactSlot.key).distinct()
                .where(FactSlot.space_id == space_id,
                       FactSlot.thought_id.in_(recent_ids),
                       FactSlot.key.isnot(None),
                       FactSlot.version > 1))
            churned = sorted(row[0] for row in r.all())
            if churned:
                r = await s.execute(
                    select(FactSlot.layer, FactSlot.role, FactSlot.value)
                    .where(FactSlot.space_id == space_id,
                           FactSlot.key.in_(churned),
                           FactSlot.is_current == 0,
                           FactSlot.layer != "_meta"))
                dropped = {f"{l}.{r_}={v}" for l, r_, v in r.all()} - current

    moved = len(added) + len(dropped)
    denom = len(current) + len(dropped)
    return {
        "entity": name, "space": space_id, "window_days": window_days,
        "drift": round(moved / denom, 3) if denom else 0.0,
        "added": sorted(added),
        "dropped": sorted(dropped),
        "churned_keys": churned,
        "facts_in_window": len(recent_ids),
        "profile_dims": len(current),
    }
