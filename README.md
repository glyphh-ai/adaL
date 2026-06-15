# Ada

**Schema-on-write memory for LLMs**, by [Glyphh AI](https://glyphh.ai).
Facts in prose, answers exact, beliefs versioned, refusals honest.

```bash
pip install glyphh-ada        # imports as `ada`
```

Ada is a universal fact table, deliberately not a graph: an LLM maps
each fact into one fixed schema at write time, and reads are exact,
deterministic scans — aggregation, distribution, multi-condition
intersection, versioned history — with full provenance, on corpora far
larger than any prompt can hold. It runs on-device (SQLite, zero setup)
or against Postgres for scale, and exposes itself to any LLM over MCP.

Measured (pre-registered protocol, raw logs in `benchmark/`): matches
or beats a hand-schema'd graph database on NL query accuracy from 1K to
1M facts with **zero per-domain schema design** (100.0% at 1M facts,
no degradation with scale), beats text-to-SQL over a generic EAV store
by ~20 points, and beats embedding RAG by 30+ (RAG decays to ~24% at 1M
facts; Ada doesn't). 1M facts ingest in ~9 seconds. The full argument
is the paper: [`paper.md`](paper.md). Every number traces to
`benchmark/PROTOCOL.md` and the phase reports — including the ones we
lost.

---

## How it works

Three pieces, each independently inspectable:

1. **Universal schema** — a fixed 7-layer × 33-role lattice every fact maps
   into (entity, perceptual, spatial, temporal, relational, quantitative,
   epistemic). Counting "facts where color = blue" is an exact scan; "top
   5 cities" is `Counter().most_common(5)`. An empty slot is a structural
   ∅ — Ada refuses instead of confabulating. `ada/cognitive/universal.py`.

2. **Versioned memory** — write a fact under a `key` and it becomes v1, v2,
   v3… with the full chain queryable via `history`. `ada/memory/thought_space.py`.

3. **Storage** — SQLite by default (`~/.ada/ada.db`, zero setup). Point
   `DATABASE_URL` at Postgres and the runtime switches backends. Two
   engine modes: **memory** (default — in-process indexes, 0–sub-ms ops,
   loads the corpus into RAM at boot) and **sql** (`ADA_STORAGE=sql` —
   the eight closed ops compiled to fixed SQL templates over an indexed
   `fact_slots` table; O(1) boot, O(1) RAM, for 10M+-fact corpora). The
   LLM only ever picks an op and fills values — no model-generated SQL
   exists, so the runaway-query class is excluded by construction.

Facts arrive two ways: **`tell_raw`** takes pre-structured slot fills with
no LLM in the path; **`tell`** takes natural language — with an Anthropic
API key, an enricher maps the text into the schema at write time (one
cached LLM call per fact). The read path never calls an LLM; structured
queries and lexical recall are exact, deterministic scans.

---

## Install & start

### Quickest: `make`

```bash
make install        # .venv + editable install (+ dev extras), seeds .env
# add ANTHROPIC_API_KEY to .env  (optional — substrate works without it)
make dev            # server with hot-reload on http://localhost:8002
```

Other targets: `make repl` (interactive shell), `make serve` (no reload),
`make test`, `make fmt`, `make clean`. Run `make` alone to list them.

### The terminal app — the interface

Just run `ada`. It opens a **full-screen terminal app** — one interface
for the whole substrate, with the same design language as the old web
workbench:

- **Dashboard** — live vital signs as terminal graphs: stat cards, the
  per-layer slot-fill bar chart, and a session sparkline, refreshed live.
- **Terminal** — the full command surface (`tell` · `ask` · `think` ·
  `count` · `top` · `find` · `history` · `recall` · …). Bare text with no
  verb is treated as `ask`.
- **Memory** — keyed facts at their current belief, filterable.
- **Tokens** — mint / list / revoke the credentials that open `/mcp`.

Everything is an **MCP tool call** against the running server (the same
`/mcp` door Claude and every other client use), so the app, Claude, and
all clients share one SQL-backed memory. Writes are write-through
durable. Switch views with the rail (or keys `1`–`4`).

```bash
make dev            # start the server (or `ada` auto-starts one)
ada                 # the terminal app  ·  ADA_URL=http://host:8002/mcp ada
ada repl            # escape hatch: the classic line REPL
```

```
  ada› tell key=carol.location Carol lives in Austin.
  absorbed v1
  ada› tell key=carol.location Carol lives in Denver.
  absorbed v2
  ada› count spatial.location=denver
  3                                  # current belief — Carol's Austin era excluded
  ada› history carol.location
  v1: Carol lives in Austin.   v2: Carol lives in Denver.
  ada› top relational.object work    # distribution, predicate-filtered
  engineer (12), designer (9), ...
```

Type `help` in the Terminal view for the full command list. The browser
workbench at `/` is **deprecated** in favor of this app — it stays served
for the no-terminal path, in maintenance only.

---

## Production: Docker

The image is storage-agnostic — `DATABASE_URL` decides the backend. Unset, Ada
runs on in-process SQLite. Point it at Postgres and the runtime runs the
alembic migrations on first boot.

### Recommended: compose (runtime + Postgres)

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY — DB is wired by compose
docker compose up -d --build
curl localhost:8002/health
```

The bundled `db` service is `postgres:16`; the runtime waits for it to be
healthy, connects via `DATABASE_URL=postgresql://ada:ada@db:5432/ada`, and
persists memory to the `pgdata` named volume across restarts and upgrades.

### Single container (SQLite, no Postgres)

```bash
docker build -t ada .
docker run -d -p 8002:8002 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v ada-data:/root/.ada \
  ada
```

Leaving `DATABASE_URL` unset keeps SQLite at `~/.ada/ada.db`; mount a volume
there to persist the substrate.

---

## Using it from an LLM (MCP)

Ada exposes a single MCP endpoint at **`/mcp`**. Start the server, then point
any MCP client at `http://localhost:8002/mcp`.

### The tools

| Tool | What it does |
|---|---|
| `think(input, top_k)` | Broad recall — surfaces the thoughts that match. No answer, just context. |
| `ask(question)` | Targeted retrieval. Returns one fact + confidence, or "I don't know." |
| `tell(text, key?)` | Natural-language ingestion. With `key`, becomes a new version of that key. |
| `tell_raw(facts, key?)` | Programmatic ingestion of a universal-schema slot fill. **No LLM in the path.** |
| `recall(query, top_k)` | Deterministic lexical search. Top matches + similarity + versioned key. |
| `query(op, ...)` | One structured operation from the closed op set: count / who / top / lookup / prev / count_not / compare. Exact, no LLM. |
| `history(key)` | Full version chain for a key, chronological. |
| `stats()` | Substrate vital signs: thoughts, versioned keys, per-layer slot fill. |
| `create_token(...)` | Mint an API token for this MCP server (returned once). |

`domains/mcp/server.py`.

### Connecting clients

```bash
ada setup claude            # auto-configure Claude Code
ada setup                   # print config snippets for Claude Desktop / Cursor / any MCP client
```

### Spaces (multi-tenant scoping)

Every fact lives in a **space** (default `main`). Pass `space` to any
MCP tool to read/write an isolated space — facts, counts, and version
chains never cross. In the REPL, `space <name>` switches the session's
active space. A token can be **bound to one space** (its `model_id`
column): a space-bound token is rejected (403) on any other space, so
each team or engagement gets a token that can only touch its own
memory. This scoping lives in the open runtime — self-hosted
multi-team works without any hosted control plane.

### Identity (first-person facts)

Tell Ada who you are (`me chris` in the REPL, or `speaker` on the
`tell` tool) and first-person statements resolve to your entity at
write time: "I am married to Brandi" stores under `entity=chris`, so
"who is my wife?" becomes an exact entity join. Third-person facts are
untouched. Deterministic, no LLM.

### Authentication

Set `ADA_AUTH_REQUIRED=true` and every `/mcp` request needs
`Authorization: Bearer <token>`. Write tools (`tell`, `tell_raw`,
token management) require write permission; the rest need read.
Bootstrap the first token locally (direct DB), then manage tokens from
the REPL or over MCP:

```bash
ada token create --name my-client --permissions read,write   # bootstrap (shown once)
ada                       # in the REPL: token create | token list | token revoke <id>
ADA_TOKEN=ada_... ada     # REPL authenticates with this token
```

### HTTP endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness probe |
| `POST /mcp` | MCP tool calls (Streamable HTTP) |
| `POST /{org_id}/tokens` | API token management |

---

## Configuration

All values have defaults — the server boots with an empty `.env`. The `.env`
is read by both the server and the `ada` REPL; secrets can also be stored
encrypted in `~/.ada/vault` (`ada setup key`).

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Enables the `tell` enricher + LLM as `ask` renderer |
| `ADA_MODEL` | `claude-haiku-4-5-20251001` | LLM model for enrichment / rendering |
| `DATABASE_URL` | SQLite at `~/.ada/ada.db` | `postgresql://…` switches to the Postgres backend |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8002` | Server port |
| `ADA_STORAGE` | `memory` | `memory` (in-RAM indexes) or `sql` (fact_slots-backed, O(1) boot for 10M+ facts) |
| `ADA_AUTH_REQUIRED` | `false` | Require Bearer tokens on `/mcp` (set `true` for any non-local deployment) |
| `JWT_SECRET_KEY` | — | JWT validation secret (token auth) |
| `ENABLE_DOCS` | `false` | Enable `/docs` and `/redoc` |

---

## Architecture map

```
ada/
  cognitive/
    universal.py       7-layer × 33-role universal schema + LLM enricher
    surface.py         think / ask cognitive surfaces
    generate.py        optional LLM renderer (the surface form)
  memory/
    thought_space.py   the substrate: tell_raw / absorb / structured
                       queries (count, distribution, intersection) /
                       lexical recall / versioned keys
    thought_persistence.py   DB sync (SQLite / Postgres)
    ada_cognitive.py   memory + input routing + conversation
  encoder/
    llm_enricher.py    LLM-at-build-time text → schema extraction
  tui/                 CLI / REPL  (the `ada` command)

domains/
  brain/               think() pipeline (perceive → recall → respond)
  mcp/server.py        MCP tools: think / ask / tell / tell_raw / recall /
                       history / stats / create_token

api/                   FastAPI HTTP routes (health, tokens)
infrastructure/        config + database (SQLite / Postgres)
shared/                auth, exceptions, middleware

benchmark/             PROTOCOL.md + the benchmark suite (being rebuilt)
scripts/               ada_repl.py and the 77-fact hard test
```

---

## License

Apache-2.0 — see [`LICENSE`](LICENSE). Copyright © 2026 Glyphh AI LLC.
