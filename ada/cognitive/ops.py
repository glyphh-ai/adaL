"""
The closed query-operation set — Ada's entire read surface.

Eight bounded operations over a ThoughtSpace. This is the op set the
benchmarks validated (benchmark/phase2, phase3): every operation is an
exact scan or cache lookup, every operation terminates, and there is no
open query language to misgenerate. An LLM fronting the store
translates a question into ONE of these; admin tools call them
directly.

    execute_op(space, {"op": "count",
                       "conditions": {"spatial.location": "boston"}})
    → "12"
"""

from __future__ import annotations

import re

from ada.memory.thought_space import ThoughtSpace

OPS = ("lookup", "prev", "count", "count_not", "top", "who",
       "compare", "refuse")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def execute_op(space: ThoughtSpace, op: dict) -> str:
    """Execute one operation; returns a short deterministic answer string.

    Raises ValueError on an unknown/malformed op — callers decide
    whether that becomes a retry or an honest failure.
    """
    kind = op.get("op")
    if kind == "refuse":
        return "I don't know."

    if kind == "lookup":
        prof = _profile_for(space, op["person"])
        slot = op["slot"]
        if not prof or slot not in prof:
            return "I don't know."
        return ", ".join(sorted(prof[slot]))

    if kind == "prev":
        prev_v = space.previous_value(op["person"], op["slot"])
        return str(prev_v) if prev_v is not None else "I don't know."

    if kind == "count":
        return str(len(space.entities_where(op["conditions"])))

    if kind == "count_not":
        slot, v = op["slot"], _norm(op["value"])
        n = sum(1 for prof in space.entity_profiles().values()
                if prof.get(slot) and v not in prof[slot])
        return str(n)

    if kind == "top":
        layer, _, role = op["slot"].partition(".")
        dist = space.distribution_filtered(
            layer, role, int(op.get("k", 5)),
            predicate_contains=op.get("predicate_contains"))
        if not dist:
            return "none"
        return ", ".join(f"{v} ({n})" for v, n in dist)

    if kind == "who":
        names = space.entities_where(op["conditions"])
        return ", ".join(sorted(names)) if names else "none"

    if kind == "compare":
        layer, _, role = op["slot"].partition(".")
        ca = space.count_where(layer, role, op["a"])
        cb = space.count_where(layer, role, op["b"])
        if ca == cb:
            return f"equal ({ca} each)"
        winner = op["a"] if ca > cb else op["b"]
        return f"{winner} ({max(ca, cb)} vs {min(ca, cb)})"

    raise ValueError(f"unknown op {kind!r} (valid: {', '.join(OPS)})")


def _profile_for(space: ThoughtSpace, person: str) -> dict | None:
    profs = space.entity_profiles()
    p = _norm(person)
    if p in profs:
        return profs[p]
    for name, prof in profs.items():
        if p in name or name in p:
            return prof
    return None
