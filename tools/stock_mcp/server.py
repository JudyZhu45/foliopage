"""
stock_mcp — MCP server exposing akshare stock data via stdio transport.

Data source strategy
────────────────────
East Money (functions ending in _em) applies aggressive per-IP rate limits.
We therefore use Sina Finance / SSE / SZE APIs as the primary stack, which
are free of such limits for moderate usage:

  • get_basic_info   → SSE/SZE listing + stock_zh_a_daily (Sina)
  • get_kline        → stock_zh_a_daily (Sina)  / stock_us_hist (EM, retried)
  • get_financials   → stock_financial_abstract (Sina)
  • get_valuation    → computed from Sina financial + price data
  • get_peers        → stock_board_industry_cons_em (EM, retried)
  • search_stock     → SSE + SZE listing tables

East Money is still used for peers and some fields, with automatic retry.

IMPORTANT: stdout is reserved for MCP JSON-RPC frames. All logging → stderr.
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

import akshare as ak
import pandas as pd
import yfinance as yf
from cachetools import TTLCache
from mcp.server.fastmcp import FastMCP

# Hard 60s socket timeout — without this, akshare's requests calls (and
# yfinance) hang indefinitely when an upstream TCP connection succeeds but
# the server stops responding. _ak() catches "timed out" as transient and
# retries with backoff, so a single slow endpoint costs at most ~3min total.
socket.setdefaulttimeout(60)

# ── Disk cache (cross-run persistence via shared SQLite) ─────────────────────
# Sits alongside the in-memory TTLCache. When the in-memory cache misses,
# fall through to ~/.foliopage/cache.db; on hit, warm the in-memory layer
# for the rest of this process's lifetime.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
try:
    from _shared.cache_store import disk_get, disk_set, ttl_for  # noqa: E402
except ImportError:  # pragma: no cover — fallback if launched outside repo
    def disk_get(key): return None
    def disk_set(key, value, ttl_s): return None
    def ttl_for(key): return 0

# ── Logging (stderr only) ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("stock_mcp")

# ── MCP server ───────────────────────────────────────────────────────────────
mcp = FastMCP("foliopage-stock")

# ── TTL cache (15 min) ───────────────────────────────────────────────────────
_CACHE: TTLCache = TTLCache(maxsize=512, ttl=900)
_LOCK = threading.Lock()

SOURCE = "akshare"


# ════════════════════════════════════════════════════════════════════════════
# Utilities
# ════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _is_a_share(code: str) -> bool:
    return code.isdigit() and len(code) == 6


def _sina_symbol(code: str) -> str:
    """Convert bare A-share code to Sina sh/sz prefix format."""
    if code.startswith("6") or code.startswith("9"):
        return "sh" + code
    return "sz" + code


def _cache_get(key: str) -> Any | None:
    with _LOCK:
        v = _CACHE.get(key)
    if v is not None:
        return v
    # Disk fallback — survives across agent runs
    v = disk_get(key)
    if v is not None:
        with _LOCK:
            _CACHE[key] = v
    return v


def _cache_set(key: str, value: Any) -> None:
    with _LOCK:
        _CACHE[key] = value
    # Persist to disk with a key-prefix-based TTL (see _shared.cache_store).
    # Errors there are logged + swallowed so a bad disk doesn't break tools.
    ttl = ttl_for(key)
    if ttl > 0:
        disk_set(key, value, ttl)


def _err(code: str, msg: str) -> dict:
    log.warning("stock_mcp error  code=%s  %s", code, msg)
    return {"error": msg, "code": code, "as_of": _ts(), "source": SOURCE}


def _safe_float(val: Any) -> float | None:
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _df_col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return first df column whose name contains any candidate string."""
    for candidate in candidates:
        for col in df.columns:
            if candidate in str(col):
                return col
    return None


def _row_val(row: pd.Series, *candidates: str) -> Any:
    """Return first value from a row whose index label contains a candidate."""
    for candidate in candidates:
        for idx in row.index:
            if candidate in str(idx):
                return row[idx]
    return None


# ── Date helpers ─────────────────────────────────────────────────────────────
_RANGE_DAYS: dict[str, int] = {
    "1M": 31, "3M": 92, "6M": 183,
    "1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "MAX": 365 * 30,
}

_YF_PERIOD_MAP: dict[str, str] = {
    "1M": "1mo", "3M": "3mo", "6M": "6mo",
    "1Y": "1y", "3Y": "3y", "5Y": "5y", "MAX": "max",
}


