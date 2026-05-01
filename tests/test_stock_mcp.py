"""
Tests for tools/stock_mcp/server.py

Run integration tests (real network):
    uv run pytest tests/ -m integration -v

Run unit tests only (mocked, offline):
    uv run pytest tests/ -m "not integration" -v
"""
from __future__ import annotations

import os
import sys
import threading
from unittest.mock import patch

import pandas as pd
import pytest

# Ensure the project root is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ════════════════════════════════════════════════════════════════════════════
# Unit tests — mocked, no network
# ════════════════════════════════════════════════════════════════════════════

def test_cache_prevents_second_akshare_call():
    """
    Call get_basic_info twice for the same A-share; akshare should be
    called exactly once — the second call must be served from cache.
    """
    from tools.stock_mcp import server

    fake_df = pd.DataFrame({
        "item": ["股票简称", "行业", "总市值", "上市时间"],
        "value": ["贵州茅台", "白酒", "2000000000000", "2001-08-27"],
    })

    # Reset cache before test
    with server._LOCK:
        server._CACHE.clear()

    call_count = 0

    def fake_individual_info(symbol):
        nonlocal call_count
        call_count += 1
        return fake_df

    with patch.object(
        server.ak, "stock_individual_info_em", side_effect=fake_individual_info
    ):
        r1 = server.get_basic_info("600519")
        r2 = server.get_basic_info("600519")

    assert call_count == 1, (
        f"akshare was called {call_count} times; expected 1 (cache miss + 1 hit)"
    )
    assert r1["name"] == "贵州茅台"
    assert r1 is r2  # same object returned from cache


def test_cache_is_thread_safe():
    """Multiple threads calling get_basic_info simultaneously should not crash."""
    from tools.stock_mcp import server

    fake_df = pd.DataFrame({
        "item": ["股票简称", "行业", "总市值", "上市时间"],
        "value": ["测试股票", "测试行业", "100000000000", "2000-01-01"],
    })

    with server._LOCK:
        server._CACHE.clear()

    errors: list[Exception] = []

    def fake_individual_info(symbol):
        import time
        time.sleep(0.01)  # simulate latency
        return fake_df

    def call_it():
        try:
            with patch.object(server.ak, "stock_individual_info_em",
                              side_effect=fake_individual_info):
                server.get_basic_info("000001")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=call_it) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread-safety errors: {errors}"


