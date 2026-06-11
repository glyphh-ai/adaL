"""
Phase 2 systems — four memory architectures behind one NL interface.

Fairness rules (PROTOCOL.md §3):
  - Same NL sentences in. Ada, EAV, and Graph share ONE extraction pass
    (the same UniversalEnricher output), so ingestion quality is held
    constant and the comparison isolates the QUERY architecture.
    (Protocol amendment §7-1: the graph derives from the shared
    extraction instead of its own LLM extraction pass.) RAG embeds the
    raw sentences — that is its architecture.
  - Same translator/renderer LLM, same max_tokens, ONE retry with the
    error message fed back.
  - Every translator may refuse. Refusing is honest; answering wrong is
    hallucination and is tracked.
  - Person identity comes from the EXTRACTION (entity.name /
    relational.subject), never from ground truth.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

ADA_MODEL = os.environ.get("ADA_MODEL", "claude-haiku-4-5-20251001")

# Slot documentation shared with every structured system's translator —
# this is schema documentation, identical across systems.
SLOT_DOC = """\
Facts about people fill these slots:
  temporal.age            — age in years
  spatial.location        — city the person lives in NOW
  spatial.origin          — city the person is from / grew up in
  perceptual.color        — the person's favorite color
  quantitative.magnitude  — height in centimeters
  relational.object       — job, hobby, or pet (with relational.subject
                            = the person, relational.predicate = the verb)
Values are lowercase single terms. Nothing else about people (salary,
cars, education, ...) is stored."""


class LLM:
    """Shared translator/renderer wrapper with measured usage."""

    def __init__(self):
        import anthropic
        self._client = anthropic.Anthropic()
        self._lock = threading.Lock()
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def ask(self, system: str, user: str, max_tokens: int = 300) -> str:
        resp = self._client.messages.create(
            model=ADA_MODEL, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
        )
        with self._lock:
            self.usage["calls"] += 1
            self.usage["input_tokens"] += resp.usage.input_tokens
            self.usage["output_tokens"] += resp.usage.output_tokens
        return resp.content[0].text.strip()


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _strip_fences(raw: str) -> str:
    return re.sub(r"^```[a-z]*\s*|\s*```$", "", raw.strip()).strip()


def _person_of(extraction: dict) -> str | None:
    """Person attribution from the extraction only."""
    if not isinstance(extraction, dict):
        return None
    ent = extraction.get("entity")
    if isinstance(ent, dict) and ent.get("name"):
        return _norm(ent["name"])
    rel = extraction.get("relational")
    if isinstance(rel, dict):
        for r in ("subject", "possessor", "agent"):
            if rel.get(r):
                return _norm(rel[r])
    return None


# ═══════════════════════════════════════════════════════════════════
# Ada — universal-schema substrate + op translator
# ═══════════════════════════════════════════════════════════════════

_ADA_TRANSLATOR = f"""You translate a natural-language question into ONE
query operation for a structured fact store. {SLOT_DOC}

Operations (output strict JSON, nothing else):
  {{"op":"lookup","person":"<name>","slot":"layer.role"}}
  {{"op":"prev","person":"<name>","slot":"layer.role"}}        — the value BEFORE the latest change
  {{"op":"count","conditions":{{"layer.role":"value", ...}}}}    — how many people match ALL conditions
  {{"op":"count_not","slot":"layer.role","value":"v"}}          — people whose slot value is NOT v
  {{"op":"top","slot":"layer.role","k":5,"predicate_contains":"work"}}
       — most common values; the optional predicate filter restricts a
         shared slot (relational.object holds jobs AND hobbies AND pets)
         to facts whose verb matches: jobs→"work", hobbies→"enjoy", pets→"pet"
  {{"op":"who","conditions":{{"layer.role":"value", ...}}}}      — names of people matching ALL conditions
  {{"op":"compare","slot":"layer.role","a":"v1","b":"v2"}}      — which value is more common
  {{"op":"refuse"}}                                             — the question asks for information not in the schema

