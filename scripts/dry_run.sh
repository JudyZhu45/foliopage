#!/usr/bin/env bash
# scripts/dry_run.sh
# Manual end-to-end test for CLAUDE.md + skills, without orchestrator.
# Run from repo root: ./scripts/dry_run.sh [stock_query]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRYRUN_DIR="${REPO_ROOT}/.foliopage/dryrun"
STOCK_QUERY="${1:-洋河股份}"      # default: 002304, less rate-limited than 600519
REQUEST_ID="req_dryrun_$(date +%s)"

echo "Foliopage dry-run"
echo "   Repo:       ${REPO_ROOT}"
echo "   Workspace:  ${DRYRUN_DIR}"
echo "   Query:      ${STOCK_QUERY}"
echo "   Request ID: ${REQUEST_ID}"
echo

# Clean & rebuild workspace
rm -rf "${DRYRUN_DIR}"
mkdir -p "${DRYRUN_DIR}"/{session,output,logs}
cd "${DRYRUN_DIR}"

# Symlinks (absolute paths for reliability)
ln -s "${REPO_ROOT}/CLAUDE.md" CLAUDE.md
ln -s "${REPO_ROOT}/.claude" .claude
ln -s "${REPO_ROOT}/shell/static" static

# examples/ is optional — only symlink if it exists
if [[ -d "${REPO_ROOT}/examples" ]]; then
    ln -s "${REPO_ROOT}/examples" examples
fi

# Initialize empty session state
echo '[]' > session/page_stack.json
echo '{}' > session/data_cache.json

# Confirm MCP tools registered (project-level .mcp.json or user-level)
if [[ ! -f "${REPO_ROOT}/.mcp.json" && ! -f "${HOME}/.claude/mcp.json" ]]; then
    echo "WARNING: No .mcp.json found. MCP tools may not be available to claude."
    echo "    See README for registration instructions."
    echo
fi

# Build the prompt
PROMPT=$(cat <<EOF
ACTION: initial
REQUEST_ID: ${REQUEST_ID}
STOCK_QUERY: ${STOCK_QUERY}
HINT:

Follow CLAUDE.md. Use the stock-overview skill.
EOF
)

echo "Prompt:"
echo "----"
echo "${PROMPT}"
echo "----"
echo

echo "Spawning claude (this will take 30-90s)..."
START=$(date +%s)

# Run claude with the same flags the orchestrator will use
echo "${PROMPT}" | claude -p \
    --dangerously-skip-permissions \
    --verbose \
    --output-format stream-json \
    > logs/transcript.jsonl 2>&1

END=$(date +%s)
DURATION=$((END - START))
echo "claude finished in ${DURATION}s"
echo

# ── Verification ──────────────────────────────────────────────────────────────
EXPECTED_HTML="output/page-${REQUEST_ID}.html"

echo "Verification:"

if [[ ! -f "${EXPECTED_HTML}" ]]; then
    echo "   FAIL HTML not written: ${EXPECTED_HTML}"
    echo "   Last 20 transcript events:"
    tail -20 logs/transcript.jsonl
    exit 1
fi
echo "   PASS HTML file exists ($(wc -c < "${EXPECTED_HTML}") bytes)"

# Grep directly from the file — avoids large-variable echo truncation issues
check() {
    local name="$1"; local pattern="$2"
    if grep -qE "${pattern}" "${EXPECTED_HTML}"; then
        echo "   PASS ${name}"
    else
        echo "   FAIL MISSING: ${name}  (pattern: ${pattern})"
    fi
}

check "DOCTYPE present"               "<!DOCTYPE html>"
check "foliopage.css linked"          'href="/static/foliopage\.css"'
check "Disclaimer present"            "本页面由 AI 生成"
check "Data freshness shown"          "data-as-of"
check "K-line chart inlined"          "<svg"
check "At least one drillable element" "data-flipbook-action"
check "Stock code mentioned"          "[0-9]{6}|AAPL|TSLA|NVDA"

# Count drillable elements
DRILL_COUNT=$(grep -o "data-flipbook-action" "${EXPECTED_HTML}" | wc -l | tr -d ' ')
if (( DRILL_COUNT >= 5 )); then
    echo "   PASS Drillable element count: ${DRILL_COUNT} (target >= 5)"
else
    echo "   FAIL Drillable element count: ${DRILL_COUNT} (target >= 5)"
fi

# Check page_stack was updated
STACK_LEN=$(python3 -c "import json,sys; print(len(json.load(open('session/page_stack.json'))))" 2>/dev/null || echo 0)
if (( STACK_LEN >= 1 )); then
    echo "   PASS page_stack.json has ${STACK_LEN} entries"
else
    echo "   FAIL page_stack.json was not updated by agent"
fi

# Check data_cache was populated
CACHE_KEYS=$(python3 -c "import json,sys; print(len(json.load(open('session/data_cache.json'))))" 2>/dev/null || echo 0)
echo "   INFO data_cache.json has ${CACHE_KEYS} keys"

echo
echo "Open the result:"
echo "   open ${DRYRUN_DIR}/${EXPECTED_HTML}"
echo
echo "Inspect tool calls from transcript:"
echo "   python3 -c \""
echo "     import json,sys"
echo "     calls = []"
echo "     for line in open('${DRYRUN_DIR}/logs/transcript.jsonl'):"
echo "       try:"
echo "         e = json.loads(line)"
echo "         if e.get('type')=='assistant':"
echo "           for b in e.get('message',{}).get('content',[]):"
echo "             if b.get('type')=='tool_use': calls.append(b['name'])"
echo "       except: pass"
echo "     [print(c) for c in sorted(set(calls))]"
echo "   \""
echo
echo "Inspect data_cache keys:"
echo "   python3 -c \"import json; print(json.dumps(list(json.load(open('${DRYRUN_DIR}/session/data_cache.json')).keys()), indent=2))\""
