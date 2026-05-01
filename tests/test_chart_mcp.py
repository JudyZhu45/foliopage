"""
Tests for tools/chart_mcp/server.py

Run:
    uv run pytest tests/test_chart_mcp.py -v
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 60) -> list[dict]:
    """Generate synthetic OHLCV bars (n days, deterministic)."""
    import math
    bars = []
    price = 100.0
    for i in range(n):
        o = price
        c = price + math.sin(i * 0.3) * 2
        h = max(o, c) + 1.0
        lo = min(o, c) - 1.0
        bars.append({
            "date": f"2024-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
            "open": round(o, 2),
            "high": round(h, 2),
            "low":  round(lo, 2),
            "close": round(c, 2),
            "volume": 1_000_000 + i * 10_000,
        })
        price = c
    return bars


def _assert_valid_svg(svg: str) -> ET.Element:
    """Parse SVG as XML and return root element. Fails with a clear message."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        pytest.fail(f"SVG is not valid XML: {exc}\n---\n{svg[:500]}\n---")
    return root


def _no_hardcoded_colors(svg: str) -> None:
    """
    Scan the SVG body (everything inside <g> blocks) for hardcoded colors.
    Allow fill="none" and structural matplotlib attributes; reject any
    actual hex or rgb() color values inside the drawing content.
    """
    # Extract everything between <g and </svg>
    body = re.sub(r"^.*?<g", "<g", svg, count=1, flags=re.DOTALL)
    # Allow fill="none" and stroke="none" explicitly
    body_no_none = re.sub(r'(?:fill|stroke)="none"', "", body)
    # Also allow fill/stroke in style blocks (those are CSS vars)
    body_no_style = re.sub(r"<style[^>]*>.*?</style>", "", body_no_none, flags=re.DOTALL)

    hits = re.findall(r'(?:fill|stroke|color|stop-color)="(#[0-9a-fA-F]{3,8}|rgb[^"]*)"',
                      body_no_style)
    assert not hits, (
        f"Hardcoded colors found inside SVG drawing content: {hits[:5]}\n"
        "All colors must use CSS var() references."
    )


# ════════════════════════════════════════════════════════════════════════════
# kline_svg tests
# ════════════════════════════════════════════════════════════════════════════

def test_kline_svg_valid_xml():
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    assert "svg" in result
    _assert_valid_svg(result["svg"])


def test_kline_svg_has_viewbox():
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    assert 'viewBox' in result["svg"], "SVG must have a viewBox attribute for responsiveness"


def test_kline_svg_no_hardcoded_colors():
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    _no_hardcoded_colors(result["svg"])


def test_kline_svg_has_css_vars():
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    svg = result["svg"]
    assert "var(--up-color)" in svg, "SVG must reference --up-color"
    assert "var(--down-color)" in svg, "SVG must reference --down-color"


def test_kline_svg_has_title():
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    assert "<title>" in result["svg"], "SVG must contain <title> for accessibility"


def test_kline_svg_x_axis_tick_count():
    """X-axis should have 5–7 date tick labels."""
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    # Date ticks look like 2024-01-01 in the SVG text elements
    date_labels = re.findall(r"\d{4}-\d{2}-\d{2}", result["svg"])
    assert 5 <= len(date_labels) <= 7, (
        f"Expected 5–7 date tick labels, found {len(date_labels)}: {date_labels}"
    )


def test_kline_svg_caption():
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    assert result.get("caption"), "kline_svg must return a non-empty caption"
    assert result.get("as_of"), "kline_svg must return as_of timestamp"


def test_kline_svg_empty_input():
    """kline_svg([]) must return a valid placeholder SVG, not raise."""
    from tools.chart_mcp.server import kline_svg
    result = kline_svg([])
    assert "svg" in result
    _assert_valid_svg(result["svg"])
    assert "No data" in result["svg"] or "no data" in result["svg"].lower()


def test_kline_svg_no_fixed_dimensions():
    """Top-level <svg> tag must NOT carry fixed pixel width/height."""
    from tools.chart_mcp.server import kline_svg
    result = kline_svg(_make_ohlcv(60))
    # Match the opening svg tag only
    svg_tag = re.match(r"<svg[^>]*>", result["svg"])
    assert svg_tag, "Could not find opening <svg> tag"
    tag_text = svg_tag.group(0)
    assert " width=" not in tag_text, (
        f"SVG tag must not carry a fixed width: {tag_text[:200]}"
    )


# ════════════════════════════════════════════════════════════════════════════
# pe_band_svg tests
# ════════════════════════════════════════════════════════════════════════════

def _make_pe_history(n: int = 120) -> list[dict]:
    import math
    return [
        {"date": f"2023-{(i // 30 + 1):02d}-{(i % 30 + 1):02d}",
         "pe": round(20 + math.sin(i * 0.1) * 8, 2)}
        for i in range(n)
    ]


