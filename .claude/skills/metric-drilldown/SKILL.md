# Skill: metric-drilldown

## When to use

Use when `ACTION=drill_down` and `CLICKED_CONTEXT` contains a `metric` key.

Parse `CLICKED_CONTEXT` (JSON) to extract `stock_code`, `metric`, and `value`.
`PARENT_PAGE` holds the `request_id` of the page the user drilled from — read it
from `session/page_stack.json` to get `stock_name`.

---

## Step 1 — Identify metric category

| `metric` value | Category |
|---|---|
| `PE_TTM`, `PB`, `PS_TTM` | valuation |
| `ROE`, `gross_margin`, `net_margin` | profitability |
| `revenue`, `net_profit`, `operating_cf` | income |
| `price`, `market_cap` | price |

---

## Step 2 — Fetch data (check data_cache.json first)

| Category | Cache key | Tool |
|---|---|---|
| valuation | `val:<code>` | `get_valuation(code)` |
| valuation | `fin:<code>:annual` | `get_financials(code, period="annual")` |
| profitability | `fin:<code>:annual` | `get_financials(code, period="annual")` |
| income | `fin:<code>:annual` | `get_financials(code, period="annual")` |
| income | `fin:<code>:quarterly` | `get_financials(code, period="quarterly")` |
| price | `kline:<code>:5Y` | `get_kline(code, range="5Y")` |
| all | `peers:<code>:5` | `get_peers(code, n=5)` |

Issue all applicable calls **simultaneously**.

**After results**: write cache via Bash (json.dumps).
Cache keys: `val:*`, `fin:*`, `kline:*`, `peers:*`.

---

## Step 3 — Write output JSON

Write to `output/data-<REQUEST_ID>.json` using Bash + json.dumps.

**Chart dispatch hints** (`metric_category` tells the server which chart to render):
- `"valuation"` → server renders `pe_band_svg` (from `pe_history`) + `peer_bar_svg`
- `"profitability"` or `"income"` → server renders `metric_sparkline_svg` + `peer_bar_svg`
- `"price"` → server renders `kline_svg` (from `kline_bars`)

**`pe_history`**: copy from `get_valuation().pe_history`. Include even if empty.
**`sparkline_values`**: extract the relevant metric column across 5 annual periods,
  oldest first. For `gross_margin` → `gross_margin_pct` from each annual row.
**`kline_bars`**: copy the full `bars` array from `get_kline()`.
**`peer_bar_items`**: include subject + peers. Use the relevant metric value for each.

### JSON schema

```json
{
  "meta": {
    "stock_code": "<code>",
    "stock_name": "<name>",
    "skill": "metric-drilldown",
    "as_of": "<ISO datetime>"
  },
  "hero": {
    "industry": "<sector>",
    "exchange": "<SH|SZ|HK|…>"
  },
  "metric_key": "<e.g. PE_TTM>",
  "metric_display": "<e.g. PE (TTM)>",
  "metric_category": "<valuation|profitability|income|price>",
  "metric_current": <current value or null>,
  "metric_1y_ago": <value 1 year ago or null>,
  "metric_percentile": <integer or null>,
  "pe_history": [{"date": "YYYY-MM-DD", "pe": 0.0}],
  "sparkline_values": [0.0, 0.0, 0.0, 0.0, 0.0],
  "kline_bars": [
    {"date": "YYYY-MM-DD", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0}
  ],
  "peer_bar_metric": "<display label matching metric_key>",
  "peer_bar_items": [
    {"code": "<code>", "name": "<name>", "<peer_bar_metric>": <value or null>}
  ],
  "history_narrative": "<2 paragraphs: current level in historical context + what drove prior extremes>",
  "peer_narrative": "<1 paragraph: who leads, who trails, where subject sits>",
  "related_peers": [
    {"code": "<code>", "name": "<name>"}
  ]
}
```

---

## Step 4 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "drill_down",
     "title": "<name> (<code>) <metric_display>",
     "stock_code": "<code>",
     "stock_name": "<name>",
     "skill_used": "metric-drilldown",
     "summary": "Metric deep-dive: historical chart, peer comparison, narrative",
     "data_keys_used": ["val:<code>", "fin:<code>:annual", "peers:<code>:5"],
     "parent_request_id": "<from CLICKED_CONTEXT or page_stack>",
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
