"""
LLM renderer factory — the surface form on top of the substrate.

The substrate does the retrieval; the renderer turns recalled facts into
natural language. The LLM only ever sees what the substrate chose to
expose, so it can't invent facts. Without a renderer (no API key), the
substrate's raw output is returned directly.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# (facts_context, query) -> rendered text
Renderer = Callable[[str, str], str]

DEFAULT_SYSTEM = (
    "You are Ada's language surface. You receive recalled memories and a "
    "query. Answer the query in ONE short sentence using ONLY the recalled "
    "memories. If they don't contain the answer, say \"I don't know.\" "
    "Never invent facts."
)


def build_llm_renderer(
    model: str | None = None,
    system: str = DEFAULT_SYSTEM,
    max_tokens: int = 200,
) -> Optional[Renderer]:
    """Return an Anthropic-backed renderer, or None if the SDK / key isn't here.

    The substrate works without it — the renderer is just the surface form.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.info("No ANTHROPIC_API_KEY — answers will return substrate facts directly.")
        return None
    try:
        import anthropic  # noqa: F401
    except ImportError:
        logger.info("anthropic SDK not installed — answers will return substrate facts directly.")
        return None

    import anthropic as _a
    client = _a.Anthropic()
    chosen = model or os.environ.get("ADA_MODEL", "claude-haiku-4-5-20251001")

    def _render(context: str, query: str) -> str:
        resp = client.messages.create(
            model=chosen,
            max_tokens=max_tokens,
            system=system,
            messages=[{
                "role": "user",
                "content": (
                    f"{context}\n\n"
                    f"Answer this query using only the recalled memories: {query}"
                ),
            }],
        )
        return resp.content[0].text.strip()

    return _render
