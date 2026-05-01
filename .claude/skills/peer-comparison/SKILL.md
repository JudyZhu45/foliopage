# Skill: peer-comparison

## When to use

Use when `ACTION=peer_switch` **or** when `ACTION=initial` and `STOCK_QUERY`
implies a comparison (e.g. "茅台 vs 五粮液", "compare AAPL and MSFT").

- **peer_switch**: `CLICKED_CONTEXT` supplies `stock_code` and
  `stock_name`. Treat `stock_code` as the subject. Load the parent
  page's stock from `session/page_stack.json` as the comparison peer.
- **compare query**: parse both codes from `STOCK_QUERY`. The first is
  the subject.

---

## Step 1 — Resolve both codes

For each code that is a name (not already a digit string or known ticker):
```
mcp__foliopage-stock__search_stock(query=<name>)
```

Variables after this step: `subject_code`, `subject_name`, `peer_code`, `peer_name`.

---

## Step 2 — Fetch data (check data_cache.json first for each key)

Fetch the same set for **both** subject and peer:

| Cache key pattern | Tool call |
|---|---|
| `basic:<code>` | `mcp__foliopage-stock__get_basic_info(code)` |
| `val:<code>` | `mcp__foliopage-stock__get_valuation(code)` |
| `fin:<code>:annual` | `mcp__foliopage-stock__get_financials(code, period="annual")` |

---

## Step 3 — Generate charts

Build the comparison metrics dict for each stock from the fetched data:

```python
# Pseudo-code — compute before calling chart tool
subject_metrics = {
    "code": subject_code, "name": subject_name,
    "PE":           valuation["pe_ttm"],
    "PB":           valuation["pb"],
    "ROE":          financials latest period["roe"],
    "gross_margin": financials latest period["gross_margin"],
    "net_margin":   financials latest period["net_margin"],
}
# same for peer
```

Then call:
```
mcp__foliopage-chart__comparison_radar_svg(
    subject=subject_metrics,
    peers=[peer_metrics],
    metrics=["PE", "PB", "ROE", "gross_margin", "net_margin"]
)
```

Omit any metric where **both** stocks have `None` — don't plot an empty axis.

---

## Step 4 — Page structure (5 sections)

### Section 1 — Hero (side by side)

```html
<section class="section hero">
  <div class="compare-hero">
    <div class="compare-subject">
      <h1>贵州茅台 <span class="code-badge">600519</span></h1>
      <p class="industry-tag">白酒 · 上交所</p>
      <p class="hero-mktcap">市值 <strong>22,800 亿元</strong></p>
    </div>
    <div class="compare-vs">VS</div>
    <div class="compare-peer"
         data-flipbook-action="peer_switch"
         data-flipbook-context='{"stock_code":"000858","stock_name":"五粮液"}'>
      <h2>五粮液 <span class="code-badge">000858</span></h2>
      <p class="industry-tag">白酒 · 深交所</p>
      <p class="hero-mktcap">市值 <strong>6,400 亿元</strong></p>
    </div>
  </div>
</section>
```

### Section 2 — Radar chart
Paste `comparison_radar_svg` verbatim inside `.chart-container`.
Caption: metric names, normalized 0–100 per axis.

### Section 3 — Side-by-side metric table
If the peer was reached via `get_peers` and `confidence` is "low", show a note
"数据来源行业分类可信度较低，如下对比仅供参考" above the table.
`.peer-table` with one row per metric. Three columns: 指标, Subject, Peer.
Each row carrying a metric that can be drilled further should be drillable.

| 指标 | 贵州茅台 | 五粮液 |
|---|---|---|
| PE (TTM) | 28.3 | 20.1 |
| PB | 12.4 | 8.7 |
| ROE (%) | 31.2 | 25.4 |
| 毛利率 (%) | 91.8 | 74.3 |
| 净利率 (%) | 51.2 | 31.8 |
| 市值 | 22,800 亿元 | 6,400 亿元 |
| 营收增速 (近1年, %) | +18.0 | +12.3 |

Drillable metric rows (drill_down on each row for the **subject**):
```html
<tr data-flipbook-action="drill_down"
    data-flipbook-context='{"clicked_topic":"PE 历史分位数","stock_code":"600519","metric":"PE_TTM","value":28.3}'>
  <td>PE (TTM)</td>
  <td>28.3</td>
  <td>20.1</td>
</tr>
```

### Section 4 — Differential narrative
Two paragraphs:
1. Where the subject leads (cite specific numbers from the table)
2. Where the subject lags or is comparable (cite specific numbers)

Do not conclude which is the better investment.

### Section 5 — Footer
Standard disclaimer + data-as-of.

---

## Drillable elements checklist

- [ ] Peer hero block (peer_switch back to peer's overview)
- [ ] Metric table rows (drill_down — at least 3)
- [ ] Subject breadcrumb back to its overview (peer_switch)
- [ ] Minimum 5 drillable elements total

---

## Length target

5 sections · ~500–600 words narrative.
