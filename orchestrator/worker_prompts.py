"""Worker and analyst prompt templates for multi-agent parallel research."""
from __future__ import annotations

import json


def build_worker_a_prompt(stock_code: str, request_id: str, output_file: str) -> str:
    """Worker A: get_basic_info + get_valuation."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_basic_info(code="{stock_code}")
- mcp__foliopage-stock__get_valuation(code="{stock_code}")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_A.py:

    import json, pathlib
    data = {{
        "worker_id": "A",
        "stock_code": "{stock_code}",
        "basic_info": <exact get_basic_info result dict>,
        "valuation": <exact get_valuation result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_A.py && rm gen_worker_A.py
Then print exactly: WORKER_A_DONE
"""


def build_worker_b_prompt(stock_code: str, request_id: str, output_file: str) -> str:
    """Worker B: get_financials annual + quarterly."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="annual")
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="quarterly")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_B.py:

    import json, pathlib
    data = {{
        "worker_id": "B",
        "stock_code": "{stock_code}",
        "financials_annual": <exact annual result dict>,
        "financials_quarterly": <exact quarterly result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_B.py && rm gen_worker_B.py
Then print exactly: WORKER_B_DONE
"""


def build_worker_c_prompt(stock_code: str, request_id: str, output_file: str) -> str:
    """Worker C: recent_news + recent_announcements."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-news__recent_news(code="{stock_code}", days=14, limit=7)
- mcp__foliopage-news__recent_announcements(code="{stock_code}", days=30)

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_C.py:

    import json, pathlib
    data = {{
        "worker_id": "C",
        "stock_code": "{stock_code}",
        "recent_news": <exact recent_news result dict>,
        "recent_announcements": <exact recent_announcements result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_C.py && rm gen_worker_C.py
Then print exactly: WORKER_C_DONE
"""


def build_worker_d_prompt(stock_code: str, request_id: str, output_file: str) -> str:
    """Worker D: get_peers + verify each peer with get_basic_info."""
    return f"""\
You are a data-fetching worker. Follow these two steps:

STEP 1 — call get_peers (one tool, one turn):
  mcp__foliopage-stock__get_peers(code="{stock_code}", n=6)

STEP 2 — for EACH peer code returned in step 1, call get_basic_info.
  Call ALL peer get_basic_info calls simultaneously in ONE turn:
  mcp__foliopage-stock__get_basic_info(code=<peer_code_1>)
  mcp__foliopage-stock__get_basic_info(code=<peer_code_2>)
  ... (one call per peer, all in the same turn)

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving all results, use the Write tool to create gen_worker_D.py:

    import json, pathlib
    data = {{
        "worker_id": "D",
        "stock_code": "{stock_code}",
        "peers": <exact get_peers result dict>,
        "peers_detail": [
            {{"code": "<peer_code>", "basic_info": <exact get_basic_info result>}},
            ...one entry per peer...
        ],
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_D.py && rm gen_worker_D.py
Then print exactly: WORKER_D_DONE
"""


def build_analyst_prompt(
    *,
    stock_code: str,
    stock_name: str,
    request_id: str,
    action: str,
    raw_data_path: str,
    hint: str = "",
    parent_request_id: str = "",
) -> str:
    """
    Analyst prompt: reads pre-fetched raw_data.json, writes final JSON output.
    No MCP tool calls allowed.
    """
    skill = "stock-overview"
    lines = [
        f"ACTION: {action}",
        f"REQUEST_ID: {request_id}",
        f"STOCK_CODE: {stock_code}",
        f"STOCK_NAME: {stock_name}",
        f"DATA_FILE: {raw_data_path}",
        f"HINT: {hint}",
        f"PARENT_PAGE: {parent_request_id}",
        "",
        "CRITICAL: DATA_FILE is provided. All market data has been pre-fetched.",
        "Do NOT call any MCP tools (get_basic_info, get_financials, recent_news, etc.).",
        "Read DATA_FILE and the skill file, then proceed directly to writing JSON output.",
        "",
        f"Follow CLAUDE.md (Parallel Mode). Use the {skill} skill.",
    ]
    return "\n".join(lines)


