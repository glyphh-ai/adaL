# Chemistry — Ada grounded in a real subject

The chemistry thread tests the thesis from `learning/README.md` on a
**real, structured domain** with deep compositional layers. The
substrate is taught chemistry the way a curriculum text would teach
it: elements first, then how elements bond, then how bonds compose
into functional groups, then how groups compose into compounds, then
which empirical properties attach to those compounds.

Every fact arrives via `tell_raw` (no LLM at ingest). Every fact's
`composed_of:` field references either layer-0 NSM primes, layer-1
cognitive primitives (colors/numbers/spatial/etc.), or
chemistry-internal keys that themselves bottom out at primes.

## What's in here

| File | What | Count |
|---|---|---|
| `elements.yaml` | 20 elements (H, C, N, O, ..., Fe, Cu, Au) | 20 |
| `bonds.yaml` | covalent, ionic, hydrogen, metallic, double, triple | 6 |
| `groups.yaml` | hydroxyl, carbonyl, carboxyl, amino, methyl, phosphate, ester, ether, aldehyde, ketone | 10 |
| `compounds.yaml` | water, methane, ethanol, glucose, ATP, DNA, benzene, NaCl, sucrose, ... | 28 |
| `properties.yaml` | boiling points, pKa/pKb, solubility, key reactions | 20 |
| `teach.py` | loads layer-0 + layer-1 + chemistry into a substrate | — |
| `verify.py` | every fact resolves; every composition target exists | — |
| `hard_questions.py` | **the proof**: 10 substantively hard chemistry questions, answered by compositional traversal | — |

Total after `teach.py`: **590 thoughts** (206 grounded concepts +
384 composition edges).

## The proof — `hard_questions.py`

These are not retrieval questions. They are questions where the
*reasoning* is the answer, and a correct answer requires traversing
a chain of independently-taught facts.

1. **Trace H2O to its primes.** Returns the full composition tree, all
   the way down to `prime.something`, `prime.touch`, `prime.near`,
   etc. Auditable, deterministic, byte-identical across runs.

2. **Trace glucose.** Depth-4 chain through groups → bonds →
   elements → primes. 9 NSM primes reached.

3. **Enumerate everything that depends on `bond.hydrogen`.** 32
   chemistry concepts. *Closed set*, not "here are some examples."

4. **Why does water boil 261°C higher than methane (similar mass)?**
   Ada compares their composition chains: water reaches
   `bond.hydrogen`, methane does not. `property.water.bp` semantically
   cites `due-to-hydrogen-bonding`. The derivation cites every fact
   it used.

5. **Which compounds contain a hydroxyl group?** 10, by traversal.

6. **Which compounds contain BOTH carbon AND oxygen?** 14, by
   intersection over the lattice.

7. **What does benzene TASTE like?** *Refusal with provenance.*
   The substrate has `perceptual.color` and `perceptual.temperature`
   for benzene, but no `perceptual.taste` role is filled anywhere in
   benzene's composition chain. Ada cites the gap. An LLM would
   confabulate "sweet, aromatic" because the text co-occurs in
   training data.

8. **What chemistry concepts ground in `color.yellow`?** Cross-layer
   query from chemistry back into layer-1 cognitive primitives.

9. **Which functional groups can hydrogen-bond?** Predicate-level
   inference: groups whose composition includes H + electronegative
   donor (F/O/N). Returns 4: hydroxyl, carboxyl (explicit), amino,
   aldehyde (inferred from composition).

10. **Compare glucose vs ATP.** Set difference over composition
    chains. The single distinguishing fact: `group.phosphate` appears
    in ATP's chain, not glucose's. *That is why ATP is the cell's
    energy currency*, and Ada arrived at it by traversal, not by
    recalling a textbook sentence.

## Why this matters

Every one of these answers is **auditable down to layer-0 primes**.
You can ask Ada "why did you say compound.glucose has a hydroxyl
group?" and the answer is: "because `compound.glucose.composed_of`
contains `group.hydroxyl`, which I was independently taught from
`groups.yaml`." Push it further: "why does `group.hydroxyl` matter?"
→ because its `composed_of` reaches `element.oxygen` +
`element.hydrogen` + `bond.covalent` + `bond.hydrogen`. Push *that*
→ `bond.hydrogen` reaches `prime.near` + `prime.touch` +
`element.hydrogen` → `prime.something` + `prime.one`.

No LLM can produce this chain because no LLM has it. They have
*statistical correlations between strings*. Ada has the lattice.

## Run it

```bash
PYTHONPATH=. python benchmark/curriculum/agi/chemistry/teach.py
PYTHONPATH=. python benchmark/curriculum/agi/chemistry/verify.py
PYTHONPATH=. python benchmark/curriculum/agi/chemistry/hard_questions.py
```

## What this is NOT

This is 84 chemistry entries — not a chemistry textbook. The point
is to show the *substrate operations* a curriculum-built cognitive
system supports, at a corpus small enough to inspect by hand. At
the scale projected in `learning/README.md` (~50K entries at layer
6, ~50M at layer 8), the same operations work, the same audit
chains hold, and Ada becomes a different category of system —
not "an LLM with grounding," but a substrate where every concept is
traceable and every "I don't know" is structural.
