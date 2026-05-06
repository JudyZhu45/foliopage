"""FastAPI orchestrator server."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent_runner import run_agent
from .renderer import render_page
from .research_coordinator import run_parallel_agent, run_parallel_drilldown_agent
from .config import Config
from .errors import (
    AgentDidNotProduceOutputError,
    AgentNonZeroExitError,
    AgentTimeoutError,
    SessionNotFoundError,
)
from .prompts import (
    build_drilldown_prompt,
    build_initial_prompt,
    build_peer_switch_prompt,
)
from .session import Session

# Supported action groups
_INITIAL_ACTIONS = {"initial"}
_DRILLDOWN_ACTIONS = {"drilldown", "drill_down"}
_PEER_ACTIONS = {"peer_switch"}

# Map clicked_topic → skill name (for parallel drilldown routing)
_DRILL_SKILL_MAP: dict[str, str] = {
    "metric_drilldown": "metric-drilldown",
    "news_timeline": "news-timeline",
    "peer_comparison": "peer-comparison",
    "business_breakdown": "business-breakdown",
    "valuation_deep": "valuation-deep",
    "peer_comparison_deep": "peer-comparison-deep",
}
# Skills that have parallel worker support
_PARALLEL_DD_SKILLS = frozenset(_DRILL_SKILL_MAP.values()) - {"peer-comparison"}


# ── Request / response models at module level so FastAPI can resolve them ─────

class GenerateRequest(BaseModel):
    session_id: str | None = None
    action: str = "initial"
    # All action-specific fields nested here:
    #   initial:     context.stock_query
    #   drill_down:  context.stock_code, context.clicked_topic, context.clicked_context
    #   peer_switch: context.stock_code, context.stock_name
    context: dict[str, Any] = {}
    force_refresh: bool = False


class GenerateResponse(BaseModel):
    session_id: str
    request_id: str
    html: str                         # inline HTML — use for API validation / iframe srcdoc
    html_url: str                     # URL to fetch — use for iframe src
    duration_ms: int
    page_stack: list[dict[str, Any]]
    cached: bool = False              # True when served from page cache
    error: bool = False               # True when html is an error page (do NOT push to stack)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _page_cache_key(action: str, context: dict[str, Any]) -> str:
    """Stable hash of (action, context) — excludes volatile fields."""
    volatile = {"hint", "force_refresh"}
    norm = {k: v for k, v in context.items() if k not in volatile}
    payload = json.dumps({"action": action, "context": norm}, sort_keys=True,
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _check_page_cache(
    cache_key: str, page_cache_root: Path, ttl: int
) -> tuple[str, dict[str, Any]] | None:
    """Return (html, meta) if a fresh cache hit exists, else None."""
    html_path = page_cache_root / f"{cache_key}.html"
    meta_path = page_cache_root / f"{cache_key}.meta.json"
    if not (html_path.exists() and meta_path.exists()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        age = time.time() - meta.get("created_at_ts", 0)
        if age > ttl:
            return None
        return html_path.read_text(encoding="utf-8"), meta
    except Exception:
        return None


def _write_page_cache(
    cache_key: str,
    page_cache_root: Path,
    html: str,
    action: str,
    context: dict[str, Any],
    duration_ms: int,
) -> None:
    """Persist HTML + metadata to the page cache directory."""
    try:
        page_cache_root.mkdir(parents=True, exist_ok=True)
        (page_cache_root / f"{cache_key}.html").write_text(html, encoding="utf-8")
        meta = {
            "action": action,
            "context": context,
            "created_at_ts": time.time(),
            "duration_ms": duration_ms,
            "cache_key": cache_key,
        }
        (page_cache_root / f"{cache_key}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass  # Cache writes are best-effort; never raise


def _build_error_html(
    title: str,
    description: str,
    request_id: str,
    transcript_path: Path | None = None,
) -> str:
    """Return a minimal styled HTML error page the shell can render in the iframe."""
    transcript_str = str(transcript_path) if transcript_path else "N/A"
    # Single-quotes inside the onclick to avoid breaking the HTML attribute
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>报告生成失败</title>\n"
        '  <link rel="stylesheet" href="/static/foliopage.css">\n'
        "  <style>\n"
        "    .error-box{max-width:600px;margin:4rem auto;padding:2rem;"
        "border:1px solid var(--border);border-radius:8px;background:var(--surface)}\n"
        "    .error-title{color:var(--down-color,#dc2626);font-size:1.25rem;"
        "font-weight:700;margin:0 0 1rem}\n"
        "    .error-desc{color:var(--text);margin:0 0 1rem;line-height:1.6}\n"
        "    .error-meta{font-size:.78rem;color:var(--text-muted);"
        "font-family:monospace;word-break:break-all;margin:0 0 1.5rem}\n"
        "    .retry-btn{padding:.6rem 1.25rem;background:var(--accent);color:#fff;"
        "border:none;border-radius:6px;font-size:.95rem;cursor:pointer;font-weight:600}\n"
        "    .retry-btn:hover{opacity:.85}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '  <section class="section">\n'
        '    <div class="error-box">\n'
        f'      <p class="error-title">{title}</p>\n'
        f'      <p class="error-desc">{description}</p>\n'
        "      <p class=\"error-desc\">完整日志：<code class=\"error-meta\">"
        f"{transcript_str}</code>。点击重试以重新生成。</p>\n"
        f'      <p class="error-meta">请求 ID：{request_id}</p>\n'
        '      <button class="retry-btn" '
        "onclick=\"window.parent.postMessage({action:'retry'},'*')\">"
        "重试</button>\n"
        "    </div>\n"
        "  </section>\n"
        "</body>\n"
        "</html>"
    )


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config.from_env()

    _sem: list[asyncio.Semaphore | None] = [None]

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        _sem[0] = asyncio.Semaphore(cfg.max_concurrent)
        yield

    app = FastAPI(title="Foliopage Orchestrator", version="0.1.0", lifespan=lifespan)

    # ── Static files ──────────────────────────────────────────────────────────
    static_dir = Path(__file__).parent.parent / "shell" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ── Shell HTML pages ──────────────────────────────────────────────────────
    shell_dir = Path(__file__).parent.parent / "shell"

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        p = shell_dir / "index.html"
        if not p.exists():
            raise HTTPException(status_code=404, detail="index.html not found")
        return HTMLResponse(content=p.read_text(encoding="utf-8"))

    @app.get("/report", response_class=HTMLResponse)
    async def report() -> HTMLResponse:
        p = shell_dir / "report.html"
        if not p.exists():
            raise HTTPException(status_code=404, detail="report.html not found")
        return HTMLResponse(content=p.read_text(encoding="utf-8"))

    # ── POST /api/generate ────────────────────────────────────────────────────

    @app.post("/api/generate", response_model=GenerateResponse)
    async def generate(req: GenerateRequest) -> GenerateResponse:  # noqa: C901
        # Resolve or create session
        if req.session_id:
            try:
                session = Session.load(req.session_id, cfg)
            except SessionNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        else:
            session = Session.create(cfg)

        request_id = f"req_{uuid.uuid4().hex}"
        ctx = req.context
        action = req.action.lower()

        # Clear the previous request's transcript immediately so the progress
        # poller doesn't see a stale "done" event and fire rescueFromStack
        # before the new agent has a chance to start.
        _transcript_path = session.workspace / "logs" / "transcript.jsonl"
        _transcript_path.parent.mkdir(parents=True, exist_ok=True)
        _transcript_path.write_text("")

        current_stack = session.page_stack()
        parent_request_id = current_stack[-1].request_id if current_stack else ""

        # ── Validate action and build prompt ──────────────────────────────────
        if action in _INITIAL_ACTIONS:
            stock_query = ctx.get("stock_query", "")
            if not stock_query:
                raise HTTPException(
                    status_code=422,
                    detail="context.stock_query is required for initial action",
                )
            prompt = build_initial_prompt(
                request_id=request_id,
                stock_query=stock_query,
                hint=ctx.get("hint", ""),
            )
        elif action in _DRILLDOWN_ACTIONS:
            stock_code = ctx.get("stock_code", "") or ctx.get("stock_query", "")
            clicked_topic = ctx.get("clicked_topic", "") or ctx.get("metric", "")
            if not stock_code or not clicked_topic:
                raise HTTPException(
                    status_code=422,
                    detail="context.stock_code and context.clicked_topic are required for drill_down",
                )
            prompt = build_drilldown_prompt(
                request_id=request_id,
                stock_query=stock_code,
                stock_code=stock_code,
                stock_name=ctx.get("stock_name", ""),
                clicked_topic=clicked_topic,
                clicked_context=ctx.get("clicked_context", {}),
                parent_request_id=parent_request_id,
                hint=ctx.get("hint", ""),
            )
        elif action in _PEER_ACTIONS:
            peer_code = ctx.get("stock_code", "") or ctx.get("peer_code", "")
            if not peer_code:
                raise HTTPException(
                    status_code=422,
                    detail="context.stock_code is required for peer_switch",
                )
            original_query = current_stack[-1].stock_query if current_stack else ""
            prompt = build_peer_switch_prompt(
                request_id=request_id,
                peer_code=peer_code,
                peer_name=ctx.get("stock_name", ""),
                original_query=original_query,
                parent_request_id=parent_request_id,
                hint=ctx.get("hint", ""),
            )
        else:
            raise HTTPException(status_code=422, detail=f"Unknown action: {req.action!r}")

        # ── Page cache check ──────────────────────────────────────────────────
        cache_key = _page_cache_key(action, ctx)
        if not req.force_refresh:
            hit = _check_page_cache(cache_key, cfg.page_cache_root, cfg.page_cache_ttl)
            if hit is not None:
                html_content, meta = hit
                # Write HTML into this session so html_url resolves correctly
                (session.output_dir).mkdir(parents=True, exist_ok=True)
                cached_html_path = session.output_dir / f"page-{request_id}.html"
                cached_html_path.write_text(html_content, encoding="utf-8")
                html_url = f"/api/sessions/{session.session_id}/pages/{request_id}"
                return GenerateResponse(
                    session_id=session.session_id,
                    request_id=request_id,
                    html=html_content,
                    html_url=html_url,
                    duration_ms=meta.get("duration_ms", 0),
                    page_stack=[e.to_dict() for e in session.page_stack()],
                    cached=True,
                )

        # ── Spawn agent ───────────────────────────────────────────────────────
        if _sem[0] is None:
            _sem[0] = asyncio.Semaphore(cfg.max_concurrent)

        error_html: str | None = None

        # Parallel mode: initial + peer_switch use multi-agent pipeline.
        # drill_down also uses parallel pipeline for supported skills.
        _use_parallel = cfg.use_parallel_agents
        _dd_skill = _DRILL_SKILL_MAP.get(clicked_topic if action in _DRILLDOWN_ACTIONS else "")
        _use_parallel_dd = (
            _use_parallel
            and action in _DRILLDOWN_ACTIONS
            and _dd_skill in _PARALLEL_DD_SKILLS
        )

        async with _sem[0]:
            try:
                if _use_parallel and action in (_INITIAL_ACTIONS | _PEER_ACTIONS):
                    result = await run_parallel_agent(
                        prompt=prompt,
                        request_id=request_id,
                        workspace=session.workspace,
                        config=cfg,
                        action=action,
                        stock_query=(
                            ctx.get("stock_query")
                            or ctx.get("stock_code")
                            or ctx.get("peer_code", "")
                        ),
                        hint=ctx.get("hint", ""),
                        parent_request_id=parent_request_id,
                    )
                elif _use_parallel_dd:
                    result = await run_parallel_drilldown_agent(
                        prompt=prompt,
                        request_id=request_id,
                        workspace=session.workspace,
                        config=cfg,
                        action=action,
                        stock_code=stock_code,
                        stock_name=ctx.get("stock_name", ""),
                        skill=_dd_skill,
                        clicked_topic=clicked_topic,
                        clicked_context_str=json.dumps(
                            ctx.get("clicked_context", {}), ensure_ascii=False
                        ),
                        hint=ctx.get("hint", ""),
                        parent_request_id=parent_request_id,
                    )
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: run_agent(
                            prompt=prompt,
                            request_id=request_id,
                            workspace=session.workspace,
                            config=cfg,
                        ),
                    )
            except AgentTimeoutError as exc:
                error_html = _build_error_html(
                    title="生成超时",
                    description="研报生成时间超过预期。这通常是数据源响应慢导致的。",
                    request_id=request_id,
                    transcript_path=exc.transcript_path,
                )
            except AgentNonZeroExitError as exc:
                error_html = _build_error_html(
                    title="生成失败",
                    description="AI agent 执行时出错。",
                    request_id=request_id,
                    transcript_path=exc.transcript_path,
                )
            except AgentDidNotProduceOutputError as exc:
                error_html = _build_error_html(
                    title="未生成报告",
                    description="AI agent 完成执行但未生成报告文件。",
                    request_id=request_id,
                    transcript_path=exc.transcript_path,
                )

        if error_html is not None:
            # Write the error HTML into the session output directory so the
            # html_url resolves; this makes it renderable in the iframe.
            (session.output_dir).mkdir(parents=True, exist_ok=True)
            err_path = session.output_dir / f"page-{request_id}.html"
            err_path.write_text(error_html, encoding="utf-8")
            html_url = f"/api/sessions/{session.session_id}/pages/{request_id}"
            return GenerateResponse(
                session_id=session.session_id,
                request_id=request_id,
                html=error_html,
                html_url=html_url,
                duration_ms=0,
                page_stack=[e.to_dict() for e in session.page_stack()],
                error=True,
            )

        # ── Success path ──────────────────────────────────────────────────────
        if result.json_path is not None:
            # Agent produced JSON → render to HTML server-side (chart generation included)
            html_content = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: render_page(
                    json_path=result.json_path,
                    workspace=session.workspace,
                    request_id=request_id,
                ),
            )
        else:
            html_content = result.html_path.read_text(encoding="utf-8", errors="replace")
        html_url = f"/api/sessions/{session.session_id}/pages/{request_id}"
        duration_ms = int(result.duration_seconds * 1000)

        # Persist to page cache for future fast-path hits
        _write_page_cache(cache_key, cfg.page_cache_root, html_content,
                          action, ctx, duration_ms)

        return GenerateResponse(
            session_id=session.session_id,
            request_id=request_id,
            html=html_content,
            html_url=html_url,
            duration_ms=duration_ms,
            page_stack=[e.to_dict() for e in session.page_stack()],
        )

    # ── Session routes ────────────────────────────────────────────────────────

    @app.post("/api/sessions")
    async def create_session() -> dict[str, str]:
        """Pre-create an empty session so the client can poll /progress
        before /api/generate starts. The next /api/generate call passes the
        same session_id and this session is reused (no duplicate workspace)."""
        s = Session.create(cfg)
        return {"session_id": s.session_id}

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        try:
            session = Session.load(session_id, cfg)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session.to_dict()

    @app.get("/api/sessions/{session_id}/progress")
    async def get_progress(session_id: str) -> dict[str, Any]:
        """
        Live progress derived from the agent transcript. Safe to poll every
        few seconds while /api/generate is in flight — read-only, no locks.
        Returns the agent's current step, completed/pending tool calls, and
        whether a rate-limit warning has fired.
        """
        try:
            session = Session.load(session_id, cfg)
        except SessionNotFoundError:
            return {"status": "no_session"}

        transcript = session.workspace / "logs" / "transcript.jsonl"
        if not transcript.exists() or transcript.stat().st_size == 0:
            return {"status": "starting"}

        tool_id_to_name: dict[str, str] = {}
        completed: list[str] = []
        pending: dict[str, str] = {}  # tool_use_id -> name
        last_text = ""
        rate_limited = False
        has_result = False
        first_ts: str | None = None
        last_ts: str | None = None

        try:
            with transcript.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    t = ev.get("type")
                    if t == "result":
                        has_result = True
                    elif t == "rate_limit_event":
                        rate_limited = True
                    elif t == "assistant":
                        msg = ev.get("message") or {}
                        for blk in (msg.get("content") or []):
                            if not isinstance(blk, dict):
                                continue
                            if blk.get("type") == "tool_use":
                                tu_id = blk.get("id")
                                name = blk.get("name", "?")
                                if tu_id:
                                    tool_id_to_name[tu_id] = name
                                    pending[tu_id] = name
                            elif blk.get("type") == "text":
                                txt = (blk.get("text") or "").strip()
                                if txt:
                                    last_text = txt
                    elif t == "user":
                        ts = ev.get("timestamp")
                        if ts:
                            if first_ts is None:
                                first_ts = ts
                            last_ts = ts
                        msg = ev.get("message") or {}
                        for blk in (msg.get("content") or []):
                            if not isinstance(blk, dict):
                                continue
                            if blk.get("type") == "tool_result":
                                tu_id = blk.get("tool_use_id")
                                if tu_id and tu_id in pending:
                                    completed.append(pending.pop(tu_id))
        except OSError:
            return {"status": "error"}

        # Time bookkeeping
        from datetime import datetime as _dt
        elapsed_s = 0
        last_event_age_s = 0
        if first_ts:
            try:
                first = _dt.fromisoformat(first_ts.replace("Z", "+00:00"))
                last = _dt.fromisoformat((last_ts or first_ts).replace("Z", "+00:00"))
                now = _dt.now(tz=first.tzinfo)
                elapsed_s = max(0, int((now - first).total_seconds()))
                last_event_age_s = max(0, int((now - last).total_seconds()))
            except (ValueError, TypeError):
                pass

        return {
            "status": "done" if has_result else "running",
            "phase_text": last_text[:200],
            "completed_tools": completed,
            "pending_tools": list(pending.values()),
            "completed_count": len(completed),
            "rate_limited": rate_limited,
            "elapsed_s": elapsed_s,
            "last_event_age_s": last_event_age_s,
        }

    @app.get("/api/sessions/{session_id}/pages/{request_id}")
    async def get_page(session_id: str, request_id: str) -> FileResponse:
        try:
            session = Session.load(session_id, cfg)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        html_path = session.html_path(request_id)
        if html_path is None or not html_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Page {request_id!r} not found in session {session_id!r}",
            )
        return FileResponse(str(html_path), media_type="text/html")

    @app.get("/api/sessions/{session_id}/stack")
    async def get_stack(session_id: str) -> list[dict[str, Any]]:
        try:
            session = Session.load(session_id, cfg)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [e.to_dict() for e in session.page_stack()]

    # ── Recent research (for landing page chips) ──────────────────────────────

    @app.get("/api/recent")
    async def get_recent(limit: int = 8) -> list[dict[str, Any]]:
        cache_root = cfg.page_cache_root
        if not cache_root.exists():
            return []
        items: list[dict[str, Any]] = []
        for meta_path in cache_root.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("action") != "initial":
                continue
            query = (meta.get("context") or {}).get("stock_query")
            if not query:
                continue
            items.append({
                "stock_query": query,
                "created_at_ts": meta.get("created_at_ts", 0),
                "duration_ms": meta.get("duration_ms", 0),
            })
        seen: dict[str, dict[str, Any]] = {}
        for item in sorted(items, key=lambda x: x["created_at_ts"], reverse=True):
            if item["stock_query"] not in seen:
                seen[item["stock_query"]] = item
        return list(seen.values())[:limit]

    # ── Back navigation ───────────────────────────────────────────────────────

    async def _back(session_id: str) -> dict[str, Any]:
        try:
            session = Session.load(session_id, cfg)
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        prev = session.pop_page()
        if prev is None:
            raise HTTPException(status_code=404, detail="No pages in stack")
        html_path = session.html_path(prev.request_id)
        if html_path is None or not html_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"HTML for page {prev.request_id!r} not found on disk",
            )
        return {
            "session_id": session_id,
            "request_id": prev.request_id,
            "html": html_path.read_text(encoding="utf-8", errors="replace"),
            "html_url": f"/api/sessions/{session_id}/pages/{prev.request_id}",
            "page_stack": [e.to_dict() for e in session.page_stack()],
        }

    @app.post("/api/session/{session_id}/back")
    async def back_singular(session_id: str) -> dict[str, Any]:
        return await _back(session_id)

    @app.post("/api/sessions/{session_id}/back")
    async def back_plural(session_id: str) -> dict[str, Any]:
        return await _back(session_id)

    return app


# Module-level ASGI app for `uvicorn orchestrator.server:app` (used by Makefile
# `make dev` for hot-reload). Reads config from env on import. The cli entry
# point in __init__.py builds its own app from CLI args separately.
app = create_app()
