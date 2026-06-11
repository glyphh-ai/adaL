"""
The universal schema — every fact maps into one fixed shape.

Instead of growing ad-hoc predicates ("favorite_color", "has_dream_loop",
"quantity_of_bones") as an LLM invents them, every fact gets MAPPED into
a fixed 7-layer lattice. The substrate stays stable; structured queries
(count / distribution / intersection) address facts by layer.role slot.

LAYERS (fixed):
    entity        — what kind of thing is this
    perceptual    — color / size / shape / sound / texture / temperature
    spatial       — location / origin / direction
    temporal      — time / duration / age / era / frequency
    relational    — subject / predicate / object / possessor / agent
    quantitative  — count / magnitude / unit
    epistemic     — source / certainty / modality

Every fact fills SOME of these slots (the rest are absent). An absent
slot is a structural ∅ — the substrate refuses rather than confabulates.

``UniversalEnricher`` is the LLM-at-build-time extractor that maps free
text into the schema. It runs once per fact at write time and is cached;
the read path never calls an LLM.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)


# ── The universal schema ─────────────────────────────────────────────

UNIVERSAL_SCHEMA: dict[str, list[str]] = {
    "entity":       ["name", "kind", "subkind"],
    "perceptual":   ["color", "size", "shape", "texture", "sound",
                     "smell", "taste", "temperature"],
    "spatial":      ["location", "origin", "direction"],
    "temporal":     ["time", "duration", "age", "era", "frequency"],
    "relational":   ["subject", "predicate", "object", "possessor",
                     "agent", "patient", "instrument"],
    "quantitative": ["count", "magnitude", "unit", "ratio"],
    "epistemic":    ["source", "certainty", "modality"],
}

ALL_LAYERS = list(UNIVERSAL_SCHEMA)
ALL_ROLES = [(layer, role) for layer, roles in UNIVERSAL_SCHEMA.items() for role in roles]


# ── Enricher: LLM maps a fact INTO the fixed shape ──────────────────

_ENRICHER_SYSTEM = (
    "You are a structured-data extractor. Given a fact, fill in the "
    "values of this fixed universal schema. Use ONLY the roles listed. "
    "Leave a role's value blank/null if the fact doesn't mention it. "
    "Do not invent roles. Return strict JSON only.\n\n"
    "RULES:\n"
    "1. The entity layer describes exactly ONE entity: the primary "
    "subject the fact is about (usually the person/agent). It is a "
    "single JSON object, never a list. When a fact mentions a second "
    "entity (a pet, a possession, an employer), the second entity goes "
    "in relational.object — e.g. 'X owns a parrot' → entity.name=X, "
    "relational={subject: X, predicate: owns, object: parrot}. This "
    "holds regardless of sentence order: 'A parrot lives with X' is "
    "still about X owning a parrot.\n"
    "2. spatial.location = where the subject is or lives NOW. "
    "spatial.origin = where the subject is from, was born, or grew up. "
    "Never put a born-in/grew-up-in/from place in spatial.location.\n"
    "3. Values must be concrete terms from the fact. Never emit "
    "deictic or generic placeholders ('home', 'here', 'there', "
    "'this place') as a value — resolve to the concrete value or "
    "leave the role blank.\n"
    "4. Attribute values (age, color, height) describe the primary "
    "subject and go in their dedicated roles (temporal.age, "
    "perceptual.color, quantitative.magnitude + quantitative.unit).\n"
    "5. Stated preferences and favorites are attributes OF the subject, "
    "stored in the attribute's natural slot: 'X's favorite color is "
    "blue' → perceptual.color=blue and relational.predicate="
    "'favorite_color'. Do not move the preferred value into "
    "relational.object.\n"
    "6. Occupations and roles: 'X works as a Y' → relational="
    "{subject: X, predicate: works_as, object: Y}. entity.kind/subkind "
    "describe what kind of thing the subject IS (person, organization, "
    "place) — never an occupation, hobby, or possession.\n"
    "7. Fill a slot only with information the fact explicitly states "
    "about the primary subject. Incidental phrases ('at home', 'at "
    "work', 'these days', 'busier than ever') fill nothing.\n\n"
    "SCHEMA:\n" +
    "\n".join(f"  {layer}: {', '.join(roles)}"
              for layer, roles in UNIVERSAL_SCHEMA.items())
)


class UniversalEnricher:
    """One LLM call per fact, cached. Maps free text into the fixed schema.

    ``usage`` accumulates measured token counts across calls so build
    cost is reported from real API usage, never estimated.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        import anthropic
        self._client = anthropic.Anthropic()
        self._model = model
        self._cache: dict[str, dict] = {}
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def enrich(self, text: str) -> dict[str, dict[str, str]]:
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        prompt = (
            f"Fact: {text}\n\n"
            "Return a JSON object with this exact structure (omit unfilled layers):\n"
            "{\n"
            '  "entity": {"name": "...", "kind": "..."},\n'
            '  "perceptual": {"color": "...", "size": "..."},\n'
            '  "temporal": {"age": "..."},\n'
            "  ...\n"
            "}\n"
        )
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=400,
                system=_ENRICHER_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            self.usage["calls"] += 1
            self.usage["input_tokens"] += resp.usage.input_tokens
            self.usage["output_tokens"] += resp.usage.output_tokens
            raw = resp.content[0].text.strip()
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
            # Parse the FIRST JSON object — the model occasionally emits
            # trailing commentary or a second object.
            mapped, _ = json.JSONDecoder().raw_decode(raw)
        except Exception as e:
            logger.warning("Universal enrich failed for %r: %s", text[:40], e)
            mapped = {}
        self._cache[key] = mapped
        return mapped