When two required values live in the SAME slot (e.g. a job and a hobby
are both relational.object), pass a list: {{"relational.object":
["teacher","chess"]}} — the person must have ALL of them.
Values in conditions must be lowercase."""


class AdaSystem:
    name = "ada"

    def __init__(self, llm: LLM):
        from ada.memory.thought_space import ThoughtSpace
        self.llm = llm
        self.space = ThoughtSpace()
        self.ingest_errors = 0

    def ingest(self, facts, keys, extractions) -> None:
        for fact, key, mapped in zip(facts, keys, extractions):
            stored = self.space.tell_raw(facts=mapped, text=fact.sentence,
                                         key=key, speaker="phase2")
            if stored is None:
                self.ingest_errors += 1

    # ── op executor ──────────────────────────────────────────────────

    def _execute(self, op: dict) -> str:
        kind = op.get("op")
        if kind == "refuse":
            return "I don't know."
        if kind == "lookup":
            return self._lookup(op["person"], op["slot"])
        if kind == "prev":
            return self._prev(op["person"], op["slot"])
        if kind == "count":
            return str(len(self.space.entities_where(op["conditions"])))
        if kind == "count_not":
            profs = self.space.entity_profiles()
            slot, v = op["slot"], _norm(op["value"])
            n = sum(1 for prof in profs.values()
                    if prof.get(slot) and v not in prof[slot])
            return str(n)
        if kind == "top":
            layer, _, role = op["slot"].partition(".")
            dist = self.space.distribution_filtered(
                layer, role, int(op.get("k", 5)),
                predicate_contains=op.get("predicate_contains"))
            if not dist:
                return "none"
            return ", ".join(v for v, _ in dist)
        if kind == "who":
            names = self.space.entities_where(op["conditions"])
            return ", ".join(sorted(names)) if names else "none"
        if kind == "compare":
            layer, _, role = op["slot"].partition(".")
            ca = self.space.count_where(layer, role, op["a"])
            cb = self.space.count_where(layer, role, op["b"])
            if ca == cb:
                return "equal"
            return op["a"] if ca > cb else op["b"]
        raise ValueError(f"unknown op {kind!r}")

    def _profile_for(self, person: str) -> dict | None:
        profs = self.space.entity_profiles()
        p = _norm(person)
        if p in profs:
            return profs[p]
        for name, prof in profs.items():
            if p in name or name in p:
                return prof
        return None

    def _lookup(self, person: str, slot: str) -> str:
        prof = self._profile_for(person)
        if not prof or slot not in prof:
            return "I don't know."
        return ", ".join(sorted(prof[slot]))

    def _prev(self, person: str, slot: str) -> str:
        p = _norm(person)
        for key, chain in self.space._history_by_key.items():
            if not key.startswith(p + ".") or len(chain) < 2:
                continue
            layer, _, role = slot.partition(".")
            prev_v = (chain[-2].universal.get(layer) or {}).get(role)
            if prev_v is not None:
                return str(prev_v)
        return "I don't know."

    def answer(self, question: str) -> str:
        raw = self.llm.ask(_ADA_TRANSLATOR, f"Question: {question}", 200)
        for attempt in (1, 2):
            try:
                return self._execute(json.loads(_strip_fences(raw)))
            except Exception as e:
                if attempt == 2:
                    return "I don't know."
                raw = self.llm.ask(
                    _ADA_TRANSLATOR,
                    f"Question: {question}\nYour previous output failed "
                    f"({e}). Output corrected JSON only.", 200)
        return "I don't know."


# ═══════════════════════════════════════════════════════════════════
# EAV + text-to-SQL
# ═══════════════════════════════════════════════════════════════════

_EAV_TRANSLATOR = f"""You translate a natural-language question into ONE
SQLite SELECT statement. {SLOT_DOC}

Table:
  CREATE TABLE facts (
    person TEXT,      -- lowercase person name
    layer TEXT, role TEXT, value TEXT,   -- e.g. layer='spatial', role='location'
    key TEXT, version INTEGER,
    is_current INTEGER  -- 1 for current belief; older versions have 0
  );