# ── Drill-down worker prompts ─────────────────────────────────────────────────

def build_dd_news_worker_alpha(stock_code: str, request_id: str, output_file: str) -> str:
    """DD news-timeline α: recent_news(30d,20) + recent_announcements(90d) + analyst_consensus."""
    return f"""\
You are a data-fetching worker. Call ONLY these three tools simultaneously in ONE turn:
- mcp__foliopage-news__recent_news(code="{stock_code}", days=30, limit=20)
- mcp__foliopage-news__recent_announcements(code="{stock_code}", days=90)
- mcp__foliopage-news__analyst_consensus(code="{stock_code}")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving all results, use the Write tool to create gen_worker_dd_news_a.py:

    import json, pathlib
    data = {{
        "worker_id": "news_a",
        "stock_code": "{stock_code}",
        "recent_news": <exact recent_news result dict>,
        "recent_announcements": <exact recent_announcements result dict>,
        "analyst_consensus": <exact analyst_consensus result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_news_a.py && rm gen_worker_dd_news_a.py
Then print exactly: WORKER_DD_NEWS_A_DONE
"""


def build_dd_metric_worker_alpha(stock_code: str, request_id: str, output_file: str) -> str:
    """DD metric-drilldown α: get_valuation + get_financials annual + quarterly."""
    return f"""\
You are a data-fetching worker. Call ONLY these three tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_valuation(code="{stock_code}")
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="annual")
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="quarterly")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving all results, use the Write tool to create gen_worker_dd_metric_a.py:

    import json, pathlib
    data = {{
        "worker_id": "metric_a",
        "stock_code": "{stock_code}",
        "valuation": <exact get_valuation result dict>,
        "financials_annual": <exact annual get_financials result dict>,
        "financials_quarterly": <exact quarterly get_financials result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_metric_a.py && rm gen_worker_dd_metric_a.py
Then print exactly: WORKER_DD_METRIC_A_DONE
"""


def build_dd_metric_worker_beta(stock_code: str, request_id: str, output_file: str) -> str:
    """DD metric-drilldown β: get_peers(n=5)."""
    return f"""\
You are a data-fetching worker. Call ONLY this tool:
- mcp__foliopage-stock__get_peers(code="{stock_code}", n=5)

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving the result, use the Write tool to create gen_worker_dd_metric_b.py:

    import json, pathlib
    data = {{
        "worker_id": "metric_b",
        "stock_code": "{stock_code}",
        "peers": <exact get_peers result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_metric_b.py && rm gen_worker_dd_metric_b.py
Then print exactly: WORKER_DD_METRIC_B_DONE
"""


def build_dd_business_worker_alpha(stock_code: str, request_id: str, output_file: str) -> str:
    """DD business-breakdown α: get_basic_info + get_revenue_breakdown."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_basic_info(code="{stock_code}")
- mcp__foliopage-stock__get_revenue_breakdown(code="{stock_code}")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_dd_biz_a.py:

    import json, pathlib
    data = {{
        "worker_id": "biz_a",
        "stock_code": "{stock_code}",
        "basic_info": <exact get_basic_info result dict>,
        "revenue_breakdown": <exact get_revenue_breakdown result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_biz_a.py && rm gen_worker_dd_biz_a.py
Then print exactly: WORKER_DD_BIZ_A_DONE
"""


def build_dd_business_worker_beta(stock_code: str, request_id: str, output_file: str) -> str:
    """DD business-breakdown β: get_financials(annual) + get_peers(n=6)."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="annual")
- mcp__foliopage-stock__get_peers(code="{stock_code}", n=6)

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_dd_biz_b.py:

    import json, pathlib
    data = {{
        "worker_id": "biz_b",
        "stock_code": "{stock_code}",
        "financials_annual": <exact annual get_financials result dict>,
        "peers": <exact get_peers result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_biz_b.py && rm gen_worker_dd_biz_b.py
Then print exactly: WORKER_DD_BIZ_B_DONE
"""


