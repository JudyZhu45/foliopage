# Skill: metric-drilldown

## When to use

Use when `ACTION=drill_down` and `CLICKED_CONTEXT` contains a `metric` key.

Parse `CLICKED_CONTEXT` (JSON) to extract `stock_code`, `metric`, and `value`.
`PARENT_PAGE` holds the `request_id` of the page the user drilled from — read it
from `session/page_stack.json` to get `stock_name`.

---

## Step 1 — Identify metric category

| `metric` value in context | Category |
|---|---|
| `PE_TTM`, `PB`, `PS_TTM` | valuation |
| `ROE`, `gross_margin`, `net_margin` | profitability |
| `revenue`, `net_profit`, `operating_cf` | income |
| `price`, `market_cap` | price |

---

## Step 2 — Fetch data (check data_cache.json first)

| Category | Cache key | Tool call |
|---|---|---|
| valuation | `val:<code>` | `mcp__foliopage-stock__get_valuation(code)` |
| valuation | `fin:<code>:annual` | `mcp__foliopage-stock__get_financials(code, period="annual")` |
| profitability | `fin:<code>:annual` | `mcp__foliopage-stock__get_financials(code, period="annual")` |
| income | `fin:<code>:annual` | `mcp__foliopage-stock__get_financials(code, period="annual")` |
| income | `fin:<code>:quarterly` | `mcp__foliopage-stock__get_financials(code, period="quarterly")` |
| price | `kline:<code>:5Y` | `mcp__foliopage-stock__get_kline(code, range="5Y")` |
| all | `peers:<code>:5` | `mcp__foliopage-stock__get_peers(code, n=5)` |

Always fetch peers so Section 3 (peer comparison) can be populated.

---

## Step 3 — Generate charts

**Valuation metrics (PE_TTM, PB):**
If `get_valuation` returned `pe_10y_percentile` data, call:
```
mcp__foliopage-chart__pe_band_svg(pe_history=<list of {date,pe}>, current_pe=<value>)
```
Otherwise, build a `metric_sparkline_svg` from `get_financials` annual EPS/NAV columns.

**Profitability / income metrics:**
Extract the relevant column across annual periods and call:
```
mcp__foliopage-chart__metric_sparkline_svg(values=[...5 years of values...])
```

**Peer comparison on this metric:**
```
mcp__foliopage-chart__peer_bar_svg(
    items=[{code, name, <metric>: value}, ...],
    metric="<metric>",
    highlight_code="<subject code>"
)
```

**Price metric:**
```
mcp__foliopage-chart__kline_svg(ohlcv=<5Y bars>, width=480, height=200)
```

---

## Step 4 — Page structure (5 sections)

### Section 1 — Hero

```html
<section class="section hero">
  <p class="breadcrumb">
    <span class="company-link"
          data-flipbook-action="peer_switch"
          data-flipbook-context='{"stock_code":"600519","stock_name":"贵州茅台"}'>
      贵州茅台 (600519)
    </span> › PE 历史分位数
  </p>
  <h1>PE (TTM)</h1>
  <div class="kpi-grid" style="--cols:3">
    <div class="metric-card">
      <span class="metric-label">当前值</span>
      <span class="metric-value">28.3</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">1 年前</span>
      <span class="metric-value">24.1</span>
    </div>
    <div class="metric-card">
      <span class="metric-label">历史分位</span>
      <span class="metric-value">72%</span>
    </div>
  </div>
</section>
```

### Section 2 — Historical chart
Paste the chart SVG verbatim inside `.chart-container`. Include the caption as
`<p class="chart-caption">`.

### Section 3 — Peer comparison on this metric
Paste `peer_bar_svg` inside `.chart-container`. Below it, add a one-sentence
summary: who leads, who trails, where the subject sits.

### Section 4 — Narrative
Two paragraphs:
1. What the current level means in historical context (use percentile and min/max
   from the data — do not invent)
2. What the peer comparison reveals

Do not make forecasts or recommendations.

### Section 5 — Related links
Drillable links back to overview and to each peer's overview page.

```html
<section class="section">
  <h2>相关页面</h2>
  <ul>
    <li>
      <span class="company-link"
            data-flipbook-action="peer_switch"
            data-flipbook-context='{"stock_code":"600519","stock_name":"贵州茅台"}'>
        返回贵州茅台总览
      </span>
    </li>
    <li>
      <span class="company-link"
            data-flipbook-action="peer_switch"
            data-flipbook-context='{"stock_code":"000858","stock_name":"五粮液"}'>
        五粮液 (000858) 总览
      </span>
    </li>
  </ul>
</section>
```

---

## Drillable elements checklist

- [ ] Breadcrumb back to parent stock (peer_switch)
- [ ] Each peer bar (peer_switch) — add data-flipbook-* to the bar labels if
  the chart SVG cannot carry them; use a separate peer list below the chart
- [ ] Related links (≥ 2 peer_switch links)
- [ ] Minimum 5 drillable elements total

---

## Length target

5 sections · ~400–500 words narrative.
