"""
Unit tests for orchestrator modules.

Fast tests: security, config, session lifecycle, prompts (no subprocess).
Slow E2E test: marked with pytest.mark.integration (skipped by default).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.config import Config
from orchestrator.errors import (
    AgentDidNotProduceOutputError,
    AgentNonZeroExitError,
    AgentTimeoutError,
    SessionNotFoundError,
)
from orchestrator.prompts import (
    build_drilldown_prompt,
    build_initial_prompt,
    build_peer_switch_prompt,
)
from orchestrator.security import sanitize_text
from orchestrator.session import PageEntry, Session

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.workspace_root = tmp_path / "sessions"
    cfg.workspace_root.mkdir()
    cfg.repo_root = Path(__file__).parent.parent  # actual repo root
    return cfg


@pytest.fixture()
def session(tmp_config: Config) -> Session:
    return Session.create(tmp_config)


# ── security ──────────────────────────────────────────────────────────────────

class TestSanitizeText:
    def test_anthropic_key_redacted(self) -> None:
        text = "ANTHROPIC_API_KEY=sk-ant-api03-abc123XYZ456def789"
        result = sanitize_text(text)
        assert "sk-ant" not in result
        assert "[REDACTED]" in result

    def test_bearer_token_redacted(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
        result = sanitize_text(text)
        assert "eyJhbGc" not in result

    def test_clean_text_unchanged(self) -> None:
        text = "Agent exited with code 1 after 42s for request req_abc123"
        assert sanitize_text(text) == text

    def test_api_key_value_redacted(self) -> None:
        text = "api_key=ABCDEFGHIJKLMNOP12345678"
        result = sanitize_text(text)
        assert "ABCDEFGHIJKLMNOP12345678" not in result


# ── config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_defaults(self) -> None:
        cfg = Config()
        assert cfg.port == 8081
        assert cfg.host == "127.0.0.1"
        assert cfg.agent_timeout == 1800

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FOLIOPAGE_PORT", "9999")
        monkeypatch.setenv("FOLIOPAGE_AGENT_TIMEOUT", "120")
        cfg = Config.from_env()
        assert cfg.port == 9999
        assert cfg.agent_timeout == 120

    def test_workspace_root_is_path(self) -> None:
        cfg = Config()
        assert isinstance(cfg.workspace_root, Path)


# ── session ───────────────────────────────────────────────────────────────────

class TestSession:
    def test_create_makes_directories(self, session: Session) -> None:
        assert session.session_dir.exists()
        assert session.output_dir.exists()
        assert session.logs_dir.exists()

    def test_session_id_has_prefix(self, session: Session) -> None:
        assert session.session_id.startswith("sess_")

    def test_create_initializes_json(self, session: Session) -> None:
        assert json.loads(session.page_stack_path.read_text()) == []
        assert json.loads(session.data_cache_path.read_text()) == {}

    def test_create_symlinks_claude_md(self, session: Session) -> None:
        assert (session.workspace / "CLAUDE.md").is_symlink()

    def test_create_symlinks_dot_claude(self, session: Session) -> None:
        assert (session.workspace / ".claude").is_symlink()

    def test_create_symlinks_mcp_json(self, session: Session) -> None:
        # .mcp.json must be symlinked so MCP tools are reachable from workspace cwd
        assert (session.workspace / ".mcp.json").is_symlink()

    def test_load_existing(self, session: Session, tmp_config: Config) -> None:
        loaded = Session.load(session.session_id, tmp_config)
        assert loaded.session_id == session.session_id

    def test_load_missing_raises(self, tmp_config: Config) -> None:
        with pytest.raises(SessionNotFoundError):
            Session.load("nonexistent_session_id", tmp_config)

    def test_page_stack_empty_on_init(self, session: Session) -> None:
        assert session.page_stack() == []

    def test_page_stack_reads_agent_writes(self, session: Session) -> None:
        entry = {
            "request_id": "req_abc",
            "action": "initial",
            "stock_query": "茅台",
            "html_file": "output/page-req_abc.html",
            "timestamp": "2026-01-01T00:00:00Z",
            "title": "贵州茅台",
        }
        session.page_stack_path.write_text(json.dumps([entry]), encoding="utf-8")
        stack = session.page_stack()
        assert len(stack) == 1
        assert stack[0].request_id == "req_abc"
        assert stack[0].stock_query == "茅台"

    def test_latest_page_none_when_empty(self, session: Session) -> None:
        assert session.latest_page() is None

    def test_html_path_fallback(self, session: Session) -> None:
        rid = "req_test123"
        html = session.output_dir / f"page-{rid}.html"
        html.write_text("<html/>")
        result = session.html_path(rid)
        assert result == html

    def test_pop_page_reduces_stack(self, session: Session) -> None:
        entries = [
            {
                "request_id": f"req_{i}",
                "action": "initial",
                "stock_query": "茅台",
                "html_file": f"output/page-req_{i}.html",
                "timestamp": "2026-01-01T00:00:00Z",
            }
            for i in range(2)
        ]
        # Create HTML files so html_path lookup works
        for e in entries:
            (session.output_dir / f"page-req_{entries.index(e)}.html").write_text("<html/>")
        session.page_stack_path.write_text(json.dumps(entries), encoding="utf-8")
        prev = session.pop_page()
        assert prev is not None
        assert prev.request_id == "req_0"
        assert len(session.page_stack()) == 1

    def test_pop_page_single_entry_unchanged(self, session: Session) -> None:
        entry = {
            "request_id": "req_only",
            "action": "initial",
            "stock_query": "茅台",
            "html_file": "output/page-req_only.html",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        session.page_stack_path.write_text(json.dumps([entry]), encoding="utf-8")
        prev = session.pop_page()
        assert prev is not None
        assert prev.request_id == "req_only"
        # Stack unchanged
        assert len(session.page_stack()) == 1

    def test_to_dict(self, session: Session) -> None:
        d = session.to_dict()
        assert d["session_id"] == session.session_id
        assert "workspace" in d
        assert d["page_count"] == 0


# ── PageEntry ─────────────────────────────────────────────────────────────────

class TestPageEntry:
    def test_from_dict_round_trip(self) -> None:
        raw = {
            "request_id": "req_123",
            "action": "drill_down",
            "stock_query": "AAPL",
            "html_file": "output/page-req_123.html",
            "timestamp": "2026-01-01T00:00:00Z",
            "title": "Apple Inc.",
            "custom_field": "hello",
        }
        entry = PageEntry.from_dict(raw)
        assert entry.request_id == "req_123"
        assert entry.extra == {"custom_field": "hello"}
        d = entry.to_dict()
        assert d["custom_field"] == "hello"
        assert "extra" not in d


# ── prompts ───────────────────────────────────────────────────────────────────

class TestPrompts:
    def test_initial_prompt_contains_fields(self) -> None:
        prompt = build_initial_prompt(
            request_id="req_001",
            stock_query="宁德时代",
            hint="focus on battery margin",
        )
        assert "ACTION: initial" in prompt
        assert "REQUEST_ID: req_001" in prompt
        assert "STOCK_QUERY: 宁德时代" in prompt
        assert "stock-overview" in prompt

    def test_drilldown_prompt(self) -> None:
        prompt = build_drilldown_prompt(
            request_id="req_002",
            stock_query="AAPL",
            clicked_topic="gross_margin",
            clicked_context={"metric": "gross_margin", "value": 42.5},
        )
        assert "ACTION: drill_down" in prompt
        assert "CLICKED_TOPIC: gross_margin" in prompt
        assert "gross_margin" in prompt
        assert "metric-drilldown" in prompt

    @pytest.mark.parametrize("topic,expected_skill", [
        ("business_breakdown",    "business-breakdown"),
        ("valuation_deep",        "valuation-deep"),
        ("peer_comparison_deep",  "peer-comparison-deep"),
        ("capital_flow",          "capital-flow"),
        ("sentiment_analysis",    "sentiment-analysis"),
        ("event_timeline",        "event-timeline"),
        ("gross_margin",          "metric-drilldown"),   # legacy fallback
        ("rd_intensity",          "metric-drilldown"),   # legacy fallback
    ])
    def test_drilldown_skill_routing(self, topic: str, expected_skill: str) -> None:
        prompt = build_drilldown_prompt(
            request_id="req_skill",
            stock_query="600519",
            clicked_topic=topic,
            clicked_context={},
        )
        assert f"Use the {expected_skill} skill." in prompt
        assert "ACTION: drill_down" in prompt
        assert f"CLICKED_TOPIC: {topic}" in prompt

    def test_peer_switch_prompt(self) -> None:
        prompt = build_peer_switch_prompt(
            request_id="req_003",
            peer_code="000858",
            peer_name="五粮液",
            original_query="茅台",
        )
        assert "ACTION: peer_switch" in prompt
        assert "STOCK_QUERY: 000858" in prompt
        assert "ORIGINAL_QUERY: 茅台" in prompt


# ── agent_runner (mocked) ─────────────────────────────────────────────────────

class TestAgentRunner:
    def _make_workspace(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "output").mkdir(parents=True)
        (ws / "logs").mkdir(parents=True)
        return ws

    def _make_config(self) -> Config:
        cfg = Config()
        cfg.claude_bin = "claude"
        cfg.agent_timeout = 30
        return cfg

    def test_success_returns_result(self, tmp_path: Path) -> None:
        from orchestrator.agent_runner import AgentResult, run_agent

        ws = self._make_workspace(tmp_path)
        cfg = self._make_config()
        rid = "req_ok"
        html = ws / "output" / f"page-{rid}.html"

        with patch("subprocess.Popen") as MockPopen:
            proc = MagicMock()
            proc.returncode = 0

            def _write_and_return(*args, **kwargs):
                html.write_text("<html/>")
                return (b"", b"")

            proc.communicate.side_effect = _write_and_return
            MockPopen.return_value = proc

            result = run_agent(
                prompt="test",
                request_id=rid,
                workspace=ws,
                config=cfg,
            )

        assert isinstance(result, AgentResult)
        assert result.html_path == html
        assert result.request_id == rid

    def test_timeout_raises(self, tmp_path: Path) -> None:
        from orchestrator.agent_runner import run_agent

        ws = self._make_workspace(tmp_path)
        cfg = self._make_config()

        with patch("subprocess.Popen") as MockPopen:
            proc = MagicMock()
            proc.communicate.side_effect = [
                subprocess.TimeoutExpired(cmd="claude", timeout=30),
                (b"", b""),
            ]
            MockPopen.return_value = proc

            with pytest.raises(AgentTimeoutError):
                run_agent(
                    prompt="test",
                    request_id="req_timeout",
                    workspace=ws,
                    config=cfg,
                )

    def test_nonzero_exit_raises(self, tmp_path: Path) -> None:
        from orchestrator.agent_runner import run_agent

        ws = self._make_workspace(tmp_path)
        cfg = self._make_config()

        with patch("subprocess.Popen") as MockPopen:
            proc = MagicMock()
            proc.returncode = 1
            proc.communicate.return_value = (b"", b"")
            MockPopen.return_value = proc

            with pytest.raises(AgentNonZeroExitError) as exc_info:
                run_agent(
                    prompt="test",
                    request_id="req_fail",
                    workspace=ws,
                    config=cfg,
                )
            assert exc_info.value.exit_code == 1

    def test_missing_output_raises(self, tmp_path: Path) -> None:
        from orchestrator.agent_runner import run_agent

        ws = self._make_workspace(tmp_path)
        cfg = self._make_config()

        with patch("subprocess.Popen") as MockPopen:
            proc = MagicMock()
            proc.returncode = 0
            proc.communicate.return_value = (b"", b"")
            MockPopen.return_value = proc

            with pytest.raises(AgentDidNotProduceOutputError):
                run_agent(
                    prompt="test",
                    request_id="req_nofile",
                    workspace=ws,
                    config=cfg,
                )


# ── FastAPI server (unit-level) ───────────────────────────────────────────────

class TestServer:
    @pytest.fixture()
    def client(self, tmp_config: Config):
        from fastapi.testclient import TestClient

        from orchestrator.server import create_app

        app = create_app(tmp_config)
        return TestClient(app)

    def test_index_returns_html(self, client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Foliopage" in resp.text

    def test_report_returns_html(self, client) -> None:
        resp = client.get("/report")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_session_not_found(self, client) -> None:
        resp = client.get("/api/sessions/nonexistent_abc")
        assert resp.status_code == 404

    def test_generate_unknown_action(self, client) -> None:
        resp = client.post(
            "/api/generate",
            json={"action": "unknown", "context": {"stock_query": "茅台"}},
        )
        assert resp.status_code == 422

    def test_generate_initial_missing_stock_query(self, client) -> None:
        resp = client.post(
            "/api/generate",
            json={"action": "initial", "context": {}},
        )
        assert resp.status_code == 422

    def test_drilldown_missing_fields(self, client) -> None:
        resp = client.post(
            "/api/generate",
            json={"action": "drill_down", "context": {"stock_code": "600519"}},
        )
        assert resp.status_code == 422

    def test_peer_switch_missing_stock_code(self, client) -> None:
        resp = client.post(
            "/api/generate",
            json={"action": "peer_switch", "context": {}},
        )
        assert resp.status_code == 422

    def test_back_session_not_found(self, client) -> None:
        resp = client.post("/api/session/nonexistent/back")
        assert resp.status_code == 404

    def test_back_plural_route(self, client) -> None:
        resp = client.post("/api/sessions/nonexistent/back")
        assert resp.status_code == 404

    def test_generate_response_has_cached_field(self, tmp_config: Config) -> None:
        """GenerateResponse must include cached and error fields."""
        from orchestrator.server import GenerateResponse
        r = GenerateResponse(
            session_id="sess_x",
            request_id="req_x",
            html="<html/>",
            html_url="/api/sessions/sess_x/pages/req_x",
            duration_ms=100,
            page_stack=[],
        )
        assert r.cached is False
        assert r.error is False

    def test_generate_force_refresh_accepted(self, client) -> None:
        """force_refresh field in request body should not cause validation errors."""
        # Will fail with 422 only on missing stock_query, not on force_refresh
        resp = client.post(
            "/api/generate",
            json={"action": "initial", "context": {}, "force_refresh": True},
        )
        assert resp.status_code == 422  # missing stock_query — not a field error


class TestPageCache:
    """Tests for the orchestrator page-level HTML cache."""

    @pytest.fixture()
    def cache_config(self, tmp_path: Path) -> Config:
        cfg = Config()
        cfg.workspace_root = tmp_path / "sessions"
        cfg.workspace_root.mkdir()
        cfg.repo_root = Path(__file__).parent.parent
        cfg.page_cache_root = tmp_path / "page_cache"
        cfg.page_cache_ttl = 1800
        return cfg

    def test_cache_key_stable(self) -> None:
        from orchestrator.server import _page_cache_key
        k1 = _page_cache_key("initial", {"stock_query": "茅台", "hint": "focus"})
        k2 = _page_cache_key("initial", {"stock_query": "茅台", "hint": "changed"})
        # hint is volatile — same key
        assert k1 == k2

    def test_cache_key_differs_by_context(self) -> None:
        from orchestrator.server import _page_cache_key
        k1 = _page_cache_key("initial", {"stock_query": "茅台"})
        k2 = _page_cache_key("initial", {"stock_query": "AAPL"})
        assert k1 != k2

    def test_cache_miss_returns_none(self, tmp_path: Path) -> None:
        from orchestrator.server import _check_page_cache
        result = _check_page_cache("nonexistent_key", tmp_path / "cache", 1800)
        assert result is None

    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        from orchestrator.server import _check_page_cache, _write_page_cache
        cache_dir = tmp_path / "cache"
        _write_page_cache("abc123", cache_dir, "<html>hello</html>",
                          "initial", {"stock_query": "茅台"}, 5000)
        hit = _check_page_cache("abc123", cache_dir, 1800)
        assert hit is not None
        html, meta = hit
        assert "<html>hello</html>" in html
        assert meta["duration_ms"] == 5000

    def test_cache_expires(self, tmp_path: Path) -> None:
        import time as _time

        from orchestrator.server import _check_page_cache, _write_page_cache
        cache_dir = tmp_path / "cache"
        _write_page_cache("expkey", cache_dir, "<html/>",
                          "initial", {}, 100)
        # Manually backdate the meta
        import json as _json
        meta_path = cache_dir / "expkey.meta.json"
        meta = _json.loads(meta_path.read_text())
        meta["created_at_ts"] = _time.time() - 9999
        meta_path.write_text(_json.dumps(meta))
        assert _check_page_cache("expkey", cache_dir, 1800) is None

    def test_generate_cache_hit_returns_cached_true(
        self, cache_config: Config
    ) -> None:
        """Pre-populate page cache; generate should return cached=True immediately."""
        from fastapi.testclient import TestClient

        from orchestrator.server import _page_cache_key, _write_page_cache, create_app

        # Pre-populate cache with a fake HTML page
        action = "initial"
        ctx = {"stock_query": "茅台"}
        key = _page_cache_key(action, ctx)
        _write_page_cache(key, cache_config.page_cache_root,
                          "<!DOCTYPE html><html><body>cached</body></html>",
                          action, ctx, 1234)

        app = create_app(cache_config)
        with TestClient(app) as client:
            resp = client.post(
                "/api/generate",
                json={"action": "initial", "context": {"stock_query": "茅台"}},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is True
        assert "cached" in data["html"]
        assert data["duration_ms"] == 1234

    def test_generate_force_refresh_skips_cache(
        self, cache_config: Config
    ) -> None:
        """force_refresh=True should bypass a valid cache hit."""
        from unittest.mock import MagicMock, patch

        from fastapi.testclient import TestClient

        from orchestrator.server import _page_cache_key, _write_page_cache, create_app

        action = "initial"
        ctx = {"stock_query": "茅台"}
        key = _page_cache_key(action, ctx)
        _write_page_cache(key, cache_config.page_cache_root,
                          "<!DOCTYPE html><html><body>stale</body></html>",
                          action, ctx, 999)

        app = create_app(cache_config)
        with TestClient(app) as client:
            with patch("orchestrator.server.run_agent") as mock_run:
                # Simulate agent producing output
                mock_result = MagicMock()
                # Create a plausible html file path; agent_runner sets html_path
                def _fake_run(**kwargs):
                    html_file = kwargs["workspace"] / "output" / f"page-{kwargs['request_id']}.html"
                    html_file.parent.mkdir(parents=True, exist_ok=True)
                    html_file.write_text("<!DOCTYPE html><html><body>fresh</body></html>")
                    mock_result.html_path = html_file
                    mock_result.json_path = None  # simulate legacy HTML output
                    mock_result.duration_seconds = 1.0
                    return mock_result
                mock_run.side_effect = _fake_run

                resp = client.post(
                    "/api/generate",
                    json={"action": "initial", "context": {"stock_query": "茅台"},
                          "force_refresh": True},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is False


class TestErrorPages:
    """Tests for error page generation when the agent fails."""

    def test_build_error_html_contains_title(self) -> None:
        from orchestrator.server import _build_error_html
        html = _build_error_html("生成超时", "数据源响应慢", "req_xyz")
        assert "生成超时" in html
        assert "数据源响应慢" in html
        assert "req_xyz" in html

    def test_build_error_html_has_retry_button(self) -> None:
        from orchestrator.server import _build_error_html
        html = _build_error_html("失败", "原因", "req_abc")
        assert "retry" in html
        assert "重试" in html

    def test_build_error_html_includes_transcript_path(self, tmp_path: Path) -> None:
        from orchestrator.server import _build_error_html
        tp = tmp_path / "logs" / "transcript.jsonl"
        html = _build_error_html("err", "desc", "req_t", transcript_path=tp)
        assert str(tp) in html

    def test_agent_timeout_returns_200_error_page(
        self, tmp_config: Config
    ) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from orchestrator.errors import AgentTimeoutError
        from orchestrator.server import create_app

        app = create_app(tmp_config)
        with TestClient(app) as client:
            with patch("orchestrator.server.run_agent",
                       side_effect=AgentTimeoutError("timed out")):
                resp = client.post(
                    "/api/generate",
                    json={"action": "initial", "context": {"stock_query": "茅台"}},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is True
        assert "生成超时" in data["html"] or "超时" in data["html"]

    def test_agent_nonzero_returns_200_error_page(
        self, tmp_config: Config
    ) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from orchestrator.errors import AgentNonZeroExitError
        from orchestrator.server import create_app

        app = create_app(tmp_config)
        with TestClient(app) as client:
            with patch("orchestrator.server.run_agent",
                       side_effect=AgentNonZeroExitError("bad exit", exit_code=1)):
                resp = client.post(
                    "/api/generate",
                    json={"action": "initial", "context": {"stock_query": "茅台"}},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is True
        assert "生成失败" in data["html"] or "出错" in data["html"]


# ── Integration (skipped by default) ─────────────────────────────────────────

@pytest.mark.integration
def test_e2e_generate(tmp_config: Config) -> None:
    """
    Full end-to-end: spawns real claude subprocess for 洋河股份.
    Only run with:  pytest -m integration tests/test_orchestrator.py
    Requires claude binary and MCP tools configured.
    """
    from fastapi.testclient import TestClient

    from orchestrator.server import create_app

    tmp_config.agent_timeout = 900  # 14-section overview targets ≤15 min with parallel charts + no compaction

    app = create_app(tmp_config)
    with TestClient(app) as client:
        resp = client.post(
            "/api/generate",
            json={"action": "initial", "context": {"stock_query": "洋河股份"}},
            timeout=950,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["session_id"].startswith("sess_")
    assert data["request_id"].startswith("req_")
    assert data["html"].startswith("<!DOCTYPE html>")
    assert data["html"].count("data-flipbook-action") >= 5
    assert "本页面由 AI 生成" in data["html"]
    assert "<svg" in data["html"]
    assert "/static/foliopage.css" in data["html"]
    assert len(data["page_stack"]) == 1
    assert 30_000 <= data["duration_ms"] <= 1_000_000
