"""Consolidation pass: re-enrichment, retroactive identity, typo-dup
supersession — against a throwaway SQLite DB."""

import asyncio
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ada.memory.consolidate import _near_duplicate, consolidate
from ada.memory.thought_space import _tokenize


def test_near_duplicate_rule():
    nd = lambda a, b: _near_duplicate(_tokenize(a), _tokenize(b))
    assert nd("my wifes name is branid", "my wifes name is brandi")
    assert not nd("my wifes name is brandi", "my wifes name is brandi")  # exact handled separately
    assert not nd("bo lives in boston", "ann lives in denver")
    assert not nd("i am happy", "i am hungry")  # short/different words
    assert not nd("the acme deal closed", "the acme deal closed today")  # shape differs


async def _make_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/c.db")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return sf


async def _seed(sf, rows):
    from domains.models.db_models import AdaThought
    async with sf() as s:
        t0 = time.time()
        for i, (content, meta) in enumerate(rows):
            s.add(AdaThought(thought_id=f"t{i}", content=content,
                             speaker="incoming", space_id="main",
                             created_at=t0 + i, last_accessed=t0 + i,
                             extra_data=meta or {}))
        await s.commit()


def test_merge_candidates_and_merge(tmp_path):
    async def run():
        from ada.memory.consolidate import merge_candidates, merge_entities
        sf = await _make_db(tmp_path)
        await _seed(sf, [
            ("bob lives in austin",
             {"_universal": {"entity": {"name": "bob"},
                             "spatial": {"location": "austin"}}}),
            ("bob smith works as an engineer",
             {"_universal": {"entity": {"name": "bob smith"},
                             "spatial": {"location": "austin"},
                             "relational": {"subject": "bob smith",
                                            "predicate": "works_as",
                                            "object": "engineer"}}}),
            ("rena lives in denver",
             {"_universal": {"entity": {"name": "rena"},
                             "spatial": {"location": "denver"}}}),
        ])
        # slot rows must exist for profiles — build them like save_thought
        from sqlalchemy import text
        from ada.memory.thought_persistence import slot_rows
        from ada.memory.thought_space import StoredThought
        from domains.models.db_models import AdaThought
        async with sf() as s:
            rows = (await s.execute(select(AdaThought))).scalars().all()
            for r in rows:
                st = StoredThought(thought_id=r.thought_id, content=r.content,
                                   speaker=r.speaker, space_id="main",
                                   metadata=dict(r.extra_data or {}))
                for sr in slot_rows(st):
                    await s.execute(text(
                        "INSERT INTO fact_slots (space_id,thought_id,entity,"
                        "layer,role,value,predicate,key,version,is_current) "
                        "VALUES (:space_id,:thought_id,:entity,:layer,:role,"
                        ":value,:predicate,:key,:version,:is_current)"), sr)
            await s.commit()

        cands = await merge_candidates(sf)
        assert len(cands) == 1
        c = cands[0]
        assert {c["a"], c["b"]} == {"bob", "bob smith"}
        assert "spatial.location=austin" in c["shared"]

        # dry run changes nothing
        dry = await merge_entities(sf, "main", "bob smith", "bob")
        assert dry["dry_run"] is True and dry["facts"] == 1
        from domains.models.db_models import FactSlot
        async with sf() as s:
            left = (await s.execute(select(FactSlot).where(
                FactSlot.entity == "bob smith"))).scalars().all()
        assert left

        # confirmed merge: slot rows re-pointed, universal rewritten,
        # content untouched
        real = await merge_entities(sf, "main", "bob smith", "bob",
                                    dry_run=False)
        assert real["facts"] == 1
        async with sf() as s:
            left = (await s.execute(select(FactSlot).where(
                FactSlot.entity == "bob smith"))).scalars().all()
            merged = (await s.execute(select(AdaThought).where(
                AdaThought.thought_id == "t1"))).scalar_one()
        assert not left
        assert merged.content == "bob smith works as an engineer"  # verbatim
        u = merged.extra_data["_universal"]
        assert u["entity"]["name"] == "bob"
        assert u["relational"]["subject"] == "bob"
    asyncio.run(run())


def test_consolidate_passes(tmp_path):
    async def run():
        sf = await _make_db(tmp_path)
        await _seed(sf, [
            # first-person facts with universal slots but no entity link
            ("i am married to brandi",
             {"_universal": {"relational": {"subject": "speaker",
                                            "predicate": "married_to",
                                            "object": "brandi"}}}),
            # slotless fact the heuristic enricher CAN parse
            ("my name is chris", {}),
            # typo + correction, both unkeyed
            ("my wifes name is branid", {}),
            ("my wifes name is brandi", {}),
            # a stored question — must be skipped
            ("who are my children?", {}),
            # clean third-person fact — must be untouched
            ("brandi has two children traceton and carson",
             {"_universal": {"entity": {"name": "brandi"},
                             "relational": {"subject": "brandi",
                                            "predicate": "has_children",
                                            "object": "traceton and carson"}}}),
        ])
        from ada.encoder.llm_enricher import HeuristicEnricher

        # dry run writes nothing
        dry = await consolidate(sf, me="chris",
                                enricher=HeuristicEnricher(), dry_run=True)
        assert dry["dry_run"] is True
        from domains.models.db_models import AdaThought
        async with sf() as s:
            n_archived = (await s.execute(select(AdaThought).where(
                AdaThought.archived == 1))).scalars().all()
        assert not n_archived

        report = await consolidate(sf, me="chris",
                                   enricher=HeuristicEnricher())
        assert report["scanned"] == 6
        assert report["questions_skipped"] == 1
        assert report["identity_resolved"] >= 1
        # the typo is archived, the correction kept
        assert len(report["duplicates_archived"]) == 1
        assert "branid" in report["duplicates_archived"][0]["archived"]
        assert "brandi" in report["duplicates_archived"][0]["kept"]

        async with sf() as s:
            rows = (await s.execute(select(AdaThought))).scalars().all()
        by_content = {r.content: r for r in rows}
        assert by_content["my wifes name is branid"].archived == 1
        assert by_content["my wifes name is brandi"].archived == 0
        # marriage fact now carries the chris entity
        u = by_content["i am married to brandi"].extra_data["_universal"]
        assert u["relational"]["subject"] == "chris"
        assert u.get("entity", {}).get("name") == "chris"
        # third-person fact untouched
        u3 = by_content["brandi has two children traceton and carson"].extra_data["_universal"]
        assert u3["entity"]["name"] == "brandi"

        # idempotent: second run changes nothing
        again = await consolidate(sf, me="chris",
                                  enricher=HeuristicEnricher())
        assert again["identity_resolved"] == 0
        assert again["duplicates_archived"] == []
    asyncio.run(run())