def test_pe_band_svg_valid_xml():
    from tools.chart_mcp.server import pe_band_svg
    result = pe_band_svg(_make_pe_history(120), current_pe=25.0)
    _assert_valid_svg(result["svg"])


def test_pe_band_svg_no_hardcoded_colors():
    from tools.chart_mcp.server import pe_band_svg
    result = pe_band_svg(_make_pe_history(120), current_pe=25.0)
    _no_hardcoded_colors(result["svg"])


def test_pe_band_svg_caption_has_percentile():
    from tools.chart_mcp.server import pe_band_svg
    result = pe_band_svg(_make_pe_history(120), current_pe=25.0)
    assert "percentile" in result["caption"].lower(), (
        f"Caption should mention percentile: {result['caption']}"
    )


def test_pe_band_svg_empty_input():
    from tools.chart_mcp.server import pe_band_svg
    result = pe_band_svg([], current_pe=25.0)
    _assert_valid_svg(result["svg"])


# ════════════════════════════════════════════════════════════════════════════
# comparison_radar_svg tests
# ════════════════════════════════════════════════════════════════════════════

def test_radar_svg_valid_xml():
    from tools.chart_mcp.server import comparison_radar_svg
    subject = {"code": "600519", "name": "贵州茅台", "pe": 25.0, "roe": 30.0, "gross_margin": 90.0}
    peers   = [
        {"code": "000858", "name": "五粮液", "pe": 20.0, "roe": 25.0, "gross_margin": 75.0},
        {"code": "002304", "name": "洋河股份", "pe": 18.0, "roe": 20.0, "gross_margin": 70.0},
    ]
    result = comparison_radar_svg(subject, peers, metrics=["pe", "roe", "gross_margin"])
    _assert_valid_svg(result["svg"])


def test_radar_svg_no_hardcoded_colors():
    from tools.chart_mcp.server import comparison_radar_svg
    subject = {"code": "600519", "name": "茅台", "pe": 25.0, "roe": 30.0, "gross_margin": 90.0}
    result = comparison_radar_svg(subject, [], metrics=["pe", "roe", "gross_margin"])
    _no_hardcoded_colors(result["svg"])


def test_radar_svg_insufficient_metrics():
    from tools.chart_mcp.server import comparison_radar_svg
    result = comparison_radar_svg({"code": "600519"}, [], metrics=["pe"])
    _assert_valid_svg(result["svg"])  # Should return placeholder, not crash


# ════════════════════════════════════════════════════════════════════════════
# metric_sparkline_svg tests
# ════════════════════════════════════════════════════════════════════════════

def test_sparkline_svg_valid_xml():
    from tools.chart_mcp.server import metric_sparkline_svg
    result = metric_sparkline_svg([10.0, 11.0, 12.5, 11.8, 13.0])
    _assert_valid_svg(result["svg"])


def test_sparkline_svg_no_hardcoded_colors():
    from tools.chart_mcp.server import metric_sparkline_svg
    result = metric_sparkline_svg([10.0, 11.0, 12.5, 11.8, 13.0])
    _no_hardcoded_colors(result["svg"])


def test_sparkline_up_uses_up_color():
    from tools.chart_mcp.server import metric_sparkline_svg
    result = metric_sparkline_svg([10.0, 11.0, 13.0])   # last > first → up
    assert "var(--up-color)" in result["svg"], "Rising sparkline must use --up-color"


def test_sparkline_down_uses_down_color():
    from tools.chart_mcp.server import metric_sparkline_svg
    result = metric_sparkline_svg([13.0, 11.0, 10.0])   # last < first → down
    assert "var(--down-color)" in result["svg"], "Falling sparkline must use --down-color"


def test_sparkline_empty_input():
    from tools.chart_mcp.server import metric_sparkline_svg
    result = metric_sparkline_svg([])
    _assert_valid_svg(result["svg"])


# ════════════════════════════════════════════════════════════════════════════
# peer_bar_svg tests
# ════════════════════════════════════════════════════════════════════════════

def _make_peers() -> list[dict]:
    return [
        {"code": "600519", "name": "贵州茅台", "pe": 25.0},
        {"code": "000858", "name": "五粮液",   "pe": 20.0},
        {"code": "002304", "name": "洋河股份", "pe": 18.0},
    ]


def test_peer_bar_svg_valid_xml():
    from tools.chart_mcp.server import peer_bar_svg
    result = peer_bar_svg(_make_peers(), metric="pe", highlight_code="600519")
    _assert_valid_svg(result["svg"])


def test_peer_bar_svg_no_hardcoded_colors():
    from tools.chart_mcp.server import peer_bar_svg
    result = peer_bar_svg(_make_peers(), metric="pe", highlight_code="600519")
    _no_hardcoded_colors(result["svg"])


def test_peer_bar_svg_empty_input():
    from tools.chart_mcp.server import peer_bar_svg
    result = peer_bar_svg([], metric="pe", highlight_code="600519")
    _assert_valid_svg(result["svg"])
