"""
Ada's thought process — runs for every request.

Steps per request:
  1. PERCEIVE  — classify the input (question / statement / correction)
  2. RECALL    — search the thought space for grounded facts
  3. RESPOND   — LLM synthesizes from recalled facts ONLY, or Ada
                 honestly says "I don't know"

The hallucination gate: the LLM only ever sees facts that recall
surfaced from the substrate. No facts → no guessing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.25


@dataclass
class Thought:
    """One pass of Ada's thought process."""
    input_text: str = ""
    cognitive_state: str = ""  # RECALL, STORE, FEEL, CONTRADICT, WONDER
    facts: list[tuple] = field(default_factory=list)  # (content, speaker, similarity)
    memory_gate: str = "ASK"  # DONE or ASK from memory recall
    confidence: float = 0.0


@dataclass
class ThoughtResult:
    """Final output of the thought process."""
    response: str
    capability: Optional[str] = None
    confidence: float = 0.0
    cognitive_state: str = ""
    gate: str = "ASK"
    facts: list[tuple] = field(default_factory=list)
    llm_assisted: bool = False
    elapsed_ms: float = 0.0


class ThoughtProcess:
    """Perceive → recall → respond, grounded in the thought space."""

    def __init__(self, cognitive, llm):
        self._cognitive = cognitive  # AdaCognitive
        self._llm = llm              # AdaLLM

    async def think(self, input_text: str) -> ThoughtResult:
        """Run the thought process for one request."""
        start = time.monotonic()
        thought = Thought(input_text=input_text)

        # ── 1. PERCEIVE ──────────────────────────────────────────
        state = self._cognitive.cognitive.process(input_text)
        thought.cognitive_state = state.action.name if state else "UNKNOWN"

        # ── 2. RECALL ────────────────────────────────────────────
        gate, facts = self._cognitive.recall(input_text, top_k=5)
        thought.memory_gate = gate
        thought.facts = facts
        thought.confidence = facts[0][2] if facts else 0.0

        # ── 3. RESPOND ───────────────────────────────────────────
        response = await self._formulate_response(thought, input_text)

        # Absorb the interaction — statements only. Questions are
        # requests for facts, not facts; storing them pollutes recall.
        if thought.cognitive_state not in ("RECALL", "WONDER"):
            self._cognitive.absorb(input_text)
        if response:
            self._cognitive.absorb(response, speaker="ada")

        return ThoughtResult(
            response=response,
            confidence=thought.confidence,
            cognitive_state=thought.cognitive_state,
            gate=thought.memory_gate,
            facts=thought.facts,
            llm_assisted=self._llm.available,
            elapsed_ms=(time.monotonic() - start) * 1000,
        )

    # ── Response formulation ─────────────────────────────────────

    async def _formulate_response(self, thought: Thought, input_text: str) -> str:
        """Formulate a natural response, grounded in recalled facts only."""

        if thought.memory_gate == "DONE" and thought.facts:
            # Recall converged — we have grounded facts. LLM synthesizes.
            if self._llm.available:
                parts = [f"User said: \"{input_text}\""]
                parts.append("\nFacts (from your memory — these are TRUE, use them):")
                for content, speaker, sim in thought.facts[:5]:
                    parts.append(f"  - {content}")
                parts.append(
                    "\nRespond using ONLY these facts. 1-2 sentences. "
                    "Do not add information that isn't in the facts."
                )
                response = await self._llm.ask("\n".join(parts))
                if response:
                    return response
            # LLM offline — return top fact directly
            return thought.facts[0][0]

        if thought.facts and thought.facts[0][2] > CONFIDENCE_THRESHOLD:
            # Partial match — some facts but low confidence
            if self._llm.available:
                parts = [f"User said: \"{input_text}\""]
                parts.append("\nPossibly relevant memories (not fully confirmed):")
                for content, speaker, sim in thought.facts[:3]:
                    parts.append(f"  - {content}")
                parts.append(
                    "\nRespond as Ada. Use these memories if they seem relevant, "
                    "but say what you're unsure about. 1-2 sentences."
                )
                response = await self._llm.ask("\n".join(parts))
                if response:
                    return response

        if thought.cognitive_state == "STORE":
            return "Got it."

        # No facts, no convergence — honest "I don't know"
        return "I don't have information about that in my memory."
