# Foliopage

[English →](README.md)

> 浏览器内的本地优先股票研究工具，由你自己的 Claude Code 订阅驱动。

输入股票名称或代码，得到一份**完整的、自包含的** HTML 研究页 — K 线、关键指标、估值、同行对比、新闻动态。每个指标和同行公司都是链接，点击即时生成下一页。

无 SaaS 账号、无 API key、无流式输出。页面在本地完整生成后整体返回。

---

## Demo

```bash
$ make dev
# 打开 http://localhost:8000
# 输入：贵州茅台
# 首次冷启动等 5–10 分钟
# → 自包含 HTML：K 线图、14 个 KPI、5 年财务、
#   同行表格、新闻时间线、深入研究卡片
# 点击任意同行 / 指标 → 自动生成下一页
```

30 分钟内重复相同查询会在 100ms 内命中页面缓存秒回；研究同行业其他股票时，基础信息、同行列表、K 线数据通过磁盘缓存复用，用时 3–5 分钟。

---

## 快速开始

**前置依赖**：Python 3.11+、[uv](https://docs.astral.sh/uv/)、有效的 [Claude Code](https://claude.ai/code) 订阅（确认 `claude --version` 能跑通）。

```bash
git clone https://github.com/JudyZhu45/foliopage.git
cd foliopage

# 安装依赖并为本机生成 .mcp.json
make install

# 启动服务
make dev
```

打开 [http://localhost:8000](http://localhost:8000) 输入股票名称或代码。

### 支持的查询方式

| 类型      | 示例           |
|-----------|----------------|
| A 股名称  | `贵州茅台`     |
| A 股代码  | `600519`       |
| 美股代码  | `AAPL`         |
| 美股名称  | `Apple`        |

A 股数据来自 akshare（新浪 / 上交所 / 深交所 / 东方财富）。美股数据来自 yfinance + akshare 的美股端点。

---

## 架构

```
浏览器 (index.html / report.html)
        │ HTTP POST /api/generate
        ▼
┌─────────────────────────────┐
│  Orchestrator (FastAPI)     │  orchestrator/server.py
│  • 页面级 HTML 缓存          │
│  • 会话管理                  │
│  • 并发信号量                │
│  • 实时进度 endpoint         │
└───────────────┬─────────────┘
                │ 子进程：claude -p
                ▼
┌─────────────────────────────┐
│  研究 Agent                  │  claude CLI（你本地的订阅）
│  • 读 CLAUDE.md             │
│  • 调用 MCP 工具             │
│  • 写出 data-<id>.json      │
└──────┬────────┬─────────────┘
       │ stdio  │ stdio
   ┌───┘    ┌───┘
   ▼        ▼
stock_mcp  chart_mcp  news_mcp  cache_mcp
(akshare,  (matplotlib (akshare, (SQLite KV，
 yfinance)  → SVG)      feedparser) ~/.foliopage/cache.db)
```

agent 输出结构化 JSON，orchestrator 服务端用 Python 渲染成 HTML，并把 SVG 图表内联进去。**agent 不写 HTML**。

完整设计思路见 [`docs/architecture.md`](docs/architecture.md)。

---

## 配置

所有设置走环境变量（或仓库根目录下的 `.env`）。

| 环境变量                       | 默认值                           | 说明                                |
|--------------------------------|----------------------------------|-------------------------------------|
| `FOLIOPAGE_HOST`               | `127.0.0.1`                      | 绑定地址                            |
| `FOLIOPAGE_PORT`               | `8000`                           | 端口                                |
| `FOLIOPAGE_MAX_CONCURRENT`     | `3`                              | 并发 agent 数上限                   |
| `FOLIOPAGE_AGENT_TIMEOUT`      | `1800`                           | agent 超时（秒）                    |
| `FOLIOPAGE_PAGE_CACHE_TTL`     | `1800`                           | 页面缓存 TTL（秒，0 = 禁用）        |
| `FOLIOPAGE_PAGE_CACHE_ROOT`    | `~/.foliopage/page_cache`        | 页面缓存目录                        |
| `FOLIOPAGE_SESSION_ROOT`       | `~/.foliopage/sessions`          | 会话工作区根目录                    |
| `FOLIOPAGE_CACHE_DB`           | `~/.foliopage/cache.db`          | SQLite 缓存路径（多 MCP 共享）      |
| `FOLIOPAGE_LOG_LEVEL`          | `INFO`                           | 日志级别                            |
| `FOLIOPAGE_CLAUDE_BIN`         | `claude`                         | Claude CLI 可执行文件路径           |

---

## 性能

| 场景                                              | 典型耗时 |
|---------------------------------------------------|----------|
| 冷启动首次研究（无任何缓存）                      | 5–10 分钟 |
| 30 分钟内相同查询                                 | < 100 ms（页面缓存命中） |
| 同行业其他股票（同行复用磁盘缓存）                | 3–5 分钟 |
| Drill-down（估值三角、同行对比等）                | 2–5 分钟 |

瓶颈分析与优化历史见 [`docs/perf-profile.md`](docs/perf-profile.md)。

---

## 可靠性

agent 调的是免费上游数据源（akshare、yfinance、Google News RSS），会偶尔触发限流或静默断连。orchestrator 做了对应处理：

- **60 秒 socket 超时**：所有上游调用强制超时。否则 TCP 连接被接受但永不响应时会让 worker 永远等下去。
- **东方财富熔断器**：EM 第一次失败后，3 分钟内所有 EM 调用直接 fail-fast，避免 8 个并发请求各自跑完 retry budget 浪费时间。其他数据源（新浪 / 上交所 / 深交所 / yfinance）继续工作，页面以降级模式渲染（如行业字段为空、同行列表为空，但其他部分正常）。
- **实时进度展示**：研究进行中，loading card 会显示 agent 当前 phase、已完成 / 进行中的工具调用列表、七日窗口 rate-limit 警告、距上次事件多久（超过 30 秒变红）。
- **前端自救**：如果 `uvicorn --reload` 在长任务中途杀掉了 `/api/generate` 的 worker（开发模式常见），前端 polling 检测到 `status=done` 时会直接从 session 加载已生成的页面，不会卡在永远 pending 的 fetch 上。

---

## 故障排查

**页面一直转圈**

- 看 loading card 里的进度块 — 已完成工具数、距上次事件多久、是否触发 rate-limit。如果「UPDATED 60s+ AGO」持续标红几分钟，agent 才是真卡了。
- agent transcript 在 `~/.foliopage/sessions/<sess_id>/logs/transcript.jsonl`。
- 全新股票首次研究最长可能到 10 分钟。

**`claude: command not found`**

确认 Claude CLI 已装且在 `PATH` 上：

```bash
which claude
claude --version
```

**`Error: virtual environment not found`**

先 `make install` 再 `make dev`。

**`make test` 报 import 错误**

跑 `uv sync --all-extras` 装齐 dev 依赖再重试。

**显示「数据暂不可用」**

上游返错或 EM 熔断器触发。页面会按可用数据渲染；几分钟后熔断恢复再重试，或点其他数据源仍健康的指标 drill-down。

---

## 免责声明

Foliopage 生成的所有研究页面均由 AI 模型生成，仅供信息参考和研究用途，**不构成任何投资建议**。任何投资决定前请通过权威渠道核实数据。

---

## Roadmap

| 版本 | 目标 |
|------|------|
| v0.1（当前） | 端到端管线，纯本地，JSON 渲染 |
| v0.2 | 资金流向 / 情绪分析 / 事件时间线 三个 drill-down |
| v0.3 | 后台任务队列 + 浏览器通知 |
| v0.4 | 自选股 / 持仓覆盖视图 |

---

## License

MIT — 见 [`LICENSE`](LICENSE)。

---

## 致谢

- [akshare](https://akshare.akfamily.xyz/) — 免费 A 股和 ETF 数据
- [yfinance](https://github.com/ranaroussi/yfinance) — 美股数据
- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server 框架
- [Claude Code](https://claude.ai/code) — 跑研究的 agent
