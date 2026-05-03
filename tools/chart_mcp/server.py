"""
chart_mcp — MCP server that generates inline SVG charts for foliopage.

Technique
─────────
1. Render with matplotlib using placeholder hex tokens.
2. Post-process: replace tokens → CSS var() references.
3. Prepend a <style> block with standalone fallback values so the SVG
   renders correctly if viewed outside the foliopage HTML (dark mode
   handled by the parent page's custom properties overriding these).

IMPORTANT: stdout is reserved for MCP JSON-RPC. All logging → stderr.
"""
from __future__ import annotations

import io
import logging
import re
import sys
import threading
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")          # non-interactive backend, must come first
matplotlib.rcParams['font.sans-serif'] = [
    'STHeiti', 'Arial Unicode MS', 'PingFang SC', 'DejaVu Sans', 'sans-serif'
]
matplotlib.rcParams['axes.unicode_minus'] = False   # fix minus sign rendering
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from cachetools import TTLCache
from mcp.server.fastmcp import FastMCP

# ── Disk cache fallback (cross-run persistence) ─────────────────────────────
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
try:
    from _shared.cache_store import disk_get, disk_set, ttl_for  # noqa: E402
except ImportError:  # pragma: no cover
    def disk_get(key): return None
    def disk_set(key, value, ttl_s): return None
    def ttl_for(key): return 0

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("chart_mcp")

# ── MCP server ────────────────────────────────────────────────────────────────
mcp = FastMCP("foliopage-chart")

# ── TTL cache ────────────────────────────────────────────────────────────────
_CACHE: TTLCache = TTLCache(maxsize=256, ttl=900)
_LOCK = threading.Lock()


def _cache_get(key: str) -> Any | None:
    with _LOCK:
        v = _CACHE.get(key)
    if v is not None:
        return v
    v = disk_get(key)
    if v is not None:
        with _LOCK:
            _CACHE[key] = v
    return v


def _cache_set(key: str, val: Any) -> None:
    with _LOCK:
        _CACHE[key] = val
    ttl = ttl_for(key)
    if ttl > 0:
        disk_set(key, val, ttl)


def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Color token system ───────────────────────────────────────────────────────
# Matplotlib renders with these placeholder hex values; _css_vars() then
# replaces them with CSS var() references in the SVG text.

_TOKEN_UP    = "#FF0001"   # → var(--up-color)
_TOKEN_DOWN  = "#FF0002"   # → var(--down-color)
_TOKEN_AXIS  = "#FF0003"   # → var(--axis-color)
_TOKEN_GRID  = "#FF0004"   # → var(--grid-color)
_TOKEN_MUTED = "#FF0005"   # → var(--text-muted)
_TOKEN_ACCENT= "#FF0006"   # → var(--accent)
_TOKEN_BG    = "#FF0007"   # → var(--bg, transparent)

_TOKEN_MAP = {
    _TOKEN_UP.lower():     "var(--up-color)",
    _TOKEN_DOWN.lower():   "var(--down-color)",
    _TOKEN_AXIS.lower():   "var(--axis-color)",
    _TOKEN_GRID.lower():   "var(--grid-color)",
    _TOKEN_MUTED.lower():  "var(--text-muted)",
    _TOKEN_ACCENT.lower(): "var(--accent)",
    _TOKEN_BG.lower():     "transparent",
}

_STYLE_BLOCK = """\
<style>
  :root {
    --up-color:    #16a34a;
    --down-color:  #dc2626;
    --axis-color:  #6b7280;
    --grid-color:  #e5e7eb;
    --text-muted:  #9ca3af;
    --accent:      #2563eb;
  }
</style>"""

_NO_DATA_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120">'
    + _STYLE_BLOCK
    + '<rect width="400" height="120" fill="none"/>'
    '<text x="200" y="65" text-anchor="middle" '
    'font-family="sans-serif" font-size="14" fill="var(--axis-color)">'
    "No data available</text></svg>"
)


def _compact_floats(svg: str) -> str:
    """
    Truncate floating-point coordinate strings to 2 decimal places.
    Reduces matplotlib SVG size by ~35% without any visual difference.
    Matches numbers like 123.456789 or -0.12345 in SVG attribute/path data.
    """
    return re.sub(
        r'(-?\d+\.\d{3,})',
        lambda m: f"{float(m.group(1)):.2f}",
        svg,
    )


