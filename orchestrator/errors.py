"""Custom exceptions for the Foliopage orchestrator."""
from __future__ import annotations

from pathlib import Path


class FoliopageError(Exception):
    """Base class for all Foliopage errors."""


class AgentError(FoliopageError):
    """Base class for agent runner errors. Always carries the transcript path."""

    def __init__(self, message: str, transcript_path: Path | None = None) -> None:
        super().__init__(message)
        self.transcript_path = transcript_path

    def transcript_tail(self, n: int = 40) -> str:
        if self.transcript_path and self.transcript_path.exists():
            lines = self.transcript_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-n:])
        return ""


class AgentTimeoutError(AgentError):
    """Raised when the agent subprocess exceeds its timeout."""


class AgentNonZeroExitError(AgentError):
    """Raised when the agent subprocess exits with a non-zero return code."""

    def __init__(self, message: str, exit_code: int,
                 transcript_path: Path | None = None) -> None:
        super().__init__(message, transcript_path)
        self.exit_code = exit_code


class AgentDidNotProduceOutputError(AgentError):
    """Raised when the expected HTML output file is missing after the agent exits."""


class SessionNotFoundError(FoliopageError):
    """Raised when a session_id cannot be resolved to a workspace on disk."""
