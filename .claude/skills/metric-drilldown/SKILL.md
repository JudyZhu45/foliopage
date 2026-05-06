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

## Step 2 — Fetch data

Tool servers cache results to disk automatically — do not maintain
`data_cache.json`. Issue all applicable calls **simultaneously in one turn**.

| Category | Tool call |
|---|---|
| valuation | `get_valuation(code)` |
| valuation | `get_financials(code, period="annual")` |
| profitability | `get_financials(code, period="annual")` |
| income | `get_financials(code, period="annual")` |
| income | `get_financials(code, period="quarterly")` |
| all | `get_peers(code, n=5)` |

---

## Step 3 — Write output JSON

Use the **Write tool** to write a Python script `gen_json.py`, then run it:
```bash
python3 gen_json.py && rm gen_json.py && echo "DONE"
```
The script must use `json.dumps(data, ensure_ascii=False, indent=2)` and write to
`output/data-<REQUEST_ID>.json`.

**Chart dispatch hints** (`metric_category` tells the server which chart to render):
- `"valuation"` → server renders `pe_band_svg` (from `pe_history`) + `peer_bar_svg`
- `"profitability"` or `"income"` → server renders `metric_sparkline_svg` + `peer_bar_svg`
- `"price"` → server renders `kline_svg` (fetched directly from cache — no `kline_bars` needed)

**`pe_history`**: copy from `get_valuation().pe_history`. Include even if empty.
**`sparkline_values`**: extract the relevant metric column across 5 annual periods,
  oldest first. For `gross_margin` → `gross_margin_pct` from each annual row.
**`peer_bar_items`**: include subject + peers. Use the relevant metric value for each.

### JSON schema

```json
{
  "meta": {"stock_code": "<code>", "stock_name": "<name>", "skill": "metric-drilldown", "as_of": "<ISO datetime>"},
  "hero": {"industry": "<sector>", "exchange": "<SH|SZ|HK|…>"},
  "metric_key": "<e.g. PE_TTM>",
  "metric_display": "<e.g. PE (TTM)>",
  "metric_category": "<valuation|profitability|income|price>",
  "metric_current": null, "metric_1y_ago": null, "metric_percentile": null,
  "pe_history": [{"date": "YYYY-MM-DD", "pe": 0.0}],
  "sparkline_values": [0.0, 0.0, 0.0, 0.0, 0.0],
  "peer_bar_metric": "<display label>",
  "peer_bar_items": [{"code": "<code>", "name": "<name>", "<metric>": null}],
  "history_narrative": "<2 paragraphs: historical context + prior extremes>",
  "peer_narrative": "<1 paragraph: who leads, who trails, where subject sits>",
  "related_peers": [{"code": "<code>", "name": "<name>"}]
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
