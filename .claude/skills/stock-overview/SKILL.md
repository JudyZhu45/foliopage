# Skill: stock-overview

## When to use

Use when `ACTION=initial` or `ACTION=peer_switch`.

---

## Step 1 — Resolve stock code

If `STOCK_QUERY` is a 6-digit code or known ticker, skip.
Otherwise: `search_stock(query=STOCK_QUERY)` → first result's `code`.

---

## Step 2 — Fetch data

Issue **all 8 calls simultaneously in one turn** (never call these one at a
time). Tool servers cache results to disk automatically — you do not need to
read or write `data_cache.json`.

| Tool call |
|---|
| `get_basic_info(code)` |
| `get_kline(code, range="1Y")` |
| `get_valuation(code)` |
| `get_financials(code, period="annual")` |
| `get_financials(code, period="quarterly")` |
| `get_peers(code, n=10)` |
| `recent_news(code, days=30, limit=10)` |
| `recent_announcements(code, days=60)` |

---

## Step 3 — Hybrid peer selection

**3a — Database candidates:** from `get_peers` result in Step 2.

**3b — Business profile:** synthesise from `basic_info.sector` and themes in
`recent_news` to understand the company's primary business.

**3c — LLM nominations (optional):** if database candidates miss obvious peers by
business similarity, nominate up to 3 additional codes from knowledge.
For EACH nomination, call `get_basic_info(nominated_code)`. If the call fails or
the business doesn't match: DROP the nomination.
Do NOT fetch val or fin data for peer nominations — only `get_basic_info` is allowed.

**3d — Final selection:** select top 5 verified candidates by business similarity.
For each, write a 1-sentence `reason`. Render fewer if < 5 confident matches.

**Hard rule:** NEVER include a stock without first verifying via `get_basic_info`.

---

## Step 4 — Write output JSON

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

**Peer link markup:** in all narrative text fields (`business_overview`,
`industry_context`, `peers_narrative`, `analysis`), wrap peer company names
as `[[stock_code|display_name]]`. The server converts these to clickable links.
Use this markup for **≥5 company name mentions** across all narrative fields combined.

**Numerical precision:** 2 decimal places for ratios; 1 decimal for large 亿元 values.
**Never invent numbers** — every value must come from a tool result or be `null`.

**`kline_bars` is mandatory.** Copy the full `bars` array from `get_kline()` verbatim into this field. The server uses it to render the price chart — do NOT summarise, truncate, or omit it. If `get_kline()` returned no bars, set this field to `[]`.

### JSON schema

```json
{
  "meta": {
    "stock_code": "<code>",
    "stock_name": "<name>",
    "skill": "stock-overview",
    "as_of": "<ISO datetime from basic_info>"
  },
  "hero": {
    "industry": "<sector from basic_info>",
    "exchange": "<SH|SZ|HK|…>",
    "as_of": "<date string>"
  },
  "kpi": {
    "price": <current price>,
    "week52_high": <or null>,
    "week52_low": <or null>,
    "pe_ttm": <or null>,
    "pe_percentile": <integer or null>,
    "pb": <or null>,
    "pb_percentile": <integer or null>,
    "market_cap_yi": <亿元>,
    "roe_pct": <or null>,
    "gross_margin_pct": <or null>,
    "dividend_yield_pct": <or null>,
    "as_of": "<date string>"
  },
  "kline_bars": [
    {"date": "YYYY-MM-DD", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0}
  ],
  "business_overview": "<one paragraph with ≥2 [[code|name]] links>",
  "financials_annual": [
    {
      "period": "<year>",
      "revenue_yi": <亿元>,
      "revenue_yoy_pct": <% or null>,
      "net_profit_yi": <亿元>,
      "gross_margin_pct": <%>,
      "roe_pct": <%>
    }
  ],
  "financials_cagr": "<one sentence about revenue/profit CAGR>",
  "financials_quarterly": [
    {
      "period": "<e.g. 2024Q4>",
      "revenue_yi": <亿元>,
      "revenue_yoy_pct": <% or null>,
      "net_profit_yi": <亿元>,
      "profit_yoy_pct": <% or null>
    }
  ],
  "quarterly_observation": "<one sentence>",
  "valuation": {
    "pe_ttm": <or null>,
    "pb": <or null>,
    "ev_ebitda": <or null>,
    "pe_percentile": <integer or null>,
    "peer_median_pe": <median PE of selected peers or null>
  },
  "valuation_comment": "<2-3 sentences>",
  "industry_context": "<150-200 words, ≥2 news-backed trends with dates, ≥2 [[code|name]] links>",
  "peers": [
    {
      "code": "<code>",
      "name": "<name>",
      "market_cap_yi": <亿元>,
      "pe_ttm": <or null>,
      "reason": "<one-sentence 同行理由>"
    }
  ],
  "peers_meta": {
    "industry": "<from get_peers.industry>",
    "confidence": "<high|medium|low>",
    "low_confidence_note": <true if confidence is low>,
    "peer_bar_metric": "营收(亿元)",
    "peer_bar_items": [
      {"code": "<code>", "name": "<name>", "营收(亿元)": <revenue 亿元>}
    ]
  },
  "peers_narrative": "<2-3 sentences, ≥2 [[code|name]] links>",
  "news": [
    {
      "title": "<headline>",
      "url": "<source URL or empty string>",
      "date": "<YYYY-MM-DD>",
      "summary": "<1-2 sentences>"
    }
  ],
  "announcements": [
    {
      "title": "<title>",
      "date": "<YYYY-MM-DD>",
      "summary": "<brief summary>"
    }
  ],
  "catalysts_risks": [
    {
      "type": "risk",
      "text": "<description>",
      "source": "<news or announcement title>",
      "date": "<date>"
    }
  ],
  "analysis": "<4-5 paragraphs separated by \\n\\n, ≥2 [[code|name]] links>",
  "pull_quote": "<single most striking data point>"
}
```

---

## Step 5 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "<ACTION>",
     "title": "<name> (<code>) 总览",
     "stock_code": "<code>",
     "stock_name": "<name>",
     "skill_used": "stock-overview",
     "summary": "14-section overview: KPI, K-line, financials, peers, news",
     "data_keys_used": ["basic:<code>", "kline:<code>:1Y", "val:<code>", "fin:<code>:annual", "fin:<code>:quarterly", "peers:<code>:10"],
     "parent_request_id": null,
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
