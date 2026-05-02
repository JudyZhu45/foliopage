"""
HTML renderer — converts stock-overview JSON to a self-contained HTML page.

The LLM agent now writes output/data-<request_id>.json instead of HTML.
This module:
  1. Reads the JSON
  2. Calls chart_service.generate_charts() to get SVG strings
  3. Builds the 14-section HTML page from the structured data

Peer link markup: narrative text fields use [[code|name]] which is converted
to <span class="company-link" data-flipbook-action="peer_switch" ...>name</span>.
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _e(s: Any) -> str:
    """HTML-escape and stringify."""
    return _html.escape(str(s)) if s is not None else ""


def _fmt(v: Any, decimals: int = 2, suffix: str = "", default: str = "—") -> str:
    """Format a numeric value."""
    if v is None:
        return default
    try:
        return f"{float(v):,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def _pct(v: Any, default: str = "—") -> str:
    """Format as percentage with sign."""
    if v is None:
        return default
    try:
        f = float(v)
        sign = "+" if f > 0 else ""
        return f"{sign}{f:.2f}%"
    except (TypeError, ValueError):
        return str(v)


def _delta_class(v: Any) -> str:
    """Return CSS class for positive/negative delta."""
    try:
        return "metric-delta-up" if float(v) >= 0 else "metric-delta-down"
    except (TypeError, ValueError):
        return ""


def _peer_links(text: str) -> str:
    """Convert [[code|name]] markup to company-link spans."""
    def _replace(m: re.Match) -> str:
        code = m.group(1).strip()
        name = m.group(2).strip()
        ctx = json.dumps({"stock_code": code, "stock_name": name}, ensure_ascii=False)
        return (
            f'<span class="company-link" data-flipbook-action="peer_switch" '
            f"data-flipbook-context='{ctx}'>{_e(name)}</span>"
        )
    return re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", _replace, text or "")


def _metric_card(label: str, value: str, delta: str | None = None,
                 badge: str | None = None) -> str:
    delta_html = ""
    if delta is not None:
        cls = _delta_class(
            float(delta.replace("+", "").replace("%", "").replace("—", "0") or "0")
        )
        delta_html = f'  <span class="{cls}">{_e(delta)}</span>\n'
    badge_html = f'  <span class="percentile-badge">{_e(badge)}</span>\n' if badge else ""
    # CSS expects: label (small, above) then value (large, below)
    return (
        '<div class="metric-card">\n'
        f'  <span class="metric-label">{_e(label)}</span>\n'
        f'  <span class="metric-value">{_e(value)}</span>\n'
        f'{delta_html}'
        f'{badge_html}'
        '</div>'
    )


# ── Section renderers ─────────────────────────────────────────────────────────

def _section_hero(code: str, name: str, hero: dict, kpi: dict) -> str:
    industry = _e(hero.get("industry", ""))
    market = _e(hero.get("exchange", "A股"))
    mcap = _fmt(kpi.get("market_cap_yi"), 1, " 亿元")
    as_of = _e(hero.get("as_of") or kpi.get("as_of", ""))
    return f"""\
<section class="section hero">
  <div class="hero-title">
    <h1>{_e(name)}</h1>
    <span class="code-badge">{_e(code)} · {market}</span>
    {f'<span class="industry-tag">{industry}</span>' if industry else ''}
  </div>
  <div class="hero-meta">
    <span>总市值 {mcap}</span>
    {f'<span class="data-as-of">截至 {as_of}</span>' if as_of else ''}
  </div>
</section>"""


def _section_nav() -> str:
    return """\
<nav class="toc section">
  <a href="#kpi">关键指标</a> <a href="#business">业务概览</a>
  <a href="#price">股价走势</a> <a href="#financials">财务摘要</a>
  <a href="#quarterly">季度趋势</a> <a href="#valuation">估值分析</a>
  <a href="#industry">行业背景</a> <a href="#peers">可比公司</a>
  <a href="#news">近期动态</a> <a href="#announcements">公司公告</a>
  <a href="#catalysts">催化剂与风险</a> <a href="#analysis">深度分析</a>
  <a href="#drill-deeper">深入研究</a>
</nav>"""


def _section_kpi(kpi: dict) -> str:
    pe = kpi.get("pe_ttm")
    pb = kpi.get("pb")
    pe_pct = kpi.get("pe_percentile")
    pb_pct = kpi.get("pb_percentile")

    pe_badge = f"历史 {pe_pct}%分位" if pe_pct is not None else None
    pb_badge = f"历史 {pb_pct}%分位" if pb_pct is not None else None

    price_str = _fmt(kpi.get("price"), 2)
    hi_lo = f"{_fmt(kpi.get('week52_high'), 2)} / {_fmt(kpi.get('week52_low'), 2)}"

    cards = "\n".join([
        _metric_card("当前价", price_str),
        _metric_card("52周高/低", hi_lo),
        _metric_card("PE (TTM)", _fmt(pe, 2), badge=pe_badge),
        _metric_card("PB", _fmt(pb, 2), badge=pb_badge),
        _metric_card("总市值", _fmt(kpi.get("market_cap_yi"), 1, " 亿元")),
        _metric_card("ROE", _fmt(kpi.get("roe_pct"), 2, "%")),
        _metric_card("毛利率", _fmt(kpi.get("gross_margin_pct"), 2, "%")),
        _metric_card("股息率", _fmt(kpi.get("dividend_yield_pct"), 2, "%")),
    ])
    as_of = kpi.get("as_of", "")
    return f"""\
<section class="section" id="kpi">
  <h2>关键指标</h2>
  <div class="kpi-grid">
{cards}
  </div>
  {f'<p class="data-as-of">截至 {_e(as_of)}</p>' if as_of else ''}
</section>"""


def _section_business(text: str) -> str:
    body = _peer_links(_e(text)) if text else '<p class="data-unavailable">数据暂不可用</p>'
    return f"""\
<section class="section" id="business">
  <h2>业务概览</h2>
  <p class="narrative">{body}</p>
</section>"""


def _section_price(kline_svg: str) -> str:
    chart = kline_svg or '<p class="data-unavailable">K线图数据暂不可用</p>'
    return f"""\