def _date_range(rng: str) -> tuple[str, str]:
    days = _RANGE_DAYS.get(rng.upper(), 365)
    end = date.today()
    start = end - timedelta(days=days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _ohlcv_records(df: pd.DataFrame, *, date_col: str, open_col: str,
                   high_col: str, low_col: str, close_col: str,
                   vol_col: str) -> list[dict]:
    cols = [date_col, open_col, high_col, low_col, close_col, vol_col]
    if not all(c in df.columns for c in cols):
        return []
    return [
        {
            "date": str(r[date_col])[:10],
            "open": _safe_float(r[open_col]),
            "high": _safe_float(r[high_col]),
            "low": _safe_float(r[low_col]),
            "close": _safe_float(r[close_col]),
            "volume": _safe_float(r[vol_col]),
        }
        for r in df[cols].to_dict("records")
    ]


# ── Retry wrapper for East-Money endpoints ───────────────────────────────────
_TRANSIENT = (
    "Connection aborted", "RemoteDisconnected", "Expecting value",
    "ConnectionError", "timed out", "ReadTimeout",
    "Failed to resolve", "NameResolutionError", "nodename nor servname",
    "ConnectionResetError",
)


def _ak(func, *args, retries: int = 2, base_delay: float = 6.0, **kwargs):
    """Call an akshare function with retry on transient network errors."""
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            is_transient = any(p in str(exc) for p in _TRANSIENT)
            if is_transient and attempt < retries:
                wait = base_delay * (2 ** attempt)
                log.warning("akshare retry %d/%d in %.0fs: %s",
                            attempt + 1, retries + 1, wait, exc)
                time.sleep(wait)
            else:
                raise


# ── EM circuit breaker ────────────────────────────────────────────────────────
# East Money rate-limits aggressively per IP. When a single EM call hangs
# (TCP accepted, no HTTP response → socket.timeout after 60s), the next one
# almost certainly will too. This breaker short-circuits all EM calls for
# 3min after the first failure, so 8 parallel requests don't each waste
# 60-180s on retries.
_EM_BLACKLIST_UNTIL: float = 0.0
_EM_BLACKLIST_LOCK = threading.Lock()
_EM_COOLDOWN_S = 180


def _em_blocked() -> bool:
    return time.time() < _EM_BLACKLIST_UNTIL


def _em_trip(reason: str) -> None:
    global _EM_BLACKLIST_UNTIL
    with _EM_BLACKLIST_LOCK:
        was_blocked = _em_blocked()
        _EM_BLACKLIST_UNTIL = time.time() + _EM_COOLDOWN_S
        if not was_blocked:
            log.warning("EM circuit tripped for %ds (reason: %s)",
                        _EM_COOLDOWN_S, reason)


def _em_call(func, *args, retries: int = 1, base_delay: float = 4.0, **kwargs):
    """
    Wrap an East Money endpoint call with a circuit breaker. If EM was
    recently broken, raise immediately instead of waiting for another timeout.
    On failure, trips the breaker so the next caller skips EM entirely.
    """
    if _em_blocked():
        raise RuntimeError("EM circuit open — endpoint recently timed out")
    try:
        return _ak(func, *args, retries=retries, base_delay=base_delay, **kwargs)
    except Exception as exc:
        # Only trip on signs of a real EM outage / rate limit, not on data-shape
        # errors from a successful response.
        if any(p in str(exc) for p in _TRANSIENT):
            _em_trip(str(exc)[:120])
        raise


# ── Module-level session caches ──────────────────────────────────────────────
_SSE_DF: pd.DataFrame | None = None
_SZE_DF: pd.DataFrame | None = None
_LISTING_LOCK = threading.Lock()


def _get_sse_listing() -> pd.DataFrame:
    global _SSE_DF
    if _SSE_DF is not None:
        return _SSE_DF
    with _LISTING_LOCK:
        if _SSE_DF is None:
            log.info("Fetching SSE listing …")
            df = ak.stock_info_sh_name_code(symbol="主板A股")
            # Also grab Science Board
            try:
                df2 = ak.stock_info_sh_name_code(symbol="科创板")
                df = pd.concat([df, df2], ignore_index=True)
            except Exception:
                pass
            _SSE_DF = df
    return _SSE_DF


def _get_sze_listing() -> pd.DataFrame:
    global _SZE_DF
    if _SZE_DF is not None:
        return _SZE_DF
    with _LISTING_LOCK:
        if _SZE_DF is None:
            log.info("Fetching SZE listing …")
            _SZE_DF = ak.stock_info_sz_name_code(symbol="A股列表")
            # Normalise: code column → "code", name column → "name"
            _SZE_DF["code"] = _SZE_DF["A股代码"].astype(str).str.zfill(6)
            _SZE_DF["name"] = _SZE_DF["A股简称"].str.replace(" ", "")
            _SZE_DF["listed_date"] = _SZE_DF.get("A股上市日期", pd.Series())
    return _SZE_DF


def _quick_market_cap_yi(code: str) -> float | None:
    """Return market cap in 亿元 using recent Sina kline, or None on failure."""
    cached = _cache_get(f"basic:{code}")
    if cached and not cached.get("error"):
        mc = cached.get("market_cap_yi")
        if mc is not None:
            return mc
    try:
        symbol = _sina_symbol(code)
        end = date.today().strftime("%Y%m%d")
        start = (date.today() - timedelta(days=5)).strftime("%Y%m%d")
        daily = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end, adjust="")
        if not daily.empty:
            last = daily.iloc[-1]
            price = _safe_float(last.get("close"))
            shares = _safe_float(last.get("outstanding_share"))
            if price and shares:
                return round(price * shares / 1e8, 2)
    except Exception:
        pass
    return None


def _lookup_a_share(code: str) -> dict[str, Any]:
    """Return {name, listed_date} from SSE or SZE listing tables."""
    if code.startswith("6") or code.startswith("9"):
        df = _get_sse_listing()
        row = df[df["证券代码"].astype(str) == code]
        if not row.empty:
            r = row.iloc[0]
            return {"name": str(r.get("证券简称", "")),
                    "listed_date": str(r.get("上市日期", ""))}
    else:
        df = _get_sze_listing()
        row = df[df["code"] == code]
        if not row.empty:
            r = row.iloc[0]
            return {"name": str(r.get("name", "")),
                    "listed_date": str(r.get("listed_date", ""))}
    return {"name": "", "listed_date": ""}


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_basic_info
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_basic_info(code: str) -> dict:
    """
    Return basic stock profile.
    A-share: 6-digit numeric (e.g. '600519'). US stock: ticker (e.g. 'AAPL').
    Returns: code, name, industry, market_cap_yi / market_cap_b,
             listed_date, as_of, source.
    """
    cache_key = f"basic:{code}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        result = _basic_a(code) if _is_a_share(code) else _basic_us(code.upper())
    except Exception as exc:
        result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _basic_a(code: str) -> dict:
    # 1. Name + listed date from exchange listing (SSE/SZE — no rate limit)
    listing = _lookup_a_share(code)
    name = listing["name"]
    listed_date = listing["listed_date"]

    # 2. Latest price + outstanding shares from Sina kline (no rate limit)
    symbol = _sina_symbol(code)
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
    daily = ak.stock_zh_a_daily(symbol=symbol, start_date=start,
                                 end_date=end, adjust="")
    market_cap_yi: float | None = None
    if not daily.empty:
        last = daily.iloc[-1]
        price = _safe_float(last.get("close"))
        shares = _safe_float(last.get("outstanding_share"))
        if price and shares:
            market_cap_yi = round(price * shares / 1e8, 2)

    # 3. Industry from EM (best-effort with retry; returns "" on failure)
    industry = ""
    try:
        df = _em_call(ak.stock_individual_info_em, symbol=code)
        info = dict(zip(df["item"], df["value"]))
        industry = str(info.get("行业", ""))
    except Exception as exc:
        log.debug("industry lookup failed for %s: %s", code, exc)

    return {
        "code": code,
        "name": name,
        "industry": industry,
        "market_cap_yi": market_cap_yi,
        "listed_date": listed_date,
        "as_of": _ts(),
        "source": SOURCE,
        "units": {"market_cap_yi": "亿元"},
    }


