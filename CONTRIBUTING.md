# Contributing to Ada

Ada is schema-on-write memory for LLMs. The project has one unusual
house rule, and it's load-bearing:

> **Claims require measurements, and measurements require
> pre-registration.** Every performance or accuracy claim in this repo
> traces to `benchmark/PROTOCOL.md` and committed raw logs — including
> the results we lost. PRs that add capability claims without numbers,
> or tune a benchmark after seeing its results, will be asked to redo
> the work on fresh seeds. Read the protocol's amendment log (§7) to
> see how we handle our own mistakes; the same standard applies to
> everyone.

## Development setup

```bash
make install        # .venv + editable install + dev extras
make test           # pytest (fast, offline — no API key needed)
make repl           # admin REPL (auto-starts a local server)
```

Lint and tests must pass (`ruff check`, `pytest -q tests/`); CI runs
both on 3.11–3.13 plus a full import sweep.

## What contributions look like here

- **Runtime changes** (`ada/`, `domains/`): keep the read path
  deterministic and LLM-free. The query surface is a closed op set on
  purpose — new ops need a a clear semantics and tests, not a query
  language.
- **Extraction/prompt changes** (`ada/cognitive/universal.py`): these
  are measured by Phase 1. Run it on fresh seeds and include the
  numbers in the PR (`benchmark/phase1/run_phase1.py`, ~$0.50 of API
  spend per 5-seed run).
- **Benchmark changes**: scorer or corpus changes require a §7
  amendment entry and a re-run; never re-score recorded results.
- **User-facing surfaces** (REPL look, command names, tool names,
  output formats): open an issue first — presentation changes are
  deliberate product decisions.

## Honesty conventions

- Costs are measured from API token usage, never estimated.
- Simulated baselines are labeled as arithmetic, never presented as
  measurements.
- A refusal is a feature; a confident wrong answer is the worst bug in
  the codebase. Tests that assert refusal behavior are not optional.
