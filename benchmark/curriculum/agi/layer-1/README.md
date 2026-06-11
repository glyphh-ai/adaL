# Layer 1 — perceptual / numerical / spatial / logical / temporal

Each concept in this layer cites the **layer-0 primes it's composed
from**. That composition is stored in the substrate as explicit
relational facts (`subject = layer-1 key, predicate = composed_of,
object = layer-0 key`), so the chain is *queryable* — not implicit.

## Five domains, ~55 entries

| File | Contents | Count | Source |
|---|---|---|---|
| [`colors.yaml`](colors.yaml) | Berlin & Kay's 11 universal color terms | 11 | Berlin & Kay 1969 |
| [`numbers.yaml`](numbers.yaml) | 0–10, plus 100 and 1000 | 13 | elementary mathematics |
| [`spatial.yaml`](spatial.yaml) | cardinal directions, prepositions, relative directions | 15 | geographic + English |
| [`logical.yaml`](logical.yaml) | Boolean connectives + ordering comparators | 9 | propositional logic |
| [`temporal.yaml`](temporal.yaml) | time units (day, hour, year) + references (past/present/future) | 11 | SI / elementary |

## Load

```bash
PYTHONPATH=. python benchmark/curriculum/agi/layer-1/teach.py
# Loads layer-0 first (~63 primes), then layer-1 (~55 concepts +
# ~150 composition facts), all via tell_raw. Zero LLM calls.

PYTHONPATH=. python benchmark/curriculum/agi/layer-1/verify.py
# Coverage + composition integrity check. Reports dangling refs.

PYTHONPATH=. python benchmark/curriculum/agi/layer-1/explore.py
# Five substrate-native demos: composition traversal,
# inverse composition, category enumeration, role-value retrieval,
# full primitive trace.
```

## What this layer makes possible

With composition explicit in the substrate, Ada answers questions
*structurally* that an LLM can only answer by text-reasoning:

| Question | Substrate operation | LLM alternative |
|---|---|---|
| "What primes is `color.blue` composed of?" | One relational query on `(subject=color.blue, predicate=composed_of)`. | Reason over loaded YAML text. |
| "What higher concepts use `prime.see`?" | One relational query on `(object=prime.see, predicate=composed_of)`. | Scan all text for references. |
| "What colors does Ada know?" | One query on `entity.kind = color`. | Enumerate from text. |
| "What things are warm-colored?" | One query on `perceptual.temperature = warm`. | Scan text for warm color mentions. |
| "Trace `color.purple` to all primes it depends on." | BFS along composed_of until everything is a `prime.*`. | Multi-step reasoning, prone to error. |

Each substrate operation is **O(N facts)** with no LLM cost. The LLM
alternative is approximate and probabilistic. As the substrate grows,
the gap widens.

## Composition mechanic

Every YAML entry has a `composed_of: [layer-0 keys]` list. The loader
expands each entry into:

1. One main glyph carrying the concept's universal-schema slots
   (entity, perceptual, spatial, etc.)
2. One relational glyph per composition link, with
   `subject = entry_key, predicate = composed_of, object = parent_key`.

So `color.purple → composed_of: [color.red, color.blue, prime.see, prime.thing]`
becomes one glyph for purple + four composition facts. Querying any of
them traverses the lattice.

## Curriculum integrity

`verify.py` checks two things:

1. **Coverage** — every YAML key actually lands in the substrate.
2. **Composition integrity** — every `composed_of` reference points at
   a key that exists somewhere in layer-0 or layer-1. Dangling
   references would mean the curriculum is broken.

If either check fails, you've found a bug in the curriculum (typo, wrong
layer name, etc). Fix the YAML; re-run.
