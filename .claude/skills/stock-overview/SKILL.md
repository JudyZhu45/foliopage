# Skill: stock-overview

## When to use

Use when `ACTION=initial` or `ACTION=peer_switch`.

---

## Step 1 — Resolve stock code

If `STOCK_QUERY` is a 6-digit code or known ticker, skip.
Otherwise: `search_stock(query=STOCK_QUERY)` → first result's `code`.

---

## Step 2 — Fetch data (check data_cache.json first)

**Batch A** (all simultaneous):

| Cache key | Tool |
|---|---|
| `basic:<code>` | `get_basic_info(code)` |
| `kline:<code>:1Y` | `get_kline(code, range="1Y")` |
| `val:<code>` | `get_valuation(code)` |
| `fin:<code>:annual` | `get_financials(code, period="annual")` |
| `fin:<code>:quarterly` | `get_financials(code, period="quarterly")` |
| `peers:<code>:10` | `get_peers(code, n=10)` |
| `news:<code>:30:10` | `recent_news(code, days=30, limit=10)` |
| `ann:<code>:60` | `recent_announcements(code, days=60)` |
| `analyst:<code>` | `analyst_consensus(code)` |

**Batch B** (all simultaneous, after A completes):

| Cache key | Tool |
|---|---|
| `revbk:<code>:latest` | `get_revenue_breakdown(code)` |
| `rd:<code>:5` | `get_rd_history(code, years=5)` |
| `holders:<code>` | `get_top_holders(code)` |
| `unlock:<code>:365` | `get_unlock_schedule(code, days=365)` |

**After Batch B completes**: run Phase 3.5 — write the merged cache via Bash
(python3 json.dump). Cache keys: basic, kline, val, fin, peers, analyst, revbk,
rd, holders, unlock. Exclude news/ann (free text corrupts JSON).

---

## Step 3 — Generate charts

Call (pass `[]` on missing data):
- `kline_svg(ohlcv=kline.bars, width=560, height=220)`
- `peer_bar_svg(items=[{code,name,value},...], metric="营收(亿元)", highlight_code=<code>)`
- `pe_band_svg(pe_history=..., current_pe=pe_ttm)` — if PE history available
- `comparison_radar_svg(subject, peers[:3], metrics)` — if peers confidence ≥ medium
- `metric_sparkline_svg(values=[rd_ratio...], width=120, height=32)` — if ≥ 2 R&D years

---

## Step 4 — Hybrid peer selection

**4a — Database candidates:** `get_peers(code, n=10)` from Batch A.

**4b — Business profile:** synthesise from `basic_info.sector`,
`revenue_breakdown.by_product`, and themes in `recent_news` to build a
clear picture of the company's primary business.

**4c — LLM nominations (optional):** if database candidates miss obvious
peers by business similarity, you MAY nominate up to 3 additional codes
from knowledge. For EACH nomination, call `get_basic_info(nominated_code)`.
If the call fails or the business doesn't match: DROP the nomination.

Permitted: same product/service; same business model; same customer segment.
Not permitted: vague thematic similarity; name pattern-matching; speculative expansion.

**4d — Final selection:** from verified candidates, select top 5 by business
similarity. For each, write a 1-sentence `同行理由`. Render fewer if < 5
confident matches — never pad. Zero peers: use the unavailability note.

**Hard rule:** NEVER include a stock without first verifying via
`get_basic_info`. No exceptions.

---

## Step 5 — Page structure (19 sections)

**Unavailable rule:** `available: false` → `.section.section-unavailable`
with `<p class="data-unavailable">此维度数据暂未覆盖</p>`.

**Drillable policy (strict):** ONLY (1) inline `<span class="company-link"
data-flipbook-action="peer_switch" ...>` in narrative prose, and (2) the 6
Section 19 drill cards, may carry `data-flipbook-action`. ALL other elements
(KPI cards, all table rows, news/announcement/analyst items, forward framework
cells) must NOT have this attribute.

**Minimum: ≥5 inline peer_switch spans** (Sections 3, 10, 11 narrative, 18).

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
  <a href="#catalysts">催化剂与风险</a>
  <a href="#forward-framework">前瞻框架</a>
  <a href="#analysis">深度分析</a> <a href="#drill-deeper">深入研究</a>
