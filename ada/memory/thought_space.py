"""
ThoughtSpace — Ada's long-term memory.

A structured fact store built on the universal schema. Facts arrive either
as natural language (``absorb`` — an optional LLM enricher maps the text
into universal-schema slots) or pre-structured (``tell_raw`` — zero LLM in
the path). Every fact is addressable three ways:

  1. **Structured queries** — count / distribution / slot intersection over
     the universal-schema slots. Exact, O(N) scans. This is the substrate's
     core claim: compositional queries top-K retrieval cannot answer.
  2. **Versioned keys** — write under a ``key`` and the fact becomes v1,
     v2, … with the full chain queryable via ``history(key)``.
  3. **Lexical recall** — deterministic token/slot scoring for fuzzy
     lookup. No vectors, no embedding model; scoring is explainable.

Usage:
    from ada.memory.thought_space import ThoughtSpace

    space = ThoughtSpace()
    space.tell_raw(facts={"entity": {"name": "Chris", "kind": "person"},
                          "spatial": {"location": "Brooklyn"}},
                   key="chris.location")
    space.count_where("spatial", "location", "Brooklyn")   # → 1
    space.recall("where does chris live", top_k=3)
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Tokenization (shared by recall + slot matching) ──────────────────────

_STOPWORDS = frozenset({
    "a", "an", "the",
    "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "by", "for", "with", "from", "as",
    "this", "that", "these", "those", "it", "its",
    "what", "which", "who", "whom", "whose", "where", "when", "how",
    "do", "does", "did", "have", "has", "had",
})

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'_-]*")


def _normalize(token: str) -> str:
    """Cheap deterministic normalization: aurora's→aurora, uses→use,
    cameras→camera. Leaves -ss words (chess, glass) and short tokens alone."""
    if token.endswith("'s") or token.endswith("s'"):
        token = token[:-2]
    elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token.rstrip("'")


def _tokenize(text: str) -> list[str]:
    return [
        _normalize(t)
        for t in _TOKEN_RE.findall(text.lower())
        if t not in _STOPWORDS
    ]




def score_thought(stored: "StoredThought", q_tokens: set,
                  q_struct=None) -> tuple[float, dict]:
    """Deterministic lexical score of one stored thought against query
    tokens (+ optional structured triple). Shared by the in-memory and
    SQL stores so both modes rank identically."""
    t_tokens = set(_tokenize(stored.content))
    slot_tokens: set[str] = set()
    for roles in stored.universal.values():
        if not isinstance(roles, dict):
            continue
        for v in roles.values():
            slot_tokens.update(_tokenize(str(v)))
    all_tokens = t_tokens | slot_tokens

    matched: dict[str, float] = {}

    def _set_cosine(target: set) -> float:
        if not target:
            return 0.0
        return len(q_tokens & target) / ((len(q_tokens) * len(target)) ** 0.5)

    token_sim = max(_set_cosine(t_tokens), _set_cosine(all_tokens))
    if token_sim:
        matched["tokens"] = token_sim

    slot_hits = len(q_tokens & slot_tokens)
    slot_sim = slot_hits / len(q_tokens) if q_tokens else 0.0
    if slot_sim:
        matched["slots"] = slot_sim

    struct_bonus = 0.0
    s_struct = stored.metadata.get("_structured")
    if (
        q_struct is not None and s_struct is not None
        and getattr(q_struct, "is_structured", lambda: False)()
        and getattr(s_struct, "is_structured", lambda: False)()
    ):
        if q_struct.predicate and q_struct.predicate == s_struct.predicate:
            struct_bonus += 1.0
        if q_struct.subject and q_struct.subject == s_struct.subject:
            struct_bonus += 0.5
        if q_struct.topic and q_struct.topic == s_struct.topic:
            struct_bonus += 0.3
    if struct_bonus:
        matched["structured"] = struct_bonus

    return token_sim * 0.5 + slot_sim * 0.2 + struct_bonus * 0.5, matched


# ── Stored thought ────────────────────────────────────────────────────────

@dataclass
class StoredThought:
    """A fact in long-term memory: text + universal-schema slots + metadata.

    ``metadata`` carries the structured payload:
      _universal — {layer: {role: value}} universal-schema slot fill
      _structured — StructuredFact (subject/predicate/object/topic), when
                    an enricher parsed the text
      _key / _version / _parent_id — versioned-concept chain fields
    """
    thought_id: str
    content: str
    speaker: str
    space_id: str = "main"
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def universal(self) -> dict[str, dict[str, str]]:
        """The universal-schema slot fill ({} when the fact has none)."""
        return self.metadata.get("_universal") or {}

    @property
    def glyph(self) -> "StoredThought":
        """Back-compat: older callers read ``thought.glyph.metadata``.
        The vector glyph is gone; metadata lives on the thought itself."""
        return self


@dataclass
class RecallResult:
    """A recall result with its deterministic lexical score."""
    thought: StoredThought
    global_similarity: float
    matched: dict[str, float] = field(default_factory=dict)


# ── ThoughtSpace ──────────────────────────────────────────────────────────

class ThoughtSpace:
    """Ada's long-term memory — absorb, store, query, recall.

    Args:
        enricher: Optional LLM-at-build-time enricher. When present,
            ``absorb`` maps natural language into universal-schema slots
            (and a subject/predicate/object triple) at write time. The
            read path never calls an LLM.
    """

    def __init__(self, enricher: object | None = None,
                 space_id: str = "main", **_compat: Any) -> None:
        # **_compat swallows legacy constructor args (primitives=, encoder=,
        # with_foundation=) from the HDC era so old call sites don't crash.
        if _compat:
            logger.debug("ThoughtSpace ignoring legacy args: %s", sorted(_compat))
        self.space_id = space_id
        self._enricher = enricher
        self._thoughts: dict[str, StoredThought] = {}
        self._absorbed_texts: set[str] = set()  # dedup
        # key → version chain, chronological. Powers history().
        self._history_by_key: dict[str, list[StoredThought]] = {}
        # entity_profiles() cache — invalidated on every write.
        self._profiles_cache: dict[str, dict[str, set[str]]] | None = None

    @property
    def count(self) -> int:
        return len(self._thoughts)

    # ── Write surfaces ───────────────────────────────────────────────────

    def absorb(
        self,
        text: str,
        speaker: str = "incoming",
        metadata: dict[str, Any] | None = None,
        key: str | None = None,
        speaker_entity: str | None = None,
    ) -> StoredThought | None:
        """Store a natural-language fact.

        If an enricher is wired in, the text is mapped into universal-schema
        slots (one LLM call at write time, cached). Deduplicates by exact
        text. With ``key``, the fact becomes the next version of that key.

        Returns the StoredThought, or None if duplicate/empty.
        """
        text_key = text.strip().lower()
        if not text_key:
            return None
        if text_key in self._absorbed_texts:
            return None

        meta = (metadata or {}).copy()

        # LLM-at-build-time enrichment: universal slots + structured triple.
        if self._enricher is not None and "_universal" not in meta:
            try:
                universal = getattr(self._enricher, "universal", None)
                if callable(universal):
                    mapped = universal(text)
                    if mapped:
                        clean = _sanitize_universal(mapped)
                        if speaker_entity:
                            clean = _resolve_speaker_entity(text, clean, speaker_entity)
                        meta["_universal"] = clean
                meta["_structured"] = self._enricher.enrich(text)
            except Exception:
                logger.warning("enricher failed for %r", text[:50], exc_info=True)

        return self._store(text, speaker=speaker, meta=meta, key=key)

    def tell_raw(
        self,
        facts: dict[str, dict[str, str]],
        key: str | None = None,
        text: str | None = None,
        speaker: str = "incoming",
        metadata: dict[str, Any] | None = None,
    ) -> StoredThought | None:
        """Ingest a pre-structured universal-schema fact. NO LLM call.

        For programmatic teaching: curriculum loaders, API callers, batch
        importers. The caller provides well-formed universal-schema slots;
        roles outside the schema are silently dropped.

        Args:
            facts: {layer: {role: value}} — the universal-schema fill.
            key: Optional stable identifier for versioning (same as absorb).
            text: Optional human-readable text (for display / dedup).
            speaker: 'incoming' / 'outgoing' / 'schema' / 'curriculum'.
            metadata: Extra metadata to attach.

        Returns: the StoredThought, or None if duplicate / empty.
        """
        clean = _sanitize_universal(facts or {})
        if not clean:
            return None

        if text is None:
            text = self._synthesize_text(clean)
        text_key = text.strip().lower()
        if not text_key or text_key in self._absorbed_texts:
            return None

        meta = (metadata or {}).copy()
        meta["_universal"] = clean
        meta["_raw"] = True
        return self._store(text, speaker=speaker, meta=meta, key=key)

    def _store(
        self,
        text: str,
        speaker: str,
        meta: dict[str, Any],
        key: str | None,
    ) -> StoredThought:
        """Shared write path: versioning + id + index updates."""
        prev: StoredThought | None = None
        version = 1
        if key is not None:
            chain = self._history_by_key.get(key, [])
            if chain:
                prev = chain[-1]
                version = prev.metadata.get("_version", 1) + 1
            from datetime import datetime, timezone
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            thought_id = f"{key}@{stamp}#v{version}"
            meta["_key"] = key
            meta["_version"] = version
            meta["_parent_id"] = prev.thought_id if prev else None
        else:
            thought_id = str(uuid.uuid4())[:12]

        stored = StoredThought(
            thought_id=thought_id,
            content=text,
            speaker=speaker,
            space_id=self.space_id,
            metadata=meta,
        )
        self._thoughts[thought_id] = stored
        self._absorbed_texts.add(text.strip().lower())
        if key is not None:
            self._history_by_key.setdefault(key, []).append(stored)
        self._profiles_cache = None
        logger.debug("Stored %s: %s", thought_id, text[:50])
        return stored

    @staticmethod
    def _synthesize_text(facts: dict[str, dict[str, str]]) -> str:
        """Human-readable text from a universal-schema fact dict."""
        parts: list[str] = []
        name = facts.get("entity", {}).get("name")
        kind = facts.get("entity", {}).get("kind")
        if name:
            parts.append(name if not kind else f"{name} ({kind})")
        elif kind:
            parts.append(f"a {kind}")
        for layer, roles in facts.items():
            if layer == "entity":
                continue
            for role, value in roles.items():
                parts.append(f"{layer}.{role}={value}")
        return " :: ".join(parts) if parts else "(unnamed)"

    # ── Structured queries (the compositional surface) ──────────────────
    #
    # These are exact O(N) scans over the universal-schema slots — the
    # query shapes (aggregation, distribution, intersection, refusal)
    # that top-K retrieval structurally cannot answer. They answer over
    # CURRENT belief: superseded versions of a keyed fact are skipped
    # (the chain stays reachable via history()).

    def _is_current(self, thought: StoredThought) -> bool:
        """False only for superseded versions of a keyed fact."""
        key = thought.metadata.get("_key")
        if key is None:
            return True
        chain = self._history_by_key.get(key)
        return not chain or chain[-1].thought_id == thought.thought_id

    def _current_thoughts(self):
        return (t for t in self._thoughts.values() if self._is_current(t))

    def count_where(self, layer: str, role: str, value: str) -> int:
        """How many current facts fill layer.role with exactly this value?"""
        v = value.strip().lower()
        return sum(
            1 for t in self._current_thoughts()
            if (t.universal.get(layer) or {}).get(role, "").strip().lower() == v
        )

    def distribution(self, layer: str, role: str, top_k: int = 5) -> list[tuple[str, int]]:
        """Most-common values for layer.role across current facts."""
        c: Counter = Counter()
        for t in self._current_thoughts():
            v = (t.universal.get(layer) or {}).get(role)
            if v is not None:
                c[str(v).strip().lower()] += 1
        return c.most_common(top_k)

    def find_where(self, conditions: dict[str, str]) -> list[StoredThought]:
        """Current facts matching ALL conditions. Keys are 'layer.role' strings.

        find_where({"perceptual.color": "blue", "spatial.location": "Austin"})
        An empty result is a structural ∅ — refusal, not failure.
        """
        parsed = []
        for lr, value in conditions.items():
            layer, _, role = lr.partition(".")
            parsed.append((layer, role, str(value).strip().lower()))
        out = []
        for t in self._current_thoughts():
            u = t.universal
            if all(
                (u.get(layer) or {}).get(role, "").strip().lower() == v
                for layer, role, v in parsed
            ):
                out.append(t)
        return out

    def slot_values(self, layer: str, role: str) -> set[str]:
        """Every distinct value current facts hold for layer.role."""
        return {
            str(v).strip().lower()
            for t in self._current_thoughts()
            if (v := (t.universal.get(layer) or {}).get(role)) is not None
        }

    # ── Entity-level view ────────────────────────────────────────────
    #
    # A single entity's facts arrive as separate thoughts (one glyph per
    # fact). Cross-fact queries — "who lives in Austin AND works as an
    # engineer" — require joining those glyphs per entity. The entity
    # view groups current thoughts by normalized entity.name and unions
    # their slot fills (a slot filled by multiple facts keeps every
    # value, so "blue" matches whether one fact or three said it).

    def entity_profiles(self) -> dict[str, dict[str, set[str]]]:
        """entity name -> {'layer.role': {values}} over current facts.

        Built once and cached; every write invalidates. O(N) rebuild,
        O(1) reuse — at 1M facts the rebuild is the cost of the first
        entity query after a write, not of every query.
        """
        if self._profiles_cache is not None:
            return self._profiles_cache
        profiles: dict[str, dict[str, set[str]]] = {}
        for t in self._current_thoughts():
            u = t.universal
            name = (u.get("entity") or {}).get("name")
            if not name:
                continue
            prof = profiles.setdefault(str(name).strip().lower(), {})
            for layer, roles in u.items():
                for role, v in roles.items():
                    prof.setdefault(f"{layer}.{role}", set()).add(
                        str(v).strip().lower()
                    )
        self._profiles_cache = profiles
        return profiles

    def entities_where(self, conditions: dict) -> list[str]:
        """Entity names whose joined facts satisfy ALL conditions.

        A condition value may be a single value or a list — a list means
        the entity's slot must contain EVERY value (e.g. two
        relational.object facts: works as a teacher AND enjoys chess).

        entities_where({"spatial.location": "Austin",
                        "relational.object": ["engineer", "chess"]})
        Empty result is a structural ∅ over entities.
        """
        wanted: list[tuple[str, list[str]]] = []
        for lr, v in conditions.items():
            values = v if isinstance(v, (list, tuple, set)) else [v]
            wanted.append((lr, [str(x).strip().lower() for x in values]))

        def slot_matches(prof: dict, lr: str, values: list[str]) -> bool:
            have = prof.get(lr, set())
            if lr == "relational.predicate":
                # Predicates are verb phrases ('works_as', 'earns living
                # as'), not categorical values — match by containment.
                return all(any(v in h or h in v for h in have) for v in values)
            return set(values) <= have

        return [
            name for name, prof in self.entity_profiles().items()
            if all(slot_matches(prof, lr, values) for lr, values in wanted)
        ]

    def distribution_filtered(
        self, layer: str, role: str, top_k: int = 5,
        predicate_contains: str | None = None,
    ) -> list[tuple[str, int]]:
        """distribution(), optionally restricted to facts whose
        relational.predicate contains a substring — disambiguates
        shared slots ('relational.object' holds jobs, hobbies, pets)."""
        c: Counter = Counter()
        needle = (predicate_contains or "").strip().lower()
        for t in self._current_thoughts():
            u = t.universal
            v = (u.get(layer) or {}).get(role)
            if v is None:
                continue
            if needle:
                pred = str((u.get("relational") or {}).get("predicate", "")).lower()
                if needle not in pred:
                    continue
            c[str(v).strip().lower()] += 1
        return c.most_common(top_k)

    # ── Versioned-concept queries ────────────────────────────────────────

    def history(self, key: str) -> list[StoredThought]:
        """Chronological version chain for a stable key. Empty if none."""
        return list(self._history_by_key.get(key, []))

    def previous_value(self, person: str, slot: str) -> str | None:
        """The value this person's slot held BEFORE the latest change."""
        p = str(person).strip().lower()
        layer, _, role = slot.partition(".")
        for key, chain in self._history_by_key.items():
            if not key.startswith(p + ".") or len(chain) < 2:
                continue
            prev_v = (chain[-2].universal.get(layer) or {}).get(role)
            if prev_v is not None:
                return str(prev_v)
        return None

    # ── Lexical recall ───────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.05,
        speaker: str = "incoming",
        exclude_speakers: tuple = (),
    ) -> list[RecallResult]:
        """Deterministic lexical search over all stored facts.

        Three explainable signals, no vectors:
          1. token overlap — set cosine between query tokens and the
             thought's content + slot-value tokens (primary signal)
          2. slot hit — a query token exactly matches a filled slot value
          3. structured match — when both sides carry an enriched
             subject/predicate/object triple, matching predicate/subject
             dominates ("Alice's age" → predicate=age facts only)

        This is a placeholder fuzzy surface, not the headline capability —
        the structured queries above are. If the benchmark shows lexical
        recall is the bottleneck, local embeddings replace it (and must
        beat this baseline to earn the dependency).
        """
        if not self._thoughts:
            return []
        q_tokens = set(_tokenize(query))
        if not q_tokens:
            return []
        q_norm = query.strip().lower().rstrip("?.! ")

        q_struct = None
        if self._enricher is not None:
            try:
                q_struct = self._enricher.enrich(query)
            except Exception:
                q_struct = None

        results: list[RecallResult] = []
        for stored in self._thoughts.values():
            if stored.speaker in exclude_speakers:
                continue  # derived utterances don't ground answers
            if stored.content.strip().endswith("?"):
                continue  # questions are requests, not facts
            if stored.content.strip().lower().rstrip("?.! ") == q_norm:
                continue  # don't recall the question itself
            key = stored.metadata.get("_key")
            if key is not None:
                chain = self._history_by_key.get(key)
                if chain and chain[-1].thought_id != stored.thought_id:
                    continue  # superseded versions are history

            score, matched = score_thought(stored, q_tokens, q_struct)
            if score >= min_similarity:
                results.append(RecallResult(
                    thought=stored, global_similarity=score, matched=matched))

        results.sort(key=lambda r: r.global_similarity, reverse=True)
        for r in results[:top_k]:
            r.thought.last_accessed = time.time()
            r.thought.access_count += 1
        return results[:top_k]

    # ── Introspection / maintenance ──────────────────────────────────────

    def get_thought(self, thought_id: str) -> StoredThought | None:
        return self._thoughts.get(thought_id)

    def all_thoughts(self) -> list[StoredThought]:
        """All thoughts, newest first."""
        return sorted(self._thoughts.values(), key=lambda t: t.created_at, reverse=True)

    def clear(self) -> None:
        """Clear all thoughts (hard reset)."""
        self._thoughts.clear()
        self._absorbed_texts.clear()
        self._history_by_key.clear()
        self._profiles_cache = None

    def stats(self) -> dict:
        layer_fill: Counter = Counter()
        for t in self._thoughts.values():
            for layer in t.universal:
                layer_fill[layer] += 1
        return {
            "count": len(self._thoughts),
            "versioned_keys": len(self._history_by_key),
            "multi_version_keys": sum(
                1 for v in self._history_by_key.values() if len(v) > 1
            ),
            "layer_fill": dict(layer_fill),
        }

    def format_recall(self, results: list[RecallResult], max_results: int = 5) -> str:
        """Format recall results for injection into an LLM prompt."""
        if not results:
            return ""
        lines = []
        for r in results[:max_results]:
            t = r.thought
            who = "the user said" if t.speaker == "incoming" else "Ada said"
            lines.append(f"[{r.global_similarity:.2f}] {who}: \"{t.content}\"")
        return "Ada remembers:\n" + "\n".join(lines)


