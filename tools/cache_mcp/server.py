"""
cache_mcp — MCP server providing a persistent SQLite-backed key/value cache.

Used by the agent to store rendered page fragments, resolved stock codes,
or other expensive-to-recompute data across sessions.

Storage: ~/.foliopage/cache.db  (configurable via FOLIOPAGE_CACHE_DB env var)
IMPORTANT: stdout is reserved for MCP JSON-RPC. All logging → stderr.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cache_mcp")

# ── MCP server ────────────────────────────────────────────────────────────────
mcp = FastMCP("foliopage-cache")

# ── SQLite connection (thread-safe, one connection per thread) ────────────────
_DB_PATH = Path(
    os.environ.get(
        "FOLIOPAGE_CACHE_DB",
        str(Path.home() / ".foliopage" / "cache.db"),
    )
)
_LOCAL = threading.local()
_INIT_LOCK = threading.Lock()


def _db() -> sqlite3.Connection:
    """Return a per-thread SQLite connection, creating the DB on first use."""
    if not hasattr(_LOCAL, "conn"):
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        with _INIT_LOCK:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cache (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at);
            """)
        conn.commit()
        _LOCAL.conn = conn
        log.info("Opened cache DB at %s", _DB_PATH)
    return _LOCAL.conn


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def cache_get(key: str) -> dict | None:
    """
    Retrieve a cached value by key.

    Returns the stored dict, or None if the key does not exist or has expired.
    Expiry is checked lazily — expired rows are deleted on first access.
    """
    now = int(time.time())
    conn = _db()
    row = conn.execute(
        "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] <= now:
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
        return None
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        log.error("cache_get: corrupt JSON for key %r", key)
        return None


@mcp.tool()
def cache_set(key: str, value: dict, ttl_s: int = 3600) -> bool:
    """
    Store a dict under key with a time-to-live in seconds.

    Overwrites any existing entry for the same key.
    Returns True on success.
    """
    expires_at = int(time.time()) + max(1, ttl_s)
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        log.error("cache_set: cannot JSON-encode value for key %r: %s", key, exc)
        return False
    conn = _db()
    conn.execute(
        """
        INSERT INTO cache (key, value, expires_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                        expires_at = excluded.expires_at
        """,
        (key, encoded, expires_at),
    )
    conn.commit()
    return True


@mcp.tool()
def cache_delete(key: str) -> bool:
    """
    Delete a key from the cache.

    Returns True if the key existed and was deleted, False if it was not found.
    """
    conn = _db()
    cursor = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
    conn.commit()
    return cursor.rowcount > 0


@mcp.tool()
def cache_list(prefix: str = "") -> list[str]:
    """
    List all non-expired cache keys, optionally filtered by prefix.

    Returns keys in alphabetical order. Expired keys are excluded.
    """
    now = int(time.time())
    conn = _db()
    if prefix:
        rows = conn.execute(
            "SELECT key FROM cache WHERE key LIKE ? AND expires_at > ? ORDER BY key",
            (prefix + "%", now),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT key FROM cache WHERE expires_at > ? ORDER BY key", (now,)
        ).fetchall()
    return [row["key"] for row in rows]


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("Starting foliopage-cache MCP server (stdio transport) …")
    mcp.run(transport="stdio")
