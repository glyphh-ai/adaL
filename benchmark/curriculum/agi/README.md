# AGI curriculum

A layered curriculum aimed at teaching Ada the compositional primitives
that, in stacked combination, can encode arbitrary cognition. Each layer
builds explicitly on the previous.

## Thesis

A cognitive substrate becomes AGI-shaped when it has:

1. A **universal schema** that every fact maps into (entity, perceptual,
   spatial, temporal, relational, quantitative, epistemic — see
   `ada/cognitive/universal.py`).
2. A **bottom layer of irreducible primitives** that cannot be
   decomposed in terms of anything simpler.
3. Each higher layer's facts **explicitly composed in terms of lower
   layers**, so any concept can be traced back to its primitives.
4. Sufficient breadth at every layer to cover the input space — that
   is the "needs massive scale" part.

LLMs approximate this via gradient descent on text. Ada constructs it
explicitly via curriculum.

## Layers

| Layer | What | Why these primitives | Status |
|---|---|---|---|
| [`layer-0`](layer-0/) | NSM semantic primes (~65) | Wierzbicka's 50-year empirical work on words that exist in every human language and cannot be defined in simpler terms — the closest thing to "atomic" the linguistics literature offers | **built** |
| `layer-1` *(planned)* | Perceptual + numerical primitives | Berlin & Kay's 11 universal color terms, numbers 0–10, basic spatial relations, formal logical operators | planned |
| `layer-2` *(planned)* | Physical / biological categories | Food, animal, tool, vehicle, plant, mineral — defined in terms of layer-1 properties | planned |
| `layer-3` *(planned)* | Action / event primitives | Move, eat, build, change, decide — defined in terms of layer-2 entities + layer-1 properties | planned |
| `layer-4` *(planned)* | Social / mental concepts | Promise, trust, debt, plan, hope — defined in terms of mental primitives + actions | planned |
| `layer-5` *(planned)* | Domain-specific bodies | Chemistry, music, programming, law — built on top of the lower stack | planned |

## Order of teaching

The substrate doesn't enforce layer order at recall time (you can ask
about a higher-layer concept before lower-layer primitives are loaded —
recall will just fail more gracefully because the chain bottoms out).
But teaching out of order means later layers can't *reference* earlier
ones, which defeats the point. Always teach upward.

## Verifying a layer

Each `layer-N/verify.py` (where present) asks Ada questions whose
answers should be in the layer's own taught material. If verify fails
for a layer, that layer's curriculum has a hole — either a missing
fact, a mis-specified slot, or a primitive that wasn't actually primitive.

The verification step is the audit. It's *the* property that
distinguishes a curriculum-loaded substrate from a gradient-trained
LLM: you can prove exactly what was learned, and exactly what wasn't.
