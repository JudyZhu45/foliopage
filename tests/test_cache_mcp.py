"""
Unit tests for cache_mcp.

All tests use a temporary SQLite database — no persistent state.
Set FOLIOPAGE_CACHE_DB before importing the module to redirect DB path.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest


@pytest.fixture()
def cache_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Import cache_mcp.server with a temporary DB path.
    Re-imports the module fresh for each test to reset thread-local connections.
    """
    db_path = tmp_path / "test_cache.db"
    monkeypatch.setenv("FOLIOPAGE_CACHE_DB", str(db_path))

    # Remove cached module so the env var is re-read on fresh import
    for mod in list(sys.modules):
        if "cache_mcp" in mod:
            del sys.modules[mod]

    import tools.cache_mcp.server as srv
    # Patch _DB_PATH on the freshly imported module
    srv._DB_PATH = db_path
    # Also reset any thread-local connection
    if hasattr(srv._LOCAL, "conn"):
        try:
            srv._LOCAL.conn.close()
        except Exception:
            pass
        del srv._LOCAL.conn

    yield srv

    # Cleanup
    if hasattr(srv._LOCAL, "conn"):
        try:
            srv._LOCAL.conn.close()
        except Exception:
            pass


class TestCacheSet:
    def test_set_returns_true(self, cache_server) -> None:
        assert cache_server.cache_set("k1", {"x": 1}) is True

    def test_set_and_get_round_trip(self, cache_server) -> None:
        cache_server.cache_set("mykey", {"foo": "bar", "n": 42})
        result = cache_server.cache_get("mykey")
        assert result == {"foo": "bar", "n": 42}

    def test_overwrite_existing(self, cache_server) -> None:
        cache_server.cache_set("ow", {"v": 1})
        cache_server.cache_set("ow", {"v": 2})
        assert cache_server.cache_get("ow") == {"v": 2}

    def test_nested_dict(self, cache_server) -> None:
        cache_server.cache_set("nested", {"a": {"b": [1, 2, 3]}})
        result = cache_server.cache_get("nested")
        assert result["a"]["b"] == [1, 2, 3]

    def test_chinese_values(self, cache_server) -> None:
        cache_server.cache_set("cn", {"name": "贵州茅台", "code": "600519"})
        result = cache_server.cache_get("cn")
        assert result["name"] == "贵州茅台"


class TestCacheGet:
    def test_get_missing_returns_none(self, cache_server) -> None:
        assert cache_server.cache_get("nonexistent") is None

    def test_get_expired_returns_none(self, cache_server) -> None:
        # Store with 1-second TTL, then wait for expiry
        cache_server.cache_set("exp", {"v": 99}, ttl_s=1)
        # Manually expire by updating expires_at in DB
        conn = cache_server._db()
        conn.execute("UPDATE cache SET expires_at = ? WHERE key = ?", (int(time.time()) - 1, "exp"))
        conn.commit()
        assert cache_server.cache_get("exp") is None

    def test_get_expired_deletes_row(self, cache_server) -> None:
        cache_server.cache_set("del_exp", {"v": 1}, ttl_s=1)
        conn = cache_server._db()
        conn.execute("UPDATE cache SET expires_at = ? WHERE key = ?", (int(time.time()) - 1, "del_exp"))
        conn.commit()
        cache_server.cache_get("del_exp")
        # Row should be deleted
        row = conn.execute("SELECT 1 FROM cache WHERE key = ?", ("del_exp",)).fetchone()
        assert row is None


class TestCacheDelete:
    def test_delete_existing(self, cache_server) -> None:
        cache_server.cache_set("to_del", {"x": 1})
        assert cache_server.cache_delete("to_del") is True
        assert cache_server.cache_get("to_del") is None

    def test_delete_missing_returns_false(self, cache_server) -> None:
        assert cache_server.cache_delete("nope") is False

    def test_delete_then_set(self, cache_server) -> None:
        cache_server.cache_set("reuse", {"v": 1})
        cache_server.cache_delete("reuse")
        cache_server.cache_set("reuse", {"v": 2})
        assert cache_server.cache_get("reuse") == {"v": 2}


class TestCacheList:
    def test_list_empty(self, cache_server) -> None:
        assert cache_server.cache_list() == []

    def test_list_all_keys(self, cache_server) -> None:
        cache_server.cache_set("z_key", {"v": 1})
        cache_server.cache_set("a_key", {"v": 2})
        keys = cache_server.cache_list()
        assert "a_key" in keys
        assert "z_key" in keys
        # Sorted alphabetically
        assert keys == sorted(keys)

    def test_list_with_prefix(self, cache_server) -> None:
        cache_server.cache_set("stock:600519", {"v": 1})
        cache_server.cache_set("stock:000858", {"v": 2})
        cache_server.cache_set("news:600519", {"v": 3})
        stock_keys = cache_server.cache_list(prefix="stock:")
        assert "stock:600519" in stock_keys
        assert "stock:000858" in stock_keys
        assert "news:600519" not in stock_keys

    def test_list_excludes_expired(self, cache_server) -> None:
        cache_server.cache_set("live", {"v": 1})
        cache_server.cache_set("dead", {"v": 2})
        # Expire "dead"
        conn = cache_server._db()
        conn.execute("UPDATE cache SET expires_at = ? WHERE key = ?", (int(time.time()) - 1, "dead"))
        conn.commit()
        keys = cache_server.cache_list()
        assert "live" in keys
        assert "dead" not in keys

    def test_list_prefix_no_match(self, cache_server) -> None:
        cache_server.cache_set("alpha:1", {"v": 1})
        assert cache_server.cache_list(prefix="beta:") == []
