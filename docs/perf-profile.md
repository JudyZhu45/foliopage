# Foliopage Performance Profile — Step 4.6

**Date:** 2026-04-30  
**Baseline query:** 洋河股份 (002304), action=initial  
**Transcript source:** `~/.foliopage/sessions/sess_*/logs/transcript.jsonl`

---

## 1. Baseline summary

| Operation | Duration (s) | Notes |
|-----------|-------------|-------|
| `initial` — 洋河股份 | **687** | API end-to-end |
| `drill_down` — PE TTM | **458** | API end-to-end |
| `peer_switch` — 五粮液 | **474** | API end-to-end |
| `back` navigation | **0.003** | Disk read, no agent |

---

## 2. Detailed tool-call timing (initial page, 洋河股份)

Wall-clock time extracted from `user` events (tool_results) in transcript.jsonl.  
Gap = time between tool_result and the next tool_use.

| # | Tool | Start (s) | Duration (s) | Gap after (s) | Notes |
|---|------|-----------|-------------|---------------|-------|
| 1 | ToolSearch | 0.0 | 3.2 | 46.0 | First MCP discovery call |
| 2 | ToolSearch | 49.2 | 5.1 | 124.9 | Second MCP discovery call |
| 3 | `get_basic_info` | 179.2 | 1.8 | 12.3 | Stock profile |
| 4 | `get_kline` | 193.3 | 2.1 | 15.2 | 1Y OHLCV |
| 5 | `get_valuation` | 210.6 | 1.6 | 8.4 | PE/PB ratios |
| 6 | `get_financials` | 220.6 | 3.4 | 65.7 | 5-period financials |
| 7 | `get_peers` | 289.7 | 2.6 | 3.8 | 5 peers |
| 8 | `recent_news` | 296.1 | 4.3 | 8.2 | Last 7 days |
| 9 | `kline_svg` | 308.6 | 2.4 | 125.1 | K-line chart SVG |
| 10 | `peer_bar_svg` | 436.1 | 1.8 | 5.7 | Peer bar chart SVG |
| 11 | Bash (write HTML) | 443.6 | 110.5 | — | LLM generating 78KB HTML |

