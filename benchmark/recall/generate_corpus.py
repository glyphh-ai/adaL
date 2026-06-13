"""
Generate the frozen recall corpus — see PROTOCOL.md.

Facts are deterministic from templates. Query phrasings are written by
Haiku ONCE per (fact-type, query-type) and frozen to JSON, so the
wordings aren't hand-chosen and the retrieval run is reproducible.

    ANTHROPIC_API_KEY=... PYTHONPATH=. \
      .venv/bin/python benchmark/recall/generate_corpus.py
"""

import json
import os
import random
import sys
from pathlib import Path

OUT = Path(__file__).parent / "corpus.json"
SEEDS = [1, 2, 3, 4, 5]
N_PERSONAS = 60

NAMES = ["harper", "rena", "marco", "june", "tobias", "lena", "omar",
         "priya", "wendell", "sofia", "dmitri", "amara", "felix", "noor",
         "callum", "ivy", "baxter", "celine", "rocco", "thea", "silas",
         "wren", "ezra", "opal", "jude", "freya", "boris", "lila", "amos",
         "greta", "nadia", "cyrus", "delphine", "hugo", "maren", "quinn",
         "rosa", "petra", "nico", "vera", "arlo", "maeve", "knox", "pearl",
         "cyril", "dot", "remy", "isla", "bodhi", "sage", "flint", "esme",
         "atlas", "juniper", "ozzy", "delia", "milo", "tasha", "elliot",
         "carson"]
CITIES = ["denver", "austin", "boston", "portland", "tucson", "savannah",
          "boise", "madison", "raleigh", "omaha", "fresno", "tulsa",
          "spokane", "laredo", "tampa", "reno", "norfolk", "anchorage",
          "fargo", "provo"]
JOBS = ["engineer", "doctor", "teacher", "chef", "lawyer", "carpenter",
        "florist", "pilot", "machinist", "surveyor", "tailor", "beekeeper",
        "glassblower", "cartographer", "barber", "plumber"]
EMPLOYERS = ["meridian labs", "northwind co", "atlas freight",
             "cedar & sons", "blue harbor", "ironwood group",
             "vellum press", "halcyon studios"]
COLORS = ["crimson", "teal", "amber", "violet", "olive", "coral",
          "indigo", "maroon", "turquoise", "sienna"]
HOBBIES = ["rock climbing", "watercolor painting", "beekeeping",
           "distance running", "chess", "pottery", "birdwatching",
           "woodworking", "sailing", "astronomy"]
VEHICLES = ["a red pickup truck", "a vintage motorcycle", "a blue sedan",
            "an electric bike", "a camper van", "a cargo bicycle"]

# fact-type → (template, pool, forbidden keywords for non-direct queries)
FACT_TYPES = {
    "residence": ("{name} lives in {v}.", CITIES,
                  ["live", "lives", "living", "reside", "resides",
                   "residence", "home"]),
    "job":       ("{name} works as a {v}.", JOBS,
                  ["work", "works", "working", "job"]),
    "employer":  ("{name} is employed by {v}.", EMPLOYERS,
                  ["employ", "employed", "employer", "employs"]),
    "color":     ("{name}'s favorite color is {v}.", COLORS,
                  ["color", "colour", "favorite color", "favourite"]),
    "hobby":     ("{name} spends weekends on {v}.", HOBBIES,
                  ["weekend", "weekends", "spends", "hobby", "hobbies"]),
    "vehicle":   ("{name} drives {v}.", VEHICLES,
                  ["drive", "drives", "driving", "vehicle"]),
}

# How many query phrasings of each type to ask the LLM for, per fact type.
QUERY_TYPES = ["direct", "paraphrase", "conceptual", "contextual"]

_GEN_SYSTEM = """You write retrieval probes for a memory test. The
stored fact is exactly: "{tmpl}". Produce {n} DISTINCT {qtype} probes,
each referring to the person by the literal token {{name}}.

Definitions (follow strictly):
- direct: a question that REUSES the fact's own keywords.
- paraphrase: a question for the SAME information, but you MUST NOT use
  any of these words or their forms: {forbidden}. Use different wording.
- conceptual: a question via a synonym, category, or roundabout phrase;
  again you MUST NOT use any of: {forbidden}.
- contextual: NOT a question — a first-person statement of a situation
  whose resolution depends on this fact, using as few of the fact's
  words as possible and NONE of: {forbidden}. Example for a 'lives in'
  fact: "I'm mailing a package to {{name}} and need their city."

Each probe MUST contain {{name}}. Return ONLY a JSON array of {n}
strings, nothing else."""