def _finalize_svg(raw: str, title: str = "") -> str:
    """
    Post-process matplotlib SVG output:
    1. Strip XML declaration and DOCTYPE.
    2. Replace color tokens with CSS var() references.
    3. Truncate excess float precision (reduces token count ~35%).
    4. Inject <style> fallback block and optional <title>.
    5. Remove fixed width/height from <svg> tag (keep viewBox only).
    """
    # Strip XML declaration
    svg = re.sub(r"<\?xml[^?]*\?>\s*", "", raw)
    svg = re.sub(r"<!DOCTYPE[^>]*>\s*", "", svg)

    # Replace color tokens (case-insensitive hex match)
    for token, var in _TOKEN_MAP.items():
        svg = re.sub(re.escape(token), var, svg, flags=re.IGNORECASE)

    # Compact floats — must come AFTER token replacement to avoid
    # mangling the hex values inside var() strings
    svg = _compact_floats(svg)

    # Remove fixed width/height attributes from <svg> opening tag,
    # keeping viewBox so it stays responsive.
    svg = re.sub(r'\s+width="[^"]*"', "", svg, count=1)
    svg = re.sub(r'\s+height="[^"]*"', "", svg, count=1)

    # Inject <style> and optional <title> right after <svg ...>
    insert = _STYLE_BLOCK
    if title:
        insert += f"\n<title>{title}</title>"
    svg = re.sub(r"(<svg\b[^>]*>)", r"\1\n" + insert, svg, count=1)

    return svg.strip()


def _fig_to_svg(fig: plt.Figure, title: str = "") -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return _finalize_svg(buf.read().decode("utf-8"), title=title)


# ════════════════════════════════════════════════════════════════════════════
# Tool: kline_svg
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def kline_svg(
    ohlcv: list[dict],
    width: int = 600,
    height: int = 280,
) -> dict:
    """
    Render a candlestick chart as an inline SVG string.

    ohlcv: list of {date, open, high, low, close, volume} dicts —
           same shape as stock_mcp.get_kline returns.
    Returns: {svg, caption, as_of}.
    """
    if not ohlcv:
        return {"svg": _NO_DATA_SVG, "caption": "No data", "as_of": _ts()}

    # Cache key MUST include ohlcv contents — the previous version keyed only
    # on len(ohlcv)/width/height, which collided across stocks with the same
    # bar count. Hash date+close pairs as a stable per-stock fingerprint.
    import hashlib
    fingerprint = "|".join(
        f"{b.get('date','')}:{b.get('close','')}" for b in ohlcv
    )
    digest = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:12]
    cache_key = f"kline:{digest}:{width}:{height}"
    if hit := _cache_get(cache_key):
        return hit

    # Downsample to max 60 bars (≈weekly for 1Y).
    # 120 bars → ~72K JSON chars which exceeds Claude's ~71K tool-result limit;
    # 60 bars → ~46K JSON chars, well within limits and still shows trend clearly.
    MAX_BARS = 60
    if len(ohlcv) > MAX_BARS:
        step = len(ohlcv) / MAX_BARS
        ohlcv = [ohlcv[int(i * step)] for i in range(MAX_BARS)]

    result = _render_kline(ohlcv, width, height)
    _cache_set(cache_key, result)
    return result


