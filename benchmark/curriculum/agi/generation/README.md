# Generation — teaching Ada to *produce*, not just recall

## The question

So far Ada has been a **recall + refusal** substrate. Tell her facts,
ask questions, get back grounded answers or a structural ∅. The
chemistry and (in-flight) philosophy / law runs prove the substrate
ingests text into a compositional lattice at scale.

What we haven't tested: **can the substrate produce?**

Three modes worth distinguishing — each progressively more ambitious:

1. **Inference.** Given two grounded facts, derive a third that
   wasn't stated. Closed-world deduction over the composition graph.

2. **Linguistic generation.** Compose a grammatical sentence from
   substrate content without delegating sentence-building to an LLM.
   This means teaching Ada the principles of language (subject-verb-
   object, agreement, scope), not just feeding her sentences.

3. **Open generation.** Given a target meaning (some composition of
   primes), produce a description that traces back to those primes.
   This is the *inverse* of the chemistry traversal: the substrate
   walks a chain and emits language as it goes.

## Why this matters

The recall+refusal substrate is already differentiated against
LLM/RAG/KG. Generation is what closes the loop from **"Ada can be
trusted to answer correctly or not at all"** to **"Ada can write."**
Without it, Ada is the trustworthy backend that an LLM renders. With
it, Ada is the system.

The harder question — and what the user asked: **can we teach
principles instead of facts?**

Today the curriculum is fact-shaped:
```
- key: compound.water
  composed_of: [element.hydrogen, element.oxygen, bond.covalent, bond.hydrogen]
```

A principle-shaped entry would look like:
```
- key: rule.composition.alcohols
  composed_of: [element.carbon, element.hydrogen, group.hydroxyl]
  applies_to: any compound containing an -OH group bonded to a carbon
  generates: compound.<name> with composed_of including group.hydroxyl
```

That's not a fact. That's an **applicable rule** the substrate could
fire to generate new facts (or refuse to fire if preconditions aren't
met). Same compositional grounding, different cognitive surface.

## What's already in the codebase

These primitives exist but are not wired for generation:

- **`GlyphCognitiveLoop`** (`ada/memory/glyph_cognitive.py`) — runs
  multi-hop reasoning chains over the composition graph. The output is
  a sequence of activations, not a sentence — but the *structure* is
  there.
- **`GlyphDreamLoop` crystallization** (`ada/memory/glyph_dream.py:600`)
  — discovers cross-thought patterns and mints compound primitives.
  This is generation of new lattice nodes, just on a slow loop.
- **NSM primes themselves** (`benchmark/curriculum/agi/layer-0/primes.yaml`) are
  the bottoming-out vocabulary for any generation output. Every
  generated piece of meaning must terminate at primes, exactly like
  every recalled fact does.

## What's missing

- **Rule entries.** No schema yet for "if-then" / "applies-when" /
  "produces" composition entries. Would need an additional layer in
  the universal schema.
- **Forward-chaining over rules.** Given the substrate state, no engine
  yet fires applicable rules and proposes new facts.
- **Surface-form templates.** No mechanism for "render a composition
  chain as a sentence" without an LLM. Could be done with extremely
  thin grammar templates that compose at the same layer the substrate
  composes facts.
- **Backward-chaining for explanation.** "Why is X true?" → walk the
  chain that produces X. The substrate has the chain; the renderer is
  missing.

## Concrete next experiments (in increasing difficulty)

### 1. Closed-world deduction
Teach 20-30 syllogism rules (`if A is-a B and B is-a C then A is-a C`).
Take a known taxonomy (mammals, biology phyla, programming-language
families). Show that given 100 ground facts and the rules, the
substrate produces N new derived facts, all traceable.

### 2. Sentence templates → grounded sentences
Teach Ada a small grammar (~50 templates) for English declarative
sentences. Each template's slots are typed against the universal
schema. Then: given a composition chain, fill the template, emit a
sentence. No LLM in the loop. Measure: are the sentences grammatical?
Are they true (i.e., do they match the chain they were generated from)?

### 3. Cross-domain analogy
Given chemistry's `bond.covalent` and the abstract `prime.touch`,
and a separate domain's `relation.partnership` also grounding in
`prime.touch`, can the substrate propose "covalent bonds are like
partnerships" via shared primitive composition? This is the
substrate-native version of metaphor.

### 4. The honest test
Teach Ada the *principles* of one small language game (e.g.
arithmetic, or formal logic) — not facts, but the rules. Then ask
her to apply them to a novel instance. If she can, principle-shaped
teaching is real. If she can't, we've found the boundary.

## What this is NOT (yet)

- This is NOT an LLM replacement for natural language generation.
  The LLM is good at fluency; the substrate is good at correctness.
  The interesting frontier is using the substrate as the *content*
  source and a very thin LLM as the *renderer*.
- This is NOT a path to creative writing. Generation here means
  "produce a grounded statement consistent with the substrate," not
  "produce a poem."
- This is NOT yet implemented. This README is the open question, not
  the result.

## Files (when work starts)

```
benchmark/curriculum/agi/generation/
  README.md          this file
  rules/             rule-shaped curriculum entries (TBD)
  templates/         sentence templates (TBD)
  forward_chain.py   rule firing engine (TBD)
  render.py          composition-chain → sentence renderer (TBD)
  hard_questions.py  generation-mode hard questions (TBD)
```

## Where this thread sits

Started: 2026-05-30, in parallel with the philosophy + law cross-
domain Phase 1 runs. Not yet implemented. Open question, captured so
it doesn't get lost.

The next step is to wait for the philosophy + law runs to land, then
pick which of the four experiments above is the smallest possible
proof that principle-shaped teaching is real.