Use is_current=1 unless the question asks about a PREVIOUS value (then
take the row with the highest version among is_current=0 for that
person+slot). Counting people = COUNT(DISTINCT person). Rows from the
same source fact share `key`; relational facts also carry a verb row
(role='predicate') — join on key to tell jobs (predicate LIKE '%work%')
from hobbies ('%enjoy%') and pets ('%pet%'), which all fill
role='object'. Values are lowercase. Output ONLY the SQL, no
commentary. If the question asks for information not in the schema,
output exactly: REFUSE"""


# LLM-generated queries can be pathological (e.g. an unconstrained
# self-join over 4M rows is a multi-trillion-row cartesian product).
# Production systems running model-generated queries need a hard query
# timeout; exceeding it is an honest failure ("I don't know").
ENGINE_TIMEOUT_S = 15.0


class EAVSystem:
    name = "eav_sql"

    def __init__(self, llm: LLM):
        self.llm = llm
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db_lock = threading.Lock()
        self._deadline = float("inf")
        # Abort any statement still running past the deadline (armed
        # only around answer-time queries; ingest runs unarmed).
        self.db.set_progress_handler(
            lambda: 1 if time.time() > self._deadline else 0, 100_000)
        self.db.execute(
            "CREATE TABLE facts (person TEXT, layer TEXT, role TEXT, "
            "value TEXT, key TEXT, version INTEGER, is_current INTEGER)")
        self.ingest_errors = 0

    def ingest(self, facts, keys, extractions) -> None:
        # Batched loading — row-at-a-time INSERTs took 87 minutes at 1M
        # facts, which misrepresents how anyone would actually load an
        # EAV table. Rows are accumulated, superseded versions are
        # resolved in memory, then executemany() writes once.
        latest: dict[str, int] = {}
        staged: list[tuple] = []  # (person, layer, role, value, key, version)
        for fact, key, mapped in zip(facts, keys, extractions):
            person = _person_of(mapped)
            if not person or not isinstance(mapped, dict):
                self.ingest_errors += 1
                continue
            version = latest.get(key, 0) + 1
            latest[key] = version
            for layer, roles in mapped.items():
                if not isinstance(roles, dict):
                    continue
                for role, v in roles.items():
                    if v is None or not str(v).strip():
                        continue
                    staged.append((person, layer, role, _norm(v), key, version))
        # is_current is known before inserting: final version per key.
        rows = [(p, l, r, v, k, ver, 1 if ver == latest[k] else 0)
                for p, l, r, v, k, ver in staged]
        with self._db_lock:
            self.db.executemany(
                "INSERT INTO facts VALUES (?,?,?,?,?,?,?)", rows)
            self.db.execute(
                "CREATE INDEX idx_facts_lrv ON facts(layer, role, value)")
            self.db.execute("CREATE INDEX idx_facts_person ON facts(person)")
            self.db.commit()

    def answer(self, question: str) -> str:
        raw = self.llm.ask(_EAV_TRANSLATOR, f"Question: {question}", 300)
        for attempt in (1, 2):
            sql = _strip_fences(raw)
            if sql.upper().startswith("REFUSE"):
                return "I don't know."
            if not re.match(r"^\s*SELECT\b", sql, re.I):
                err = "not a SELECT"
            else:
                try:
                    with self._db_lock:
                        self._deadline = time.time() + ENGINE_TIMEOUT_S
                        try:
                            rows = self.db.execute(sql).fetchall()
                        finally:
                            self._deadline = float("inf")
                    return self._format(rows)
                except Exception as e:
                    err = str(e)
            if attempt == 2:
                return "I don't know."
            raw = self.llm.ask(
                _EAV_TRANSLATOR,
                f"Question: {question}\nYour SQL failed ({err}):\n{sql}\n"
                f"Output corrected SQL only.", 300)
        return "I don't know."

    @staticmethod
    def _format(rows: list) -> str:
        if not rows:
            return "none"
        flat = [str(c) for r in rows for c in r if c is not None]
        return ", ".join(flat[:30]) if flat else "none"


# ═══════════════════════════════════════════════════════════════════
# Embedding RAG (local MiniLM + renderer)
# ═══════════════════════════════════════════════════════════════════

_RAG_RENDERER = """You answer questions using ONLY the provided notes.
Be concise: a single value, a number, or a comma-separated list — no
explanation. If the notes do not contain the answer, say exactly:
I don't know."""


