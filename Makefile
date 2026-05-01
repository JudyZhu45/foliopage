.PHONY: install test test-all lint format dev clean fresh

PYTHON := .venv/bin/python
UV     := uv

# ── Setup ────────────────────────────────────────────────────────────────────

install:
	$(UV) sync --all-extras
	./scripts/init_mcp.sh

# ── Tests ────────────────────────────────────────────────────────────────────

## Fast unit tests only (no network, no real agent)
test:
	$(UV) run pytest tests/ -m "not integration" -v

## All tests including integration (requires network + Claude CLI)
test-all:
	$(UV) run pytest tests/ -v

# ── Code quality ─────────────────────────────────────────────────────────────

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

# ── Development server ────────────────────────────────────────────────────────

dev:
	$(UV) run uvicorn orchestrator.server:app --reload --port 8000

# ── Cleanup ───────────────────────────────────────────────────────────────────

## Remove generated artefacts (keeps .venv and uv.lock)
clean:
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
	find . -name '*.pyc' -not -path './.venv/*' -delete
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info

## Full reset: clean + wipe venv (re-run 'make install' after)
fresh: clean
	rm -rf .venv
