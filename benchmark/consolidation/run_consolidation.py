"""
Consolidation eval harness — see PROTOCOL.md (registered first).

Offline and deterministic: HeuristicEnricher, no renderer, no API.

    PYTHONPATH=. .venv/bin/python benchmark/consolidation/run_consolidation.py
"""

import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

OUT = Path(__file__).parent / "results"
SEEDS = [6, 7, 8, 9, 10]  # A1: seeds 1-5 ran with ambiguous value pools

NAMES = ["chris", "harper", "rena", "marco", "june", "tobias", "lena",
         "omar", "priya", "wendell", "sofia", "dmitri", "amara", "felix",
         "noor", "callum", "ivy", "baxter", "celine", "rocco"]
SPOUSES = ["brandi", "elliot", "maren", "tasha", "quinn", "rosa", "hugo",
           "petra", "silas", "vera", "nico", "opal", "jude", "freya",
           "boris", "lila", "amos", "greta", "ezra", "wren"]
KIDS = ["traceton", "carson", "milo", "esme", "atlas", "juniper", "ozzy",
        "delia", "flint", "sage", "remy", "thea", "bodhi", "isla",
        "knox", "pearl", "arlo", "maeve", "cyrus", "dot"]
# A1: one distinct value per persona — token-presence grading must be
# unambiguous (a shared city credited the wrong persona's fact).
CITIES = ["austin", "boston", "denver", "portland", "tucson", "savannah",
          "boise", "madison", "raleigh", "omaha", "fresno", "tulsa",
          "spokane", "laredo", "tampa", "reno", "norfolk", "anchorage",
          "fargo", "provo"]
COLORS = ["blue", "green", "crimson", "violet", "amber", "teal", "coral",
          "indigo", "maroon", "olive", "salmon", "turquoise", "lavender",
          "chartreuse", "magenta", "ochre", "periwinkle", "scarlet",
          "cerulean", "sienna"]
JOBS = ["engineer", "doctor", "teacher", "chef", "lawyer", "carpenter",
        "plumber", "architect", "florist", "barber", "pilot", "weaver",
        "librarian", "machinist", "surveyor", "blacksmith", "tailor",
        "glassblower", "beekeeper", "cartographer"]


def typo(word: str, rng: random.Random) -> str:
    """Swap two adjacent interior letters — branid-style."""
    if len(word) < 4:
        return word + word[-1]
    i = rng.randrange(1, len(word) - 2)
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


def build_corpus(seed: int):
    rng = random.Random(seed)
    names = NAMES[:]
    rng.shuffle(names)
    cities, colors, jobs = CITIES[:], COLORS[:], JOBS[:]
    rng.shuffle(cities), rng.shuffle(colors), rng.shuffle(jobs)
    personas = []
    for i, name in enumerate(names):
        personas.append({
            "name": name,
            "spouse": SPOUSES[(i * 7 + seed) % len(SPOUSES)],
            "kids": [KIDS[(i * 3 + seed) % len(KIDS)],
                     KIDS[(i * 3 + seed + 1) % len(KIDS)]],
            "city": cities[i],     # unique within the seed (A1)
            "color": colors[i],
            "job": jobs[i],
        })
    op = personas[0]

    # (content, legacy_universal_or_empty)
    facts = [
        (f"my name is {op['name']}", {}),
        (f"i am {op['name']}", {}),
        (f"i am married to {op['spouse']}",
         {"relational": {"subject": "speaker", "predicate": "married_to",
                         "object": op["spouse"]}}),
        (f"my wifes name is {typo(op['spouse'], rng)}", {}),
        (f"my wifes name is {op['spouse']}", {}),
        (f"i live in {op['city']}",
         {"relational": {"subject": "speaker", "predicate": "lives_in",
                         "object": op["city"]},
          "spatial": {"location": op["city"]}}),
        (f"my favorite color is {op['color']}", {}),
        (f"{op['spouse']} has two children {op['kids'][0]} and {op['kids'][1]}",
         {"entity": {"name": op["spouse"]},
          "relational": {"subject": op["spouse"], "predicate": "has_children",
                         "object": f"{op['kids'][0]} and {op['kids'][1]}"}}),
        ("who are my children?", {}),
    ]
    for p in personas[1:]:
        facts.append((f"{p['name']} lives in {p['city']}",
                      {"entity": {"name": p["name"]},
                       "spatial": {"location": p["city"]}}))
        facts.append((f"{p['name']} works as a {p['job']}",
                      {"entity": {"name": p["name"]},
                       "relational": {"subject": p["name"],
                                      "predicate": "works_as",
                                      "object": p["job"]}}))

    conversational = [
        ("who is my wife?", [op["spouse"]]),
        ("who are my children?", op["kids"]),
        ("where do I live?", [op["city"]]),
        ("what is my favorite color?", [op["color"]]),
    ]
    controls = []
    for p in personas[1:6]:
        controls.append((f"where does {p['name']} live?", [p["city"]]))
        controls.append((f"what does {p['name']} do?", [p["job"]]))
    return op, facts, conversational, controls


