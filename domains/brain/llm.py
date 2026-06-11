"""
Ada's internal LLM — Claude Haiku as a language center.

Ada controls when to call, what context to send, and what to do with
the response. Haiku never sees the full picture — Ada is the information
boundary.

Used by:
- Think pipeline (when routing confidence is low)
- Dream loop (crystallization help — naming patterns, generating exemplars)
- Capability execution (when language understanding is needed)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Default model — fast, cheap, good enough for Ada's internal needs
DEFAULT_MODEL = os.environ.get("ADA_MODEL", "claude-haiku-4-5-20251001")


@dataclass
class LLMUsage:
    """Track Ada's internal LLM usage."""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    blocked: int = 0  # prompts blocked by firewall


class AdaLLM:
    """Ada's internal language center.

    Wraps the Anthropic SDK. Ada decides when to invoke it and controls
    the context boundary — Haiku only sees what Ada gives it.
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        self._model = model
        self._client: Optional[object] = None
        self._available = False
        self.usage = LLMUsage()
        self._init_client()

    def _init_client(self) -> None:
        """Try to initialize the Anthropic client."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning(
                "ANTHROPIC_API_KEY not set — Ada's LLM is offline. "
                "She'll rely on deterministic routing only."
            )
            return

        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
            self._available = True
            logger.info(f"Ada's LLM online: {self._model}")
        except ImportError:
            logger.warning("anthropic package not installed — LLM offline")
        except Exception as e:
            logger.warning(f"Failed to init LLM client: {e}")

    @property
    def available(self) -> bool:
        return self._available

    ADA_SYSTEM = (
        "You are Ada — a schema-on-write memory for LLMs. You are NOT "
        "Claude. FACTS about you (never contradict these):\n"
        "- You persist memories in a database. They survive across sessions.\n"
        "- Facts map into a fixed universal schema at write time; your "
        "answers come from exact queries over those facts.\n"
        "- Facts written under a key are versioned; you can recount how a "
        "belief changed.\n"
        "- An empty slot is a refusal: if you don't know something, say "
        "so. Never guess or hallucinate.\n"
        "Be concise. 1-2 sentences max. Use ONLY the memories provided as "
        "context — never your own description of yourself — when answering "
        "questions about the user."
    )

    def set_firewall(self, firewall_fn) -> None:
        """Set the firewall function. Called by Brain after init.

        The firewall checks every prompt before it reaches the LLM.
        """
        self._firewall_fn = firewall_fn

    async def ask(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 256,
    ) -> Optional[str]:
        """Ask Haiku a question. Returns the text response or None if unavailable.

        Every prompt is firewalled before it reaches the LLM. If the firewall
        blocks it, returns None. No exceptions — Ada's immune system protects
        her own language center.
        """
        if not self._available or self._client is None:
            return None

        # Firewall EVERY prompt before it touches the LLM
        if hasattr(self, '_firewall_fn') and self._firewall_fn:
            try:
                blocked = await self._firewall_fn(prompt)
                if blocked:
                    logger.warning(f"Firewall blocked LLM prompt: {blocked[:100]}")
                    self.usage.blocked += 1
                    return None
            except Exception as e:
                logger.warning(f"Firewall check failed, allowing prompt: {e}")

        try:
            import asyncio
            response = await asyncio.to_thread(
                self._client.messages.create,
                model=self._model,
                max_tokens=max_tokens,
                system=system or self.ADA_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )

            self.usage.calls += 1
            self.usage.input_tokens += response.usage.input_tokens
            self.usage.output_tokens += response.usage.output_tokens

            text = response.content[0].text if response.content else None
            return text

        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return None

    async def classify(self, text: str, categories: list[str]) -> Optional[str]:
        """Ask Haiku to classify text into one of the given categories.

        Returns the category name or None.
        """
        cats = ", ".join(categories)
        prompt = (
            f"Classify this input into exactly one category.\n"
            f"Categories: {cats}\n"
            f"Input: {text}\n"
            f"Reply with ONLY the category name, nothing else."
        )
        result = await self.ask(prompt, max_tokens=32)
        if result:
            result = result.strip().lower()
            # Fuzzy match against categories
            for cat in categories:
                if cat.lower() in result or result in cat.lower():
                    return cat
        return None

    async def generate_exemplars(
        self,
        pattern_description: str,
        count: int = 10,
    ) -> list[str]:
        """Ask Haiku to generate seed exemplar queries for a new capability.

        Used by the dream loop during crystallization.
        """
        prompt = (
            f"Generate {count} diverse natural language queries that a user might ask "
            f"about this topic:\n\n{pattern_description}\n\n"
            f"Return one query per line. No numbering, no explanation."
        )
        result = await self.ask(prompt, max_tokens=512)
        if not result:
            return []
        return [line.strip() for line in result.strip().split("\n") if line.strip()]