def build_dd_valuation_worker_alpha(stock_code: str, request_id: str, output_file: str) -> str:
    """DD valuation-deep α: get_basic_info + get_valuation."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_basic_info(code="{stock_code}")
- mcp__foliopage-stock__get_valuation(code="{stock_code}")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_dd_val_a.py:

    import json, pathlib
    data = {{
        "worker_id": "val_a",
        "stock_code": "{stock_code}",
        "basic_info": <exact get_basic_info result dict>,
        "valuation": <exact get_valuation result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_val_a.py && rm gen_worker_dd_val_a.py
Then print exactly: WORKER_DD_VAL_A_DONE
"""


def build_dd_valuation_worker_beta(stock_code: str, request_id: str, output_file: str) -> str:
    """DD valuation-deep β: get_kline(5Y) + get_financials(annual)."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_kline(code="{stock_code}", range="5Y")
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="annual")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_dd_val_b.py:

    import json, pathlib
    data = {{
        "worker_id": "val_b",
        "stock_code": "{stock_code}",
        "kline_5y": <exact get_kline result dict>,
        "financials_annual": <exact annual get_financials result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_val_b.py && rm gen_worker_dd_val_b.py
Then print exactly: WORKER_DD_VAL_B_DONE
"""


def build_dd_valuation_worker_gamma(stock_code: str, request_id: str, output_file: str) -> str:
    """DD valuation-deep γ: get_peers(n=6) + analyst_consensus."""
    return f"""\
You are a data-fetching worker. Call ONLY these two tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_peers(code="{stock_code}", n=6)
- mcp__foliopage-news__analyst_consensus(code="{stock_code}")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving both results, use the Write tool to create gen_worker_dd_val_c.py:

    import json, pathlib
    data = {{
        "worker_id": "val_c",
        "stock_code": "{stock_code}",
        "peers": <exact get_peers result dict>,
        "analyst_consensus": <exact analyst_consensus result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_val_c.py && rm gen_worker_dd_val_c.py
Then print exactly: WORKER_DD_VAL_C_DONE
"""


def build_dd_peercomp_subject_worker(stock_code: str, request_id: str, output_file: str) -> str:
    """DD peer-comparison-deep Batch1 α: subject basic_info + valuation + financials."""
    return f"""\
You are a data-fetching worker. Call ONLY these three tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_basic_info(code="{stock_code}")
- mcp__foliopage-stock__get_valuation(code="{stock_code}")
- mcp__foliopage-stock__get_financials(code="{stock_code}", period="annual")

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving all results, use the Write tool to create gen_worker_dd_peercomp_subj.py:

    import json, pathlib
    data = {{
        "worker_id": "peercomp_subj",
        "stock_code": "{stock_code}",
        "subject_basic_info": <exact get_basic_info result dict>,
        "subject_valuation": <exact get_valuation result dict>,
        "subject_financials_annual": <exact annual get_financials result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_peercomp_subj.py && rm gen_worker_dd_peercomp_subj.py
Then print exactly: WORKER_DD_PEERCOMP_SUBJ_DONE
"""


def build_dd_peercomp_peers_worker(stock_code: str, request_id: str, output_file: str) -> str:
    """DD peer-comparison-deep Batch1 β: get_peers(n=6)."""
    return f"""\
You are a data-fetching worker. Call ONLY this tool:
- mcp__foliopage-stock__get_peers(code="{stock_code}", n=6)

STOCK_CODE: {stock_code}
OUTPUT_FILE: {output_file}

After receiving the result, use the Write tool to create gen_worker_dd_peercomp_peers.py:

    import json, pathlib
    data = {{
        "worker_id": "peercomp_peers",
        "stock_code": "{stock_code}",
        "peers_list": <exact get_peers result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_peercomp_peers.py && rm gen_worker_dd_peercomp_peers.py
Then print exactly: WORKER_DD_PEERCOMP_PEERS_DONE
"""


