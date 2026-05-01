"""
Agent subprocess runner — NeuriCo pattern.

Builds the claude CLI command, spawns it with Popen, streams stdout to a
transcript file, and verifies the expected HTML output exists on disk.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .errors import (
    AgentDidNotProduceOutputError,
    AgentNonZeroExitError,
    AgentTimeoutError,
)
from .security import sanitize_text


@dataclass
class AgentResult:
    request_id: str
    html_path: Path
    transcript_path: Path
    duration_seconds: float


def run_agent(
    *,
    prompt: str,
    request_id: str,
    workspace: Path,
    config: Config,
) -> AgentResult:
    """
    Run the claude agent subprocess inside *workspace* and return an AgentResult.

    The agent is expected to:
    - Read CLAUDE.md from the workspace (symlinked by Session)
    - Write output/page-<request_id>.html
    - Update session/page_stack.json and session/data_cache.json

    The orchestrator does NOT touch those files — the agent owns them.
    """
    import time

    transcript_path = workspace / "logs" / "transcript.jsonl"
    expected_html = workspace / "output" / f"page-{request_id}.html"

    # Build CLI command (same flags as dry_run.sh)
    # ToolSearch is blocked: tool signatures are pre-listed in CLAUDE.md;
    # allowing ToolSearch adds ~200s of wasted planning overhead per page.
    cmd_str = (
        f"{config.claude_bin} -p"
        " --dangerously-skip-permissions"
        " --verbose"
        " --output-format stream-json"
        " --disallowed-tools ToolSearch"
    )
    cmd = shlex.split(cmd_str)

    # Environment: inherit parent env + PYTHONUNBUFFERED for real-time output
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    start = time.monotonic()

    with transcript_path.open("wb") as transcript_fh:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=transcript_fh,
            stderr=subprocess.STDOUT,
            cwd=str(workspace),
            env=env,
        )

        try:
            proc.communicate(
                input=prompt.encode("utf-8"),
                timeout=config.agent_timeout,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            duration = time.monotonic() - start
            raise AgentTimeoutError(
                f"Agent timed out after {duration:.0f}s "
                f"(limit={config.agent_timeout}s) for request {request_id}",
                transcript_path=transcript_path,
            )

    duration = time.monotonic() - start

    # Verify exit code
    if proc.returncode != 0:
        raise AgentNonZeroExitError(
            sanitize_text(
                f"Agent exited with code {proc.returncode} "
                f"after {duration:.0f}s for request {request_id}"
            ),
            exit_code=proc.returncode,
            transcript_path=transcript_path,
        )

    # Verify output file was produced
    if not expected_html.exists():
        raise AgentDidNotProduceOutputError(
            f"Agent finished successfully but {expected_html.name} was not written "
            f"(request {request_id})",
            transcript_path=transcript_path,
        )

    return AgentResult(
        request_id=request_id,
        html_path=expected_html,
        transcript_path=transcript_path,
        duration_seconds=duration,
    )
