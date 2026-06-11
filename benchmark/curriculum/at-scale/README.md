# At-scale benchmark — proving Ada handles what LLMs structurally can't

The argument up to here has been: *Ada is a memory substrate that does
things vector DBs and KGs can't.* This directory makes the **stronger
empirical claim**:

> At corpus sizes that exceed an LLM's context window, Ada answers
> compositional queries deterministically. The LLM cannot answer them
> at all. RAG can retrieve but cannot aggregate.

## Three-way result at n=1500 (30,000 facts, ~1.08M tokens)

| Query | Truth | Ada | LLM-only | RAG (top-40 + Claude) |
|---|---|---|---|---|
| A. count of `perceptual.color=blue` | 270 | **270 ✓** | impossible | "I don't know" ✗ |
| B. count of `works_as=engineer` | 71 | **71 ✓** | impossible | "I don't know" ✗ |
| C. top-5 cities | Antwerp/Denver/York/Fresno/Vienna | **exact ✓** | impossible | "I don't know" ✗ |
| D. top-5 colors | black/red/white/brown/orange | **exact ✓** | impossible | "I don't know" ✗ |
| E. people who are blue ∧ Austin ∧ chess | [] | **[] ✓** | impossible | "I don't know" ~✓ |

**Final scoreboard: Ada 5/5 · LLM-only 0/5 · RAG 1/5.**

Ada's queries ran in 30–47 ms each. RAG's queries ran in ~870 ms (the
Claude call), and 4 of the 5 returned "I don't know" because the
top-40 retrieval contained *individual person facts*, not the
aggregation answer. The single RAG hit was on query E where the truth
is the empty list — RAG honestly said it didn't know and that graded
as matching.

The deeper read: **RAG isn't *failing to find* the answer. Top-K is
the wrong shape for aggregation. No retrieval system can answer "how
many engineers exist" without scanning every entry**, which is exactly
what Ada does and what RAG-by-design doesn't.

## Context-window math (current Claude models)

| Corpus n (persons) | Facts | ≈Tokens | Haiku (200K) | Sonnet (1M) | Opus (200K) |
|---|---|---|---|---|---|
| 100 | 2,000 | ~70K | ✓ | ✓ | ✓ |
| 300 | 6,000 | ~210K | **exceeds** | ✓ | **exceeds** |
| 1,000 | 20,000 | ~700K | exceeds | ✓ | exceeds |
| 1,500 | 30,000 | **~1.08M** | exceeds | **exceeds** | exceeds |
| 5,000 | 100,000 | ~3.5M | exceeds | exceeds | exceeds |
| 50,000 | 1,000,000 | ~35M | far exceeds | far exceeds | far exceeds |

The crossover is **n≈285 for Haiku/Opus** and **n≈1,425 for Sonnet**. Past
those points the LLM-only baseline is *structurally impossible*, not
slow or expensive.

## The five compositional queries

| Query | Substrate operation | What it tests |
|---|---|---|
| A. `perceptual.color = blue` count | Role-value scan | Cross-fact role aggregation |
| B. `works_as = engineer` count | Relational predicate match | Predicate-targeted retrieval + count |
| C. Top-5 cities | Distribution over `spatial.location` | Aggregation / counting |
| D. Top-5 colors | Distribution across `perceptual.color` | Cross-domain enumeration |
| E. blue ∧ Austin ∧ chess | Three-way conjunction on roles | Multi-role intersection |

Each is a *single query*. Each is deterministic. Each result is
auditable to the specific facts that contributed.

## Run it

```bash
# Three-way comparison at corpus-busts-Opus scale (~7 minutes total)
ANTHROPIC_API_KEY=sk-ant-... PYTHONPATH=. python benchmark/curriculum/at-scale/bench_rag.py --n 1500

# Substrate-only (faster, no API costs)
PYTHONPATH=. python benchmark/curriculum/at-scale/bench.py --n 1000

# Scale up further
PYTHONPATH=. python benchmark/curriculum/at-scale/bench_rag.py --n 5000   # ~35min, busts Sonnet 3.5×
```

## Sample output (n=1,500)

```
generated 30,000 facts about 1,500 persons
~1,076,957 tokens · 32 MB

context fit:
  Haiku 4.5  (200K):    EXCEEDS by 5.4×
  Sonnet 4.6 (1M):      EXCEEDS by 1.1×
  Opus 4.x   (200K):    EXCEEDS by 5.4×

ground truth:
  blue_count       : 270
  engineer_count   : 71
  top5_cities      : Antwerp/Denver/York (tied @64), Fresno (59), Vienna (58)

loaded 30,000 thoughts in 162.9s (184 facts/sec)

A. How many people have blue as their color?
   ADA      ( 30.4 ms)  ✓  270
   LLM-ONLY              ✗  IMPOSSIBLE — corpus exceeds Opus context
   RAG      (892.5 ms)  ✗  "I don't know..."

B. How many people work as engineers?
   ADA      ( 32.7 ms)  ✓  71
   LLM-ONLY              ✗  IMPOSSIBLE
   RAG      (875.6 ms)  ✗  "I don't know..."

(... C/D/E same shape ...)

final scoreboard at n=1,500 (1,076,957 tokens):
  Ada (substrate, zero LLM)   : 5/5
  LLM-only (full corpus)       : 0/5  (corpus too big)
  LLM + naive RAG (top-40)     : 1/5
```

## What this proves

Three claims, each empirically demonstrated:

1. **Ada answers** in deterministic, auditable, sub-50ms time at 1M+
   token corpus scale.
2. **LLM-only is bounded by context window.** Past n≈285 (Haiku/Opus) or
   n≈1,425 (Sonnet) it cannot see the data. Not "slow" — *cannot*.
3. **RAG is a workaround** for retrieval, not for aggregation. Top-K
   surfaces individual facts; counting and distribution queries require
   scanning the whole substrate, which is what Ada does natively and
   what RAG by design doesn't.

These three are the architectural argument made empirical. Any specific
corpus and query set can be slotted in; the conclusion holds.

## Files

```
generate.py     deterministic synthetic-corpus generator
bench.py        Ada-only timing benchmark (no API needed)
bench_rag.py    three-way comparison: Ada / LLM-only / RAG (needs API key)
corpus.json     last-generated corpus (gitignored)
README.md       this file
```

