# Professional services on Ada

A demo of Ada as the memory layer for a consulting practice —
**Meridian Advisory**, a fictional ~40-person firm. ~70 natural-language
facts of the kind that pile up in any practice: engagements, staffing,
fee models, rate cards, policies, and lessons learned.

```bash
ANTHROPIC_API_KEY=... PYTHONPATH=. python examples/professional-services/demo.py
```

What it shows, in order:

1. **Ingestion is just prose.** Facts go in as sentences ("The Atlas
   engagement is billed time-and-materials."). The enricher maps each
   into the universal schema at write time — one cached LLM call per
   fact, ~$0.001. Reads never call an LLM (the optional answer renderer
   is the only exception).

2. **Versioned beliefs.** Facts written under a key supersede their
   predecessors: the travel policy, partner rates, engagement status,
   and a staff relocation each show a queryable v1 → v2 chain.
   "Which office is Dan in **now**?" returns Boston; the Chicago era is
   one `history` call away.

3. **Exact structured queries.** "How many engagements are fixed-fee?"
   is a slot scan, not a retrieval guess — the answer is a count with
   the matching entities listed.

4. **Honest refusal.** "What's our AI-usage policy?" was never stated.
   The empty slot refuses; nothing is invented for the things a firm
   never wrote down.

This directory is a **demo of the developer experience, not a
benchmark** — the measured, pre-registered claims live in
[`benchmark/PROTOCOL.md`](../../benchmark/PROTOCOL.md) and the phase
reports next to it. In particular, extraction here is subject to the
same ~96% clean-extraction rate measured in Phase 1: on a corpus this
size, expect a fact or two to land in a non-canonical slot.

To use the same corpus interactively: `make repl`, then `write` /
`ask` / `count` / `top` / `history` — or start the server (`make dev`)
and point any MCP client at `http://localhost:8002/mcp`.
