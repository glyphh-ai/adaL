"""
Phase 1 — ingestion truth test (benchmark/PROTOCOL.md §4).

Runs Ada's real write path (UniversalEnricher) over natural-language
sentences with known ground truth and measures SEMANTIC extraction
accuracy — the number the deleted paper's "composition integrity" never
was. No pre-structured dicts anywhere.

Per fact, three independent checks:

  entity_ok     — extraction attributes the fact to the right person:
                  the person's name appears in entity.name or a
                  relational attribution slot (subject / possessor /
                  agent / object). Attribution anywhere in the glyph
                  keeps the fact intersectable with the person; the
                  VALUE side is still held to slot-level strictness.
  canonical_ok  — the value landed in the canonical layer.role slot
  captured_ok   — the value landed in the canonical OR an acceptable
                  alternate slot (defensible but non-canonical)

Headline metric (pre-registered, PROTOCOL §5.3):
  semantic accuracy = fraction of facts with entity_ok AND canonical_ok

Then the end-to-end proof: the extractions are loaded into a
ThoughtSpace and the structured queries (count / distribution) are run
against the corpus — answers compared to ground truth computed from the
generator. This is the full chain the old benchmark skipped:
NL text -> LLM enricher -> universal slots -> exact aggregation.

Cost is reported from measured API token usage, never estimated.

    ANTHROPIC_API_KEY=... PYTHONPATH=. python benchmark/phase1/run_phase1.py \
        --n 60 --seed 0 --workers 8
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_nl import NLFact, generate_nl, ground_truth_aggregates  # noqa: E402

from ada.cognitive.universal import UniversalEnricher  # noqa: E402
from ada.memory.thought_space import ThoughtSpace  # noqa: E402

# Haiku 4.5 pricing, $/MTok (uncached input, output)
HAIKU_IN_PER_M = 1.00
HAIKU_OUT_PER_M = 5.00


# ── Value matching ────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _value_matches(expected: str, got: str) -> bool:
    """Lenient-but-honest value match: normalized equality, or the
    expected value appears as a whole word inside the extracted one
    ('180' in '180 centimeters', 'engineer' in 'software engineer'
    would NOT occur here since values are single tokens by construction,
    but 'blue' must not match 'blueprint')."""
    e, g = _norm(expected), _norm(got)
    if e == g:
        return True
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(e)}(?![a-z0-9])", g))


def _find_value(mapped: dict, value: str) -> list[tuple[str, str]]:
    """Every (layer, role) whose extracted value matches `value`."""
    hits = []
    for layer, roles in (mapped or {}).items():
        if not isinstance(roles, dict):
            continue
        for role, got in roles.items():
            if got is not None and _value_matches(value, str(got)):
                hits.append((layer, role))
    return hits


# The canonical slots used by ANY fact type in this corpus. A fill in one
# of these slots that belongs to neither this fact's expected nor
# acceptable slots, with a value that isn't the fact's value or the
# person, pollutes that slot's aggregations — measured as a spurious fill
# (precision-side complement to the recall-side checks).
AGGREGATION_SLOTS = {
    ("temporal", "age"), ("spatial", "location"), ("spatial", "origin"),
    ("relational", "object"), ("perceptual", "color"),
    ("quantitative", "magnitude"),
}


def spurious_fills(fact: NLFact, mapped: dict) -> list[list[str]]:
    """Aggregation-relevant slots polluted by this extraction."""
    layer, role, value = fact.expected
    allowed = {(layer, role)} | {tuple(a) for a in fact.acceptable}
    person = _norm(fact.person)
    out = []
    for slot in AGGREGATION_SLOTS - allowed:
        slayer, srole = slot
        roles = (mapped or {}).get(slayer)
        if not isinstance(roles, dict):
            continue
        got = roles.get(srole)
        if got is None or not str(got).strip():
            continue
        if person in _norm(got):
            continue  # attribution echo (person's name) — harmless to
                      # value aggregations, common in relational slots
        out.append([slayer, srole, str(got)])
    return out


def score_fact(fact: NLFact, mapped: dict) -> dict:
    layer, role, value = fact.expected
    if not isinstance(mapped, dict):
        mapped = {}  # malformed extraction — scores as a miss on every check
    entity_layer = mapped.get("entity")
    if not isinstance(entity_layer, dict):
        entity_layer = {}
    relational = mapped.get("relational")
    if not isinstance(relational, dict):
        relational = {}
    person = _norm(fact.person)
    attribution_values = [entity_layer.get("name")] + [
        relational.get(r) for r in ("subject", "possessor", "agent", "object")
    ]
    entity_ok = any(person in _norm(v) for v in attribution_values if v)

    hits = _find_value(mapped, value)
    canonical_ok = (layer, role) in hits
    acceptable_slots = {tuple(a) for a in fact.acceptable}
    captured_ok = canonical_ok or bool(acceptable_slots & set(hits))

    spurious = spurious_fills(fact, mapped)
    return {
        "sentence": fact.sentence,
        "person": fact.person,
        "fact_type": fact.fact_type,
        "expected": list(fact.expected),
        "entity_ok": entity_ok,
        "canonical_ok": canonical_ok,
        "captured_ok": captured_ok,
        "semantic_ok": entity_ok and canonical_ok,
        "spurious_fills": spurious,
        "clean_ok": entity_ok and canonical_ok and not spurious,
        "value_landed_in": [list(h) for h in hits],
        "extraction": mapped,
    }


# ── Runner ────────────────────────────────────────────────────────────

def run_seed(n_persons: int, seed: int, workers: int, out_dir: Path) -> dict:
    facts = generate_nl(n_persons, seed)
    enricher = UniversalEnricher()

    print(f"  seed {seed}: extracting {len(facts)} NL facts "
          f"({workers} workers, model {enricher._model}) ...")
    t0 = time.time()

    def extract(fact: NLFact) -> dict:
        for attempt in (1, 2):  # one retry on transport errors
            try:
                return enricher.enrich(fact.sentence)
            except Exception:
                if attempt == 2:
                    return {}
                time.sleep(2.0)
        return {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        mappings = list(pool.map(extract, facts))
    wall = time.time() - t0

    rows = [score_fact(f, m) for f, m in zip(facts, mappings)]

    # ── Per-type breakdown ────────────────────────────────────────────
    by_type: dict[str, dict] = {}
    for r in rows:
        d = by_type.setdefault(r["fact_type"], {"n": 0, "entity": 0,
                                                "canonical": 0, "captured": 0,
                                                "semantic": 0})
        d["n"] += 1
        d["entity"] += r["entity_ok"]
        d["canonical"] += r["canonical_ok"]
        d["captured"] += r["captured_ok"]
        d["semantic"] += r["semantic_ok"]

    n = len(rows)
    cost = (enricher.usage["input_tokens"] * HAIKU_IN_PER_M
            + enricher.usage["output_tokens"] * HAIKU_OUT_PER_M) / 1e6

    summary = {
        "seed": seed,
        "n_facts": n,
        "semantic_accuracy": sum(r["semantic_ok"] for r in rows) / n,
        "entity_rate": sum(r["entity_ok"] for r in rows) / n,
        "canonical_rate": sum(r["canonical_ok"] for r in rows) / n,
        "captured_rate": sum(r["captured_ok"] for r in rows) / n,
        "spurious_fill_rate": sum(bool(r["spurious_fills"]) for r in rows) / n,
        "clean_rate": sum(r["clean_ok"] for r in rows) / n,
        "by_type": by_type,
        "usage": dict(enricher.usage),
        "cost_usd": round(cost, 4),
        "cost_per_fact_usd": round(cost / n, 6),
        "wall_seconds": round(wall, 1),
    }

    # ── End-to-end: load extractions into the substrate, run the
    #    structured queries, compare to ground truth ───────────────────
    space = ThoughtSpace()
    for fact, mapped in zip(facts, mappings):
        space.tell_raw(facts=mapped, text=fact.sentence, speaker="phase1")

    truth = ground_truth_aggregates(facts)
    e2e = {
        "count_color_blue": {
            "truth": truth["count_color_blue"],
            "ada": space.count_where("perceptual", "color", "blue"),
        },
        "count_job_engineer": {
            "truth": truth["count_job_engineer"],
            "ada": space.count_where("relational", "object", "engineer"),
        },
        "top5_locations": {
            "truth": truth["top5_locations"],
            "ada": space.distribution("spatial", "location", 5),
        },
        "top5_colors": {
            "truth": truth["top5_colors"],
            "ada": space.distribution("perceptual", "color", 5),
        },
    }
    summary["end_to_end_aggregation"] = e2e

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"results_seed{seed}.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(out_dir / f"summary_seed{seed}.json", "w") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    return summary


def print_summary(s: dict) -> None:
    print(f"\n  ── seed {s['seed']}: {s['n_facts']} facts, "
          f"${s['cost_usd']} (${s['cost_per_fact_usd']}/fact), "
          f"{s['wall_seconds']}s ──")
    print(f"  SEMANTIC ACCURACY (entity + canonical slot): "
          f"{100 * s['semantic_accuracy']:.1f}%")
    print(f"    entity attribution : {100 * s['entity_rate']:.1f}%")
    print(f"    canonical slot     : {100 * s['canonical_rate']:.1f}%")
    print(f"    captured anywhere  : {100 * s['captured_rate']:.1f}%")
    print(f"    spurious-fill rate : {100 * s['spurious_fill_rate']:.1f}%  "
          f"(facts polluting a foreign aggregation slot)")
    print(f"    CLEAN (semantic + no spurious): {100 * s['clean_rate']:.1f}%")
    print(f"\n  {'type':<10} {'n':>4} {'semantic':>9} {'entity':>7} "
          f"{'canon':>6} {'captured':>9}")
    for ft, d in sorted(s["by_type"].items()):
        print(f"  {ft:<10} {d['n']:>4} {100*d['semantic']/d['n']:>8.1f}% "
              f"{100*d['entity']/d['n']:>6.1f}% {100*d['canonical']/d['n']:>5.1f}% "
              f"{100*d['captured']/d['n']:>8.1f}%")
    print("\n  end-to-end aggregation (NL → enricher → substrate → exact query):")
    for name, r in s["end_to_end_aggregation"].items():
        match = "✓" if r["ada"] == r["truth"] else "✗"
        print(f"    {match} {name:<22} truth={r['truth']}  ada={r['ada']}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=60, help="persons per seed (×8 facts)")
    p.add_argument("--seeds", type=str, default="0", help="comma-separated seeds")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", type=str, default="benchmark/phase1/results")
    args = p.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    out_dir = Path(args.out)
    summaries = []
    for seed in seeds:
        s = run_seed(args.n, seed, args.workers, out_dir)
        print_summary(s)
        summaries.append(s)

    if len(summaries) > 1:
        import statistics
        accs = [s["semantic_accuracy"] for s in summaries]
        print(f"\n  ═══ {len(seeds)} seeds: semantic accuracy "
              f"{100*statistics.mean(accs):.1f}% ± {100*statistics.stdev(accs):.1f}% ═══")


if __name__ == "__main__":
    main()
