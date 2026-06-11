# Phase 2 report — NL query benchmark, four systems

*2026-06-10. Protocol: `benchmark/PROTOCOL.md` §3–§5. Per seed: 60
persons → ~498 NL facts (incl. ~18 versioned location updates), 60
weighted NL questions, 4 systems, same translator LLM (Haiku 4.5)
everywhere. 5 seeds per run. All costs measured from API tokens.*

## Headline (v2, fresh seeds 5–9)

| System | Accuracy | p95 latency | $/query | Ingest errors (5 seeds) |
|---|---|---|---|---|
| **Ada** (universal schema + op translator) | **92.3% ± 2.8%** | 3,452 ms | $0.0007 | **0** |
| Kùzu + text-to-Cypher | 91.7% ± 1.7% | 3,122 ms | $0.0005 | 154 |
| EAV + text-to-SQL | 70.7% ± 3.5% | 4,188 ms | $0.0009 | 0 |
| RAG (MiniLM top-8 + renderer) | 60.0% ± 2.6% | 2,154 ms | $0.0002 | 0 |

Per-shape totals (5 seeds, correct/total):

| System | lookup | agg | dist | intersect | negcmp | history | refusal | stress |
|---|---|---|---|---|---|---|---|---|
| Ada | **90/90** | 29/45 | **30/30** | **30/30** | **30/30** | **30/30** | **30/30** | 8/15 |
| Kùzu | 83/90 | 30/45 | 30/30 | 29/30 | 28/30 | 30/30 | 30/30 | 15/15 |
| EAV-SQL | 61/90 | 29/45 | 30/30 | 8/30 | 30/30 | 16/30 | 30/30 | 8/15 |
| RAG | 87/90 | 13/45 | 0/30 | 7/30 | 11/30 | 17/30 | 30/30 | 15/15 |

**Zero hallucinations on unanswerable questions, all systems, all
seeds** — every architecture refused cleanly when given the option.

## Pre-registered verdict (§5)

1. *Ada within noise of EAV on structured shapes* — **exceeded**: Ada
   beats EAV on every structured shape (intersections 30/30 vs 8/30;
   text-to-SQL reliably fails multi-value same-slot joins).
2. *Ada beats all three baselines on the combined score* — **NOT met**.
   Ada vs Kùzu is a statistical tie on accuracy (paired per-seed diffs:
   +6.7, −3.3, −1.7, +1.7, 0.0), and Kùzu wins the next two
   tie-breakers (cost/query $0.0005 vs $0.0007; p95 3.1s vs 3.5s). Ada
   wins the last (ingestion: 0 vs 154 errors, zero schema design).
3. *Kill condition (EAV matches/beats Ada)* — **does not fire**: EAV is
   21.6 points behind, far outside noise.

**So: not a win, not a kill.** The claim that survives, stated
honestly:

> Ada matches a hand-schema'd graph database on NL query accuracy
> while requiring **zero per-domain schema design** (Kùzu's
> predicate→edge mapping silently dropped 154 facts — ~6% of the
> corpus — and that mapping was hand-written for this corpus), with
> native versioning and structural refusal. It decisively beats the
> general-purpose alternatives: +21.6 points over text-to-SQL on a
> generic EAV store, +32.3 over embedding RAG.

## What the shapes show

- **RAG fails exactly where predicted**: 0/30 distributions, 13/45
  aggregations, 7/30 intersections — top-K cannot see the whole corpus.
  It is also the best paraphrase system (15/15 stress) and fine at
  lookups. Both things are true.
- **Text-to-SQL's weakness is compositional joins**, not aggregation:
  multi-value same-slot intersections (8/30) and history-by-version
  (16/30) produce subtly wrong SQL that executes fine — silent wrong
  answers, the worst failure mode.
- **The aggregation ceiling (~29–30/45) is shared by every
  extraction-fed system** — Ada, EAV, and Kùzu all hit it. It is an
  *ingestion-consistency* property, not a query-architecture property:
  with ~96% clean extraction (Phase 1), exact counts over cohorts of
  5–12 are off by one frequently. Better extraction lifts all three
  equally; no query engine can recover a miscounted slot.
- **Ada's residual weakness is paraphrase stress** (8/15): the op
  translator misroutes colloquial phrasings ("How does X earn a
  paycheck?") that Kùzu's Cypher translator handled (15/15). Translator
  prompt parity is worth a look before Phase 3.

## v1 (seeds 0–4) and what changed

v1: Kùzu 93.0% ± 2.2%, Ada 90.3% ± 2.2%, EAV 76.3% ± 4.3%, RAG 59.3% ±
4.2%. 24 of Ada's 29 misses were aggregation zero-counts from one
engine bug: the translator added predicate filters to count conditions
and `entities_where` matched predicates exactly ("work" ≠ "works_as").
Fix: predicate conditions match by containment (predicates are verb
phrases, not categorical values). v2 ran on fresh seeds per protocol.

## Protocol amendments logged

- **§7-1** (before v1): the graph baseline ingests from the shared
  universal extraction instead of its own LLM extraction pass —
  isolates query architecture by holding ingestion constant. The
  predicate→edge mapping it still requires is the measured
  schema-design cost.
- **§7-2** (after v1, before v2): `entities_where` predicate matching
  changed from exact to containment; multi-value same-slot conditions
  and predicate-filtered distributions added after the n=10 pilot.
  All engine changes, no scorer changes; v2 ran on fresh seeds.

## Limitations / next

- n=60 persons (~500 facts) — Phase 3 (scale sweep to 1M facts) is
  where O(N) scans vs indexed stores differentiate on latency.
- Synthetic corpus, 8 fact types. The professional-services example
  (`examples/professional-services/`) shows the qualitative behavior on
  realistic prose; it is a demo, not a measurement.
- Translator-prompt quality is a confound bounded by using the same
  model + budgets everywhere; per-system prompt tuning parity is
  imperfect by construction.

## Reproduce

```bash
uv venv .venv-bench --python 3.13 && uv pip install --python .venv-bench/bin/python -e . sentence-transformers kuzu
ANTHROPIC_API_KEY=... PYTHONPATH=.:benchmark/phase2:benchmark/phase1 \
  .venv-bench/bin/python benchmark/phase2/run_phase2.py --n 60 --seeds 5,6,7,8,9 --out benchmark/phase2/results-v2
```

Raw per-question answers for every system: `results/` (v1) and
`results-v2/` — `answers_seed*.json`.