def _render_kline(ohlcv: list[dict], width: int, height: int) -> dict:
    dates  = [d["date"] for d in ohlcv]
    opens  = np.array([float(d["open"])  for d in ohlcv])
    highs  = np.array([float(d["high"])  for d in ohlcv])
    lows   = np.array([float(d["low"])   for d in ohlcv])
    closes = np.array([float(d["close"]) for d in ohlcv])

    n = len(dates)
    xs = np.arange(n)

    dpi = 96
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(_TOKEN_BG)
    ax.set_facecolor(_TOKEN_BG)

    # Candle body half-width
    bw = max(0.3, min(0.4, 8 / n))

    for i in range(n):
        up = closes[i] >= opens[i]
        color = _TOKEN_UP if up else _TOKEN_DOWN
        body_bot = min(opens[i], closes[i])
        body_h   = abs(closes[i] - opens[i]) or (highs[i] - lows[i]) * 0.01
        # Wick
        ax.plot([xs[i], xs[i]], [lows[i], highs[i]],
                color=color, linewidth=0.8, solid_capstyle="round")
        # Body
        ax.add_patch(mpatches.Rectangle(
            (xs[i] - bw, body_bot), 2 * bw, body_h,
            facecolor=color, edgecolor=color, linewidth=0,
        ))

    # Grid
    ax.yaxis.grid(True, color=_TOKEN_GRID, linewidth=0.5, linestyle="--", alpha=0.7)
    ax.set_axisbelow(True)
    ax.spines[:].set_color(_TOKEN_AXIS)
    ax.tick_params(colors=_TOKEN_AXIS, labelsize=8)

    # X-axis: 5-7 evenly spaced date labels
    tick_count = min(7, max(5, n // 30))
    tick_indices = np.linspace(0, n - 1, tick_count, dtype=int)
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(
        [dates[i][:10] for i in tick_indices],
        rotation=30, ha="right", color=_TOKEN_AXIS, fontsize=7,
    )

    # Y-axis: 4-5 price ticks
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4, steps=[1, 2, 5, 10]))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v:,.2f}"
    ))
    for label in ax.get_yticklabels():
        label.set_color(_TOKEN_AXIS)
        label.set_fontsize(7)

    ax.set_xlim(-0.8, n - 0.2)
    ax.margins(y=0.08)

    caption = (
        f"{dates[0][:10]} – {dates[-1][:10]}  "
        f"last {closes[-1]:.2f}  "
        f"{'▲' if closes[-1] >= closes[0] else '▼'} "
        f"{(closes[-1]/closes[0]-1)*100:+.1f}%"
    )

    svg = _fig_to_svg(fig, title="Price chart")
    return {"svg": svg, "caption": caption, "as_of": _ts()}


