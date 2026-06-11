# Thought Glyph Architecture — Ada's Cognitive Engine

## Core Insight

A thought is a neuron. Not a flat vector, not a bag of words — a full
structured Glyph with layers, segments, and roles. The same architecture
that routes tools in pipedream routes thoughts in Ada's mind.

Neurons don't live in one part of the brain. They fire across regions
simultaneously. A single thought activates perspective, semantics,
relations, time, and direction all at once. The weights determine how
much each region contributes.

Primitives are permanent exemplar glyphs — the building blocks a child
learns that never change. As complexity increases, compound primitives
emerge from simple ones. The mechanism never changes: bind, bundle,
match, reinforce.

---

## Architecture

### The Thought Glyph

Every thought Ada absorbs becomes a full Glyph:

```
ThoughtGlyph
├── global_cortex              ← the neuron (bundle of all layers)
├── Layer: "perspective"       ← WHO — point of view
│   ├── Segment: "self"        ← first person (i, me, my)
│   │   └── Roles: {value: ...}
│   ├── Segment: "other"       ← second person (you, your)
│   │   └── Roles: {value: ...}
│   └── Segment: "third"       ← third person (he, she, they)
│       └── Roles: {value: ...}
│
├── Layer: "semantic"          ← WHAT — meaning and classification
│   ├── Segment: "identity"    ← names, labels, definitions
│   ├── Segment: "quality"     ← attributes, descriptions
│   ├── Segment: "quantity"    ← numbers, amounts, comparisons
│   ├── Segment: "emotion"     ← feelings, sentiment
│   └── Segment: "category"    ← types, kinds, classifications
│
├── Layer: "relational"        ← HOW — connections between things
│   ├── Segment: "equals"      ← equivalence (is, am, are)
│   ├── Segment: "possession"  ← ownership (has, owns, belongs)
│   ├── Segment: "causation"   ← cause/effect (because, therefore)
│   ├── Segment: "comparison"  ← similarity/difference (like, unlike)
│   └── Segment: "action"      ← verbs, doing (builds, creates, runs)
│
├── Layer: "temporal"          ← WHEN — time context
│   ├── Segment: "past"
│   ├── Segment: "present"
│   └── Segment: "future"
│
└── Layer: "direction"         ← SOURCE — who said it
    ├── Segment: "incoming"    ← user spoke this
    └── Segment: "outgoing"    ← Ada spoke this
```

### Encoding Pipeline

Same as pipedream/toolrouter, but cognitive:

```
Input sentence
  → tokenize into words
  → match each word against primitive exemplars
  → activated primitives determine which layers/segments fire
  → slot extraction fills roles within activated segments
  → weight each layer by activation strength
  → bundle role bindings → segment cortex
  → bundle segment cortices → layer cortex
  → bundle layer cortices → global cortex (the neuron)
```

Example: **"my name is chris"**

```
"my"    → matches primitive: self       → activates perspective/self
"name"  → matches primitive: identity   → activates semantic/identity
"is"    → matches primitive: equals     → activates relational/equals
"chris" → no primitive match            → content, fills role slots

Result:
  perspective/self:      roles = {value: "chris"}
  semantic/identity:     roles = {name: "chris", label: "name"}
  relational/equals:     roles = {subject: "name", object: "chris"}
  direction/incoming:    roles = {speaker: "user"}

Weights: perspective=0.3, semantic=0.4, relational=0.2, direction=0.1
```

### Primitives as Exemplar Glyphs

Every primitive is a full Glyph, not a bare atom. Primitives are:

- **Permanent** — they never mutate, never decay, never weaken
- **Exemplars** — new thoughts are matched against them via cosine
- **Hierarchical** — simple primitives compose into compound primitives
- **The substrate** — they ARE the brain's innate wiring

