"""
Ada — a structured memory substrate for LLMs.

Facts map into a fixed universal schema (7 layers × 33 roles) at write
time; structured queries (count / distribution / intersection), versioned
keys, and lexical recall address them at read time. No vectors, no
embedding model — every operation is an exact, explainable scan.

Example:
    >>> from ada import ThoughtSpace
    >>>
    >>> space = ThoughtSpace()
    >>> space.tell_raw(
    ...     facts={"entity": {"name": "Chris", "kind": "person"},
    ...            "spatial": {"location": "Brooklyn"}},
    ...     key="chris.location",
    ... )
    >>> space.count_where("spatial", "location", "Brooklyn")
    1
"""

from .cognitive import (
    ALL_LAYERS,
    ALL_ROLES,
    UNIVERSAL_SCHEMA,
    Activation,
    Answer,
    CognitiveSurface,
    UniversalEnricher,
    build_llm_renderer,
)
from .memory import (
    AdaCognitive,
    Conversation,
    RecallResult,
    StoredThought,
    ThoughtGlyphSpace,
    ThoughtSpace,
)

__version__ = "0.7.0"

__all__ = [
    "UNIVERSAL_SCHEMA",
    "ALL_LAYERS",
    "ALL_ROLES",
    "UniversalEnricher",
    "CognitiveSurface",
    "Activation",
    "Answer",
    "build_llm_renderer",
    "ThoughtSpace",
    "ThoughtGlyphSpace",
    "StoredThought",
    "RecallResult",
    "AdaCognitive",
    "Conversation",
    "__version__",
]