def test_error_dict_on_exception():
    """If akshare raises during kline fetch, get_basic_info returns an error dict."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    # The new architecture calls stock_zh_a_daily (Sina) for market cap.
    # Mock it to raise so we can verify graceful error handling.
    with patch.object(
        server.ak,
        "stock_zh_a_daily",
        side_effect=RuntimeError("network timeout"),
    ):
        result = server.get_basic_info("999999")

    assert "error" in result, f"Expected error dict, got: {result}"
    assert "network timeout" in result["error"]
    assert result["code"] == "999999"
    assert "as_of" in result


# ════════════════════════════════════════════════════════════════════════════
# Integration tests — real network calls.
# Cache is cleared ONCE per session by conftest.py; individual tests share
# the cache so expensive full-market fetches are not repeated.
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_basic_info_maotai():
    """get_basic_info('600519') should return 贵州茅台."""
    from tools.stock_mcp.server import get_basic_info

    result = get_basic_info("600519")

    assert "error" not in result, f"Unexpected error: {result}"
    assert "贵州茅台" in result["name"], f"Expected 贵州茅台, got: {result['name']}"
    assert result["code"] == "600519"
    assert result["market_cap_yi"] is not None
    assert result["market_cap_yi"] > 0
    assert result["source"] == "akshare"
    assert "as_of" in result


@pytest.mark.integration
def test_basic_info_aapl():
    """get_basic_info('AAPL') should return a name containing 'Apple' via akshare or yfinance."""
    from tools.stock_mcp.server import get_basic_info

    result = get_basic_info("AAPL")

    assert "error" not in result, f"Unexpected error: {result}"
    assert "apple" in result["name"].lower(), (
        f"Expected name to contain 'Apple', got: {result['name']}"
    )
    assert result["code"] == "AAPL"
    assert result["source"] in ("akshare", "yfinance"), (
        f"Expected source to be akshare or yfinance, got: {result['source']}"
    )
    assert result.get("market_cap_b") is not None
    assert result["market_cap_b"] > 0


@pytest.mark.integration
def test_kline_maotai_1m():
    """get_kline('600519', '1M') should return >= 15 daily bars."""
    from tools.stock_mcp.server import get_kline

    result = get_kline("600519", "1M")

    assert "error" not in result, f"Unexpected error: {result}"
    assert result["count"] >= 15, (
        f"Expected >= 15 bars for 1M range, got {result['count']}"
    )
    assert len(result["bars"]) == result["count"]

    # Validate bar structure
    bar = result["bars"][0]
    for field in ("date", "open", "high", "low", "close", "volume"):
        assert field in bar, f"Missing field '{field}' in bar: {bar}"
    assert bar["high"] >= bar["low"], "high < low in a bar"


@pytest.mark.integration
def test_kline_maotai_1y_count():
    """get_kline('600519', '1Y') should return ~250 trading days."""
    from tools.stock_mcp.server import get_kline

    result = get_kline("600519", "1Y")

    assert "error" not in result, f"Unexpected error: {result}"
    # Chinese stock market has ~245 trading days per year
    assert result["count"] >= 200, (
        f"Expected >= 200 bars for 1Y range, got {result['count']}"
    )


@pytest.mark.integration
def test_search_maotai():
    """search_stock('茅台') should include 600519 in results."""
    from tools.stock_mcp.server import search_stock

    results = search_stock("茅台")

    assert isinstance(results, list), "search_stock should return a list"
    assert len(results) >= 1, "Expected at least one result for '茅台'"

    codes = [r.get("code") for r in results]
    assert "600519" in codes, (
        f"Expected 600519 in results, got codes: {codes}"
    )


@pytest.mark.integration
def test_search_apple():
    """search_stock('AAPL') should find Apple via akshare or yfinance fallback."""
    from tools.stock_mcp.server import search_stock

    results = search_stock("AAPL")

    assert isinstance(results, list)
    assert len(results) >= 1, f"Expected at least one result, got: {results}"
    names = [r.get("name", "").lower() for r in results]
    codes = [r.get("code") for r in results]
    assert any("apple" in n for n in names) or "AAPL" in codes, (
        f"Expected Apple in results, got: {results}"
    )


@pytest.mark.integration
def test_get_valuation_maotai():
    """get_valuation('600519') should return numeric PE and PB."""
    from tools.stock_mcp.server import get_valuation

    result = get_valuation("600519")

    assert "error" not in result, f"Unexpected error: {result}"
    assert result.get("pe_ttm") is not None, "PE should not be None for 茅台"
    assert result.get("pb") is not None, "PB should not be None for 茅台"
    assert isinstance(result["pe_ttm"], float)
    assert result["pe_ttm"] > 0


@pytest.mark.integration
def test_get_financials_maotai():
    """get_financials('600519') should return at least 3 annual periods."""
    from tools.stock_mcp.server import get_financials

    result = get_financials("600519", "annual")

    assert "error" not in result, f"Unexpected error: {result}"
    assert "periods" in result
    assert len(result["periods"]) >= 3, (
        f"Expected >= 3 annual periods, got {len(result['periods'])}"
    )


@pytest.mark.integration
def test_get_peers_maotai():
    """get_peers('600519') should return peer companies in 白酒 industry."""
    from tools.stock_mcp.server import get_peers

    result = get_peers("600519", n=5)

    assert "error" not in result, f"Unexpected error: {result}"
    assert "peers" in result
    assert len(result["peers"]) >= 1, "Expected at least 1 peer"
    # Should not include itself
    peer_codes = [p["code"] for p in result["peers"]]
    assert "600519" not in peer_codes, "Stock should not be listed as its own peer"


@pytest.mark.integration
def test_kline_aapl_1m():
    """get_kline('AAPL', '1M') should return >= 15 daily bars via akshare or yfinance."""
    from tools.stock_mcp.server import get_kline

    result = get_kline("AAPL", "1M")

    assert "error" not in result, f"Unexpected error: {result}"
    assert result["count"] >= 15, (
        f"Expected >= 15 bars for 1M range, got {result['count']}"
    )
    assert len(result["bars"]) == result["count"]
    assert result["source"] in ("akshare", "yfinance")

    bar = result["bars"][0]
    for field in ("date", "open", "high", "low", "close", "volume"):
        assert field in bar, f"Missing field '{field}' in bar: {bar}"
    assert bar["high"] >= bar["low"], "high < low in a bar"


@pytest.mark.integration
def test_cache_hit_on_second_integration_call():
    """Second real call returns same object (cache hit) within TTL."""
    from tools.stock_mcp.server import get_basic_info

    r1 = get_basic_info("000858")  # 五粮液
    r2 = get_basic_info("000858")

    assert r1 is r2, "Cache miss on second call — cache not working"


def test_basic_info_aapl_yfinance_fallback():
    """When akshare US endpoint fails, get_basic_info falls back to yfinance."""
    from unittest.mock import MagicMock

    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    mock_ticker = MagicMock()
    mock_ticker.info = {
        "shortName": "Apple Inc.",
        "marketCap": 3_000_000_000_000,
        "sector": "Technology",
    }

    with patch.object(server.ak, "stock_us_spot_em",
                      side_effect=RuntimeError("EM rate limited")):
        with patch.object(server.yf, "Ticker", return_value=mock_ticker) as mock_yf_ticker:
            result = server.get_basic_info("AAPL")

    assert "error" not in result, f"Unexpected error: {result}"
    assert result["source"] == "yfinance"
    assert "apple" in result["name"].lower()
    assert result["market_cap_b"] == 3000.0
    mock_yf_ticker.assert_called_once_with("AAPL")


# ════════════════════════════════════════════════════════════════════════════
# Unit tests — get_peers (mocked, no network)
# ════════════════════════════════════════════════════════════════════════════

def _make_em_info_df(industry: str) -> pd.DataFrame:
    return pd.DataFrame({
        "item": ["股票简称", "行业", "总市值"],
        "value": ["测试股票", industry, "10000000000"],
    })


def _make_board_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal industry-board DataFrame from a list of dicts."""
    return pd.DataFrame(rows)