class RAGSystem:
    name = "rag_minilm"

    def __init__(self, llm: LLM, top_k: int = 8):
        from sentence_transformers import SentenceTransformer
        self.llm = llm
        self.top_k = top_k
        self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        self.sentences: list[str] = []
        self.embeddings = None
        self.ingest_errors = 0

    def ingest(self, facts, keys, extractions) -> None:
        # RAG ingests the raw sentences — every one, including superseded
        # statements; it has no versioning concept (that is the point).
        self.sentences = [f.sentence for f in facts]
        self.embeddings = self.model.encode(
            self.sentences, normalize_embeddings=True, show_progress_bar=False)

    def answer(self, question: str) -> str:
        q = self.model.encode([question], normalize_embeddings=True)[0]
        sims = self.embeddings @ q
        top = sims.argsort()[::-1][: self.top_k]
        notes = "\n".join(f"- {self.sentences[i]}" for i in top)
        return self.llm.ask(_RAG_RENDERER,
                            f"Notes:\n{notes}\n\nQuestion: {question}", 200)


# ═══════════════════════════════════════════════════════════════════
# Kùzu graph + text-to-Cypher
# ═══════════════════════════════════════════════════════════════════

_GRAPH_DDL = """\
CREATE NODE TABLE Person (name STRING PRIMARY KEY, age INT64, height INT64);
CREATE NODE TABLE City  (name STRING PRIMARY KEY);
CREATE NODE TABLE Job   (name STRING PRIMARY KEY);
CREATE NODE TABLE Hobby (name STRING PRIMARY KEY);
CREATE NODE TABLE Pet   (name STRING PRIMARY KEY);
CREATE NODE TABLE Color (name STRING PRIMARY KEY);
CREATE REL TABLE LIVES_IN   (FROM Person TO City, current BOOLEAN);
CREATE REL TABLE ORIGIN_FROM(FROM Person TO City);
CREATE REL TABLE WORKS_AS   (FROM Person TO Job);
CREATE REL TABLE ENJOYS     (FROM Person TO Hobby);
CREATE REL TABLE HAS_PET    (FROM Person TO Pet);
CREATE REL TABLE LIKES_COLOR(FROM Person TO Color);"""

_GRAPH_TRANSLATOR = f"""You translate a natural-language question into ONE
Kùzu Cypher query. Schema:

{_GRAPH_DDL}

Names and values are lowercase. LIVES_IN edges: current=true is where
the person lives NOW; current=false is a previous home. Counting people
= COUNT(DISTINCT p.name). Output ONLY the Cypher, no commentary. If the
question asks for information not in the schema, output exactly: REFUSE"""

# Mapping extraction predicates -> relationship (the per-domain schema
# design a graph requires; misses are counted as ingest errors).
_PRED_TO_REL = [
    (re.compile(r"work|job|profession|occupat|employ|earn"), "WORKS_AS", "Job"),
    (re.compile(r"enjoy|hobby|like.*doing|into|spend|play"), "ENJOYS", "Hobby"),
    (re.compile(r"pet|own|care|live[sd]?.with|keep"), "HAS_PET", "Pet"),
    (re.compile(r"favorite_?color|prefer|like"), "LIKES_COLOR", "Color"),
]


