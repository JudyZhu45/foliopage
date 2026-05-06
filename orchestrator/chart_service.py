"""
Chart generation for the orchestrator renderer.

Calls the chart MCP tool functions directly (no subprocess / MCP protocol)
so chart SVGs are generated server-side after the agent produces JSON output.

K-line data is fetched here directly via get_kline() — the agent no longer
copies kline_bars into its JSON output. By the time this runs, the agent has
already called get_kline() and the result is in ~/.foliopage/cache.db, so the
repeated call returns in <10 ms. If the cache is cold for any reason, the
function falls back to a live akshare/yfinance request transparently.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# Lazy import: only load matplotlib-heavy code when actually called
_kline_svg_fn = None
_peer_bar_svg_fn = None
_pe_band_svg_fn = None
_radar_svg_fn = None
_sparkline_svg_fn = None
_get_kline_fn = None


def _load_chart_fns() -> None:
    global _kline_svg_fn, _peer_bar_svg_fn, _pe_band_svg_fn, _radar_svg_fn
    global _sparkline_svg_fn, _get_kline_fn
    if _kline_svg_fn is not None:
        return
    repo_root = str(Path(__file__).parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from tools.chart_mcp.server import (  # type: ignore[import]
        kline_svg,
        peer_bar_svg,
        pe_band_svg,
        comparison_radar_svg,
        metric_sparkline_svg,
    )
    from tools.stock_mcp.server import get_kline  # type: ignore[import]
    _kline_svg_fn = kline_svg
    _peer_bar_svg_fn = peer_bar_svg
    _pe_band_svg_fn = pe_band_svg
    _radar_svg_fn = comparison_radar_svg
    _sparkline_svg_fn = metric_sparkline_svg
    _get_kline_fn = get_kline


def generate_charts(data: dict, workspace: Path) -> dict[str, str]:
    """
    Generate SVG charts for a stock JSON payload.

    Dispatches by data["meta"]["skill"]. Falls back to empty string on error
    so the page still renders.
    """
    _load_chart_fns()
    skill = data.get("meta", {}).get("skill", "stock-overview")

    dispatch = {
        "stock-overview":      lambda: _generate_overview_charts(data, workspace),
        "valuation-deep":      lambda: _generate_valuation_charts(data),
        "business-breakdown":  lambda: _generate_business_charts(data),
        "peer-comparison-deep": lambda: _generate_peer_deep_charts(data),
        "peer-comparison":     lambda: _generate_peer_comparison_charts(data),
        "metric-drilldown":    lambda: _generate_metric_charts(data),
        "news-timeline":       lambda: _generate_news_charts(data),
    }
    fn = dispatch.get(skill)
    if fn is None:
        log.warning("No chart generator for skill %r — returning empty", skill)
        return {}
    return fn()


# ── stock-overview ────────────────────────────────────────────────────────────

def _generate_overview_charts(data: dict, workspace: Path) -> dict[str, str]:
    stock_code: str = data.get("meta", {}).get("stock_code", "")
    result: dict[str, str] = {}

    try:
        # Fetch kline directly — agent already called get_kline() so cache is warm.
        kline_data = _get_kline_fn(code=stock_code, range="1Y")
        bars: list[dict] = kline_data.get("bars", [])
        result["kline"] = _kline_svg_fn(ohlcv=bars, width=560, height=220)["svg"]
    except Exception as exc:
        log.warning("kline_svg failed for %s: %s", stock_code, exc)
        result["kline"] = ""

    try:
        peers_meta = data.get("peers_meta", {})
        metric: str = peers_meta.get("peer_bar_metric", "营收(亿元)")
        items: list[dict] = peers_meta.get("peer_bar_items", [])
        peer_result = _peer_bar_svg_fn(items=items, metric=metric, highlight_code=stock_code)
        result["peer_bar"] = peer_result["svg"]
    except Exception as exc:
        log.warning("peer_bar_svg failed: %s", exc)
        result["peer_bar"] = ""

    return result


# ── valuation-deep ────────────────────────────────────────────────────────────

def _generate_valuation_charts(data: dict) -> dict[str, str]:
    stock_code: str = data.get("meta", {}).get("stock_code", "")
    result: dict[str, str] = {}

    try:
        pe_history: list[dict] = data.get("pe_history") or []
        current_pe: float | None = (data.get("kpi") or {}).get("pe_ttm")
        pe_result = _pe_band_svg_fn(
            pe_history=pe_history, current_pe=current_pe or 0.0,
        )
        result["pe_band"] = pe_result["svg"]
    except Exception as exc:
        log.warning("pe_band_svg failed: %s", exc)
        result["pe_band"] = ""

    try:
        metric: str = data.get("peer_bar_metric", "PE(TTM)")
        items: list[dict] = data.get("peer_bar_items", [])
        result["peer_bar"] = _peer_bar_svg_fn(items=items, metric=metric,
                                              highlight_code=stock_code)["svg"]
    except Exception as exc:
        log.warning("peer_bar_svg (valuation) failed: %s", exc)
        result["peer_bar"] = ""

    try:
        subject: dict = data.get("radar_subject") or {}
        peers: list[dict] = data.get("radar_peers") or []
        metrics: list[str] = data.get("radar_metrics") or ["pe", "pb", "roe", "gross_margin"]
        result["radar"] = _radar_svg_fn(subject=subject, peers=peers[:5],
                                        metrics=metrics)["svg"]
    except Exception as exc:
        log.warning("comparison_radar_svg failed: %s", exc)
        result["radar"] = ""

    return result


# ── business-breakdown ────────────────────────────────────────────────────────

def _generate_business_charts(data: dict) -> dict[str, str]:
    stock_code: str = data.get("meta", {}).get("stock_code", "")
    result: dict[str, str] = {}
    try:
        metric: str = data.get("peer_bar_metric", "毛利率(%)")
        items: list[dict] = data.get("peer_bar_items", [])
        result["peer_bar"] = _peer_bar_svg_fn(items=items, metric=metric,
                                              highlight_code=stock_code)["svg"]
    except Exception as exc:
        log.warning("peer_bar_svg (business) failed: %s", exc)
        result["peer_bar"] = ""
    return result


# ── peer-comparison-deep ──────────────────────────────────────────────────────

def _generate_peer_deep_charts(data: dict) -> dict[str, str]:
    stock_code: str = data.get("meta", {}).get("stock_code", "")
    result: dict[str, str] = {}

    try:
        subject: dict = data.get("radar_subject") or {}
        peers: list[dict] = data.get("radar_peers") or []
        metrics: list[str] = data.get("radar_metrics") or ["pe", "pb", "gross_margin", "roe"]
        result["radar"] = _radar_svg_fn(subject=subject, peers=peers[:4],
                                        metrics=metrics)["svg"]
    except Exception as exc:
        log.warning("radar (peer-deep) failed: %s", exc)
        result["radar"] = ""

    for key, metric_field, items_field in [
        ("bar1", "bar_metric_1", "bar_items_1"),
        ("bar2", "bar_metric_2", "bar_items_2"),
    ]:
        try:
            metric: str = data.get(metric_field, "")
            items: list[dict] = data.get(items_field, [])
            if metric and items:
                result[key] = _peer_bar_svg_fn(items=items, metric=metric,
                                               highlight_code=stock_code)["svg"]
            else:
                result[key] = ""
        except Exception as exc:
            log.warning("peer_bar_svg (%s) failed: %s", key, exc)
            result[key] = ""

    return result


# ── peer-comparison ───────────────────────────────────────────────────────────

def _generate_peer_comparison_charts(data: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        subject: dict = data.get("radar_subject") or {}
        peer: dict = data.get("radar_peer") or {}
        metrics: list[str] = data.get("radar_metrics") or ["PE", "PB", "ROE", "gross_margin"]
        peers_list = [peer] if peer else []
        result["radar"] = _radar_svg_fn(subject=subject, peers=peers_list,
                                        metrics=metrics)["svg"]
    except Exception as exc:
        log.warning("radar (peer-comparison) failed: %s", exc)
        result["radar"] = ""
    return result


# ── metric-drilldown ──────────────────────────────────────────────────────────

def _generate_metric_charts(data: dict) -> dict[str, str]:
    stock_code: str = data.get("meta", {}).get("stock_code", "")
    category: str = data.get("metric_category", "")
    result: dict[str, str] = {}

    # Primary chart — depends on metric category
    try:
        if category == "valuation":
            pe_history: list[dict] = data.get("pe_history") or []
            current_pe: float | None = data.get("metric_current")
            result["primary"] = _pe_band_svg_fn(
                pe_history=pe_history, current_pe=current_pe or 0.0,
            )["svg"]
        elif category == "price":
            # Fetch kline directly (5Y for price drilldown) — cache already warm.
            kline_data = _get_kline_fn(code=stock_code, range="5Y")
            bars: list[dict] = kline_data.get("bars", [])
            result["primary"] = _kline_svg_fn(ohlcv=bars, width=560, height=220)["svg"]
        else:
            # profitability / income → sparkline
            values: list[float] = [v for v in (data.get("sparkline_values") or [])
                                   if v is not None]
            result["primary"] = _sparkline_svg_fn(values=values, width=360, height=64)["svg"]
    except Exception as exc:
        log.warning("primary chart (metric-drilldown) failed: %s", exc)
        result["primary"] = ""

    # Peer bar
    try:
        metric: str = data.get("peer_bar_metric", "")
        items: list[dict] = data.get("peer_bar_items", [])
        if metric and items:
            result["peer_bar"] = _peer_bar_svg_fn(items=items, metric=metric,
                                                  highlight_code=stock_code)["svg"]
        else:
            result["peer_bar"] = ""
    except Exception as exc:
        log.warning("peer_bar_svg (metric) failed: %s", exc)
        result["peer_bar"] = ""

    return result


# ── news-timeline ─────────────────────────────────────────────────────────────

def _generate_news_charts(data: dict) -> dict[str, str]:
    stock_code: str = data.get("meta", {}).get("stock_code", "")
    result: dict[str, str] = {}
    try:
        # Fetch kline directly (3M for news price strip) — cache already warm.
        kline_data = _get_kline_fn(code=stock_code, range="3M")
        bars: list[dict] = kline_data.get("bars", [])
        result["kline"] = _kline_svg_fn(ohlcv=bars, width=560, height=100)["svg"]
    except Exception as exc:
        log.warning("kline_svg (news-timeline) failed for %s: %s", stock_code, exc)
        result["kline"] = ""
    return result
