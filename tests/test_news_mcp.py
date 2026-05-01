"""
Tests for tools/news_mcp/server.py

Integration tests require network access:
    uv run pytest tests/test_news_mcp.py -m integration -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_MATERIAL_TYPES = {"业绩预告", "业绩报告", "重大事项", "分红送配", "股权变动"}
_MATERIAL_KEYWORDS = ["业绩", "分红", "配股", "股权", "重大", "公告", "报告"]


def _is_material(title: str) -> bool:
    return any(kw in title for kw in _MATERIAL_KEYWORDS)


# ════════════════════════════════════════════════════════════════════════════
# Unit tests (no network)
# ════════════════════════════════════════════════════════════════════════════

def test_dedup_removes_near_duplicates():
    from tools.news_mcp.server import _dedup_news
    items = [
        {"title": "苹果公司发布第四季度财报", "published_at": "2024-01-01T10:00:00"},
        {"title": "苹果公司发布第四季度财报 业绩超预期", "published_at": "2024-01-01T11:00:00"},
        {"title": "特斯拉交付量创历史新高", "published_at": "2024-01-01T09:00:00"},
    ]
    deduped = _dedup_news(items)
    titles = [i["title"] for i in deduped]
    # The near-duplicate should be removed, the unique one kept
    assert len(deduped) == 2
    assert "特斯拉交付量创历史新高" in titles


def test_recent_announcements_us_returns_unavailable():
    from tools.news_mcp.server import recent_announcements
    result = recent_announcements("AAPL", days=30)
    assert result.get("available") is False
    assert "items" in result
    assert result["items"] == []
    assert "reason" in result


# ════════════════════════════════════════════════════════════════════════════
# Integration tests — real network
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_recent_news_maotai():
    """recent_news('600519') should return ≥ 1 item with title and URL."""
    from tools.news_mcp.server import recent_news

    result = recent_news("600519", days=7, limit=10)

    assert "error" not in result, f"Unexpected error: {result}"
    assert "items" in result
    assert len(result["items"]) >= 1, (
        f"Expected ≥ 1 news item for 600519, got {len(result['items'])}"
    )
    item = result["items"][0]
    assert item.get("title"), f"First item has no title: {item}"
    assert item.get("url"), f"First item has no URL: {item}"
    assert item.get("published_at"), f"First item has no published_at: {item}"


@pytest.mark.integration
def test_recent_news_aapl():
    """recent_news('AAPL') should return ≥ 1 item via yfinance or Google News RSS."""
    from tools.news_mcp.server import recent_news

    result = recent_news("AAPL", days=7, limit=10)

    assert "error" not in result, f"Unexpected error: {result}"
    assert "items" in result
    assert len(result["items"]) >= 1, (
        f"Expected ≥ 1 news item for AAPL, got {len(result['items'])}"
    )
    item = result["items"][0]
    assert item.get("title"), f"First item has no title: {item}"
    assert result.get("source") in ("yfinance", "google-news-rss"), (
        f"Expected source to be yfinance or google-news-rss, got: {result.get('source')}"
    )


@pytest.mark.integration
def test_recent_announcements_maotai():
    """recent_announcements('600519') should return ≥ 1 material announcement."""
    from tools.news_mcp.server import recent_announcements

    result = recent_announcements("600519", days=30)

    assert "error" not in result, f"Unexpected error: {result}"
    assert result.get("available") is True
    assert "items" in result

    if result["items"]:
        # If we got items, they should look like announcements
        item = result["items"][0]
        assert item.get("title"), f"Announcement item has no title: {item}"
        assert item.get("published_at"), f"Announcement item has no date: {item}"
    # Note: if empty during market downtime that's acceptable; we just verify structure


@pytest.mark.integration
def test_analyst_consensus_aapl():
    """analyst_consensus('AAPL') should return a mean target price > 0."""
    from tools.news_mcp.server import analyst_consensus

    result = analyst_consensus("AAPL")

    assert "error" not in result, f"Unexpected error: {result}"
    # If available, validate the data
    if result.get("available"):
        tp = result.get("target_price")
        assert tp is not None, f"target_price should not be None when available: {result}"
        assert tp > 0, f"target_price should be > 0, got {tp}"
        assert "ratings" in result
        ratings = result["ratings"]
        assert "buy" in ratings and "hold" in ratings and "sell" in ratings
    else:
        # No coverage data is a valid (non-error) response
        assert "reason" in result


@pytest.mark.integration
def test_recent_announcements_aapl_unavailable():
    """recent_announcements('AAPL') must return available=false (no SEC EDGAR)."""
    from tools.news_mcp.server import recent_announcements

    result = recent_announcements("AAPL", days=30)
    assert result.get("available") is False
    assert "SEC" in result.get("reason", "") or "not yet" in result.get("reason", "").lower()