def _basic_us_akshare(code: str) -> dict | None:
    """Try akshare US spot endpoint; return result dict on success, None on failure."""
    try:
        df = _em_call(ak.stock_us_spot_em)
        code_col = _df_col(df, "代码", "symbol")
        name_col = _df_col(df, "名称", "name")
        cap_col = _df_col(df, "市值", "总市值")
        if code_col is None:
            return None
        mask = df[code_col].astype(str).str.upper().str.endswith(code)
        row = df[mask]
        if row.empty:
            return None
        row = row.iloc[0]
        name = str(row[name_col]) if name_col else ""
        mc_raw = _safe_float(row[cap_col]) if cap_col else None
        market_cap_b = round(mc_raw / 1e9, 2) if mc_raw else None
        return {
            "code": code, "name": name, "industry": "",
            "market_cap_b": market_cap_b, "market_cap_currency": "USD",
            "listed_date": None, "as_of": _ts(), "source": "akshare",
            "units": {"market_cap_b": "$B"},
        }
    except Exception as exc:
        log.debug("_basic_us_akshare failed for %s: %s", code, exc)
        return None


def _basic_us_yfinance(code: str) -> dict | None:
    """Try yfinance for US stock; return result dict on success, None on failure."""
    try:
        info = yf.Ticker(code).info
        name = info.get("shortName") or info.get("longName") or ""
        if not name:
            return None
        mc_raw = info.get("marketCap")
        market_cap_b = round(mc_raw / 1e9, 2) if mc_raw else None
        industry = info.get("sector") or info.get("industry") or ""
        return {
            "code": code, "name": name, "industry": industry,
            "market_cap_b": market_cap_b, "market_cap_currency": "USD",
            "listed_date": None, "as_of": _ts(), "source": "yfinance",
            "units": {"market_cap_b": "$B"},
        }
    except Exception as exc:
        log.debug("_basic_us_yfinance failed for %s: %s", code, exc)
        return None


def _basic_us(code: str) -> dict:
    result = _basic_us_akshare(code) or _basic_us_yfinance(code)
    if result is None:
        return _err(code, f"US stock '{code}' not found via akshare or yfinance")
    return result


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_kline
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_kline(code: str, range: str = "1Y") -> dict:
    """
    Return OHLCV daily bars.
    range: 1M / 3M / 6M / 1Y / 3Y / 5Y / MAX (default 1Y).
    Returns: {code, range, bars: [{date,open,high,low,close,volume}], count}.
    """
    cache_key = f"kline:{code}:{range}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        result = _kline_a(code, range) if _is_a_share(code) else _kline_us(code.upper(), range)
    except Exception as exc:
        result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _kline_a(code: str, rng: str) -> dict:
    start, end = _date_range(rng)
    # Sina's stock_zh_a_daily uses sh/sz prefix; no East Money dependency
    symbol = _sina_symbol(code)
    df = ak.stock_zh_a_daily(symbol=symbol, start_date=start,
                              end_date=end, adjust="")
    bars = _ohlcv_records(df, date_col="date", open_col="open", high_col="high",
                          low_col="low", close_col="close", vol_col="volume")
    return {"code": code, "range": rng, "bars": bars,
            "count": len(bars), "as_of": _ts(), "source": SOURCE}


def _kline_us_akshare(code: str, rng: str) -> dict | None:
    """Try akshare US kline; return result dict on success, None on failure."""
    start, end = _date_range(rng)
    try:
        df = _ak(ak.stock_us_hist, symbol=code, period="daily",
                 start_date=start, end_date=end, adjust="")
        bars = _ohlcv_records(df, date_col="日期", open_col="开盘", high_col="最高",
                              low_col="最低", close_col="收盘", vol_col="成交量")
        if bars:
            return {"code": code, "range": rng, "bars": bars,
                    "count": len(bars), "as_of": _ts(), "source": "akshare"}
    except Exception as e1:
        log.debug("stock_us_hist failed for %s: %s", code, e1)
    try:
        df = _ak(ak.stock_us_daily, symbol=code, adjust="")
        df["date"] = pd.to_datetime(df["date"])
        start_dt = datetime.strptime(start, "%Y%m%d").date()
        df = df[df["date"].dt.date >= start_dt]
        bars = _ohlcv_records(df, date_col="date", open_col="open",
                              high_col="high", low_col="low",
                              close_col="close", vol_col="volume")
        if bars:
            return {"code": code, "range": rng, "bars": bars,
                    "count": len(bars), "as_of": _ts(), "source": "akshare"}
    except Exception as e2:
        log.debug("stock_us_daily failed for %s: %s", code, e2)
    return None


def _kline_us_yfinance(code: str, rng: str) -> dict | None:
    """Try yfinance US kline; return result dict on success, None on failure."""
    try:
        period_str = _YF_PERIOD_MAP.get(rng.upper(), "1y")
        df = yf.Ticker(code).history(period=period_str, interval="1d")
        if df.empty:
            return None
        df = df.reset_index()
        # yfinance columns: Date, Open, High, Low, Close, Volume
        bars = _ohlcv_records(df, date_col="Date", open_col="Open",
                              high_col="High", low_col="Low",
                              close_col="Close", vol_col="Volume")
        if not bars:
            return None
        return {"code": code, "range": rng, "bars": bars,
                "count": len(bars), "as_of": _ts(), "source": "yfinance"}
    except Exception as exc:
        log.debug("_kline_us_yfinance failed for %s: %s", code, exc)
        return None


