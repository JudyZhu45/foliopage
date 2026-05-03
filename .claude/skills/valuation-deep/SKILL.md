# Skill: valuation-deep

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=valuation_deep`
(triggered by the "估值三角" card in the Drill Deeper section).

---

## Step 1 — Resolve stock

Read `CLICKED_CONTEXT` for `stock_code` and `stock_name`.

---

## Step 2 — Fetch data

Issue **all 6 calls simultaneously in one turn** (never call these one at a
time). Tool servers cache results to disk automatically — do not maintain
`data_cache.json`.

| Tool call |
|---|
| `get_basic_info(code)` |
| `get_valuation(code)` |
| `get_kline(code, range="5Y")` |
| `get_financials(code, period="annual")` |
| `get_peers(code, n=10)` |
| `analyst_consensus(code)` |

`val:<code>` data now includes `pe_history` — a list of `{date, pe}` dicts.
Copy it verbatim into the JSON output (see schema below).

---

## Step 3 — Write output JSON

Write the following JSON to `output/data-<REQUEST_ID>.json` using the Bash tool
with Python's `json.dumps` to ensure correct escaping:

```bash
python3 << 'PYEOF'
import json, pathlib
data = {
    # ... full dict below ...
}
pathlib.Path("output/data-<REQUEST_ID>.json").write_text(
    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
)
PYEOF
```

**`pe_history` is mandatory.** Copy the full list from `get_valuation().pe_history`
verbatim. The server uses it to render the PE band chart. Set to `[]` if unavailable.

**Peer link markup:** in `valuation_snapshot`, `pe_band_narrative`, `peer_narrative`,
and `valuation_narrative`, wrap peer company names as `[[stock_code|display_name]]`.
Use this markup for **≥3 company name mentions** across all narrative fields.

**Numerical precision:** 2 decimal places for ratios; 1 decimal for large values.
**Never invent numbers** — every value must come from a tool result or be `null`.

### JSON schema

```json
{
  "meta": {
    "stock_code": "<code>",
    "stock_name": "<name>",
    "skill": "valuation-deep",
    "as_of": "<ISO datetime from basic_info>"
  },
  "hero": {
    "industry": "<sector from basic_info>",
    "exchange": "<SH|SZ|HK|…>",
    "as_of": "<date string>"
  },
  "kpi": {
    "pe_ttm": <or null>,
    "pe_percentile": <integer or null>,
    "pb": <or null>,
    "ev_ebitda": <or null>,
    "dividend_yield_pct": <or null>,
    "roe_pct": <or null>,
    "as_of": "<date string>"
  },
  "pe_history": [
    {"date": "YYYY-MM-DD", "pe": 28.3}
  ],
  "peer_bar_metric": "PE(TTM)",
  "peer_bar_items": [
    {"code": "<code>", "name": "<name>", "PE(TTM)": <pe_ttm or null>}
  ],
  "radar_subject": {
    "code": "<code>",
    "name": "<name>",
    "pe": <pe_ttm or null>,
    "pb": <pb or null>,
    "ev_ebitda": <or null>,
    "roe": <roe_pct or null>,
    "gross_margin": <gross_margin_pct or null>
  },
  "radar_peers": [
    {
      "code": "<code>",
      "name": "<name>",
      "pe": <or null>,
      "pb": <or null>,
      "ev_ebitda": <or null>,
      "roe": <or null>,
      "gross_margin": <or null>
    }
  ],
  "radar_metrics": ["pe", "pb", "ev_ebitda", "roe", "gross_margin"],
  "valuation_snapshot": "<2-3 sentences about current valuation level, ≥1 [[code|name]] link>",
  "pe_band_narrative": "<2-3 sentences: where current PE sits vs historical range, notable peaks/troughs>",
  "peers": [
    {
      "code": "<code>",
      "name": "<name>",
      "pe_ttm": <or null>,
      "pb": <or null>,
      "ev_ebitda": <or null>,
      "roe_pct": <or null>,
      "gross_margin_pct": <or null>
    }
  ],
  "peer_narrative": "<2-3 sentences, premium/discount rationale, ≥2 [[code|name]] links>",
  "implied_growth_rate": <float or null>,
  "implied_growth_note": "<one sentence showing Gordon/DDM formula transparently, label as inferred>",
  "analyst_target_low": <float or null>,
  "analyst_target_high": <float or null>,
  "analyst_count": <int or null>,
  "valuation_narrative": "<4 paragraphs separated by \\n\\n: PE percentile vs business quality, analyst range vs implied growth, key risk to valuation, overall assessment. ≥2 [[code|name]] links>",
  "pull_quote": "<single most striking valuation data point>"
}
```

---

## Step 4 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "drill_down",
     "title": "<name> (<code>) 估值深度",
     "stock_code": "<code>",
     "stock_name": "<name>",
     "skill_used": "valuation-deep",
     "summary": "4-section valuation: KPI, PE band, peer comparison, narrative",
     "data_keys_used": ["basic:<code>", "val:<code>", "fin:<code>:annual", "peers:<code>:10"],
     "parent_request_id": "<PARENT_REQUEST_ID from CLICKED_CONTEXT or page_stack>",
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
