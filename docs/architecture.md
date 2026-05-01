# Foliopage Architecture

**Audience:** Contributors and curious developers who want to understand how the
system is put together before making changes.

---

## 1. High-level overview

```
Browser (index.html / report.html)
        │ HTTP POST /api/generate
        ▼
┌─────────────────────────────┐
│  Orchestrator (FastAPI)     │  orchestrator/server.py
│  • Session management       │
│  • Page-level HTML cache    │
│  • Concurrency semaphore    │
└───────────────┬─────────────┘
                │ subprocess  claude -p
                ▼
┌─────────────────────────────┐
│  Research Agent             │  claude CLI (your local subscription)
│  • Reads CLAUDE.md          │
│  • Calls MCP tools          │
│  • Writes HTML to disk      │
└──────┬────────┬─────────────┘
       │ stdio  │ stdio
   ┌───┘    ┌───┘
   ▼        ▼
stock_mcp  chart_mcp  news_mcp     tools/*/server.py
(akshare)  (matplotlib) (akshare)
```

**Request lifecycle (happy path):**

1. User types a query in the browser.
2. Browser POSTs to `POST /api/generate` on the FastAPI orchestrator.
3. Orchestrator checks the page-level HTML cache (30-minute TTL). Cache hit → return instantly.
4. Cache miss: orchestrator creates a session workspace, spawns a `claude -p` subprocess.
5. The subprocess reads `CLAUDE.md` from the workspace, loads the relevant skill file,
   calls MCP tools to fetch data and generate charts, then writes one HTML file to
   `output/page-<request_id>.html`.
6. Orchestrator reads the HTML, caches it, and returns it in the API response.
7. Browser renders the HTML in an iframe; click events on drillable elements are
   intercepted by `report.html` and fire new `POST /api/generate` calls.

---

## 2. Layer-by-layer description

### Layer 1 — Browser shell (`shell/`)

Two static HTML pages with vanilla JS. No framework, no build step.

- `index.html` — search homepage. Submits a query, navigates to `/report`.
- `report.html` — research dashboard. Hosts the generated page in an iframe,
  manages a client-side breadcrumb stack, handles `postMessage` from the iframe
  for drilldown and peer-switch navigation.

**Why vanilla JS?** The generated pages are self-contained HTML. There is no shared
state or routing between them. A full SPA framework would add complexity without
benefit.

### Layer 2 — Orchestrator (`orchestrator/`)

FastAPI application with five components:

| Module | Responsibility |
|--------|---------------|
| `server.py` | Route handlers, page cache, error pages |
| `session.py` | Session workspace lifecycle, page stack management |
| `agent_runner.py` | Subprocess spawn (NeuriCo pattern) |
| `prompts.py` | Prompt builders for the three action types |
| `config.py` | Environment-based configuration |
| `errors.py` | Custom exception hierarchy |
| `security.py` | Credential redaction in error messages |

**Why FastAPI + subprocess (NeuriCo pattern)?** The Claude CLI (`claude -p`) is
the most capable way to invoke Claude Code locally — it resolves MCP tool
configurations, manages context windows, and handles the full agent loop. A
direct API call would lose MCP tool support and require reimplementing the
agent control loop.

**Why a semaphore?** Agent runs are CPU/IO-heavy. The semaphore
(`FOLIOPAGE_MAX_CONCURRENT`, default 3) prevents the machine from being
overloaded by parallel requests.

### Layer 3 — Research agent (CLAUDE.md + skills)

The `claude -p` subprocess reads `CLAUDE.md` (symlinked into the session
workspace) as its system-level instructions. `CLAUDE.md` defines a 5-phase
workflow:

1. Read context (page stack, data cache)
2. Load skill file
3. Fetch data via MCP tools (with 30-minute data cache)
4. Generate SVG charts via chart MCP
5. Write HTML, update page stack and data cache

Skill files (`.claude/skills/<name>/SKILL.md`) are action-specific recipes
that specify: which data to fetch, which charts to produce, and what sections
the page should contain. Adding a new page type means adding a skill file —
no orchestrator code changes needed.

**Why CLAUDE.md + skills rather than one big prompt?** The multi-file approach
keeps individual files at a readable length and allows skills to be developed
and tested independently. The orchestrator doesn't need to know the structure of
the research page — that knowledge lives in the skill.

**Why one HTML file per request?** Each request produces a fully self-contained
HTML page with inline SVG and linked CSS. This makes pages:
- Directly saveable/shareable (right-click → Save As)
- Renderable without a running server (open the file directly)
- Simple to cache (just a file on disk)

### Layer 4 — MCP tool servers (`tools/`)

Three stdio-transport MCP servers:

| Server | Data source | Key tools |
|--------|------------|-----------|
| `stock_mcp` | akshare (A-shares), yfinance (US) | `get_basic_info`, `get_kline`, `get_financials`, `get_valuation`, `get_peers`, `search_stock` |
| `chart_mcp` | matplotlib | `kline_svg`, `peer_bar_svg`, `pe_band_svg`, `metric_sparkline_svg`, `comparison_radar_svg` |
| `news_mcp` | akshare | `recent_news`, `recent_announcements`, `analyst_consensus` |
| `cache_mcp` | SQLite (`~/.foliopage/cache.db`) | `cache_get`, `cache_set`, `cache_delete`, `cache_list` |