# ════════════════════════════════════════════════════════════════════════════
# Tool: pe_band_svg
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def pe_band_svg(
    pe_history: list[dict],
    current_pe: float,
    percentiles: list[int] | None = None,
) -> dict:
    """
    PE Band chart with shaded percentile bands.

    pe_history: list of {date, pe} dicts (oldest first).
    current_pe: current PE to mark with a horizontal line + dot.
    percentiles: list of percentile breakpoints (default [10,30,50,70,90]).
    Returns: {svg, caption, as_of}.
    """
    if percentiles is None:
        percentiles = [10, 30, 50, 70, 90]

    if not pe_history:
        return {"svg": _NO_DATA_SVG, "caption": "No PE history", "as_of": _ts()}

    dpi = 96
    fig, ax = plt.subplots(figsize=(600 / dpi, 240 / dpi), dpi=dpi)
    fig.patch.set_facecolor(_TOKEN_BG)
    ax.set_facecolor(_TOKEN_BG)

    dates = [d["date"][:10] for d in pe_history]
    pes   = np.array([float(d["pe"]) for d in pe_history], dtype=float)
    xs    = np.arange(len(dates))

    # Draw PE line
    ax.plot(xs, pes, color=_TOKEN_AXIS, linewidth=0.9, alpha=0.8)

    # Percentile bands (fill between adjacent bands)
    pct_vals = np.nanpercentile(pes, percentiles)
    for i in range(len(pct_vals) - 1):
        ax.axhspan(pct_vals[i], pct_vals[i + 1],
                   color=_TOKEN_GRID, alpha=0.25 + 0.1 * i, linewidth=0)

    # Percentile lines
    for p, v in zip(percentiles, pct_vals):
        ax.axhline(v, color=_TOKEN_MUTED, linewidth=0.6, linestyle=":")
        ax.text(xs[-1] + 0.5, v, f"P{p}", fontsize=6,
                color=_TOKEN_MUTED, va="center")

    # Current PE marker
    color = _TOKEN_DOWN if current_pe > pct_vals[-1] else (
        _TOKEN_UP if current_pe < pct_vals[1] else _TOKEN_ACCENT
    )
    ax.axhline(current_pe, color=color, linewidth=1.2, linestyle="--")
    ax.scatter([xs[-1]], [current_pe], color=color, s=30, zorder=5)

    # Axes
    n = len(dates)
    tick_count = min(7, max(5, n // 30))
    tick_ix = np.linspace(0, n - 1, tick_count, dtype=int)
    ax.set_xticks(tick_ix)
    ax.set_xticklabels([dates[i] for i in tick_ix], rotation=30, ha="right",
                       color=_TOKEN_AXIS, fontsize=7)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}x"))
    for lbl in ax.get_yticklabels():
        lbl.set_color(_TOKEN_AXIS)
        lbl.set_fontsize(7)
    ax.tick_params(colors=_TOKEN_AXIS)
    ax.spines[:].set_color(_TOKEN_AXIS)
    ax.yaxis.grid(True, color=_TOKEN_GRID, linewidth=0.4, linestyle="--", alpha=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(-0.5, n + 2)
    ax.margins(y=0.1)

    # Compute percentile rank
    rank = float((pes < current_pe).sum() / len(pes) * 100)
    caption = f"Current PE {current_pe:.1f}x  ·  {rank:.0f}th percentile of history"

    svg = _fig_to_svg(fig, title="PE Band chart")
    return {"svg": svg, "caption": caption, "as_of": _ts()}


# ════════════════════════════════════════════════════════════════════════════
# Tool: comparison_radar_svg
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def comparison_radar_svg(
    subject: dict,
    peers: list[dict],
    metrics: list[str],
) -> dict:
    """
    Multi-axis radar chart comparing subject vs ≤ 5 peers.

    subject: {code, name, metric1: val, metric2: val, ...}
    peers: list of same-shape dicts.
    metrics: list of metric keys to plot.
    Returns: {svg, caption, as_of}.
    """
    if not metrics or not subject:
        return {"svg": _NO_DATA_SVG, "caption": "No metrics", "as_of": _ts()}

    all_stocks = [subject] + peers[:5]
    M = len(metrics)
    if M < 3:
        return {"svg": _NO_DATA_SVG, "caption": "Need ≥ 3 metrics for radar", "as_of": _ts()}

    # Normalise each metric 0–100 across the full set
    def _val(d: dict, m: str) -> float:
        v = d.get(m)
        return float(v) if v is not None else 0.0

    normed: list[list[float]] = []
    for stock in all_stocks:
        vals = [_val(stock, m) for m in metrics]
        normed.append(vals)
    normed_arr = np.array(normed, dtype=float)

    col_min = normed_arr.min(axis=0)
    col_max = normed_arr.max(axis=0)
    col_range = np.where(col_max - col_min == 0, 1, col_max - col_min)
    normed_arr = (normed_arr - col_min) / col_range * 100

    # Angles
    angles = np.linspace(0, 2 * np.pi, M, endpoint=False).tolist()
    angles += angles[:1]

    dpi = 96
    fig, ax = plt.subplots(figsize=(5, 5), dpi=dpi,
                           subplot_kw={"polar": True})
    fig.patch.set_facecolor(_TOKEN_BG)
    ax.set_facecolor(_TOKEN_BG)

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_rlim(0, 100)
    ax.set_thetagrids(np.degrees(angles[:-1]), metrics,
                      fontsize=7, color=_TOKEN_AXIS)
    ax.tick_params(colors=_TOKEN_AXIS, labelsize=7)
    ax.yaxis.grid(True, color=_TOKEN_GRID, linewidth=0.5, alpha=0.6)
    ax.xaxis.grid(True, color=_TOKEN_GRID, linewidth=0.5, alpha=0.6)
    ax.spines["polar"].set_color(_TOKEN_AXIS)
    ax.set_yticklabels([])

    # Draw peers first (dashed)
    for i, stock in enumerate(all_stocks[1:], 1):
        vals = normed_arr[i].tolist() + [normed_arr[i][0]]
        ax.plot(angles, vals, color=_TOKEN_MUTED, linewidth=0.8,
                linestyle="--", alpha=0.7)

    # Draw subject (solid, accent color)
    subj_vals = normed_arr[0].tolist() + [normed_arr[0][0]]
    ax.plot(angles, subj_vals, color=_TOKEN_ACCENT, linewidth=1.5)
    ax.fill(angles, subj_vals, color=_TOKEN_ACCENT, alpha=0.15)

    caption = (
        f"{subject.get('name', subject.get('code', ''))} vs "
        f"{len(all_stocks)-1} peer(s) on {', '.join(metrics)}"
    )
    svg = _fig_to_svg(fig, title="Comparison radar")
    return {"svg": svg, "caption": caption, "as_of": _ts()}


# ════════════════════════════════════════════════════════════════════════════
# Tool: metric_sparkline_svg
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def metric_sparkline_svg(
    values: list[float],
    width: int = 120,
    height: int = 32,
) -> dict:
    """
    Tiny sparkline for embedding in metric cards.
    No axes, no labels — just a line and an end-point dot.
    Color: --up-color if last > first, else --down-color.
    Returns: {svg, as_of}.
    """
    if not values or len(values) < 2:
        return {"svg": _NO_DATA_SVG, "as_of": _ts()}

    vals = np.array([float(v) for v in values])
    color = _TOKEN_UP if vals[-1] >= vals[0] else _TOKEN_DOWN

    dpi = 96
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(_TOKEN_BG)
    ax.set_facecolor(_TOKEN_BG)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    xs = np.arange(len(vals))
    ax.plot(xs, vals, color=color, linewidth=1.2, solid_capstyle="round")
    ax.scatter([xs[-1]], [vals[-1]], color=color, s=12, zorder=5)
    ax.axis("off")
    ax.margins(x=0.05, y=0.15)

    svg = _fig_to_svg(fig, title="Sparkline")
    return {"svg": svg, "as_of": _ts()}


# ════════════════════════════════════════════════════════════════════════════
# Tool: peer_bar_svg
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def peer_bar_svg(
    items: list[dict],
    metric: str,
    highlight_code: str,
) -> dict:
    """
    Horizontal bar chart ranking peers on a single metric.

    items: list of {code, name, <metric>: value} dicts.
    metric: key to read from each item.
    highlight_code: the bar for this code gets class .bar-highlight.
    Returns: {svg, caption, as_of}.
    """
    if not items:
        return {"svg": _NO_DATA_SVG, "caption": "No data", "as_of": _ts()}

    # Filter to items with a valid value, sort descending
    valid = [(d, float(d[metric])) for d in items if d.get(metric) is not None]
    if not valid:
        return {"svg": _NO_DATA_SVG, "caption": f"No valid {metric} values", "as_of": _ts()}
    valid.sort(key=lambda x: x[1], reverse=True)

    labels = [d.get("name") or d.get("code", "") for d, _ in valid]
    values = [v for _, v in valid]
    codes  = [d.get("code", "") for d, _ in valid]
    colors = [_TOKEN_ACCENT if c == highlight_code else _TOKEN_AXIS for c in codes]

    n = len(valid)
    dpi = 96
    row_h = 22
    fig, ax = plt.subplots(figsize=(5, max(1.5, n * row_h / dpi)), dpi=dpi)
    fig.patch.set_facecolor(_TOKEN_BG)
    ax.set_facecolor(_TOKEN_BG)

    ys = np.arange(n)
    bars = ax.barh(ys, values, color=colors, height=0.6)

    # Value labels on bars
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height() / 2,
                f"{val:.2f}", va="center", ha="left",
                fontsize=7, color=_TOKEN_AXIS)

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=8, color=_TOKEN_AXIS)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.2f}"))
    ax.tick_params(colors=_TOKEN_AXIS, labelsize=7)
    ax.spines[:].set_color(_TOKEN_AXIS)
    ax.xaxis.grid(True, color=_TOKEN_GRID, linewidth=0.4, linestyle="--", alpha=0.6)
    ax.set_axisbelow(True)
    fig.patch.set_facecolor(_TOKEN_BG)

    caption = f"{metric} comparison  ·  {n} companies"
    svg = _fig_to_svg(fig, title=f"{metric} peer comparison")
    return {"svg": svg, "caption": caption, "as_of": _ts()}


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("Starting foliopage-chart MCP server (stdio transport) …")
    mcp.run(transport="stdio")
