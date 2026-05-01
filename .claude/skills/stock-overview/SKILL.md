# Skill: stock-overview

## When to use

Use when `ACTION=initial`.

---

## Step 1 — Resolve the stock code

If `STOCK_QUERY` is a 6-digit number or known ticker, skip. Otherwise:
`mcp__foliopage-stock__search_stock(query=STOCK_QUERY)` → take first result's `code`.

---

## Step 2 — Fetch data

**Batch A** (issue all simultaneously — check data_cache.json first):

| Cache key | Tool |
|---|---|
| `basic:<code>` | `get_basic_info(code)` |
| `kline:<code>:1Y` | `get_kline(code, range="1Y")` |
| `val:<code>` | `get_valuation(code)` |
| `fin:<code>:annual` | `get_financials(code, period="annual")` |
| `fin:<code>:quarterly` | `get_financials(code, period="quarterly")` |
| `peers:<code>:5` | `get_peers(code, n=5)` |
| `news:<code>:30:10` | `recent_news(code, days=30, limit=10)` |
| `ann:<code>:60` | `recent_announcements(code, days=60)` |
| `analyst:<code>` | `analyst_consensus(code)` |

**Batch B** (issue all simultaneously after Batch A):

| Cache key | Tool |
|---|---|
| `revbk:<code>:latest` | `get_revenue_breakdown(code)` |
| `rd:<code>:5` | `get_rd_history(code, years=5)` |
| `holders:<code>` | `get_top_holders(code)` |
| `unlock:<code>:365` | `get_unlock_schedule(code, days=365)` |

---

## Step 3 — Generate charts

Always call (pass `[]` on missing data):
- `kline_svg(ohlcv=kline.bars, width=560, height=220)`
- `peer_bar_svg(items=[{code, name, value=revenue_yi},...], metric="营收(亿元)", highlight_code=<latest>)`
- `pe_band_svg(pe_history=..., current_pe=pe_ttm)` — if PE history available
- `comparison_radar_svg(subject, peers[:3], metrics)` — if peers confidence medium/high
- `metric_sparkline_svg(values=[rd_ratio...], width=120, height=32)` — if ≥2 R&D years

---

## Step 4 — Page structure (16 sections in order)

**Unavailable-section rule**: if a section's primary tool returned `available: false`,
render a `.section.section-unavailable` block with `<p class="data-unavailable">此维度数据暂未覆盖</p>`.
Never silently skip (exception: quarterly data may be omitted if tool returns nothing).

**Drillable minimum: 12 elements** — see checklist at end.

### Nav bar (Section 0)
```html
<nav class="toc section">
  <a href="#kpi">关键指标</a> <a href="#business">业务概览</a>
  <a href="#revenue-bk">收入拆分</a> <a href="#price">股价走势</a>
  <a href="#financials">财务摘要</a> <a href="#quarterly">季度趋势</a>
  <a href="#rd">研发投入</a> <a href="#valuation">估值分析</a>
  <a href="#industry">行业背景</a> <a href="#peers">可比公司</a>
  <a href="#news">近期动态</a> <a href="#announcements">公司公告</a>
  <a href="#analyst">分析师观点</a> <a href="#holders">股东结构</a>
  <a href="#catalysts">催化剂与风险</a> <a href="#analysis">深度分析</a>
</nav>
```

### Section 1 — Hero
`{name}` + `{code}` badge + industry tag + market cap + `as_of`.

### Section 2 — KPI grid (id="kpi")
Eight metric cards: 当前价, 52周高/低, PE(TTM), PB, 市值, ROE, 毛利率, 股息率.
Add percentile badge to PE/PB if `pe_10y_percentile` available. No flipbook actions on KPI cards.

### Section 3 — Business overview (id="business") [NEW]
One dense paragraph: what the company does, core products, end markets, competitive position.
Synthesise from `basic_info.sector`, `revenue_breakdown.by_product`, and `recent_news`.
If one segment > 70% of revenue, call it out explicitly.

### Section 4 — Revenue breakdown (id="revenue-bk") [NEW]
If `available: false` → section-unavailable. Otherwise:
- Table of `by_product`: 产品/业务, 收入(亿元), 收入占比, 毛利率. Section heading: `{year}年度`.
- Sub-table of `by_region` if non-empty: 地区, 收入(亿元), 收入占比.
- Each product row: `data-flipbook-action="business_drilldown"` + `data-flipbook-context='{"code":"...","segment":"..."}'`

### Section 5 — Price chart (id="price")
`kline_svg` verbatim inside `.chart-container`.

### Section 6 — Financial summary (id="financials")
5-year annual table: 年度, 营收(亿元), 增速, 净利润(亿元), 增速, 毛利率, 净利率, ROE.
Most recent first. Below table: `peer_bar_svg`. One sentence of CAGR context.

### Section 7 — Quarterly trend (id="quarterly")
Last 5 quarters: 季度, 营收(亿元), YoY%, 净利润(亿元), YoY%. One observation sentence.

