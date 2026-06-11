"""
Phase 3 — scale sweep (PROTOCOL.md §4): ~1K → ~1M facts.

Measures how each architecture's accuracy, latency, and cost move with
corpus size. Two latency views:

  end-to-end  — NL question → answer, translator LLM included (what a
                user experiences; the LLM call is a shared ~1.3s floor)
  engine-only — the storage engine executing representative operations
                directly (count, distribution, 2-cond intersection,
                point lookup), no LLM. This is where O(N) scans vs
                indexed stores actually differentiate.

Ingestion (protocol amendment §7-3): systems ingest ground-truth
structured rows, not LLM extractions. Extraction quality and cost are
PER-FACT properties already measured in Phase 1 (99.8% semantic,
$0.001/fact) and exercised end-to-end in Phase 2; re-buying them at 1M
facts (~$1,000) would add no information. Phase 3 isolates query-path
scaling. RAG still embeds the raw sentences (its real ingestion).

Seeds: 5 at the 1K/10K tiers, 3 at 100K, 2 at 1M (compute-bounded;
logged in §7-3). Accuracy variance is translator/sampling-driven and
scale-independent, so thinner seeding at the top tiers mainly widens
latency CIs.

    ANTHROPIC_API_KEY=... PYTHONPATH=.:benchmark/phase2:benchmark/phase1 \
        .venv-bench/bin/python benchmark/phase3/run_phase3.py \
        --out benchmark/phase3/results
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "phase2"))
sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))

from corpus import Phase2Corpus, build_corpus  # noqa: E402
from generate_nl import NLFact  # noqa: E402
from queries import build_queries  # noqa: E402
from run_phase2 import HAIKU_IN_PER_M, HAIKU_OUT_PER_M, score, _expected_repr  # noqa: E402
from systems import (  # noqa: E402
    LLM, AdaSystem, EAVSystem, GraphSystem, RAGSystem, timed_answer,
)

# persons → ≈ facts (8 facts/person + ~0.3 updates)
SCALES = [
    ("1K", 125, 5),
    ("10K", 1_250, 5),
    ("100K", 12_500, 3),
    ("1M", 125_000, 2),
]

_PREDICATE = {"job": "works_as", "hobby": "enjoys", "pet": "has_pet"}


def to_structured(fact: NLFact) -> dict:
    """Ground-truth universal-schema row for a generated fact —
    the shape a perfect extraction would produce."""
    layer, role, value = fact.expected
    mapped: dict = {"entity": {"name": fact.person, "kind": "person"}}
    if layer == "relational":
        mapped["relational"] = {
            "subject": fact.person,
            "predicate": _PREDICATE.get(fact.fact_type, "relates_to"),
            "object": value,
        }
    else:
        mapped[layer] = {role: value}
        if fact.fact_type == "color":
            mapped["relational"] = {"subject": fact.person,
                                    "predicate": "favorite_color"}
        if fact.fact_type == "height":
            mapped["quantitative"]["unit"] = "centimeters"
    return mapped


# ── Engine-only micro-benchmark (no LLM) ──────────────────────────────

def engine_bench(system, corpus: Phase2Corpus, reps: int = 5) -> dict[str, float]:
    """Median ms for representative engine operations, executed directly."""
    city = corpus.current[corpus.persons[0]]["location"].lower()
    job = corpus.current[corpus.persons[0]]["job"].lower()
    person = corpus.persons[len(corpus.persons) // 2].lower()

    def run(fn) -> float:
        times = []
        for _ in range(reps):
            t0 = time.perf_counter()
            fn()
            times.append((time.perf_counter() - t0) * 1000)
        return statistics.median(times)

    if isinstance(system, AdaSystem):
        s = system.space
        s.entity_profiles()  # build the cache once, outside the timer
        return {
            "count": run(lambda: s.count_where("spatial", "location", city)),
            "distribution": run(lambda: s.distribution("spatial", "location", 5)),
            "intersection": run(lambda: s.entities_where(
                {"spatial.location": city, "relational.object": job})),
            "lookup": run(lambda: s.entity_profiles().get(person)),
        }
    if isinstance(system, EAVSystem):
        q = system.db.execute
        return {
            "count": run(lambda: q(
                "SELECT COUNT(DISTINCT person) FROM facts WHERE layer='spatial' "
                "AND role='location' AND value=? AND is_current=1", (city,)).fetchall()),
            "distribution": run(lambda: q(
                "SELECT value, COUNT(DISTINCT person) c FROM facts WHERE "
                "layer='spatial' AND role='location' AND is_current=1 "
                "GROUP BY value ORDER BY c DESC LIMIT 5").fetchall()),
            "intersection": run(lambda: q(
                "SELECT DISTINCT a.person FROM facts a JOIN facts b ON "
                "a.person=b.person WHERE a.role='location' AND a.value=? AND "
                "a.is_current=1 AND b.role='object' AND b.value=?",
                (city, job)).fetchall()),
            "lookup": run(lambda: q(
                "SELECT layer, role, value FROM facts WHERE person=? AND "
                "is_current=1", (person,)).fetchall()),
        }
    if isinstance(system, GraphSystem):
        def cy(stmt, params=None):
            r = system.conn.execute(stmt, params or {})
            rows = []
            while r.has_next():
                rows.append(r.get_next())
            return rows
        return {
            "count": run(lambda: cy(
                "MATCH (p:Person)-[r:LIVES_IN {current: true}]->"
                "(c:City {name: $c}) RETURN COUNT(DISTINCT p.name)", {"c": city})),
            "distribution": run(lambda: cy(
                "MATCH (p:Person)-[r:LIVES_IN {current: true}]->(c:City) "
                "RETURN c.name, COUNT(*) AS n ORDER BY n DESC LIMIT 5")),
            "intersection": run(lambda: cy(
                "MATCH (j:Job {name: $j})<-[:WORKS_AS]-(p:Person)"
                "-[r:LIVES_IN {current: true}]->(c:City {name: $c}) "
                "RETURN DISTINCT p.name", {"c": city, "j": job})),
            "lookup": run(lambda: cy(
                "MATCH (p:Person {name: $p}) RETURN p.age, p.height", {"p": person})),
        }
    if isinstance(system, RAGSystem):
        def retrieve():
            q = system.model.encode([f"who lives in {city}"],
                                    normalize_embeddings=True)[0]
            (system.embeddings @ q).argsort()[::-1][:8]
        return {"retrieval_top8": run(retrieve)}
    return {}


# ── One scale/seed cell ───────────────────────────────────────────────

def run_cell(label: str, n_persons: int, seed: int, out_dir: Path) -> dict:
    t_corpus = time.time()
    corpus = build_corpus(n_persons, seed)
    structured = [to_structured(f) for f in corpus.facts]
    queries = build_queries(corpus, seed, 60, count_intersections_over=10)
    print(f"\n  [{label}] seed {seed}: {len(corpus.facts):,} facts, "
          f"{len(queries)} queries (corpus {time.time()-t_corpus:.0f}s)")

    systems = [AdaSystem(LLM()), EAVSystem(LLM()), RAGSystem(LLM())]
    graph_dir = tempfile.mkdtemp(prefix=f"kuzu_{label}_{seed}_")
    graph = GraphSystem(LLM(), graph_dir + "/db")
    systems.append(graph)

    cell: dict = {"scale": label, "seed": seed, "n_facts": len(corpus.facts),
                  "systems": {}}
    all_rows: dict[str, list] = {}
    for system in systems:
        t0 = time.time()
        if isinstance(system, GraphSystem):
            system.ingest_bulk(corpus.facts, corpus.keys, structured, graph_dir)
        else:
            system.ingest(corpus.facts, corpus.keys, structured)
        ingest_s = time.time() - t0

        engine = engine_bench(system, corpus)

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=6) as pool:
            answered = list(pool.map(
                lambda q: timed_answer(system, q.question), queries))
        rows = []
        for q, (ans, ms) in zip(queries, answered):
            s = score(q, ans)
            rows.append({"shape": q.shape, "kind": q.kind,
                         "question": q.question,
                         "expected": _expected_repr(q),
                         "answer": ans[:200], "latency_ms": round(ms, 1), **s})
        all_rows[system.name] = rows
        lat = sorted(r["latency_ms"] for r in rows)
        usage = system.llm.usage
        cost = (usage["input_tokens"] * HAIKU_IN_PER_M +
                usage["output_tokens"] * HAIKU_OUT_PER_M) / 1e6
        cell["systems"][system.name] = {
            "accuracy": sum(r["correct"] for r in rows) / len(rows),
            "latency_p50_ms": lat[len(lat) // 2],
            "latency_p95_ms": lat[int(len(lat) * 0.95)],
            "engine_ms": engine,
            "cost_per_query_usd": round(cost / len(rows), 6),
            "ingest_seconds": round(ingest_s, 1),
            "ingest_errors": system.ingest_errors,
            "query_seconds": round(time.time() - t0, 1),
        }
        p = cell["systems"][system.name]
        eng = " ".join(f"{k}={v:.1f}ms" for k, v in engine.items())
        print(f"    {system.name:<12} acc {100*p['accuracy']:5.1f}%  "
              f"ingest {ingest_s:6.1f}s  e2e p50 {p['latency_p50_ms']:6.0f}ms")
        print(f"      engine: {eng}")

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"cell_{label}_seed{seed}.json", "w") as fh:
        json.dump(cell, fh, indent=2)
    with open(out_dir / f"answers_{label}_seed{seed}.json", "w") as fh:
        json.dump(all_rows, fh, indent=2)
    return cell


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=str, default="benchmark/phase3/results")
    p.add_argument("--scales", type=str, default="1K,10K,100K,1M")
    args = p.parse_args()
    wanted = set(args.scales.split(","))
    out_dir = Path(args.out)

    cells = []
    for label, n_persons, n_seeds in SCALES:
        if label not in wanted:
            continue
        for seed in range(n_seeds):
            cells.append(run_cell(label, n_persons, seed, out_dir))

    print("\n  ═══ accuracy by scale ═══")
    by = {}
    for c in cells:
        for name, p in c["systems"].items():
            by.setdefault((c["scale"], name), []).append(p["accuracy"])
    for label, _, _ in SCALES:
        if label not in wanted:
            continue
        row = []
        for name in ("ada", "eav_sql", "rag_minilm", "kuzu_cypher"):
            accs = by.get((label, name), [])
            if accs:
                row.append(f"{name} {100*statistics.mean(accs):.1f}%")
        print(f"    {label:>5}: " + "   ".join(row))


if __name__ == "__main__":
    main()