class TestGetPeers:
    def setup_method(self):
        from tools.stock_mcp import server
        with server._LOCK:
            server._CACHE.clear()

    def test_returns_required_fields(self):
        """get_peers response must include industry, match_method, confidence, peers."""
        from tools.stock_mcp import server

        board = _make_board_df([
            {"代码": "000001", "名称": "平安银行", "总市值": 5e11},
            {"代码": "000002", "名称": "万科A",   "总市值": 3e11},
            {"代码": "600519", "名称": "贵州茅台", "总市值": 2e12},  # subject — excluded
        ])
        info_df = _make_em_info_df("测试行业")

        with (
            patch.object(server.ak, "stock_individual_info_em", return_value=info_df),
            patch.object(server.ak, "stock_board_industry_cons_em", return_value=board),
            patch.object(server, "_quick_market_cap_yi", return_value=None),
        ):
            result = server.get_peers("600519", n=2)

        for field in ("industry", "match_method", "confidence", "peers"):
            assert field in result, f"Missing field '{field}' in response"
        assert result["match_method"] == "industry_board"
        assert result["confidence"] in ("high", "medium", "low")

    def test_subject_excluded_from_peers(self):
        """The subject stock itself must not appear in the peers list."""
        from tools.stock_mcp import server

        board = _make_board_df([
            {"代码": "600519", "名称": "贵州茅台", "总市值": 2e12},
            {"代码": "000858", "名称": "五粮液",   "总市值": 8e11},
        ])
        info_df = _make_em_info_df("白酒")

        with (
            patch.object(server.ak, "stock_individual_info_em", return_value=info_df),
            patch.object(server.ak, "stock_board_industry_cons_em", return_value=board),
            patch.object(server, "_quick_market_cap_yi", return_value=None),
        ):
            result = server.get_peers("600519", n=5)

        peer_codes = [p["code"] for p in result["peers"]]
        assert "600519" not in peer_codes

    def test_peers_sorted_by_market_cap_descending(self):
        """Peers are returned in descending market-cap order (most prominent first)."""
        from tools.stock_mcp import server

        board = _make_board_df([
            {"代码": "000001", "名称": "小公司",  "总市值": 1e9},    # 10 亿元
            {"代码": "000002", "名称": "超大公司", "总市值": 5e12},   # 50000 亿元 — largest
            {"代码": "000003", "名称": "中公司",  "总市值": 1e11},   # 1000 亿元
        ])
        info_df = _make_em_info_df("测试行业")

        with (
            patch.object(server.ak, "stock_individual_info_em", return_value=info_df),
            patch.object(server.ak, "stock_board_industry_cons_em", return_value=board),
        ):
            result = server.get_peers("600519", n=5)

        peer_codes = [p["code"] for p in result["peers"]]
        # All three should appear (no size filter), largest first
        assert peer_codes.index("000002") < peer_codes.index("000003"), "超大公司 should precede 中公司"
        assert peer_codes.index("000003") < peer_codes.index("000001"), "中公司 should precede 小公司"

    def test_confidence_high_for_small_board(self):
        """Board with ≤ 20 members → confidence 'high'."""
        from tools.stock_mcp import server

        board = _make_board_df([
            {"代码": f"00{i:04d}", "名称": f"公司{i}", "总市值": 1e10}
            for i in range(15)
        ])
        info_df = _make_em_info_df("白酒")

        with (
            patch.object(server.ak, "stock_individual_info_em", return_value=info_df),
            patch.object(server.ak, "stock_board_industry_cons_em", return_value=board),
            patch.object(server, "_quick_market_cap_yi", return_value=None),
        ):
            result = server.get_peers("600519", n=5)

        assert result["confidence"] == "high"

    def test_confidence_low_for_large_board(self):
        """Board with > 60 members → confidence 'low'."""
        from tools.stock_mcp import server

        board = _make_board_df([
            {"代码": f"{i:06d}", "名称": f"公司{i}", "总市值": 1e10}
            for i in range(100)
        ])
        info_df = _make_em_info_df("机械行业")

        with (
            patch.object(server.ak, "stock_individual_info_em", return_value=info_df),
            patch.object(server.ak, "stock_board_industry_cons_em", return_value=board),
            patch.object(server, "_quick_market_cap_yi", return_value=None),
        ):
            result = server.get_peers("600519", n=5)

        assert result["confidence"] == "low"

    def test_em_failure_returns_empty_peers_not_error(self):
        """If EM lookup fails entirely, return empty peers with confidence 'low'."""
        from tools.stock_mcp import server

        with patch.object(server.ak, "stock_individual_info_em",
                          side_effect=RuntimeError("rate limited")):
            result = server.get_peers("600519", n=5)

        assert result["peers"] == []
        assert result["confidence"] == "low"
        assert "error" not in result


