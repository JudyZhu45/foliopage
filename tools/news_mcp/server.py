"""
news_mcp — MCP server providing real news, announcements, and analyst data.

Data sources
────────────
A-share:  akshare (stock_news_em, stock_notice_report, stock_research_report_em)
US:       yfinance ticker.news + Google News RSS (feedparser, no API key)

IMPORTANT: stdout is reserved for MCP JSON-RPC. All logging → stderr.
"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

import akshare as ak
import feedparser
import yfinance as yf
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
log = logging.getLogger("news_mcp")

# ── MCP server ────────────────────────────────────────────────────────────────
mcp = FastMCP("foliopage-news")

# ── TTL cache (15 min) ───────────────────────────────────────────────────────
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


def _is_a_share(code: str) -> bool:
    return code.isdigit() and len(code) == 6


def _err(code: str, msg: str) -> dict:
    log.warning("news_mcp error  code=%s  %s", code, msg)
    return {"error": msg, "code": code, "as_of": _ts()}


# ── Levenshtein dedup helper ─────────────────────────────────────────────────

def _similar(a: str, b: str) -> float:
    """
    Character-level similarity ratio (0.0–1.0): fraction of the shorter
    string's characters that appear in the longer string.
    Returns 0 when the strings differ too much in length (ratio < 0.5)
    to avoid false positives between a short word and a long sentence.
    """
    if not a or not b:
        return 0.0
    a, b = a.lower(), b.lower()
    if a == b:
        return 1.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    # Don't match if lengths are wildly different
    if len(shorter) < len(longer) * 0.5:
        return 0.0
    matches = sum(c in longer for c in shorter)
    return matches / len(shorter)


def _dedup_news(items: list[dict]) -> list[dict]:
    """Remove near-duplicate titles (similarity > 0.80); keep the older one."""
    seen: list[dict] = []
    for item in items:
        title = item.get("title", "")
        duplicate = False
        for kept in seen:
            if _similar(title, kept.get("title", "")) > 0.80:
                duplicate = True
                break
        if not duplicate:
            seen.append(item)
    return seen


# ════════════════════════════════════════════════════════════════════════════
# Tool: recent_news
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def recent_news(code: str, days: int = 7, limit: int = 10) -> dict:
    """
    Return recent news for a stock.

    A-share (6-digit code): akshare stock_news_em, fallback to news_cctv.
    US ticker: yfinance ticker.news, fallback to Google News RSS.
    Returns: {items: [{title, source, published_at, url, summary}], as_of}.
    """
    cache_key = f"news:{code}:{days}:{limit}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        result = (
            _recent_news_a(code, days, limit)
            if _is_a_share(code)
            else _recent_news_us(code.upper(), days, limit)
        )
    except Exception as exc:
        result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _recent_news_a(code: str, days: int, limit: int) -> dict:
    cutoff = datetime.now() - timedelta(days=days)
    items: list[dict] = []

    # Primary: East Money news feed
    try:
        df = ak.stock_news_em(symbol=code)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                pub_raw = str(row.get("发布时间", "") or row.get("时间", ""))
                try:
                    pub_dt = datetime.fromisoformat(pub_raw.replace(" ", "T"))
                except ValueError:
                    pub_dt = datetime.now()
                if pub_dt < cutoff:
                    continue
                items.append({
                    "title":        str(row.get("新闻标题", "") or row.get("title", "")),
                    "source":       str(row.get("文章来源", "") or "东方财富"),
                    "published_at": pub_dt.isoformat(timespec="seconds"),
                    "url":          str(row.get("新闻链接", "") or row.get("url", "")),
                    "summary":      "",
                    "data_source":  "akshare",
                })
    except Exception as exc:
        log.debug("stock_news_em failed for %s: %s", code, exc)

    # Fallback: CCTV news filtered by stock name
    if not items:
        try:
            name_df = ak.stock_info_sh_name_code(symbol="主板A股")
            # Look up name
            name_row = name_df[name_df["证券代码"].astype(str) == code]
            stock_name = str(name_row.iloc[0]["证券简称"]) if not name_row.empty else code

            cctv = ak.news_cctv(date=datetime.now().strftime("%Y%m%d"))
            if cctv is not None and not cctv.empty:
                for _, row in cctv.iterrows():
                    title = str(row.get("title", ""))
                    if stock_name not in title:
                        continue
                    pub_raw = str(row.get("time", ""))
                    try:
                        pub_dt = datetime.fromisoformat(pub_raw.replace(" ", "T"))
                    except ValueError:
                        pub_dt = datetime.now()
                    items.append({
                        "title":        title,
                        "source":       "央视新闻",
                        "published_at": pub_dt.isoformat(timespec="seconds"),
                        "url":          str(row.get("url", "")),
                        "summary":      "",
                        "data_source":  "akshare-cctv",
                    })
        except Exception as exc:
            log.debug("news_cctv fallback failed for %s: %s", code, exc)

    items = _dedup_news(items)
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return {"items": items[:limit], "as_of": _ts(), "source": "akshare"}


def _recent_news_us(code: str, days: int, limit: int) -> dict:
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    items: list[dict] = []

    # Primary: yfinance ticker.news
    try:
        news = yf.Ticker(code).news or []
        for item in news:
            ts = item.get("providerPublishTime") or item.get("providerPublishTime", 0)
            pub_dt = datetime.fromtimestamp(int(ts), tz=UTC)
            if pub_dt < cutoff:
                continue
            content = item.get("content", {})
            title = (
                item.get("title")
                or content.get("title")
                or ""
            )
            url = (
                item.get("link")
                or item.get("url")
                or content.get("canonicalUrl", {}).get("url")
                or content.get("clickThroughUrl", {}).get("url")
                or ""
            )
            publisher = (
                item.get("publisher")
                or content.get("provider", {}).get("displayName")
                or ""
            )
            summary = (
                item.get("summary")
                or content.get("summary")
                or ""
            )
            if not title:
                continue
            items.append({
                "title":        title,
                "source":       publisher,
                "published_at": pub_dt.isoformat(timespec="seconds"),
                "url":          url,
                "summary":      summary,
                "data_source":  "yfinance",
            })
    except Exception as exc:
        log.debug("yfinance.news failed for %s: %s", code, exc)

    # Fallback / augment: Google News RSS
    if len(items) < limit:
        try:
            rss_url = (
                f"https://news.google.com/rss/search"
                f"?q={quote_plus(code + ' stock')}&hl=en-US&gl=US&ceid=US:en"
            )
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                title = entry.get("title", "")
                url   = entry.get("link", "")
                pub_struct = entry.get("published_parsed")
                if pub_struct:
                    pub_dt = datetime(*pub_struct[:6], tzinfo=UTC)
                else:
                    pub_dt = datetime.now(tz=UTC)
                if pub_dt < cutoff:
                    continue
                items.append({
                    "title":        title,
                    "source":       entry.get("source", {}).get("title", "Google News"),
                    "published_at": pub_dt.isoformat(timespec="seconds"),
                    "url":          url,
                    "summary":      "",
                    "data_source":  "google-news-rss",
                })
        except Exception as exc:
            log.debug("Google News RSS failed for %s: %s", code, exc)

    items = _dedup_news(items)
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    source = "yfinance" if any(i["data_source"] == "yfinance" for i in items) else "google-news-rss"
    return {"items": items[:limit], "as_of": _ts(), "source": source}


# ════════════════════════════════════════════════════════════════════════════
# Tool: recent_announcements
# ════════════════════════════════════════════════════════════════════════════

_ANNOUNCEMENT_TYPES = {
    "业绩预告", "业绩报告", "重大事项", "分红送配", "股权变动",
    # broader catch-all substrings checked below
}

_ANNOUNCEMENT_KEYWORDS = ["业绩", "分红", "配股", "股权", "重大", "公告", "报告"]


def _is_material(title: str) -> bool:
    return any(kw in title for kw in _ANNOUNCEMENT_KEYWORDS)


@mcp.tool()
def recent_announcements(code: str, days: int = 30) -> dict:
    """
    Return official company announcements.

    A-share only. For US codes, returns {available: false, reason: ...}.
    Returns: {items: [{title, type, published_at, url}], as_of}.
    """
    if not _is_a_share(code):
        return {
            "available": False,
            "reason": "SEC EDGAR integration not yet supported",
            "items": [],
            "as_of": _ts(),
        }

    cache_key = f"ann:{code}:{days}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        result = _announcements_a(code, days)
    except Exception as exc:
        result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _announcements_a(code: str, days: int) -> dict:
    cutoff = datetime.now() - timedelta(days=days)
    items: list[dict] = []

    try:
        df = ak.stock_notice_report(symbol=code)
        if df is None or df.empty:
            return {"items": [], "available": True, "as_of": _ts(), "source": "akshare"}

        for _, row in df.iterrows():
            title   = str(row.get("公告标题", "") or row.get("title", ""))
            ann_type= str(row.get("公告类型", "") or row.get("type", ""))
            pub_raw = str(row.get("公告日期", "") or row.get("date", ""))
            url     = str(row.get("公告链接", "") or row.get("url", ""))

            # Date parse
            try:
                pub_dt = datetime.fromisoformat(pub_raw.replace("/", "-").replace(" ", "T"))
            except ValueError:
                pub_dt = datetime.now()

            if pub_dt < cutoff:
                continue

            # Filter to material types
            if ann_type in _ANNOUNCEMENT_TYPES or _is_material(title):
                items.append({
                    "title":        title,
                    "type":         ann_type,
                    "published_at": pub_dt.isoformat(timespec="seconds"),
                    "url":          url,
                })
    except Exception as exc:
        log.warning("stock_notice_report failed for %s: %s", code, exc)

    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return {"items": items, "available": True, "as_of": _ts(), "source": "akshare"}


# ════════════════════════════════════════════════════════════════════════════
# Tool: analyst_consensus
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def analyst_consensus(code: str) -> dict:
    """
    Aggregate analyst views: mean target price and buy/hold/sell distribution.

    A-share: akshare stock_research_report_em.
    US: yfinance ticker.recommendations + ticker.analyst_price_targets.
    Returns: {target_price, currency, ratings: {buy, hold, sell},
              recent_changes: [...], available, as_of}.
    """
    cache_key = f"analyst:{code}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        result = (
            _analyst_a(code)
            if _is_a_share(code)
            else _analyst_us(code.upper())
        )
    except Exception as exc:
        result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _pct(lst: list[float], p: float) -> float | None:
    """p-th percentile of a pre-sorted list (linear interpolation)."""
    if not lst:
        return None
    n = len(lst)
    idx = p / 100 * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return round(lst[lo] + (idx - lo) * (lst[hi] - lst[lo]), 2)


def _analyst_a(code: str) -> dict:
    try:
        df = ak.stock_research_report_em(symbol=code)
    except Exception as exc:
        log.warning("stock_research_report_em failed for %s: %s", code, exc)
        return {"available": False, "reason": f"akshare error: {exc}", "as_of": _ts()}

    if df is None or df.empty:
        return {"available": False, "reason": "No public analyst coverage data", "as_of": _ts()}

    # Column detection — akshare column names vary by version
    target_col = next((c for c in df.columns if "目标" in str(c) or "price" in str(c).lower()), None)
    rating_col  = next((c for c in df.columns if "评级" in str(c) or "rating" in str(c).lower()), None)
    date_col    = next((c for c in df.columns if "日期" in str(c) or "date" in str(c).lower()), None)
    firm_col    = next((c for c in df.columns if "机构" in str(c) or "firm" in str(c).lower()), None)

    # ── Target price distribution ─────────────────────────────────────────
    targets: list[float] = []
    if target_col:
        for v in df[target_col]:
            try:
                t = float(v)
                if t > 0:
                    targets.append(t)
            except (TypeError, ValueError):
                pass
    targets_sorted = sorted(targets)
    target_prices: dict = {"sample_size": len(targets_sorted)}
    if targets_sorted:
        target_prices.update({
            "low":         round(targets_sorted[0], 2),
            "pessimistic": _pct(targets_sorted, 25),   # 25th percentile
            "neutral":     _pct(targets_sorted, 50),   # median
            "optimistic":  _pct(targets_sorted, 75),   # 75th percentile
            "high":        round(targets_sorted[-1], 2),
            "mean":        round(sum(targets_sorted) / len(targets_sorted), 2),
        })

    # ── 5-level rating distribution ───────────────────────────────────────
    # Levels (descending bullishness): 买入 → 增持 → 中性/持有 → 减持 → 卖出
    buy = outperform = neutral_r = underperform = sell = 0
    _SCORE = {"buy": 5, "outperform": 4, "neutral": 3, "underperform": 2, "sell": 1}
    rating_score = total_rated = 0

    if rating_col:
        for v in df[rating_col].astype(str):
            vs = v.strip()
            vl = vs.lower()
            if any(k in vs for k in ["买入", "强买"]) or "strong buy" in vl:
                buy += 1; rating_score += _SCORE["buy"]
            elif any(k in vs for k in ["增持", "跑赢"]) or any(k in vl for k in ["overweight", "outperform", "accumulate"]):
                outperform += 1; rating_score += _SCORE["outperform"]
            elif "buy" in vl and "strong" not in vl:
                buy += 1; rating_score += _SCORE["buy"]
            elif any(k in vs for k in ["减持", "跑输"]) or any(k in vl for k in ["underweight", "underperform", "reduce"]):
                underperform += 1; rating_score += _SCORE["underperform"]
            elif any(k in vs for k in ["卖出", "强卖"]) or any(k in vl for k in ["sell", "strong sell"]):
                sell += 1; rating_score += _SCORE["sell"]
            else:  # 中性, 持有, hold, neutral, 观望, etc.
                neutral_r += 1; rating_score += _SCORE["neutral"]
            total_rated += 1

    overall_score = round(rating_score / total_rated, 2) if total_rated > 0 else None

    # ── Recent changes (last 90 days) ─────────────────────────────────────
    cutoff = datetime.now() - timedelta(days=90)
    recent: list[dict] = []
    for _, row in df.iterrows():
        pub_raw = str(row.get(date_col, "")) if date_col else ""
        try:
            pub_dt = datetime.fromisoformat(pub_raw.replace("/", "-"))
        except ValueError:
            pub_dt = datetime.now()
        if pub_dt < cutoff:
            continue
        recent.append({
            "firm":   str(row.get(firm_col, "")) if firm_col else "",
            "rating": str(row.get(rating_col, "")) if rating_col else "",
            "target": float(row[target_col]) if target_col and _sfloat(row.get(target_col)) else None,
            "date":   pub_dt.isoformat(timespec="seconds"),
        })

    return {
        "available":      True,
        "currency":       "CNY",
        "total_coverage": len(df),
        "ratings": {
            "buy":          buy,
            "outperform":   outperform,
            "neutral":      neutral_r,
            "underperform": underperform,
            "sell":         sell,
        },
        "overall_score":  overall_score,   # 1.0–5.0, higher = more bullish
        "target_prices":  target_prices,
        "recent_changes": recent[:10],
        "as_of":          _ts(),
        "source":         "akshare",
    }


def _sfloat(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _analyst_us(code: str) -> dict:
    try:
        ticker = yf.Ticker(code)

        # Price targets
        targets = ticker.analyst_price_targets
        mean_target: float | None = None
        if isinstance(targets, dict):
            mean_target = _sfloat(targets.get("mean"))
        elif hasattr(targets, "empty") and not targets.empty:
            for col in ["mean", "Mean"]:
                if col in targets.columns:
                    mean_target = _sfloat(targets[col].iloc[0])
                    break

        # Recommendations summary (buy/hold/sell counts)
        buy = hold = sell = 0
        try:
            summary = ticker.recommendations_summary
            if summary is not None and not summary.empty:
                for _, row in summary.iterrows():
                    period = str(row.get("period", ""))
                    if period == "0m":  # current month
                        buy  = int(row.get("strongBuy", 0) or 0) + int(row.get("buy", 0) or 0)
                        hold = int(row.get("hold", 0) or 0)
                        sell = int(row.get("sell", 0) or 0) + int(row.get("strongSell", 0) or 0)
                        break
        except Exception as exc:
            log.debug("recommendations_summary failed for %s: %s", code, exc)

        # Recent rating changes
        recent: list[dict] = []
        cutoff = datetime.now(tz=UTC) - timedelta(days=90)
        try:
            recs = ticker.recommendations
            if recs is not None and not recs.empty:
                recs = recs.reset_index()
                date_col = "Date" if "Date" in recs.columns else (
                    "date" if "date" in recs.columns else None)
                for _, row in recs.iterrows():
                    if date_col:
                        try:
                            d = row[date_col]
                            if hasattr(d, "tzinfo") and d.tzinfo is None:
                                import pandas as pd
                                d = pd.Timestamp(d, tz="UTC")
                            if d < cutoff:
                                continue
                        except Exception:
                            pass
                    recent.append({
                        "firm":   str(row.get("Firm", "")),
                        "action": str(row.get("Action", "")),
                        "from":   str(row.get("From Grade", "")),
                        "to":     str(row.get("To Grade", "")),
                        "date":   str(row.get(date_col, ""))[:10] if date_col else "",
                    })
        except Exception as exc:
            log.debug("recommendations failed for %s: %s", code, exc)

        if mean_target is None and not recent and buy + hold + sell == 0:
            return {"available": False,
                    "reason": "No public analyst coverage data", "as_of": _ts()}

        return {
            "available":      True,
            "target_price":   mean_target,
            "currency":       "USD",
            "ratings":        {"buy": buy, "hold": hold, "sell": sell},
            "recent_changes": recent[:10],
            "as_of":          _ts(),
            "source":         "yfinance",
        }
    except Exception as exc:
        log.warning("_analyst_us failed for %s: %s", code, exc)
        return {"available": False, "reason": str(exc), "as_of": _ts()}


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("Starting foliopage-news MCP server (stdio transport) …")
    mcp.run(transport="stdio")