async def seed_db(sf, facts):
    from domains.models.db_models import AdaThought
    async with sf() as s:
        t0 = time.time()
        for i, (content, u) in enumerate(facts):
            meta = {"_universal": u} if u else {}
            s.add(AdaThought(thought_id=f"f{i}", content=content,
                             speaker="incoming", space_id="main",
                             created_at=t0 + i, last_accessed=t0 + i,
                             extra_data=meta))
        await s.commit()


async def ask_set(sf, me, questions):
    from ada.cognitive.surface import CognitiveSurface
    from ada.encoder.llm_enricher import HeuristicEnricher
    from ada.memory.thought_persistence import load_thoughts
    from ada.memory.thought_space import ThoughtSpace, resolve_question_identity

    space = ThoughtSpace(enricher=HeuristicEnricher())
    await load_thoughts(sf, space)
    surf = CognitiveSurface(space=space)
    top1 = top5 = 0
    detail = []
    for q, gt in questions:
        rq = resolve_question_identity(q, me)
        a = surf.ask(rq)
        ok1 = (not a.refused and a.fact is not None
               and all(t in a.fact.content.lower() for t in gt))
        res = space.recall(rq, top_k=5, exclude_speakers=("ada",))
        h2 = surf._hop2_query(rq, res)
        if h2:
            res = surf._merge(res, space.recall(h2, top_k=5,
                                                exclude_speakers=("ada",)), 5)
        ok5 = any(all(t in r.thought.content.lower() for t in gt)
                  for r in res)
        top1 += ok1
        top5 += ok5
        detail.append({"q": q, "gt": gt, "top1": ok1, "top5": ok5,
                       "refused": a.refused,
                       "fact": a.fact.content if a.fact else None})
    return top1, top5, detail


async def run_seed(seed: int):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from infrastructure.database.connection import Base
    from domains.models.db_models import AdaThought, FactSlot  # noqa: F401
    from ada.encoder.llm_enricher import HeuristicEnricher
    from ada.memory.consolidate import consolidate

    op, facts, conv, ctrl = build_corpus(seed)
    out = {"seed": seed, "operator": op["name"]}
    for arm in ("noop", "consolidated"):
        db = f"/tmp/conseval-{seed}-{arm}.db"
        if os.path.exists(db):
            os.remove(db)
        engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        await seed_db(sf, facts)
        if arm == "consolidated":
            report = await consolidate(sf, me=op["name"],
                                       enricher=HeuristicEnricher())
            out["consolidation_report"] = {
                k: report[k] for k in ("re_enriched", "identity_resolved",
                                       "questions_skipped")}
            out["consolidation_report"]["dups"] = len(report["duplicates_archived"])
        c1, c5, cdet = await ask_set(sf, op["name"], conv)
        t1, t5, tdet = await ask_set(sf, op["name"], ctrl)
        out[arm] = {
            "conversational_top1": c1 / len(conv),
            "conversational_top5": c5 / len(conv),
            "control_top1": t1 / len(ctrl),
            "control_top5": t5 / len(ctrl),
            "detail": {"conversational": cdet, "control": tdet},
        }
        await engine.dispose()
    return out


async def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for seed in SEEDS:
        r = await run_seed(seed)
        rows.append(r)
        print(f"seed {seed}: noop conv={r['noop']['conversational_top1']:.2f} "
              f"ctrl={r['noop']['control_top1']:.2f} | consolidated "
              f"conv={r['consolidated']['conversational_top1']:.2f} "
              f"ctrl={r['consolidated']['control_top1']:.2f}")
    (OUT / "results.json").write_text(json.dumps(rows, indent=2))

    import statistics as st
    def agg(arm, key):
        vals = [r[arm][key] * 100 for r in rows]
        return st.mean(vals), (st.stdev(vals) if len(vals) > 1 else 0.0)
    print("\n=== aggregate (mean ± std, %) ===")
    for key in ("conversational_top1", "conversational_top5",
                "control_top1", "control_top5"):
        a, sa = agg("noop", key)
        b, sb = agg("consolidated", key)
        print(f"{key:22s} noop {a:5.1f} ± {sa:4.1f}   "
              f"consolidated {b:5.1f} ± {sb:4.1f}   Δ {b-a:+.1f}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
