# Skill: peer-comparison-deep

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=peer_comparison_deep`
(triggered by the "同行对比" card in the Drill Deeper section).

---

## Step 1 — Resolve stock

Read `CLICKED_CONTEXT` for `stock_code` and `stock_name`. This is the
**subject** company.

---

## Step 2 — Fetch data (check data_cache.json first)

**Batch A** (simultaneous):

| Cache key | Tool |
|---|---|
| `basic:<code>` | `get_basic_info(code)` |
| `val:<code>` | `get_valuation(code)` |
| `fin:<code>:annual` | `get_financials(code, period="annual")` |
| `peers:<code>:10` | `get_peers(code, n=10)` |

**Batch B** — after Batch A, apply hybrid peer selection (same 4-step
procedure as stock-overview Step 4) to identify top 5 verified peers.
Then for each selected peer, fetch (all simultaneous):

| Cache key | Tool |
|---|---|
| `basic:<peer_code>` | `get_basic_info(peer_code)` |
| `val:<peer_code>` | `get_valuation(peer_code)` |
| `fin:<peer_code>:annual` | `get_financials(peer_code, period="annual")` |

If any peer tool returns an error: show `—` for those cells; do not drop
the peer from the table.

---

## Step 3 — Generate charts

- `comparison_radar_svg(subject, peers[:4], metrics=["pe","pb","gross_margin","roe","revenue_cagr_3y"])` — multi-metric radar
- `peer_bar_svg(items=[subject+peers], metric="毛利率%", highlight_code=<code>)`
- `peer_bar_svg(items=[subject+peers], metric="ROE%", highlight_code=<code>)`

---

## Step 4 — Page structure (4 sections)

**Drillable policy:** ONLY inline company-link peer_switch spans in
narrative prose. No table rows.

### Section 1 — Comparison overview

`comparison_radar_svg` in `.chart-container`. Caption: metrics shown.

Subheading listing the 5 peers with one-line business description each
(from `基本信息.sector`).

### Section 2 — Multi-metric comparison table

Full peer table with subject highlighted. Columns:

| 名称 | 市值(亿) | PE | PB | EV/EBITDA | 毛利率% | 净利率% | ROE% | 营收CAGR(3Y) |
|---|---|---|---|---|---|---|---|---|

Subject row in bold. Missing values: `—`.

Two bar charts below: 毛利率 (`peer_bar_svg`) + ROE (`peer_bar_svg`).

### Section 3 — Business positioning matrix

Qualitative 2×2 grid (rendered as HTML table, not a chart):
- Axes: 盈利质量 (毛利率 + 净利率) vs 成长性 (3Y CAGR)
- Each peer placed in one quadrant with its name
- One sentence per peer on why it lands in that quadrant

### Section 4 — Competitive analysis narrative

4–5 paragraphs, 400–500 words:
- Subject's relative strengths and weaknesses vs peer median (cite numbers)
- Which peer is most similar in business model and how they differ
- Which peer differs most in valuation — and what justifies the gap
- Wrap every peer name as inline peer_switch span

One `<blockquote class="pull-quote">` with the sharpest cross-peer contrast.

Not permitted: buy/sell/hold language; investment recommendation implied
by comparison framing.

---

## Segmented write strategy

Write in 2 segments:
1. `Write` — head + Sections 1–2
2. `Edit` append — Sections 3–4 + footer + `</body></html>`

Print `PAGE_READY: output/page-<REQUEST_ID>.html` when done.
