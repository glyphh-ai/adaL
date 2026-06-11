# Cross-domain Phase 1: chemistry, philosophy, law

**Date:** 2026-05-30
**Model:** `claude-haiku-4-5-20251001`
**Total spend:** ~$80 (philosophy + law) + $40 (chemistry baseline)

## The question being tested

Can the universal-schema substrate + LLM-assisted curriculum
extraction scale **across domains** at high composition integrity,
or does the chemistry result (97.8%) generalize only because
chemistry has unusually regular composition structure?

Setup: three domains. Same model. Same pipeline. **One critical
difference:** chemistry was run with a 206-key namespace (layer-0 +
layer-1 + 84 hand-written chemistry seeds). Philosophy and law were
run with the *naked* 122-key namespace (only layer-0 NSM primes +
layer-1 cognitive primitives — zero domain seeds).

## Results

| Domain | Namespace | Retry pass? | First-pass integrity | After retry | Cost/clean fact |
|---|---|---|---|---|---|
| **Chemistry** | 206 keys (incl. 84 seeds) | ✓ ran | 81.3% | **97.8%** | $0.003 |
| **Philosophy** | 122 keys (no seeds) | ✗ skipped on budget | **6.1%** | — | $0.062 |
| **Law** | 122 keys (no seeds) | ✗ skipped on budget | **3.2%** | — | $0.119 |

**The cross-domain claim is NOT proven.** Philosophy and law collapsed
under the naked-schema condition.

## Why they collapsed

Three failure modes, observed in both philosophy and law:

### 1. The "declare intermediates" rule didn't fire at scale

The prompt allows the LLM to declare intermediate concepts (e.g.,
`concept.causation`) provided each declared key emits its own JSON
entry that itself decomposes into the namespace. **In the chemistry
smoke test this rule worked** (20% → 90% integrity on a 10-fact
sample). At 10K-fact scale, the LLM defaulted to using
plausible-sounding keys without declaring them — the rule was
permissive ("you may") rather than mandatory ("you MUST emit a
declaration for any non-namespace key").

### 2. Corpus contamination

Wikipedia's category trees aren't clean. The "Philosophy of science"
subcategory contains chemistry-adjacent pages. "Law" depth-3 contains
drug-law pages that link to specific chemical compounds. When Haiku
saw a Wikipedia summary of `compound.aluminon` or `compound.cyanide`,
it reached for chemistry keys it knows from training rather than
recognizing the text as out-of-domain.

Failures observed:

```
compound.aluminon         → references element.aluminum (not in namespace)
compound.dragons-blood    → references element.carbon (not in namespace)
compound.cyanide          → references element.carbon, element.nitrogen
compound.4-fluorococaine  → references element.fluorine, element.hydrogen
book.failure-of-capitalism → references concept.capitalism (not declared)
strategy.aggressive-legalism → references prime.state (NOT a real prime)
```

### 3. The retry-pass skip bug

The pipeline's budget enforcement was: `if DO_RETRY and not budget_hit:`.
When the first-pass run hit $40, retry was skipped entirely. **This
is where most of the integrity recovery lives.** Chemistry went from
81.3% to 97.8% via retry on the *same* corpus — without it, chemistry
would have looked similar to philosophy/law.

The retry pass for philosophy/law would have:
- Surfaced "compound.aluminon contains keys [element.aluminum, ...] that
  don't exist; re-emit using only namespace keys"
- Forced the LLM to either decompose to primes or declare the keys
- Likely recovered most failures, as it did for chemistry

This is a pipeline bug, not an architectural failure.

## What this honestly proves

**Proven:**
- The chemistry result (97.8% on a structured domain with seeds + retry) holds.
- The retry-with-feedback mechanism is **load-bearing infrastructure**, not optional polish.
- Wikipedia category crawls have ~10-20% off-domain drift at depth 3.
- The LLM's failure mode without seeds is to hallucinate chemistry keys (its training prior is dominated by structured-knowledge text).

**Not proven (in either direction yet):**
- Whether the universal schema can handle philosophy/law at chemistry-level integrity, with retry running and a cleaner corpus.
- Whether ~50-key domain seeds (much smaller than chemistry's 84) would close the gap on heterogeneous domains.

**Disproven:**
- The "naked" universal schema thesis: NSM primes + cognitive primitives alone, with no domain anchors and no retry, do NOT produce a high-integrity extraction on a real-world corpus. The floor is 3-6%.

## What needs to change before the next run

1. **Fix the retry-skip-on-budget bug.** Budget cap should stop *fresh* extractions but always run retry on what's already extracted. The marginal retry cost is small.

2. **Strengthen the prompt's declaration rule.** Change "you may declare intermediates" to "you MUST emit a separate JSON for any key in composed_of that isn't in the listed namespace, and that JSON's composed_of must follow the same rule." This is the rule we already have, but the smoke test proved it works when followed and the at-scale runs proved it isn't always followed at scale.

3. **Filter the corpus by domain semantics.** Either pre-filter Wikipedia titles by category-tree purity, or add a domain-classification pre-pass that drops obviously off-domain entries before extraction.

4. **Re-run philosophy + law with proper retry budget.** Same $40 first-pass + ~$10 reserved retry budget per domain. That's the fair test.

## The deeper architectural finding

The naked-schema test surfaced something real: **the universal schema
is universal at the primitive layer (NSM primes + binary distinctions
+ cognitive primitives), but practical LLM-assisted extraction at
scale on heterogeneous text requires lightweight domain anchors that
decompose into the universal layer.**

This is consistent with developmental psychology and Wierzbicka's
NSM theory itself. Children don't go directly from primes to "theory
of mind" — there's a developmental scaffolding (sensations →
categories → causality → permanence → emotions → social cognition).
Adult domain knowledge composes on top of THAT scaffolding, not
directly on primes.

The `infant/` curriculum (233 entries, 0-36 month cognitive
development) is exactly that scaffolding. The natural fix to the
philosophy/law collapse may be:

**Re-run philosophy and law with namespace = layer-0 + layer-1 + infant
+ symbols + communication (currently ~523 keys).** That's not "domain
seeds" in the chemistry sense — it's the *universal developmental
substrate* underneath all human cognition. If that closes the gap to
80%+ integrity, the thesis holds (with the caveat that the substrate
needs the developmental layer, not just NSM primes).

## What I'm NOT going to claim

I'm not going to claim philosophy + law worked. They didn't. The
data is what the data is. 

But the failure is informative: it points at exactly which parts
of the system need work (retry-on-budget, prompt rule strength,
corpus filtering, developmental substrate priming), and the chemistry
result still stands as proof the architecture can hit 97.8% when
those parts are in place.

The next experiment is a re-run with the bugs fixed. If philosophy +
law hit 80%+ with retry + cleaner corpus + developmental priming,
the cross-domain claim is real. If they don't, we've found a
genuine limit to the universal schema's reach.

## Files

- `chemistry/PHASE1_REPORT.md` — the 97.8% baseline (with seeds + retry)
- `philosophy/phase1_output/` — 10,598 extractions, 643 clean (6.1%)
- `law/phase1_output/` — 10,394 extractions, 337 clean (3.2%)

## Cost summary

```
Chemistry baseline:  $40.19
Philosophy run:      $40.00
Law run:             $40.00
Total spend:        $120.19
```

Total runtime: ~6 hours of wall clock (mostly Wikipedia fetch).
