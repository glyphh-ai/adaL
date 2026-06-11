"""Ada's reflective layer — skills that watch the substrate and adapt it.

`schema_evolution.py` is the first: a tracker that observes every enriched
fact, detects when a new predicate or topic appears, and persists the
discovery two ways:

  1. Appended to a markdown changelog (git-native audit trail).
  2. Absorbed as a meta-glyph in the substrate itself (so Ada can recall
     and reason about its own schema, with versioning).

Both representations stay in sync. Either can drive the other.
"""

from ada.skill.schema_evolution import SchemaTracker

__all__ = ["SchemaTracker"]
