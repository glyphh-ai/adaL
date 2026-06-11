"""
Meridian Advisory demo — Ada as a professional-services memory.

Ingests ~70 NL facts about a fictional consulting firm through Ada's
real write path (LLM enricher → universal schema), then walks through
the query surfaces a practice lead would actually use:

  - targeted retrieval with grounding ("who leads Atlas?")
  - versioned history ("what did the travel policy used to say?")
  - structured counts and distributions ("how many fixed-fee engagements?")
  - honest refusal ("what's our AI-usage policy?" — never stated)

This is a DEMO of the developer experience, not a benchmark — the
measured claims live in benchmark/. Requires ANTHROPIC_API_KEY (the
enricher maps text into the schema at write time; reads are LLM-free
except the optional answer renderer).

    ANTHROPIC_API_KEY=... PYTHONPATH=. python examples/professional-services/demo.py
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from facts import FACTS  # noqa: E402

from ada import CognitiveSurface, ThoughtSpace, build_llm_renderer  # noqa: E402
from ada.encoder.llm_enricher import auto_enricher  # noqa: E402

D, C, B, R = "\033[38;5;244m", "\033[38;5;116m", "\033[1m", "\033[0m"


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required — the enricher maps each fact "
              "into the universal schema at write time.")
        sys.exit(1)

    enricher = auto_enricher()
    space = ThoughtSpace(enricher=enricher)
    surface = CognitiveSurface(space, renderer=build_llm_renderer())

    # ── Ingest (parallel pre-warm of the enricher cache, then absorb
    #    in corpus order so version chains build correctly) ───────────
    print(f"{B}── Ingesting {len(FACTS)} facts about Meridian Advisory ──{R}")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda f: enricher.enrich(f[0]), FACTS))
    for text, key in FACTS:
        space.absorb(text, key=key, speaker="incoming")
    stats = space.stats()
    print(f"{D}   {stats['count']} thoughts, {stats['versioned_keys']} versioned "
          f"keys, {time.time()-t0:.0f}s (write-time LLM; reads are LLM-free){R}\n")

    # ── 1. Targeted retrieval, grounded ──────────────────────────────
    print(f"{B}── ask: targeted retrieval (refuses rather than guesses) ──{R}")
    for q in [
        "Who is the lead partner on the Atlas engagement?",
        "What kind of engagement is Northwind?",
        "What is the current partner billing rate?",
        "Which office is Dan Okafor in now?",
    ]:
        a = surface.ask(q)
        print(f"  {q}\n    → {C}{a.rendered}{R}")
        if a.fact:
            print(f"      {D}grounded in: \"{a.fact.content}\"{R}")
    print()

    # ── 2. Versioned history ─────────────────────────────────────────
    print(f"{B}── history: how beliefs changed over time ──{R}")
    for key, label in [("policy.travel", "travel policy"),
                       ("rates.partner", "partner rate"),
                       ("eng.northwind.status", "Northwind status"),
                       ("staff.dan.office", "Dan Okafor's office")]:
        chain = space.history(key)
        print(f"  {label} ({len(chain)} versions):")
        for t in chain:
            print(f"    {D}v{t.metadata.get('_version')}:{R} {t.content}")
    print()

    # ── 3. Structured queries (exact, LLM-free) ──────────────────────
    print(f"{B}── structured queries: exact scans over the schema ──{R}")
    fee_dist = space.distribution("relational", "object", top_k=8)
    print(f"  {D}most common relational objects:{R} {fee_dist}")
    profiles = space.entity_profiles()
    fixed = [n for n, p in profiles.items()
             if "fixed-fee" in p.get("relational.object", set())
             or "fixed fee" in p.get("relational.object", set())]
    print(f"  engagements billed fixed-fee: {C}{len(fixed)}{R} {D}{sorted(fixed)}{R}")
    healthcare = [n for n, p in profiles.items()
                  if any("healthcare" in v for vs in p.values() for v in vs)]
    print(f"  entities touching healthcare: {C}{len(healthcare)}{R} {D}{sorted(healthcare)}{R}")
    print()

    # ── 4. Honest refusal ────────────────────────────────────────────
    print(f"{B}── refusal: what was never written down stays unknown ──{R}")
    for q, note in [
        ("What is Meridian's policy on AI tool usage?", ""),
        ("What is Meridian's parental leave policy?", ""),
        ("What is Sofia Reyes's billing rate?",
         "her personal rate was never stated — only the manager rate card"),
    ]:
        a = surface.ask(q)
        print(f"  {q}\n    → {C}{a.rendered}{R}")
        if note:
            print(f"      {D}({note}){R}")

    print(f"\n{D}Demo complete. The same substrate is reachable over MCP "
          f"(make dev → http://localhost:8002/mcp).{R}")


if __name__ == "__main__":
    main()
