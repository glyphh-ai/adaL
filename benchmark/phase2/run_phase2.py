"""
Phase 2 — NL query benchmark across four systems (PROTOCOL.md §4).

One corpus of NL sentences (with versioned updates) → one shared
extraction pass (Ada / EAV / Graph) + raw-sentence embedding (RAG) →
the weighted NL question mix → scored per the pre-registered rules.

    ANTHROPIC_API_KEY=... PYTHONPATH=.:benchmark/phase2 \
        .venv-bench/bin/python benchmark/phase2/run_phase2.py \
        --n 60 --seeds 0,1,2 --out benchmark/phase2/results
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))

from corpus import build_corpus  # noqa: E402
from queries import Query, build_queries  # noqa: E402
from systems import (  # noqa: E402
    LLM, AdaSystem, EAVSystem, GraphSystem, RAGSystem, timed_answer,
)

from ada.cognitive.universal import UniversalEnricher  # noqa: E402

HAIKU_IN_PER_M = 1.00
HAIKU_OUT_PER_M = 5.00

REFUSAL_RX = re.compile(
    r"don'?t know|do not know|no information|not (in|stored|available)|"
    r"cannot answer|can'?t answer|unknown", re.I)
NONE_RX = re.compile(r"^\s*(none|no one|nobody|no people|nothing|0|zero)\b", re.I)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _parse_list(answer: str) -> list[str]:
    parts = re.split(r"[,\n;]+", answer)
    out = []
    for p in parts:
        p = re.sub(r"\(?\b\d+\b\)?", "", p)        # strip counts
        p = re.sub(r"^[\s\-•*\d.]+|[\s.]+$", "", p)
        if p and not REFUSAL_RX.search(p):
            out.append(_norm(p))
    return out


def score(q: Query, answer: str) -> dict:
    a = answer.strip()
    refused = bool(REFUSAL_RX.search(a))
    correct = False
    hallucinated = False

    if q.kind == "refusal":
        correct = refused
        hallucinated = not refused
    elif q.kind == "value":
        correct = bool(re.search(
            rf"(?<![a-z0-9]){re.escape(_norm(q.expected))}(?![a-z0-9])", _norm(a)))
    elif q.kind == "number":
        m = re.search(r"-?\d+", a)
        got = int(m.group()) if m else (0 if NONE_RX.match(a) else None)
        correct = got == q.expected
    elif q.kind == "none":
        correct = bool(NONE_RX.match(a)) or (not refused and not _parse_list(a))
    elif q.kind == "names":
        got = set(_parse_list(a))
        want = {_norm(n) for n in q.expected}
        correct = got == want
    elif q.kind == "top5":
        ranking = q.expected  # full most_common() list
        k = min(5, len(ranking))
        c5 = ranking[k - 1][1]
        must = {v for v, c in ranking if c > c5}
        allowed = {v for v, c in ranking if c >= c5}
        got = _parse_list(a)
        got_set = {g for g in got}
        correct = (len(got_set) == k and must <= got_set
                   and got_set <= allowed)

    return {"correct": correct, "refused": refused,
            "hallucinated": hallucinated}


def run_seed(n_persons: int, seed: int, out_dir: Path) -> dict:
    corpus = build_corpus(n_persons, seed)
    queries = build_queries(corpus, seed)
    print(f"\n  seed {seed}: {len(corpus.facts)} facts "
          f"({len(corpus.previous)} updates), {len(queries)} queries")

    # ── shared extraction pass (the ingestion all keyed systems share) ─
    enricher = UniversalEnricher()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as pool:
        extractions = list(pool.map(
            lambda f: _safe_enrich(enricher, f.sentence), corpus.facts))
    extract_s = time.time() - t0
    extract_cost = (enricher.usage["input_tokens"] * HAIKU_IN_PER_M +
                    enricher.usage["output_tokens"] * HAIKU_OUT_PER_M) / 1e6
    print(f"    extraction: {extract_s:.0f}s, ${extract_cost:.2f} "
          f"(shared by ada/eav/graph)")

    # ── systems ───────────────────────────────────────────────────────
    systems = []
    for cls in (AdaSystem, EAVSystem, RAGSystem):
        systems.append(cls(LLM()))
    systems.append(GraphSystem(LLM(), tempfile.mkdtemp(prefix=f"kuzu{seed}_") + "/db"))

    per_system: dict[str, dict] = {}
    for system in systems:
        t0 = time.time()
        system.ingest(corpus.facts, corpus.keys, extractions)
        ingest_s = time.time() - t0

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
                         "answer": ans, "latency_ms": round(ms, 1), **s})
        query_s = time.time() - t0

        lat = sorted(r["latency_ms"] for r in rows)
        usage = system.llm.usage
        cost = (usage["input_tokens"] * HAIKU_IN_PER_M +
                usage["output_tokens"] * HAIKU_OUT_PER_M) / 1e6
        n_refusal_q = sum(1 for q in queries if q.kind == "refusal")
        by_shape: dict[str, list] = {}
        for r in rows:
            by_shape.setdefault(r["shape"], []).append(r["correct"])
        per_system[system.name] = {
            "accuracy": sum(r["correct"] for r in rows) / len(rows),
            "by_shape": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_shape.items())},
            "hallucination_rate_on_refusal":
                sum(r["hallucinated"] for r in rows) / max(1, n_refusal_q),
            "latency_p50_ms": lat[len(lat) // 2],
            "latency_p95_ms": lat[int(len(lat) * 0.95)],
            "query_cost_usd": round(cost, 4),
            "cost_per_query_usd": round(cost / len(rows), 6),
            "ingest_errors": system.ingest_errors,
            "ingest_seconds": round(ingest_s, 1),
            "query_seconds": round(query_s, 1),
            "rows": rows,
        }
        p = per_system[system.name]
        print(f"    {system.name:<12} acc {100*p['accuracy']:5.1f}%  "
              f"p50 {p['latency_p50_ms']:6.0f}ms  ${p['cost_per_query_usd']:.4f}/q  "
              f"halluc {100*p['hallucination_rate_on_refusal']:.0f}%  "
              f"ingest_err {p['ingest_errors']}")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "seed": seed, "n_facts": len(corpus.facts),
        "n_queries": len(queries),
        "extraction_cost_usd": round(extract_cost, 4),
        "systems": {k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                    for k, v in per_system.items()},
    }
    with open(out_dir / f"summary_seed{seed}.json", "w") as fh:
        json.dump(summary, fh, indent=2)
    with open(out_dir / f"answers_seed{seed}.json", "w") as fh:
        json.dump({k: v["rows"] for k, v in per_system.items()}, fh, indent=2)
    return summary


def _safe_enrich(enricher, sentence: str) -> dict:
    for attempt in (1, 2):
        try:
            return enricher.enrich(sentence)
        except Exception:
            if attempt == 2:
                return {}
            time.sleep(2.0)
    return {}


def _expected_repr(q: Query):
    if q.kind == "top5":
        return q.expected[:7]
    return q.expected


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=60)
    p.add_argument("--seeds", type=str, default="0")
    p.add_argument("--out", type=str, default="benchmark/phase2/results")
    args = p.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    out_dir = Path(args.out)
    all_summaries = [run_seed(args.n, s, out_dir) for s in seeds]

    print("\n  ═══ cross-seed accuracy ═══")
    names = list(all_summaries[0]["systems"])
    for name in names:
        accs = [s["systems"][name]["accuracy"] for s in all_summaries]
        mean = statistics.mean(accs)
        sd = statistics.stdev(accs) if len(accs) > 1 else 0.0
        print(f"    {name:<12} {100*mean:5.1f}% ± {100*sd:.1f}%")


if __name__ == "__main__":
    main()