# ════════════════════════════════════════════════════════════════════════════
# Integration tests — get_peers (real network)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_peers_maotai_returns_liquor_peers():
    """get_peers('600519') should return Wuliangye (000858) or Luzhou Laojiao (000568)."""
    from tools.stock_mcp.server import get_peers

    result = get_peers("600519", n=5)

    assert "error" not in result, f"Unexpected error: {result}"
    assert len(result["peers"]) >= 3, (
        f"Expected >= 3 peers for 茅台, got {len(result['peers'])}"
    )
    peer_codes = {p["code"] for p in result["peers"]}
    # At least one of the two main liquor peers should appear
    assert peer_codes & {"000858", "000568"}, (
        f"Expected 五粮液 (000858) or 泸州老窖 (000568) in peers, got: {peer_codes}"
    )
    for field in ("industry", "match_method", "confidence"):
        assert field in result


@pytest.mark.integration
def test_peers_yonyou_excludes_maotai():
    """get_peers('600588') (用友网络, software) should not include 茅台 or 五粮液."""
    from tools.stock_mcp.server import get_peers

    result = get_peers("600588", n=5)

    assert "error" not in result, f"Unexpected error: {result}"
    peer_codes = {p["code"] for p in result["peers"]}
    for bad in ("600519", "000858", "000568", "002202"):  # 茅台, 五粮液, 泸州, 金风科技
        assert bad not in peer_codes, (
            f"Unrelated stock {bad} appeared in 用友网络 peers: {peer_codes}"
        )


# ════════════════════════════════════════════════════════════════════════════
# Unit tests — 4 new tools (mocked, no network)
# ════════════════════════════════════════════════════════════════════════════

