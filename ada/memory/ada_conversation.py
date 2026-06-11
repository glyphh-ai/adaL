"""
Conversation — ChatML multi-turn prompt builder.

No CLI dependencies. Used by AdaCognitive and directly by models
that need conversation state without the full cognitive loop.
"""

from __future__ import annotations


class Conversation:
    """Manages multi-turn conversation as a ChatML prompt."""

    def __init__(self, system_prompt: str, max_turns: int = 3):
        self._system = system_prompt
        self._turns: list[tuple[str, str]] = []
        self._max_turns = max_turns

    def build_prompt(self, user_msg: str, recall: str | None = None) -> str:
        """Build a ChatML prompt with optional recall injection.

        Args:
            user_msg: Current user message.
            recall: Optional recall/instruction context injected as a
                system message right before the user turn.

        Returns:
            Full ChatML prompt string.
        """
        parts = [f"<|im_start|>system\n{self._system}<|im_end|>"]
        for user, assistant in self._turns:
            parts.append(f"<|im_start|>user\n{user}<|im_end|>")
            parts.append(f"<|im_start|>assistant\n{assistant}<|im_end|>")
        # Inject recall right before the current message — keeps facts
        # close to where the LLM generates, not buried in system prompt
        if recall:
            parts.append(f"<|im_start|>system\n{recall}<|im_end|>")
        parts.append(f"<|im_start|>user\n{user_msg}<|im_end|>")
        parts.append("<|im_start|>assistant\n<think>\n</think>\n\n")
        return "\n".join(parts)

    def add_turn(self, user_msg: str, assistant_msg: str) -> None:
        """Record a conversation turn.

        Deduplicates identical assistant responses to prevent the LLM
        from locking into a pattern by seeing its own repeated output.
        """
        if self._turns and self._turns[-1][1] == assistant_msg:
            self._turns[-1] = (user_msg, assistant_msg)
            return
        self._turns.append((user_msg, assistant_msg))
        if len(self._turns) > self._max_turns:
            self._turns = self._turns[-self._max_turns:]

    def clear(self) -> None:
        self._turns.clear()

    @property
    def turn_count(self) -> int:
        return len(self._turns)
