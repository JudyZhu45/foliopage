# Skill: stock-overview

## When to use

Use when `ACTION=initial`, regardless of the skill name in the prompt.

---

## Step 1 — Resolve the stock code

If `STOCK_QUERY` is already a 6-digit number (A-share) or a known US ticker,
skip this step. Otherwise:

```
mcp__foliopage-stock__search_stock(query=STOCK_QUERY)
```

Take the first result's `code` as the canonical code for all subsequent calls.

---

## Step 2 — Fetch data (one parallel batch — check data_cache.json first)

| Cache key | Tool call |
|---|---|
| `basic:<code>` | `mcp__foliopage-stock__get_basic_info(code)` |
| `kline:<code>:1Y` | `mcp__foliopage-stock__get_kline(code, range="1Y")` |
| `val:<code>` | `mcp__foliopage-stock__get_valuation(code)` |
| `fin:<code>:annual` | `mcp__foliopage-stock__get_financials(code, period="annual")` |
| `fin:<code>:quarterly` | `mcp__foliopage-stock__get_financials(code, period="quarterly")` |
| `peers:<code>:5` | `mcp__foliopage-stock__get_peers(code, n=5)` |
| `news:<code>:30:10` | `mcp__foliopage-news__recent_news(code, days=30, limit=10)` |
| `ann:<code>:60` | `mcp__foliopage-news__recent_announcements(code, days=60)` |
| `analyst:<code>` | `mcp__foliopage-news__analyst_consensus(code)` |

---

## Step 3 — Generate charts

Always call (regardless of data availability — pass empty list on missing data):
```
mcp__foliopage-chart__kline_svg(ohlcv=kline.bars, width=560, height=220)
```

If `get_valuation` returned historical PE data:
```
mcp__foliopage-chart__pe_band_svg(pe_history=<historical PE list>, current_pe=<pe_ttm>)
```

Revenue bar chart (use annual periods as items):
```
mcp__foliopage-chart__peer_bar_svg(
    items=[{"code": period_str, "name": year_label, "value": revenue_yi}, ...],
    metric="营收(亿元)",
    highlight_code=<latest_period_str>
)
```

If peers confidence is "medium" or "high", radar chart:
```
mcp__foliopage-chart__comparison_radar_svg(
    subject={code, name, PE, PB, ROE, gross_margin, net_margin},
    peers=[same for up to 3 peers],
    metrics=["PE","PB","ROE","gross_margin","net_margin"]
)
```
Omit any metric where all stocks have `None`.

---

## Step 4 — Page structure (12 sections, in order)

All sections get an `id` attribute that matches the in-page nav. The page is a
single self-contained document — no further generation is needed for any section.

### Section 0 — In-page navigation bar

```html
<nav class="toc section">
  <a href="#kpi">关键指标</a>
  <a href="#price">股价走势</a>
  <a href="#valuation">估值历史</a>
  <a href="#financials">财务摘要</a>
  <a href="#quarterly">季度趋势</a>
  <a href="#peers">可比公司</a>
  <a href="#news">近期动态</a>
  <a href="#analysis">深度分析</a>
</nav>
```

### Section 1 — Hero

```html
<section class="section hero">
  <h1>贵州茅台 <span class="code-badge">600519</span></h1>
  <p class="industry-tag">白酒 · 上交所</p>
  <div class="hero-stats">
    <span class="hero-mktcap">市值 <strong>22,800 亿元</strong></span>
    <span class="data-as-of">截至 2026-04-30 15:00</span>
  </div>
</section>
```

### Section 2 — KPI grid (id="kpi")

Eight metric cards. Metrics in order: 当前价, 52周高/低, PE (TTM), PB, 市值,
ROE, 毛利率, 股息率.

For PE and PB, add a delta badge showing the 10-year percentile if available
(`metric-delta-down` if above 70th percentile, `metric-delta-up` if below 30th).
For ROE and 毛利率, show peer-median context if available.

No `data-flipbook-action` on KPI cards — the details are already on this page.

```html
<section class="section" id="kpi">
  <div class="kpi-grid">
    <div class="metric-card">
      <span class="metric-label">当前价</span>
      <span class="metric-value">1,785.00</span>
      <span class="metric-delta-down">近1年 -8.3%</span>
    </div>
    <!-- repeat for other 7 metrics -->
  </div>
</section>
```

### Section 3 — Price chart (id="price")

```html
<section class="section" id="price">
  <h2>股价走势（近 1 年）</h2>
  <div class="chart-container"><!-- kline_svg verbatim --></div>
  <p class="chart-caption"><!-- kline_svg.caption --></p>
</section>
```