<section class="section" id="price">
  <h2>股价走势（近1年）</h2>
  <div class="chart-container">
{chart}
  </div>
</section>"""


def _section_financials(annual: list[dict], peer_bar_svg: str, cagr: str) -> str:
    if not annual:
        body = '<p class="data-unavailable">财务数据暂不可用</p>'
    else:
        rows = ""
        for row in annual:
            rev_yoy = row.get("revenue_yoy_pct")
            yoy_html = (
                f'<span class="{_delta_class(rev_yoy)}">{_pct(rev_yoy)}</span>'
                if rev_yoy is not None else "—"
            )
            rows += (
                f"<tr><td>{_e(row.get('period',''))}</td>"
                f"<td>{_fmt(row.get('revenue_yi'), 2)} 亿</td>"
                f"<td>{yoy_html}</td>"
                f"<td>{_fmt(row.get('net_profit_yi'), 2)} 亿</td>"
                f"<td>{_fmt(row.get('gross_margin_pct'), 2)}%</td>"
                f"<td>{_fmt(row.get('roe_pct'), 2)}%</td></tr>\n"
            )
        body = f"""\
<table class="fin-table">
  <thead><tr>
    <th>报告期</th><th>营收</th><th>营收同比</th>
    <th>净利润</th><th>毛利率</th><th>ROE</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""

    cagr_html = f'<p class="narrative">{_e(cagr)}</p>' if cagr else ""
    chart_html = f'<div class="chart-container">{peer_bar_svg}</div>' if peer_bar_svg else ""

    return f"""\
<section class="section" id="financials">
  <h2>财务摘要（年度）</h2>
  {body}
  {chart_html}
  {cagr_html}
</section>"""


def _section_quarterly(quarterly: list[dict], observation: str) -> str:
    if not quarterly:
        body = '<p class="data-unavailable">季度数据暂不可用</p>'
    else:
        rows = ""
        for row in quarterly:
            rev_yoy = row.get("revenue_yoy_pct")
            profit_yoy = row.get("profit_yoy_pct")
            rows += (
                f"<tr><td>{_e(row.get('period',''))}</td>"
                f"<td>{_fmt(row.get('revenue_yi'), 2)} 亿</td>"
                f"<td><span class='{_delta_class(rev_yoy)}'>{_pct(rev_yoy)}</span></td>"
                f"<td>{_fmt(row.get('net_profit_yi'), 2)} 亿</td>"
                f"<td><span class='{_delta_class(profit_yoy)}'>{_pct(profit_yoy)}</span></td>"
                f"</tr>\n"
            )
        body = f"""\
<table class="fin-table">
  <thead><tr>
    <th>季度</th><th>营收</th><th>营收YoY</th>
    <th>净利润</th><th>净利润YoY</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""
    obs_html = f'<p class="narrative">{_e(observation)}</p>' if observation else ""
    return f"""\
<section class="section" id="quarterly">
  <h2>季度趋势</h2>
  {body}
  {obs_html}
</section>"""


def _section_valuation(val: dict, comment: str) -> str:
    pe = val.get("pe_ttm")
    pb = val.get("pb")
    ev = val.get("ev_ebitda")
    pe_pct = val.get("pe_percentile")
    peer_pe = val.get("peer_median_pe")

    cards_html = "\n".join([
        _metric_card("PE (TTM)", _fmt(pe, 2), badge=f"历史 {pe_pct}%分位" if pe_pct is not None else None),
        _metric_card("PB", _fmt(pb, 2)),
        _metric_card("EV/EBITDA", _fmt(ev, 2)),
        _metric_card("可比公司中位PE", _fmt(peer_pe, 2)),
    ])
    comment_html = f'<p class="narrative">{_e(comment)}</p>' if comment else ""
    return f"""\
<section class="section" id="valuation">
  <h2>估值分析</h2>
  <div class="kpi-grid">
{cards_html}
  </div>
  {comment_html}
</section>"""


def _section_industry(text: str) -> str:
    body = _peer_links(_e(text)) if text else '<p class="data-unavailable">数据暂不可用</p>'
    return f"""\
<section class="section" id="industry">
  <h2>行业背景</h2>
  <p class="narrative">{body}</p>
</section>"""


def _section_peers(peers: list[dict], peers_meta: dict, narrative: str) -> str:
    industry = peers_meta.get("industry", "")
    confidence = peers_meta.get("confidence", "medium")
    low_note = peers_meta.get("low_confidence_note", False)

    if not peers:
        table_html = '<p class="data-unavailable">未找到强相关可比公司，建议人工筛选</p>'
    else:
        rows = ""
        for p in peers:
            rows += (
                f"<tr>"
                f"<td>{_e(p.get('name',''))}</td>"
                f"<td>{_e(p.get('code',''))}</td>"
                f"<td>{_fmt(p.get('market_cap_yi'), 1)}</td>"
                f"<td>{_fmt(p.get('pe_ttm'), 2)}</td>"
                f"<td>{_e(p.get('reason',''))}</td>"
                f"</tr>\n"
            )
        low_note_html = (
            '<p class="chart-caption">该行业分类覆盖范围较广，以下公司仅供参考</p>\n'
            if low_note else ""
        )
        industry_cap = (
            f'<p class="chart-caption">可比公司参照行业：<strong>{_e(industry)}</strong></p>\n'
            if industry else ""
        )
        table_html = f"""\
{low_note_html}{industry_cap}<table class="peer-table">
  <thead><tr>
    <th>名称</th><th>代码</th><th>市值(亿)</th><th>PE</th><th>同行理由</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>"""

    narrative_html = ""
    if narrative:
        narrative_html = f'<p class="narrative">{_peer_links(_e(narrative))}</p>'

    return f"""\
<section class="section" id="peers">
  <h2>可比公司</h2>
  {table_html}
  {narrative_html}
</section>"""


def _section_news(news: list[dict]) -> str:
    if not news:
        body = '<p class="data-unavailable">暂无近期新闻</p>'
    else:
        items_html = ""
        for item in news[:7]:
            url = item.get("url", "#")
            title = _e(item.get("title", ""))
            date = _e(item.get("date", ""))
            summary = _e(item.get("summary", ""))
            items_html += f"""\
