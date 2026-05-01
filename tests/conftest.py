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
