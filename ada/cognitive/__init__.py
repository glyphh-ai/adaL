"""
ada.cognitive — the universal schema and the cognitive surfaces on it.

    UNIVERSAL_SCHEMA   — the fixed 7-layer × 33-role lattice
    UniversalEnricher  — LLM-at-build-time text → schema extractor
    CognitiveSurface   — think / ask on a ThoughtSpace
    build_llm_renderer — optional LLM surface form for answers
"""

from .universal import ALL_LAYERS, ALL_ROLES, UNIVERSAL_SCHEMA, UniversalEnricher
from .surface import Activation, Answer, CognitiveSurface
from .generate import build_llm_renderer

__all__ = [
    "UNIVERSAL_SCHEMA",
    "ALL_LAYERS",
    "ALL_ROLES",
    "UniversalEnricher",
    "CognitiveSurface",
    "Activation",
    "Answer",
    "build_llm_renderer",
]
