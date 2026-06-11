# Schema-on-Write Memory for Language Models: Exact, Versioned, Honest Recall Without Schema Design

*Christopher Timmerman — Glyphh AI*
*Working paper, June 2026. All results pre-registered; raw logs and
reproduction commands in* [`benchmark/`](benchmark/).

## Abstract

Language models need persistent memory, and the three standard ways to
provide it each fail structurally: embedding retrieval (RAG) cannot
answer questions about the whole corpus, knowledge graphs require
per-domain schema engineering that silently drops what it cannot map,
and product memory features evict. We describe **Ada**, a
*schema-on-write* memory: an LLM maps each natural-language fact into
one fixed universal schema (7 layers × 33 roles) at write time, and
reads are exact, deterministic operations — aggregation, distribution,
multi-condition intersection, versioned history, and structural refusal
— drawn from a closed set of eight operations rather than a generated
query language. The store is a flat, versioned fact table; it is
deliberately not a graph.

We evaluate against a pre-registered protocol with an explicit kill
condition, comparing four systems behind an identical natural-language
interface: Ada, text-to-SQL over a generic entity–attribute–value
store, embedding RAG (local MiniLM, top-8), and a Kùzu graph database
with text-to-Cypher. All systems ingest identical prose and use the
same translator model with the same budgets. Three results: (1)
extraction into the universal schema reaches 99.8% ± 0.1% per-fact
semantic accuracy at $0.0011/fact; (2) on a 60-question weighted mix
over ~500 extracted facts, Ada (92.3% ± 2.8) statistically ties the
hand-schema'd graph (91.7% ± 1.7) while requiring zero schema design —
the graph's hand-written predicate mapping silently dropped 6% of the
corpus — and decisively beats text-to-SQL (70.7%) and RAG (60.0%); (3)
swept from one thousand to one million facts, Ada's accuracy does not
degrade (97.7% → 100.0%) while RAG collapses (56.7% → 24.2%), with
million-fact ingestion in ~9 seconds and worst-case engine latency
(341 ms, measured linear) below the LLM-translation floor. Across all
~7,000 graded answers, no system hallucinated on unanswerable
questions; the benchmark's most consequential incidental finding is
that model-generated query languages produced a runaway 14-CPU-hour
cartesian join, a failure class Ada's closed operation set excludes by
construction. We report our pre-registered loss alongside the wins, and
three harness bugs we found and kept in the record.

## 1. The problem

A language model's context window is working memory, not memory. Any
deployment that accumulates facts — a long-running assistant, a
professional-services knowledge base, an agent that must remember
decisions — exceeds every window within weeks, and the question becomes
which external memory to bolt on. The incumbent options fail on
different axes:

- **Embedding retrieval (RAG)** answers "find me something similar"
  but is structurally blind to questions about the corpus as a whole.
  *How many clients are on fixed-fee contracts?* requires seeing every
  contract; top-K retrieval sees K. The failure is not a quality
  problem better embeddings fix — we measure it growing monotonically
  worse with corpus size (§5.3).
- **Knowledge graphs** answer compositional questions well but demand
  per-domain ontology: node types, edge types, and a mapping from
  language to both. That mapping is hand-written, and what it cannot
  express it silently drops (§5.2). The schema work is also where such
  projects stall organizationally.
- **Text-to-SQL** over a generic table avoids per-domain DDL but makes
  the model author arbitrary queries. We measure two failure modes:
  subtly wrong SQL that executes and returns confident wrong answers,
  and pathological queries that do not terminate (§6).
- **Product memory features** (bounded fact budgets injected into
  prompts) evict; their failure is arithmetic and we do not re-measure
  it here.

The hypothesis behind Ada is that one *fixed* schema — universal in the
sense of being domain-independent, not in any stronger sense — can be
applied automatically at write time by an LLM, eliminating schema
engineering while preserving the exactness that compositional questions
require.

## 2. Design

### 2.1 The universal schema

Every fact maps into a fixed lattice of 7 layers × 33 roles:

| Layer | Roles (abridged) |
|---|---|
| entity | name, kind, subkind |
| perceptual | color, size, shape, texture, … |
| spatial | location, origin, direction |
| temporal | time, duration, age, era, frequency |
| relational | subject, predicate, object, possessor, … |
| quantitative | count, magnitude, unit, ratio |
| epistemic | source, certainty, modality |

