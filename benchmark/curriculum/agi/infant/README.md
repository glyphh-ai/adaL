# Infant — what a developing mind knows, grounded in NSM primes

A curriculum that teaches Ada the cognitive primitives an infant
acquires from birth through ~36 months, organized by developmental
stage. Every entry decomposes through the binary cognitive layer down
to the 63 NSM semantic primes.

The thesis being tested: **if the universal-prime substrate can
represent the universal-human cognitive starting point, then any
adult domain (chemistry, philosophy, law, math, ...) can be built on
top of it via composition.**

## The layer stack

```
prime.* (63)             — NSM semantic primes (universal)
  ↓
binary.* (54)            — pre-sensory cognitive distinctions (on/off)
  ↓
infant.* (179)           — developmental concepts in 12 stages
```

233 total entries (54 binary + 179 infant), 924 composition links,
**100% grounded to NSM primes within ≤6 hops** (mean 2.2).

## The stages

| Stage | Theme | Age band | Entries |
|---|---|---|---|
| 0 | Binary cognitive distinctions (pre-sensory) | innate | 54 |
| 1 | Sensations and reflexes | 0-3m | 28 |
| 2 | Perception (tracking, recognition, social smile) | 3-6m | 13 |
| 3 | Categories (people, objects, body parts) | 3-6m | 17 |
| 4 | Causality and means-end | 6-9m | 12 |
| 5 | Object permanence and spatial cognition | 9-12m | 14 |
| 6 | Intent and proto-language | 9-12m | 12 |
| 7 | Intentional actions on objects | 12-18m | 12 |
| 8 | First words and naming | 12-18m | 13 |
| 9 | Possession and self-recognition | 18-24m | 10 |
| 10 | Differentiated emotions (primary + self-conscious) | 18-24m | 14 |
| 11 | Social cognition (theory of mind precursors) | 24-36m | 12 |
| 12 | Combinatorial cognition (syntax, negation, counting) | 24-36m | 18 |

## Why the binary layer matters

Before specific sensations are categorized, the brain encodes raw
on/off distinctions: presence vs absence, same vs different, good vs
bad, here vs there, more vs less. These are the **building blocks of
all sensation and thought** — every richer concept decomposes through
them.

Example chain:
```
infant.empathy
  ↓ composed_of
binary.other, binary.feel, binary.self, binary.same, prime.because
  ↓
binary.other  = [prime.someone, prime.not, prime.i]
binary.feel   = [prime.feel]
binary.self   = [prime.i, prime.body]
binary.same   = [prime.the_same]
```

Every infant concept terminates at NSM primes within at most 6
composition hops. The mean is 2.2 — meaning most infant cognition is
2-3 levels above the prime substrate.

## What this enables

Three downstream uses:

1. **Cross-domain grounding.** Adult domain concepts (chemistry,
   philosophy, law) that map onto infant cognitive primitives compose
   more naturally. `philosophy.causation` can ground through
   `infant.cause-effect` and reach NSM primes via a shorter chain
   than directly via primes.

2. **Generation seed.** The infant stages are the foundation of the
   `generation/` thread. Language generation, inference, and
   composition rules all need primitives that bottom out in
   well-grounded human-universal concepts. Infant cognition IS that.

3. **Falsification surface.** If any infant concept fails to decompose
   cleanly, we've found a hole in either the primes or the binaries.
   Today: 100% decomposition. The 63 NSM primes + 54 binary
   distinctions are sufficient for the cognitive starting point of
   human development.

## Run it

```bash
PYTHONPATH=. python benchmark/curriculum/agi/infant/teach.py
PYTHONPATH=. python benchmark/curriculum/agi/infant/verify.py
```

`teach.py` loads layers 0-1 then all 13 infant stages, taking the
substrate from 122 keys to **355 keys**. `verify.py` confirms every
composition target exists and every chain bottoms out at primes.

## Source

Synthesized from:
- **Anna Wierzbicka** — NSM semantic primes (the 63 universal
  concepts that compose all human thought, from infant cognition
  onward).
- **Jean Piaget** — sensorimotor stages, object permanence, causality.
- **John Bowlby, Mary Ainsworth** — attachment theory (caregiver bond,
  stranger anxiety, separation anxiety).
- **Andrew Meltzoff** — neonatal imitation, intentionality reading.
- **Michael Tomasello** — joint attention, shared intentionality,
  the cooperative origins of language.
- **Lewis & Brooks-Gunn** — self-recognition (rouge test).
- **Henry Wellman** — theory-of-mind development.
- **Susan Carey, Elizabeth Spelke** — core knowledge systems
  (objects, agents, number, space).

## What this is NOT

Not a complete model of infant cognition. Not a developmental
psychology textbook. It's an **operational curriculum**: 233 concepts
that compose all the way down to 63 NSM primes, with 100% verifiable
grounding, ready to be the substrate on which any adult domain
builds.
