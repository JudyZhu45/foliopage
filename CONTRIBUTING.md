# Contributing to Foliopage

Three contribution paths are described below. For everything else — bug reports,
feature requests, or general discussion — open a GitHub issue.

---

## Adding a new MCP tool

MCP tools live in `tools/<name>_mcp/server.py` and are registered in `.mcp.json`.

**1. Scaffold the server**

```
tools/
  my_mcp/
    __init__.py
    server.py        ← FastMCP server
tests/
  test_my_mcp.py
```

`server.py` minimal template:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("foliopage-my")

@mcp.tool()
def my_tool(arg: str) -> dict:
    """One-line description of what this tool returns."""
    ...

if __name__ == "__main__":
    mcp.run()
```

**2. Register in `.mcp.json`**

Add an entry under `mcpServers`. Run `./scripts/init_mcp.sh` to regenerate
`.mcp.json` with correct absolute paths, or add the entry manually:

```json
"foliopage-my": {
  "type": "stdio",
  "command": "/abs/path/to/.venv/bin/python",
  "args": ["-m", "tools.my_mcp.server"],
  "cwd": "/abs/path/to/foliopage"
}
```

**3. Document in `CLAUDE.md`**

Add the tool signature under `## Available MCP tools` so the agent can call it
without a discovery step. Follow the existing format exactly:

```
### foliopage-my
- `mcp__foliopage-my__my_tool(arg: str) -> dict` — description of return value
```

**4. Write tests**

Unit-test each tool function directly (no subprocess). Use
`monkeypatch.setenv("FOLIOPAGE_CACHE_DB", ...)` for any env-dependent tools.
Mark network-touching tests with `@pytest.mark.integration`.

---

## Adding a new skill

Skills are action-specific recipes stored in `.claude/skills/<name>/SKILL.md`.
Adding a skill teaches the agent a new page type without touching orchestrator code.

**1. Create the skill file**

```
.claude/skills/my-skill/SKILL.md
```

Every `SKILL.md` must contain these sections (in order):

| Section | Content |
|---------|---------|
| `# Skill: <name>` | One-sentence purpose |
| `## Data to fetch` | Exact cache keys + MCP tool calls needed |
| `## Charts to generate` | Which `chart_mcp` tools to call, with parameter guidance |
| `## Page sections` | Ordered list of sections the HTML must contain |
| `## Drillable elements` | Which elements carry `data-flipbook-action` and what context they emit |

See `.claude/skills/stock-overview/SKILL.md` as the reference example.

**2. Understand how skills are dispatched**

The orchestrator sends an action string (`initial`, `drill_down`, `peer_switch`,
or a custom name) together with a context dict to the agent via stdin. The agent
reads `CLAUDE.md` Phase 2, which loads the skill file whose name matches the
`SKILL` field in the prompt. To route to a new skill, pass its name as the
`skill` key in the context, or add a mapping in `orchestrator/prompts.py` if the
routing is deterministic.

**3. Test the skill end-to-end**

```bash
make dev          # start the server
# Open http://localhost:8000 and run a query that exercises the new skill.
# Inspect the generated page in ~/.foliopage/sessions/<latest>/output/.
```

There is no automated test for skill output quality — review it manually.

---

## Reporting bugs and discussing features

Open a [GitHub issue](../../issues/new/choose) and choose the appropriate template:

- **Bug report** — include OS, Python version, the query that failed, and the
  relevant lines from `~/.foliopage/sessions/<sess_id>/logs/transcript.jsonl`.
- **Feature request** — describe the use case, not just the desired behaviour.
- **Question** — use the Discussions tab rather than Issues.

Before filing, search existing issues to avoid duplicates.
