# Ada Memory Recall & Reinforcement Spec

## Problem

Ada's memory system has the primitives (strength, decay, reinforce, recency timestamps) but none of them are wired into the recall scoring or lifecycle. Memories are recalled by pure similarity — a memory from 10 seconds ago and one from 10 hours ago score identically. Nothing gets stronger from use. Nothing fades from neglect. And everything is lost on restart.

## Current State

### What exists (thought_space.py)
- `StoredThought.strength` — float, starts at 1.0, caps at 3.0
- `StoredThought.reinforce(amount)` — Hebbian: `strength += amount / (1 + 0.1 * strength)` (diminishing returns)
- `StoredThought.decay(factor)` — multiplicative: `strength *= 0.95`
- `StoredThought.created_at` — unix timestamp
- 3-signal recall: content cosine (50%) + layer cosine (35%) + structural Jaccard (15%)
- Adaptive content/structure weighting based on query word count
- Dream loop (glyph_dream.py) — dual REM + Slow-Wave background reasoning

### What's NOT wired
- Strength is never factored into recall scoring
- Reinforce is never called on successful recall
- Decay is never called by the dream loop or any lifecycle
- Recency (created_at) is never used in scoring
- No persistence — all in-memory, lost on restart

## Proposed Algorithm

### Recall Scoring

```
final_score = similarity × strength_boost × recency_boost

where:
  similarity    = existing 3-signal score (content + layers + structure)
  strength_boost = 1.0 + log(1 + strength)     # range: 1.0 to ~2.4 at max strength
  recency_boost  = α + (1 - α) × exp(-λ × age) # range: α to 1.0
```

Parameters:
- `α = 0.3` — floor: even old memories retain 30% of their recency boost (they don't disappear, they just lose urgency)
- `λ = 0.05` — decay rate per hour: ~61% at 10h, ~37% at 20h, 30% (floor) after ~48h

This means:
- A memory recalled 5 minutes ago: recency ≈ 1.0
- A memory from 10 hours ago: recency ≈ 0.51
- A memory from 2 days ago: recency ≈ 0.30 (floor)
- A memory recalled 100 times (strength 3.0): strength_boost ≈ 2.4×
- A fresh memory never reinforced (strength 1.0): strength_boost ≈ 1.7×

### Hebbian Reinforcement

On every successful recall (thought appears in top-k results AND the think pipeline uses it):

```python
thought.reinforce(amount=0.1)
# strength += 0.1 / (1 + 0.1 * strength)
# Diminishing returns — getting from 1.0 to 2.0 is easy, 2.0 to 3.0 is hard
```

This creates a positive feedback loop: useful memories get recalled more → get reinforced → score higher → get recalled more. The diminishing returns cap prevents runaway dominance.

### Decay (Dream Loop Integration)

During the dream loop's **Slow-Wave (deep) cycle**:

```python
for thought in all_thoughts:
    hours_since_last_access = (now - thought.last_accessed) / 3600
    if hours_since_last_access > 1.0:
        thought.decay(factor=0.98)  # gentle: 2% per deep cycle (~30s)
    if thought.strength < 0.05:
        archive(thought)  # move to cold storage, not deleted
```

This means:
- Actively used memories stay strong (reinforcement > decay)
- Idle memories slowly weaken over hours
- Nothing is deleted — archived memories can be restored by the dream loop if a pattern re-emerges
- The dream loop IS the garbage collector — during Slow-Wave it prunes, during REM it reinforces

### Reinforcement Signal Flow

```
User query
  → recall() returns top-k memories
    → think pipeline uses them (or doesn't)
      → if used: reinforce(0.1) — memory gets stronger
      → if not used: no change (decay handles weakening later)
        → dream loop Slow-Wave: decay unused memories
          → dream loop REM: reinforce memories that appear in reasoning chains
```

This is the biological gradient:
- **Forward pass**: query → recall → use
- **Backward signal**: use → reinforce (Hebbian)
- **Background maintenance**: dream → decay/prune (homeostatic)

### Last-Accessed Tracking

Add `last_accessed: float` to StoredThought. Updated on:
- Recall (appears in results): `last_accessed = now`
- Reinforcement: `last_accessed = now`
- Dream loop wander (thought is part of a chain): `last_accessed = now`

This separates "when was it created" from "when was it last useful" — a memory from a week ago that's recalled every day should not decay.

## Persistence

### Schema (SQLite)

```sql
CREATE TABLE ada_thoughts (
    thought_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    speaker TEXT NOT NULL,
    glyph_data BLOB NOT NULL,        -- serialized Glyph (layers + cortex)
    content_vector TEXT,              -- JSON array for content similarity
    strength REAL DEFAULT 1.0,
    created_at REAL NOT NULL,
    last_accessed REAL NOT NULL,
    metadata TEXT,                    -- JSON
    archived INTEGER DEFAULT 0       -- 1 = cold storage
);

CREATE INDEX idx_thoughts_strength ON ada_thoughts(strength DESC);
CREATE INDEX idx_thoughts_accessed ON ada_thoughts(last_accessed DESC);
```

### Lifecycle
- **Boot**: load all non-archived thoughts from SQLite into memory
- **Absorb**: write to memory + SQLite
- **Recall**: read from memory (fast), update last_accessed in SQLite async
- **Reinforce**: update strength in memory + SQLite async
- **Dream decay**: update strength in memory + SQLite async
- **Archive**: set archived=1 in SQLite, remove from memory dict
- **Shutdown**: flush any pending strength/accessed updates

### Cold → Hot Restoration

When the dream loop discovers a pattern involving an archived thought:
1. Load it back from SQLite
2. Set strength to 0.5 (partial restoration)
3. If it gets recalled and reinforced, it stays
4. If not, it decays back to archive threshold

## Dream Loop Wiring

### REM (Localized, ~3s) — already exists
Add: when a thought appears in a reasoning chain, call `thought.reinforce(0.05)` (smaller than direct recall reinforcement).

### Slow-Wave (Deep, ~30s) — already exists  
Add:
1. **Decay pass**: iterate all thoughts, decay if `hours_since_last_access > 1.0`
2. **Archive pass**: move thoughts with `strength < 0.05` to cold storage
3. **Pattern mining**: check observations for clusters (existing growth.py)
4. **Restoration check**: if a pattern references an archived thought, restore it

## Implementation Order

1. **Wire strength into recall scoring** — `thought_space.py` recall() method
2. **Add recency boost** — exponential decay based on age
3. **Call reinforce on successful recall** — `think.py` after using facts
4. **Wire decay into dream loop** — `glyph_dream.py` Slow-Wave phase
5. **Add last_accessed tracking** — StoredThought + recall/reinforce updates
6. **Add SQLite persistence** — new table, boot/absorb/shutdown lifecycle
7. **Add archival** — cold storage threshold, dream loop restoration

## Parameters (Tunable)

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `recency_floor` | 0.3 | Old memories keep 30% recency weight |
| `recency_lambda` | 0.05 | Per-hour decay rate |
| `reinforce_amount` | 0.1 | Hebbian boost on recall |
| `reinforce_dream` | 0.05 | Hebbian boost from dream chains |
| `decay_factor` | 0.98 | Per Slow-Wave cycle decay |
| `archive_threshold` | 0.05 | Below this → cold storage |
| `strength_cap` | 3.0 | Maximum strength (existing) |
| `strength_init` | 1.0 | Starting strength (existing) |
