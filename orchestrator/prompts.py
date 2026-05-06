"""Prompt builders for the three agent action types."""
from __future__ import annotations

import json

# Maps clicked_topic values to the skill directory name the agent should load.
# Topics not listed here fall back to "metric-drilldown".
_DRILL_SKILL_MAP: dict[str, str] = {
    "business_breakdown": "business-breakdown",
    "valuation_deep": "valuation-deep",
    "peer_comparison_deep": "peer-comparison-deep",
    "capital_flow": "capital-flow",
    "sentiment_analysis": "sentiment-analysis",
    "event_timeline": "event-timeline",
}


def build_initial_prompt(
    *,
    request_id: str,
    stock_query: str,
    hint: str = "",
) -> str:
    """Prompt for the first page in a session (stock overview)."""
    lines = [
        "ACTION: initial",
        f"REQUEST_ID: {request_id}",
        f"STOCK_QUERY: {stock_query}",
        f"HINT: {hint}",
        "",
        "Follow CLAUDE.md. Use the stock-overview skill.",
    ]
    return "\n".join(lines)


def build_drilldown_prompt(
    *,
    request_id: str,
    stock_query: str,
    clicked_topic: str,
    clicked_context: dict | str = "",
    parent_request_id: str = "",
    hint: str = "",
    stock_code: str = "",
    stock_name: str = "",
) -> str:
    """Prompt for a metric drilldown page."""
    if isinstance(clicked_context, dict):
        clicked_context = json.dumps(clicked_context, ensure_ascii=False)
    skill = _DRILL_SKILL_MAP.get(clicked_topic, "metric-drilldown")
    lines = [
        "ACTION: drill_down",
        f"REQUEST_ID: {request_id}",
        f"STOCK_QUERY: {stock_query}",
        f"CLICKED_TOPIC: {clicked_topic}",
        f"CLICKED_CONTEXT: {clicked_context}",
        f"PARENT_PAGE: {parent_request_id}",
        f"HINT: {hint}",
    ]
    if stock_code:
        lines.append(f"STOCK_CODE: {stock_code}")
    if stock_name:
        lines.append(f"STOCK_NAME: {stock_name}")
    lines += ["", f"Follow CLAUDE.md. Use the {skill} skill."]
    return "\n".join(lines)


def build_peer_switch_prompt(
    *,
    request_id: str,
    peer_code: str,
    peer_name: str = "",
    original_query: str = "",
    parent_request_id: str = "",
    hint: str = "",
) -> str:
    """Prompt for switching to a peer company's overview page."""
    lines = [
        "ACTION: peer_switch",
        f"REQUEST_ID: {request_id}",
        f"STOCK_CODE: {peer_code}",
        f"STOCK_NAME: {peer_name}",
        f"STOCK_QUERY: {peer_code}",
        f"ORIGINAL_QUERY: {original_query}",
        f"PARENT_PAGE: {parent_request_id}",
        f"HINT: {hint}",
        "",
        "Follow CLAUDE.md. Use the stock-overview skill for this peer company.",
    ]
    return "\n".join(lines)
