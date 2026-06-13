# Recall benchmark — report

*Protocol registered before results. Frozen corpus: 360 facts × 5
seeds, 7,400 queries, LLM-generated keyword-filtered phrasings. Three
scorers rank the same fact set per query; lexical == Ada's shipped
`score_thought`.*

## Result — hit@1 / hit@3 / MRR (mean over 5 seeds, %)

| query type | lexical | embedding (MiniLM) | hybrid (RRF) |
|---|---|---|---|
| direct | 97.3 / 97.8 / 97.9 | 91.3 / 99.7 / 95.4 | 96.2 / 99.4 / 97.7 |
| paraphrase | **14.5** / 48.4 / 38.5 | **76.6** / 97.1 / 86.7 | 34.6 / 89.4 / 59.5 |
| conceptual | **17.2** / 48.8 / 40.3 | **68.7** / 93.2 / 81.2 | 39.8 / 85.3 / 61.3 |
| contextual | **15.0** / 47.4 / 38.6 | **57.7** / 92.4 / 74.7 | 34.6 / 80.9 / 57.7 |

**Fuzzy-set hit@3** (paraphrase + conceptual + contextual):
lexical **48.2** · embedding **94.3** · hybrid 85.2.

## Verdict: embedding WINS, decisively. Pre-registered bar cleared 4×.

The bar was +10 hit@3 on the fuzzy set without regressing direct by >2.
Embedding delivers **+46.1** hit@3 on the fuzzy set and *gains* on
direct (97.8 → 99.7). Not close.

## The damning finding — lexical recall is at chance

Six facts per person; the query always names the person. So once the
query stops reusing the fact's keyword, the only token that matches is
the name — which is shared by all six of that person's facts.

- Lexical paraphrase **hit@1 = 14.5% ≈ 1/6 (random among the person's
  facts).** hit@3 = 48% ≈ 3/6. **Lexical recall carries no signal about
  *which* fact beyond the name.**
- This is the answer to "how can anyone query Ada if it's purely
  lexical?" — for natural phrasing, **they can't.** Ask "where is X
  based?" instead of "where does X live?" and lexical recall is a coin
  toss over X's facts. Embeddings lift hit@1 to 58–77%.

The structured op engine (Phase 2/3, 92–100%) is unaffected — that path
never used lexical recall. The failure is specific and total to the
**free-text `ask`/`recall`/`think` path**, which is the path a human or
naive client actually hits.

## Gating (the hook / context-injection use case)

False-injection at τ tuned to keep 80% of correct top-1:

| method | τ | negatives wrongly injected | neg median score |
|---|---|---|---|
| lexical | 0.233 | **96.5%** | 0.233 |
| embedding | 0.589 | **43.0%** | 0.578 |
| hybrid | 0.033 | 81.5% | 0.033 |

- **Lexical cannot gate at all** — negatives score as high as positives
  (the name matches), so a lexical confidence floor injects garbage.
- **Embedding gates meaningfully better** but still injects 43% of true
  negatives at this operating point: a query about an *absent* attribute
  ("X's pet's name") still embeds near X's facts. Knowing-you-don't-know
  for plausibly-phrased absent attributes is genuinely hard.
- **Hybrid/RRF scores don't threshold** — rank-fusion isn't calibrated
  for a confidence floor. RRF also underperforms pure embedding on
  ranking here; it is not the answer.

## Implications

1. **The embedding arm must ship for the recall path.** Lexical-only
   `ask`/`recall` is unreliable for anything but keyword queries — this
   is now measured, not suspected.
2. **Embedding alone beats hybrid** on this workload; if we add hybrid,
   it's for keeping the direct-query crispness, not for the fuzzy gains.
3. **For the Claude hook (#44):** embedding recall surfaces the right
   fact in the top-3 ~92% of the time when one is relevant, but needs a
   **conservative τ** to control the 43% false-injection on irrelevant
   contexts. The hook should inject only above a high floor and accept
   lower recall — precision matters more than recall when you're adding
   to every prompt.

## Boundaries

- One embedding model (MiniLM, 384-dim). A larger/instruction model
  would likely raise the fuzzy and gating numbers; MiniLM is the floor.
- Synthetic single-attribute facts; real facts are richer and may help
  or hurt both arms. The *relative* gap (lexical at chance vs embedding
  strong) is the robust signal.

## Reproduce

```bash
# regenerate the frozen corpus (needs an API key)
ANTHROPIC_API_KEY=... PYTHONPATH=. .venv-bench/bin/python \
  benchmark/recall/generate_corpus.py
# run (offline, deterministic)
PYTHONPATH=. .venv-bench/bin/python benchmark/recall/run_recall.py
```

Raw per-query ranks: `results/results.json`.
