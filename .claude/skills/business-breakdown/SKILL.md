# Skill: business-breakdown

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=business_breakdown`.

---

## Step 1 — Resolve stock

Read `CLICKED_CONTEXT` for `stock_code` and `stock_name`.

---

## Step 2 — Fetch data

Issue **all 4 calls simultaneously in one turn**. Tool servers cache results
to disk automatically — do not read or write `data_cache.json`.

| Tool call |
|---|
| `get_basic_info(code)` |
| `get_revenue_breakdown(code)` |
| `get_financials(code, period="annual")` |
| `get_peers(code, n=6)` |

If `revbk` returns `available: false`, set `"available": false` in the JSON
and skip all product/region fields. The renderer will show an unavailability notice.

---

## Step 3 — Write output JSON

Write to `output/data-<REQUEST_ID>.json` using Bash + json.dumps.

**Never invent numbers** — every value must come from a tool result or be `null`.

**`peer_bar_items`**: include subject + top 5 peers from `get_peers`. Use
`gross_margin_pct` from latest annual financials. If a peer has no margin data,
set the metric value to `null` (server skips nulls gracefully).

### JSON schema

```json
{
  "meta": {"stock_code": "<code>", "stock_name": "<name>", "skill": "business-breakdown", "as_of": "<ISO datetime>"},
  "hero": {"industry": "<sector>", "exchange": "<SH|SZ|HK|…>", "as_of": "<date>"},
  "available": true,
  "report_year": null,
  "business_overview": "<150-200 words: what sold, who buys, pricing drivers. ≥1 [[code|name]] link>",
  "by_product": [{"segment": "<name>", "revenue_yi": null, "revenue_pct": null, "gross_margin_pct": null, "yoy_pct": null}],
  "by_region": [{"region": "<name>", "revenue_yi": null, "revenue_pct": null, "yoy_pct": null}],
  "top_segment": "<largest segment name>",
  "top_segment_pct": null,
  "peer_bar_metric": "毛利率(%)",
  "peer_bar_items": [{"code": "<code>", "name": "<name>", "毛利率(%)": null}],
  "structural_analysis": "<3-4 paragraphs \\n\\n: concentration risk, margin mix, growth engine. ≥2 [[code|name]] links>",
  "pull_quote": "<striking segment data point>"
}
```

---

## Step 4 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "drill_down",
     "title": "<name> (<code>) 业务拆解",
     "stock_code": "<code>",
     "stock_name": "<name>",
     "skill_used": "business-breakdown",
     "summary": "Revenue breakdown by product and region, peer margin comparison",
     "data_keys_used": ["basic:<code>", "fin:<code>:annual", "peers:<code>:6"],
     "parent_request_id": "<from CLICKED_CONTEXT or page_stack>",
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