def build_dd_peercomp_peer_worker(peer_code: str, request_id: str, output_file: str) -> str:
    """DD peer-comparison-deep Batch2 per-peer: basic_info + valuation + financials."""
    return f"""\
You are a data-fetching worker. Call ONLY these three tools simultaneously in ONE turn:
- mcp__foliopage-stock__get_basic_info(code="{peer_code}")
- mcp__foliopage-stock__get_valuation(code="{peer_code}")
- mcp__foliopage-stock__get_financials(code="{peer_code}", period="annual")

PEER_CODE: {peer_code}
OUTPUT_FILE: {output_file}

After receiving all results, use the Write tool to create gen_worker_dd_peer.py:

    import json, pathlib
    data = {{
        "worker_id": "peer_{peer_code}",
        "peer_code": "{peer_code}",
        "basic_info": <exact get_basic_info result dict>,
        "valuation": <exact get_valuation result dict>,
        "financials_annual": <exact annual get_financials result dict>,
    }}
    pathlib.Path("{output_file}").parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path("{output_file}").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

Then run: python3 gen_worker_dd_peer.py && rm gen_worker_dd_peer.py
Then print exactly: WORKER_DD_PEER_DONE
"""


def build_drilldown_analyst_prompt(
    *,
    stock_code: str,
    stock_name: str,
    request_id: str,
    action: str,
    raw_data_path: str,
    skill: str,
    clicked_topic: str,
    clicked_context_str: str,
    hint: str = "",
    parent_request_id: str = "",
) -> str:
    """
    Analyst prompt for drill-down parallel mode.
    DATA_FILE already contains all pre-fetched data — no MCP calls allowed.
    """
    lines = [
        f"ACTION: {action}",
        f"REQUEST_ID: {request_id}",
        f"STOCK_CODE: {stock_code}",
        f"STOCK_NAME: {stock_name}",
        f"CLICKED_TOPIC: {clicked_topic}",
        f"CLICKED_CONTEXT: {clicked_context_str}",
        f"DATA_FILE: {raw_data_path}",
        f"HINT: {hint}",
        f"PARENT_PAGE: {parent_request_id}",
        "",
        "CRITICAL: DATA_FILE is provided. All market data has been pre-fetched.",
        "Do NOT call any MCP tools (get_basic_info, get_financials, recent_news, etc.).",
        "Read DATA_FILE and the skill file, then proceed directly to writing JSON output.",
        "",
        f"Follow CLAUDE.md (Parallel Mode). Use the {skill} skill.",
    ]
    return "\n".join(lines)


# ── Skill → worker config mapping (peer-comparison-deep handled separately) ───

_DD_WORKER_CONFIGS: dict[str, list[dict]] = {
    "news-timeline": [
        {"id": "news_a", "builder": build_dd_news_worker_alpha, "timeout": 90},
    ],
    "metric-drilldown": [
        {"id": "metric_a", "builder": build_dd_metric_worker_alpha, "timeout": 120},
        {"id": "metric_b", "builder": build_dd_metric_worker_beta, "timeout": 60},
    ],
    "business-breakdown": [
        {"id": "biz_a", "builder": build_dd_business_worker_alpha, "timeout": 90},
        {"id": "biz_b", "builder": build_dd_business_worker_beta, "timeout": 90},
    ],
    "valuation-deep": [
        {"id": "val_a", "builder": build_dd_valuation_worker_alpha, "timeout": 90},
        {"id": "val_b", "builder": build_dd_valuation_worker_beta, "timeout": 120},
        {"id": "val_c", "builder": build_dd_valuation_worker_gamma, "timeout": 90},
    ],
    # peer-comparison-deep handled by _run_peer_comparison_deep (2-batch)
}