Each MCP server runs as a subprocess of the Claude agent, communicating via
stdin/stdout JSON-RPC. They are registered in `.mcp.json` at repo root, which is
symlinked into each session workspace so the agent can discover them.

**Why local MCP servers?** The agent runs your local Claude subscription — no API
key is needed. MCP tools run in the same machine context, making them fast
(no network hop) and keeping data local.

### Layer 5 — Session workspace (`~/.foliopage/sessions/<sess_id>/`)

```
sess_<hex>/
  session/
    page_stack.json      ← written by agent: history of pages generated
    data_cache.json      ← written by agent: raw MCP data, 30-min TTL
  output/
    page-<req_id>.html   ← written by agent: the generated research page
  logs/
    transcript.jsonl     ← written by orchestrator: full agent transcript
  CLAUDE.md              → symlink to repo CLAUDE.md
  .claude/               → symlink to repo .claude/
  .mcp.json              → symlink to repo .mcp.json   ← CRITICAL
  static/                → symlink to repo shell/static/
```

**Why symlinks?** The session workspace is the agent's working directory. Claude
Code discovers `CLAUDE.md` and `.mcp.json` by looking in the current directory.
Symlinking ensures the agent always uses the current repo's instructions and MCP
configuration without copying files.

---

## 3. Data contracts

### `session/page_stack.json`

Array of objects appended by the agent on each request:

```json
{
  "request_id": "req_abc123",
  "action": "initial",
  "title": "贵州茅台 (600519) 总览",
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "skill_used": "stock-overview",
  "summary": "Hero metrics, 1Y K-line, 5Y financials, peer table, news",
  "data_keys_used": ["basic:600519", "kline:600519:1Y"],
  "parent_request_id": null,
  "created_at": "2026-04-30T15:00:00Z"
}
```

### `session/data_cache.json`

Flat dict of `cache_key → {as_of, data}` where `as_of` is ISO-8601 and `data`
is the raw MCP tool response. The agent checks this before calling an MCP tool
and uses the cached value if it is less than 30 minutes old.

```json
{
  "basic:600519": { "as_of": "2026-04-30T15:00:00", "data": { "name": "贵州茅台", ... } },
  "kline:600519:1Y": { "as_of": "2026-04-30T15:00:00", "data": [...] }
}
```

### Drillable HTML elements (`data-flipbook-*`)

Every interactive element in a generated page carries two data attributes:

```html
<div data-flipbook-action="drill_down"
     data-flipbook-context='{"clicked_topic":"PE TTM","stock_code":"600519","metric":"PE_TTM","value":28.3}'>
```

`report.html` intercepts clicks via `postMessage` from the iframe, reads these
attributes, and calls `POST /api/generate` with the corresponding action and
context. The agent never receives raw click events — only structured context dicts.

---

## 4. Key design decisions with rationale

### No streaming output

The agent writes a complete, self-contained HTML page and only then signals
`PAGE_READY:`. Streaming partial HTML would require the browser to handle
incremental updates to a document being assembled in real time, significantly
complicating the frontend and the skill logic. The tradeoff is an apparent
blank-screen wait of ~10 minutes on first generation; the page cache (30-minute
TTL) makes repeat queries instant.

### Local CLI, not API key

Using `claude -p` (your existing Claude Code subscription) instead of
`ANTHROPIC_API_KEY` + direct API calls:
- Zero additional cost to the user beyond their subscription
- MCP tool support comes for free (the CLI handles tool dispatch)
- The agent's context window management, retry logic, and tool-use loop are
  handled by the CLI — not reimplemented here

### One HTML per request

Each research page is a standalone file with no external dependencies beyond the
hosted `foliopage.css`. Benefits: trivially cacheable on disk, directly openable
without a server, easy to share (email the file). Cost: no incremental updates or
live data refresh.

### CLAUDE.md + skill files

Rather than embedding all agent instructions in a single prompt string, the
instructions live in version-controlled Markdown files that the agent reads as
its first step. This means:
- Instructions can be reviewed and tested in isolation
- Adding a new page type (skill) does not require touching orchestrator code
- The agent's behavior is auditable by reading the files, not by reading Python

---

## 5. Performance characteristics

See `docs/perf-profile.md` for a full profiling breakdown. The short version:

| Operation | Duration |
|-----------|---------|
| Initial page (cold cache) | ~10–11 min |
| Drill-down | ~7–8 min |
| Peer switch | ~7–8 min |
| Any operation (warm page cache, <30 min) | < 100ms |
| Back navigation | < 5ms |

87% of generation time is LLM reasoning (thinking about how to structure the
research). The remaining 13% is MCP tool calls and disk I/O. Reaching the
90-second target requires architectural changes (v0.2 roadmap).
