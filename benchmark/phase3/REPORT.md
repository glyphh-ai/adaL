# Phase 3 report — scale sweep, ~1K → ~1M facts

*2026-06-11. Protocol §4 Phase 3 + amendments §7-3/§7-4. Four systems,
same NL questions, ground-truth structured ingestion (extraction
quality is a per-fact property measured in Phase 1). Tiers: 1K/10K ×5
seeds, 100K ×3, 1M ×2. 1K/10K from the original run (verified
uncontaminated); 100K/1M from the v2 re-run after the §7-4 fixes.*

## Accuracy by scale

| Facts | Ada | Kùzu+Cypher | EAV+SQL | RAG (MiniLM) |
|---|---|---|---|---|
| 1,037 | 97.7% ± 1.5 | 96.7% ± 3.1 | 85.0% ± 3.5 | 56.7% ± 2.6 |
| 10,375 | 98.3% ± 1.2 | 97.7% ± 2.2 | 85.3% ± 2.2 | 43.0% ± 4.3 |
| 103,750 | 99.4% ± 1.0 | 96.7% ± 2.9 | 85.0% ± 2.9 | 31.1% ± 5.1 |
| **1,037,500** | **100.0% ± 0.0** | **96.7% ± 0.0** | 78.3% ± 2.4 | 24.2% ± 1.2 |

- **Ada leads or ties every tier and does not degrade with scale** —
  at clean ingestion its accuracy *rises* with N (bigger cohorts are
  more forgiving of phrasing, and the op surface doesn't change).
- **RAG decays on a clean curve: 57 → 43 → 31 → 24%.** Top-8 retrieval
  over a million facts cannot see what compositional questions need.
  Measured, not simulated.
- **EAV+SQL degrades at 1M** (85 → 78%) as LLM-generated SQL gets
  riskier on big joins — including runaway queries (below).
- Caveat: with *real LLM extraction* (Phase 2, n≈500 facts), Ada and
  Kùzu were a statistical tie (92.3 vs 91.7). Phase 3 isolates the
  query path; the Phase 2 tie remains the honest end-to-end number at
  small scale.

## Latency and ingestion at 1M facts

| | Ada | Kùzu | EAV+SQL | RAG |
|---|---|---|---|---|
| Ingest (1M facts) | 8.7s | 4.9s | 11.6s | 223s (embedding) |
| Engine: count | 341ms | **14ms** | 3ms (indexed) | — |
| Engine: distribution | 336ms | 20ms | 147ms | — |
| Engine: intersection | 66ms | 22ms | 365ms | 112ms (top-8) |
| Engine: person lookup | **0.0ms** | 0.3ms | 0.0ms | — |
| End-to-end p50 | **1.30s** | 1.19s | 4.1–15.0s | 0.93s |

- **Ada's O(N) scan is real and quantified**: count grows linearly
  (0.3ms → 2.4 → 25 → 341ms across tiers). Kùzu's indexes stay ~flat.
  Behind the LLM translator (~1.2s floor) the difference is
  imperceptible at ≤1M facts; at 10M+ or for machine-speed callers the
  scan needs an index — a roadmap item, not an architecture question.
- Ada's entity-profile cache keeps lookups and intersections O(1)-ish
  after the first build.

## Three failures the sweep surfaced (all kept in the record)

1. **Ground-truth contamination (§7-4).** v1's "guaranteed-empty"
   intersection questions weren't empty at 100K/1M — a random 3-way
   combo has an expected cohort of ~21 at 125K persons. Systems that
   answered with the *actually existing people* were marked wrong
   (Ada/Kùzu "dipped" to ~93%). Fix: escalate to 4/5-way conditions
   until verified empty. The corrected 1M tier reads 100.0/96.7.
2. **O(N²) in our own harness.** The first "batched" EAV loader used a
   correlated-subquery UPDATE with no index — it span for an hour at
   the 100K tier. Fixed by computing `is_current` before insertion
   (1.1s). The 87-minute v1 number was equally unrepresentative in the
   other direction; the fair EAV load time is ~12s at 1M.
3. **Runaway LLM-generated SQL.** One generated statement was
   effectively a cartesian self-join over 4M rows; SQLite ground on it
   for 14 CPU-hours. Both query engines now run under a 15s timeout
   (timeout → honest "I don't know"). **Finding: a store that executes
   model-generated queries without a hard timeout is a self-DoS
   waiting to happen.** Ada's closed op set is immune by construction
   — every op is bounded; there is no query language to run away in.
   EAV's p50 at 1M (4–15s) reflects timeouts firing.

## Verdict

The scale claim, in its strongest defensible form:

> **From 1K to 1M facts, Ada's accuracy does not degrade (97.7% →
> 100.0%) while RAG collapses (56.7% → 24.2%) and text-to-SQL erodes
> (85% → 78%). It matches or beats the hand-schema'd graph DB at every
> tier with zero per-domain schema design, ingests 1M facts in ~9s,
> and its O(N) engine cost (341ms at 1M) stays invisible under the
> LLM-translator floor. Its closed op set cannot generate runaway
> queries — the SQL baseline did.**

Boundaries stated plainly: engine-level, indexed stores are 24× faster
on scans at 1M; the end-to-end tie with the graph DB under *real*
extraction (Phase 2) is the production-grade number; multi-hop
traversal remains out of scope.

## Reproduce

```bash
ANTHROPIC_API_KEY=... PYTHONPATH=.:benchmark/phase2:benchmark/phase1 \
  .venv-bench/bin/python benchmark/phase3/run_phase3.py --out benchmark/phase3/results-v2
```

Raw per-cell metrics and per-question answers: `results/` (v1,
contaminated at 100K/1M — kept for the record) and `results-v2/`.

## Addendum (2026-06-11): SQL storage mode at 10M rows — measured

The O(N) boundary identified above is now resolved by the SQL storage
mode (`ADA_STORAGE=sql`): the eight closed ops compiled to fixed,
parameterized SQL templates over an indexed `fact_slots` table. The 10M
extrapolation is replaced by measurement (`sql_bench.py`, 1.25M
entities × 8 slots = 10,000,000 rows, SQLite, 2.0GB on disk):

| | Memory mode @1M (measured) | Memory @10M (extrapolated) | **SQL mode @10M (measured)** |
|---|---|---|---|
| Boot | ~9s + ~3GB RAM | minutes + ~25GB | **8 ms, O(1) RAM** |
| count | 341 ms | ~3.4 s | **6.2 ms** |
| distribution | 336 ms | ~3.4 s | **97 ms** |
| intersection (two ~125K-entity conditions) | 66 ms | — | 308 ms (SQL INTERSECT) |
| point lookup | 0.0 ms (cache) | — | **0.5 ms** |

Two engineering notes kept for the record: the first cut measured
intersection at 2.4s (per-condition entity sets materialized in Python
— replaced with SQL INTERSECT, 8×) and lookup at 1.1s (SQLite's planner
chose the layer/role index and scanned 1.25M rows; the lookup now
fetches the entity's ~8 rows via the entity index and filters in
Python — planner-proof, 2200×). Both ops remain fixed templates; the
no-model-generated-SQL property is unchanged. Memory ↔ SQL parity is
enforced by tests (identical answers on the same corpus, all ops).
