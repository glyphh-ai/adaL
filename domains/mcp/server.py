"""
MCP Server — Ada's substrate exposed as deterministic skills.

Cognitive surfaces:
  think(input)        — broad recall, returns what matches
  ask(question)       — targeted retrieval, one fact + confidence
  tell(text[,key])    — absorb a fact (optional versioning)
  tell_raw(facts[,key]) — absorb a pre-structured universal-schema fact (no LLM)

Deterministic skills (no LLM in the path):
  recall(query)       — lexical search, top-k matches + similarity
  history(key)        — full version chain for a versioned key
  stats()             — substrate vital signs

Access management:
  create_token(...)   — mint an API token for this MCP server

This is the tool surface an LLM drives: the model decides WHAT to do
(chat, ingest, query); these tools guarantee HOW (deterministic scans).
"""

import json
import logging
from typing import Any

from mcp.server.lowlevel.server import Server
from mcp.types import (
    CallToolResult,
    TextContent,
    Tool,
)

from domains.auth.service import AuthService

logger = logging.getLogger(__name__)

# Single-tenant runtime: every thought/token lives under one org.
ADA_ORG_ID = "ada"


def create_mcp_server(brain: Any, auth_service: AuthService) -> Server:
    """Create the MCP server with three cognitive tools.

    Args:
        brain: The Brain instance (domains.brain.think.Brain)
        auth_service: AuthService for token validation
    """
    app = Server("ada")

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="think",
                description=(
                    "Pure associative recall over Ada's substrate. Surfaces the "
                    "constellation of thoughts that resonate with the input — "
                    "no answer, no refusal, no synthesis. Call this when you "
                    "want CONTEXT to bring into a response."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "input": {"type": "string"},
                        "top_k": {"type": "integer", "default": 8},
                        "space": {"type": "string"},
                    },
                    "required": ["input"],
                },
            ),
            Tool(
                name="ask",
                description=(
                    "Targeted retrieval — find me the fact that answers this "
                    "question. Returns a single fact + confidence, or refuses "
                    "with 'I don't know.' Call this when you NEED a specific "
                    "answer and would rather be told 'no' than guess."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "space": {"type": "string"},
                        "speaker": {
                            "type": "string",
                            "description": "who is asking — first-person "
                                "tokens (my/i/me) resolve to this entity "
                                "before retrieval",
                        },
                    },
                    "required": ["question"],
                },
            ),
            Tool(
                name="tell",
                description=(
                    "Tell Ada something to remember. Optional `key` makes "
                    "this a new version of that key (versioned chain, drift "
                    "queryable). Call this on every decision or observation "
                    "you'd want to recall later."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "key": {"type": "string"},
                        "space": {"type": "string", "description": "space id (default 'main')"},
                        "speaker": {"type": "string"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="tell_raw",
                description=(
                    "Programmatically tell Ada a pre-structured fact. NO LLM "
                    "in the path — bypasses the enricher entirely. Use this "
                    "for curriculum loaders, batch importers, or anywhere you "
                    "know the universal-schema slot fill ahead of time. The "
                    "`facts` argument is {layer: {role: value}} matching the "
                    "universal schema (entity, perceptual, spatial, temporal, "
                    "relational, quantitative, epistemic)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "facts": {
                            "type": "object",
                            "description": "Universal-schema slot fill, e.g. "
                                "{\"entity\": {\"name\": \"blue\", \"kind\": "
                                "\"color\"}, \"perceptual\": {\"wavelength\": "
                                "\"470\"}}",
                        },
                        "key": {"type": "string"},
                        "text": {
                            "type": "string",
                            "description": "Optional human-readable label "
                                "(synthesized from facts if omitted).",
                        },
                        "space": {"type": "string", "description": "space id (default 'main')"},
                    },
                    "required": ["facts"],
                },
            ),
            Tool(
                name="recall",
                description=(
                    "Deterministic lexical search over Ada's substrate "
                    "(no LLM). Returns the top matching thoughts with "
                    "similarity scores and their versioned key."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                        "space": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="history",
                description=(
                    "The full version chain for a versioned key (e.g. "
                    "'market.SPY', 'chris.age') in chronological order."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"key": {"type": "string"},
                                   "space": {"type": "string"}},
                    "required": ["key"],
                },
            ),
            Tool(
                name="query",
                description=(
                    "Run ONE structured query operation against the "
                    "substrate — the closed op set: lookup / prev / count / "
                    "count_not / top / who / compare. Exact, deterministic, "
                    "no LLM. Conditions are {'layer.role': value} (value may "
                    "be a list when one slot must hold several values). "
                    "Examples: {\"op\":\"count\",\"conditions\":"
                    "{\"spatial.location\":\"boston\"}} · "
                    "{\"op\":\"top\",\"slot\":\"relational.object\","
                    "\"predicate_contains\":\"work\"} · "
                    "{\"op\":\"who\",\"conditions\":{\"perceptual.color\":"
                    "\"blue\",\"relational.object\":[\"engineer\",\"chess\"]}}"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "op": {"type": "string",
                               "enum": ["lookup", "prev", "count", "count_not",
                                        "top", "who", "compare"]},
                        "person": {"type": "string"},
                        "slot": {"type": "string"},
                        "conditions": {"type": "object"},
                        "value": {"type": "string"},
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                        "k": {"type": "integer", "default": 5},
                        "predicate_contains": {"type": "string"},
                        "space": {"type": "string"},
                    },
                    "required": ["op"],
                },
            ),
            Tool(
                name="keys",
                description=(
                    "Current belief for every versioned key in a space, "
                    "newest first — the workbench slot grid. Superseded "
                    "versions excluded; use `history` for the chain."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 60},
                        "q": {"type": "string",
                              "description": "narrow to keys containing this"},
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="entities",
                description=(
                    "Entity profiles for a space — every entity with its "
                    "current slot fills and weight. The constellation "
                    "view's data source; also what entities_where joins "
                    "over."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 150},
                        "conditions": {
                            "type": "object",
                            "description": "scope to entities matching ALL "
                                "{'layer.role': value} conditions (same "
                                "semantics as query/who) — the lens for "
                                "stores too big to draw whole",
                        },
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="similar",
                description=(
                    "k nearest entities by EXACT Jaccard over current "
                    "slot=value profiles — find accounts like this one. "
                    "Candidates come off the slot index (entities sharing "
                    "at least one value), capped — bounded at any store "
                    "size. Every score lists the shared dimensions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string"},
                        "k": {"type": "integer", "default": 5},
                        "space": {"type": "string"},
                    },
                    "required": ["entity"],
                },
            ),
            Tool(
                name="drift",
                description=(
                    "Descriptive profile drift for one entity over the "
                    "trailing window: dimensions added, dimensions "
                    "dropped via in-window supersession, churned keys, "
                    "and a 0-1 score that decomposes into those receipts. "
                    "Measurement, not prediction."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string"},
                        "window_days": {"type": "integer", "default": 30},
                        "space": {"type": "string"},
                    },
                    "required": ["entity"],
                },
            ),
            Tool(
                name="merge_candidates",
                description=(
                    "Deterministic entity-alias proposals: name-alike "
                    "pairs (misspelling distance or containment) with "
                    "shared slot-value evidence and conflicts. Read-only "
                    "— ada never merges on its own; the operator decides."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 25},
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="merge",
                description=(
                    "Merge entity `source` into `target`: slot rows are "
                    "re-pointed and universal references rewritten; the "
                    "original sentences stay verbatim as receipts. "
                    "dry_run defaults TRUE — counts only until confirmed."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "dry_run": {"type": "boolean", "default": True},
                        "space": {"type": "string"},
                    },
                    "required": ["source", "target"],
                },
            ),
            Tool(
                name="inspect",
                description=(
                    "The anatomy of one fact: content, entity, speaker, "
                    "timestamps, key and full version chain, and every "
                    "universal-schema slot it fills. Look up by key "
                    "(returns the current belief) or thought_id."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "thought_id": {"type": "string"},
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="archive",
                description=(
                    "Archive every current fact belonging to entities "
                    "matching ALL conditions — cohort-level data change, "
                    "bounded by the same capped entity intersection as "
                    "query/who. dry_run defaults TRUE and returns counts "
                    "only; pass dry_run=false to actually archive. "
                    "Archived facts leave recall/ops but stay in the "
                    "database. There is no archive-everything: conditions "
                    "are required."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "conditions": {"type": "object"},
                        "dry_run": {"type": "boolean", "default": True},
                        "space": {"type": "string"},
                    },
                    "required": ["conditions"],
                },
            ),
            Tool(
                name="forget",
                description=(
                    "Permanently delete facts — the irreversible erase, "
                    "for corrections, PII, and right-to-be-forgotten. "
                    "Scope by exactly one of: key (the whole version "
                    "chain), thought_id (one fact), or entity (every fact "
                    "of that entity). Removes the rows outright; unlike "
                    "archive, there is no undo. dry_run defaults TRUE and "
                    "returns counts only."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "thought_id": {"type": "string"},
                        "entity": {"type": "string"},
                        "dry_run": {"type": "boolean", "default": True},
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="forget_all",
                description=(
                    "Erase EVERY fact in a space — the nuclear reset, for "
                    "decommissioning or wiping test data. dry_run defaults "
                    "TRUE (counts only). To execute, pass dry_run=false AND "
                    "confirm equal to the space id (typed confirmation, not "
                    "a bare flag). Admin only; no undo."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "confirm": {"type": "string",
                                    "description": "must equal the space id"},
                        "dry_run": {"type": "boolean", "default": True},
                        "space": {"type": "string"},
                    },
                },
            ),
            Tool(
                name="stats",
                description=(
                    "Substrate vital signs: total thoughts, versioned keys, "
                    "multi-version keys, and per-layer slot fill."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="consolidate",
                description=(
                    "Offline maintenance pass over a space: re-enrich "
                    "slotless facts, retroactively resolve first-person "
                    "facts to the operator's entity (`me`), archive "
                    "near-duplicate misspellings (newer wins). "
                    "Deterministic, never in the answer path. dry_run "
                    "previews without writing."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "space": {"type": "string"},
                        "me": {"type": "string",
                               "description": "operator identity for "
                                   "retroactive first-person resolution"},
                        "dry_run": {"type": "boolean", "default": False},
                    },
                },
            ),
            Tool(
                name="token_list",
                description=(
                    "List API tokens for this server (prefix, name, "
                    "permissions, status, expiry). Never returns raw tokens."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="token_revoke",
                description=(
                    "Revoke an API token by id or prefix. Revocation is "
                    "immediate and permanent."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"token": {"type": "string",
                                             "description": "token id or prefix"}},
                    "required": ["token"],
                },
            ),
            Tool(
                name="token_delete",
                description=(
                    "Permanently delete a REVOKED token's record by id or "
                    "prefix. Active tokens must be revoked first — delete "
                    "is bookkeeping, revoke is the security action."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"token": {"type": "string",
                                             "description": "token id or prefix"}},
                    "required": ["token"],
                },
            ),
            Tool(
                name="create_token",
                description=(
                    "Mint an API token for accessing this MCP server. The raw "
                    "token is returned ONCE — store it now. Optionally scope by "
                    "permissions and expiry."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "default": "repl-token"},
                        "permissions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["read", "write"],
                        },
                        "expires_days": {"type": "integer"},
                        "model_id": {"type": "string"},
                    },
                },
            ),
        ]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> CallToolResult:
        args = arguments or {}

        if name == "think":
            return await _handle_think(brain, args)
        if name == "ask":
            return await _handle_ask(brain, args)
        if name == "tell":
            return await _handle_tell(brain, args)
        if name == "tell_raw":
            return await _handle_tell_raw(brain, args)
        if name == "recall":
            return await _handle_recall(brain, args)
        if name == "history":
            return await _handle_history(brain, args)
        if name == "query":
            return await _handle_query(brain, args)
        if name == "keys":
            return await _handle_keys(brain, args)
        if name == "entities":
            return await _handle_entities(brain, args)
        if name == "archive":
            return await _handle_archive(brain, args)
        if name == "forget":
            return await _handle_forget(brain, args)
        if name == "forget_all":
            return await _handle_forget_all(brain, args)
        if name == "similar":
            return await _handle_similar(brain, args)
        if name == "drift":
            return await _handle_drift(brain, args)
        if name == "merge_candidates":
            return await _handle_merge_candidates(brain, args)
        if name == "merge":
            return await _handle_merge(brain, args)
        if name == "inspect":
            return await _handle_inspect(brain, args)
        if name == "consolidate":
            return await _handle_consolidate(brain, args)
        if name == "stats":
            return await _handle_stats(brain, args)
        if name == "create_token":
            return await _handle_create_token(brain, args)
        if name == "token_list":
            return await _handle_token_list(brain, args)
        if name == "token_revoke":
            return await _handle_token_revoke(brain, args)
        if name == "token_delete":
            return await _handle_token_delete(brain, args)
        return _err(f"Unknown tool: {name}")

    return app