<div class="news-item">
  <h3><a href="{_e(url)}" target="_blank" rel="noopener">{title}</a></h3>
  <span class="news-date">{date}</span>
  <p>{summary}</p>
</div>
"""
        body = items_html
    return f"""\
<section class="section" id="news">
  <h2>近期动态</h2>
  {body}
</section>"""


def _section_announcements(announcements: list[dict]) -> str:
    if not announcements:
        body = '<p class="data-unavailable">近期无重大公告</p>'
    else:
        items_html = ""
        for item in announcements[:5]:
            title = _e(item.get("title", ""))
            date = _e(item.get("date", ""))
            summary = _e(item.get("summary", ""))
            items_html += f"""\
<div class="ann-item">
  <h3>{title}</h3>
  <span class="ann-date">{date}</span>
  <p>{summary}</p>
</div>
"""
        body = items_html
    return f"""\
<section class="section" id="announcements">
  <h2>公司公告</h2>
  {body}
</section>"""


def _section_catalysts(risks: list[dict]) -> str:
    if not risks:
        body = '<p class="data-unavailable">暂无数据</p>'
    else:
        items_html = '<ul class="risk-list">\n'
        for r in risks[:5]:
            text = _e(r.get("text", ""))
            source = _e(r.get("source", ""))
            date = _e(r.get("date", ""))
            meta = f" <span class='risk-meta'>({source}{', ' + date if date else ''})</span>" if source or date else ""
            items_html += f"  <li>{text}{meta}</li>\n"
        items_html += "</ul>"
        body = items_html
    return f"""\
<section class="section" id="catalysts">
  <h2>催化剂与风险</h2>
  {body}
</section>"""


def _section_analysis(analysis: str, pull_quote: str) -> str:
    if not analysis:
        body = '<p class="data-unavailable">数据暂不可用</p>'
        quote_html = ""
    else:
        paragraphs = [p.strip() for p in analysis.split("\n\n") if p.strip()]
        body_parts = []
        quote_inserted = False
        for i, para in enumerate(paragraphs):
            body_parts.append(f'<p class="narrative">{_peer_links(_e(para))}</p>')
            # Insert pull quote after 2nd paragraph
            if i == 1 and pull_quote and not quote_inserted:
                body_parts.append(
                    f'<blockquote class="pull-quote">{_e(pull_quote)}</blockquote>'
                )
                quote_inserted = True
        if pull_quote and not quote_inserted:
            body_parts.append(
                f'<blockquote class="pull-quote">{_e(pull_quote)}</blockquote>'
            )
        body = "\n".join(body_parts)
        quote_html = ""
    return f"""\
<section class="section" id="analysis">
  <h2>深度分析</h2>
  {body}
</section>"""


def _section_drill_deeper(code: str, name: str) -> str:
    ctx = json.dumps({"stock_code": code, "stock_name": name}, ensure_ascii=False)
    return f"""\
<section class="section drill-deeper" id="drill-deeper">
  <h2>深入研究</h2>
  <p class="drill-deeper-intro">从这里继续深入特定维度：</p>
  <div class="drill-grid">
    <a class="drill-card available" data-flipbook-action="business_breakdown"
       data-flipbook-context='{ctx}'>
      <span class="drill-card-icon">📊</span><span class="drill-card-title">业务拆解</span>
      <span class="drill-card-desc">收入结构、产品线毛利、客户集中度</span></a>
    <a class="drill-card available" data-flipbook-action="valuation_deep"
       data-flipbook-context='{ctx}'>
      <span class="drill-card-icon">📐</span><span class="drill-card-title">估值三角</span>
      <span class="drill-card-desc">历史分位、海外可比、隐含增长率</span></a>
    <a class="drill-card available" data-flipbook-action="peer_comparison_deep"
       data-flipbook-context='{ctx}'>
      <span class="drill-card-icon">⚖️</span><span class="drill-card-title">同行对比</span>
      <span class="drill-card-desc">多维财务指标 + 业务定位差异</span></a>
    <a class="drill-card coming-soon" data-flipbook-action="capital_flow"
       data-flipbook-context='{ctx}'>
      <span class="drill-card-icon">💧</span><span class="drill-card-title">资金流向</span>
      <span class="drill-card-desc">机构 / 北向 / 龙虎榜</span>
      <span class="drill-card-tag">v0.2</span></a>
    <a class="drill-card coming-soon" data-flipbook-action="sentiment_analysis"
       data-flipbook-context='{ctx}'>
      <span class="drill-card-icon">🌡️</span><span class="drill-card-title">情绪分析</span>
      <span class="drill-card-desc">大盘 / 板块 / 个股三层情绪</span>
      <span class="drill-card-tag">v0.2</span></a>
    <a class="drill-card coming-soon" data-flipbook-action="event_timeline"
       data-flipbook-context='{ctx}'>
      <span class="drill-card-icon">📅</span><span class="drill-card-title">事件时间线</span>
      <span class="drill-card-desc">关键事件 × 股价反应</span>
      <span class="drill-card-tag">v0.2</span></a>
  </div>