A fact fills *some* slots; the rest are absent. An absent slot is a
structural ∅: the system refuses rather than confabulates. The schema
never grows and is never edited per domain — that is the entire claim.

### 2.2 Write path: extraction at $0.001/fact

Natural-language facts pass once through an LLM extractor
(claude-haiku-4-5 in all experiments) whose prompt is the schema plus
seven domain-independent conventions (single primary entity,
origin ≠ location, no deictic values, etc. — the conventions and their
empirical motivation are in `benchmark/phase1/REPORT.md`). The call is
cached by content hash; measured cost is $0.0011 per fact. Facts may
also arrive pre-structured (`tell_raw`), with no model in the path.

Facts written under a *key* form an append-only version chain. All
read operations answer over **current belief** — superseded versions
are excluded — while the full chain remains queryable as history.

### 2.3 Read path: a closed operation set

Reads never invoke an LLM against the data. The query surface is eight
operations: point lookup, previous-value lookup, count over
conditions, negated count, top-K distribution (optionally
predicate-filtered), entity intersection (multi-condition, including
multiple values in one slot), pairwise comparison, and refuse. All are
exact scans or indexed lookups over the fact table; an entity-level
view joins a single entity's facts across slots (built once per write
epoch, O(N); reused O(1)).

When a language model fronts the store, it translates the user's
question into *one* of these operations (JSON, one retry). This is the
load-bearing contrast with text-to-SQL and text-to-Cypher: a closed,
bounded operation set is a smaller target for the translator (fewer
silent errors, §5.2) and cannot express a non-terminating query (§6).

### 2.4 What Ada is not

Ada is a flat fact table, **not a graph**: slot values are strings, not
references; there is no traversal; multi-hop questions are out of
scope (a graph remains the right tool for them — §5.2 measures one).
It contains **no learned representations**: an earlier iteration of
this system was built on hyperdimensional computing; an internal audit
found the vector layer carried none of the measured results, and it
was removed before this evaluation. The architecture is exactly as
boring as described, on purpose.

## 3. Evaluation methodology

The full protocol, including a pre-registered win condition *and kill
condition*, was committed before any comparison ran
(`benchmark/PROTOCOL.md`); the four amendments made along the way are
logged in its §7 with dates and reasons, and every run they affected
was re-executed on fresh seeds.

**Fairness rules.** All systems ingest *identical natural-language
sentences*. Ada, the EAV store, and the graph share one extraction
pass, isolating query architecture from extraction quality; RAG embeds
the raw sentences (its native ingestion). All systems use the same
translator/renderer model with identical token budgets and one
retry-with-error-feedback. Every translator may refuse. Person
identity comes only from extraction output, never from ground truth.

**Corpora and ground truth.** Synthetic populations (125 to 125,000
persons; 8 fact types; 3–4 paraphrase templates per type; ~30% of
persons receive a later location update creating version chains).
Because the corpus is generated, every question has a computable
ground truth — no human grading, no LLM judge.

**Query mix** (weights fixed in advance): point lookup 30%,
aggregation 15%, distribution 10%, intersection 10% (half verified
empty), negation/comparison 10%, version history 10%, unanswerable
10%, paraphrase stress 5%. Scoring is type-specific (exact integers
for counts, tie-tolerant set comparison for top-K, word-boundary match
for values); on unanswerable questions only an explicit refusal scores,
and concrete answers are tracked as hallucinations. ≥5 seeds wherever
an LLM is in the loop (reduced to 3/2 at the two largest scale tiers;
logged).

**Cost discipline.** All dollar figures are computed from API token
usage returned by the provider, never estimated; cost extrapolations
beyond 10× measured scale are banned by the protocol.

## 4. Phase 1 — can one schema absorb prose?

480 NL facts/seed, 5 seeds per iteration. Three scorer-visible
properties per fact: entity attribution, canonical-slot placement, and
(from v3) *spurious fills* — pollution of another fact type's
aggregation slot.