**Transcript total span:** ~463s (tool #1 start to Bash end)  
**API overhead:** ~224s (subprocess startup + MCP init + pre-first-tool LLM planning)  
**API total:** 687s

---

## 3. Time breakdown by category

| Category | Time (s) | % of transcript |
|----------|---------|-----------------|
| ToolSearch (direct) | 8.3 | 1.8% |
| LLM planning after ToolSearch | ~170.9 | 36.9% |
| MCP stock/news data calls (direct) | 15.8 | 3.4% |
| LLM gaps between MCP calls | ~60.3 | 13.0% |
| Chart SVG calls (direct) | 4.2 | 0.9% |
| LLM gap before chart calls | ~125.1 | 27.0% |
| HTML write (Bash) | 110.5 | 23.9% |
| **Total transcript** | **~463** | — |

**Key bottlenecks:**
1. ToolSearch triggers ~204s of wasted work (33.7s direct + ~170s LLM overhead planning around discovery results)
2. HTML composition Bash: 110.5s (LLM emitting 78KB of text)
3. LLM thinking gap before `get_financials` → chart calls: ~125s gap after 2nd ToolSearch

---

## 4. HTML size analysis

| Component | Size | % of total |
|-----------|------|-----------|
| kline_svg chart | ~47 KB | 60% |
| peer_bar_svg chart | ~18 KB | 23% |
| Non-SVG HTML | ~13 KB | 17% |
| **Total** | **~78 KB** | — |

SVG content accounts for 83% of total HTML size. HTML composition time scales with output size.

---

## 5. Optimizations planned

| # | Optimization | Predicted impact | Status |
|---|-------------|-----------------|--------|
| 1 | Pre-list MCP tool signatures in CLAUDE.md | Eliminate ~204s ToolSearch overhead | pending |
| 2 | Parallel independent MCP calls in Phase 3 | Eliminate ~60s sequential gaps | pending |
| 3 | Tighten cache-first enforcement | Save ~16s on drill/peer repeat calls | pending |
| 4 | Reduce SVG chart dimensions | Cut HTML size 30–50%, save ~30–50s compose | pending |
| 5 | LRU cache on chart SVG renders | Eliminate duplicate chart renders on drill | pending |
| 6 | Compress CLAUDE.md overall | Cut Phase 1 read time ~2s | defer |

---

## 6. Benchmark table

| Configuration | initial (s) | drill_down (s) | peer_switch (s) | notes |
|--------------|------------|----------------|-----------------|-------|
| Baseline (Step 4.5) | 687 | 458 | 474 | 2× ToolSearch, sequential MCP calls |
| Opt 1–4 (CLAUDE.md + SVG) | 641 | — | — | ToolSearch still called 3×; parallel batches working |
| Opt 1–5 (+ `--disallowed-tools ToolSearch`) | 657 | — | — | ToolSearch eliminated; same thinking gaps remain |

---

## 7. Root-cause analysis

Detailed timing from `sess_9ed8a743...` (Opt 1–5 run, 657s):

| Segment | Time (s) | % of transcript |
|---------|---------|-----------------|
| Initial planning gap (reads → first MCP call) | 179.6 | 28% |
| search_stock retry thinking | 65.8 | 10% |
| Between-batch gap (financials → peers) | 67.2 | 11% |
| Post-news → chart gap | 147.8 | 23% |
| HTML composition (Bash, LLM generating ~72KB) | 99.0 | 16% |
| **Total LLM reasoning time** | **~559** | **87%** |
| Actual tool execution (MCP calls + reads + writes) | ~34 | 5% |
| Subprocess / API overhead | ~17 | 3% |

**Conclusion:** LLM reasoning time accounts for 87% of wall-clock time. Optimizing MCP overhead (tool discovery, call parallelism, SVG size) addresses only the remaining 8%. The 90–120s target requires a fundamentally different approach.

---

## 8. What worked vs. what didn't

| Optimization | Predicted impact | Actual impact | Verdict |
|-------------|-----------------|---------------|---------|
| Opt 1: MCP tool signatures in CLAUDE.md | −200s (eliminate ToolSearch overhead) | ~0s (ToolSearch was within the baseline planning gap, not additive) | ❌ Wrong model |
| Opt 2: Parallel call instruction | −60s | Partial — agent calls in 2 parallel batches (4+2) but can't be forced to one batch | ⚠️ Partial |
| Opt 3: Cache enforcement | −16s on drill/peer | Not measured separately | — |
| Opt 4: SVG dimensions 640→480 | −25s HTML write | HTML shrank 8% (78KB→72KB); thinking gap dominates so net ~0s | ❌ Wrong model |
| Opt 5: `--disallowed-tools ToolSearch` | −34s direct + overhead | No benefit — agent spends same thinking time regardless | ❌ |
| Opt 6: Compress CLAUDE.md | −5s | Deferred; negligible vs 559s thinking gap | — |

---

## 9. Path to <120s (architectural changes required)

The 90–120s target requires addressing the 87% thinking overhead:

1. **Streaming HTML generation**: Stream the agent's output to the client as it's produced, so the user sees content before the 640s total elapses. No latency reduction but perceived latency drops dramatically.
2. **Pre-fetch data in orchestrator**: Orchestrator calls stock/news MCP tools directly before spawning the agent. Agent receives pre-loaded data as JSON in the prompt, skipping Phases 1–3 entirely. Would save ~150–200s.
3. **Two-phase architecture**: Phase 1 = data agent (fast, structured output); Phase 2 = HTML template (deterministic Jinja, no LLM). Would reduce agent task to data collection only (~200s).
4. **Lighter model for HTML**: Use Haiku for HTML composition (99s of Sonnet → ~20s of Haiku) while keeping Sonnet for analysis. Estimated saving: 70–80s.

These are Step 5+ architectural changes.