### Section 8 — R&D investment (id="rd") [NEW]
If `available: false` → section-unavailable. Otherwise:
- Table: 年度, 研发费用(亿元), 研发/营收比.
- Sparkline SVG inline if ≥ 2 years.
- Narrative `<p>` with `data-flipbook-action="metric_drilldown"` + `data-flipbook-context='{"code":"...","metric":"rd_intensity"}'`.
- One sentence on trend direction and industry norm (label inferred value with `.data-inferred`).

### Section 9 — Valuation analysis (id="valuation") [EXPANDED]
Paste `pe_band_svg` if available. Then metric cards for PE, PB, and 10y percentile.
Peer-median PE/PB from `peers` for comparison. 2–3 sentences: percentile rank, premium/discount to peer median, historical context.

### Section 10 — Industry context (id="industry") [NEW]
One paragraph (150–200 words). Source: industry label from `get_peers`, sector from `basic_info`, themes from `recent_news`.
Cite 2–3 concrete news-backed trends with dates. Wrap competitor names in `peer_switch` links.
Add `data-flipbook-action="industry_drilldown"` on the industry label span.

### Section 11 — Peer comparison (id="peers")
Apply CLAUDE.md confidence rendering rules. If peers empty: show unavailability note.
Otherwise:
1. `comparison_radar_svg` (subject + up to 3 peers)
2. Peer table — all peers; each `<tr>` is `peer_switch`. Columns: 名称, 市值(亿), PE, PB, 毛利率%, ROE%, 近1年涨跌. Missing values → `—`.
3. One paragraph: 2–3 sharpest contrasts, cite specific numbers.

### Section 12 — Recent news (id="news")
Top 5–7 items from `recent_news`, descending. Link headline to source URL (new tab). 1–2 sentence summary per item.

### Section 13 — Announcements (id="announcements") [NEW]
Top 3–5 items from `recent_announcements` as `.ann-item` blocks (date + `.ann-badge` + title + 1-sentence summary).
If empty: `<p class="data-unavailable">近期无重大公告</p>`.

### Section 14 — Analyst consensus (id="analyst")
Only render if `available: true`. Three sub-sections:
- A: Rating distribution (买入/增持/中性/减持/卖出 counts as 5 metric cards)
- B: Target price P25/median/P75 vs current price (upside % with delta badges)
- C: Recent individual calls table (机构, 评级, 目标价, 日期) — last 90 days, ≤5 rows

### Section 15 — Shareholder structure (id="holders") [NEW]
If `available: false` → section-unavailable. Otherwise:
- Table: 股东名称, 类型, 持股(亿股), 占比, 变动. Each corporate holder row: `data-flipbook-action="holder_drilldown"`.
- If `north_bound` non-null: annotation card "北向资金: {shares_yi}亿股 ({pct}%), 近30日 {trend_30d}".
- Show `as_of_quarter` as data freshness note.

### Section 16 — Catalysts & risks (id="catalysts") [NEW]
**A — Unlock schedule**: compact table if `events` non-empty (解禁日期, 股数(亿), 市值估算(亿), 类型); each row `data-flipbook-action="event_drilldown"`. If empty: "未来12个月内无限售股解禁". If `available: false`: `data-unavailable`.

**B — Company-specific risks**: max 3 bullets, must be data-backed (from news/announcements/financials). Cite source and date. If only generic risks identifiable, write 0–2 bullets.

### Section 17 — Deep narrative analysis (id="analysis")
Five to six paragraphs, 400–600 words. Connects business model, financials, valuation, R&D, and risks into a coherent thesis. Include one `<blockquote class="pull-quote">` with the most striking data point. Wrap peer names in `peer_switch` links.

Not permitted: forward projections stated as facts; numbers not already on the page; buy/sell/hold language.

---

## Drillable elements checklist (minimum 12)

- [ ] ≥ 5 peer table rows (`peer_switch`)
- [ ] ≥ 2 company name mentions in prose (`peer_switch`)
- [ ] ≥ 1 revenue breakdown product row (`business_drilldown`)
- [ ] ≥ 1 R&D paragraph (`metric_drilldown` on `rd_intensity`)
- [ ] ≥ 2 top holder rows (`holder_drilldown`)
- [ ] ≥ 1 industry label (`industry_drilldown`)
- [ ] ≥ 1 unlock event row (`event_drilldown`) if events exist

---

## Segmented HTML write strategy (Phase 5)

Page is ~120–180 KB. Write in 4 segments:
1. `Write` — `<!DOCTYPE html>` through Section 4 (revenue breakdown)
2. `Edit` append — Section 5 (price) through Section 9 (valuation)
3. `Edit` append — Section 10 (industry) through Section 14 (analyst)
4. `Edit` append — Section 15 (holders) through footer + `</body></html>`

After writing: `Read` last 10 lines to verify ends with `</html>`.

---

## Length target

16 sections · 1,800–2,400 words narrative · data-dense tables throughout.
