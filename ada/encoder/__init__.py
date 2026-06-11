"""
ada.encoder — LLM-at-build-time fact enrichment.

    auto_enricher() — picks the best available enricher (universal-schema
                      LLM extractor with an API key, regex heuristics without)
"""

from ada.encoder.llm_enricher import (
    FactEnricher,
    HeuristicEnricher,
    StructuredFact,
    UniversalSchemaEnricher,
    auto_enricher,
)

__all__ = [
    "FactEnricher",
    "HeuristicEnricher",
    "StructuredFact",
    "UniversalSchemaEnricher",
    "auto_enricher",
]
