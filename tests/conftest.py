"""
pytest configuration for foliopage tests.

For integration tests we clear the server cache ONCE per session.
This lets expensive full-market fetches (stock_zh_a_spot_em etc.) be shared
across tests instead of re-fetching on every case.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session", autouse=True)
def clear_stock_cache_once():
    """Clear the in-process cache at the start of the test session."""
    import tools.stock_mcp.server as srv

    with srv._LOCK:
        srv._CACHE.clear()
    yield


@pytest.fixture(autouse=True)
def isolated_disk_cache(tmp_path, monkeypatch):
    """
    Each unit test gets its own empty SQLite cache. Without this, the shared
    ~/.foliopage/cache.db from prior real agent runs would short-circuit mocked
    tool calls (e.g. test_cache_prevents_second_akshare_call expects akshare to
    be called once, but disk hits from a real research session make it zero).
    Also clears the in-memory caches in stock_mcp / chart_mcp / news_mcp so
    tests start from a fully cold state.
    """
    import importlib

    db = tmp_path / "test_cache.db"
    monkeypatch.setenv("FOLIOPAGE_CACHE_DB", str(db))

    try:
        from tools._shared import cache_store
        cache_store.reset_thread_local_conn()
    except ImportError:
        pass

    # Bypass disk cache in unit tests entirely: most tests mock akshare and
    # check call counts; a stale disk hit (from another test in the same run,
    # or from a prior real agent run) would short-circuit the mock and break
    # those assertions. We monkeypatch the module-level disk_get/disk_set that
    # each MCP server imported at load time.
    noop_get = lambda key: None
    noop_set = lambda key, value, ttl_s: None
    for mod_name in ("tools.stock_mcp.server",
                     "tools.chart_mcp.server",
                     "tools.news_mcp.server"):
        try:
            mod = importlib.import_module(mod_name)
            with mod._LOCK:
                mod._CACHE.clear()
            monkeypatch.setattr(mod, "disk_get", noop_get, raising=False)
            monkeypatch.setattr(mod, "disk_set", noop_set, raising=False)
        except (ImportError, AttributeError):
            pass

    yield
