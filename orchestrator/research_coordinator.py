"""
Multi-agent parallel research coordinator for Foliopage.

Architecture:
  Manager (Python) orchestrates 4 parallel Worker agents + 1 Analyst agent.
  Workers fetch MCP data concurrently; Analyst receives pre-fetched data and
  focuses entirely on analysis and JSON assembly.

Expected latency: ~3 min vs ~10 min single-agent serial.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_runner import AgentResult, run_agent
from .config import Config
from .errors import (
    AgentDidNotProduceOutputError,
    AgentNonZeroExitError,
    AgentTimeoutError,
)
from .security import sanitize_text
from .worker_prompts import (
    build_analyst_prompt,
    build_worker_a_prompt,
    build_worker_b_prompt,
    build_worker_c_prompt,
    build_worker_d_prompt,
    build_drilldown_analyst_prompt,
    build_dd_peercomp_subject_worker,
    build_dd_peercomp_peers_worker,
    build_dd_peercomp_peer_worker,
    _DD_WORKER_CONFIGS,
)

log = logging.getLogger(__name__)

_WORKER_IDS = ("A", "B", "C", "D")

_WORKER_PROMPT_BUILDERS = {
    "A": build_worker_a_prompt,
    "B": build_worker_b_prompt,
    "C": build_worker_c_prompt,
    "D": build_worker_d_prompt,
}

# Fall back to single-agent mode if this many workers fail
_FALLBACK_THRESHOLD = 3


# ── Stock code resolver ───────────────────────────────────────────────────────

def _resolve_stock_code(stock_query: str) -> tuple[str, str]:
    """
    Return (code, name) for a stock query.

    For 6-digit A-share codes and short tickers, return immediately.
    For ambiguous queries, call search_stock() directly via Python import
    (hits the same disk cache as the MCP tool, returns in <100ms if warm).
    """
    # 6-digit A-share code
    if re.match(r"^\d{6}$", stock_query):
        return stock_query, ""

    # Short uppercase ticker (AAPL, TSLA, NVDA, …)
    if re.match(r"^[A-Z]{1,6}$", stock_query):
        return stock_query, ""

    # Resolve via search_stock Python function (avoids spawning a subprocess)
    try:
        repo_root = str(Path(__file__).parent.parent)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from tools.stock_mcp.server import search_stock  # type: ignore[import]

        results = search_stock(query=stock_query)
        if not results:
            # Transient network error is common — retry once after a short delay
            log.warning("search_stock returned empty for %r, retrying in 2s", stock_query)
            time.sleep(2)
            results = search_stock(query=stock_query)

        if results:
            first = results[0]
            return first.get("code", stock_query), first.get("name", "")
    except Exception as exc:
        log.warning("search_stock failed for %r: %s", stock_query, exc)

    # Could not resolve — signal failure so caller can fallback to single agent
    log.warning(
        "Could not resolve stock query %r to a code; parallel mode will skip.", stock_query
    )
    return "", stock_query


# ── Worker workspace setup ────────────────────────────────────────────────────

def _setup_worker_workspace(
    worker_id: str, session_workspace: Path, config: Config
) -> Path:
    """
    Create a minimal workspace for one worker subprocess.

    Layout: session_workspace/workers/{id}/
      CLAUDE.md  → repo/CLAUDE.worker.md   (lightweight system prompt)
      .mcp.json  → repo/.mcp.json          (MCP tool discovery)
      .claude/   → repo/.claude/           (MCP server registration)
      output/                              (worker writes JSON here)
      logs/                                (transcript)
    """
    worker_ws = session_workspace / "workers" / worker_id
    (worker_ws / "output").mkdir(parents=True, exist_ok=True)
    (worker_ws / "logs").mkdir(parents=True, exist_ok=True)

    repo = config.repo_root

    def _symlink(src: Path, dst: Path) -> None:
        if not dst.exists() and not dst.is_symlink():
            dst.symlink_to(src)

    worker_claude = repo / "CLAUDE.worker.md"
    if worker_claude.exists():
        _symlink(worker_claude, worker_ws / "CLAUDE.md")

    mcp_json = repo / ".mcp.json"
    if mcp_json.exists():
        _symlink(mcp_json, worker_ws / ".mcp.json")

    claude_dir = repo / ".claude"
    if claude_dir.exists():
        _symlink(claude_dir, worker_ws / ".claude")

    return worker_ws


# ── Worker subprocess runner (async) ─────────────────────────────────────────

async def _run_worker(
    worker_id: str,
    prompt: str,
    worker_workspace: Path,
    config: Config,
    timeout: float,
    request_id: str,
) -> dict[str, Any]:
    """
    Spawn one claude -p worker subprocess and return its parsed JSON output.

    Never raises — on any failure returns {"error": str, "worker_id": worker_id}
    so asyncio.gather can collect partial results.
    """
    transcript_path = (
        worker_workspace / "logs" / f"transcript_{request_id}.jsonl"
    )
    output_file = (
        worker_workspace / "output" / f"worker_{worker_id}_{request_id}.json"
    )
    output_file_rel = f"output/worker_{worker_id}_{request_id}.json"

    # Embed the output file path into the prompt so the worker knows where to write
    full_prompt = prompt.replace(
        f"output/worker_{worker_id}_{request_id}.json", output_file_rel
    )

    cmd = shlex.split(
        f"{config.claude_bin} -p"
        " --dangerously-skip-permissions"
        " --verbose"
        " --output-format stream-json"
        " --disallowed-tools ToolSearch"
    )
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    log.info("Worker %s starting (timeout=%ss, code=%s)", worker_id, int(timeout),
             full_prompt.split("STOCK_CODE:")[-1].split("\n")[0].strip() if "STOCK_CODE:" in full_prompt else "?")

    start = time.monotonic()

    try:
        # Stdout → PIPE (captured) to avoid large-output buffer issues we open file separately
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(worker_workspace),
            env=env,
        )

        try:
            stdout_data, _ = await asyncio.wait_for(
                proc.communicate(input=full_prompt.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.communicate()
            except Exception:
                pass
            elapsed = time.monotonic() - start
            log.warning("Worker %s timed out after %.0fs", worker_id, elapsed)
            transcript_path.write_bytes(b"")
            return {"error": f"timeout after {elapsed:.0f}s", "worker_id": worker_id}

    except Exception as exc:
        log.warning("Worker %s failed to spawn: %s", worker_id, exc)
        return {"error": str(exc), "worker_id": worker_id}

    elapsed = time.monotonic() - start
    transcript_path.write_bytes(stdout_data)

    if proc.returncode != 0:
        log.warning("Worker %s exited with code %d after %.0fs",
                    worker_id, proc.returncode, elapsed)
        return {
            "error": f"exit code {proc.returncode}",
            "worker_id": worker_id,
        }

    if not output_file.exists():
        log.warning("Worker %s: output file not created after %.0fs", worker_id, elapsed)
        return {"error": "output file not created", "worker_id": worker_id}

    try:
        result = json.loads(output_file.read_text(encoding="utf-8"))
        log.info("Worker %s done in %.0fs", worker_id, elapsed)
        return result
    except json.JSONDecodeError as exc:
        log.warning("Worker %s: invalid JSON output: %s", worker_id, exc)
        return {"error": f"invalid JSON: {exc}", "worker_id": worker_id}


# ── Result merger ─────────────────────────────────────────────────────────────

def _merge_worker_results(
    results: list[dict[str, Any]],
    stock_code: str,
    stock_name: str,
) -> dict[str, Any]:
    """Combine 4 worker dicts into a single raw_data dict for the analyst."""
    raw: dict[str, Any] = {
        "meta": {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "workers_completed": [],
            "workers_failed": [],
        },
        "basic_info": None,
        "valuation": None,
        "financials_annual": None,
        "financials_quarterly": None,
        "peers": None,
        "peers_detail": [],
        "recent_news": None,
        "recent_announcements": None,
    }

    completed: list[str] = []
    failed: list[str] = []

    for result in results:
        if "error" in result:
            failed.append(str(result.get("worker_id", "?")))
            continue
        wid = result.get("worker_id", "")
        if wid == "A":
            raw["basic_info"] = result.get("basic_info")
            raw["valuation"] = result.get("valuation")
            completed.append("A")
        elif wid == "B":
            raw["financials_annual"] = result.get("financials_annual")
            raw["financials_quarterly"] = result.get("financials_quarterly")
            completed.append("B")
        elif wid == "C":
            raw["recent_news"] = result.get("recent_news")
            raw["recent_announcements"] = result.get("recent_announcements")
            completed.append("C")
        elif wid == "D":
            raw["peers"] = result.get("peers")
            raw["peers_detail"] = result.get("peers_detail", [])
            completed.append("D")
        else:
            log.warning("Unknown worker_id in result: %r", wid)

    raw["meta"]["workers_completed"] = completed
    raw["meta"]["workers_failed"] = failed

    if failed:
        log.warning("Workers failed: %s", ", ".join(failed))

    return raw


# ── Analyst subprocess runner (sync, wrapped in executor by caller) ───────────

def _run_analyst_sync(
    prompt: str,
    request_id: str,
    workspace: Path,
    config: Config,
) -> AgentResult:
    """
    Run the analyst claude -p subprocess synchronously.

    Mirrors agent_runner.run_agent() but uses config.analyst_timeout.
    The analyst has DATA_FILE pre-fetched; it should only do analysis + write JSON.
    """
    transcript_path = workspace / "logs" / f"transcript_analyst_{request_id}.jsonl"
    expected_json = workspace / "output" / f"data-{request_id}.json"
    expected_html = workspace / "output" / f"page-{request_id}.html"

    cmd_str = (
        f"{config.claude_bin} -p"
        " --dangerously-skip-permissions"
        " --verbose"
        " --output-format stream-json"
        " --disallowed-tools ToolSearch"
    )
    cmd = shlex.split(cmd_str)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    analyst_timeout = getattr(config, "analyst_timeout", 360)
    start = time.monotonic()

    with transcript_path.open("wb") as tf:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=tf,
            stderr=subprocess.STDOUT,
            cwd=str(workspace),
            env=env,
        )
        try:
            proc.communicate(input=prompt.encode("utf-8"), timeout=analyst_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            duration = time.monotonic() - start
            raise AgentTimeoutError(
                f"Analyst timed out after {duration:.0f}s "
                f"(limit={analyst_timeout}s) for request {request_id}",
                transcript_path=transcript_path,
            )

    duration = time.monotonic() - start

    if proc.returncode != 0:
        raise AgentNonZeroExitError(
            sanitize_text(
                f"Analyst exited with code {proc.returncode} "
                f"after {duration:.0f}s for request {request_id}"
            ),
            exit_code=proc.returncode,
            transcript_path=transcript_path,
        )

    if expected_json.exists():
        return AgentResult(
            request_id=request_id,
            html_path=expected_html,
            transcript_path=transcript_path,
            duration_seconds=duration,
            json_path=expected_json,
        )

    if expected_html.exists():
        return AgentResult(
            request_id=request_id,
            html_path=expected_html,
            transcript_path=transcript_path,
            duration_seconds=duration,
        )

    raise AgentDidNotProduceOutputError(
        f"Analyst finished but neither {expected_json.name} nor "
        f"{expected_html.name} was written (request {request_id})",
        transcript_path=transcript_path,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_parallel_agent(
    *,
    prompt: str,
    request_id: str,
    workspace: Path,
    config: Config,
    action: str = "initial",
    stock_query: str = "",
    hint: str = "",
    parent_request_id: str = "",
) -> AgentResult:
    """
    Manager: resolve stock → parallel workers → merge → analyst.

    Drop-in async replacement for run_agent() when use_parallel_agents=True.
    Falls back to run_agent() if too many workers fail.
    """
    overall_start = time.monotonic()

    # ── Phase 1: Resolve stock code ───────────────────────────────────────────
    stock_code, stock_name = _resolve_stock_code(stock_query)

    # Empty code means resolution failed — fall back to single agent which has
    # search_stock as an MCP tool and can resolve it independently.
    if not stock_code:
        log.warning(
            "Stock resolution failed for %r; falling back to single agent", stock_query
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: run_agent(
                prompt=prompt,
                request_id=request_id,
                workspace=workspace,
                config=config,
            ),
        )

    log.info(
        "Parallel agent starting: code=%s name=%r request=%s",
        stock_code, stock_name, request_id,
    )

    # ── Phase 2: Setup worker workspaces and build prompts ────────────────────
    timeouts = config.worker_timeouts
    worker_tasks = []
    for wid in _WORKER_IDS:
        worker_ws = _setup_worker_workspace(wid, workspace, config)
        output_file_rel = f"output/worker_{wid}_{request_id}.json"
        worker_prompt = _WORKER_PROMPT_BUILDERS[wid](
            stock_code=stock_code,
            request_id=request_id,
            output_file=output_file_rel,
        )
        worker_timeout = timeouts.get(wid, 120)
        worker_tasks.append(
            _run_worker(wid, worker_prompt, worker_ws, config, worker_timeout, request_id)
        )

    # ── Phase 3: Run all workers in parallel ──────────────────────────────────
    log.info("Launching 4 workers in parallel for %s", stock_code)
    worker_results: tuple[dict, ...] = await asyncio.gather(*worker_tasks)

    # ── Phase 4: Fallback if too many workers failed ──────────────────────────
    failed_count = sum(1 for r in worker_results if "error" in r)
    if failed_count >= _FALLBACK_THRESHOLD:
        log.warning(
            "%d/4 workers failed for %s; falling back to single agent",
            failed_count, stock_code,
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: run_agent(
                prompt=prompt,
                request_id=request_id,
                workspace=workspace,
                config=config,
            ),
        )

    # ── Phase 5: Merge worker results → raw_data.json ────────────────────────
    raw_data = _merge_worker_results(list(worker_results), stock_code, stock_name)
    raw_data_path = workspace / "session" / f"raw_data_{request_id}.json"
    raw_data_path.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    workers_elapsed = time.monotonic() - overall_start
    log.info(
        "Workers done in %.0fs (%d/%d succeeded). Starting analyst.",
        workers_elapsed, 4 - failed_count, 4,
    )

    # ── Phase 6: Run analyst ──────────────────────────────────────────────────
    # stock_name may be empty if code was already resolved; analyst will get it
    # from raw_data["basic_info"]["name"] or leave it to CLAUDE.md to fill.
    if not stock_name and raw_data.get("basic_info"):
        stock_name = raw_data["basic_info"].get("name", "")

    analyst_prompt = build_analyst_prompt(
        stock_code=stock_code,
        stock_name=stock_name,
        request_id=request_id,
        action=action,
        raw_data_path=f"session/raw_data_{request_id}.json",
        hint=hint,
        parent_request_id=parent_request_id,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _run_analyst_sync(analyst_prompt, request_id, workspace, config),
    )

    total_elapsed = time.monotonic() - overall_start
    log.info(
        "Parallel agent complete for %s in %.0fs total", stock_code, total_elapsed
    )
    return result


# ── Drill-down parallel support ───────────────────────────────────────────────

def _merge_dd_worker_results(
    results: list[dict[str, Any]],
    stock_code: str,
    stock_name: str,
    skill: str,
) -> dict[str, Any]:
    """
    Generic merger for drill-down workers.
    Reads all in-memory worker result dicts, strips metadata keys,
    and merges the remaining fields into one raw_data dict.
    """
    raw: dict[str, Any] = {
        "meta": {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "skill": skill,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "workers_completed": [],
            "workers_failed": [],
        }
    }
    completed: list[str] = []
    failed: list[str] = []

    for result in results:
        if "error" in result:
            failed.append(str(result.get("worker_id", "?")))
            continue
        wid = result.get("worker_id", "?")
        completed.append(wid)
        for k, v in result.items():
            if k not in ("worker_id", "stock_code", "peer_code"):
                raw[k] = v

    raw["meta"]["workers_completed"] = completed
    raw["meta"]["workers_failed"] = failed
    if failed:
        log.warning("DD workers failed: %s", ", ".join(failed))
    return raw


async def _run_peer_comparison_deep(
    *,
    stock_code: str,
    stock_name: str,
    request_id: str,
    workspace: Path,
    config: Config,
    action: str,
    clicked_topic: str,
    clicked_context_str: str,
    hint: str = "",
    parent_request_id: str = "",
) -> AgentResult:
    """
    2-batch special handling for peer-comparison-deep.

    Batch1 (parallel): subject worker + peers_list worker
    Batch2 (parallel): one worker per peer (up to 5), depends on Batch1 peer codes
    """
    overall_start = time.monotonic()

    # ── Batch 1 ───────────────────────────────────────────────────────────────
    subj_ws = _setup_worker_workspace("peercomp_subj", workspace, config)
    peers_ws = _setup_worker_workspace("peercomp_peers", workspace, config)

    subj_output_rel = f"output/worker_peercomp_subj_{request_id}.json"
    peers_output_rel = f"output/worker_peercomp_peers_{request_id}.json"

    subj_prompt = build_dd_peercomp_subject_worker(stock_code, request_id, subj_output_rel)
    peers_prompt = build_dd_peercomp_peers_worker(stock_code, request_id, peers_output_rel)

    log.info("Peer-comparison-deep Batch1: subject + peers for %s", stock_code)
    batch1 = await asyncio.gather(
        _run_worker("peercomp_subj", subj_prompt, subj_ws, config,
                    config.worker_timeouts.get("A", 120), request_id),
        _run_worker("peercomp_peers", peers_prompt, peers_ws, config, 60, request_id),
    )
    subj_result, peers_result = batch1

    # ── Extract peer codes for Batch 2 ───────────────────────────────────────
    peer_codes: list[str] = []
    if "error" not in peers_result:
        peers_data = peers_result.get("peers_list", {})
        if isinstance(peers_data, dict):
            for p in (peers_data.get("peers") or [])[:5]:
                code = p.get("code", "")
                if code:
                    peer_codes.append(code)

    batch1_elapsed = time.monotonic() - overall_start
    log.info(
        "Peer-comparison-deep Batch1 done in %.0fs, found %d peers: %s",
        batch1_elapsed, len(peer_codes), peer_codes,
    )

    # ── Batch 2 ───────────────────────────────────────────────────────────────
    peer_results: list[dict] = []
    if peer_codes:
        peer_tasks = []
        for i, peer_code in enumerate(peer_codes):
            peer_ws = _setup_worker_workspace(f"peer_{i}", workspace, config)
            peer_output_rel = f"output/worker_peer_{i}_{request_id}.json"
            peer_prompt = build_dd_peercomp_peer_worker(peer_code, request_id, peer_output_rel)
            peer_tasks.append(
                _run_worker(f"peer_{i}", peer_prompt, peer_ws, config, 90, request_id)
            )
        log.info("Peer-comparison-deep Batch2: launching %d peer workers", len(peer_tasks))
        peer_results = list(await asyncio.gather(*peer_tasks))

    # ── Merge ─────────────────────────────────────────────────────────────────
    raw_data = _merge_dd_worker_results(
        [subj_result, peers_result], stock_code, stock_name, "peer-comparison-deep"
    )
    peers_detail = []
    for r in peer_results:
        if "error" not in r:
            peers_detail.append({
                "code": r.get("peer_code", ""),
                "basic_info": r.get("basic_info"),
                "valuation": r.get("valuation"),
                "financials_annual": r.get("financials_annual"),
            })
    raw_data["peers_detail"] = peers_detail

    raw_data_path = workspace / "session" / f"raw_data_{request_id}.json"
    raw_data_path.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fetch_elapsed = time.monotonic() - overall_start
    log.info(
        "Peer-comparison-deep fetch done in %.0fs for %s (%d peers OK). Starting analyst.",
        fetch_elapsed, stock_code, len(peers_detail),
    )

    analyst_prompt = build_drilldown_analyst_prompt(
        stock_code=stock_code,
        stock_name=stock_name,
        request_id=request_id,
        action=action,
        raw_data_path=f"session/raw_data_{request_id}.json",
        skill="peer-comparison-deep",
        clicked_topic=clicked_topic,
        clicked_context_str=clicked_context_str,
        hint=hint,
        parent_request_id=parent_request_id,
    )

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_analyst_sync(analyst_prompt, request_id, workspace, config),
    )


async def run_parallel_drilldown_agent(
    *,
    prompt: str,
    request_id: str,
    workspace: Path,
    config: Config,
    action: str,
    stock_code: str,
    stock_name: str,
    skill: str,
    clicked_topic: str,
    clicked_context_str: str,
    hint: str = "",
    parent_request_id: str = "",
) -> AgentResult:
    """
    Drill-down parallel manager.

    - peer-comparison-deep → _run_peer_comparison_deep (2-batch)
    - other skills → _DD_WORKER_CONFIGS lookup → asyncio.gather workers
    - fallback to run_agent() if ≥ ceil(N/2) workers fail
    - fallback to run_agent() for unknown skills (not in _DD_WORKER_CONFIGS)
    """
    import math

    overall_start = time.monotonic()

    if skill == "peer-comparison-deep":
        return await _run_peer_comparison_deep(
            stock_code=stock_code,
            stock_name=stock_name,
            request_id=request_id,
            workspace=workspace,
            config=config,
            action=action,
            clicked_topic=clicked_topic,
            clicked_context_str=clicked_context_str,
            hint=hint,
            parent_request_id=parent_request_id,
        )

    worker_configs = _DD_WORKER_CONFIGS.get(skill)
    if not worker_configs:
        log.warning("No worker config for skill %r; falling back to single agent", skill)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: run_agent(
                prompt=prompt,
                request_id=request_id,
                workspace=workspace,
                config=config,
            ),
        )

    # ── Build and launch workers ──────────────────────────────────────────────
    worker_tasks = []
    for wcfg in worker_configs:
        wid = wcfg["id"]
        worker_ws = _setup_worker_workspace(wid, workspace, config)
        output_file_rel = f"output/worker_{wid}_{request_id}.json"
        worker_prompt = wcfg["builder"](
            stock_code=stock_code,
            request_id=request_id,
            output_file=output_file_rel,
        )
        worker_tasks.append(
            _run_worker(wid, worker_prompt, worker_ws, config,
                        wcfg.get("timeout", 90), request_id)
        )

    log.info(
        "Launching %d DD workers for %s skill=%s", len(worker_tasks), stock_code, skill
    )
    worker_results: tuple[dict, ...] = await asyncio.gather(*worker_tasks)

    # ── Fallback check ────────────────────────────────────────────────────────
    n_workers = len(worker_configs)
    failed_count = sum(1 for r in worker_results if "error" in r)
    fallback_threshold = math.ceil(n_workers / 2)

    if failed_count >= fallback_threshold:
        log.warning(
            "%d/%d DD workers failed for %s skill=%s; falling back to single agent",
            failed_count, n_workers, stock_code, skill,
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: run_agent(
                prompt=prompt,
                request_id=request_id,
                workspace=workspace,
                config=config,
            ),
        )

    # ── Merge and write raw_data ──────────────────────────────────────────────
    raw_data = _merge_dd_worker_results(
        list(worker_results), stock_code, stock_name, skill
    )
    raw_data_path = workspace / "session" / f"raw_data_{request_id}.json"
    raw_data_path.write_text(
        json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    workers_elapsed = time.monotonic() - overall_start
    log.info(
        "DD workers done in %.0fs (%d/%d OK) skill=%s. Starting analyst.",
        workers_elapsed, n_workers - failed_count, n_workers, skill,
    )

    # ── Run analyst ───────────────────────────────────────────────────────────
    analyst_prompt = build_drilldown_analyst_prompt(
        stock_code=stock_code,
        stock_name=stock_name,
        request_id=request_id,
        action=action,
        raw_data_path=f"session/raw_data_{request_id}.json",
        skill=skill,
        clicked_topic=clicked_topic,
        clicked_context_str=clicked_context_str,
        hint=hint,
        parent_request_id=parent_request_id,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _run_analyst_sync(analyst_prompt, request_id, workspace, config),
    )

    total_elapsed = time.monotonic() - overall_start
    log.info(
        "Parallel drilldown complete for %s skill=%s in %.0fs",
        stock_code, skill, total_elapsed,
    )
    return result