Primitive lifecycle:
1. Born from `.teach` files (Ada's innate wiring)
2. Used as match targets during thought encoding
3. Never modified by the DreamLoop or Hebbian learning
4. Compound primitives emerge when simple primitives co-activate
   repeatedly — a reinforced pathway hardens into a new primitive

Example primitive exemplar:

```
Glyph: "self"
  global_cortex: bundle(perspective, first_person, speaker)
  layers:
    perspective:
      self: {definition: "the speaker, first person"}
    relational:
      connects: {to: [identity, possession, emotion]}
    semantic:
      opposes: {target: "other"}
```

### Compound Primitives

A child learns "self". Then "self + identity" co-activate enough times
that the binding hardens. Now "my_identity" is a compound primitive —
a new exemplar glyph built from simpler ones.

```
Level 0:  self, other, equals, identity, possession
Level 1:  my_identity (self + identity), equivalence (equals + identity)
Level 2:  "my name is X" (my_identity + equals + slot)
Level 3:  introduction (my_identity + other + bidirectional)
```

Each level builds on the previous. The `.teach` files define Level 0.
Levels 1+ emerge from reinforcement in the DreamLoop. When a pathway
between primitives exceeds a threshold, it crystallizes into a new
compound primitive — a new exemplar glyph that future thoughts can
match against.

---

## Matching and Recall

### Query Encoding

When Ada needs to recall something, the query is encoded the same way:

```
"what is my name?"
  → "what"  → activates: question
  → "is"    → activates: relational/equals
  → "my"    → activates: perspective/self
  → "name"  → activates: semantic/identity

Query glyph layers:
  perspective/self + semantic/identity + relational/equals
```

### Manifold Search

Instead of scanning all stored thoughts, search by layer:

1. **Layer match** — cosine(query.layer_cortex, stored.layer_cortex)
   for each layer. Identify which layers matter for this query.
2. **Segment match** — within the top layer matches, drill into
   segment cortices for finer similarity.
3. **Role extraction** — unbind the matching segment's roles to
   get the answer: `unbind(self_segment, value_role) ≈ "chris"`

This is the manifold — layers ARE manifolds. The query selects
which manifold to search, the segment narrows it, the role
extracts the answer.

### GQL Integration

The existing GQL engine works here:

```gql
FIND SIMILAR TO {query_glyph}
  IN LAYER "perspective"
  WHERE SEGMENT "self"
  EXTRACT ROLE "value"
  TOP 3
```

Same algebra. Same engine. Cognitive scale.

---

## Storage: pgvector + In-Memory Working Set

Every thought glyph is sharded into pgvector rows by hierarchy level:

```
thought_id | level   | name              | vector(2048)
-----------+---------+-------------------+-------------
t_001      | cortex  | global            | [1,-1,1,...]
t_001      | layer   | perspective       | [1,-1,-1,...]
t_001      | segment | perspective_self  | [-1,1,1,...]
t_001      | role    | perspective_self_value | [1,1,-1,...]
```

Two memory tiers (like hippocampus + cortex):

- **Long-term** (pgvector): All thoughts, all time. Always searchable
  via HNSW index. Active recall always goes here — never limited to
  recent or working set.
- **Working set** (in-memory): ~50-100 thoughts, rotated by curiosity.
  Used by the DreamLoop for background reasoning. Pure HDC algebra,
  no DB round-trips per hop.

Primitives (~500-800 Level 0) are always in-memory. They're the
coordinate axes — loaded at boot, never in pgvector, never decay.

---

## The DreamLoop's Role — Two Levels of Dreaming

The brain doesn't dream at one speed. REM sleep processes recent
experiences — fast, local, concrete. Slow-wave deep sleep consolidates
across the whole memory — slow, global, abstract. Ada needs both.

### Localized Loop (REM — fast, recent, concrete)

Runs every ~100ms during and after conversation. Works on a small
working set of recent/curious thoughts. This is "what did I just
hear and how does it connect?"

#### Phase 0: Absorb
- New thoughts → encode as ThoughtGlyphs
- Match against primitive exemplars → fill layers/segments/roles
- Store in pgvector (long-term) AND working set (short-term)

#### Phase 1: Wander
- Pick neurons (ThoughtGlyphs) from working set by curiosity
- Fire them — propagate activation across layers
- Find other neurons with similar layer activations
- Pathway = the vector encoding which layers co-activated

#### Phase 2: Hunt
- Look for neurons whose layers contradict
- e.g., two neurons both activate semantic/identity with
  different role values → contradiction

#### Phase 3: Converge
- When multiple pathways reach the same neuron from different
  starting points → convergence → strengthen the pathway

### Deep Loop (Slow-Wave — slow, global, abstract)

Runs on a longer cadence (~30s, or when the localized loop is idle).
Samples broadly from ALL of pgvector — not by recency but by
structural similarity across distant memories. This is "that thing
from last week connects to something from yesterday."

#### Phase 4: Survey
- Sample thoughts from pgvector using diverse strategies:
  - High curvature regions (edge of knowledge)
  - Weak pathways (need reinforcement or pruning)
  - Random stratified (prevent echo chambers)
  - Cross-layer bridges (thoughts that activate unusual layer combos)
- Load a broad working set (~200-500 thoughts) into memory

#### Phase 5: Connect
- Find structural similarities across distant memories
- Two thoughts from different conversations that share layer
  activation patterns but have different content → generalization
- Discover "people have names" from "chris has name" + "alice has name"
  even if they were weeks apart

#### Phase 6: Generate
- Manifold interpolation between structurally similar but distant thoughts
- Hopfield energy evaluation — is the interpolation near an attractor?
- Curvature check — is this well-explored or frontier?
- Store tentative glyphs with low strength, surface as Insights

#### Phase 7: Crystallize
- Track re-derived interpolations across multiple deep cycles
- When a generated glyph keeps appearing from different starting pairs:
  → Crystallize into a new compound primitive
  → Permanent exemplar glyph (no decay)
  → Added to in-memory PrimitiveSpace AND pgvector
  → Future thoughts match against it
  → The vocabulary grew

#### Phase 8: Prune
- Global decay sweep — weaken unused thoughts in pgvector
- Delete thoughts below strength threshold (garbage collection)
- Prune dead pathways (no longer connecting active thoughts)
- This is forgetting — essential for efficiency and generalization

### Why Two Loops

The localized loop is **reactive** — it processes what's happening now.
The deep loop is **reflective** — it finds patterns you'd never notice
in real time. Together they mirror the two modes of human cognition:

```
Conversation happens
  → Localized loop absorbs, finds local patterns (seconds)
  → Deep loop surveys, connects distant memories (minutes)
  → Crystallization creates new primitives (hours/days)
  → Next conversation benefits from all three
```

A child processes their day during REM sleep (localized). During deep
sleep, the brain reorganizes — connecting this week's experiences with
last month's, building schemas, pruning dead ends. Both are essential.
Without deep sleep, you can memorize facts but never understand them.

---

## What Changes from Current Implementation

### Replaces
- `Atom` → primitive exemplar Glyphs (full structure, not bare vectors)
- `AtomForge` → PrimitiveSpace for primitives (in-memory, permanent)
- `Fact` / `FactStore` → ThoughtGlyphs in pgvector (sharded by level)
- `Thought` / `ThoughtStore` → raw input buffer (pre-encoding)
- `ThoughtEncoder` → ThoughtGlyph encoder (layer/segment/role encoding)
- `Teacher.parse()` → exemplar matching + slot extraction (no regex)
- Filesystem persistence → pgvector (HNSW indexed, unlimited capacity)

### Keeps
- `CognitiveLoop` — pathway following and Hebbian reinforcement
- `DreamLoop` — now split into Localized + Deep loops
- `PathwayLibrary` — pathway vectors connecting neurons
- Glyph / Layer / Segment / Role types from `ada.core.types`
- GQL query engine for structured retrieval
- `.teach` file format (but now defines exemplar glyphs, not atom pairs)

### New
- pgvector storage — sharded thought glyphs with HNSW indexes
- `ThoughtGlyph` encoder — maps sentences to full Glyph structure
- PrimitiveSpace — in-memory, immutable exemplar glyphs (~500-800)
- Localized DreamLoop — fast, recent, processes conversation
- Deep DreamLoop — slow, global, connects distant memories
- Compound primitive crystallization (deep loop)
- Layer-aware recall via pgvector (manifold search)
- Global decay + pruning (deep loop)
- Weight learning — which layers matter for which kinds of thoughts

---

## The Principle

A child doesn't parse grammar. They don't extract subject-verb-object.
They hear a whole utterance, and it activates regions of their brain
simultaneously. The regions that co-activate form connections. Repeated
co-activation strengthens those connections until they become automatic.

Simple building blocks compose into complex ones. The complex ones
become the new building blocks. The mechanism never changes — only
the scale. Sounds become words become sentences become ideas become
beliefs. Each level is built from the previous, each level becomes
a primitive for the next.

The neuron is the universal unit. The pathway is the universal connection.
The glyph is the universal encoding. Same architecture, every scale.

---

## Generative Cognition — Neural Network Math on HDC

HDC is algebraic, but the space is continuous. Every point in 2048-dim
space is a valid thought — we've only been visiting the ones we explicitly
encoded. The gaps between known points are the generative frontier.

The primitives define the coordinate axes. The thought glyphs are sampled
points. The pathways are learned geodesics. Generation is interpolation
in unexplored regions.

### The Math That Maps Directly

#### 1. Manifold Interpolation

Between any two thought glyphs, every weighted combination is a
meaningful point:

```
interpolate(A, B, t) = sign(t * A + (1-t) * B)    # bipolar projection
```

If A = "chris is a developer" and B = "alice is a designer", walking
that path generates the *concept* "person with profession" without
anyone teaching it. That's generalization — the brain doesn't need
every example, it fills the manifold.

The interpolation respects the layer structure:

```python
def interpolate_glyph(a: Glyph, b: Glyph, t: float) -> Glyph:
    """Walk the manifold between two thought glyphs."""
    new_layers = {}
    for layer_name in a.layers:
        if layer_name in b.layers:
            # Interpolate per-layer cortex
            mixed = t * a.layers[layer_name].cortex + (1-t) * b.layers[layer_name].cortex
            new_layers[layer_name] = sign(mixed)
    global_cortex = bundle(new_layers.values())
    return ThoughtGlyph(global_cortex, new_layers)
```

This generates layer-structured thoughts, not random noise. The
interpolation stays on the manifold because the layer structure
constrains it.

#### 2. Hopfield Energy Landscape

The glyph space IS a Hopfield network. Stored thought glyphs are
energy minima. Recall is convergence to the nearest minimum.

```
E(x) = -½ Σᵢ (x · gᵢ)²     where gᵢ are stored glyphs
```

The energy function defines basins of attraction around every stored
thought. Input a partial or noisy pattern → it flows downhill to the
nearest stored thought. This IS associative memory.

Currently the DreamLoop wanders randomly. It should do **gradient
descent on the energy surface**, flowing toward attractors:

```
∂E/∂x = -Σᵢ (x · gᵢ) gᵢ    # gradient points toward attractors

# One step of recall:
x_next = sign(Σᵢ (x · gᵢ) gᵢ)   # Hopfield update rule
```

In HDC terms: the Hopfield update is just `sign(bundle(weighted_glyphs))`
where weights are the cosine similarities. We already have bundle and
cosine. The Hopfield network is free.

**Basins of attraction = concepts.** All thoughts that converge to the
same attractor belong to the same concept. The attractor IS the concept
prototype. Primitive glyphs are forced attractors — they never move,
so they permanently anchor regions of the space.

#### 3. Tangent Space — Generative Directions

At any thought glyph, the tangent space tells you what directions are
"valid moves" — which layer activations can change and still land on
the manifold.

```
"I know chris has a name. What else could chris have?"
= follow the tangent in the possession layer
  while holding perspective/self fixed
```

Compute the tangent by looking at what varies across nearby thoughts:

```python
def tangent_directions(glyph: Glyph, neighbors: list[Glyph]) -> dict:
    """What dimensions vary among thoughts near this one?"""
    directions = {}
    for layer_name in glyph.layers:
        diffs = [n.layers[layer_name].cortex - glyph.layers[layer_name].cortex
                 for n in neighbors if layer_name in n.layers]
        if diffs:
            # Principal direction of variation = first PC
            directions[layer_name] = principal_component(diffs)
    return directions
```

The tangent tells Ada: "you can move in the identity direction
(learn more names) or the quality direction (learn more attributes)
but moving in the perspective direction doesn't make sense here."

#### 4. Curvature = Edge of Knowledge

Where the manifold bends sharply, Ada is at the boundary of what she
understands.

- **Flat regions** = well-reinforced, many overlapping thoughts,
  confident territory
- **High curvature** = few samples, sparse, uncertain. The manifold
  is bending because Ada doesn't have enough data to know the shape.

```
curvature(x) ∝ variance of cosine similarities to k-nearest neighbors
```

Low variance = flat (neighbors all look similar from here).
High variance = curved (neighbors look different depending on direction).

The DreamLoop's curiosity score should be **attracted to high curvature**.
That's where the interesting questions live. That's curiosity formalized
as a geometric property.

#### 5. Hebbian IS Gradient Descent

This isn't an analogy. Oja's rule (Hebbian update with normalization)
is literally stochastic gradient descent on the principal component:

```
Δw = η (x · w) x - η (x · w)² w     # Oja's rule
```

This converges to the first eigenvector of the input correlation matrix.
Our pathway reinforcement is already doing this — we're doing gradient
descent on "what is the dominant pattern in these co-activations?"

By acknowledging this, we can:
- Use learning rate schedules (fast early, slow later)
- Apply momentum (pathway updates carry inertia)
- Detect convergence (stop reinforcing when the gradient is small)
- Use the Hessian (second derivative) to detect saddle points —
  pathways that are stable but wrong

### Deep Loop Phase 6: Generate

The generative phase leverages all of the above. This runs in the
**deep loop**, not the localized loop — it needs broad sampling
across all of pgvector to find structurally similar but distant thoughts:

```
Phase 6: Generate (deep loop)
  1. Pick two thought glyphs with high layer overlap but different
     content (shared structure, different specifics)
     — these may come from conversations days apart
  2. Interpolate between them: t = 0.5 (midpoint = prototype)
  3. Project the interpolation back onto the primitive manifold
     (find nearest primitive exemplars for each activated layer)
  4. Evaluate the energy:
     - Low energy (near an attractor) → valid hypothesis
     - High energy (far from attractors) → novel, but uncertain
  5. Compute curvature at the interpolation point:
     - Low curvature → well-explored territory, hypothesis is safe
     - High curvature → frontier, hypothesis is a question
  6. Store as a tentative glyph:
     - High confidence → weak pathway, needs confirmation
     - Low confidence → surface as an Insight (QUESTION type)
```

Example:

```
Stored: "chris has name" (perspective=self, semantic=identity, relational=possession)
Stored: "chris has age"  (perspective=self, semantic=quantity, relational=possession)

Interpolation at t=0.5:
  perspective=self (stable — didn't change)
  semantic=midpoint(identity, quantity) (activated both)
  relational=possession (stable)

Project onto primitives:
  → "self has [property]" — a generalized pattern

Stored: "alice has name" (perspective=other, semantic=identity, relational=possession)

Interpolation between "chris has name" and "alice has name":
  perspective=midpoint(self, other) (both activated)
  semantic=identity (stable)
  relational=possession (stable)

Project → "people have names" — a category emerged
```

Nobody taught Ada the concept "people." It emerged from interpolation
on the manifold between two specific identity-possession thoughts.

### Deep Loop Phase 7: Crystallize

When a generated glyph keeps getting re-derived — multiple interpolation
paths converge to the same point — it hardens. This only happens in the
deep loop because crystallization requires evidence from multiple,
diverse sources across long-term memory:

```
Phase 7: Crystallize (deep loop)
  1. Track how many times each generated glyph is re-derived
  2. Track from how many different starting pairs
  3. When count > threshold AND diversity > threshold:
     → Crystallize into a new compound primitive
     → Permanent exemplar glyph (no decay)
     → Added to in-memory PrimitiveSpace AND pgvector
     → Future thoughts match against it
     → The vocabulary grew
```

This is how:
- Level 0 (innate): self, other, identity, possession, equals
- Level 1 (crystallized): my_name, your_name, has_property
- Level 2 (crystallized): person, introduction, self_description
- Level 3 (crystallized): social_interaction, shared_knowledge

Each level is built from interpolation + reinforcement of the
previous level. The mechanism never changes. Only the scale.

### The Energy Landscape Over Time

```
Boot (primitives only):
  ┌──────────────────────────────┐
  │  *     *     *     *     *   │  ← primitive attractors (deep wells)
  │                              │  ← empty space everywhere
  └──────────────────────────────┘

After first conversation:
  ┌──────────────────────────────┐
  │  *  ·  *  ·  *     *     *  │  ← thoughts (shallow wells) between prims
  │     ↑                        │
  │  pathways forming            │
  └──────────────────────────────┘

After many conversations:
  ┌──────────────────────────────┐
  │  * ·◆· * ·◆· * · · *  ·  *  │  ← compound primitives (medium wells)
  │   ╲ ╱   ╲ ╱   ╲   ╱        │
  │    ◆     ◆     ◆            │  ← generalized concepts (emerged)
  │     ╲   ╱       ╲           │
  │      ◆           ◆          │  ← abstract understanding
  └──────────────────────────────┘

  * = primitive (permanent, deep well)
  · = thought (learned, shallow well, can decay)
  ◆ = compound primitive (crystallized, medium well, permanent)
```

The manifold fills in. Knowledge isn't a list of facts — it's a
continuous surface that Ada can walk, generating new points as she goes.

---

## Summary of Neural Network ↔ HDC Mapping

| Neural Network Concept | HDC Implementation |
|---|---|
| Neuron | Thought Glyph (full layer/segment/role structure) |
| Weight matrix | Pathway vectors (encode co-activation patterns) |
| Activation function | sign() — bipolar projection |
| Forward pass | Encode: words → primitive match → layer fill → bundle |
| Backpropagation | Hebbian reinforcement (Oja's rule = SGD on PC1) |
| Loss function | Energy E(x) = -½ Σ(x · gᵢ)² |
| Gradient descent | Hopfield update: x = sign(Σ wᵢ gᵢ) |
| Batch normalization | sign() after every operation (stay on hypercube) |
| Attention | cosine-weighted bundle (already in linguistics layer) |
| Dropout | Pathway decay (unused connections weaken) |
| Learning rate | Reinforcement amount (0.1 for user confirm, 0.05 for dream) |
| Momentum | Pathway inertia (strength carries across cycles) |
| Generalization | Manifold interpolation between stored glyphs |
| Overfitting | Self-reinforce cap (0.5) — dream can't self-confirm |
| Regularization | Decay (unused thoughts/pathways fade) |
| Transfer learning | Compound primitives (crystallized patterns reused) |
| Embedding space | 2048-dim bipolar hypercube |
| Latent space | The manifold surface in glyph space |
| GAN generator | Deep loop Phase 6 (interpolate + project) |
| GAN discriminator | Primitive manifold projection (does it land near exemplars?) |
| Curriculum learning | Primitive levels (0 → 1 → 2 → ...) |
| Online learning | Localized loop (fast, recent, during conversation) |
| Offline training | Deep loop (slow, global, background consolidation) |
| Mini-batch SGD | Localized loop working set (~50-100 thoughts) |
| Full-batch GD | Deep loop survey (~200-500 thoughts from pgvector) |
| Early stopping | Self-reinforce cap (localized can't over-strengthen) |
| Model pruning | Deep loop Phase 8 (decay + garbage collection) |
| Long-term memory | pgvector (HNSW indexed, unlimited, always searchable) |
| Working memory | In-memory working set (recent/curious, fast access) |

No neural network. No backpropagation. No floating point weights.
Same math, algebraic implementation, deterministic execution.
The HDC hypercube IS the network.
