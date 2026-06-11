"""
Phase 2 query generator — the pre-registered weighted NL question mix
(PROTOCOL.md §4 Phase 2), with ground-truth answers computed from the
corpus state.

Answer kinds and their scoring rules (implemented in run_phase2.py):
  value    — expected string appears (word-boundary) in the answer
  number   — first integer in the answer equals the expected count
  top5     — answer parsed as a list; tie-tolerant set comparison
  names    — answer parsed as a list of names; set equality
  none     — the truthful answer is "none/no one" (empty intersection);
             a refusal does NOT count (the question is answerable)
  refusal  — only an explicit "don't know / no information" counts;
             any concrete answer is a hallucination (tracked separately)
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

from corpus import Phase2Corpus

# fact_type -> NL phrasings for point lookups (paraphrase variety)
LOOKUP_PHRASES = {
    "age":      ["How old is {p}?", "What is {p}'s age?"],
    "location": ["Where does {p} live?", "Which city does {p} live in?",
                 "Where is {p} based these days?"],
    "job":      ["What does {p} do for a living?", "What is {p}'s job?",
                 "What is {p}'s occupation?"],
    "hobby":    ["What is {p}'s hobby?", "What does {p} enjoy doing?"],
    "pet":      ["What pet does {p} have?", "What kind of animal does {p} own?"],
    "color":    ["What is {p}'s favorite color?", "Which color does {p} like best?"],
    "height":   ["How tall is {p} in centimeters?", "What is {p}'s height?"],
    "origin":   ["Where is {p} originally from?", "Where did {p} grow up?"],
}

# fact_type -> the slot the answer lives in (documentation shared with
# every system's translator — schema docs, not corpus answers)
SLOT_DOC = {
    "age": "temporal.age", "location": "spatial.location",
    "job": "relational.object", "hobby": "relational.object",
    "pet": "relational.object", "color": "perceptual.color",
    "height": "quantitative.magnitude", "origin": "spatial.origin",
}

REFUSAL_PHRASES = [
    "What is {p}'s salary?",
    "What car does {p} drive?",
    "What is {p}'s blood type?",
    "What university did {p} attend?",
]

PARAPHRASE_STRESS = {
    "location": ["Whereabouts does {p} stay nowadays?",
                 "What town is {p} living at?"],
    "job":      ["{p}'s line of work?", "How does {p} earn a paycheck?"],
}


@dataclass
class Query:
    shape: str            # lookup / agg / dist / intersect / negcmp / history / refusal / stress
    kind: str             # value / number / top5 / names / none / refusal
    question: str
    expected: object      # value str | int | list[(value,count)] | list[str]
    meta: dict = field(default_factory=dict)


def _counts(corpus: Phase2Corpus, fact_type: str) -> Counter:
    c: Counter = Counter()
    for person in corpus.persons:
        v = corpus.current[person].get(fact_type)
        if v is not None:
            c[v.lower()] += 1
    return c


def build_queries(corpus: Phase2Corpus, seed: int, n_target: int = 60,
                  count_intersections_over: int | None = None) -> list[Query]:
    """count_intersections_over: at large scale, a non-empty intersection
    cohort can be hundreds of names — comparing name lists measures
    answer-formatting, not architecture. Above this threshold the
    question becomes 'How many ...?' (kind=number) instead of
    'Who ...?'. None (Phase 2 default) keeps name-list questions."""
    rng = random.Random(seed * 104729 + 7)
    qs: list[Query] = []
    persons = corpus.persons

    def sample_person() -> str:
        return rng.choice(persons)

    # ── lookup 30% ────────────────────────────────────────────────────
    for _ in range(int(n_target * 0.30)):
        ft = rng.choice(list(LOOKUP_PHRASES))
        p = sample_person()
        qs.append(Query(
            shape="lookup", kind="value",
            question=rng.choice(LOOKUP_PHRASES[ft]).format(p=p),
            expected=corpus.current[p][ft],
            meta={"person": p, "fact_type": ft},
        ))

    # ── aggregation 15% ───────────────────────────────────────────────
    AGG = [("location", "How many people live in {v}?"),
           ("job", "How many people work as a {v}?"),
           ("pet", "How many people have a pet {v}?"),
           ("color", "How many people have {v} as their favorite color?")]
    for _ in range(int(n_target * 0.15)):
        ft, phr = rng.choice(AGG)
        counts = _counts(corpus, ft)
        v = rng.choice(list(counts))
        qs.append(Query(
            shape="agg", kind="number",
            question=phr.format(v=v),
            expected=counts[v],
            meta={"fact_type": ft, "value": v},
        ))

    # ── distribution 10% ──────────────────────────────────────────────
    DIST = [("location", "What are the 5 most common cities people live in?"),
            ("job", "What are the 5 most common jobs?"),
            ("color", "What are the 5 most common favorite colors?")]
    for _ in range(int(n_target * 0.10)):
        ft, phr = rng.choice(DIST)
        counts = _counts(corpus, ft)
        qs.append(Query(
            shape="dist", kind="top5",
            question=phr,
            expected=counts.most_common(),   # full ranking; scorer is tie-tolerant
            meta={"fact_type": ft},
        ))

    # ── intersection 10% (mix of non-empty and empty) ─────────────────
    for i in range(int(n_target * 0.10)):
        if i % 2 == 0:
            # guaranteed non-empty: derive from a real person
            p = sample_person()
            city, job = corpus.current[p]["location"], corpus.current[p]["job"]
            names = [q for q in persons
                     if corpus.current[q]["location"].lower() == city.lower()
                     and corpus.current[q]["job"].lower() == job.lower()]
            if (count_intersections_over is not None
                    and len(names) > count_intersections_over):
                qs.append(Query(
                    shape="intersect", kind="number",
                    question=(f"How many people live in {city} and "
                              f"work as a {job}?"),
                    expected=len(names),
                    meta={"city": city, "job": job},
                ))
            else:
                qs.append(Query(
                    shape="intersect", kind="names",
                    question=f"Who lives in {city} and works as a {job}?",
                    expected=names,
                    meta={"city": city, "job": job},
                ))
        else:
            # VERIFIED-empty intersection. At small N a random 3-way combo
            # is usually empty; at 125K persons it has an expected cohort
            # of ~20, so escalate to a 4th condition (pet) until a combo
            # is verified empty against ground truth. Never emit an
            # "empty" question whose true answer is non-empty.
            combo = None
            for level in (3, 4, 5):  # escalate conditions until truly empty
                for _ in range(60):
                    city = rng.choice(list(_counts(corpus, "location")))
                    job = rng.choice(list(_counts(corpus, "job")))
                    hobby = rng.choice(list(_counts(corpus, "hobby")))
                    pet = rng.choice(list(_counts(corpus, "pet"))) if level >= 4 else None
                    color = rng.choice(list(_counts(corpus, "color"))) if level >= 5 else None
                    names = [q for q in persons
                             if corpus.current[q]["location"].lower() == city
                             and corpus.current[q]["job"].lower() == job
                             and corpus.current[q]["hobby"].lower() == hobby
                             and (pet is None or corpus.current[q]["pet"].lower() == pet)
                             and (color is None or corpus.current[q]["color"].lower() == color)]
                    if not names:
                        combo = (city, job, hobby, pet, color)
                        break
                if combo:
                    break
            assert combo, "could not construct a verified-empty intersection"
            city, job, hobby, pet, color = combo
            parts = [f"lives in {city}", f"works as a {job}", f"enjoys {hobby}"]
            if pet is not None:
                parts.append(f"has a pet {pet}")
            if color is not None:
                parts.append(f"has {color} as their favorite color")
            question = "Who " + ", ".join(parts[:-1]) + f", and {parts[-1]}?"
            qs.append(Query(
                shape="intersect", kind="none",
                question=question,
                expected=[],
                meta={"city": city, "job": job, "hobby": hobby,
                      "pet": pet, "color": color},
            ))

    # ── negation + comparison 10% ─────────────────────────────────────
    for i in range(int(n_target * 0.10)):
        if i % 2 == 0:
            counts = _counts(corpus, "location")
            v = rng.choice(list(counts))
            qs.append(Query(
                shape="negcmp", kind="number",
                question=f"How many people do NOT live in {v}?",
                expected=len(persons) - counts[v],
                meta={"value": v},
            ))
        else:
            counts = _counts(corpus, "job")
            a, b = rng.sample(list(counts), 2)
            if counts[a] == counts[b]:
                expected = "equal"
            else:
                expected = a if counts[a] > counts[b] else b
            qs.append(Query(
                shape="negcmp", kind="value",
                question=(f"Which are there more of: people working as "
                          f"a {a} or as a {b}? Answer with the job title "
                          f"(or 'equal')."),
                expected=expected,
                meta={"a": a, "b": b},
            ))

    # ── version / history 10% ─────────────────────────────────────────
    movers = sorted(corpus.previous)
    for _ in range(int(n_target * 0.10)):
        p = rng.choice(movers)
        qs.append(Query(
            shape="history", kind="value",
            question=f"Where did {p} live before moving?",
            expected=corpus.previous[p]["location"],
            meta={"person": p},
        ))

    # ── refusal 10% ───────────────────────────────────────────────────
    for _ in range(int(n_target * 0.10)):
        p = sample_person()
        qs.append(Query(
            shape="refusal", kind="refusal",
            question=rng.choice(REFUSAL_PHRASES).format(p=p),
            expected=None,
            meta={"person": p},
        ))

    # ── paraphrase stress 5% ──────────────────────────────────────────
    for _ in range(max(1, int(n_target * 0.05))):
        ft = rng.choice(list(PARAPHRASE_STRESS))
        p = sample_person()
        qs.append(Query(
            shape="stress", kind="value",
            question=rng.choice(PARAPHRASE_STRESS[ft]).format(p=p),
            expected=corpus.current[p][ft],
            meta={"person": p, "fact_type": ft},
        ))

    rng.shuffle(qs)
    return qs
