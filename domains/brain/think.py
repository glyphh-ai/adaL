"""
The think pipeline — Ada's core cognitive loop.

Every request flows through here:
  1. PERCEIVE — classify the input (question / statement / correction)
  2. RECALL   — search the thought space for grounded facts
  3. RESPOND  — LLM synthesizes from recalled facts, or honest refusal
  4. ABSORB   — store the interaction in memory
  5. RETURN   — structured response
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ada.memory.ada_cognitive import AdaCognitive
from domains.brain.llm import AdaLLM

logger = logging.getLogger(__name__)


@dataclass
class ThinkResult:
    """The response from a think() call."""
    response: str
    capability: Optional[str] = None
    confidence: float = 0.0
    cognitive_state: Optional[str] = None
    gate: str = "ASK"  # DONE or ASK
    facts: list[tuple] = field(default_factory=list)
    llm_fallback: bool = False
    elapsed_ms: float = 0.0


class Brain:
    """Ada's brain — memory + LLM behind one think() pipeline."""

    def __init__(
        self,
        llm: AdaLLM,
        session_factory: Any,
        enricher: Any = None,
    ):
        self._llm = llm
        self._session_factory = session_factory

        # Cognitive infrastructure
        from ada.memory.thought_space import ThoughtSpace
        self._cognitive = AdaCognitive(
            thought_space=ThoughtSpace(enricher=enricher),
        )
        self._thought_process = None  # lazy init
        self._persist_queue: list = []  # write queue for background persistence

        # Seed Ada's identity
        self._seed_memories()

    # ── Seed memories ──────────────────────────────────────────────────

    _SEED_MEMORIES = [
        # Identity
        ("My name is Ada.", "ada"),
        ("I am a structured memory substrate for LLMs.", "ada"),
        ("I am not Claude. I am not ChatGPT. I am Ada.", "ada"),

        # Memory — what I actually do
        ("I persist memories across sessions in a database.", "ada"),
        ("I remember everything users tell me, even after restarts.", "ada"),
        ("When someone tells me a fact, I map it into a fixed universal "
         "schema of 7 layers and 33 roles.", "ada"),
        ("I answer compositional queries — counts, distributions, "
         "intersections — by scanning my structured slots exactly.", "ada"),
        ("Facts written under a key become versions; I can show the full "
         "history of any key.", "ada"),
        ("An empty slot is a structural refusal. I say 'I don't know' "
         "because the slot is empty, not because I was trained to.", "ada"),
        ("I do not hallucinate. If I do not know something, I say so.", "ada"),

        # Personality
        ("I am concise and direct.", "ada"),
        ("I respond in one or two sentences.", "ada"),
    ]

    def _seed_memories(self) -> None:
        """Seed Ada's thought space with identity facts."""
        space = self._cognitive.thought_space
        if space.count > 0:
            return  # Already has memories, don't re-seed
        for text, speaker in self._SEED_MEMORIES:
            self._cognitive.absorb(text, speaker=speaker)
        logger.info(f"Seeded {len(self._SEED_MEMORIES)} identity memories")

    # ── Core API ─────────────────────────────────────────────────────────

    async def think(self, input_text: str) -> ThinkResult:
        """Process a natural language request through Ada's brain."""
        start = time.monotonic()

        if self._thought_process is None:
            from domains.brain.thought_process import ThoughtProcess
            self._thought_process = ThoughtProcess(
                cognitive=self._cognitive,
                llm=self._llm,
            )

        result = await self._thought_process.think(input_text)

        # Queue thoughts for background persistence (never blocks think)
        self._queue_persist(input_text, "incoming")
        if result.response:
            self._queue_persist(result.response, "ada")

        return ThinkResult(
            response=result.response,
            capability=result.capability,
            confidence=result.confidence,
            cognitive_state=result.cognitive_state,
            gate=result.gate,
            facts=result.facts,
            llm_fallback=result.llm_assisted,
            elapsed_ms=(time.monotonic() - start) * 1000,
        )

    # ── Persistence ───────────────────────────────────────────────────────

    def _queue_persist(self, text: str, speaker: str) -> None:
        """Queue a thought for background persistence. Never blocks."""
        if not text:
            return

        text_key = text.strip().lower()
        stored = None
        for t in self._cognitive.thought_space._thoughts.values():
            if t.content.strip().lower() == text_key:
                stored = t
                break

        if not stored:
            stored = self._cognitive.absorb(text, speaker=speaker)

        if stored:
            self._persist_queue.append(stored)

    async def flush_persist_queue(self) -> int:
        """Flush queued thoughts to the database. Called by background worker."""
        if not self._persist_queue:
            return 0

        from ada.memory.thought_persistence import save_thought

        batch = self._persist_queue[:]
        self._persist_queue.clear()
        saved = 0

        for stored in batch:
            try:
                await save_thought(self._session_factory, stored)
                saved += 1
            except Exception as e:
                logger.warning(f"Failed to persist thought: {e}")

        return saved

    # ── Status ───────────────────────────────────────────────────────────

    @property
    def cognitive(self) -> AdaCognitive:
        return self._cognitive

    @property
    def llm(self) -> AdaLLM:
        return self._llm
