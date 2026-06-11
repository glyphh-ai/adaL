# Symbols — digits, letters, phonemes

The bridge from infant cognitive primitives to the **generation
substrate**. Every entry is something Ada can **see** (digits,
letters), **say/hear** (phonemes), or both (letters paired with their
phonemes).

## What's here

| File | Entries | Each entry is |
|---|---|---|
| `digits.yaml` | 10 | a digit symbol 0-9 (visual + spoken) |
| `letters.yaml` | 26 | a letter A-Z (visual + spoken name) |
| `phonemes.yaml` | 40 | an English phoneme (audio-anchored: formants + articulation) |

**76 total entries, 264 composition links, 100% composition integrity,
all grounded to NSM primes.** Substrate scales from 355 keys (after
infant) to 431.

## The audio-anchor design

Each phoneme entry carries the data needed to **synthesize a real
sound** downstream:

- **Vowels** carry formant frequencies (F1, F2 in Hz). A simple
  audio engine can generate a recognizable spoken vowel from these.
- **Consonants** carry articulation features (manner: stop/fricative/
  nasal/lateral/approximant; place: bilabial/alveolar/velar/etc.;
  voiced: true/false). A klatt-style synthesizer can produce these.
- **Diphthongs** carry start and end formant pairs.
- **Affricates** decompose into their constituent phonemes (e.g.,
  `phoneme.ch = phoneme.t + phoneme.sh`).

The composition lattice gives the **abstract identity** of each
phoneme (its relation to other concepts); the `audio:` field on the
entity gives the **concrete signature** for synthesis.

## The sight + sound anchor thesis

The roadmap (per the design conversation): every primitive eventually
gets a **deterministic sight + sound signature** so the substrate is
grounded in *real perception*, not just labels.

- **Sight:** unique visual pattern per primitive (color, shape, glyph)
- **Sound:** unique tone per primitive (frequency, timbre)
- **Touch:** skipped — no easy computer modality

Composition chains become **playable as tone sequences** and
**renderable as visual patterns**. This is the next thread after
audio synthesis lands.

## Sequence as composition

Successive digits and letters chain through `binary.after`:

```
digit.0 → digit.1 → digit.2 → ... → digit.9
letter.a → letter.b → letter.c → ... → letter.z
```

This means asking the substrate "what comes after digit.5" is a
single-hop traversal that returns `digit.6`. The alphabet and the
counting sequence are queryable structures, not arbitrary metadata.

## Run it

```bash
PYTHONPATH=. python benchmark/curriculum/agi/symbols/teach.py
PYTHONPATH=. python benchmark/curriculum/agi/symbols/verify.py
```

## What this enables

This layer is the foundation for three generation experiments
(see `benchmark/curriculum/agi/generation/`):

1. **Counting and multi-digit numbers.** Compose digit symbols +
   place value rules to generate any integer. The substrate already
   knows the next-digit relation; the open work is the place-value
   composition rule.

2. **Phonetic spelling and reading.** Map letters to phonemes via
   spelling rules (the messy English part), then map phoneme
   sequences to synthesized audio.

3. **Word construction.** Phoneme sequences → syllables → words.
   The vocabulary layer (infant.word, infant.naming) already exists
   in stage 8 of the infant curriculum; here we have the atomic
   units those words are built from.

## Sources

- IPA chart for English phonemes (General American dialect)
- Standard formant frequencies from Peterson & Barney (1952) and
  later acoustic phonetics literature
- English orthography standard 26-letter alphabet
- Hindu-Arabic numeral system 0-9
