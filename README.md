# Foliopage

[简体中文 →](README.zh-CN.md)

> Local-first stock research in your browser, powered by your own Claude Code subscription.

Type a ticker. Get a self-contained HTML research page with K-line, fundamentals, valuation, peer comparison, and news. Every metric and peer is a link that generates the next page on the fly. No SaaS account. No API keys. Pages are served locally.

---

## Demo

```bash
$ make dev
# Open http://localhost:8000
# Type: AAPL
# Wait 5–10 min on the first cold run
# → Self-contained HTML: K-line chart, 14 KPI tiles, 5-year financials,
#   peer table, news timeline, drill-down cards
# Click any peer or metric → next page generates automatically
```

The same query returns in under 100 ms within the 30-minute page-cache window. Subsequent queries on related tickers (same industry, overlapping peers) finish in 3–5 minutes because basic info, peer lists, and K-line data are reused from a persistent on-disk cache.

---

## Quickstart

**Prerequisites:** Python 3.11+, [uv](https://docs.astral.sh/uv/), and an active [Claude Code](https://claude.ai/code) subscription with the CLI installed (`claude --version` should work).

```bash
git clone https://github.com/JudyZhu45/foliopage.git
cd foliopage

# Install dependencies and write .mcp.json for this machine
make install

# Start the server
make dev
```

Open [http://localhost:8000](http://localhost:8000) and type a ticker or company name.

### Supported queries

| Query style          | Example          |
|----------------------|------------------|
| US ticker            | `AAPL`           |
| US company name      | `Apple`          |
| A-share code         | `600519`         |
| A-share company name | (see Chinese README) |

US data comes from yfinance plus selected akshare US endpoints. A-share data comes from akshare's Sina / SSE / SZE / East Money sources.

---

## Architecture

```
Browser (index.html / report.html)
        │ HTTP POST /api/generate
        ▼
┌─────────────────────────────┐
│  Orchestrator (FastAPI)     │  orchestrator/server.py
│  • Page-level HTML cache    │
│  • Session management       │
│  • Concurrency semaphore    │
│  • Live progress endpoint   │
└───────────────┬─────────────┘
                │ subprocess: claude -p
                ▼
┌─────────────────────────────┐
│  Research Agent             │  claude CLI (your local subscription)
│  • Reads CLAUDE.md          │
│  • Calls MCP tools          │
│  • Writes data-<id>.json    │
└──────┬────────┬─────────────┘
       │ stdio  │ stdio
   ┌───┘    ┌───┘
   ▼        ▼
stock_mcp  chart_mcp  news_mcp  cache_mcp
(akshare,  (matplotlib  (akshare, (SQLite KV,
 yfinance)  → SVG)       feedparser) ~/.foliopage/cache.db)
```

The agent emits structured JSON; the orchestrator renders it to HTML server-side (using Python helpers, not the agent) and inlines the SVG charts. The agent never writes HTML.

Full design rationale lives in [`docs/architecture.md`](docs/architecture.md).

---

## Configuration

All settings come from environment variables (or a `.env` file at the repo root).

| Variable                       | Default                          | Description                          |
|--------------------------------|----------------------------------|--------------------------------------|
| `FOLIOPAGE_HOST`               | `127.0.0.1`                      | Bind address                         |
| `FOLIOPAGE_PORT`               | `8000`                           | Listen port                          |
| `FOLIOPAGE_MAX_CONCURRENT`     | `3`                              | Max parallel agent runs              |
| `FOLIOPAGE_AGENT_TIMEOUT`      | `1800`                           | Agent timeout in seconds             |
| `FOLIOPAGE_PAGE_CACHE_TTL`     | `1800`                           | Page-cache TTL in seconds (0 = off)  |
| `FOLIOPAGE_PAGE_CACHE_ROOT`    | `~/.foliopage/page_cache`        | Page-cache directory                 |
| `FOLIOPAGE_SESSION_ROOT`       | `~/.foliopage/sessions`          | Session workspace root               |
| `FOLIOPAGE_CACHE_DB`           | `~/.foliopage/cache.db`          | SQLite cache path (shared by MCPs)   |
| `FOLIOPAGE_LOG_LEVEL`          | `INFO`                           | Logging level                        |
| `FOLIOPAGE_CLAUDE_BIN`         | `claude`                         | Path to the Claude CLI binary        |

---

## Performance

| Scenario                                              | Typical |
|-------------------------------------------------------|---------|
| Cold initial research (no cache hits)                 | 5–10 min |
| Same query within 30 min                              | < 100 ms (page cache) |
| Different ticker, same industry (peers reused)        | 3–5 min |
| Drill-down (valuation, peer comparison, etc.)         | 2–5 min |

Bottlenecks and the optimization history are in [`docs/perf-profile.md`](docs/perf-profile.md).

---

## Reliability

The agent talks to free upstream sources (akshare, yfinance, Google News RSS) that occasionally rate-limit or silently drop connections. The orchestrator handles this:

- **60-second socket timeout** on every upstream call. Without it, a TCP connection accepted but never answered hangs the worker indefinitely.
- **East Money circuit breaker.** When EM rate-limits, the first failure trips a 3-minute cooldown — subsequent EM calls fail-fast instead of each waiting out their own retry budget. Other sources (Sina / SSE / SZE / yfinance) keep working in degraded mode (e.g. industry name = empty, peers list = empty, page still renders).
- **Live progress display.** While research runs, the loading card shows the agent's current phase, the list of completed and in-flight tool calls, a rate-limit banner if the seven-day window is tripped, and a freshness counter that turns red when no transcript event has arrived for 30 seconds.
- **Frontend self-rescue.** If `uvicorn --reload` kills the `/api/generate` worker mid-run (a common dev-mode failure mode), progress polling detects `status=done` and loads the finished report directly from the session, so the UI doesn't get stuck on a forever-pending fetch.

---

## Troubleshooting

**The page never appears / spinner runs forever**

- Look at the live progress block in the loading card — completed tool calls, time since last event, rate-limit warning. If "UPDATED 60s+ AGO" stays red for several minutes, the agent really has stalled.
- The agent transcript is at `~/.foliopage/sessions/<sess_id>/logs/transcript.jsonl`.
- A first-time cold run on a brand-new ticker can take up to 10 minutes.

**`claude: command not found`**

Install the Claude CLI and ensure it is on your `PATH`:

```bash
which claude    # should print a path
claude --version
```

**`Error: virtual environment not found`**

Run `make install` before `make dev`.

**`make test` fails with import errors**

Run `uv sync --all-extras` to install dev dependencies, then retry.

**Data shows "数据暂不可用" (data unavailable)**

The upstream returned an error or the East Money circuit breaker tripped. The page renders with the available data; retry the same query in a few minutes once the cooldown clears, or drill into a different metric whose data source is still healthy.

---

## Disclaimer

All research pages produced by Foliopage are generated by an AI model and are provided for informational and research purposes only. They do not constitute investment advice. Always verify data with authoritative sources before making any financial decision.

---

## Roadmap

| Version | Goal                                                |
|---------|-----------------------------------------------------|
| v0.1 (current) | End-to-end pipeline, local-only, JSON-rendered |
| v0.2    | Capital flow / sentiment / event-timeline drill-downs |
| v0.3    | Background task queue + browser notifications      |
| v0.4    | Watchlist and portfolio overlay                    |

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Acknowledgments

- [akshare](https://akshare.akfamily.xyz/) — free A-share and ETF data
- [yfinance](https://github.com/ranaroussi/yfinance) — US equity data
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Claude Code](https://claude.ai/code) — the agent that does the research
