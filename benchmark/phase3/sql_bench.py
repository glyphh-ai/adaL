"""
SQL-mode engine bench — replaces Phase 3's extrapolated 10M boundary
with a measured number.

Generates N persons (8 slots each) directly into fact_slots, then times
the closed ops executing as fixed SQL templates over the indexed table,
plus boot time (connection open — no in-RAM load). Compares against the
in-memory engine's known O(N)-scan curve.

    PYTHONPATH=. .venv/bin/python benchmark/phase3/sql_bench.py --persons 1250000
    (1.25M persons x 8 slots = 10M rows)
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

CITIES = ["austin", "boston", "chicago", "denver", "eugene", "fresno",
          "glasgow", "helsinki", "istanbul", "jakarta"]
JOBS = ["engineer", "doctor", "teacher", "designer", "scientist",
        "lawyer", "pilot", "chef", "writer", "musician"]
COLORS = ["red", "blue", "green", "yellow", "orange", "purple"]


async def build(db_path: str, persons: int, seed: int = 0) -> "tuple":
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot, Token  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    rng = random.Random(seed)
    t0 = time.time()
    # Raw executemany for speed — same rows save_thought would write.
    batch, B = [], 50_000
    async with engine.begin() as conn:
        for i in range(persons):
            name = f"p{i}"
            city, job, color = rng.choice(CITIES), rng.choice(JOBS), rng.choice(COLORS)
            age, height = rng.randint(18, 80), rng.randint(150, 200)
            for layer, role, value, pred in [
                ("entity", "name", name, None),
                ("spatial", "location", city, None),
                ("relational", "object", job, "works_as"),
                ("perceptual", "color", color, None),
                ("temporal", "age", str(age), None),
                ("quantitative", "magnitude", str(height), None),
                ("relational", "object", color, "favorite_color"),
                ("spatial", "origin", rng.choice(CITIES), None),
            ]:
                batch.append({"space_id": "main", "thought_id": name,
                              "entity": name, "layer": layer, "role": role,
                              "value": value, "predicate": pred, "key": None,
                              "version": 1, "is_current": 1})
            if len(batch) >= B:
                await conn.execute(text(
                    "INSERT INTO fact_slots (space_id,thought_id,entity,layer,role,value,predicate,key,version,is_current) "
                    "VALUES (:space_id,:thought_id,:entity,:layer,:role,:value,:predicate,:key,:version,:is_current)"),
                    batch)
                batch = []
        if batch:
            await conn.execute(text(
                "INSERT INTO fact_slots (space_id,thought_id,entity,layer,role,value,predicate,key,version,is_current) "
                "VALUES (:space_id,:thought_id,:entity,:layer,:role,:value,:predicate,:key,:version,:is_current)"),
                batch)
    build_s = time.time() - t0
    return engine, sf, build_s


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--persons", type=int, default=1_250_000)
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--db", default="/tmp/ada_sqlbench.db")
    args = p.parse_args()

    Path(args.db).unlink(missing_ok=True)
    rows = args.persons * 8
    print(f"  building {args.persons:,} persons ({rows:,} slot rows) ...")
    engine, sf, build_s = await build(args.db, args.persons)
    db_mb = Path(args.db).stat().st_size / 1e6
    print(f"  built in {build_s:.0f}s · {db_mb:.0f}MB on disk")

    from ada.memory.sql_store import SqlFactStore

    # Boot = open a fresh store/connection. No in-RAM load.
    t0 = time.time()
    store = SqlFactStore(sf, space_id="main")
    await store.count_where("spatial", "location", "boston")  # warm one query
    boot_ms = (time.time() - t0) * 1000

    async def timed(coro_fn):
        ts = []
        for _ in range(args.reps):
            t = time.perf_counter()
            await coro_fn()
            ts.append((time.perf_counter() - t) * 1000)
        return statistics.median(ts)

    ops = {
        "count": lambda: store.count_where("spatial", "location", "boston"),
        "distribution": lambda: store.distribution_filtered("spatial", "location", 5),
        "intersection": lambda: store.execute_op({"op": "who", "conditions": {
            "spatial.location": "boston", "relational.object": "engineer"}}),
        "lookup": lambda: store.execute_op({"op": "lookup",
                                            "person": f"p{args.persons // 2}",
                                            "slot": "spatial.location"}),
    }
    print(f"\n  ── SQL engine @ {rows:,} rows ── (boot {boot_ms:.0f}ms)")
    for name, fn in ops.items():
        ms = await timed(fn)
        print(f"    {name:<14} {ms:8.1f} ms")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
