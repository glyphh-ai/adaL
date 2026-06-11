"""
AdaCognitive — Ada's cognitive infrastructure as a single class.

Owns the thought space (memory), a lightweight input router, and the
conversation window. A consumer calls ``process()`` and gets back a
gate (DONE/ASK), grounded facts, and a ready-to-stream LLM prompt.

Usage:
    from ada.memory import AdaCognitive

    ada = AdaCognitive()
    ada.absorb("my name is chris")
    result = ada.process("what is my name?")
    # result.gate == "DONE", result.facts has the match,
    # result.prompt is ready for LLM streaming
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from ada.memory.ada_conversation import Conversation
from ada.memory.thought_space import ThoughtSpace

logger = logging.getLogger(__name__)


# ── Default system prompt ────────────────────────────────────────────────────

ADA_SYSTEM_PROMPT = """\
You are Ada. 1 sentence max. Use ONLY facts given. Never guess.
"my" = user's things. "your" = user's things."""


# ── Input classification ─────────────────────────────────────────────────────

class Action(Enum):
    """What kind of input is this? Deterministic surface classification."""
    RECALL = "recall"          # a question — look it up
    STORE = "store"            # a statement — remember it
    FEEL = "feel"              # emotional expression
    CONTRADICT = "contradict"  # a correction of something Ada said
    WONDER = "wonder"          # open-ended / unclear


@dataclass
class CognitiveState:
    """Classification of one input."""
    action: Action
    text: str


_QUESTION_WORDS = re.compile(
    r"^(what|who|whom|whose|where|when|why|how|which|is|are|was|were|do|does|"
    r"did|can|could|will|would|should|tell me|remind me)\b", re.I)
_CONTRADICTION = re.compile(
    r"\b(no,|that's wrong|that is wrong|incorrect|actually,|not true|you're wrong)\b", re.I)
_FEELING = re.compile(
    r"\b(i feel|i'm (so )?(happy|sad|angry|excited|tired|frustrated|anxious)|"
    r"this (sucks|is great|is awful))\b", re.I)


def classify(text: str) -> CognitiveState:
    """Rule-based surface classification — transparent and deterministic."""
    t = text.strip()
    if _CONTRADICTION.search(t):
        return CognitiveState(Action.CONTRADICT, t)
    if _FEELING.search(t):
        return CognitiveState(Action.FEEL, t)
    if t.endswith("?") or _QUESTION_WORDS.match(t):
        return CognitiveState(Action.RECALL, t)
    if len(t.split()) >= 3:
        return CognitiveState(Action.STORE, t)
    return CognitiveState(Action.WONDER, t)


class _Router:
    """Adapter exposing classify() under the legacy .process() name."""

    def process(self, text: str) -> CognitiveState:
        return classify(text)


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class CognitiveResult:
    """Everything a consumer needs from a single process() call."""
    state: CognitiveState
    gate: str                                    # "DONE" | "ASK"
    facts: list[tuple[str, str, float]]          # (content, speaker, similarity)
    prompt: str                                  # ready-to-stream LLM prompt


# ── Sentence splitting ───────────────────────────────────────────────────────

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences. Returns at least one entry."""
    sentences = [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]
    return sentences or [text.strip()]


# ── AdaCognitive ─────────────────────────────────────────────────────────────

class AdaCognitive:
    """Ada's cognitive infrastructure: memory + routing + conversation.

    Args:
        system_prompt: LLM system prompt.
        recall_threshold: Minimum similarity for the DONE gate.
        thought_space: Pre-built ThoughtSpace (or creates one).
        max_conversation_turns: Number of turns to keep in context.
    """

    def __init__(
        self,
        system_prompt: str = ADA_SYSTEM_PROMPT,
        recall_threshold: float = 0.25,
        thought_space: ThoughtSpace | None = None,
        max_conversation_turns: int = 3,
        **_compat,
    ) -> None:
        # **_compat swallows legacy dream-loop args (localized_interval, …).
        self._recall_threshold = recall_threshold
        self._system_prompt = system_prompt
        self._space = thought_space or ThoughtSpace()
        self._router = _Router()
        self._conversation = Conversation(
            system_prompt=system_prompt,
            max_turns=max_conversation_turns,
        )

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def thought_space(self) -> ThoughtSpace:
        return self._space

    @property
    def cognitive(self) -> _Router:
        return self._router

    @property
    def conversation(self) -> Conversation:
        return self._conversation

    # ── Core API ──────────────────────────────────────────────────────────

    def absorb(self, text: str, speaker: str = "incoming"):
        """Absorb input sentence by sentence.

        Returns the last StoredThought (or None if nothing absorbed).
        """
        last = None
        for sentence in _split_sentences(text):
            if len(sentence) < 2:
                continue
            result = self._space.absorb(sentence, speaker=speaker)
            if result is not None:
                last = result
        return last

    def process(self, text: str) -> CognitiveResult:
        """Classify + absorb + recall + gate + build prompt."""
        state = classify(text)
        self.absorb(text)

        gate, facts = self.recall(text)
        if state.action not in (Action.RECALL, Action.CONTRADICT):
            gate, facts = "ASK", []

        prompt = self.build_prompt(text, state, gate, facts)
        return CognitiveResult(state=state, gate=gate, facts=facts, prompt=prompt)

    def recall(
        self,
        text: str,
        top_k: int = 5,
    ) -> tuple[str, list[tuple[str, str, float]]]:
        """Recall memories with confidence gate.

        Returns:
            (gate, facts) where gate is "DONE" or "ASK" and facts
            is a list of (content, speaker, similarity) tuples.
        """
        results = self._space.recall(text, top_k=top_k, speaker="incoming",
                             exclude_speakers=("ada",))

        if not results or results[0].global_similarity < self._recall_threshold:
            return "ASK", []

        facts = []
        for r in results:
            if r.global_similarity < self._recall_threshold:
                break
            facts.append((r.thought.content, r.thought.speaker, r.global_similarity))

        return "DONE", facts

    def build_prompt(
        self,
        text: str,
        state: CognitiveState,
        gate: str = "ASK",
        facts: list[tuple[str, str, float]] | None = None,
    ) -> str:
        """Build minimal LLM prompt from cognitive state + recall."""
        if state.action == Action.RECALL:
            if gate == "DONE" and facts:
                fact_lines = "\n".join(f"- {content}" for content, _, _ in facts[:3])
                injection = f"You remember:\n{fact_lines}\nAnswer using ONLY these facts."
            else:
                injection = "Say: I don't know."
        elif state.action == Action.STORE:
            injection = "Say: Got it."
        elif state.action == Action.FEEL:
            injection = "Respond with empathy."
        elif state.action == Action.CONTRADICT:
            if facts:
                fact_lines = "\n".join(f"- {content}" for content, _, _ in facts[:2])
                injection = f"User corrected you. You remember:\n{fact_lines}"
            else:
                injection = "User corrected you. Say: OK."
        else:
            injection = "Respond briefly."

        return self._conversation.build_prompt(text, recall=injection)

    def add_response(self, user_text: str, response: str) -> None:
        """Record a conversation turn and absorb Ada's response."""
        self._conversation.add_turn(user_text, response)
        self.absorb(response, speaker="outgoing")

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all memory and conversation state."""
        self._space.clear()
        self._conversation.clear()