</nav>
```

### Sections 1–10

1. **Hero** — `{name}` `{code}` badge + industry tag + market cap + `as_of`
2. **KPI grid** (`id="kpi"`) — 8 metric cards: 当前价, 52周高/低, PE(TTM),
   PB, 市值, ROE, 毛利率, 股息率. Percentile badge on PE/PB if available.
   No `data-flipbook-action` on KPI cards.
3. **Business overview** (`id="business"`) — one dense paragraph.
   Synthesise sector, revenue_breakdown, news. ≥ 2 inline peer_switch
   spans. Flag dominant segment if > 70% of revenue.
4. **Revenue breakdown** (`id="revenue-bk"`) — `by_product` table
   (产品, 收入(亿元), 占比, 毛利率) + `by_region` sub-table.
   No data-flipbook-action on rows.
5. **Price chart** (`id="price"`) — `kline_svg` in `.chart-container`.
6. **Financial summary** (`id="financials"`) — 5-year annual table
   (最新在前), `peer_bar_svg` below, one CAGR sentence.
7. **Quarterly trend** (`id="quarterly"`) — last 5 quarters YoY%.
   One observation sentence.
8. **R&D investment** (`id="rd"`) — table + sparkline. Trend sentence
   with `.data-inferred` if inferring industry norm.
9. **Valuation analysis** (`id="valuation"`) — `pe_band_svg` + metric
   cards for PE/PB/percentile + peer-median compare. 2–3 sentences.
10. **Industry context** (`id="industry"`) — 150–200 words. ≥ 2
    news-backed trends with dates. ≥ 2 inline peer_switch spans.

### Section 11 — Peer comparison (`id="peers"`)

Apply hybrid selection from Step 4. Confidence rendering:
- `confidence: "low"`: prepend `<p class="chart-caption">该行业分类覆盖范围较广，以下公司仅供参考</p>`
- Any confidence, peers non-empty: show `<p class="chart-caption">可比公司参照行业：<strong>{industry}</strong></p>`
- Peers empty: `<p class="data-unavailable">未找到强相关可比公司，建议人工筛选</p>`

Render (when peers non-empty):
1. `comparison_radar_svg` (subject + top 3 peers) if confidence ≥ medium
2. `.peer-table` with columns: 名称, 代码, 市值(亿), PE, 同行理由.
   **No `data-flipbook-action` on table rows.**
3. Narrative paragraph: 2–3 contrasts with specific numbers; wrap peer
   names as inline peer_switch spans.

### Sections 12–16

12. **News** (`id="news"`) — top 5–7 items, headline links to source URL
    (new tab), 1–2 sentence summary. No flipbook actions.
13. **Announcements** (`id="announcements"`) — top 3–5 `.ann-item` blocks.
    Empty: `<p class="data-unavailable">近期无重大公告</p>`.
14. **Analyst consensus** (`id="analyst"`) — only if `available: true`.
    A) rating counts as 5 metric cards; B) P25/median/P75 vs current with
    delta badges; C) individual calls table ≤5 rows, last 90 days.
    No flipbook actions on rows.
15. **Shareholder structure** (`id="holders"`) — top-10 table + north-bound
    card if available. No flipbook actions on rows.
16. **Catalysts & risks** (`id="catalysts"`) — A) unlock schedule table if
    events exist; B) ≤3 data-backed risk bullets with source + date.
    No flipbook actions on table rows.

### Section 17 — Forward Framework (`id="forward-framework"`)

A 3×3 matrix: scenarios (悲观 / 中性 / 乐观) × horizons
(短期 < 3M / 中期 3–12M / 长期 1–3Y).

Each cell: 1–2 sentences of **conditions + drivers** specific to THIS
company. Ground every cell in data already on this page (financials, news,
announcements, catalysts). Generic macro drivers (e.g. "大盘下跌") are
rejected — rewrite with company-specific triggers.

Render as `.forward-framework-table`:
- Pessimistic cells: class `scenario-pessimistic`
- Neutral cells: class `scenario-neutral`
- Optimistic cells: class `scenario-optimistic`

**Hard rules:** no price/% targets; no probability language; no buy/hold/sell;
ungrounded cell → `需观察`; no `data-flipbook-action` on cells.

Always append verbatim:
`<p class="forward-framework-note">本框架为基于公开数据的情景分析，不构成具体股价预测或投资建议。</p>`

### Section 18 — Deep narrative analysis (`id="analysis"`)

5–6 paragraphs, 400–600 words. Connect business model, financials,
valuation, R&D, and risks into a coherent analytical thesis. One
`<blockquote class="pull-quote">` with the most striking data point.
Wrap peer names as inline peer_switch spans (contributes to ≥5 minimum).
Not permitted: forward projections as facts; numbers not on the page;
buy/sell/hold language.

### Section 19 — Drill Deeper (`id="drill-deeper"`)

Fixed section — same 6 cards across all stocks. Replace `<CODE>` and
`<NAME>` with the stock's code and name only:

```html
<section class="section drill-deeper" id="drill-deeper">
  <h2>深入研究</h2>
  <p class="drill-deeper-intro">从这里继续深入特定维度：</p>
  <div class="drill-grid">
    <a class="drill-card available" data-flipbook-action="business_breakdown"
       data-flipbook-context='{"stock_code":"<CODE>","stock_name":"<NAME>"}'>
      <span class="drill-card-icon">📊</span><span class="drill-card-title">业务拆解</span>
      <span class="drill-card-desc">收入结构、产品线毛利、客户集中度</span></a>
    <a class="drill-card available" data-flipbook-action="valuation_deep"
       data-flipbook-context='{"stock_code":"<CODE>","stock_name":"<NAME>"}'>
      <span class="drill-card-icon">📐</span><span class="drill-card-title">估值三角</span>
      <span class="drill-card-desc">历史分位、海外可比、隐含增长率</span></a>
    <a class="drill-card available" data-flipbook-action="peer_comparison_deep"
       data-flipbook-context='{"stock_code":"<CODE>","stock_name":"<NAME>"}'>
      <span class="drill-card-icon">⚖️</span><span class="drill-card-title">同行对比</span>
      <span class="drill-card-desc">多维财务指标 + 业务定位差异</span></a>
    <a class="drill-card coming-soon" data-flipbook-action="capital_flow"
       data-flipbook-context='{"stock_code":"<CODE>","stock_name":"<NAME>"}'>
      <span class="drill-card-icon">💧</span><span class="drill-card-title">资金流向</span>
      <span class="drill-card-desc">机构 / 北向 / 龙虎榜</span>
      <span class="drill-card-tag">v0.2</span></a>
    <a class="drill-card coming-soon" data-flipbook-action="sentiment_analysis"
       data-flipbook-context='{"stock_code":"<CODE>","stock_name":"<NAME>"}'>
      <span class="drill-card-icon">🌡️</span><span class="drill-card-title">情绪分析</span>
      <span class="drill-card-desc">大盘 / 板块 / 个股三层情绪</span>
      <span class="drill-card-tag">v0.2</span></a>
    <a class="drill-card coming-soon" data-flipbook-action="event_timeline"
       data-flipbook-context='{"stock_code":"<CODE>","stock_name":"<NAME>"}'>
      <span class="drill-card-icon">📅</span><span class="drill-card-title">事件时间线</span>
      <span class="drill-card-desc">关键事件 × 股价反应</span>
      <span class="drill-card-tag">v0.2</span></a>
  </div>
</section>
```

---

## Segmented HTML write strategy (Phase 5)

Page is ~150–200 KB. Write in 5 segments:
1. `Write` — `<!DOCTYPE html>` through Section 4 (revenue breakdown)
2. `Edit` append — Section 5 (price) through Section 9 (valuation)
3. `Edit` append — Section 10 (industry) through Section 13 (announcements)
4. `Edit` append — Section 14 (analyst) through Section 17 (forward framework)
5. `Edit` append — Section 18 (deep narrative) + Section 19 (drill deeper)
   + footer + `</body></html>`. Then `Read` last 10 lines to confirm `</html>`.

**Length target:** 19 sections · 2,000–2,800 words narrative · data-dense tables.
