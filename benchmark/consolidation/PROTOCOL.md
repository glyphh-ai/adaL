# Consolidation eval — pre-registered protocol

*Registered 2026-06-12, BEFORE any results were produced. The
manipulated variable is the consolidation pass alone; everything else
(ask path, read-time identity resolution, scorer, thresholds) is the
shipped code, identical in both arms.*

## Question

Does the offline consolidation pass (`ada.memory.consolidate`) improve
first-person conversational retrieval over doing nothing — without
degrading third-person retrieval?

## Corpus (synthetic, deterministic per seed)

Per seed: 20 personas with profiles (name, spouse, two children, city,
color, job). Persona 0 is the operator. Facts are written the way a
real pre-resolution database accumulated them (modeled on the actual
database that motivated this work):

- Operator facts in the first person: identity ("my name is X",
  "i am X"), marriage, city, color. Half carry legacy universal slots
  with `subject: "speaker"` placeholders; half are slotless.
- One typo pair: an earlier misspelled version of the spouse fact and
  its later correction, both unkeyed (neither supersedes the other).
- The children fact is third-person via the spouse ("S has two
  children A and B") — answering "who are my children?" requires the
  operator→spouse link.
- One stored question ("who are my children?").
- Third-person control facts for the other 19 personas: residence and
  job, with clean entity slots.

## Conditions

- **A (no-op)**: load the corpus, ask.
- **B (consolidate)**: run `consolidate(me=operator)` once, reload, ask.

Both arms ask through the shipped path: `resolve_question_identity`
with me=operator, then `CognitiveSurface.ask` (two-hop). Offline:
HeuristicEnricher, no LLM renderer, no API calls — fully deterministic
given the seed.

## Question sets

- **Conversational (first-person)**, 4 per seed: wife, children, city,
  color. Ground truth from the operator's profile.
- **Third-person control**, 10 per seed: residence and job for 5
  non-operator personas.

## Grading (top-1 grounding)

An answer is **correct** iff ask() does not refuse AND every
ground-truth value token appears in the grounding fact's content
(`answer.fact.content`). Refusal on an answerable question is wrong.
This is stricter than what a user sees (the LLM renderer reads the
top-5), so reported numbers are a floor.

Secondary metric (reported, not gating): **top-5 visibility** — the
ground-truth tokens appear in any of the top-5 recall results.

## Seeds and reporting

Seeds 1–5. Report mean ± std per condition per question set, plus the
per-question breakdown. All numbers go in REPORT.md whichever way they
fall.

## Win / kill conditions

- **WIN**: conversational top-1 accuracy (B − A) ≥ +10 points absolute,
  AND third-person control accuracy within ±2 points.
- **KILL**: conversational improvement < +5 points, or any third-person
  degradation > 2 points → consolidation does not ship as a default or
  scheduled pass; it stays a manual operator tool with documented
  limits.
- Between +5 and +10: ships as opt-in, result recorded as weak.

## Amendments

**A1 (2026-06-12, after seeds 1–5).** Value pools (10 cities, 6 colors,
6 jobs) were smaller than the persona count (20), so token-presence
grading produced false positives: the no-op arm was credited for
"sofia lives in boston" on the operator's "where do I live?" because
sofia shares the operator's city. The consolidated arm's genuinely
correct grounding ("i live in boston") scored the same — ambiguity
masked a real difference. Fix: every persona's city/color/job is
unique within a seed (pools expanded to 20). Fresh seeds 6–10; the
seed 1–5 numbers are kept in results/results-seeds1-5.json for the
record. No change to conditions, grading rule, or win/kill bars.
