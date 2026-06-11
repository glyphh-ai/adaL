# Communication — teaching Ada to speak and be spoken to

The layer that turns Ada from a recall+refusal substrate into a
participant in conversation. Every entry composes through the
infant/binary/prime stack so the sound of a word and its meaning
share the same substrate.

## What's here

| File | Entries | What it teaches |
|---|---|---|
| `phonotactics.yaml` | 10 | Rules for which phoneme sequences are valid English |
| `syllables.yaml` | 11 | Syllable templates (V, CV, CVC, CCVC, …) + stress patterns |
| `lexicon.yaml` | 44 | First words, each a sound sequence + a meaning cluster |
| `grammar.yaml` | 27 | Phrase/sentence templates + speech acts + dialogue moves |
| `teach.py` | — | Loads the full stack: layers 0-1 + infant + symbols + here |
| `verify.py` | — | Coverage + composition integrity + semantic-distance proof |

**92 entries, 508 composition links, 100% composition integrity.**
Substrate scales from 431 keys (after symbols) to **523 keys** total.

## The lexicon design point

Each word is a **knot in the substrate**, not just a phoneme
sequence. `lexicon.mama` composes through:

```
infant.mother + infant.warm + infant.comfort + infant.smell-mother
+ infant.hear-mother-voice + infant.coo + infant.smile-reflex
+ infant.caregiver-bond + phoneme.m + phoneme.ah + binary.same
```

Eleven concept atoms. Five of them are about warmth/care/closeness.
Two are the phoneme atoms /m/ and /ah/. One captures the doubled
syllable structure.

**Compare `lexicon.rock`:**

```
infant.object + infant.touch-firm + binary.not + binary.alive
+ binary.cannot + prime.move + phoneme.r + phoneme.ah
```

Zero overlap with `mama` on semantic keys. They share **only one
phoneme** (`ah`). In the substrate's vector space, they sit far apart
— exactly as they should.

This emerges for free from honest compositional encoding. We didn't
build a distance metric; we just wrote each entry truthfully and
the geometry fell out.

### The verify.py distance proof

```
lexicon.mama ↔ lexicon.hug    semantic-shared=3  ← close (warmth cluster)
lexicon.mama ↔ lexicon.milk   semantic-shared=2  ← close (feeding)
lexicon.mama ↔ lexicon.warm   semantic-shared=1  ← close
lexicon.mama ↔ lexicon.rock   semantic-shared=0  ← far (inert object)
lexicon.mama ↔ lexicon.gone   semantic-shared=0  ← far (absence)
lexicon.mama ↔ lexicon.cold   semantic-shared=0  ← far
lexicon.warm ↔ lexicon.cold   semantic-shared=2  ← same channel, opposite valence
```

The vector space already has the right shape before any neural net
training, because the symbolic substrate IS the geometry.

## Speech production pipeline

The substrate now has every piece needed for "Ada speaks":

```
meaning composition (infant.* + binary.* + prime.*)
   ↓ grammar templates fire and fill from lexicon
word sequence
   ↓ each word's perceptual.pronunciation gives the phoneme list
phoneme sequence
   ↓ audio synthesizer (NOT YET WRITTEN — one piece of code)
audible speech
```

The phoneme entries already carry the data needed for synthesis
(F1/F2 formants for vowels, manner+place+voiced for consonants).
A ~250-line Python synth using Klatt-style formant synthesis is the
one missing piece.

## Grammar and speech-act inventory

**Phrase templates** (6): NP-pronoun, NP-noun, NP-det-noun,
VP-intransitive, VP-transitive, VP-ditransitive

**Sentence templates** (7): S-declarative, S-question-wh,
S-question-yn, S-imperative, S-negation, S-possessive,
S-telegraphic-2word

**Speech acts** (9): statement, question, command, request, greeting,
farewell, agreement, refusal, acknowledgment

**Dialogue rules** (5): turn-taking, adjacency-pair, repair,
common-ground, topic-shift

## Run it

```bash
PYTHONPATH=. python benchmark/curriculum/agi/communication/teach.py
PYTHONPATH=. python benchmark/curriculum/agi/communication/verify.py
```

`verify.py` will print the semantic-distance proof table.

## What this enables

1. **A receivable substrate.** Ada can now parse incoming utterances
   by mapping them to known phonemes → words → grammar templates →
   speech acts. The pipeline is symbolic, not statistical.

2. **A producible substrate.** Given a meaning to express, grammar
   templates select words from the lexicon, words emit phoneme
   sequences, phoneme sequences feed a synthesizer.

3. **The trust gate.** Every utterance Ada produces is traceable: the
   meaning composes back through the substrate, the grammar template
   is named, the words are looked up. There is no sampling step.

## What's still missing

- The audio synthesizer (the one piece of code)
- More words in the lexicon (currently 44, easy to grow via tell_raw)
- More grammar templates for complex sentences
- Pragmatic / discourse-level features (politeness, register)
- Visual sensory anchors per primitive (the "sight + sound" thread)

These are engineering, not research. The substrate is ready.
