# Ada Workbench — the management interface

*Status: design accepted, build in progress. This document records the
architecture decisions; the UI itself follows the Ada Workbench design
in the brand design system.*

## What it is

The workbench is the web interface for managing an Ada runtime: telling
facts, running the closed op set, browsing recall and history chains,
and administering tokens, users, and spaces. It replaces the REPL as
the management surface; the REPL remains the bootstrapper that gets the
runtime running and points at the workbench.

It ships **inside the open runtime**. The same UI serves both the local
self-hosted install and the hosted cloud product — the cloud does not
get a second, better admin interface.

## Where it runs

The workbench is a static single-page app whose prebuilt assets ship in
the `glyphh-ada` wheel (no Node required at install time). The runtime
serves it at `/` on its own port:

```
pip install glyphh-ada
ada                       # boots runtime + REPL
open http://localhost:8002   # → workbench login
```

It talks to the runtime exclusively through the public contract — the
MCP tools on `/mcp` plus the small `/auth` surface below. It is
deliberately a reference client: anything the workbench can do, any
MCP client can do.

## Two entry modes, one app

| | Local / self-hosted | Cloud (glyphh-cloud) |
|---|---|---|
| Served by | the runtime itself | the (hosted) runtime itself |
| Scope | full admin — all spaces, tokens, users, config | one space, via a short-lived space-scoped session minted by the control plane |
| Entry | browse to the runtime port, log in | "Open workbench" on a space in the console |

The cloud console keeps what is genuinely control-plane business —
orgs, spaces, provisioning, token-shown-once, billing — and delegates
all fact-level work to the workbench. (The console's interim
space-detail page is retired once the workbench reaches parity.)

## Auth: two principals, one enforcement path

The runtime enforces all access. There are two kinds of principal:

1. **Tokens** — machine auth for MCP clients (agents, the control
   plane, the REPL). Bearer tokens with read/write permissions and
   optional space binding. Already shipped.
2. **Users** — human auth for the workbench. A `users` table
   (username, password hash, role, `must_change_password`);
   `POST /auth/login` issues an httponly session cookie. Sessions map
   onto the **same permission layer** as tokens (read/write + space
   binding), so there is exactly one enforcement path no matter how
   you arrived.

### First boot

The runtime seeds a default admin — username `root`, password `root` —
with `must_change_password = true`. The workbench login flow refuses
to render anything else until the password is rotated. The REPL boot
panel prints the pointer:

```
Workbench   http://localhost:8002   (login root/root — you'll be asked to change it)
```

Defaults stay safe: the runtime binds localhost unless configured
otherwise, and `ADA_AUTH_REQUIRED=true` remains mandatory for any
non-local deployment.

### Cloud sessions

For hosted spaces, the control plane mints a short-lived,
space-scoped workbench session against the runtime (the user-session
analogue of the space-bound tokens it already mints) and opens the
workbench with it. The control plane never stores the credential;
expiry does the cleanup.

## The REPL and the workbench

Decision (2026-06): the REPL and the workbench carry the **same
command set** — full parity, not a stripped bootstrapper. The terminal
is a first-class management surface for headless/SSH operators who
don't want a browser; the workbench is the same capabilities for
mouse-first/visual work.

The cost is explicit: each capability lives in three places — the MCP
tool (the source of truth) and two thin clients (workbench verb, REPL
command). New capabilities ship to all three. We accept that to keep
one consistent operator vocabulary everywhere.

The REPL additionally owns the bootstrapper role: boot the runtime,
show status/config, print the workbench URL, mint the first token.
