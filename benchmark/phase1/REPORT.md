# Phase 1 report — ingestion truth test

*2026-06-10. Protocol: `benchmark/PROTOCOL.md` §4 Phase 1. Model:
claude-haiku-4-5. 480 NL facts/seed (60 persons × 8 fact types,
3–4 paraphrase templates each), 5 seeds per run, all costs measured
from API token usage.*

## Headline

| Run | Seeds | Semantic accuracy (entity + canonical slot) | Gate (≥90%) |
|---|---|---|---|
| v1 (baseline prompt) | 0–4 | **88.5% ± 1.0%** | ✗ FAIL |
| v2 (+4 extraction rules) | 5–9 | **96.6% ± 0.6%** | ✓ PASS |
| v3 (+3 convention rules, +precision metric) | 10–14 | **99.8% ± 0.1%** | ✓ PASS |

v3 also measures the precision side that v1/v2 were blind to:
**spurious-fill rate 3.7%** (a fact polluting a foreign aggregation
slot, e.g. "spends hours on chess" → `quantitative.magnitude="hours"`),
giving **CLEAN rate 96.1% ± 0.5%** (semantic + zero pollution), and the
end-to-end aggregation diagnostics went from 9/20 (v2) to **17/20
exact**. The three remaining misses are single-count drifts from the
residual spurious fills. Cost rose to $0.0011/fact with the longer
prompt — still ~3× below the old paper's claim.

Entity attribution was **100% on all 10 seeds** — every fact linked to
the right person. Capture-anywhere was 100% in v2: the enricher never
lost a fact's content; every residual error is the value landing in a
defensible-but-non-canonical slot.

Cost: $0.0007/fact (v1), $0.0009/fact (v2, longer system prompt).
~60–190s wall per 480 facts at 12 workers.

## What v1 → v2 fixed

v1's failures were three systematic behaviors, all diagnosed from the
per-fact logs:

1. **pet 35–57%** — two-entity sentences ("Doqu2 owns a parrot") made
   the enricher emit `entity` as a list of both entities, or invert
   subject/object on "A goldfish lives with Wavi1".
2. **origin 77–88%** — born-in/grew-up-in places filed under
   `spatial.location`, colliding with the lives-in slot.
3. **`"home"` artifact** — the template "Home for X is Y." produced the
   literal value `home`; it topped the location distribution on all 5
   seeds.

Four explicit rules in the extraction prompt (single primary entity;
origin ≠ location; no deictic placeholders; attribute-role routing)
took pet, origin, location, and height to **100%** in v2.

## The honest wrinkle: per-fact accuracy and aggregation consistency
## are different properties

The same prompt rules that fixed v1's failures *regressed* two types:
**job 99% → 78%** and **color 100% → 93%** on canonical slot — while
capture stayed 100%. The model became *more* semantically careful and
therefore less conventional: "X's favorite color is blue" now sometimes
lands in `relational.object` (a preference) rather than
`perceptual.color` (which literally asserts X is blue — arguably the
*wrong* slot, inherited from the deleted paper's generator). Honest
read: this is a **slot-convention ambiguity in our ground truth**, not
purely a model error.

The end-to-end aggregation diagnostics make the consequence concrete:

| Exact aggregates (5 seeds each) | v1 | v2 |
|---|---|---|
| count color=blue | 5/5 | 3/5 |
| count job=engineer | 5/5 | 4/5 |
| top-5 colors | 5/5 | 2/5 |
| top-5 locations | 0/5 | 0/5 |

v1 had *worse per-fact accuracy but better aggregation consistency* on
job/color, because its (sloppier) extractions were more uniform.
And top-5 locations still fails in v2 for a new reason: pet sentences
like "X takes care of a parrot **at home**" spuriously fill
`spatial.location=home` — faithful to the sentence, poison to the
aggregate. Our per-fact metric only checks the expected value's slot
(recall); it is blind to spurious fills of *other* slots (precision).

## Conclusions

1. **The gate passes**: per-fact semantic extraction ≥90% is met
   (96.6% ± 0.6%), so the "single universal pipeline" premise holds at
   Haiku cost. Phase 2 may proceed.
2. **Aggregation-grade consistency is the real bar and it is not yet
   met.** Counts that depend on every instance of a fact type landing
   in the same slot are off by 1–2 per 60 (and worse where spurious
   fills pollute a slot). Before Phase 2, the enricher prompt must pin
   an explicit convention for preference-type facts, and the scorer
   gains a spurious-fill (precision) metric.
3. **Known residuals to fix**: job→`entity.subkind` drift (~20%),
   favorite-color→`relational.object` drift (~7%), `at home`→
   `spatial.location` spurious fill on pet sentences.
4. Synthetic-corpus caveat: 8 fact types, single-sentence facts,
   synthetic names. Real-corpus extraction is Phase 2+ territory.

## Reproduce

```bash
ANTHROPIC_API_KEY=... PYTHONPATH=. \
  python benchmark/phase1/run_phase1.py --n 60 --seeds 5,6,7,8,9 --workers 12
```

Raw per-fact logs: `results/` (v1, seeds 0–4) and `results-v2/`
(seeds 5–9), one JSON line per fact including the full extraction.
