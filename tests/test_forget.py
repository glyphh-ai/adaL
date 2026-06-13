"""forget: hard-delete by key / thought_id / entity, dry-run safe."""

import asyncio
import time

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ada.memory.sql_store import SqlFactStore


async def _make(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/f.db")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot  # noqa: F401
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return SqlFactStore(sf, space_id="main"), sf


# forget resolves the same way the MCP handler does — replicate that
# resolution + delete here so the test exercises the real query shapes.
async def _forget(sf, space, *, key=None, thought_id=None, entity=None,
                  dry_run=True):
    from sqlalchemy import delete
    from domains.models.db_models import AdaThought, FactSlot
    async with sf() as s:
        if thought_id:
            ids = [r[0] for r in (await s.execute(
                select(AdaThought.thought_id).where(
                    AdaThought.thought_id == thought_id,
                    AdaThought.space_id == space))).all()]
        else:
            col = FactSlot.key if key else FactSlot.entity
            val = (key or entity).lower()
            ids = [r[0] for r in (await s.execute(
                select(FactSlot.thought_id).distinct().where(
                    FactSlot.space_id == space, col == val))).all()]
    if dry_run or not ids:
        return len(ids)
    async with sf() as s:
        await s.execute(delete(FactSlot).where(FactSlot.thought_id.in_(ids)))
        await s.execute(delete(AdaThought).where(AdaThought.thought_id.in_(ids)))
        await s.commit()
    return len(ids)


def test_forget_key_thought_entity(tmp_path):
    async def run():
        store, sf = await _make(tmp_path)
        # acme.status: two versions (a chain)
        await store.absorb("Acme is in discovery.", key="acme.status")
        await store.absorb("Acme is now active.", key="acme.status")
        # an unkeyed fact + an entity with two facts
        await store.tell_raw(facts={"entity": {"name": "bo"},
                                    "spatial": {"location": "reno"}})
        await store.tell_raw(facts={"entity": {"name": "bo"},
                                    "relational": {"subject": "bo",
                                                   "predicate": "works_as",
                                                   "object": "pilot"}})
        from domains.models.db_models import AdaThought

        async def thought_count():
            async with sf() as s:
                return len((await s.execute(select(AdaThought))).scalars().all())
        assert await thought_count() == 4

        # dry run touches nothing
        n = await _forget(sf, "main", key="acme.status", dry_run=True)
        assert n == 2 and await thought_count() == 4

        # forget the whole key chain
        assert await _forget(sf, "main", key="acme.status", dry_run=False) == 2
        assert await thought_count() == 2
        assert await store.history("acme.status") == []

        # forget an entity → both its facts gone
        assert await _forget(sf, "main", entity="bo", dry_run=False) == 2
        assert await thought_count() == 0
    asyncio.run(run())


def test_forget_single_thought(tmp_path):
    async def run():
        store, sf = await _make(tmp_path)
        t = await store.tell_raw(facts={"entity": {"name": "cy"},
                                        "spatial": {"location": "tulsa"}})
        await store.tell_raw(facts={"entity": {"name": "dee"},
                                    "spatial": {"location": "fargo"}})
        from domains.models.db_models import AdaThought, FactSlot
        assert await _forget(sf, "main", thought_id=t.thought_id,
                             dry_run=False) == 1
        async with sf() as s:
            left = (await s.execute(select(AdaThought))).scalars().all()
            slots = (await s.execute(select(FactSlot))).scalars().all()
        assert len(left) == 1 and left[0].content.startswith("dee")
        # the forgotten thought's slot rows are gone too
        assert all(fs.thought_id != t.thought_id for fs in slots)
    asyncio.run(run())
