"""
Baseline — Claude with the ENTIRE Aurora corpus in context (no Ada).

The fair comparison for 'is Ada actually buying us something on long-term
memory continuity, or is a big context window enough?' We send Claude all
77 Aurora facts in a single prompt for every query, ask the same 25
questions used by aurora_versioned.py, and grade with the same rubric.

If LLM+full-context wins, the substrate isn't earning its keep. If
Ada+LLM (the aurora_versioned.py result) wins, the substrate's discipline
on versioning / absence / synthesis is the contribution.

    ANTHROPIC_API_KEY=... PYTHONPATH=. python benchmark/llm_only_baseline.py
"""

from __future__ import annotations

import os
import sys
import time
sys.path.insert(0, "scripts")
from hard_test import SESSION_1, QUERIES  # same corpus, same 25 questions


SYSTEM = (
    "You are a memory-only Q&A system. You will be given ALL the facts you "
    "know about a project, followed by a question. Use ONLY the facts. If "
    "the answer isn't there, say \"I don't know.\" Be concise."
)


def main() -> None:
    try:
        import anthropic
    except ImportError:
        print("anthropic SDK required. pip install anthropic.")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set.")
        return

    client = anthropic.Anthropic()
    model = os.environ.get("ADA_MODEL", "claude-haiku-4-5-20251001")

    # The full corpus, sent verbatim with every query.
    corpus = "\n".join(f"- {text}" for text, _key in SESSION_1)

    REFUSAL_PHRASES = (
        "don't know", "do not know", "no information",
        "do not contain", "doesn't contain", "doesn't include",
        "cannot answer", "can't answer", "not in the memories",
        "memories don't", "memories do not",
    )

    by_cat: dict[str, list[bool]] = {c: [] for c in "ABCDEF"}
    rows = []
    t0 = time.time()
    for i, (cat, q, want_a, want_b) in enumerate(QUERIES, 1):
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"FACTS:\n{corpus}\n\nQuestion: {q}"}],
        )
        ans = resp.content[0].text.strip().lower()
        if cat == "E":
            ok = any(p in ans for p in REFUSAL_PHRASES)
        else:
            ok = bool(want_a) and want_a.lower() in ans
            if not ok and want_b:
                ok = want_b.lower() in ans
        by_cat[cat].append(ok)
        rows.append((cat, q, ans, ok))
        mark = "✓" if ok else "✗"
        print(f"  [{cat}{i:>2}] {mark}  {q[:55]}")
    print(f"\n  ran 25 queries in {time.time() - t0:.1f}s\n")

    print("─── Category breakdown (LLM + full corpus, NO Ada) ───")
    names = {
        "A": "Direct recall",
        "B": "Multi-hop inference",
        "C": "Version-aware recall",
        "D": "Schema introspection",
        "E": "Absence detection",
        "F": "Long-horizon synthesis",
    }
    total_ok, total = 0, 0
    for c in "ABCDEF":
        oks = by_cat[c]
        n_ok = sum(oks)
        n = len(oks)
        total_ok += n_ok
        total += n
        pct = 100 * n_ok / n if n else 0
        print(f"   {c}. {names[c]:<25} {n_ok}/{n}  ({pct:>3.0f}%)")
    print()
    print(f"   OVERALL: {total_ok}/{total}  ({100*total_ok/total:.0f}%)")


if __name__ == "__main__":
    main()
