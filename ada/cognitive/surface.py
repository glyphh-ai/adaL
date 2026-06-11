"""
Two cognitive surfaces on the same substrate:

    think(input)   — broad recall. Surfaces the facts that match,
                     without interpretation. No question/answer framing.

    ask(question)  — targeted retrieval. Returns one fact and a
                     confidence, or refuses honestly with "I don't know."

Same substrate, different recall policies. think is broader and
unfiltered; ask is narrower and disciplined. The MCP layer exposes both —
an LLM calls think when it wants context, ask when it needs a fact.

Usage:
    surface = CognitiveSurface(space, renderer=...)
    activation = surface.think("project aurora")
    answer     = surface.ask("what hull does aurora use?")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ada.memory.thought_space import StoredThought, ThoughtSpace


# ── Return types ─────────────────────────────────────────────────────

@dataclass
class Activation:
    """What think() returns — raw recall output, no synthesis."""
    input: str
    thoughts: list[StoredThought] = field(default_factory=list)
    similarities: list[float] = field(default_factory=list)

    def __iter__(self):
        return iter(zip(self.thoughts, self.similarities))

    def __len__(self) -> int:
        return len(self.thoughts)


@dataclass
class Answer:
    """What ask() returns — one fact and a confidence, or 'I don't know'."""
    question: str
    fact: Optional[StoredThought] = None
    confidence: float = 0.0
    rendered: str = ""           # natural-language form (via renderer)
    refused: bool = False        # True when confidence < threshold


# ── The surface ──────────────────────────────────────────────────────

class CognitiveSurface:
    """The two-tool API on Ada's substrate."""

    def __init__(
        self,
        space: ThoughtSpace,
        renderer=None,
        min_confidence: float = 0.3,
        **_compat,
    ):
        # **_compat swallows the legacy cognitive= arg from the HDC era.
        self.space = space
        self.renderer = renderer
        self.min_confidence = min_confidence

    # ── think — broad recall ──────────────────────────────────────────

    def think(self, input_text: str, top_k: int = 10) -> Activation:
        """What does this input surface? No filtering for 'the answer'."""
        results = self.space.recall(input_text, top_k=top_k, exclude_speakers=("ada",))
        return Activation(
            input=input_text,
            thoughts=[r.thought for r in results],
            similarities=[r.global_similarity for r in results],
        )

    # ── ask — targeted retrieval ──────────────────────────────────────

    def ask(self, question: str, top_chains: int = 5) -> Answer:
        """Find me a fact that answers this question.

        Refuses with low confidence rather than inventing — the
        no-hallucinations property comes from this discipline.

        Two-hop retrieval: when the direct match is weak, entities from
        the best hop-1 facts expand the query and recall runs again
        ("who are my children?" → hop-1 surfaces the brandi facts →
        hop-2 finds "brandi has two children ..."). This widens what
        the renderer SEES; it never widens what may be CLAIMED — every
        answer still grounds in stated facts only.
        """
        results = self.space.recall(question, top_k=top_chains, exclude_speakers=("ada",))

        # ── hop 2: entity-expanded recall ─────────────────────────────
        # Bridge entities come from hop-1 facts' entity-bearing slots
        # only (entity.name, relational subject/object/possessor), and
        # the hop-2 query is FOCUSED: question content + bridge names.
        # A wordy expansion dilutes its own match.
        if results:
            from ada.memory.thought_space import _tokenize
            q_content = _tokenize(question)
            bridges: list[str] = []
            seen = set(q_content)
            for r in results[:2]:
                u = r.thought.universal
                names = [(u.get("entity") or {}).get("name")]
                rel = u.get("relational") or {}
                names += [rel.get(k) for k in ("subject", "object", "possessor")]
                for name in names:
                    if not name:
                        continue
                    for tok in _tokenize(str(name)):
                        if tok not in seen:
                            bridges.append(tok)
                            seen.add(tok)
            if bridges:
                hop2 = self.space.recall(
                    " ".join(q_content + bridges[:4]),
                    top_k=top_chains, exclude_speakers=("ada",))
                known = {r.thought.thought_id for r in results}
                results = sorted(
                    results + [r for r in hop2 if r.thought.thought_id not in known],
                    key=lambda r: r.global_similarity, reverse=True)[:top_chains]

        if not results:
            return Answer(question=question, refused=True, rendered="I don't know.")

        top = results[0]
        confidence = top.global_similarity
        if confidence < self.min_confidence:
            return Answer(
                question=question,
                confidence=confidence,
                refused=True,
                rendered="I don't know.",
            )

        fact = top.thought

        # Render the answer through the LLM if one's wired in. The renderer
        # sees only the top facts — it can't invent because there's nothing
        # off-substrate to invent from.
        if self.renderer is not None:
            try:
                facts_for_render = "\n".join(
                    f"- {r.thought.content}" for r in results
                )
                rendered = self.renderer(facts_for_render, question)
            except Exception:
                rendered = fact.content
        else:
            rendered = fact.content

        return Answer(
            question=question,
            fact=fact,
            confidence=confidence,
            rendered=rendered,
        )
