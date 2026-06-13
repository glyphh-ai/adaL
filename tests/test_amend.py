"""amend: edit a fact in place, preserving version + chain position."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ada.memory.sql_store import SqlFactStore
from ada.memory.thought_persistence import amend_thought


async def _make(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/a.db")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot  # noqa
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return SqlFactStore(sf, space_id="main"), sf


def test_amend_in_place_preserves_chain(tmp_path):
    async def run():
        store, sf = await _make(tmp_path)
        # v1 then v2 of acme.status
        await store.absorb("Acme is in dicsovery.", key="acme.status")  # typo
        await store.absorb("Acme is now active.", key="acme.status")
        hist = await store.history("acme.status")
        v1 = next(t for t in hist if t.metadata["_version"] == 1)
        v2 = next(t for t in hist if t.metadata["_version"] == 2)

        # fix v1's typo IN PLACE — no new version
        out = await amend_thought(sf, "main", v1.thought_id,
                                  text="Acme is in discovery.")
        assert out["version"] == 1
        hist2 = await store.history("acme.status")
        assert [t.metadata["_version"] for t in hist2] == [1, 2]  # still 2
        v1b = next(t for t in hist2 if t.metadata["_version"] == 1)
        assert v1b.content == "Acme is in discovery."  # corrected
        assert v1b.thought_id == v1.thought_id          # same id

        # current belief is still v2 — editing v1 didn't disturb is_current
        from domains.models.db_models import FactSlot
        async with sf() as s:
            cur = (await s.execute(select(FactSlot.version).where(
                FactSlot.space_id == "main", FactSlot.key == "acme.status",
                FactSlot.is_current == 1))).scalars().all()
        assert cur and all(v == 2 for v in cur)

        # amend slots in place on the current version
        out = await amend_thought(sf, "main", v2.thought_id,
                                  universal={"entity": {"name": "acme"},
                                             "relational": {"subject": "acme",
                                                            "predicate": "status",
                                                            "object": "active"}})
        assert out["version"] == 2
        async with sf() as s:
            rows = (await s.execute(select(FactSlot).where(
                FactSlot.thought_id == v2.thought_id))).scalars().all()
        vals = {(r.layer, r.role, r.value) for r in rows}
        assert ("relational", "object", "active") in vals
        assert all(r.is_current == 1 for r in rows)  # current stays current

        # unknown thought_id → None
        assert await amend_thought(sf, "main", "nope", text="x") is None
    asyncio.run(run())
