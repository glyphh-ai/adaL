"""SqlFactStore parity + scoping + speaker resolution (offline, sqlite)."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ada.cognitive.ops import execute_op
from ada.memory.sql_store import SqlFactStore
from ada.memory.thought_space import ThoughtSpace


async def _make_sql(tmp_path, space_id="main"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot, Token  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return SqlFactStore(sf, space_id=space_id), sf


CORPUS = [
    ({"entity": {"name": "Ann", "kind": "person"}, "spatial": {"location": "Boston"}}, None),
    ({"entity": {"name": "Ann"}, "relational": {"subject": "Ann", "predicate": "works_as", "object": "doctor"}}, None),
    ({"entity": {"name": "Bo", "kind": "person"}, "spatial": {"location": "Boston"}}, None),
    ({"entity": {"name": "Bo"}, "relational": {"subject": "Bo", "predicate": "works_as", "object": "engineer"}}, None),
    ({"entity": {"name": "Cy", "kind": "person"}, "spatial": {"location": "Denver"}}, None),
]


def _fill_memory() -> ThoughtSpace:
    s = ThoughtSpace()
    for facts, key in CORPUS:
        s.tell_raw(facts=facts, key=key)
    return s


async def _fill_sql(store):
    for facts, key in CORPUS:
        await store.tell_raw(facts=facts, key=key)


# ── Parity: memory and SQL give identical op answers ──────────────────

OPS = [
    {"op": "count", "conditions": {"spatial.location": "boston"}},
    {"op": "who", "conditions": {"spatial.location": "boston",
                                 "relational.object": "engineer"}},
    {"op": "top", "slot": "relational.object", "predicate_contains": "work"},
    {"op": "count_not", "slot": "spatial.location", "value": "boston"},
    {"op": "compare", "slot": "spatial.location", "a": "boston", "b": "denver"},
    {"op": "lookup", "person": "Ann", "slot": "spatial.location"},
]


def test_memory_sql_parity(tmp_path):
    mem = _fill_memory()

    async def run():
        store, _ = await _make_sql(tmp_path)
        await _fill_sql(store)
        for op in OPS:
            sql_ans = await store.execute_op(op)
            mem_ans = execute_op(mem, op)
            assert sql_ans == mem_ans, (op, sql_ans, mem_ans)
    asyncio.run(run())


def test_sql_versioning_current_belief(tmp_path):
    async def run():
        store, _ = await _make_sql(tmp_path)
        await store.tell_raw(facts={"entity": {"name": "Carol"},
                                    "spatial": {"location": "Austin"}}, key="carol.loc")
        await store.tell_raw(facts={"entity": {"name": "Carol"},
                                    "spatial": {"location": "Denver"}}, key="carol.loc")
        assert await store.count_where("spatial", "location", "austin") == 0
        assert await store.count_where("spatial", "location", "denver") == 1
        h = await store.history("carol.loc")
        assert [t.metadata["_version"] for t in h] == [1, 2]
        assert await store.previous_value("Carol", "spatial.location") == "austin"
    asyncio.run(run())


def test_sql_space_isolation(tmp_path):
    async def run():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/iso.db")
        sf = async_sessionmaker(engine, expire_on_commit=False)
        from infrastructure.database.connection import Base
        from domains.models.db_models import AdaThought, FactSlot, Token  # noqa
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        acme = SqlFactStore(sf, space_id="acme")
        beta = SqlFactStore(sf, space_id="beta")
        await acme.tell_raw(facts={"entity": {"name": "X"}, "spatial": {"location": "Boston"}})
        await acme.tell_raw(facts={"entity": {"name": "Y"}, "spatial": {"location": "Boston"}})
        await beta.tell_raw(facts={"entity": {"name": "Z"}, "spatial": {"location": "Boston"}})
        assert await acme.count_where("spatial", "location", "boston") == 2
        assert await beta.count_where("spatial", "location", "boston") == 1
    asyncio.run(run())


def test_keyed_slotless_fact_survives_restart(tmp_path):
    """A keyed fact whose enrichment produced NO universal slots must
    still appear in keyed_facts — including from a fresh store instance
    (the restart case). Guards the _meta marker row."""
    async def run():
        store, sf = await _make_sql(tmp_path)
        await store.absorb("The Acme engagement is in discovery.",
                           key="acme.status")
        await store.absorb("The Acme engagement is now active.",
                           key="acme.status")
        # same DB, fresh store — what a server restart sees
        fresh = SqlFactStore(sf, space_id="main")
        facts = await fresh.keyed_facts()
        assert [f["key"] for f in facts] == ["acme.status"]
        assert facts[0]["version"] == 2
        assert "active" in facts[0]["content"]
        h = await fresh.history("acme.status")
        assert [t.metadata["_version"] for t in h] == [1, 2]
    asyncio.run(run())


def test_sql_recall_never_surfaces_superseded(tmp_path):
    """A superseded version must not come back from recall even when
    the CURRENT version shares no tokens with the query — the max
    version is authoritative, not candidate-relative."""
    async def run():
        store, _ = await _make_sql(tmp_path)
        await store.absorb("The Acme engagement is now active.",
                           key="acme.status")
        await store.absorb("The renewal just closed.", key="acme.status")
        # query matches v1's tokens only; v1 is superseded → no keyed hit
        results = await store.recall("acme engagement", top_k=5)
        keyed = [r for r in results
                 if r.thought.metadata.get("_key") == "acme.status"]
        assert all("renewal" in r.thought.content for r in keyed), \
            [r.thought.content for r in keyed]
    asyncio.run(run())


def test_keyed_facts_parity(tmp_path):
    """keys (the workbench slot grid): current belief per key, both modes."""
    mem = ThoughtSpace()
    mem.tell_raw(facts={"entity": {"name": "Carol"},
                        "spatial": {"location": "Austin"}}, key="carol.loc")
    mem.tell_raw(facts={"entity": {"name": "Carol"},
                        "spatial": {"location": "Denver"}}, key="carol.loc")
    mem.tell_raw(facts={"entity": {"name": "Dan"},
                        "quantitative": {"age": "40"}}, key="dan.age")
    mem.tell_raw(facts={"entity": {"name": "Eve"}})  # unkeyed → not listed

    async def run():
        store, _ = await _make_sql(tmp_path)
        await store.tell_raw(facts={"entity": {"name": "Carol"},
                                    "spatial": {"location": "Austin"}}, key="carol.loc")
        await store.tell_raw(facts={"entity": {"name": "Carol"},
                                    "spatial": {"location": "Denver"}}, key="carol.loc")
        await store.tell_raw(facts={"entity": {"name": "Dan"},
                                    "quantitative": {"age": "40"}}, key="dan.age")
        await store.tell_raw(facts={"entity": {"name": "Eve"}})

        for facts in (mem.keyed_facts(), await store.keyed_facts()):
            by_key = {f["key"]: f for f in facts}
            assert set(by_key) == {"carol.loc", "dan.age"}
            assert by_key["carol.loc"]["version"] == 2
            assert "denver" in by_key["carol.loc"]["content"].lower()
            assert by_key["dan.age"]["version"] == 1
    asyncio.run(run())


# ── Speaker-entity resolution ─────────────────────────────────────────

def test_speaker_resolution_memory():
    from ada.memory.thought_space import _resolve_speaker_entity, _sanitize_universal
    # "i am married to brandi" — subject is first-person → resolves to chris
    clean = _sanitize_universal({
        "entity": {"name": "I"},
        "relational": {"subject": "I", "predicate": "married_to", "object": "brandi"}})
    out = _resolve_speaker_entity("i am married to brandi", clean, "chris")
    assert out["entity"]["name"] == "chris"
    assert out["relational"]["subject"] == "chris"


def test_speaker_resolution_skips_third_person():
    from ada.memory.thought_space import _resolve_speaker_entity, _sanitize_universal
    clean = _sanitize_universal({
        "entity": {"name": "Bob"}, "spatial": {"location": "Denver"}})
    out = _resolve_speaker_entity("bob lives in denver", clean, "chris")
    assert out["entity"]["name"] == "Bob"  # untouched — no first-person token


def test_children_chain_via_entity_join():
    # The who-are-my-children scenario, resolved at write time.
    from ada.memory.thought_space import ThoughtSpace, _resolve_speaker_entity, _sanitize_universal
    s = ThoughtSpace()
    # chris's fact about brandi (resolved): entity=chris won't hold children;
    # the join is chris -> brandi (object) -> brandi's children.
    s.tell_raw(facts=_resolve_speaker_entity(
        "i am married to brandi",
        _sanitize_universal({"entity": {"name": "I"},
                             "relational": {"subject": "I", "predicate": "married_to",
                                            "object": "brandi"}}),
        "chris"))
    s.tell_raw(facts={"entity": {"name": "brandi"},
                      "relational": {"subject": "brandi", "predicate": "has_children",
                                     "object": "traceton"}})
    # chris is married to brandi (entity chris, object brandi)
    assert "chris" in s.entities_where({"relational.object": "brandi"})
    # brandi has traceton
    assert "brandi" in s.entities_where({"relational.object": "traceton"})