</section>"""


# ── Main renderer ──────────────────────────────────────────────────────────────

def render_stock_overview(data: dict, charts: dict[str, str]) -> str:
    """
    Render a stock-overview JSON payload to a complete HTML page.

    charts: {"kline": svg_str, "peer_bar": svg_str} from chart_service.generate_charts()
    """
    meta = data.get("meta", {})
    code = meta.get("stock_code", "")
    name = meta.get("stock_name", "")
    as_of = meta.get("as_of", "")

    kpi = data.get("kpi", {})
    hero = data.get("hero", {})

    sections = "\n".join([
        _section_hero(code, name, hero, kpi),
        _section_nav(),
        _section_kpi(kpi),
        _section_business(data.get("business_overview", "")),
        _section_price(charts.get("kline", "")),
        _section_financials(
            data.get("financials_annual", []),
            charts.get("peer_bar", ""),
            data.get("financials_cagr", ""),
        ),
        _section_quarterly(
            data.get("financials_quarterly", []),
            data.get("quarterly_observation", ""),
        ),
        _section_valuation(
            data.get("valuation", {}),
            data.get("valuation_comment", ""),
        ),
        _section_industry(data.get("industry_context", "")),
        _section_peers(
            data.get("peers", []),
            data.get("peers_meta", {}),
            data.get("peers_narrative", ""),
        ),
        _section_news(data.get("news", [])),
        _section_announcements(data.get("announcements", [])),
        _section_catalysts(data.get("catalysts_risks", [])),
        _section_analysis(data.get("analysis", ""), data.get("pull_quote", "")),
        _section_drill_deeper(code, name),
    ])

    title = f"{_e(name)} ({_e(code)}) — 总览"
    footer_date = as_of[:10] if as_of else "—"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="/static/foliopage.css">
  <style>
    /* page-specific tweaks only — shared styles live in foliopage.css */
    .code-badge{{ font-family: monospace }}
  </style>
</head>
<body>
{sections}
<footer>
  <p class="disclaimer">本页面由 AI 生成，仅供研究参考，不构成投资建议</p>
  <p class="data-as-of">截至 {_e(footer_date)}</p>
</footer>
<script src="/static/flipbook.js"></script>
</body>
</html>"""


def render_valuation_deep(data: dict, charts: dict[str, str]) -> str:
    """
    Render a valuation-deep JSON payload to a complete HTML page.

    charts: {"pe_band": svg, "peer_bar": svg, "radar": svg}
    """
    meta = data.get("meta", {})
    code = meta.get("stock_code", "")
    name = meta.get("stock_name", "")
    as_of = meta.get("as_of", "")
    hero = data.get("hero", {})
    kpi = data.get("kpi", {})

    def _fmt(v: float | None, suffix: str = "", decimals: int = 2) -> str:
        if v is None:
            return "—"
        return f"{v:.{decimals}f}{suffix}"

    def _badge(pct: int | float | None) -> str:
        if pct is None:
            return ""
        pct_i = int(pct)
        color = ("green" if pct_i < 30 else "amber" if pct_i <= 70 else "red")
        label = ("历史低位" if pct_i < 30 else "历史中位" if pct_i <= 70 else "历史高位")
        style_map = {
            "green": "background:#dcfce7;color:#166534",
            "amber": "background:#fef9c3;color:#854d0e",
            "red":   "background:#fee2e2;color:#991b1b",
        }
        return (f'<span class="percentile-badge" style="{style_map[color]}">'
                f'{pct_i}th pct · {label}</span>')

    # ── Section 1: KPI snapshot ──────────────────────────────────────────────
    pe_ttm = kpi.get("pe_ttm")
    pb     = kpi.get("pb")
    ev     = kpi.get("ev_ebitda")
    pct    = kpi.get("pe_percentile")
    div    = kpi.get("dividend_yield_pct")
    roe    = kpi.get("roe_pct")

    kpi_cards = "\n".join([
        _metric_card("PE (TTM)", _fmt(pe_ttm, "x"), badge=_badge(pct)),
        _metric_card("PB",       _fmt(pb, "x")),
        _metric_card("EV/EBITDA", _fmt(ev, "x")),
        _metric_card("PE 历史百分位", _fmt(pct, "%", 0) if pct is not None else "—"),
        _metric_card("股息率",   _fmt(div, "%")),
        _metric_card("ROE",      _fmt(roe, "%")),
    ])
    s1 = f"""\
<section class="section" id="valuation-kpi">
  <h2>估值快照</h2>
  <p class="narrative">{_peer_links(_e(data.get("valuation_snapshot", "")))}</p>
  <div class="kpi-grid">{kpi_cards}</div>
</section>"""

    # ── Section 2: PE band ───────────────────────────────────────────────────
    pe_chart = charts.get("pe_band", "") or '<p class="data-unavailable">PE 历史数据暂不可用</p>'
    s2 = f"""\
<section class="section" id="pe-band">
  <h2>历史 PE 区间</h2>
  <div class="chart-container">{pe_chart}</div>
  <p class="narrative">{_peer_links(_e(data.get("pe_band_narrative", "")))}</p>
</section>"""

    # ── Section 3: Peer comparison ───────────────────────────────────────────
    peer_bar_chart = charts.get("peer_bar", "") or '<p class="data-unavailable">同行 PE 图表暂不可用</p>'
    radar_chart    = charts.get("radar", "")    or '<p class="data-unavailable">雷达图暂不可用</p>'

    # Peer table
    rows = []
    for p in data.get("peers", []):
        pname = p.get("name", p.get("code", ""))
        rows.append(
            f'<tr>'
            f'<td>{_e(pname)}</td>'
            f'<td>{_fmt(p.get("pe_ttm"), "x")}</td>'
            f'<td>{_fmt(p.get("pb"), "x")}</td>'
            f'<td>{_fmt(p.get("ev_ebitda"), "x")}</td>'
            f'<td>{_fmt(p.get("roe_pct"), "%")}</td>'
            f'<td>{_fmt(p.get("gross_margin_pct"), "%")}</td>'
            f'</tr>'
        )
    peer_rows = "\n".join(rows)
    peer_table = (
        '<table class="peer-table">'
        '<thead><tr><th>公司</th><th>PE</th><th>PB</th><th>EV/EBITDA</th><th>ROE</th><th>毛利率</th></tr></thead>'
        f'<tbody>{peer_rows}</tbody>'
        '</table>'
    ) if rows else '<p class="data-unavailable">暂无可比公司数据</p>'

    # Implied growth note
    igr = data.get("implied_growth_rate")
    igr_note = data.get("implied_growth_note", "")
    implied_block = ""
    if igr is not None or igr_note:
        implied_block = (
            f'<p class="narrative data-inferred">{_e(igr_note)}</p>'
        )

    s3 = f"""\
<section class="section" id="peer-comparison">
  <h2>同行估值对比</h2>
  <div class="chart-container">{peer_bar_chart}</div>
  <div class="chart-container">{radar_chart}</div>
  {peer_table}
  <p class="narrative">{_peer_links(_e(data.get("peer_narrative", "")))}</p>
  {implied_block}
</section>"""

    # ── Section 4: Valuation narrative ───────────────────────────────────────
    analyst_low  = data.get("analyst_target_low")
    analyst_high = data.get("analyst_target_high")
    analyst_n    = data.get("analyst_count")
    analyst_line = ""
    if analyst_low is not None or analyst_high is not None:
        rng = f"{_fmt(analyst_low)}–{_fmt(analyst_high)}" if analyst_low and analyst_high else _fmt(analyst_low or analyst_high)
        n_str = f"（{analyst_n} 家机构）" if analyst_n else ""
        analyst_line = f'<p class="chart-caption">分析师目标价区间：{rng} 元{n_str}</p>'

    narrative_paras = data.get("valuation_narrative", "")
    paras_html = "".join(
        f'<p class="narrative">{_peer_links(_e(p.strip()))}</p>'
        for p in narrative_paras.split("\n\n") if p.strip()
    )

    pull_q = data.get("pull_quote", "")
    pull_html = f'<blockquote class="pull-quote">{_e(pull_q)}</blockquote>' if pull_q else ""

    s4 = f"""\
<section class="section" id="valuation-context">
  <h2>估值解读</h2>
  {analyst_line}
  {paras_html}
  {pull_html}
</section>"""

    # ── TOC nav ──────────────────────────────────────────────────────────────
    nav = """\
<nav class="section toc">
  <a href="#valuation-kpi">估值快照</a>
  <a href="#pe-band">历史 PE</a>
  <a href="#peer-comparison">同行对比</a>
  <a href="#valuation-context">估值解读</a>
</nav>"""

    # ── Hero ─────────────────────────────────────────────────────────────────
    exchange = hero.get("exchange", "")
    industry = hero.get("industry", "")
    hero_html = f"""\
<section class="section hero">
  <div class="hero-title">
    <h1>{_e(name)}</h1>
    <span class="code-badge">{_e(code)}</span>
    <span class="industry-tag">{_e(industry)}</span>
  </div>
  <div class="hero-meta">{_e(exchange)} · 估值深度分析</div>
</section>"""

    sections = "\n".join([hero_html, nav, s1, s2, s3, s4])
    title = f"{_e(name)} ({_e(code)}) — 估值深度"
    footer_date = as_of[:10] if as_of else "—"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="/static/foliopage.css">
  <style>
    /* page-specific tweaks only — shared styles live in foliopage.css */
    .code-badge{{ font-family: monospace }}
  </style>
