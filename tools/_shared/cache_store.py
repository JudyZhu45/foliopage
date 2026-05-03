"""
Shared on-disk SQLite cache for the foliopage MCP servers.

stock_mcp and chart_mcp use this to persist tool results across agent
restarts, so that "research the same stock again" hits the disk cache
instead of re-fetching from akshare or re-rendering matplotlib.

Schema is intentionally identical to cache_mcp's own table — the same
~/.foliopage/cache.db file backs both, so cache_mcp.cache_get() will see
entries written by stock_mcp / chart_mcp and vice versa.

Values must be JSON-serializable. TTLs are caller-specified.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("foliopage.cache_store")

_DEFAULT_DB = str(Path.home() / ".foliopage" / "cache.db")

_LOCAL = threading.local()
_INIT_LOCK = threading.Lock()


def _db_path() -> Path:
    """Resolve the cache DB path each time — env-overridable for tests."""
    return Path(os.environ.get("FOLIOPAGE_CACHE_DB", _DEFAULT_DB))


def _conn() -> sqlite3.Connection:
    """
    Per-thread SQLite connection with the cache schema initialized.
    Re-resolves the DB path on first access so tests that monkeypatch the
    FOLIOPAGE_CACHE_DB env var get an isolated DB.
    """
    if not hasattr(_LOCAL, "conn"):
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        with _INIT_LOCK:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS cache (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at);
            """)
        c.commit()
        _LOCAL.conn = c
        _LOCAL.path = str(path)
    return _LOCAL.conn


def reset_thread_local_conn() -> None:
    """Force the next call to _conn() to re-open the DB (used in tests)."""
    if hasattr(_LOCAL, "conn"):
        try: _LOCAL.conn.close()
        except Exception: pass
        del _LOCAL.conn
    if hasattr(_LOCAL, "path"):
        del _LOCAL.path


def disk_get(key: str) -> Any | None:
    """Fetch and JSON-decode a cached value, or None if missing / expired."""
    now = int(time.time())
    try:
        c = _conn()
        row = c.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now:
            c.execute("DELETE FROM cache WHERE key = ?", (key,))
            c.commit()
            return None
        return json.loads(row["value"])
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        log.warning("disk_get failed for key %r: %s", key, exc)
        return None


def disk_set(key: str, value: Any, ttl_s: int) -> None:
    """JSON-encode and persist a value with TTL. Silent on failure."""
    if ttl_s <= 0:
        return
    expires_at = int(time.time()) + ttl_s
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        log.warning("disk_set: cannot encode key %r: %s", key, exc)
        return
    try:
        c = _conn()
        c.execute(
            """
            INSERT INTO cache (key, value, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                            expires_at = excluded.expires_at
            """,
            (key, encoded, expires_at),
        )
        c.commit()
    except sqlite3.Error as exc:
        log.warning("disk_set failed for key %r: %s", key, exc)


def disk_delete_prefix(prefix: str) -> int:
    """Drop all keys starting with prefix. Returns number of rows removed."""
    try:
        c = _conn()
        cur = c.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))
        c.commit()
        return cur.rowcount
    except sqlite3.Error as exc:
        log.warning("disk_delete_prefix failed for %r: %s", prefix, exc)
        return 0


# ── TTL policy ─────────────────────────────────────────────────────────────────
#
# By default a tool calls disk_set(key, value, ttl_for(key)).
# Adjust here in one place when policy changes.

_TTL_POLICY: dict[str, int] = {
    # stock_mcp keys
    "search:":   30 * 86400,   # name -> code map; basically immutable
    "basic:":         86400,   # company basic info; daily refresh OK
    "peers:":         86400,
    "kline:":         86400,   # historical bars; today's last bar updates EOD
    "val:":       6 * 3600,    # PE/PB shifts intraday
    "fin:":           86400,   # financial statements; quarterly cadence
    "rd:":            86400,
    "holders:":       86400,
    "unlock:":        86400,
    "revbk:":         86400,   # revenue breakdown
    # news / announcements — short lived, but we still cache for a few hours
    # so a redrill within a session is free
    "news:":      6 * 3600,
    "ann:":       6 * 3600,
    "analyst:":   6 * 3600,
    # chart_mcp keys
    "chart:":         86400,   # generic chart SVG cache
}

_DEFAULT_TTL = 3600


def ttl_for(key: str) -> int:
    """Pick TTL from key prefix; default 1 hour for unmatched."""
    for prefix, ttl in _TTL_POLICY.items():
        if key.startswith(prefix):
            return ttl
    return _DEFAULT_TTL
