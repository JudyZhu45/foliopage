# Skill: business-breakdown

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=business_breakdown`
(triggered by the "业务拆解" card in the Drill Deeper section).

---

## Step 1 — Resolve stock

Read `CLICKED_CONTEXT` for `stock_code` and `stock_name`.

---

## Step 2 — Fetch data (check data_cache.json first)

| Cache key | Tool |
|---|---|
| `basic:<code>` | `get_basic_info(code)` |
| `revbk:<code>:latest` | `get_revenue_breakdown(code)` |
| `fin:<code>:annual` | `get_financials(code, period="annual")` |
| `peers:<code>:10` | `get_peers(code, n=10)` |

If `revbk` returns `available: false`, render a full-page unavailability
notice (class `.data-unavailable`) and stop.

---

## Step 3 — Generate charts

- `peer_bar_svg(items=[...], metric="毛利率%", highlight_code=<code>)` —
  compare gross margin across peers (use `get_peers` data for peer margins)
- `metric_sparkline_svg(values=[revenue by product trend if multi-year], ...)`
  if revenue breakdown includes multi-year product data

---

## Step 4 — Page structure (4 sections)

**Drillable policy:** ONLY inline company-link peer_switch spans in
narrative prose may carry `data-flipbook-action`. No table rows, no cards.

### Section 1 — Business description

One dense paragraph (150–200 words): what the company actually sells,
who buys it, what drives pricing. Source: `basic_info.sector`,
`revenue_breakdown.by_product`. Wrap ≥1 competitor name as peer_switch.

### Section 2 — Product / segment breakdown

Table from `by_product`:

| 产品/业务 | 收入(亿元) | 收入占比 | 毛利率 | YoY% |
|---|---|---|---|---|

If any segment > 70% of revenue, call it out in a `.pull-quote`.
Peer gross-margin bar chart (`peer_bar_svg`) below the table.

### Section 3 — Regional breakdown

Table from `by_region` (if non-empty):

| 地区 | 收入(亿元) | 收入占比 | YoY% |
|---|---|---|---|

If region data unavailable: `<p class="data-unavailable">地区拆分数据暂不可用</p>`.

### Section 4 — Structural analysis narrative

3–4 paragraphs, 300–400 words:
- Revenue concentration risk (HHI or simple top-segment share)
- Margin mix: which segment drives blended gross margin
- Growth engine: which segment grew fastest and why (cite news/financials)
- Wrap peer names as inline peer_switch spans

Include `<blockquote class="pull-quote">` with the most striking
segment-level data point.

---

## Segmented write strategy

Small page (~40–60 KB). Write in 2 segments:
1. `Write` — head + Sections 1–2
2. `Edit` append — Sections 3–4 + footer + `</body></html>`

Print `PAGE_READY: output/page-<REQUEST_ID>.html` when done.
