# Skill: news-timeline

## When to use

Use when `ACTION=drill_down` and `CLICKED_CONTEXT` contains
`"clicked_topic":"news"` or `"clicked_topic":"recent_news"`.

Parse `CLICKED_CONTEXT` for `stock_code`. Read `PARENT_PAGE` from
`session/page_stack.json` to get `stock_name`.

---

## Step 1 — Fetch data (check data_cache.json first)

| Cache key | Tool call |
|---|---|
| `news:<code>:30:20` | `mcp__foliopage-news__recent_news(code, days=30, limit=20)` |
| `ann:<code>:90` | `mcp__foliopage-news__recent_announcements(code, days=90)` |
| `analyst:<code>` | `mcp__foliopage-news__analyst_consensus(code)` |
| `kline:<code>:3M` | `mcp__foliopage-stock__get_kline(code, range="3M")` |

---

## Step 2 — Generate charts

```
mcp__foliopage-chart__kline_svg(ohlcv=<3M bars>, width=480, height=140)
```

Use the compact height (160px) so the chart sits above the timeline as a
reference strip without dominating the page.

---

## Step 3 — Group news by calendar week

Before writing HTML, sort all news items by `published_at` (descending) and
group them into ISO week buckets:

```
Week of 2026-04-28:  item, item, item
Week of 2026-04-21:  item, item
...
```

Merge `recent_news` results and `recent_announcements` results into one
timeline. Mark announcements with class `ann-item`; news with `news-item`.

---

## Step 4 — Page structure (4 sections)

### Section 1 — Hero

```html
<section class="section hero">
  <p class="breadcrumb">
    <span class="company-link"
          data-flipbook-action="peer_switch"
          data-flipbook-context='{"stock_code":"600519","stock_name":"贵州茅台"}'>
      贵州茅台 (600519)
    </span> › 近期舆情
  </p>
  <h1>近 30 天舆情</h1>
  <p class="hero-sub">共 <strong>14</strong> 条新闻 · <strong>3</strong> 条公告</p>
</section>
```

### Section 2 — Price + timeline

First: paste `kline_svg` (compact, 160px height) as a reference backdrop.

Then: the merged weekly timeline. Each item is a drillable `<article>`:

```html
<section class="section">
  <div class="chart-container"><!-- compact kline SVG --></div>

  <div class="timeline">
    <h2 class="week-header">2026-04-28 当周</h2>

    <article class="news-item"
             data-flipbook-action="news_detail"
             data-flipbook-context='{"url":"https://...","title":"贵州茅台一季报营收同比+12%","source":"东方财富"}'>
      <time>2026-04-29</time>
      <span class="news-source">东方财富</span>
      <h3>贵州茅台一季报营收同比 +12%</h3>
    </article>

    <article class="ann-item"
             data-flipbook-action="news_detail"
             data-flipbook-context='{"url":"https://...","title":"2026年一季度报告","source":"上交所"}'>
      <time>2026-04-28</time>
      <span class="ann-badge">公告</span>
      <h3>2026 年一季度报告</h3>
    </article>

    <!-- more items -->
    <h2 class="week-header">2026-04-21 当周</h2>
    <!-- items for that week -->
  </div>
</section>
```

### Section 3 — Analyst consensus

Show only if `analyst_consensus` returned `available: true`.

```html
<section class="section">
  <h2>机构观点</h2>
  <div class="kpi-grid" style="--cols:4">
    <div class="metric-card">
      <span class="metric-label">目标价均值</span>
      <span class="metric-value">1,980 元</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">买入</span>
      <span class="metric-value metric-delta-up">12</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">中性</span>
      <span class="metric-value">4</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">卖出</span>
      <span class="metric-value metric-delta-down">1</span>
    </div>
  </div>
  <p class="narrative"><!-- 1 sentence: what the consensus reflects, no recommendation --></p>
</section>
```

If `available: false`, show:
```html
<p class="data-unavailable">暂无公开机构评级数据</p>
```

### Section 4 — Footer
Standard disclaimer + data-as-of.

---

## Drillable elements checklist

- [ ] Breadcrumb back to stock overview (peer_switch)
- [ ] Every news article in timeline (news_detail) — must be ≥ 5
- [ ] Every announcement in timeline (news_detail)
- [ ] Minimum 5 drillable elements total

---

## Length target

4 sections · list-heavy, ~300 words narrative · all news items shown,
not summarized.
