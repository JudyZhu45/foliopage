# Skill: valuation-deep

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=valuation_deep`
(triggered by the "估值三角" card in the Drill Deeper section).

---

## Step 1 — Resolve stock

Read `CLICKED_CONTEXT` for `stock_code` and `stock_name`.

---

## Step 2 — Fetch data (check data_cache.json first)

| Cache key | Tool |
|---|---|
| `basic:<code>` | `get_basic_info(code)` |
| `val:<code>` | `get_valuation(code)` |
| `kline:<code>:5Y` | `get_kline(code, range="5Y")` |
| `fin:<code>:annual` | `get_financials(code, period="annual")` |
| `peers:<code>:10` | `get_peers(code, n=10)` |
| `analyst:<code>` | `analyst_consensus(code)` |

---

## Step 3 — Generate charts

- `pe_band_svg(pe_history=val.pe_history, current_pe=val.pe_ttm)` —
  5-year PE band (primary chart)
- `peer_bar_svg(items=[{code,name,value=pe_ttm},...], metric="PE(TTM)",
  highlight_code=<code>)` — peer PE comparison
- `comparison_radar_svg(subject, peers[:3],
  metrics=["pe","pb","ev_ebitda","roe","gross_margin"])` — multi-metric radar

---

## Step 4 — Page structure (4 sections)

**Drillable policy:** ONLY inline company-link peer_switch spans in
narrative prose may carry `data-flipbook-action`.

### Section 1 — Valuation snapshot

KPI cards: PE(TTM), PB, EV/EBITDA, 10Y PE percentile, dividend yield.
Percentile badge on PE (color: green < 30th, amber 30–70th, red > 70th).

### Section 2 — Historical PE band

`pe_band_svg` in `.chart-container`.

Narrative (2–3 sentences): where does current PE sit vs 10-year range?
What events drove prior valuation peaks/troughs (cite specific dates from
financials / news). Label inferred historical context with `.data-inferred`.

### Section 3 — Peer & overseas comparison

Two sub-sections:

**A — Domestic peers:** `peer_bar_svg` (PE) + `comparison_radar_svg`.
Table: 名称, PE, PB, EV/EBITDA, ROE, 毛利率. Wrap peer names as inline
peer_switch spans. One paragraph: premium/discount rationale grounded in
business differences.

**B — Implied growth rate:** back out the growth rate implied by current PE
using a simple Gordon/DDM heuristic. Show formula transparently. Label with
`.data-inferred`. Do NOT state this as a prediction — frame as "当前估值
隐含的增长假设约为 X%，参考近三年CAGR为Y%".

### Section 4 — Valuation context narrative

3–4 paragraphs, 300–400 words. Connect:
- Current PE percentile to business quality (ROE, margin stability)
- Analyst target price range (P25/P75 from `analyst_consensus`) vs implied
  growth — show the range, never a personal recommendation
- One `<blockquote class="pull-quote">` with the most striking number
- Wrap peer names as inline peer_switch spans

Not permitted: buy/sell/hold language; price targets stated as own opinion.

---

## Segmented write strategy

Write in 2 segments:
1. `Write` — head + Sections 1–2
2. `Edit` append — Sections 3–4 + footer + `</body></html>`

Print `PAGE_READY: output/page-<REQUEST_ID>.html` when done.