# ── handlers ────────────────────────────────────────────────────────

async def _handle_think(brain, args: dict) -> CallToolResult:
    input_text = args.get("input", "")
    top_k = int(args.get("top_k", 8))
    if not input_text:
        return _err("Missing 'input' parameter")
    try:
        store, _ = _space(brain, args)
        results = await _maybe(store.recall(input_text, top_k=top_k,
                                            exclude_speakers=("ada",)))
        return _ok({
            "input": input_text, "space": store.space_id,
            "activated": [
                {"content": r.thought.content,
                 "similarity": round(float(r.global_similarity), 3)}
                for r in results
            ],
        })
    except Exception as e:
        logger.error("think failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_ask(brain, args: dict) -> CallToolResult:
    question = args.get("question", "")
    if not question:
        return _err("Missing 'question' parameter")
    try:
        from ada.memory.thought_space import resolve_question_identity
        store, _ = _space(brain, args)
        surface = _get_surface(brain, store)
        resolved = resolve_question_identity(question, args.get("speaker"))
        a = await surface.ask_async(resolved)
        out = {
            "question": question, "space": store.space_id,
            "refused": a.refused,
            "confidence": round(a.confidence, 3),
            "fact": a.fact.content if a.fact else None,
            "answer": a.rendered,
        }
        if resolved != question:
            out["resolved_question"] = resolved
        return _ok(out)
    except Exception as e:
        logger.error("ask failed: %s", e, exc_info=True)
        return _err(str(e))


async def _persist_now(brain, stored) -> bool:
    """Write-through: persist synchronously; fall back to the background
    queue on failure so the fact is retried rather than lost."""
    try:
        from ada.memory.thought_persistence import save_thought
        await save_thought(brain._session_factory, stored)
        return True
    except Exception:
        logger.warning("write-through failed; queued for retry", exc_info=True)
        brain._persist_queue.append(stored)
        return False


def _space(brain, args: dict):
    """Resolve the target space store. `space` arg selects it; default 'main'.
    Returns (store, is_sql)."""
    space_id = args.get("space") or "main"
    store = brain.space(space_id)
    return store, getattr(store, "is_sql", False)


async def _maybe(value):
    """Await coroutines, pass through plain values — so handlers work
    against both the sync ThoughtSpace and the async SqlFactStore."""
    import inspect
    return await value if inspect.isawaitable(value) else value


async def _handle_tell_raw(brain, args: dict) -> CallToolResult:
    facts = args.get("facts") or {}
    key = args.get("key")
    text = args.get("text")
    if not facts or not isinstance(facts, dict):
        return _err("Missing or invalid 'facts' parameter (must be dict)")
    try:
        store, is_sql = _space(brain, args)
        stored = await _maybe(store.tell_raw(facts=facts, key=key, text=text,
                                             speaker="curriculum"))
        if stored is None:
            return _ok({"told": False, "reason": "duplicate or empty"})
        durable = True if is_sql else await _persist_now(brain, stored)
        return _ok({
            "told": True, "durable": durable, "space": store.space_id,
            "thought_id": stored.thought_id,
            "version": stored.metadata.get("_version"),
            "key": stored.metadata.get("_key"),
            "synthesized_text": stored.content,
        })
    except Exception as e:
        logger.error("tell_raw failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_tell(brain, args: dict) -> CallToolResult:
    text = args.get("text", "")
    key = args.get("key")
    if not text:
        return _err("Missing 'text' parameter")
    try:
        store, is_sql = _space(brain, args)
        speaker = args.get("speaker") or "incoming"
        stored = await _maybe(store.absorb(text, key=key, speaker=speaker))
        if stored is None:
            return _ok({"told": False, "reason": "duplicate"})
        durable = True if is_sql else await _persist_now(brain, stored)
        return _ok({
            "told": True, "durable": durable, "space": store.space_id,
            "thought_id": stored.thought_id,
            "version": stored.metadata.get("_version"),
            "key": stored.metadata.get("_key"),
        })
    except Exception as e:
        logger.error("tell failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_query(brain, args: dict) -> CallToolResult:
    from ada.cognitive.ops import execute_op
    try:
        store, is_sql = _space(brain, args)
        op = {k: v for k, v in args.items() if k != "space"}
        if is_sql:
            answer = await store.execute_op(op)
        else:
            answer = execute_op(store, op)
        return _ok({"op": args.get("op"), "space": store.space_id, "answer": answer})
    except (ValueError, KeyError) as e:
        return _err(f"bad query op: {e}")
    except Exception as e:
        logger.error("query failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_recall(brain, args: dict) -> CallToolResult:
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    if not query:
        return _err("Missing 'query' parameter")
    try:
        store, _ = _space(brain, args)
        results = await _maybe(store.recall(query, top_k=top_k))
        return _ok({
            "query": query, "space": store.space_id,
            "results": [
                {"content": r.thought.content,
                 "similarity": round(float(r.global_similarity), 3),
                 "key": r.thought.metadata.get("_key")}
                for r in results
            ],
        })
    except Exception as e:
        logger.error("recall failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_history(brain, args: dict) -> CallToolResult:
    key = args.get("key", "")
    if not key:
        return _err("Missing 'key' parameter")
    try:
        store, _ = _space(brain, args)
        hist = await _maybe(store.history(key))
        return _ok({
            "key": key, "space": store.space_id, "versions": len(hist),
            "chain": [
                {"version": h.metadata.get("_version"), "content": h.content,
                 "thought_id": h.thought_id}
                for h in hist
            ],
        })
    except Exception as e:
        logger.error("history failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_entities(brain, args: dict) -> CallToolResult:
    try:
        store, _ = _space(brain, args)
        limit = int(args.get("limit", 150))
        conditions = args.get("conditions") or None
        view = await _maybe(store.entity_view(limit=limit,
                                              conditions=conditions))
        return _ok({"space": store.space_id, "count": len(view),
                    "scoped": bool(conditions), "entities": view})
    except Exception as e:
        logger.error("entities failed: %s", e, exc_info=True)
        return _err(str(e))


async def _reload_memory_space(brain, store) -> None:
    """After an at-rest mutation, a memory-mode space must reload from
    the DB (SQL mode reads it directly)."""
    if getattr(store, "is_sql", False):
        _surface_cache.pop((id(brain), store.space_id), None)
        return
    from ada.memory.thought_persistence import load_thoughts
    from ada.memory.thought_space import ThoughtSpace
    fresh = ThoughtSpace(enricher=brain._enricher, space_id=store.space_id)
    await load_thoughts(brain._session_factory, fresh,
                        space_id=store.space_id)
    brain._spaces[store.space_id] = fresh
    if brain._cognitive.thought_space is store:
        brain._cognitive._space = fresh  # property is read-only
    _surface_cache.pop((id(brain), store.space_id), None)


async def _handle_archive(brain, args: dict) -> CallToolResult:
    from sqlalchemy import select, update
    from domains.models.db_models import AdaThought, FactSlot
    conditions = args.get("conditions")
    if not conditions or not isinstance(conditions, dict):
        return _err("archive requires non-empty 'conditions' — "
                    "there is no archive-everything")
    dry = bool(args.get("dry_run", True))
    try:
        store, is_sql = _space(brain, args)
        if is_sql:
            names = await store._entities_where(conditions)
        else:
            names = await _maybe(store.entities_where(conditions))
        sf = brain._session_factory
        ids: list = []
        if names:
            async with sf() as s:
                r = await s.execute(
                    select(FactSlot.thought_id).distinct()
                    .where(FactSlot.space_id == store.space_id,
                           FactSlot.is_current == 1,
                           FactSlot.entity.in_(list(names))))
                ids = [row[0] for row in r.all()]
        payload = {"space": store.space_id, "conditions": conditions,
                   "entities_matched": len(names), "facts": len(ids),
                   "dry_run": dry}
        if dry:
            payload["note"] = ("dry run — nothing changed; call with "
                               "dry_run=false to archive")
            return _ok(payload)
        if ids:
            async with sf() as s:
                await s.execute(update(AdaThought)
                                .where(AdaThought.thought_id.in_(ids))
                                .values(archived=1))
                await s.execute(update(FactSlot)
                                .where(FactSlot.thought_id.in_(ids))
                                .values(is_current=0))
                await s.commit()
            await _reload_memory_space(brain, store)
        return _ok(payload)
    except Exception as e:
        logger.error("archive failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_forget(brain, args: dict) -> CallToolResult:
    """Hard-delete by exactly one of key / thought_id / entity. Removes
    ada_thoughts + fact_slots rows outright; no undo (cf. archive)."""
    from sqlalchemy import delete, select
    from domains.models.db_models import AdaThought, FactSlot
    key = (args.get("key") or "").strip().lower() or None
    tid = (args.get("thought_id") or "").strip() or None
    entity = (args.get("entity") or "").strip().lower() or None
    given = [x for x in (key, tid, entity) if x]
    if len(given) != 1:
        return _err("forget needs exactly one of key, thought_id, or "
                    "entity")
    dry = bool(args.get("dry_run", True))
    try:
        store, _ = _space(brain, args)
        sf = brain._session_factory
        async with sf() as s:
            if tid:
                ids = [tid] if (await s.execute(select(AdaThought.thought_id)
                    .where(AdaThought.thought_id == tid,
                           AdaThought.space_id == store.space_id))).first() \
                    else []
                scope = {"thought_id": tid}
            else:
                col = FactSlot.key if key else FactSlot.entity
                val = key or entity
                r = await s.execute(
                    select(FactSlot.thought_id).distinct()
                    .where(FactSlot.space_id == store.space_id, col == val))
                ids = [row[0] for row in r.all()]
                scope = {"key": key} if key else {"entity": entity}
        payload = {"space": store.space_id, **scope, "facts": len(ids),
                   "dry_run": dry}
        if dry:
            payload["note"] = ("dry run — nothing deleted; call with "
                               "dry_run=false to erase permanently")
            return _ok(payload)
        if ids:
            async with sf() as s:
                await s.execute(delete(FactSlot)
                                .where(FactSlot.thought_id.in_(ids)))
                await s.execute(delete(AdaThought)
                                .where(AdaThought.thought_id.in_(ids)))
                await s.commit()
            await _reload_memory_space(brain, store)
        return _ok(payload)
    except Exception as e:
        logger.error("forget failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_forget_all(brain, args: dict) -> CallToolResult:
    """Wipe an entire space. dry_run default TRUE; to execute, confirm
    must equal the space id (typed confirmation)."""
    from sqlalchemy import delete, func, select
    from domains.models.db_models import AdaThought, FactSlot
    dry = bool(args.get("dry_run", True))
    try:
        store, _ = _space(brain, args)
        sf = brain._session_factory
        async with sf() as s:
            n = (await s.execute(
                select(func.count()).select_from(AdaThought)
                .where(AdaThought.space_id == store.space_id))).scalar() or 0
        payload = {"space": store.space_id, "facts": int(n), "dry_run": dry}
        if dry:
            payload["note"] = (f"dry run — nothing deleted; to erase all "
                               f"{n} facts call dry_run=false with "
                               f"confirm='{store.space_id}'")
            return _ok(payload)
        if (args.get("confirm") or "") != store.space_id:
            return _err(f"typed confirmation required: pass "
                        f"confirm='{store.space_id}' to erase all "
                        f"{n} facts in this space")
        async with sf() as s:
            await s.execute(delete(FactSlot)
                            .where(FactSlot.space_id == store.space_id))
            await s.execute(delete(AdaThought)
                            .where(AdaThought.space_id == store.space_id))
            await s.commit()
        await _reload_memory_space(brain, store)
        return _ok(payload)
    except Exception as e:
        logger.error("forget_all failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_consolidate(brain, args: dict) -> CallToolResult:
    from ada.memory.consolidate import consolidate
    space_id = args.get("space") or "main"
    dry_run = bool(args.get("dry_run", False))
    try:
        report = await consolidate(
            brain._session_factory, space_id=space_id,
            me=args.get("me"), enricher=brain._enricher, dry_run=dry_run)
        if not dry_run:
            await _reload_memory_space(brain, brain.space(space_id))
        return _ok(report)
    except Exception as e:
        logger.error("consolidate failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_similar(brain, args: dict) -> CallToolResult:
    from ada.memory.profile_sim import similar_entities
    entity = (args.get("entity") or "").strip()
    if not entity:
        return _err("Missing 'entity' parameter")
    try:
        store, _ = _space(brain, args)
        out = await similar_entities(brain._session_factory,
                                     store.space_id, entity,
                                     k=int(args.get("k", 5)))
        if out.get("error"):
            return _err(out["error"])
        return _ok(out)
    except Exception as e:
        logger.error("similar failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_drift(brain, args: dict) -> CallToolResult:
    from ada.memory.profile_sim import entity_drift
    entity = (args.get("entity") or "").strip()
    if not entity:
        return _err("Missing 'entity' parameter")
    try:
        store, _ = _space(brain, args)
        out = await entity_drift(brain._session_factory, store.space_id,
                                 entity,
                                 window_days=int(args.get("window_days", 30)))
        if out.get("error"):
            return _err(out["error"])
        return _ok(out)
    except Exception as e:
        logger.error("drift failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_merge_candidates(brain, args: dict) -> CallToolResult:
    from ada.memory.consolidate import merge_candidates
    try:
        store, _ = _space(brain, args)
        cands = await merge_candidates(brain._session_factory,
                                       space_id=store.space_id,
                                       limit=int(args.get("limit", 25)))
        return _ok({"space": store.space_id, "count": len(cands),
                    "candidates": cands})
    except Exception as e:
        logger.error("merge_candidates failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_merge(brain, args: dict) -> CallToolResult:
    from ada.memory.consolidate import merge_entities
    try:
        store, _ = _space(brain, args)
        report = await merge_entities(
            brain._session_factory, space_id=store.space_id,
            source=args.get("source") or "", target=args.get("target") or "",
            dry_run=bool(args.get("dry_run", True)))
        if report.get("error"):
            return _err(report["error"])
        if not report["dry_run"]:
            await _reload_memory_space(brain, store)
        return _ok(report)
    except Exception as e:
        logger.error("merge failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_inspect(brain, args: dict) -> CallToolResult:
    from sqlalchemy import select as _select
    from domains.models.db_models import AdaThought
    key = (args.get("key") or "").strip()
    tid = (args.get("thought_id") or "").strip()
    if not key and not tid:
        return _err("inspect needs a key or a thought_id")
    try:
        store, _ = _space(brain, args)
        sf = brain._session_factory
        chain: list = []
        if key:
            hist = await _maybe(store.history(key))
            if not hist:
                return _err(f"no such key: {key}")
            chain = hist
            row = hist[-1]  # current belief
            content, speaker = row.content, row.speaker
            created, meta = row.created_at, row.metadata
            tid = row.thought_id
        else:
            async with sf() as s:
                db_row = (await s.execute(_select(AdaThought).where(
                    AdaThought.thought_id == tid))).scalar_one_or_none()
            if db_row is None:
                return _err(f"no such thought: {tid}")
            content, speaker = db_row.content, db_row.speaker
            created, meta = db_row.created_at, dict(db_row.extra_data or {})
            k = meta.get("_key")
            if k:
                key = k
                chain = await _maybe(store.history(k))
        from datetime import datetime, timezone
        u = meta.get("_universal") or {}
        slots = []
        entity = None
        for layer, roles in u.items():
            if not isinstance(roles, dict):
                continue
            for role, v in roles.items():
                if v is None or not str(v).strip():
                    continue
                slots.append({"layer": layer, "role": role, "value": str(v)})
        ent = u.get("entity")
        if isinstance(ent, dict) and ent.get("name"):
            entity = str(ent["name"]).strip().lower()
        return _ok({
            "thought_id": tid,
            "space": store.space_id,
            "content": content,
            "entity": entity,
            "speaker": speaker,
            "created_at": datetime.fromtimestamp(
                created, tz=timezone.utc).isoformat() if created else None,
            "key": key or None,
            "version": meta.get("_version"),
            "versions": len(chain) or None,
            "chain": [{"version": t.metadata.get("_version"),
                       "content": t.content, "thought_id": t.thought_id}
                      for t in chain] or None,
            "slots": slots,
        })
    except Exception as e:
        logger.error("inspect failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_keys(brain, args: dict) -> CallToolResult:
    try:
        store, _ = _space(brain, args)
        limit = int(args.get("limit", 60))
        q = args.get("q")
        facts = await _maybe(store.keyed_facts(limit=limit, q=q))
        return _ok({"space": store.space_id, "count": len(facts),
                    "q": q or None, "facts": facts})
    except Exception as e:
        logger.error("keys failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_stats(brain, args: dict) -> CallToolResult:
    try:
        store, _ = _space(brain, args)
        return _ok(await _maybe(store.stats()))
    except Exception as e:
        logger.error("stats failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_token_list(brain, args: dict) -> CallToolResult:
    from sqlalchemy import select
    from domains.models.db_models import Token
    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available")
    try:
        async with session_factory() as session:
            rows = (await session.execute(
                select(Token).order_by(Token.created_at))).scalars().all()
        return _ok({"tokens": [
            {"id": str(t.id), "prefix": t.token_prefix, "name": t.name,
             "permissions": t.permissions, "status": t.status,
             "space": t.model_id,
             "created_at": t.created_at.isoformat() if t.created_at else None,
             "expires_at": t.expires_at.isoformat() if t.expires_at else None}
            for t in rows]})
    except Exception as e:
        logger.error("token_list failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_token_revoke(brain, args: dict) -> CallToolResult:
    from datetime import datetime
    from sqlalchemy import or_, select, cast, String
    from domains.models.db_models import Token
    needle = (args.get("token") or "").strip()
    if not needle:
        return _err("Missing 'token' (id or prefix)")
    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available")
    conds = [Token.token_prefix == needle[:12],
             cast(Token.id, String) == needle]
    try:
        from uuid import UUID
        conds.append(Token.id == UUID(needle))  # dashed/undashed both bind
    except ValueError:
        pass
    try:
        async with session_factory() as session:
            rows = (await session.execute(
                select(Token).where(or_(*conds)))).scalars().all()
            if not rows:
                return _err(f"No token matching {needle!r}")
            for t in rows:
                t.status = "revoked"
                t.revoked_at = datetime.utcnow()
            await session.commit()
        return _ok({"revoked": [str(t.id) for t in rows]})
    except Exception as e:
        logger.error("token_revoke failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_token_delete(brain, args: dict) -> CallToolResult:
    from sqlalchemy import or_, select, cast, String
    from domains.models.db_models import Token
    needle = (args.get("token") or "").strip()
    if not needle:
        return _err("Missing 'token' (id or prefix)")
    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available")
    conds = [Token.token_prefix == needle[:12],
             cast(Token.id, String) == needle]
    try:
        from uuid import UUID
        conds.append(Token.id == UUID(needle))
    except ValueError:
        pass
    try:
        async with session_factory() as session:
            rows = (await session.execute(
                select(Token).where(or_(*conds)))).scalars().all()
            if not rows:
                return _err(f"No token matching {needle!r}")
            active = [t for t in rows if t.status == "active"]
            if active:
                return _err("Token is still active — revoke it first; "
                            "delete is bookkeeping, revoke is the "
                            "security action")
            deleted = [str(t.id) for t in rows]
            for t in rows:
                await session.delete(t)
            await session.commit()
        return _ok({"deleted": deleted})
    except Exception as e:
        logger.error("token_delete failed: %s", e, exc_info=True)
        return _err(str(e))


async def _handle_create_token(brain, args: dict) -> CallToolResult:
    import hashlib
    import secrets
    from datetime import datetime, timedelta

    from domains.models.db_models import Token

    session_factory = getattr(brain, "_session_factory", None)
    if session_factory is None:
        return _err("No database session available for token creation")

    name = args.get("name") or "repl-token"
    permissions = args.get("permissions") or ["read", "write"]
    model_id = args.get("model_id")
    expires_days = args.get("expires_days")
    expires_at = (
        datetime.utcnow() + timedelta(days=int(expires_days)) if expires_days else None
    )

    raw_token = f"ada_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    try:
        async with session_factory() as session:
            tok = Token(
                name=name,
                token_hash=token_hash,
                token_prefix=raw_token[:12],
                org_id=ADA_ORG_ID,
                model_id=model_id,
                permissions=permissions,
                expires_at=expires_at,
            )
            session.add(tok)
            await session.commit()
            await session.refresh(tok)
            token_id = str(tok.id)
        return _ok({
            "id": token_id,
            "name": name,
            "token": raw_token,
            "token_prefix": raw_token[:12],
            "permissions": permissions,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "note": "Store this token now — it is not shown again.",
        })
    except Exception as e:
        logger.error("create_token failed: %s", e, exc_info=True)
        return _err(str(e))


# ── plumbing ────────────────────────────────────────────────────────

_surface_cache: dict = {}


def _get_surface(brain, store=None):
    """Build a CognitiveSurface over a space's store (default: the
    brain's main space). One surface per (brain, space) — the renderer
    is shared, the retrieval target isn't."""
    if store is None:
        store = brain.space("main")
    cache_key = (id(brain), store.space_id)
    if cache_key in _surface_cache:
        return _surface_cache[cache_key]
    from ada.cognitive.generate import build_llm_renderer
    from ada.cognitive.surface import CognitiveSurface
    surface = CognitiveSurface(space=store, renderer=build_llm_renderer())
    _surface_cache[cache_key] = surface
    return surface


def _ok(payload: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
    )


def _err(msg: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": msg}))],
        isError=True,
    )