def _facts_for_seed(seed):
    rng = random.Random(seed)
    names = NAMES[:N_PERSONAS]
    facts = []  # (id, name, fact_type, value, sentence)
    for i, name in enumerate(names):
        for ftype, (tmpl, pool, _fb) in FACT_TYPES.items():
            val = pool[(i * 7 + seed + hash(ftype)) % len(pool)]
            facts.append({
                "id": f"{seed}:{name}:{ftype}",
                "name": name, "fact_type": ftype, "value": val,
                "sentence": tmpl.format(name=name, v=val),
            })
    return facts


def _gen_phrasings(client, ftype, tmpl, forbidden, qtype, n=6):
    """Ask Haiku for n {qtype} query templates (with {name} token).
    For non-direct types, drop any phrasing that leaks a forbidden
    keyword — enforced here, not trusted to the model."""
    import re
    sysmsg = _GEN_SYSTEM.format(n=n, qtype=qtype, tmpl=tmpl,
                               forbidden=", ".join(forbidden))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=500,
        system=sysmsg,
        messages=[{"role": "user", "content": f"Produce the {n} {qtype} probes."}])
    raw = msg.content[0].text
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    out = []
    for s in arr:
        if not (isinstance(s, str) and "{name}" in s):
            continue
        low = s.lower()
        if qtype != "direct" and any(re.search(rf"\b{re.escape(w)}\b", low)
                                     for w in forbidden):
            continue  # leaked a banned keyword — reject
        out.append(s)
    return out


def main():
    import anthropic
    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

    # 1) phrasing templates — generated once, shared across seeds/personas
    print("generating query templates with Haiku...", file=sys.stderr)
    templates = {}  # (fact_type, qtype) -> [template strings with {name}]
    for ftype, (tmpl, _, forbidden) in FACT_TYPES.items():
        for qtype in QUERY_TYPES:
            ts = _gen_phrasings(client, ftype, tmpl, forbidden, qtype, n=6)
            templates[f"{ftype}|{qtype}"] = ts
            print(f"  {ftype}/{qtype}: {len(ts)} kept", file=sys.stderr)

    # 2) negative attributes — fact types a person does NOT have a fact for
    #    (every person has all 6 here, so negatives target an absent
    #    attribute entirely: pet / allergy / birthplace etc.)
    NEG_TEMPLATES = [
        "what is {name}'s pet's name?",
        "what is {name} allergic to?",
        "where was {name} born?",
        "what instrument does {name} play?",
        "what is {name}'s blood type?",
    ]

    corpus = {"seeds": {}, "templates": templates,
              "neg_templates": NEG_TEMPLATES}
    for seed in SEEDS:
        facts = _facts_for_seed(seed)
        by_name = {}
        for f in facts:
            by_name.setdefault(f["name"], []).append(f)
        queries = []
        rng = random.Random(seed * 31)
        for f in facts:
            for qtype in QUERY_TYPES:
                ts = templates.get(f"{f['fact_type']}|{qtype}", [])
                if not ts:
                    continue
                tmpl = ts[rng.randrange(len(ts))]
                queries.append({
                    "query": tmpl.replace("{name}", f["name"]),
                    "qtype": qtype, "target_id": f["id"],
                })
        # negatives: pick random people, ask about an absent attribute
        names = list(by_name)
        for _ in range(40):
            nm = names[rng.randrange(len(names))]
            tmpl = NEG_TEMPLATES[rng.randrange(len(NEG_TEMPLATES))]
            queries.append({"query": tmpl.replace("{name}", nm),
                            "qtype": "negative", "target_id": None})
        corpus["seeds"][str(seed)] = {"facts": facts, "queries": queries}
        print(f"seed {seed}: {len(facts)} facts, {len(queries)} queries",
              file=sys.stderr)

    OUT.write_text(json.dumps(corpus, indent=1))
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