def _kline_us(code: str, rng: str) -> dict:
    result = _kline_us_akshare(code, rng) or _kline_us_yfinance(code, rng)
    if result is None:
        return _err(code, f"US kline unavailable for '{code}' via akshare or yfinance")
    return result


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_financials
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_financials(code: str, period: str = "annual") -> dict:
    """
    Return key financials for last 5 periods (annual or quarterly).
    Fields: revenue, net_profit, operating_cf, equity, eps, roe,
            gross_margin, net_margin.
    A-shares only via akshare (Sina Finance source).
    """
    cache_key = f"fin:{code}:{period}"
    if hit := _cache_get(cache_key):
        return hit
    if not _is_a_share(code):
        try:
            result = _financials_us_yfinance(code.upper(), period)
        except Exception as exc:
            result = _err(code, str(exc))
    else:
        try:
            result = _financials_a(code, period)
        except Exception as exc:
            result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _financials_us_yfinance(code: str, period: str) -> dict:
    """Fetch US stock financials via yfinance."""
    try:
        ticker = yf.Ticker(code)
        if period == "annual":
            income = ticker.income_stmt
            cf = ticker.cash_flow
            bs = ticker.balance_sheet
        else:
            income = ticker.quarterly_income_stmt
            cf = ticker.quarterly_cash_flow
            bs = ticker.quarterly_balance_sheet

        if income is None or income.empty:
            return _err(code, "yfinance returned empty income statement")

        date_cols = list(income.columns[:5])

        def _cell(df: pd.DataFrame | None, col: Any, *candidates: str) -> float | None:
            if df is None or df.empty or col not in df.columns:
                return None
            for cand in candidates:
                for idx in df.index:
                    if cand.lower() in str(idx).lower():
                        return _safe_float(df.loc[idx, col])
            return None

        records = []
        for col in date_cols:
            revenue = _cell(income, col, "total revenue")
            net_profit = _cell(income, col, "net income")
            gross_profit = _cell(income, col, "gross profit")
            op_cf = _cell(cf, col, "operating cash flow", "cash from operations")
            equity = _cell(bs, col, "stockholders equity", "total equity")
            eps = _cell(income, col, "basic eps", "diluted eps")
            gross_margin = (round(gross_profit / revenue * 100, 2)
                            if gross_profit and revenue else None)
            net_margin = (round(net_profit / revenue * 100, 2)
                          if net_profit and revenue else None)
            roe = (round(net_profit / equity * 100, 2)
                   if net_profit and equity and equity != 0 else None)
            records.append({
                "period": str(col)[:10],
                "revenue": revenue, "net_profit": net_profit,
                "operating_cf": op_cf, "equity": equity,
                "eps": eps, "roe": roe,
                "gross_margin": gross_margin, "net_margin": net_margin,
            })

        return {
            "code": code, "period": period, "periods": records,
            "as_of": _ts(), "source": "yfinance",
            "units": {
                "revenue": "USD", "net_profit": "USD",
                "operating_cf": "USD", "equity": "USD",
                "roe": "%", "gross_margin": "%", "net_margin": "%",
            },
        }
    except Exception as exc:
        return _err(code, f"yfinance financials failed: {exc}")


