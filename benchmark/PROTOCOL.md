# Benchmark Protocol — pre-registered

*Written 2026-06-10, before any Phase 2 results exist. The win/kill
condition below was fixed before the comparison systems were run. If we
change it after seeing results, the change and its reason must be
recorded in §7.*

## 1. The claim under test

> **Given a corpus delivered as natural-language text and ingested once
> through a single universal pipeline (no per-domain schema design), Ada
> answers natural-language questions over that corpus better — on the
> combined score of answer accuracy, latency, cost, and ingestion effort
> across a mixed query distribution — than (a) text-to-SQL over a generic
> EAV table, (b) embedding RAG, and (c) text-to-Cypher over a graph DB.**

What Ada is, for the purpose of this test: the universal schema
(7 layers × 33 roles), the LLM extraction pipeline that maps text into
it at write time, the versioned-key store, exact structured queries
(count / distribution / intersection / refusal), and lexical recall.
**There is no HDC / vector layer in the system** (removed 2026-06-10
after three independent results showed it carried no benchmark wins).

## 2. Why this framing (and not others)

- "Outperform a DB at counting" is unwinnable by anyone — nothing beats
  `GROUP BY` on its home turf. The claim is at the **system level**:
  same NL interface, same single ingestion pipeline, mixed real-shaped
  query load.
- The **mandatory killer baseline** is text-to-SQL over a generic EAV
  table (`entity, layer, role, value, key, version, ts`). It shares
  Ada's zero-schema property. If Ada cannot beat *that* system on the
  combined score, the substrate has no demonstrated point beyond the
  schema-as-extraction-target.
- Every system gets the **same translator LLM** budget for query
  understanding. Differences in results must come from the storage
  architecture, not from one system getting a smarter model.

## 3. Systems

| System | Ingestion | Query path |
|---|---|---|
| **Ada** | enricher (LLM) → universal-schema slots | NL → LLM maps to slot ops (count/dist/intersect/lookup) → exact scan; lexical recall fallback |
| **EAV + text-to-SQL** | same enricher output written as EAV rows | NL → LLM emits SQL → SQLite/Postgres |
| **Embedding RAG** | sentence-transformers (local MiniLM) → vector index | NL → embed → top-K → LLM renders answer |
| **Graph DB + text-to-Cypher** | LLM emits nodes/relations (its own extraction prompt) | NL → LLM emits Cypher → Kùzu |

Rules:
- All systems ingest the **same natural-language sentences**. Nobody
  receives pre-structured dicts (this was the central flaw of the
  deleted 2026-05 benchmark).
- Same translator/renderer model for all systems, same max-token
  budgets, same number of retries (1).
- Each system may fail honestly ("I don't know" / query error) — wrong
  answers score worse than refusals on unanswerable items, and refusals
  score zero on answerable items.

## 4. Phases

**Phase 1 — ingestion truth test.** Synthetic corpus rendered as NL
sentences (multiple templates + paraphrase variants per fact), ground
truth known by construction. Measures **semantic extraction accuracy**
per system: does the stored structure match the known fact? This is the
number the old "composition integrity" metric never was. Report
per-slot precision/recall for Ada's enricher.

**Phase 2 — NL query benchmark.** Paraphrased NL questions over the
ingested corpus. Query distribution (weights fixed now):

| Shape | Weight | Example |
|---|---|---|
| Point lookup | 30% | "where does Karano42 live?" |
| Aggregation | 15% | "how many people prefer tea?" |
| Distribution | 10% | "what are the most common jobs?" |
| Intersection | 10% | "who is blue AND in Austin AND plays chess?" |
| Negation / comparison / rank | 10% | "how many are NOT engineers?" |
| Version / history | 10% | "where did X live before?" |
| Refusal (unanswerable) | 10% | "what is X's salary?" (never stated) |
| Paraphrase-stress lookup | 5% | synonym/typo variants of point lookups |

**Phase 3 — scale sweep.** N ∈ {1K, 10K, 100K, 1M} facts. Accuracy,
p50/p95 end-to-end latency, $ per query, $ per 1K facts ingested.

**Seeds & stats.** ≥5 seeds per configuration for anything with an LLM
in the loop. Report mean ± sd and effect sizes, not just point scores.

## 5. Pre-registered win / kill condition

Chosen 2026-06-10 (option: "systems-level win").

**Ada WINS if, at every scale tier in Phase 3:**
1. Accuracy on structured shapes (aggregation, distribution,
   intersection, negation, rank, refusal) is within noise (overlapping
   95% CIs) of EAV+text-to-SQL, **and**
2. Ada's combined score — accuracy first, ties broken by cost per
   query, then p95 latency, then ingestion cost — beats **all three**
   baselines on the full mixed distribution, **and**
3. Phase 1 semantic extraction accuracy ≥ 90% per-fact (else the
   "single universal pipeline" premise is hollow).

**Ada is KILLED (as a substrate claim) if** EAV+text-to-SQL matches or
beats Ada on the combined score at any scale tier. In that world the
honest conclusion is: the contribution is the universal schema as an
LLM extraction ontology, and the product is the ingestion pipeline +
MCP memory surface over any conventional store. We write that up and
move on — no post-hoc re-weighting of the query mix to rescue the
result.

## 6. What we will not do

- No pre-structured ingestion for Ada while baselines get raw text.
- No scoring metric that conflates syntactic validity with semantic
  accuracy ("integrity" is banned from results tables).
- No simulated baselines presented as measurements. Analytical
  models (e.g. context-eviction arithmetic) may appear only if labeled
  as arithmetic, never in a results table next to measured numbers.
- No single-seed LLM results.
- No cost extrapolations beyond 10× the largest measured scale.

## 7. Amendments

- **§7-1 (2026-06-10, before Phase 2 v1):** the graph baseline ingests
  from the shared universal extraction rather than its own LLM
  extraction pass. Reason: holds ingestion quality constant so the
  comparison isolates query architecture; the hand-written
  predicate→edge mapping the graph still needs is the measured
  schema-design cost.
- **§7-2 (2026-06-10, after Phase 2 v1, before v2):** engine fixes from
  pilot/v1 failure analysis — `entities_where` gained multi-value
  same-slot conditions and containment matching for
  `relational.predicate`; `distribution_filtered` added. No §4 weights
  or §5 thresholds changed; no scorer changes; v2 ran on fresh seeds.
  Outcome recorded in `phase2/REPORT.md`: §5 win condition NOT met
  (statistical tie with Kùzu on accuracy, lost cost/latency
  tie-breakers), kill condition not fired (EAV −21.6 points).
- **§7-3 (2026-06-10, before Phase 3):** Phase 3 ingests ground-truth
  structured rows instead of LLM extractions. Reason: extraction
  quality/cost are per-fact properties already measured (Phase 1) and
  exercised end-to-end (Phase 2); re-buying them at 1M facts (~$1,000)
  adds no information. RAG still embeds raw sentences. Seeds at the
  top tiers reduced to 3 (100K) and 2 (1M), compute-bounded.
- **§7-4 (2026-06-10, after Phase 3 v1, before v2):** v1's
  "guaranteed-empty" intersection questions were NOT empty at the
  100K/1M tiers (a random 3-way combo has an expected cohort of ~21 at
  125K persons; the generator gave up and mislabeled). Systems that
  answered with the actually-existing people were scored wrong —
  contamination AGAINST the systems. Fix: conditions escalate (3→5-way)
  until verified empty. Also: EAV ingestion batched + indexed
  (row-at-a-time INSERTs took 87 min at 1M, misrepresenting EAV).
  100K and 1M tiers re-run as v2; 1K/10K tiers unaffected (verified).
