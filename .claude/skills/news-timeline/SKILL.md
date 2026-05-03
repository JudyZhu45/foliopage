# Skill: news-timeline

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC` contains `news` or `recent_news`.

Parse `CLICKED_CONTEXT` for `stock_code`. Read `PARENT_PAGE` from
`session/page_stack.json` to get `stock_name`.

---

## Step 1 — Fetch data

Issue **all 4 calls simultaneously in one turn**. Tool servers cache results
to disk automatically — do not maintain `data_cache.json`.

| Tool call |
|---|
| `recent_news(code, days=30, limit=20)` |
| `recent_announcements(code, days=90)` |
| `analyst_consensus(code)` |
| `get_kline(code, range="3M")` |

---

## Step 2 — Write output JSON

Sort all news + announcements by date descending. Group into ISO week buckets.
Write to `output/data-<REQUEST_ID>.json` using Bash + json.dumps.

**`kline_bars_3m`**: copy the full `bars` array from `get_kline()` verbatim —
the server uses it to render the compact price strip chart.

### JSON schema

```json
{
  "meta": {
    "stock_code": "<code>",
    "stock_name": "<name>",
    "skill": "news-timeline",
    "as_of": "<ISO datetime>"
  },
  "hero": {
    "stock_code": "<code>",
    "stock_name": "<name>",
    "news_count": <int>,
    "ann_count": <int>
  },
  "kline_bars_3m": [
    {"date": "YYYY-MM-DD", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "volume": 0}
  ],
  "timeline": [
    {
      "type": "news",
      "date": "YYYY-MM-DD",
      "title": "<headline>",
      "url": "<source URL or empty string>",
      "source": "<outlet name>",
      "summary": "<1-2 sentences>"
    },
    {
      "type": "ann",
      "date": "YYYY-MM-DD",
      "title": "<announcement title>",
      "url": "",
      "source": "交易所公告",
      "summary": "<brief summary>"
    }
  ],
  "analyst": {
    "available": <true|false>,
    "buy_count": <int or null>,
    "neutral_count": <int or null>,
    "sell_count": <int or null>,
    "target_mean": <float or null>,
    "target_low": <float or null>,
    "target_high": <float or null>,
    "note": "<1 sentence: what the consensus reflects, no recommendation>"
  }
}
```

---

## Step 3 — Register and complete

1. Append to `session/page_stack.json`:
   ```json
   {
     "request_id": "<REQUEST_ID>",
     "action": "drill_down",
     "title": "<name> (<code>) 近期舆情",
     "stock_code": "<code>",
     "stock_name": "<name>",
     "skill_used": "news-timeline",
     "summary": "30-day news + 90-day announcements timeline with price strip",
     "data_keys_used": ["kline:<code>:3M"],
     "parent_request_id": "<from CLICKED_CONTEXT or page_stack>",
     "created_at": "<ISO datetime>"
   }
   ```

2. Print **exactly** this line, then stop:
   ```
   PAGE_READY: output/data-<REQUEST_ID>.json
   ```