### Section 4 — Valuation history (id="valuation")

If PE band data is available: paste `pe_band_svg` verbatim. Follow with a
two-sentence context: current percentile rank + comparison to the peer median PE.

If no historical PE data: show a prose table of PE/PB/EV-EBITDA with industry
median for context (use peer data).

```html
<section class="section" id="valuation">
  <h2>估值历史</h2>
  <div class="chart-container"><!-- pe_band_svg verbatim --></div>
  <p class="chart-caption">当前 PE 28.3×，处于近 10 年 72 分位。行业中位 PE 约 18×。</p>
</section>
```

### Section 5 — Financial summary table (id="financials")

Five-year annual data. Columns: 年度, 营收(亿元), 营收增速, 净利润(亿元),
净利润增速, 毛利率, 净利率, ROE. One row per reporting period, most recent first.

Below the table, paste the revenue bar chart:
```html
<div class="chart-container" style="margin-top:.75rem"><!-- peer_bar_svg --></div>
```

One sentence of CAGR context after the chart.

```html
<section class="section" id="financials">
  <h2>财务摘要（近 5 年）</h2>
  <table class="peer-table">
    <thead>
      <tr>
        <th>年度</th>
        <th>营收(亿元)</th>
        <th>增速</th>
        <th>净利润(亿元)</th>
        <th>增速</th>
        <th>毛利率</th>
        <th>净利率</th>
        <th>ROE</th>
      </tr>
    </thead>
    <tbody>
      <!-- one <tr> per year, most recent first -->
    </tbody>
  </table>
  <!-- revenue bar chart here -->
</section>
```

### Section 6 — Quarterly trend (id="quarterly")

Last 4–6 quarters from `get_financials(period="quarterly")`. Show as a compact
prose table: 季度, 营收(亿元), YoY%, 净利润(亿元), YoY%. One sentence of
observation on the most recent quarter vs year-ago.

If quarterly data is unavailable: omit the section entirely (do not show a
`data-unavailable` placeholder — just skip).

### Section 7 — Peer comparison (id="peers")

Apply confidence rendering rules from CLAUDE.md.

If `peers` is empty: show the unavailability note only.

Otherwise always render the full section:
1. **Radar chart** — call `comparison_radar_svg` with subject + up to 3 largest peers
2. **Peer table** — all returned peers
3. **Differential commentary** — one paragraph highlighting the sharpest contrasts:
   pick the 2–3 metrics where the subject diverges most from peers (e.g. margin
   premium, valuation gap, growth rate difference). Cite specific numbers.

Peer table columns: 名称, 市值(亿元), PE(TTM), PB, 毛利率(%), ROE(%), 近1年涨跌幅.
Each `<tr>` is a `peer_switch` link. Leave cells `—` for missing values.
Show industry label + confidence note per CLAUDE.md rules.

```html
<section class="section" id="peers">
  <h2>可比公司</h2>
  <!-- confidence note if low -->
  <div class="chart-container"><!-- comparison_radar_svg --></div>
  <table class="peer-table">
    <thead>
      <tr>
        <th>名称</th><th>市值(亿)</th><th>PE</th><th>PB</th>
        <th>毛利率%</th><th>ROE%</th><th>近1年涨跌</th>
      </tr>
    </thead>
    <tbody>
      <tr data-flipbook-action="peer_switch"
          data-flipbook-context='{"stock_code":"000858","stock_name":"五粮液"}'>
        <td>五粮液</td><td>6,400</td><td>20.1</td>
        <td>8.7</td><td>74.3</td><td>25.4</td><td>+3.2%</td>
      </tr>
    </tbody>
  </table>
  <p class="chart-caption">可比公司参照行业：<strong>白酒</strong></p>
  <p class="narrative"><!-- differential commentary --></p>
</section>
```

### Section 8 — Recent news & announcements (id="news")

All items from `recent_news` (up to 10) followed by items from
`recent_announcements` (up to 5). Render as a unified timeline — sort all by
date descending, add a week-header label when the week changes.

News items: link headline to the original URL if present. Open in a new tab.
Announcements: use `.ann-badge` instead of `.news-source`.

```html
<section class="section" id="news">
  <h2>近期动态</h2>

  <p class="week-header">本周</p>

  <article class="news-item">
    <time>2026-04-28</time>
    <span class="news-source">东方财富</span>
    <h3>
      <a href="https://..." target="_blank" rel="noopener">
        贵州茅台一季度营收同比增长 12%
      </a>
    </h3>
    <p class="narrative"><!-- 1–2 sentence summary from the tool result --></p>
  </article>

  <!-- announcements use ann-badge -->
  <article class="ann-item">
    <time>2026-04-25</time>
    <span class="ann-badge">公告</span>
    <h3>2025 年度利润分配预案：10 派 24.6 元</h3>
    <p class="narrative"><!-- summary --></p>
  </article>
</section>
```