| Iteration | Semantic accuracy | Clean (no pollution) |
|---|---|---|
| v1 baseline prompt | 88.5% ± 1.0 | — |
| v2 + extraction rules | 96.6% ± 0.6 | — |
| v3 + slot conventions | **99.8% ± 0.1** | **96.1% ± 0.5** |

Entity attribution was 100% throughout. Each iteration's failures were
diagnosed from per-fact logs (two-entity inversion, origin/location
conflation, a template artifact extracting the literal value "home")
and fixed by prompt rules; each fix was re-measured on fresh seeds. The
v2 round produced the methodologically important observation: per-fact
accuracy and *aggregation-grade slot consistency* are different
properties — v1 was less accurate but more uniform, and exact counts
need uniformity. This motivated the precision metric and the v3
conventions. Measured cost: $0.0011/fact.

## 5. Phases 2 and 3 — four systems, one interface

### 5.1 Systems

| System | Storage | NL → query |
|---|---|---|
| Ada | universal fact table | LLM → 1 of 8 closed ops |
| EAV + SQL | generic SQLite EAV (indexed, batch-loaded) | LLM → SQL |
| Graph | Kùzu; hand-written predicate→edge mapping | LLM → Cypher |
| RAG | MiniLM embeddings, top-8 | LLM renders from snippets |

The EAV baseline is the protocol's designated killer: it shares Ada's
zero-DDL property, so if it matched Ada, the substrate would have no
demonstrated value beyond the schema as an extraction target. The
pre-registered kill condition was written accordingly.

### 5.2 Phase 2 — accuracy under real extraction (~500 facts, 5 seeds)

| System | Accuracy | $/query | Ingest errors |
|---|---|---|---|
| Ada | **92.3% ± 2.8** | $0.0007 | **0** |
| Kùzu + Cypher | 91.7% ± 1.7 | $0.0005 | 154 |
| EAV + SQL | 70.7% ± 3.5 | $0.0009 | 0 |
| RAG | 60.0% ± 2.6 | $0.0002 | 0 |

Per the pre-registered terms: the kill condition did not fire (EAV
−21.6 points, far outside noise), and the win condition was **not
met** — Ada and the graph tie on accuracy (paired per-seed differences
+6.7, −3.3, −1.7, +1.7, 0.0) and the graph wins the cost and latency
tie-breakers. Ada wins the remaining criterion: its ingestion dropped
nothing, while the graph's hand-written predicate→edge mapping —
written specifically for this corpus — silently dropped 154 facts
(~6%). Per shape, Ada was perfect on lookup (90/90), distribution,
intersection, negation, history, and refusal; text-to-SQL failed
multi-value same-slot intersections (8/30) and version queries (16/30)
with *executing, confidently wrong* SQL — the worst failure mode a
memory can have. The shared aggregation ceiling (~64% for every
extraction-fed system) is an ingestion-consistency property, not a
query-architecture one: no engine can recover a fact filed in the
wrong slot.

The honest summary: **under real extraction, schema-on-write matches a
hand-schema'd graph at zero schema-design cost, and decisively beats
the general-purpose alternatives.**

### 5.3 Phase 3 — scale sweep, ~1K → ~1M facts

Ground-truth structured ingestion (extraction is per-fact and already
measured; amendment §7-3); RAG embeds raw sentences.

| Facts | Ada | Kùzu | EAV+SQL | RAG |
|---|---|---|---|---|
| 1,037 | 97.7 ± 1.5 | 96.7 ± 3.1 | 85.0 ± 3.5 | 56.7 ± 2.6 |
| 10,375 | 98.3 ± 1.2 | 97.7 ± 2.2 | 85.3 ± 2.2 | 43.0 ± 4.3 |
| 103,750 | 99.4 ± 1.0 | 96.7 ± 2.9 | 85.0 ± 2.9 | 31.1 ± 5.1 |
| 1,037,500 | **100.0 ± 0.0** | 96.7 ± 0.0 | 78.3 ± 2.4 | 24.2 ± 1.2 |