def test_get_revenue_breakdown_non_a_share_returns_unavailable():
    """get_revenue_breakdown for a non-A-share code returns available=False."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    result = server.get_revenue_breakdown("AAPL")
    assert result["available"] is False
    assert "A-shares" in result["reason"]


def test_get_revenue_breakdown_parses_product_and_region():
    """get_revenue_breakdown correctly splits by_product and by_region."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    fake_df = pd.DataFrame([
        {"股票代码": "600519", "报告日期": "2025-12-31", "分类类型": "按产品分类",
         "主营构成": "茅台酒", "主营收入": 1.46e11, "收入比例": 0.87,
         "主营成本": 9.5e9, "成本比例": 0.64, "主营利润": 1.36e11,
         "利润比例": 0.89, "毛利率": 0.935},
        {"股票代码": "600519", "报告日期": "2025-12-31", "分类类型": "按地区分类",
         "主营构成": "国内", "主营收入": 1.64e11, "收入比例": 0.97,
         "主营成本": 1.44e10, "成本比例": 0.97, "主营利润": 1.50e11,
         "利润比例": 0.97, "毛利率": 0.912},
    ])

    with patch.object(server.ak, "stock_zygc_em", return_value=fake_df):
        result = server.get_revenue_breakdown("600519")

    assert result["available"] is True
    assert result["year"] == 2025
    assert len(result["by_product"]) == 1
    assert result["by_product"][0]["name"] == "茅台酒"
    assert len(result["by_region"]) == 1
    assert result["by_region"][0]["name"] == "国内"


def test_get_rd_history_non_a_share_returns_empty():
    """get_rd_history for a non-A-share returns available=False with empty history."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    result = server.get_rd_history("AAPL")
    assert result["available"] is False
    assert result["history"] == []


def test_get_rd_history_computes_ratio():
    """get_rd_history correctly computes rd_ratio = rd / revenue."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    fake_df = pd.DataFrame([
        {"报告日": "20251231", "研发费用": 1.35e9, "营业总收入": 6.5e9},
        {"报告日": "20241231", "研发费用": 1.22e9, "营业总收入": 1.17e9},
    ])

    with patch.object(server.ak, "stock_financial_report_sina", return_value=fake_df):
        result = server.get_rd_history("688256", years=5)

    assert result["available"] is True
    assert len(result["history"]) == 2
    h = result["history"][0]
    assert h["year"] == 2025
    assert h["rd_yi"] is not None
    assert h["rd_ratio"] is not None
    assert abs(h["rd_ratio"] - round(1.35e9 / 6.5e9, 4)) < 1e-6


def test_get_top_holders_non_a_share_returns_unavailable():
    """get_top_holders for a non-A-share returns available=False."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    result = server.get_top_holders("AAPL")
    assert result["available"] is False


def test_get_top_holders_parses_holders():
    """get_top_holders correctly parses holder list from gdfx mock."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    fake_df = pd.DataFrame([
        {"名次": 1, "股东名称": "中国贵州茅台酒厂(集团)有限责任公司",
         "股份类型": "流通A股", "持股数": 679211576, "占总股本持股比例": 54.07,
         "增减": "不变", "变动比率": float("nan")},
        {"名次": 2, "股东名称": "香港中央结算有限公司",
         "股份类型": "流通A股", "持股数": 77511622, "占总股本持股比例": 6.17,
         "增减": -3527332, "变动比率": -4.35},
    ])

    with (
        patch.object(server.ak, "stock_gdfx_top_10_em", return_value=fake_df),
        patch.object(server.ak, "stock_hsgt_individual_em",
                     side_effect=RuntimeError("not available")),
    ):
        result = server.get_top_holders("600519")

    assert result["available"] is True
    assert len(result["top_holders"]) == 2
    assert result["top_holders"][0]["name"] == "中国贵州茅台酒厂(集团)有限责任公司"
    assert result["top_holders"][0]["pct"] is not None
    assert result["north_bound"] is None


