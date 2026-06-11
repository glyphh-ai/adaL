"""
Phase 2 corpus — the Phase 1 NL corpus plus versioned updates.

A fraction of persons get a later update sentence ("X has since moved
to Y"), so the corpus contains superseded facts. Systems with a notion
of current-vs-historical belief can answer both "where does X live?"
and "where did X live before?"; systems without one are measured on
what happens when they can't.

Every fact carries a derived key (person + canonical slot) — the same
derivation every keyed system uses, so versioning is identical across
Ada / EAV / graph. RAG ingests raw sentences only (its architecture).
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))
from generate_nl import CITIES, NLFact, generate_nl  # noqa: E402

UPDATE_FRACTION = 0.3  # persons whose location changes later

UPDATE_TEMPLATES = [
    "{p} has since moved to {v}.",
    "{p} recently relocated to {v}.",
    "Update: {p} now lives in {v}.",
]


@dataclass
class Phase2Corpus:
    facts: list[NLFact]                       # in ingestion order
    keys: list[str]                           # derived key per fact (parallel)
    current: dict[str, dict[str, str]]        # person -> fact_type -> value
    previous: dict[str, dict[str, str]] = field(default_factory=dict)
    persons: list[str] = field(default_factory=list)


def derive_key(person: str, fact_type: str) -> str:
    return f"{person.lower()}.{fact_type}"


def build_corpus(n_persons: int = 60, seed: int = 0) -> Phase2Corpus:
    rng = random.Random(seed * 7919 + 13)
    base = generate_nl(n_persons, seed)

    current: dict[str, dict[str, str]] = {}
    persons: list[str] = []
    for f in base:
        if f.person not in current:
            current[f.person] = {}
            persons.append(f.person)
        current[f.person][f.fact_type] = f.expected[2]

    facts = list(base)
    keys = [derive_key(f.person, f.fact_type) for f in base]
    previous: dict[str, dict[str, str]] = {}

    # Location updates for a deterministic subset of persons.
    n_updates = int(len(persons) * UPDATE_FRACTION)
    for person in rng.sample(persons, n_updates):
        old_city = current[person]["location"]
        new_city = rng.choice([c for c in CITIES if c != old_city])
        template = rng.choice(UPDATE_TEMPLATES)
        facts.append(NLFact(
            sentence=template.format(p=person, v=new_city),
            person=person,
            fact_type="location",
            expected=("spatial", "location", new_city),
            acceptable=[],
        ))
        keys.append(derive_key(person, "location"))
        previous.setdefault(person, {})["location"] = old_city
        current[person]["location"] = new_city

    return Phase2Corpus(
        facts=facts, keys=keys, current=current,
        previous=previous, persons=persons,
    )
