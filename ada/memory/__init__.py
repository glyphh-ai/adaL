"""
ada.memory — Ada's lifelong memory system.

  ThoughtSpace    — the structured fact store (universal schema, versioned
                    keys, structured queries, lexical recall)
  AdaCognitive    — memory + input routing + conversation in one class
  Conversation    — rolling conversation window for LLM prompts

``ThoughtGlyphSpace`` is a back-compat alias for ThoughtSpace.
"""

from .thought_space import ThoughtSpace, ThoughtGlyphSpace, StoredThought, RecallResult
from .ada_conversation import Conversation
from .ada_cognitive import (
    Action,
    AdaCognitive,
    CognitiveResult,
    CognitiveState,
)

__all__ = [
    "ThoughtSpace",
    "ThoughtGlyphSpace",
    "StoredThought",
    "RecallResult",
    "Conversation",
    "AdaCognitive",
    "CognitiveResult",
    "Action",
    "CognitiveState",
]