</head>
<body>
{sections}
<footer>
  <p class="disclaimer">本页面由 AI 生成，仅供研究参考，不构成投资建议</p>
  <p class="data-as-of">截至 {_e(footer_date)}</p>
</footer>
<script src="/static/flipbook.js"></script>
</body>
</html>"""


def _html_shell(title: str, body: str, footer_date: str) -> str:
    """Common HTML shell shared by all skill renderers."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="/static/foliopage.css">
  <style>
    /* page-specific tweaks only — shared styles live in foliopage.css */
    .code-badge{{ font-family: monospace }}
  </style>
</head>
<body>
{body}
<footer>
  <p class="disclaimer">本页面由 AI 生成，仅供研究参考，不构成投资建议</p>
  <p class="data-as-of">截至 {_e(footer_date)}</p>
</footer>
<script src="/static/flipbook.js"></script>
</body>
</html>"""


def _drill_hero(code: str, name: str, exchange: str, industry: str, subtitle: str) -> str:
    return f"""\
<section class="section hero">
  <div class="hero-title">
    <h1>{_e(name)}</h1>
    <span class="code-badge">{_e(code)}</span>
    <span class="industry-tag">{_e(industry)}</span>
  </div>
  <div class="hero-meta">{_e(exchange)} · {_e(subtitle)}</div>
</section>"""


def _chart_section(section_id: str, heading: str, svg: str, fallback_msg: str,
                   narrative: str = "", caption: str = "") -> str:
    chart_html = svg or f'<p class="data-unavailable">{fallback_msg}</p>'
    caption_html = f'<p class="chart-caption">{_e(caption)}</p>' if caption else ""
    narr_html = f'<p class="narrative">{_peer_links(_e(narrative))}</p>' if narrative else ""
    return f"""\
<section class="section" id="{section_id}">
  <h2>{heading}</h2>
  {caption_html}
  <div class="chart-container">{chart_html}</div>
  {narr_html}
</section>"""


# ── business-breakdown renderer ───────────────────────────────────────────────

def render_business_breakdown(data: dict, charts: dict[str, str]) -> str:
    meta = data.get("meta", {})
    code, name = meta.get("stock_code", ""), meta.get("stock_name", "")
    as_of = meta.get("as_of", "")
    hero = data.get("hero", {})

    if not data.get("available", True):
        body = f"""\
{_drill_hero(code, name, hero.get("exchange",""), hero.get("industry",""), "业务拆解")}
<section class="section">
  <p class="data-unavailable">该股票的收入分拆数据暂不可用（仅支持 A 股）</p>