def test_get_unlock_schedule_non_a_share_returns_unavailable():
    """get_unlock_schedule for a non-A-share returns available=False."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    result = server.get_unlock_schedule("AAPL")
    assert result["available"] is False


def test_get_unlock_schedule_filters_by_code():
    """get_unlock_schedule returns only events for the requested stock code."""
    from tools.stock_mcp import server

    with server._LOCK:
        server._CACHE.clear()

    fake_df = pd.DataFrame([
        {"序号": 1, "股票代码": "688256", "股票简称": "寒武纪",
         "解禁时间": "2026-07-22", "限售股类型": "首发原股东限售股",
         "解禁数量": 1.8e7, "实际解禁数量": 1.8e7,
         "实际解禁市值": 2.35e10, "占解禁前流通市值比例": 0.084,
         "解禁前一交易日收盘价": 1307.0, "解禁前20日涨跌幅": 17.96,
         "解禁后20日涨跌幅": float("nan")},
        {"序号": 2, "股票代码": "600519", "股票简称": "贵州茅台",
         "解禁时间": "2026-09-01", "限售股类型": "股权激励限售股",
         "解禁数量": 5e5, "实际解禁数量": 5e5,
         "实际解禁市值": 9e8, "占解禁前流通市值比例": 0.001,
         "解禁前一交易日收盘价": 1800.0, "解禁前20日涨跌幅": 1.2,
         "解禁后20日涨跌幅": float("nan")},
    ])

    with patch.object(server.ak, "stock_restricted_release_detail_em",
                      return_value=fake_df):
        result = server.get_unlock_schedule("688256", days=365)

    assert result["available"] is True
    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == "首发原股东限售股"
    assert result["total_in_window"] > 0


# ════════════════════════════════════════════════════════════════════════════
# Integration tests — 4 new tools (real network)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_get_revenue_breakdown_maotai():
    """get_revenue_breakdown('600519') should return by_product and by_region."""
    from tools.stock_mcp.server import get_revenue_breakdown

    result = get_revenue_breakdown("600519")

    assert result["available"] is True, f"Unexpected unavailable: {result}"
    assert len(result["by_product"]) >= 1
    assert len(result["by_region"]) >= 1
    assert result["year"] is not None
    first = result["by_product"][0]
    assert first["revenue_yi"] is not None and first["revenue_yi"] > 0


@pytest.mark.integration
def test_get_revenue_breakdown_cambricon():
    """get_revenue_breakdown('688256') should return available breakdown."""
    from tools.stock_mcp.server import get_revenue_breakdown

    result = get_revenue_breakdown("688256")

    # 688256 may have limited breakdown data but should not error out
    assert "error" not in result, f"Unexpected error dict: {result}"
    assert "available" in result


@pytest.mark.integration
def test_get_rd_history_maotai():
    """get_rd_history('600519') should return history (may be empty for 茅台)."""
    from tools.stock_mcp.server import get_rd_history

    result = get_rd_history("600519")

    assert "error" not in result, f"Unexpected error dict: {result}"
    assert "history" in result
    # 茅台 may not have R&D expense; just verify structure
    if result["available"] and result["history"]:
        h = result["history"][0]
        assert "year" in h and "rd_yi" in h and "rd_ratio" in h


@pytest.mark.integration
def test_get_rd_history_cambricon():
    """get_rd_history('688256') should return R&D history with ratios."""
    from tools.stock_mcp.server import get_rd_history

    result = get_rd_history("688256")

    assert "error" not in result, f"Unexpected error dict: {result}"
    assert result["available"] is True, f"Expected available, got: {result}"
    assert len(result["history"]) >= 1
    h = result["history"][0]
    assert h["rd_yi"] is not None and h["rd_yi"] > 0


@pytest.mark.integration
def test_get_top_holders_maotai():
    """get_top_holders('600519') should return at least 5 top shareholders."""
    from tools.stock_mcp.server import get_top_holders

    result = get_top_holders("600519")

    assert result["available"] is True, f"Unexpected unavailable: {result}"
    assert len(result["top_holders"]) >= 5
    h = result["top_holders"][0]
    assert h["name"] != ""
    assert h["pct"] is not None


@pytest.mark.integration
def test_get_top_holders_cambricon():
    """get_top_holders('688256') should return holder data."""
    from tools.stock_mcp.server import get_top_holders

    result = get_top_holders("688256")

    assert "error" not in result, f"Unexpected error dict: {result}"
    assert "top_holders" in result


@pytest.mark.integration
def test_get_unlock_schedule_maotai():
    """get_unlock_schedule('600519') should return a valid schedule (may be empty)."""
    from tools.stock_mcp.server import get_unlock_schedule

    result = get_unlock_schedule("600519", days=365)

    assert result["available"] is True, f"Unexpected unavailable: {result}"
    assert "events" in result
    assert isinstance(result["total_in_window"], float)


@pytest.mark.integration
def test_get_unlock_schedule_cambricon():
    """get_unlock_schedule('688256') should return unlock events if any exist."""
    from tools.stock_mcp.server import get_unlock_schedule

    result = get_unlock_schedule("688256", days=365)

    assert "error" not in result, f"Unexpected error dict: {result}"
    assert "events" in result
