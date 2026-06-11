"""
Phase 1 corpus generator — natural-language sentences with known ground truth.

Unlike the deleted 2026-05 benchmark (which handed Ada pre-structured
dicts), every fact here is rendered as a natural-language sentence drawn
from one of several paraphrase templates. The structured ground truth
rides alongside, so the LLM enricher's *semantic* extraction accuracy is
measurable: did the right value land in the right slot, attributed to
the right entity?

Each fact carries:
  sentence    — what every system ingests
  person      — the entity the fact is about
  fact_type   — age / location / job / hobby / pet / color / height / origin
  expected    — (layer, role, value): the canonical slot the value belongs in
  acceptable  — additional (layer, role) slots where the value still counts
                as captured-but-non-canonical (slot ambiguity is a real
                phenomenon; we measure it instead of pretending it away)

Deterministic given a seed.

    PYTHONPATH=. python benchmark/phase1/generate_nl.py --n 60 --seed 0
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

COLORS = ["red", "blue", "green", "yellow", "orange", "purple", "pink",
          "brown", "black", "white", "grey"]

CITIES = ["Austin", "Boston", "Chicago", "Denver", "Eugene", "Fresno",
          "Glasgow", "Helsinki", "Istanbul", "Jakarta", "Kyoto", "Lagos",
          "Madrid", "Naples", "Oslo", "Paris", "Quito", "Riga",
          "Stockholm", "Tokyo", "Uppsala", "Vienna", "Warsaw", "Xi'an",
          "York", "Zurich", "Phoenix", "Calgary", "Lyon", "Antwerp"]

JOBS = ["engineer", "doctor", "teacher", "designer", "scientist",
        "lawyer", "pilot", "chef", "writer", "musician",
        "architect", "nurse", "carpenter", "plumber", "electrician",
        "accountant", "farmer", "actor", "athlete", "researcher"]

HOBBIES = ["chess", "painting", "hiking", "gardening", "cooking",
           "running", "swimming", "reading", "photography", "knitting"]

PETS = ["dog", "cat", "rabbit", "hamster", "parrot", "goldfish"]


@dataclass
class NLFact:
    """One natural-language fact with its structured ground truth."""
    sentence: str
    person: str
    fact_type: str
    expected: tuple[str, str, str]            # (layer, role, value)
    acceptable: list[tuple[str, str]] = field(default_factory=list)


# ── Paraphrase templates per fact type ────────────────────────────────
#
# {p} = person, {v} = value. Each type has ≥3 surface forms so the
# enricher can't pattern-match a single template.

TEMPLATES: dict[str, list[str]] = {
    "age": [
        "{p} is {v} years old.",
        "{p} just turned {v}.",
        "At {v}, {p} is busier than ever.",
        "{p} celebrated a {v}th birthday this year.",
    ],
    "location": [
        "{p} lives in {v}.",
        "{p} is based in {v} these days.",
        "Home for {p} is {v}.",
        "{p} moved to {v} and has stayed there since.",
    ],
    "job": [
        "{p} works as a {v}.",
        "{p} earns a living as a {v}.",
        "Professionally, {p} is a {v}.",
        "{p}'s day job is being a {v}.",
    ],
    "hobby": [
        "{p} enjoys {v} in their free time.",
        "{p}'s favorite hobby is {v}.",
        "On weekends, {p} spends hours on {v}.",
        "{p} is really into {v}.",
    ],
    "pet": [
        "{p} has a pet {v}.",
        "{p} owns a {v}.",
        "{p} takes care of a {v} at home.",
        "A {v} lives with {p}.",
    ],
    "color": [
        "{p}'s favorite color is {v}.",
        "{p} likes the color {v} best.",
        "If you ask {p}, no color beats {v}.",
        "{p} always picks {v} when given the choice.",
    ],
    "height": [
        "{p} is {v} centimeters tall.",
        "{p} stands {v} centimeters tall.",
        "{p} measures {v} centimeters in height.",
    ],
    "origin": [
        "{p} is originally from {v}.",
        "{p} grew up in {v}.",
        "{p} was born in {v}.",
    ],
}

# Canonical slot + acceptable alternates per fact type. "Acceptable"
# means the value landed somewhere defensible but non-canonical — it
# counts as captured, not as canonically correct, and it breaks
# cross-corpus aggregation if inconsistent.
SLOTS: dict[str, tuple[tuple[str, str], list[tuple[str, str]]]] = {
    "age":      (("temporal", "age"),        []),
    "location": (("spatial", "location"),    []),
    "job":      (("relational", "object"),   [("entity", "subkind"), ("entity", "kind")]),
    "hobby":    (("relational", "object"),   []),
    "pet":      (("relational", "object"),   [("entity", "subkind")]),
    "color":    (("perceptual", "color"),    [("relational", "object")]),
    "height":   (("quantitative", "magnitude"), [("perceptual", "size")]),
    "origin":   (("spatial", "origin"),      [("spatial", "location")]),
}

FACT_TYPES = list(TEMPLATES)


def _name_for(i: int, rng: random.Random) -> str:
    syllables = ["ka", "ra", "no", "mi", "to", "le", "vi", "su", "do", "an",
                 "be", "ji", "po", "rey", "fa", "yu", "ze", "qu", "wa", "ho"]
    return (rng.choice(syllables) + rng.choice(syllables)).title() + str(i)


def generate_nl(n_persons: int = 60, seed: int = 0) -> list[NLFact]:
    """n_persons × 8 fact types = 8n NL facts with ground truth."""
    rng = random.Random(seed)
    out: list[NLFact] = []
    for i in range(n_persons):
        person = _name_for(i, rng)
        values = {
            "age": str(rng.randint(18, 80)),
            "location": rng.choice(CITIES),
            "job": rng.choice(JOBS),
            "hobby": rng.choice(HOBBIES),
            "pet": rng.choice(PETS),
            "color": rng.choice(COLORS),
            "height": str(rng.randint(150, 200)),
            "origin": rng.choice(CITIES),
        }
        for ft in FACT_TYPES:
            v = values[ft]
            template = rng.choice(TEMPLATES[ft])
            (layer, role), acceptable = SLOTS[ft]
            out.append(NLFact(
                sentence=template.format(p=person, v=v),
                person=person,
                fact_type=ft,
                expected=(layer, role, v),
                acceptable=acceptable,
            ))
    return out


def ground_truth_aggregates(facts: list[NLFact]) -> dict:
    """Exact answers for the aggregation sanity checks, from ground truth."""
    from collections import Counter
    by_type: dict[str, Counter] = {}
    for f in facts:
        by_type.setdefault(f.fact_type, Counter())[f.expected[2].lower()] += 1
    return {
        "count_color_blue": by_type.get("color", Counter())["blue"],
        "count_job_engineer": by_type.get("job", Counter())["engineer"],
        "top5_locations": by_type.get("location", Counter()).most_common(5),
        "top5_colors": by_type.get("color", Counter()).most_common(5),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=60, help="number of persons (×8 facts)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=str, default="")
    args = p.parse_args()

    facts = generate_nl(args.n, args.seed)
    print(f"  generated {len(facts)} NL facts about {args.n} persons (seed {args.seed})")
    for f in facts[:5]:
        print(f"    {f.sentence!r:64s} -> {'.'.join(f.expected[:2])}={f.expected[2]}")

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            for f in facts:
                fh.write(json.dumps(asdict(f)) + "\n")
        print(f"  saved -> {path}")


if __name__ == "__main__":
    main()