def _sanitize_universal(facts: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Keep only schema-valid layers/roles with non-empty values."""
    from ada.cognitive.universal import UNIVERSAL_SCHEMA

    clean: dict[str, dict[str, str]] = {}
    if not isinstance(facts, dict):
        return clean
    for layer, roles in facts.items():
        if layer not in UNIVERSAL_SCHEMA:
            continue
        if not isinstance(roles, dict):
            continue  # malformed layer (e.g. LLM emitted a list) — drop it
        kept = {}
        for role, value in (roles or {}).items():
            if role not in UNIVERSAL_SCHEMA[layer]:
                continue
            if value is None:
                continue
            v = str(value).strip()
            if not v or v.lower() in ("none", "null", "n/a"):
                continue
            kept[role] = v
        if kept:
            clean[layer] = kept
    return clean



_FIRST_PERSON = {"i", "me", "my", "mine", "myself", "i'm", "im"}


def _resolve_speaker_entity(text: str, clean: dict, speaker_entity: str
                            ) -> dict:
    """Rewrite first-person references to the known speaker entity.

    "i am married to brandi" (speaker=chris) → entity.name=chris.
    Only fires when the sentence actually uses a first-person token, so
    third-person facts are untouched. Deterministic; no LLM."""
    toks = set(_tokenize(text)) | {t for t in text.lower().split()}
    if not (_FIRST_PERSON & toks):
        return clean
    me = speaker_entity.strip().lower()
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in clean.items()}
    ent = out.get("entity")
    name = (ent or {}).get("name", "").strip().lower() if isinstance(ent, dict) else ""
    # If the extracted subject IS a first-person token (or absent), it's
    # the speaker.
    if name in _FIRST_PERSON or name in ("", "user", "me", "i"):
        out.setdefault("entity", {})["name"] = me
    rel = out.get("relational")
    if isinstance(rel, dict):
        for r in ("subject", "possessor", "agent"):
            if str(rel.get(r, "")).strip().lower() in _FIRST_PERSON:
                rel[r] = me
    return out


# Back-compat alias — the HDC-era name, used by curriculum/benchmark scripts.
ThoughtGlyphSpace = ThoughtSpace