class GraphSystem:
    name = "kuzu_cypher"

    def __init__(self, llm: LLM, workdir: str):
        import kuzu
        self.llm = llm
        self._db = kuzu.Database(workdir)
        self.conn = kuzu.Connection(self._db)
        # Same runaway-query protection as the SQL engine.
        if hasattr(self.conn, "set_query_timeout"):
            self.conn.set_query_timeout(int(ENGINE_TIMEOUT_S * 1000))
        self._cypher_lock = threading.Lock()
        for stmt in _GRAPH_DDL.strip().splitlines():
            self.conn.execute(stmt)
        self.ingest_errors = 0
        self._nodes: dict[str, set[str]] = {t: set() for t in
                                            ("Person", "City", "Job", "Hobby",
                                             "Pet", "Color")}

    def _ensure(self, table: str, name: str) -> None:
        if name not in self._nodes[table]:
            self.conn.execute(
                f"MERGE (n:{table} {{name: $name}})", {"name": name})
            self._nodes[table].add(name)

    def ingest(self, facts, keys, extractions) -> None:
        seen_loc: dict[str, int] = {}
        for fact, key, mapped in zip(facts, keys, extractions):
            person = _person_of(mapped)
            if not person or not isinstance(mapped, dict):
                self.ingest_errors += 1
                continue
            self._ensure("Person", person)
            ok = False
            for layer, roles in mapped.items():
                if not isinstance(roles, dict):
                    continue
                for role, v in roles.items():
                    if v is None or not str(v).strip():
                        continue
                    ok = self._ingest_slot(person, layer, role, _norm(v),
                                           mapped, key, seen_loc) or ok
            if not ok:
                self.ingest_errors += 1

    def _ingest_slot(self, person, layer, role, v, mapped, key, seen_loc) -> bool:
        if layer == "temporal" and role == "age" and v.isdigit():
            self.conn.execute(
                "MATCH (p:Person {name: $p}) SET p.age = $v",
                {"p": person, "v": int(v)})
            return True
        if layer == "quantitative" and role == "magnitude" and v.isdigit():
            self.conn.execute(
                "MATCH (p:Person {name: $p}) SET p.height = $v",
                {"p": person, "v": int(v)})
            return True
        if layer == "spatial" and role == "location":
            self._ensure("City", v)
            if seen_loc.get(key):
                self.conn.execute(
                    "MATCH (p:Person {name: $p})-[r:LIVES_IN]->(:City) "
                    "SET r.current = false", {"p": person})
            seen_loc[key] = seen_loc.get(key, 0) + 1
            self.conn.execute(
                "MATCH (p:Person {name: $p}), (c:City {name: $c}) "
                "CREATE (p)-[:LIVES_IN {current: true}]->(c)",
                {"p": person, "c": v})
            return True
        if layer == "spatial" and role == "origin":
            self._ensure("City", v)
            self.conn.execute(
                "MATCH (p:Person {name: $p}), (c:City {name: $c}) "
                "CREATE (p)-[:ORIGIN_FROM]->(c)", {"p": person, "c": v})
            return True
        if layer == "perceptual" and role == "color":
            self._ensure("Color", v)
            self.conn.execute(
                "MATCH (p:Person {name: $p}), (c:Color {name: $c}) "
                "CREATE (p)-[:LIKES_COLOR]->(c)", {"p": person, "c": v})
            return True
        if layer == "relational" and role == "object":
            pred = _norm((mapped.get("relational") or {}).get("predicate") or "")
            for rx, rel, table in _PRED_TO_REL:
                if rx.search(pred):
                    self._ensure(table, v)
                    self.conn.execute(
                        f"MATCH (p:Person {{name: $p}}), (t:{table} {{name: $t}}) "
                        f"CREATE (p)-[:{rel}]->(t)", {"p": person, "t": v})
                    return True
            return False  # unmappable predicate — schema-design miss
        return False

    def ingest_bulk(self, facts, keys, extractions, workdir: str) -> None:
        """Bulk ingestion via CSV COPY — per-row CREATE is hours at 1M
        facts; COPY is how a graph DB would actually be loaded."""
        import csv
        from collections import defaultdict
        from pathlib import Path

        persons: set[str] = set()
        values: dict[str, set[str]] = defaultdict(set)
        rels: dict[str, list] = defaultdict(list)
        loc_chain: dict[str, list] = defaultdict(list)

        for fact, key, mapped in zip(facts, keys, extractions):
            person = _person_of(mapped)
            if not person or not isinstance(mapped, dict):
                self.ingest_errors += 1
                continue
            persons.add(person)
            ok = False
            for layer, roles in mapped.items():
                if not isinstance(roles, dict):
                    continue
                for role, v in roles.items():
                    if v is None or not str(v).strip():
                        continue
                    v = _norm(v)
                    if layer == "temporal" and role == "age" and v.isdigit():
                        rels["_age"].append((person, int(v))); ok = True
                    elif (layer == "quantitative" and role == "magnitude"
                          and v.isdigit()):
                        rels["_height"].append((person, int(v))); ok = True
                    elif layer == "spatial" and role == "location":
                        values["City"].add(v)
                        loc_chain[key].append((person, v)); ok = True
                    elif layer == "spatial" and role == "origin":
                        values["City"].add(v)
                        rels["ORIGIN_FROM"].append((person, v)); ok = True
                    elif layer == "perceptual" and role == "color":
                        values["Color"].add(v)
                        rels["LIKES_COLOR"].append((person, v)); ok = True
                    elif layer == "relational" and role == "object":
                        pred = _norm((mapped.get("relational") or {})
                                     .get("predicate") or "")
                        for rx, rel, table in _PRED_TO_REL:
                            if rx.search(pred):
                                values[table].add(v)
                                rels[rel].append((person, v)); ok = True
                                break
            if not ok:
                self.ingest_errors += 1

        # LIVES_IN with current flag from version order.
        lives = []
        for chain in loc_chain.values():
            for i, (person, city) in enumerate(chain):
                lives.append((person, city, i == len(chain) - 1))

        wd = Path(workdir)
        ages = dict(rels.pop("_age", []))
        heights = dict(rels.pop("_height", []))
        with open(wd / "person.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            for p in sorted(persons):
                w.writerow([p, ages.get(p, ""), heights.get(p, "")])
        self.conn.execute(f"COPY Person FROM '{wd}/person.csv' (header=false)")
        rel_table = {"ORIGIN_FROM": "City", "WORKS_AS": "Job",
                     "ENJOYS": "Hobby", "HAS_PET": "Pet",
                     "LIKES_COLOR": "Color"}
        for table, vals in values.items():
            path = wd / f"{table}.csv"
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                for v in sorted(vals):
                    w.writerow([v])
            self.conn.execute(f"COPY {table} FROM '{path}' (header=false)")
        with open(wd / "lives_in.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            for person, city, cur in lives:
                w.writerow([person, city, str(cur).lower()])
        self.conn.execute(f"COPY LIVES_IN FROM '{wd}/lives_in.csv' (header=false)")
        for rel, pairs in rels.items():
            path = wd / f"{rel.lower()}.csv"
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh)
                seen = set()
                for pair in pairs:
                    if pair not in seen:
                        seen.add(pair)
                        w.writerow(list(pair))
            self.conn.execute(f"COPY {rel} FROM '{path}' (header=false)")

    def answer(self, question: str) -> str:
        raw = self.llm.ask(_GRAPH_TRANSLATOR, f"Question: {question}", 300)
        for attempt in (1, 2):
            cypher = _strip_fences(raw)
            if cypher.upper().startswith("REFUSE"):
                return "I don't know."
            try:
                with self._cypher_lock:
                    result = self.conn.execute(cypher)
                    rows = []
                    while result.has_next():
                        rows.append(result.get_next())
                return EAVSystem._format(rows)
            except Exception as e:
                if attempt == 2:
                    return "I don't know."
                raw = self.llm.ask(
                    _GRAPH_TRANSLATOR,
                    f"Question: {question}\nYour Cypher failed ({e}):\n"
                    f"{cypher}\nOutput corrected Cypher only.", 300)
        return "I don't know."


def timed_answer(system, question: str) -> tuple[str, float]:
    t0 = time.time()
    try:
        ans = system.answer(question)
    except Exception:
        ans = "I don't know."
    return ans, (time.time() - t0) * 1000
