"""Runtime configuration loaded from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root (if present) before reading os.environ
load_dotenv(Path(__file__).parent.parent / ".env", override=False)


@dataclass
class Config:
    # Where session workspaces live
    workspace_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FOLIOPAGE_WORKSPACE_ROOT",
                           str(Path.home() / ".foliopage" / "sessions"))
        )
    )
    # Agent subprocess timeout (seconds) — research-grade depth pages take 20-30 min
    agent_timeout: int = field(
        default_factory=lambda: int(os.environ.get("FOLIOPAGE_AGENT_TIMEOUT", "1800"))
    )
    # Path to the claude binary
    claude_bin: str = field(
        default_factory=lambda: os.environ.get("FOLIOPAGE_CLAUDE_BIN", "claude")
    )
    # Repo root (needed to set up workspace symlinks)
    repo_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FOLIOPAGE_REPO_ROOT",
                           str(Path(__file__).parent.parent))
        )
    )
    # FastAPI server host / port
    host: str = field(
        default_factory=lambda: os.environ.get("FOLIOPAGE_HOST", "127.0.0.1")
    )
    port: int = field(
        default_factory=lambda: int(os.environ.get("FOLIOPAGE_PORT", "8081"))
    )
    # Max concurrent agent subprocesses
    max_concurrent: int = field(
        default_factory=lambda: int(os.environ.get("FOLIOPAGE_MAX_CONCURRENT", "3"))
    )
    # Page-level HTML cache (short-circuits identical requests within TTL)
    page_cache_root: Path = field(
        default_factory=lambda: Path(
            os.environ.get("FOLIOPAGE_PAGE_CACHE_ROOT",
                           str(Path.home() / ".foliopage" / "page_cache"))
        )
    )
    page_cache_ttl: int = field(
        default_factory=lambda: int(os.environ.get("FOLIOPAGE_PAGE_CACHE_TTL", "1800"))
    )
    # Logging level
    log_level: str = field(
        default_factory=lambda: os.environ.get("FOLIOPAGE_LOG_LEVEL", "INFO")
    )
    # Multi-agent parallel mode (feature flag — off by default)
    use_parallel_agents: bool = field(
        default_factory=lambda: os.environ.get(
            "FOLIOPAGE_USE_PARALLEL_AGENTS", "false"
        ).lower() == "true"
    )
    # Per-worker subprocess timeouts (seconds)
    worker_timeouts: dict = field(
        default_factory=lambda: {"A": 120, "B": 120, "C": 90, "D": 150}
    )
    # Analyst agent timeout (seconds) — analysis only, no data fetch
    analyst_timeout: int = field(
        default_factory=lambda: int(
            os.environ.get("FOLIOPAGE_ANALYST_TIMEOUT", "360")
        )
    )

    @classmethod
    def from_env(cls) -> Config:
        """Create a Config from current environment (including any loaded .env)."""
        return cls()
