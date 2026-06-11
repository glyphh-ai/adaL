# Layer 0 — Natural Semantic Metalanguage primes

The bedrock. ~65 cognitive primitives drawn from Anna Wierzbicka's
**Natural Semantic Metalanguage** (NSM) — the set of concepts that
appear in *every* human language and cannot be defined in terms of
anything simpler.

These are not vocabulary. They are the **slots in which all other
vocabulary is defined**.

## What's in here

- [`primes.yaml`](primes.yaml) — the data. One entry per prime, each
  giving its universal-schema slot fill (entity name + kind + subkind,
  semantic category, etc.) and a citation.
- [`teach.py`](teach.py) — loads the yaml and ingests each prime into
  Ada via `space.tell_raw()`. Zero LLM calls.
- [`verify.py`](verify.py) — asks Ada to enumerate her primes by
  category. If a category comes back empty, the curriculum has a hole.

## How to load

```bash
PYTHONPATH=. python benchmark/curriculum/agi/layer-0/teach.py
# Loads ~65 primes. Substrate now has the bedrock.

PYTHONPATH=. python benchmark/curriculum/agi/layer-0/verify.py
# Asks Ada to recall primes by category. Reports coverage.
```

## Categories (NSM)

| Category | Primes (examples) | Why irreducible |
|---|---|---|
| Substantives | I, you, someone, something, body, people | Referents — defining them requires using them. |
| Relational substantives | kind, part | Structural — needed to talk about everything else. |
| Determiners | this, the same, other | Pointing — pre-linguistic. |
| Quantifiers | one, two, some, all, many | Cardinality — built into perception. |
| Evaluators | good, bad | Affect — pre-linguistic and universal. |
| Descriptors | big, small | Magnitude — pre-linguistic. |
| Mental predicates | know, think, want, feel, see, hear | Mind-states — only definable via self-reference. |
| Speech | say, words, true | Communication primitives. |
| Actions, events | do, happen, move | Causality primitives. |
| Existence | there is, have, be | Ontological. |
| Life | live, die | Biological universal. |
| Time | when, now, before, after, moment | Temporal axes. |
| Space | where, here, above, below, near, far, inside | Spatial axes. |
| Logical | not, can, because, if, maybe | Inference primitives. |
| Augmentor | very, more | Intensifiers. |
| Similarity | like, as | Comparison primitives. |

## Citation

Wierzbicka, Anna. *Semantics: Primes and Universals.* Oxford University
Press, 1996. (And ~50 years of follow-up work by Goddard, Wierzbicka,
and the NSM research community.)

The set we use is the standard 65-prime inventory documented at
<https://intranet.secure.griffith.edu.au/schools-departments/natural-semantic-metalanguage>
and in the cross-linguistic studies underlying the NSM program.