Ada's accuracy does not degrade with corpus size; RAG's decays
monotonically — the bounded-retrieval wall as a measured curve rather
than an argument. At one million facts Ada ingests in ~9 s and its
worst engine operation costs 341 ms (measured linear in N, as an
unindexed scan must be), which disappears under the ~1.2 s
LLM-translation floor every system shares. Engine-to-engine the graph's
indexes are ~24× faster at this scale; the boundary of Ada's claim is
explicit: beyond ~10M facts, or for callers without an LLM in the
loop, the scan needs an index.

## 6. Findings beyond the scoreboard

**Zero hallucinations, all systems.** Across ~7,000 graded answers, no
system fabricated an answer to an unanswerable question. Gating an LLM
behind retrieval-or-refusal works; the differences between
architectures lie in what each *can* answer, not in invented answers.

**Refusal asymmetry is measurable.** On verified-empty intersections,
Ada and the graph answer "none" (a confident, correct empty set);
text-to-SQL and RAG say "I don't know" — which sounds safe but is
wrong, because the question is answerable. Distinguishing structural
emptiness from ignorance requires seeing the whole corpus.

**Open query languages are an operational hazard.** One LLM-generated
SQL statement was effectively a cartesian self-join over 4M rows and
consumed 14 CPU-hours before we killed it. Both open-language baselines
now run under 15 s timeouts (timeout → honest failure). A closed
operation set excludes this failure class by construction: every Ada
operation is bounded. We regard this as the strongest *qualitative*
argument for closed op sets fronting model-driven systems.

**The harness failed three times, and the record keeps all three:**
ground-truth "empty" intersections that were not empty at scale
(penalizing systems for being right — fixed by escalating to verified
emptiness, contaminated results retained alongside corrected ones); an
O(N²) loader in our own EAV baseline; and the runaway query above. We
believe benchmark credibility is carried less by headline numbers than
by whether the authors' own mistakes are visible.

## 7. Related work

Ada occupies the gap between three mature lines: dense-retrieval RAG
(similarity, not composition), knowledge graphs and text-to-Cypher
(composition at the price of ontology), and text-to-SQL over
schema-flexible stores (no DDL, but an open query language with the
failure modes measured here). The universal-schema idea descends from
frame semantics and slot-filling IE; the contribution here is not the
lattice itself but the measured demonstration that *one fixed lattice
plus a write-time LLM plus a closed read surface* is competitive with
per-domain engineering. Bounded product memory features form a fourth
line whose failure is arithmetic (eviction) and is not re-measured.

## 8. Limitations

Corpora are synthetic, with eight fact types and template-generated
paraphrase; real prose is messier than anything measured here, and the
professional-services example in the repository is a demo, not a
measurement. Multi-hop questions are out of scope by design; a graph
remains the right tool for them. The Phase 2 tie under real extraction
— not Phase 3's clean-ingestion lead — is the production-grade
accuracy claim. All extraction and translation used one model family
at one size; translator-prompt parity across systems is bounded by
using identical models and budgets but is imperfect by construction.
Engine latency is unindexed and linear; the ~10M-fact boundary is
extrapolated from a measured linear fit, within the protocol's 10×
extrapolation limit. Aggregation exactness under real extraction is
bounded by extraction consistency (~96% clean), not by the query
engine.

## 9. Conclusion

A memory that an LLM writes into once, through one fixed schema, and
reads from through eight bounded operations, delivers: extraction at
99.8% per-fact fidelity and $0.001/fact; accuracy that ties a
hand-schema'd graph under real extraction and does not degrade through
one million facts; native versioned belief; refusal that distinguishes
emptiness from ignorance; and immunity to the runaway-query class that
open query languages expose. The claim is deliberately narrow: for the
question shapes that dominate assistant memory — lookup, aggregate,
intersect, history, refuse — schema-on-write removes the engineering
that makes structured memory expensive, at no measured accuracy cost.
Where it loses (multi-hop, machine-speed engine latency at extreme
scale), it loses legibly, and we have said where.

## Reproducibility

Everything in this paper regenerates from the repository:
`benchmark/PROTOCOL.md` (pre-registration + amendment log),
`benchmark/phase{1,2,3}/REPORT.md` (per-phase detail),
`results*/` directories (per-question raw logs for every system, seed,
and tier), and the runner commands at the top of each phase report.
The runtime itself is `ada/` — pure Python, no compiled dependencies.
