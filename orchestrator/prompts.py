"""Prompt builders for the three agent action types."""
from __future__ import annotations

import json


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
) -> str:
    """Prompt for a metric drilldown page."""
    if isinstance(clicked_context, dict):
        clicked_context = json.dumps(clicked_context, ensure_ascii=False)
    lines = [
        "ACTION: drill_down",
        f"REQUEST_ID: {request_id}",
        f"STOCK_QUERY: {stock_query}",
        f"CLICKED_TOPIC: {clicked_topic}",
        f"CLICKED_CONTEXT: {clicked_context}",
        f"PARENT_PAGE: {parent_request_id}",
        f"HINT: {hint}",
        "",
        "Follow CLAUDE.md. Use the metric-drilldown skill.",
    ]
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
        f"STOCK_QUERY: {peer_code}",
        f"STOCK_NAME: {peer_name}",
        f"ORIGINAL_QUERY: {original_query}",
        f"PARENT_PAGE: {parent_request_id}",
        f"HINT: {hint}",
        "",
        "Follow CLAUDE.md. Use the stock-overview skill for this peer company.",
    ]
    return "\n".join(lines)
