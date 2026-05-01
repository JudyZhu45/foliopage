"""Session workspace lifecycle management."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .errors import SessionNotFoundError


@dataclass
class PageEntry:
    """One entry in session/page_stack.json — written by the agent."""
    request_id: str
    action: str          # initial | drill_down | peer_switch
    stock_query: str
    html_file: str       # relative path inside workspace, e.g. output/page-<id>.html
    timestamp: str       # ISO-8601 written by agent
    title: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PageEntry:
        known = {f for f in cls.__dataclass_fields__}
        extra = {k: v for k, v in d.items() if k not in known}
        return cls(
            request_id=d.get("request_id", ""),
            action=d.get("action", ""),
            stock_query=d.get("stock_query", ""),
            html_file=d.get("html_file", ""),
            timestamp=d.get("timestamp", ""),
            title=d.get("title", ""),
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra", {})
        d.update(extra)
        return d


class Session:
    """
    Manages the on-disk workspace for one browser session.

    Directory layout (mirrors dry_run.sh):
        <workspace_root>/<session_id>/
            session/
                page_stack.json   ← written by agent
                data_cache.json   ← written by agent
            output/               ← HTML files written by agent
            logs/                 ← transcript.jsonl written by agent_runner
            CLAUDE.md             ← symlink → repo CLAUDE.md
            .claude/              ← symlink → repo .claude/
            .mcp.json             ← symlink → repo .mcp.json  (MCP tool discovery)
            static/               ← symlink → repo shell/static/
            examples/             ← symlink → repo examples/ (if exists)
    """

    def __init__(self, session_id: str, workspace: Path, config: Config) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.config = config

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def session_dir(self) -> Path:
        return self.workspace / "session"

    @property
    def output_dir(self) -> Path:
        return self.workspace / "output"

    @property
    def logs_dir(self) -> Path:
        return self.workspace / "logs"

    @property
    def page_stack_path(self) -> Path:
        return self.session_dir / "page_stack.json"

    @property
    def data_cache_path(self) -> Path:
        return self.session_dir / "data_cache.json"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, config: Config, session_id: str | None = None) -> Session:
        """Create a new session workspace on disk and return the Session object."""
        sid = session_id or ("sess_" + uuid.uuid4().hex)
        workspace = config.workspace_root / sid
        session = cls(sid, workspace, config)
        session._setup_workspace()
        return session

    @classmethod
    def load(cls, session_id: str, config: Config) -> Session:
        """Load an existing session; raises SessionNotFoundError if missing."""
        workspace = config.workspace_root / session_id
        if not workspace.exists():
            raise SessionNotFoundError(
                f"Session {session_id!r} not found at {workspace}"
            )
        return cls(session_id, workspace, config)

    def _setup_workspace(self) -> None:
        """Create directory tree and symlinks, matching dry_run.sh exactly."""
        repo = self.config.repo_root

        # Create directories
        for d in (self.session_dir, self.output_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Initialize empty session state (agent will populate these)
        if not self.page_stack_path.exists():
            self.page_stack_path.write_text("[]", encoding="utf-8")
        if not self.data_cache_path.exists():
            self.data_cache_path.write_text("{}", encoding="utf-8")

        # Symlinks — order matches dry_run.sh
        self._symlink(repo / "CLAUDE.md", self.workspace / "CLAUDE.md")
        self._symlink(repo / ".claude", self.workspace / ".claude")
        self._symlink(repo / "shell" / "static", self.workspace / "static")

        # .mcp.json — critical for MCP tool discovery when claude runs from workspace dir
        mcp_json = repo / ".mcp.json"
        if mcp_json.exists():
            self._symlink(mcp_json, self.workspace / ".mcp.json")

        examples = repo / "examples"
        if examples.exists():
            self._symlink(examples, self.workspace / "examples")

    @staticmethod
    def _symlink(src: Path, dst: Path) -> None:
        if not dst.exists() and not dst.is_symlink():
            dst.symlink_to(src)

    # ------------------------------------------------------------------
    # Page stack helpers (read-only — agent writes, orchestrator reads)
    # ------------------------------------------------------------------

    def page_stack(self) -> list[PageEntry]:
        """Read current page_stack.json; returns [] if empty or malformed."""
        try:
            data = json.loads(self.page_stack_path.read_text(encoding="utf-8"))
            return [PageEntry.from_dict(e) for e in data]
        except Exception:
            return []

    def latest_page(self) -> PageEntry | None:
        stack = self.page_stack()
        return stack[-1] if stack else None

    def pop_page(self) -> PageEntry | None:
        """
        Remove the last entry from page_stack.json and return the new last entry.
        Used by back-navigation. Returns None if the stack is now empty.
        """
        stack = self.page_stack()
        if len(stack) <= 1:
            # Nothing to pop — keep the single entry
            return stack[0] if stack else None
        stack = stack[:-1]
        data = [e.to_dict() for e in stack]
        self.page_stack_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return stack[-1]

    def html_path(self, request_id: str) -> Path | None:
        """Return absolute path to the HTML output for *request_id*, or None."""
        for entry in self.page_stack():
            if entry.request_id == request_id and entry.html_file:
                p = self.workspace / entry.html_file
                if p.exists() and p.is_file():
                    return p
                break  # found the entry but file missing — fall through to fallback
        # Fallback: look for the file directly by convention
        candidate = self.output_dir / f"page-{request_id}.html"
        return candidate if candidate.exists() else None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace": str(self.workspace),
            "page_count": len(self.page_stack()),
        }
