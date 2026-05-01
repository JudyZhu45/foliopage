"""Foliopage orchestrator package."""
from __future__ import annotations

import sys
from pathlib import Path


def cli() -> None:
    """Entry point: `foliopage [--host H] [--port P] [--check]`"""
    import argparse

    import uvicorn

    from .config import Config
    from .server import create_app

    parser = argparse.ArgumentParser(
        prog="foliopage",
        description="Foliopage orchestrator — local-first stock research server",
    )
    parser.add_argument("--host", default=None, help="Bind host (default: from config)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: from config)")
    parser.add_argument("--check", action="store_true", help="Preflight check then exit")
    args = parser.parse_args()

    cfg = Config.from_env()
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port

    if args.check:
        _preflight_check(cfg)
        return

    _preflight_check(cfg, fatal=False)
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


def _preflight_check(cfg: Config, *, fatal: bool = True) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Verify dependencies and configuration before starting."""
    import shutil

    issues: list[str] = []

    # claude binary
    if not shutil.which(cfg.claude_bin):
        issues.append(f"claude binary not found: {cfg.claude_bin!r}")

    # repo assets
    repo = cfg.repo_root
    for rel in ("CLAUDE.md", ".claude", "shell/static"):
        if not (repo / rel).exists():
            issues.append(f"Missing repo asset: {repo / rel}")

    # MCP config (warn only)
    mcp_ok = (repo / ".mcp.json").exists() or (Path.home() / ".claude" / "mcp.json").exists()
    if not mcp_ok:
        print("WARNING: No .mcp.json found — MCP tools may be unavailable to the agent",
              file=sys.stderr)

    if issues:
        for msg in issues:
            print(f"ERROR: {msg}", file=sys.stderr)
        if fatal:
            sys.exit(1)
    else:
        print("Preflight OK", file=sys.stderr)