</section>"""
        return _html_shell(f"{_e(name)} ({_e(code)}) — 业务拆解",
                           body, as_of[:10] if as_of else "—")

    # Product table
    product_rows = "".join(
        f'<tr><td>{_e(r.get("segment",""))}</td>'
        f'<td>{_fmt_yi(r.get("revenue_yi"))}</td>'
        f'<td>{_fmt_pct(r.get("revenue_pct"))}</td>'
        f'<td>{_fmt_pct(r.get("gross_margin_pct"))}</td>'
        f'<td>{_fmt_pct(r.get("yoy_pct"))}</td></tr>'
        for r in data.get("by_product", [])
    )
    product_table = (
        '<table class="fin-table"><thead><tr>'
        '<th>产品/业务</th><th>营收(亿元)</th><th>占比</th><th>毛利率</th><th>同比</th>'
        '</tr></thead><tbody>' + product_rows + '</tbody></table>'
        if product_rows else '<p class="data-unavailable">产品分拆数据暂不可用</p>'
    )

    # Region table
    region_rows = "".join(
        f'<tr><td>{_e(r.get("region",""))}</td>'
        f'<td>{_fmt_yi(r.get("revenue_yi"))}</td>'
        f'<td>{_fmt_pct(r.get("revenue_pct"))}</td>'
        f'<td>{_fmt_pct(r.get("yoy_pct"))}</td></tr>'
        for r in data.get("by_region", [])
    )
    region_table = (
        '<table class="fin-table"><thead><tr>'
        '<th>地区</th><th>营收(亿元)</th><th>占比</th><th>同比</th>'
        '</tr></thead><tbody>' + region_rows + '</tbody></table>'
        if region_rows else '<p class="data-unavailable">地区拆分数据暂不可用</p>'
    )

    peer_bar_html = charts.get("peer_bar", "") or '<p class="data-unavailable">同行毛利率图表暂不可用</p>'
    pull_q = data.get("pull_quote", "")
    pull_html = f'<blockquote class="pull-quote">{_e(pull_q)}</blockquote>' if pull_q else ""

    analysis_html = "".join(
        f'<p class="narrative">{_peer_links(_e(p.strip()))}</p>'
        for p in data.get("structural_analysis", "").split("\n\n") if p.strip()
    )

    sections = "\n".join([
        _drill_hero(code, name, hero.get("exchange",""), hero.get("industry",""), "业务拆解"),
        '<nav class="section toc"><a href="#overview">业务概述</a>'
        '<a href="#products">产品结构</a><a href="#regions">地区分布</a>'
        '<a href="#analysis">结构分析</a></nav>',
        f'<section class="section" id="overview"><h2>业务概述</h2>'
        f'<p class="narrative">{_peer_links(_e(data.get("business_overview","")))}</p></section>',
        f'<section class="section" id="products"><h2>产品/业务分拆</h2>'
        f'{product_table}'
        f'<div class="chart-container">{peer_bar_html}</div></section>',
        f'<section class="section" id="regions"><h2>地区分布</h2>{region_table}</section>',
        f'<section class="section" id="analysis"><h2>结构分析</h2>'
        f'{analysis_html}{pull_html}</section>',
    ])
    return _html_shell(f"{_e(name)} ({_e(code)}) — 业务拆解", sections,
                       as_of[:10] if as_of else "—")


# ── peer-comparison-deep renderer ─────────────────────────────────────────────

def render_peer_comparison_deep(data: dict, charts: dict[str, str]) -> str:
    meta = data.get("meta", {})
    code, name = meta.get("stock_code", ""), meta.get("stock_name", "")
    as_of = meta.get("as_of", "")
    hero = data.get("hero", {})

    def _fmt(v: float | None, suffix: str = "", d: int = 1) -> str:
        return "—" if v is None else f"{v:.{d}f}{suffix}"

    subject = data.get("subject", {})
    peers   = data.get("peers", [])
    all_cos = [subject] + peers

    # Comparison table
    metrics = [
        ("市值(亿)", "market_cap_yi", ""),
        ("PE", "pe_ttm", "x"),
        ("PB", "pb", "x"),
        ("EV/EBITDA", "ev_ebitda", "x"),
        ("毛利率(%)", "gross_margin_pct", "%"),
        ("净利率(%)", "net_margin_pct", "%"),
        ("ROE(%)", "roe_pct", "%"),
        ("营收CAGR(3Y)", "revenue_cagr_3y", "%"),
    ]
    header = "<tr><th>指标</th>" + "".join(
        f'<th{"" if i else " style=\"font-weight:700\""}'
        f'>{_e(c.get("name", c.get("code","")))}</th>'
        for i, c in enumerate(all_cos)
    ) + "</tr>"
    rows = "".join(
        "<tr><td>" + label + "</td>" + "".join(
            f'<td {"style=\"font-weight:600\"" if i == 0 else ""}>'
            + _fmt(c.get(field), suffix) + "</td>"
            for i, c in enumerate(all_cos)
        ) + "</tr>"
        for label, field, suffix in metrics
    )
    comparison_table = f'<table class="peer-table"><thead>{header}</thead><tbody>{rows}</tbody></table>'

    # Positioning matrix
    matrix_rows = "".join(
        f'<tr><td>{_e(q.get("name",""))}</td>'
        f'<td>{_e(q.get("quadrant",""))}</td>'
        f'<td>{_e(q.get("note",""))}</td></tr>'
        for q in data.get("positioning_matrix", [])
    )
    matrix_table = (
        '<table class="peer-table"><thead><tr><th>公司</th><th>定位</th><th>说明</th></tr></thead>'
        f'<tbody>{matrix_rows}</tbody></table>'
        if matrix_rows else ""
    )

    radar = charts.get("radar", "") or '<p class="data-unavailable">雷达图暂不可用</p>'
    bar1 = charts.get("bar1", "")
    bar2 = charts.get("bar2", "")

    analysis_html = "".join(
        f'<p class="narrative">{_peer_links(_e(p.strip()))}</p>'
        for p in data.get("competitive_analysis", "").split("\n\n") if p.strip()
    )
    pull_q = data.get("pull_quote", "")
    pull_html = f'<blockquote class="pull-quote">{_e(pull_q)}</blockquote>' if pull_q else ""

    sections = "\n".join([
        _drill_hero(code, name, "", hero.get("industry",""), "同行对比"),
        '<nav class="section toc"><a href="#overview">总览雷达</a>'
        '<a href="#table">多维对比</a><a href="#positioning">定位矩阵</a>'
        '<a href="#analysis">竞争分析</a></nav>',
        f'<section class="section" id="overview"><h2>多维雷达对比</h2>'
        f'<div class="chart-container">{radar}</div></section>',
        f'<section class="section" id="table"><h2>多指标对比</h2>'
        f'{comparison_table}'
        f'{"<div class=\"chart-container\">" + bar1 + "</div>" if bar1 else ""}'
        f'{"<div class=\"chart-container\">" + bar2 + "</div>" if bar2 else ""}'
        f'</section>',
        f'<section class="section" id="positioning"><h2>业务定位矩阵</h2>{matrix_table}</section>',
        f'<section class="section" id="analysis"><h2>竞争格局分析</h2>'
        f'{analysis_html}{pull_html}</section>',
    ])
    return _html_shell(f"{_e(name)} ({_e(code)}) — 同行对比", sections,
                       as_of[:10] if as_of else "—")


# ── peer-comparison renderer ──────────────────────────────────────────────────

def render_peer_comparison(data: dict, charts: dict[str, str]) -> str:
    as_of = data.get("meta", {}).get("as_of", "")
    subject = data.get("subject", {})
    peer    = data.get("peer", {})
    s_name = subject.get("name", subject.get("code", ""))
    p_name = peer.get("name", peer.get("code", ""))

    def _fmt(v: float | None, suffix: str = "", d: int = 2) -> str:
        return "—" if v is None else f"{v:.{d}f}{suffix}"

    # Side-by-side hero
    s_ctx = json.dumps({"stock_code": subject.get("code",""),
                        "stock_name": s_name}, ensure_ascii=False)
    p_ctx = json.dumps({"stock_code": peer.get("code",""),
                        "stock_name": p_name}, ensure_ascii=False)
    hero_html = f"""\