Show full `summary` field from the tool result (1–2 sentences). If there is no
summary field, omit the `<p class="narrative">`.

### Section 9 — Analyst consensus (id="analyst")

Only render if `analyst_consensus` returned `available: true`.

Show three sub-sections:

**A — Rating distribution** (5-level counts + overall score)

```html
<section class="section" id="analyst">
  <h2>分析师观点（共 {total_coverage} 份报告）</h2>

  <div class="kpi-grid" style="grid-template-columns: repeat(5,1fr)">
    <div class="metric-card">
      <span class="metric-label">买入</span>
      <span class="metric-value metric-delta-up">{ratings.buy}</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">增持</span>
      <span class="metric-value metric-delta-up">{ratings.outperform}</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">中性</span>
      <span class="metric-value">{ratings.neutral}</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">减持</span>
      <span class="metric-value metric-delta-down">{ratings.underperform}</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">卖出</span>
      <span class="metric-value metric-delta-down">{ratings.sell}</span>
    </div>
  </div>
```

**B — Target price scenarios** (only if `target_prices.sample_size > 0`)

Show three scenarios as metric cards, each displaying the target price and the
upside/downside percentage vs. current price from `get_basic_info`.

```html
  <h3 style="margin-top:1.25rem">目标价区间（{sample_size} 家机构）</h3>
  <div class="kpi-grid" style="grid-template-columns: repeat(3,1fr)">
    <div class="metric-card">
      <span class="metric-label">悲观（P25）</span>
      <span class="metric-value">{pessimistic}</span>
      <span class="metric-delta-down">{upside_pct_pessimistic}% 较现价</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">中性（中位）</span>
      <span class="metric-value">{neutral}</span>
      <span class="{delta_class}">{upside_pct_neutral}% 较现价</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">乐观（P75）</span>
      <span class="metric-value">{optimistic}</span>
      <span class="metric-delta-up">{upside_pct_optimistic}% 较现价</span>
    </div>
  </div>
  <p class="chart-caption">区间 {low}–{high} 元 · 均值 {mean} 元</p>
```

**C — Recent individual calls** (last 90 days, up to 5 rows)

```html
  <table class="peer-table" style="margin-top:1rem">
    <thead>
      <tr><th>机构</th><th>评级</th><th>目标价</th><th>日期</th></tr>
    </thead>
    <tbody>
      <!-- one row per entry in recent_changes -->
    </tbody>
  </table>
</section>
```

Upside calculation: `round((target - current_price) / current_price * 100, 1)`.
Use `metric-delta-up` for positive upside, `metric-delta-down` for negative.

### Section 10 — Narrative analysis (id="analysis")

Four to five paragraphs. Permitted content:
1. Business description and revenue structure
2. Financial trend analysis (cite CAGR, margin trajectory, ROE stability)
3. Valuation context — current vs historical percentile, vs peer median
4. Recent news/announcement themes that are material (cite dates and numbers
   already shown in the news section — no new numbers)
5. Key risks visible in the data (declining margins, debt growth, valuation
   premium vs peers, etc.) — never framed as buy/sell advice

Not permitted: forward projections stated as facts; any number not already
shown earlier on the page; buy/sell/hold language.

Company name mentions in the narrative: wrap with `peer_switch` links so the
user can navigate to that stock's overview directly from the prose.

```html
<section class="section narrative" id="analysis">
  <h2>深度分析</h2>
  <p><!-- paragraph 1 --></p>
  <p><!-- paragraph 2 --></p>
  <blockquote class="pull-quote"><!-- one key data insight as a pull quote --></blockquote>
  <p><!-- paragraph 3 --></p>
  <p><!-- paragraph 4 --></p>
</section>
```

### Section 11 — Footer

Standard disclaimer + data-as-of timestamp from the tool results.

---

## Drillable elements checklist (minimum 5)

- [ ] 5 × peer table rows (`peer_switch` to each peer)
- [ ] Company name mentions in narrative prose (`peer_switch`)

KPI cards do **not** need `data-flipbook-action` — their detail is on this page.
News headlines link directly to source URLs, not to generated pages.

---

## Length target

12 sections · ~800–1,000 words narrative · data-dense with full financial tables.
The page should be comprehensive enough that no follow-up generation is needed for
standard research questions about this stock.
