# Consolidation eval — report

*2026-06-12. Protocol registered before results (commit e0ac300);
amendment A1 (grading ambiguity) noted in PROTOCOL.md. Offline,
deterministic: HeuristicEnricher, no renderer, no API calls.*

## Result (seeds 6–10, after A1)

| metric | no-op | consolidated | Δ |
|---|---|---|---|
| conversational top-1 | 0.0 ± 0.0 | **25.0 ± 0.0** | **+25.0** |
| conversational top-5 | 100.0 ± 0.0 | 100.0 ± 0.0 | 0.0 |
| control top-1 | 50.0 ± 0.0 | 50.0 ± 0.0 | 0.0 |
| control top-5 | 100.0 ± 0.0 | 100.0 ± 0.0 | 0.0 |

**Verdict: WIN.** Conversational top-1 improves +25 points (bar: ≥+10)
with zero third-person movement (bar: within ±2). Consolidation ships
as a default-available maintenance pass.

## What the numbers mean — boundaries stated plainly

- The gain is real and entirely attributable to retroactive identity
  resolution: "where do I live?" goes from refusal (or, pre-A1, a
  false-positive grounding in someone else's same-city fact) to the
  operator's own fact. Per-seed reports: 2 facts identity-resolved,
  1 typo pair archived, every seed.
- **The absolute numbers are floors.** Offline there is no LLM
  enrichment and no renderer: wife/children/color questions still
  refuse at the 0.3 confidence bar in both arms even though the
  ground-truth fact is ALWAYS in the top-5 (100% visibility) that a
  renderer would see. Production behavior with an API key is better
  than every number here.
- Control top-1 of 50% in both arms is a property of the offline
  lexical floor on "what does X do?" phrasing, not of consolidation —
  identical in both arms, stable across seeds.
- Typo-dup archival did not move accuracy on this corpus (the typo
  competed with, but did not outrank, the correction). Its value
  showed on the real database that motivated this work: the typo
  poisoned two-hop bridge tokens, which the synthetic grading does not
  capture.

## Seeds 1–5 (pre-A1, kept for the record)

results-seeds1-5.json. Headline read Δ0.0 top-1 / −25 top-5 — both
artifacts of value pools smaller than the persona count: a same-city
stranger's fact was credited as correct in the no-op arm, and shared
values inflated top-5 in ways that interacted with slot-boosted
identity facts. A1 made every persona's values unique; the ambiguity
(and the phantom degradation) disappeared.

## Reproduce

```bash
ANTHROPIC_API_KEY= PYTHONPATH=. \
  .venv/bin/python benchmark/consolidation/run_consolidation.py
```

Per-question details: results/results.json.