<section class="section hero">
  <div style="display:flex;gap:2rem;align-items:center;flex-wrap:wrap">
    <div>
      <h1>{_e(s_name)} <span class="code-badge">{_e(subject.get("code",""))}</span></h1>
      <span class="industry-tag">{_e(subject.get("industry",""))}</span>
    </div>
    <div style="font-size:1.5rem;color:var(--text-muted)">VS</div>
    <div class="company-link" data-flipbook-action="peer_switch"
         data-flipbook-context='{p_ctx}'>
      <h2 style="display:inline">{_e(p_name)} <span class="code-badge">{_e(peer.get("code",""))}</span></h2>
      <span class="industry-tag" style="margin-left:.5rem">{_e(peer.get("industry",""))}</span>
    </div>
  </div>
</section>"""

    radar = charts.get("radar", "") or '<p class="data-unavailable">雷达图暂不可用</p>'

    # Metric table
    table_rows = "".join(
        f'<tr><td>{_e(r.get("metric",""))}</td>'
        f'<td><strong>{_e(r.get("subject_value","—"))}</strong></td>'
        f'<td>{_e(r.get("peer_value","—"))}</td></tr>'
        for r in data.get("comparison_table", [])
    )
    metric_table = (
        f'<table class="peer-table"><thead><tr>'
        f'<th>指标</th><th>{_e(s_name)}</th><th>{_e(p_name)}</th>'
        f'</tr></thead><tbody>{table_rows}</tbody></table>'
        if table_rows else ""
    )

    s_leads = data.get("subject_leads", "")
    p_leads = data.get("peer_leads", "")

    sections = "\n".join([
        hero_html,
        '<nav class="section toc"><a href="#radar">雷达对比</a>'
        '<a href="#metrics">指标对比</a><a href="#narrative">差异分析</a></nav>',
        f'<section class="section" id="radar"><h2>多维雷达</h2>'
        f'<div class="chart-container">{radar}</div></section>',
        f'<section class="section" id="metrics"><h2>指标对比</h2>{metric_table}</section>',
        f'<section class="section" id="narrative"><h2>差异分析</h2>'
        f'<p class="narrative">{_peer_links(_e(s_leads))}</p>'
        f'<p class="narrative">{_peer_links(_e(p_leads))}</p></section>',
    ])
    return _html_shell(f"{_e(s_name)} vs {_e(p_name)}", sections,
                       as_of[:10] if as_of else "—")


# ── metric-drilldown renderer ─────────────────────────────────────────────────

def render_metric_drilldown(data: dict, charts: dict[str, str]) -> str:
    meta = data.get("meta", {})
    code, name = meta.get("stock_code", ""), meta.get("stock_name", "")
    as_of = meta.get("as_of", "")
    hero = data.get("hero", {})
    metric_display = data.get("metric_display", data.get("metric_key", ""))
    current = data.get("metric_current")
    ago_1y  = data.get("metric_1y_ago")
    pct     = data.get("metric_percentile")

    def _fmt(v: float | None, d: int = 2) -> str:
        return "—" if v is None else f"{v:.{d}f}"

    kpi_cards = "\n".join([
        _metric_card("当前值", _fmt(current)),
        _metric_card("1 年前", _fmt(ago_1y)),
        _metric_card("历史分位", f"{int(pct)}%" if pct is not None else "—"),
    ])

    primary_chart = charts.get("primary", "") or '<p class="data-unavailable">图表数据暂不可用</p>'
    peer_bar = charts.get("peer_bar", "")
    peer_bar_html = f'<div class="chart-container">{peer_bar}</div>' if peer_bar else ""

    history_html = "".join(
        f'<p class="narrative">{_peer_links(_e(p.strip()))}</p>'
        for p in data.get("history_narrative", "").split("\n\n") if p.strip()
    )
    peer_narr = data.get("peer_narrative", "")

    # Related peers back-links
    peer_links_html = "".join(
        f'<li><span class="company-link" data-flipbook-action="peer_switch"'
        f' data-flipbook-context=\'{json.dumps({"stock_code": p.get("code",""), "stock_name": p.get("name","")}, ensure_ascii=False)}\'>'
        f'{_e(p.get("name",""))} ({_e(p.get("code",""))})</span></li>'
        for p in data.get("related_peers", [])
    )

    s_ctx = json.dumps({"stock_code": code, "stock_name": name}, ensure_ascii=False)
    breadcrumb = (
        f'<span class="company-link" data-flipbook-action="peer_switch"'
        f' data-flipbook-context=\'{s_ctx}\'>{_e(name)} ({_e(code)})</span>'
        f' › {_e(metric_display)}'
    )

    sections = "\n".join([
        f'<section class="section hero">'
        f'<p class="breadcrumb">{breadcrumb}</p>'
        f'<h1>{_e(metric_display)}</h1>'
        f'<div class="kpi-grid">{kpi_cards}</div></section>',
        f'<section class="section" id="chart"><h2>历史走势</h2>'
        f'<div class="chart-container">{primary_chart}</div></section>',
        f'<section class="section" id="peers"><h2>同行对比</h2>'
        f'{peer_bar_html}'
        f'<p class="narrative">{_peer_links(_e(peer_narr))}</p></section>',
        f'<section class="section" id="narrative"><h2>解读</h2>{history_html}</section>',
        f'<section class="section" id="related"><h2>相关页面</h2><ul>{peer_links_html}</ul></section>'
        if peer_links_html else "",
    ])
    return _html_shell(f"{_e(name)} ({_e(code)}) — {_e(metric_display)}", sections,
                       as_of[:10] if as_of else "—")


# ── news-timeline renderer ────────────────────────────────────────────────────

def render_news_timeline(data: dict, charts: dict[str, str]) -> str:
    meta = data.get("meta", {})
    code, name = meta.get("stock_code", ""), meta.get("stock_name", "")
    as_of = meta.get("as_of", "")
    hero_d = data.get("hero", {})
    timeline = data.get("timeline", [])
    analyst = data.get("analyst", {})

    # Group by week
    from datetime import date as _date
    weeks: dict[str, list[dict]] = {}
    for item in timeline:
        d = item.get("date", "")[:10]
        try:
            iso = _date.fromisoformat(d).isocalendar()
            week_key = f"{iso.year}-W{iso.week:02d}"
        except Exception:
            week_key = d[:7]
        weeks.setdefault(week_key, []).append(item)

    def _item_html(item: dict) -> str:
        is_ann = item.get("type") == "ann"
        cls = "ann-item" if is_ann else "news-item"
        url = item.get("url", "")
        title = item.get("title", "")
        src = item.get("source", "")
        badge = '<span class="ann-badge">公告</span>' if is_ann else f'<span class="news-source">{_e(src)}</span>'
        link_open  = f'<a href="{_e(url)}" target="_blank" rel="noopener">' if url else ""
        link_close = '</a>' if url else ""
        summary = item.get("summary", "")
        return (
            f'<div class="{cls}">'
            f'<span class="{("ann" if is_ann else "news")}-date">{_e(item.get("date",""))}</span> {badge}'
            f'<h3>{link_open}{_e(title)}{link_close}</h3>'
            f'{"<p class=\"narrative\">" + _e(summary) + "</p>" if summary else ""}'
            f'</div>'
        )

    timeline_html = ""
    for week_key in sorted(weeks.keys(), reverse=True):
        items = weeks[week_key]
        timeline_html += f'<h3 class="week-header">{_e(week_key)} 当周</h3>\n'
        timeline_html += "\n".join(_item_html(i) for i in items)

    # Analyst section
    analyst_html = ""
    if analyst.get("available"):
        cards = "\n".join([
            _metric_card("目标价均值", f"{analyst['target_mean']:.0f}" if analyst.get("target_mean") else "—"),
            _metric_card("买入", str(analyst.get("buy_count", "—"))),
            _metric_card("中性", str(analyst.get("neutral_count", "—"))),
            _metric_card("卖出", str(analyst.get("sell_count", "—"))),
        ])
        note = analyst.get("note", "")
        analyst_html = (
            f'<section class="section" id="analyst"><h2>机构观点</h2>'
            f'<div class="kpi-grid">{cards}</div>'
            f'{"<p class=\"narrative\">" + _e(note) + "</p>" if note else ""}'
            f'</section>'
        )
    else:
        analyst_html = '<section class="section" id="analyst"><p class="data-unavailable">暂无公开机构评级数据</p></section>'

    kline = charts.get("kline", "")
    kline_html = f'<div class="chart-container">{kline}</div>' if kline else ""

    s_ctx = json.dumps({"stock_code": code, "stock_name": name}, ensure_ascii=False)
    n_news = hero_d.get("news_count", len([i for i in timeline if i.get("type") == "news"]))
    n_ann  = hero_d.get("ann_count",  len([i for i in timeline if i.get("type") == "ann"]))

    sections = "\n".join([
        f'<section class="section hero">'
        f'<p class="breadcrumb"><span class="company-link" data-flipbook-action="peer_switch"'
        f' data-flipbook-context=\'{s_ctx}\'>{_e(name)} ({_e(code)})</span> › 近期舆情</p>'
        f'<h1>近 30 天舆情</h1>'
        f'<p>共 <strong>{n_news}</strong> 条新闻 · <strong>{n_ann}</strong> 条公告</p>'
        f'</section>',
        f'<section class="section" id="timeline"><h2>时间线</h2>'
        f'{kline_html}'
        f'<div class="timeline">{timeline_html}</div></section>',
        analyst_html,
    ])
    return _html_shell(f"{_e(name)} ({_e(code)}) — 近期舆情", sections,
                       as_of[:10] if as_of else "—")


# ── helpers used by new renderers ─────────────────────────────────────────────

def _fmt_yi(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}"


def _fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}%"


# ── render_page dispatcher ────────────────────────────────────────────────────

def render_page(json_path: Path, workspace: Path, request_id: str) -> str:
    """
    Top-level entry point: read JSON, generate charts, render HTML.
    Dispatches by data["meta"]["skill"].
    Returns the HTML string and also writes it to output/page-<request_id>.html.
    """
    from .chart_service import generate_charts

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot read JSON from {json_path}: {exc}") from exc

    charts = generate_charts(data, workspace)
    skill = data.get("meta", {}).get("skill", "stock-overview")

    renderers = {
        "stock-overview":       render_stock_overview,
        "valuation-deep":       render_valuation_deep,
        "business-breakdown":   render_business_breakdown,
        "peer-comparison-deep": render_peer_comparison_deep,
        "peer-comparison":      render_peer_comparison,
        "metric-drilldown":     render_metric_drilldown,
        "news-timeline":        render_news_timeline,
    }
    renderer = renderers.get(skill)
    if renderer is None:
        raise ValueError(f"No renderer for skill: {skill!r}")
    html = renderer(data, charts)

    # Write HTML alongside the JSON
    html_path = json_path.parent / f"page-{request_id}.html"
    html_path.write_text(html, encoding="utf-8")
    return html
