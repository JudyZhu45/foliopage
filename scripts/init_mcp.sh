#!/usr/bin/env bash
# init_mcp.sh — Write .mcp.json with paths correct for this machine.
#
# Run after cloning or moving the repo:
#   ./scripts/init_mcp.sh
#
# The generated .mcp.json uses the repo's venv Python so Claude Code can
# discover and launch the three MCP servers (stock, chart, news).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Error: virtual environment not found at ${REPO_DIR}/.venv" >&2
  echo "Run 'uv sync' first to create the venv." >&2
  exit 1
fi

cat > "${REPO_DIR}/.mcp.json" <<EOF
{
  "mcpServers": {
    "foliopage-stock": {
      "type": "stdio",
      "command": "${PYTHON}",
      "args": ["-m", "tools.stock_mcp.server"],
      "cwd": "${REPO_DIR}"
    },
    "foliopage-chart": {
      "type": "stdio",
      "command": "${PYTHON}",
      "args": ["-m", "tools.chart_mcp.server"],
      "cwd": "${REPO_DIR}"
    },
    "foliopage-news": {
      "type": "stdio",
      "command": "${PYTHON}",
      "args": ["-m", "tools.news_mcp.server"],
      "cwd": "${REPO_DIR}"
    }
  }
}
EOF

echo "Written .mcp.json for repo at: ${REPO_DIR}"
echo "Python: ${PYTHON}"
