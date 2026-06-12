"""Profile similarity + drift: exact Jaccard, windowed receipts."""

import asyncio
import time

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ada.memory.profile_sim import entity_drift, similar_entities


async def _make_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/ps.db")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sf


async def _fact(sf, tid, content, universal, created, key=None, version=1,
                is_current=1):
    from ada.memory.thought_persistence import slot_rows
    from ada.memory.thought_space import StoredThought
    from domains.models.db_models import AdaThought
    meta = {"_universal": universal}
    if key:
        meta["_key"], meta["_version"] = key, version
    async with sf() as s:
        s.add(AdaThought(thought_id=tid, content=content, speaker="incoming",
                         space_id="main", created_at=created,
                         last_accessed=created, extra_data=meta))
        st = StoredThought(thought_id=tid, content=content,
                           speaker="incoming", space_id="main", metadata=meta)
        for sr in slot_rows(st):
            sr["is_current"] = is_current
            await s.execute(text(
                "INSERT INTO fact_slots (space_id,thought_id,entity,layer,"
                "role,value,predicate,key,version,is_current) VALUES "
                "(:space_id,:thought_id,:entity,:layer,:role,:value,"
                ":predicate,:key,:version,:is_current)"), sr)
        await s.commit()


def _person(name, city, job):
    return {"entity": {"name": name, "kind": "person"},
            "spatial": {"location": city},
            "relational": {"subject": name, "predicate": "works_as",
                           "object": job}}


def test_similar_ranking(tmp_path):
    async def run():
        sf = await _make_db(tmp_path)
        t0 = time.time()
        await _fact(sf, "a", "ann ...", _person("ann", "boston", "engineer"), t0)
        await _fact(sf, "b", "bo ...", _person("bo", "boston", "engineer"), t0)
        await _fact(sf, "c", "cy ...", _person("cy", "boston", "chef"), t0)
        await _fact(sf, "d", "dee ...", _person("dee", "tulsa", "florist"), t0)

        out = await similar_entities(sf, "main", "ann", k=3)
        names = [e["name"] for e in out["similar"]]
        # bo shares city+job (+kind/predicate) > cy shares city only;
        # dee shares only kind/predicate
        assert names[0] == "bo"
        assert names.index("bo") < names.index("cy")
        assert "spatial.location=boston" in out["similar"][0]["shared"]
        assert (await similar_entities(sf, "main", "ghost"))["error"]
    asyncio.run(run())


def test_drift_receipts(tmp_path):
    async def run():
        sf = await _make_db(tmp_path)
        now = time.time()
        old = now - 60 * 86400
        # acme: stable old fact + an in-window supersession + new fill
        await _fact(sf, "a1", "acme is in boston",
                    {"entity": {"name": "acme"},
                     "spatial": {"location": "boston"}}, old)
        await _fact(sf, "a2", "acme tier is gold",
                    {"entity": {"name": "acme"},
                     "quantitative": {"amount": "gold"}}, old,
                    key="acme.tier", version=1, is_current=0)
        await _fact(sf, "a3", "acme tier is silver",
                    {"entity": {"name": "acme"},
                     "quantitative": {"amount": "silver"}}, now - 86400,
                    key="acme.tier", version=2)
        await _fact(sf, "a4", "acme opened a ticket",
                    {"entity": {"name": "acme"},
                     "relational": {"subject": "acme", "predicate": "opened",
                                    "object": "ticket"}}, now - 3600)

        out = await entity_drift(sf, "main", "acme", window_days=30)
        assert out["churned_keys"] == ["acme.tier"]
        assert "quantitative.amount=gold" in out["dropped"]
        assert "quantitative.amount=silver" in out["added"]
        assert any("ticket" in d for d in out["added"])
        assert out["drift"] > 0.3
        assert out["facts_in_window"] == 2

        # steady entity: zero drift
        await _fact(sf, "b1", "bo lives in tulsa",
                    {"entity": {"name": "bo"},
                     "spatial": {"location": "tulsa"}}, old)
        steady = await entity_drift(sf, "main", "bo", window_days=30)
        assert steady["drift"] == 0.0
        assert steady["added"] == [] and steady["dropped"] == []
    asyncio.run(run())