def _financials_a(code: str, period: str) -> dict:
    """
    stock_financial_abstract returns a wide DataFrame:
      rows = metrics, columns = period dates (YYYYMMDD).
    We pivot it to a list of per-period dicts.
    """
    df = ak.stock_financial_abstract(symbol=code)
    if df is None or df.empty:
        return _err(code, "stock_financial_abstract returned empty data")

    # Select period columns
    all_date_cols = [c for c in df.columns if str(c).isdigit() and len(str(c)) == 8]
    if period == "annual":
        date_cols = [c for c in all_date_cols if str(c).endswith("1231")]
    else:
        date_cols = all_date_cols  # include quarters

    date_cols = date_cols[:5]  # last 5

    # Build indicator → row lookup
    indicator_idx = dict(zip(df["指标"], range(len(df))))

    def _ind(name: str) -> Any:
        """Get value for indicator `name` from the df."""
        # Try exact match first, then substring
        if name in indicator_idx:
            return df.iloc[indicator_idx[name]]
        for idx_name, idx_pos in indicator_idx.items():
            if name in str(idx_name):
                return df.iloc[idx_pos]
        return None

    records = []
    for col in date_cols:
        rec: dict[str, Any] = {"period": str(col)}

        def _val(indicator_name: str) -> float | None:
            row = _ind(indicator_name)
            return _safe_float(row[col]) if row is not None else None

        rec["revenue"] = _val("营业总收入")
        rec["net_profit"] = _val("归母净利润")
        rec["operating_cf"] = _val("经营现金流量净额")
        rec["equity"] = _val("股东权益合计")
        rec["eps"] = _val("基本每股收益")
        rec["roe"] = _val("净资产收益率(ROE)")
        rec["gross_margin"] = _val("毛利率")
        rec["net_margin"] = _val("销售净利率")
        records.append(rec)

    return {
        "code": code,
        "period": period,
        "periods": records,
        "as_of": _ts(),
        "source": SOURCE,
        "units": {
            "revenue": "元", "net_profit": "元",
            "operating_cf": "元", "equity": "元",
            "roe": "%", "gross_margin": "%", "net_margin": "%",
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_valuation
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_valuation(code: str) -> dict:
    """
    Return current valuation: pe_ttm, pb, market_cap, and 10-year PE percentile.
    PE and PB are computed from Sina financial data + latest price.
    """
    cache_key = f"val:{code}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        result = _valuation_a(code) if _is_a_share(code) else _valuation_us(code.upper())
    except Exception as exc:
        result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _valuation_a(code: str) -> dict:
    # Get latest price + shares from Sina kline
    symbol = _sina_symbol(code)
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
    daily = ak.stock_zh_a_daily(symbol=symbol, start_date=start,
                                 end_date=end, adjust="")
    if daily.empty:
        return _err(code, "No daily data available for valuation")
    last = daily.iloc[-1]
    price = _safe_float(last.get("close"))
    shares = _safe_float(last.get("outstanding_share"))
    market_cap_yi = round(price * shares / 1e8, 2) if price and shares else None

    # Get latest annual EPS and equity per share from financial abstract
    pe_ttm: float | None = None
    pb: float | None = None
    try:
        fab = ak.stock_financial_abstract(symbol=code)
        annual_cols = [c for c in fab.columns
                       if str(c).isdigit() and len(str(c)) == 8 and str(c).endswith("1231")]
        if annual_cols and price:
            latest = annual_cols[0]
            indicator_idx = dict(zip(fab["指标"], range(len(fab))))

            def _fab_val(name: str) -> float | None:
                for k, i in indicator_idx.items():
                    if name in str(k):
                        return _safe_float(fab.iloc[i][latest])
                return None

            eps = _fab_val("基本每股收益")
            nav_per_share = _fab_val("每股净资产")

            if eps and eps > 0:
                pe_ttm = round(price / eps, 2)
            if nav_per_share and nav_per_share > 0:
                pb = round(price / nav_per_share, 2)
    except Exception as exc:
        log.debug("PE/PB computation failed for %s: %s", code, exc)

    # PE percentile + history (best-effort, EM endpoint)
    pe_pct: float | None = None
    pe_desc: str | None = None
    pe_history: list[dict] = []
    try:
        pe_hist = _ak(ak.stock_a_pe, symbol=code, retries=1, base_delay=3.0)
        if not pe_hist.empty:
            pe_col = _df_col(pe_hist, "PE", "市盈率")
            date_col = _df_col(pe_hist, "日期", "date", "Date")
            if pe_col and pe_ttm:
                series = pe_hist[pe_col].apply(_safe_float).dropna()
                series = series[series > 0]
                if len(series) > 50:
                    pct = float((series < pe_ttm).sum() / len(series) * 100)
                    pe_pct = round(pct, 1)
                    years = round(len(series) / 252)
                    pe_desc = (f"PE {pe_ttm:.1f}x is at {pe_pct:.0f}th percentile "
                               f"of last ~{years}y history")
            # Build pe_history list (last 10 years ≤ 2520 bars) for pe_band_svg
            if pe_col and date_col:
                tail = pe_hist.tail(2520)
                for _, row in tail.iterrows():
                    d = str(row[date_col])[:10]
                    p = _safe_float(row[pe_col])
                    if d and p and p > 0:
                        pe_history.append({"date": d, "pe": round(p, 2)})
    except Exception as exc:
        log.debug("PE percentile unavailable for %s: %s", code, exc)

    return {
        "code": code,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "ps_ttm": None,
        "dividend_yield": None,
        "market_cap_yi": market_cap_yi,
        "pe_10y_percentile": pe_pct,
        "pe_percentile_desc": pe_desc,
        "pe_history": pe_history,
        "as_of": _ts(),
        "source": SOURCE,
        "units": {"market_cap_yi": "亿元", "pe_10y_percentile": "%"},
    }


def _valuation_us_akshare(code: str) -> dict | None:
    """Try akshare US valuation; return result dict on success, None on failure."""
    try:
        df = _em_call(ak.stock_us_spot_em)
        code_col = _df_col(df, "代码", "symbol")
        if code_col is None:
            return None
        mask = df[code_col].astype(str).str.upper().str.endswith(code)
        row = df[mask]
        if row.empty:
            return None
        row = row.iloc[0]
        pe = _safe_float(_row_val(row, "市盈率", "PE"))
        pb = _safe_float(_row_val(row, "市净率", "PB"))
        mc = _safe_float(_row_val(row, "总市值", "市值"))
        return {
            "code": code,
            "pe_ttm": pe, "pb": pb, "ps_ttm": None, "dividend_yield": None,
            "market_cap_b": round(mc / 1e9, 2) if mc else None,
            "market_cap_currency": "USD",
            "pe_10y_percentile": None, "pe_percentile_desc": None,
            "as_of": _ts(), "source": "akshare",
            "units": {"market_cap_b": "$B"},
        }
    except Exception as exc:
        log.debug("_valuation_us_akshare failed for %s: %s", code, exc)
        return None


def _valuation_us_yfinance(code: str) -> dict | None:
    """Try yfinance US valuation; return result dict on success, None on failure."""
    try:
        info = yf.Ticker(code).info
        mc = info.get("marketCap")
        pe = _safe_float(info.get("trailingPE"))
        pb = _safe_float(info.get("priceToBook"))
        return {
            "code": code,
            "pe_ttm": pe, "pb": pb, "ps_ttm": None, "dividend_yield": None,
            "market_cap_b": round(mc / 1e9, 2) if mc else None,
            "market_cap_currency": "USD",
            "pe_10y_percentile": None, "pe_percentile_desc": None,
            "as_of": _ts(), "source": "yfinance",
            "units": {"market_cap_b": "$B"},
        }
    except Exception as exc:
        log.debug("_valuation_us_yfinance failed for %s: %s", code, exc)
        return None


def _valuation_us(code: str) -> dict:
    result = _valuation_us_akshare(code) or _valuation_us_yfinance(code)
    if result is None:
        return _err(code, f"US valuation unavailable for '{code}' via akshare or yfinance")
    return result


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_peers
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_peers(code: str, n: int = 5) -> dict:
    """
    Return top-n peers in same industry sorted by market cap (A-shares only).
    Each peer: {code, name, market_cap_yi, pe_ttm, industry}.
    """
    cache_key = f"peers:{code}:{n}"
    if hit := _cache_get(cache_key):
        return hit
    if not _is_a_share(code):
        result = _err(code, "get_peers currently supports A-shares only")
    else:
        try:
            result = _peers_a(code, n)
        except Exception as exc:
            result = _err(code, str(exc))
    _cache_set(cache_key, result)
    return result


def _peers_a(code: str, n: int) -> dict:
    """
    Find A-share peers using East Money industry board classification.

    Strategy:
    - East Money's industry board (stock_board_industry_cons_em) is the primary
      and only source.  Sina Finance's sector classification was dropped because
      it mis-categorises stocks (e.g. turbine-maker 汽轮科技 into "电子信息"),
      causing completely unrelated large-cap companies to be returned.
    - Within the EM industry board, candidates are filtered to those within a
      0.1×–10× market-cap band around the subject, then sorted by proximity.
    - Confidence reflects board size:
        "high"   → board has ≤ 20 members
        "medium" → board has 21–60 members
        "low"    → board has > 60 members
    - If EM lookup fails entirely, returns an empty peer list with
      confidence "low" rather than falling back to a full-market pool.
    """
    # ── Step 1: resolve EM industry label ────────────────────────────────
    industry = ""
    try:
        df_info = _em_call(ak.stock_individual_info_em, symbol=code,
                      retries=1, base_delay=4.0)
        info = dict(zip(df_info["item"], df_info["value"]))
        industry = str(info.get("行业", ""))
    except Exception as exc:
        log.warning("EM info lookup failed for %s: %s", code, exc)

    if not industry:
        return {
            "code": code, "industry": "unknown", "peers": [],
            "match_method": "none", "confidence": "low",
            "as_of": _ts(), "source": SOURCE,
            "units": {"market_cap_yi": "亿元"},
        }

    # ── Step 2: fetch industry board constituents ─────────────────────────
    try:
        df = _em_call(ak.stock_board_industry_cons_em, symbol=industry,
                 retries=1, base_delay=4.0)
    except Exception as exc:
        return _err(code, f"EM industry board '{industry}' lookup failed: {exc}")

    code_col = _df_col(df, "代码", "code")
    name_col = _df_col(df, "名称", "name")
    mc_col = _df_col(df, "总市值", "流通市值", "市值")
    if code_col is None:
        return _err(code, "No code column in EM industry data")

    total_in_board = len(df)

    # ── Step 3: sort by market cap descending (largest = most prominent) ────
    # No size filter — peers are chosen by business similarity (same industry
    # board), not by proximity to the subject's market cap.  The top-N by
    # market cap are the most widely-recognised names in the same industry.
    rows = df.copy()
    rows[code_col] = rows[code_col].astype(str).str.zfill(6)
    rows = rows[rows[code_col] != code]

    if mc_col:
        rows["_mc"] = rows[mc_col].apply(_safe_float)
        rows = rows.sort_values("_mc", ascending=False, na_position="last")

    peers: list[dict] = []
    for _, row in rows.iterrows():
        mc_val = _safe_float(row.get("_mc")) if "_mc" in row.index else (
            _safe_float(row[mc_col]) if mc_col else None
        )
        peers.append({
            "code": str(row[code_col]),
            "name": str(row[name_col]) if name_col else "",
            "market_cap_yi": round(mc_val / 1e8, 2) if mc_val else None,
            "pe_ttm": None,
            "industry": industry,
        })
        if len(peers) >= n:
            break

    # ── Step 4: confidence assessment ─────────────────────────────────────
    if total_in_board <= 20:
        confidence = "high"
    elif total_in_board <= 60:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "code": code,
        "industry": industry,
        "peers": peers,
        "match_method": "industry_board",
        "confidence": confidence,
        "as_of": _ts(),
        "source": SOURCE,
        "units": {"market_cap_yi": "亿元"},
    }


# ════════════════════════════════════════════════════════════════════════════
# Tool: search_stock
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_stock(query: str) -> list[dict]:
    """
    Resolve a stock name or code to up to 5 candidates.
    Chinese names → A-share (SSE+SZE). ASCII letters → also checks US stocks.
    Each result: {code, name, market, market_cap_yi or market_cap_b}.
    """
    cache_key = f"search:{query}"
    if hit := _cache_get(cache_key):
        return hit
    try:
        results = _search(query)
    except Exception as exc:
        results = [_err(query, str(exc))]
    _cache_set(cache_key, results)
    return results


def _em_symbol(code: str) -> str:
    """Convert bare A-share code to East Money SH/SZ uppercase prefix format."""
    if code.startswith("6") or code.startswith("9"):
        return "SH" + code
    return "SZ" + code


def _search(query: str) -> list[dict]:
    results: list[dict] = []
    q = query.strip()

    # ── A-share: search SSE listing ──────────────────────────────────────
    try:
        sh_df = _get_sse_listing()
        name_col = "证券简称"
        code_col = "证券代码"
        mask = (sh_df[name_col].astype(str).str.contains(q, na=False)
                | sh_df[code_col].astype(str).str.contains(q, na=False))
        for _, row in sh_df[mask].head(5).iterrows():
            results.append({
                "code": str(row[code_col]),
                "name": str(row[name_col]),
                "market": "A",
                "market_cap_yi": None,
                "as_of": _ts(), "source": SOURCE,
            })
    except Exception as exc:
        log.warning("SSE search error for '%s': %s", q, exc)

    # ── A-share: search SZE listing ──────────────────────────────────────
    if len(results) < 5:
        try:
            sz_df = _get_sze_listing()
            mask2 = (sz_df["name"].str.contains(q, na=False)
                     | sz_df["code"].str.contains(q, na=False))
            for _, row in sz_df[mask2].head(5 - len(results)).iterrows():
                results.append({
                    "code": str(row["code"]),
                    "name": str(row["name"]),
                    "market": "A",
                    "market_cap_yi": None,
                    "as_of": _ts(), "source": SOURCE,
                })
        except Exception as exc:
            log.warning("SZE search error for '%s': %s", q, exc)

    # ── US stocks (ASCII query only) ─────────────────────────────────────
    q_upper = q.upper()
    if len(results) < 5 and q.isascii():
        try:
            df_us = _em_call(ak.stock_us_spot_em)
            code_col_us = _df_col(df_us, "代码")
            name_col_us = _df_col(df_us, "名称")
            mc_col_us = _df_col(df_us, "总市值", "市值")
            if code_col_us and name_col_us:
                mask_us = (
                    df_us[code_col_us].astype(str).str.upper().str.endswith(q_upper)
                    | df_us[name_col_us].astype(str).str.upper().str.contains(
                        q_upper, na=False)
                )
                matches = df_us[mask_us].copy()
                if mc_col_us:
                    matches = matches.sort_values(mc_col_us, ascending=False)
                for _, row in matches.head(5 - len(results)).iterrows():
                    mc = _safe_float(row[mc_col_us]) if mc_col_us else None
                    raw_code = str(row[code_col_us])
                    clean_code = raw_code.split(".")[-1] if "." in raw_code else raw_code
                    results.append({
                        "code": clean_code,
                        "name": str(row[name_col_us]),
                        "market": "US",
                        "market_cap_b": round(mc / 1e9, 2) if mc else None,
                        "as_of": _ts(), "source": "akshare",
                    })
        except Exception as exc:
            log.warning("US akshare search error for '%s': %s", q, exc)

    # ── US yfinance fallback (ticker lookup when akshare found nothing) ───
    if len(results) < 5 and q.isascii() and not any(r.get("market") == "US" for r in results):
        try:
            info = yf.Ticker(q_upper).info
            name = info.get("shortName") or info.get("longName") or ""
            if name:
                mc = info.get("marketCap")
                results.append({
                    "code": q_upper,
                    "name": name,
                    "market": "US",
                    "market_cap_b": round(mc / 1e9, 2) if mc else None,
                    "as_of": _ts(), "source": "yfinance",
                })
        except Exception as exc:
            log.debug("yfinance search fallback failed for '%s': %s", q_upper, exc)

    return results[:5]


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_revenue_breakdown
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_revenue_breakdown(code: str, year: int | None = None) -> dict:
    """
    Return revenue breakdown by product line and by region for the most recent
    annual period (or the specified year).
    A-shares only. Returns {year, by_product, by_region, available}.
    """
    cache_key = f"revbk:{code}:{year or 'latest'}"
    if hit := _cache_get(cache_key):
        return hit
    if not _is_a_share(code):
        result = {"available": False, "reason": "get_revenue_breakdown supports A-shares only",
                  "as_of": _ts(), "source": SOURCE}
    else:
        try:
            result = _revenue_breakdown_a(code, year)
        except Exception as exc:
            log.warning("get_revenue_breakdown error %s: %s", code, exc)
            result = {"available": False, "reason": str(exc),
                      "as_of": _ts(), "source": SOURCE}
    _cache_set(cache_key, result)
    return result


def _revenue_breakdown_a(code: str, year: int | None) -> dict:
    symbol = _em_symbol(code)
    df = _em_call(ak.stock_zygc_em, symbol=symbol, retries=1, base_delay=4.0)
    if df is None or df.empty:
        return {"available": False, "reason": "stock_zygc_em returned empty",
                "as_of": _ts(), "source": SOURCE}

    # Parse dates and filter to annual reports (12-31) only
    df["_date"] = pd.to_datetime(df["报告日期"], errors="coerce")
    annual = df[df["_date"].dt.month == 12].copy()
    if annual.empty:
        annual = df.copy()

    # Pick target year
    if year is not None:
        annual = annual[annual["_date"].dt.year == year]
    else:
        # Use the most recent annual date
        latest_date = annual["_date"].max()
        annual = annual[annual["_date"] == latest_date]

    if annual.empty:
        return {"available": False, "reason": "no annual breakdown data found",
                "as_of": _ts(), "source": SOURCE}

    target_date = annual["_date"].iloc[0]
    report_year = int(target_date.year)

    by_product: list[dict] = []
    by_region: list[dict] = []

    for _, row in annual.iterrows():
        clf = str(row.get("分类类型", ""))
        name = str(row.get("主营构成", ""))
        rev = _safe_float(row.get("主营收入"))
        share = _safe_float(row.get("收入比例"))
        gross_margin = _safe_float(row.get("毛利率"))
        rev_yi = round(rev / 1e8, 4) if rev else None

        entry = {
            "name": name,
            "revenue_yi": rev_yi,
            "share": round(share, 4) if share is not None else None,
            "gross_margin": round(gross_margin, 4) if gross_margin is not None else None,
        }

        if clf == "按产品分类":
            by_product.append(entry)
        elif clf == "按地区分类":
            by_region.append(entry)

    return {
        "available": True,
        "year": report_year,
        "by_product": by_product,
        "by_region": by_region,
        "as_of": _ts(),
        "source": SOURCE,
    }


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_rd_history
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_rd_history(code: str, years: int = 5) -> dict:
    """
    Return R&D expense history for last `years` annual periods.
    Uses Sina income statement (利润表). A-shares only.
    Returns {history: [{year, rd_yi, rd_ratio, revenue_yi}]}.
    """
    cache_key = f"rd:{code}:{years}"
    if hit := _cache_get(cache_key):
        return hit
    if not _is_a_share(code):
        result = {"available": False, "reason": "get_rd_history supports A-shares only",
                  "history": [], "as_of": _ts(), "source": SOURCE}
    else:
        try:
            result = _rd_history_a(code, years)
        except Exception as exc:
            log.warning("get_rd_history error %s: %s", code, exc)
            result = {"available": False, "reason": str(exc),
                      "history": [], "as_of": _ts(), "source": SOURCE}
    _cache_set(cache_key, result)
    return result


def _rd_history_a(code: str, years: int) -> dict:
    symbol = _sina_symbol(code)
    df = ak.stock_financial_report_sina(stock=symbol, symbol="利润表")
    if df is None or df.empty:
        return {"available": False, "reason": "stock_financial_report_sina returned empty",
                "history": [], "as_of": _ts(), "source": SOURCE}

    # Filter to annual reports: 报告日 ends with 1231
    date_col = "报告日"
    df[date_col] = df[date_col].astype(str)
    annual = df[df[date_col].str.endswith("1231")].copy()
    annual = annual.sort_values(date_col, ascending=False).head(years)

    if annual.empty:
        return {"available": False, "reason": "no annual periods in income statement",
                "history": [], "as_of": _ts(), "source": SOURCE}

    history: list[dict] = []
    for _, row in annual.iterrows():
        year_str = str(row[date_col])[:4]
        rd = _safe_float(row.get("研发费用"))
        rev = _safe_float(row.get("营业总收入")) or _safe_float(row.get("营业收入"))
        rd_yi = round(rd / 1e8, 4) if rd is not None else None
        rev_yi = round(rev / 1e8, 4) if rev else None
        rd_ratio = round(rd / rev, 4) if (rd is not None and rev and rev != 0) else None
        history.append({
            "year": int(year_str),
            "rd_yi": rd_yi,
            "rd_ratio": rd_ratio,
            "revenue_yi": rev_yi,
        })

    return {
        "available": len(history) > 0,
        "history": history,
        "as_of": _ts(),
        "source": SOURCE,
    }


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_top_holders
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_top_holders(code: str) -> dict:
    """
    Return top-10 shareholders and north-bound (沪深港通) holdings for an A-share.
    Returns {as_of_quarter, top_holders, north_bound}.
    """
    cache_key = f"holders:{code}"
    if hit := _cache_get(cache_key):
        return hit
    if not _is_a_share(code):
        result = {"available": False, "reason": "get_top_holders supports A-shares only",
                  "top_holders": [], "as_of": _ts(), "source": SOURCE}
    else:
        try:
            result = _top_holders_a(code)
        except Exception as exc:
            log.warning("get_top_holders error %s: %s", code, exc)
            result = {"available": False, "reason": str(exc),
                      "top_holders": [], "as_of": _ts(), "source": SOURCE}
    _cache_set(cache_key, result)
    return result


def _top_holders_a(code: str) -> dict:
    # Determine latest quarter-end date
    today = date.today()
    # Latest completed quarter end
    q_month = ((today.month - 1) // 3) * 3  # 0, 3, 6, 9
    if q_month == 0:
        q_year, q_month = today.year - 1, 12
    else:
        q_year = today.year
    quarter_date = f"{q_year}{q_month:02d}{'30' if q_month in (6, 9) else '31'}"
    as_of_quarter = f"{q_year}-Q{(q_month // 3)}"

    sym_lower = _sina_symbol(code)  # sh600519 format

    top_holders: list[dict] = []
    try:
        df = _em_call(ak.stock_gdfx_top_10_em, symbol=sym_lower, date=quarter_date,
                      retries=1, base_delay=4.0)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = str(row.get("股东名称", ""))
                share_type = str(row.get("股份类型", ""))
                shares_raw = _safe_float(row.get("持股数", 0))
                pct_raw = _safe_float(row.get("占总股本持股比例"))
                change_raw = row.get("增减", "")
                shares_yi = round(shares_raw / 1e8, 4) if shares_raw else None
                pct = round(pct_raw / 100, 4) if pct_raw is not None else None
                # Normalise change field
                if isinstance(change_raw, (int, float)) and not pd.isna(change_raw):
                    change = f"{'+' if change_raw > 0 else ''}{change_raw:,.0f}"
                else:
                    change = str(change_raw) if change_raw and str(change_raw) != "nan" else "未知"
                top_holders.append({
                    "name": name,
                    "type": share_type,
                    "shares_yi": shares_yi,
                    "pct": pct,
                    "change": change,
                })
    except Exception as exc:
        log.debug("stock_gdfx_top_10_em failed for %s: %s", code, exc)

    # North-bound holdings
    north_bound: dict = {}
    try:
        nb_df = _em_call(ak.stock_hsgt_individual_em, symbol=code, retries=1, base_delay=4.0)
        if nb_df is not None and not nb_df.empty:
            latest = nb_df.sort_values("持股日期", ascending=False).iloc[0]
            # 30-day trend: compare latest vs 30 days ago
            nb_df["持股日期"] = pd.to_datetime(nb_df["持股日期"], errors="coerce")
            cutoff = nb_df["持股日期"].max() - pd.Timedelta(days=30)
            old = nb_df[nb_df["持股日期"] <= cutoff]
            shares_now = _safe_float(latest.get("持股数量"))
            shares_pct = _safe_float(latest.get("持股数量占A股百分比"))
            if not old.empty:
                shares_old = _safe_float(old.iloc[-1].get("持股数量"))
                if shares_now and shares_old:
                    if shares_now > shares_old * 1.005:
                        trend_30d = "净增持"
                    elif shares_now < shares_old * 0.995:
                        trend_30d = "净减持"
                    else:
                        trend_30d = "持平"
                else:
                    trend_30d = "未知"
            else:
                trend_30d = "未知"
            north_bound = {
                "shares_yi": round(shares_now / 1e8, 4) if shares_now else None,
                "pct": round(shares_pct / 100, 4) if shares_pct is not None else None,
                "trend_30d": trend_30d,
            }
    except Exception as exc:
        log.debug("stock_hsgt_individual_em failed for %s: %s", code, exc)

    return {
        "available": len(top_holders) > 0,
        "as_of": _ts(),
        "as_of_quarter": as_of_quarter,
        "top_holders": top_holders,
        "north_bound": north_bound if north_bound else None,
        "source": SOURCE,
    }


# ════════════════════════════════════════════════════════════════════════════
# Tool: get_unlock_schedule
# ════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_unlock_schedule(code: str, days: int = 365) -> dict:
    """
    Return upcoming restricted-share unlock events for an A-share in the next
    `days` days. Uses East Money detail endpoint filtered by stock code.
    Returns {events: [{date, shares_yi, shares_pct, type, value_yi_estimated}],
             total_in_window}.
    """
    cache_key = f"unlock:{code}:{days}"
    if hit := _cache_get(cache_key):
        return hit
    if not _is_a_share(code):
        result = {"available": False, "reason": "get_unlock_schedule supports A-shares only",
                  "events": [], "total_in_window": 0, "as_of": _ts(), "source": SOURCE}
    else:
        try:
            result = _unlock_schedule_a(code, days)
        except Exception as exc:
            log.warning("get_unlock_schedule error %s: %s", code, exc)
            result = {"available": False, "reason": str(exc),
                      "events": [], "total_in_window": 0, "as_of": _ts(), "source": SOURCE}
    _cache_set(cache_key, result)
    return result


def _unlock_schedule_a(code: str, days: int) -> dict:
    start = date.today()
    end = start + timedelta(days=days)
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    df = _em_call(ak.stock_restricted_release_detail_em,
             start_date=start_str, end_date=end_str,
             retries=1, base_delay=6.0)

    if df is None or df.empty:
        return {"available": True, "events": [], "total_in_window": 0,
                "as_of": _ts(), "source": SOURCE}

    code_col = _df_col(df, "股票代码")
    if code_col is None:
        return {"available": False, "reason": "no stock code column in unlock data",
                "events": [], "total_in_window": 0, "as_of": _ts(), "source": SOURCE}

    filtered = df[df[code_col].astype(str).str.zfill(6) == code].copy()
    if filtered.empty:
        return {"available": True, "events": [], "total_in_window": 0,
                "as_of": _ts(), "source": SOURCE}

    events: list[dict] = []
    for _, row in filtered.iterrows():
        date_val = str(row.get("解禁时间", ""))
        shares_raw = _safe_float(row.get("实际解禁数量") or row.get("解禁数量"))
        mc_raw = _safe_float(row.get("实际解禁市值"))
        pct_raw = _safe_float(row.get("占解禁前流通市值比例"))
        unlock_type = str(row.get("限售股类型", ""))
        shares_yi = round(shares_raw / 1e8, 4) if shares_raw else None
        value_yi = round(mc_raw / 1e8, 4) if mc_raw else None
        events.append({
            "date": date_val[:10] if date_val else "",
            "shares_yi": shares_yi,
            "shares_pct": round(pct_raw, 4) if pct_raw is not None else None,
            "type": unlock_type,
            "value_yi_estimated": value_yi,
        })

    total = sum(e["shares_yi"] or 0 for e in events)

    return {
        "available": True,
        "events": events,
        "total_in_window": round(total, 4),
        "as_of": _ts(),
        "source": SOURCE,
    }


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("Starting foliopage-stock MCP server (stdio transport) …")
    mcp.run(transport="stdio")
