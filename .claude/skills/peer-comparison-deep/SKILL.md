# Skill: peer-comparison-deep

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=peer_comparison_deep`.

---

## Step 1 — Resolve stock

Read `CLICKED_CONTEXT` for `stock_code` and `stock_name`. This is the **subject**.

---

## Step 2 — Fetch data

Tool servers cache results to disk automatically — do not maintain
`data_cache.json`.

**Batch A** — all simultaneous in one turn:

| Tool call |
|---|
| `get_basic_info(code)` |
| `get_valuation(code)` |
| `get_financials(code, period="annual")` |
| `get_peers(code, n=10)` |

**Batch B** — apply hybrid peer selection (same as stock-overview Step 3) to
identify top 5 verified peers. Then for each selected peer, fetch in parallel:

| Tool call |
|---|
| `get_basic_info(peer_code)` |
| `get_valuation(peer_code)` |
| `get_financials(peer_code, period="annual")` |

If any peer tool returns an error: use `null` for missing fields — do not drop the peer.

---

## Step 3 — Write output JSON

Write to `output/data-<REQUEST_ID>.json` using Bash + json.dumps.

**Never invent numbers.** All metric values must come from tool results or be `null`.

**Positioning matrix**: classify each company (subject + peers) into one of four
quadrants based on `gross_margin_pct` vs `revenue_cagr_3y` relative to peer median:
- High margin + High growth: "优质成长"
- High margin + Low growth: "价值防御"
- Low margin + High growth: "规模扩张"
- Low margin + Low growth: "效率改善"

**`revenue_cagr_3y`**: compute from annual financials (3-year CAGR).

### JSON schema

```json
{
  "meta": {
    "stock_code": "<code>",
    "stock_name": "<name>",
    "skill": "peer-comparison-deep",
    "as_of": "<ISO datetime>"
  },
  "hero": {
    "industry": "<sector>",
    "exchange": "<SH|SZ|HK|…>",
    "peer_count": <int>
  },
  "subject": {
    "code": "<code>",
    "name": "<name>",
    "market_cap_yi": <亿元 or null>,
    "pe_ttm": <or null>,
    "pb": <or null>,
    "ev_ebitda": <or null>,
    "gross_margin_pct": <or null>,
    "net_margin_pct": <or null>,
    "roe_pct": <or null>,
    "revenue_cagr_3y": <% or null>
  },
  "peers": [
    {
      "code": "<code>",
      "name": "<name>",
      "market_cap_yi": <or null>,
      "pe_ttm": <or null>,
      "pb": <or null>,
      "ev_ebitda": <or null>,
      "gross_margin_pct": <or null>,
      "net_margin_pct": <or null>,
      "roe_pct": <or null>,
      "revenue_cagr_3y": <% or null>
    }
  ],
  "radar_subject": {
    "code": "<code>",
    "name": "<name>",
    "pe": <or null>,
    "pb": <or null>,
    "gross_margin": <or null>,
    "roe": <or null>,
    "revenue_cagr_3y": <or null>
  },
  "radar_peers": [...],
  "radar_metrics": ["pe", "pb", "gross_margin", "roe", "revenue_cagr_3y"],
  "bar_metric_1": "毛利率(%)",
  "bar_items_1": [
    {"code": "<code>", "name": "<name>", "毛利率(%)": <gross_margin_pct or null>}
  ],
  "bar_metric_2": "ROE(%)",
  "bar_items_2": [
    {"code": "<code>", "name": "<name>", "ROE(%)": <roe_pct or null>}
  ],
  "positioning_matrix": [
    {
      "code": "<code>",
      "name": "<name>",
      "quadrant": "优质成长|价值防御|规模扩张|效率改善",
      "note": "<one sentence why>"
    }
  ],
  "competitive_analysis": "<4-5 paragraphs separated by \\n\\n: strengths vs peer median, most similar peer, biggest valuation gap, overall assessment. ≥3 [[code|name]] links>",
  "pull_quote": "<sharpest cross-peer contrast>"
}
```

---

## Step 4 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "drill_down",
     "title": "<name> (<code>) 同行对比",
     "stock_code": "<code>",
     "stock_name": "<name>",
     "skill_used": "peer-comparison-deep",
     "summary": "Multi-metric peer comparison: radar, bar charts, positioning matrix",
     "data_keys_used": ["basic:<code>", "val:<code>", "fin:<code>:annual", "peers:<code>:10"],
     "parent_request_id": "<from CLICKED_CONTEXT or page_stack>",
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
