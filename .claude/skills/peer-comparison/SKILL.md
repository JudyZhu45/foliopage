# Skill: peer-comparison

## When to use

Use when `ACTION=peer_switch` **and** there is already a subject stock in the
page stack — i.e., the user is comparing the clicked peer against the original
stock. Or when `ACTION=initial` and `STOCK_QUERY` implies a comparison
(e.g. "茅台 vs 五粮液").

- **peer_switch**: `CLICKED_CONTEXT` supplies `stock_code`/`stock_name` for
  the peer. Load the parent page's stock from `session/page_stack.json` as
  the subject.
- **compare query**: parse both codes from `STOCK_QUERY`. The first is subject.

---

## Step 1 — Resolve both codes

For any code that is a name (not a digit string or known ticker):
```
search_stock(query=<name>)
```

Variables after this step: `subject_code`, `subject_name`, `peer_code`, `peer_name`.

---

## Step 2 — Fetch data

Issue all **6 calls simultaneously in one turn**. Tool servers cache results
to disk automatically — do not maintain `data_cache.json`.

| Tool call |
|---|
| `get_basic_info(subject_code)` |
| `get_valuation(subject_code)` |
| `get_financials(subject_code, period="annual")` |
| `get_basic_info(peer_code)` |
| `get_valuation(peer_code)` |
| `get_financials(peer_code, period="annual")` |

---

## Step 3 — Write output JSON

Write to `output/data-<REQUEST_ID>.json` using Bash + json.dumps.

**Omit any radar metric where BOTH stocks have `null`** — don't plot empty axes.
**`comparison_table`**: one row per metric, ordered by importance.

### JSON schema

```json
{
  "meta": {
    "skill": "peer-comparison",
    "as_of": "<ISO datetime>"
  },
  "subject": {
    "code": "<code>",
    "name": "<name>",
    "industry": "<sector>",
    "exchange": "<SH|SZ|…>",
    "market_cap_yi": <亿元 or null>,
    "pe_ttm": <or null>,
    "pb": <or null>,
    "roe_pct": <or null>,
    "gross_margin_pct": <or null>,
    "net_margin_pct": <or null>,
    "revenue_yoy_pct": <% latest annual or null>
  },
  "peer": {
    "code": "<code>",
    "name": "<name>",
    "industry": "<sector>",
    "exchange": "<SH|SZ|…>",
    "market_cap_yi": <亿元 or null>,
    "pe_ttm": <or null>,
    "pb": <or null>,
    "roe_pct": <or null>,
    "gross_margin_pct": <or null>,
    "net_margin_pct": <or null>,
    "revenue_yoy_pct": <% or null>
  },
  "radar_subject": {
    "code": "<code>",
    "name": "<name>",
    "PE": <pe_ttm or null>,
    "PB": <pb or null>,
    "ROE": <roe_pct or null>,
    "gross_margin": <gross_margin_pct or null>,
    "net_margin": <net_margin_pct or null>
  },
  "radar_peer": {
    "code": "<code>",
    "name": "<name>",
    "PE": <or null>,
    "PB": <or null>,
    "ROE": <or null>,
    "gross_margin": <or null>,
    "net_margin": <or null>
  },
  "radar_metrics": ["PE", "PB", "ROE", "gross_margin", "net_margin"],
  "comparison_table": [
    {"metric": "PE (TTM)", "subject_value": "<formatted>", "peer_value": "<formatted>"},
    {"metric": "PB", "subject_value": "...", "peer_value": "..."},
    {"metric": "ROE (%)", "subject_value": "...", "peer_value": "..."},
    {"metric": "毛利率 (%)", "subject_value": "...", "peer_value": "..."},
    {"metric": "净利率 (%)", "subject_value": "...", "peer_value": "..."},
    {"metric": "市值 (亿元)", "subject_value": "...", "peer_value": "..."},
    {"metric": "营收增速 (%)", "subject_value": "...", "peer_value": "..."}
  ],
  "subject_leads": "<paragraph: where subject outperforms, cite specific numbers>",
  "peer_leads": "<paragraph: where peer outperforms or is comparable, cite numbers>"
}
```

---

## Step 4 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "peer_switch",
     "title": "<subject_name> vs <peer_name>",
     "stock_code": "<subject_code>",
     "stock_name": "<subject_name>",
     "skill_used": "peer-comparison",
     "summary": "Side-by-side comparison: radar chart, metric table, narrative",
     "data_keys_used": ["basic:<subject>", "val:<subject>", "fin:<subject>:annual", "basic:<peer>", "val:<peer>", "fin:<peer>:annual"],
     "parent_request_id": null,
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
