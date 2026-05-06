# Skill: news-timeline

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC` contains `news` or `recent_news`.

Parse `CLICKED_CONTEXT` for `stock_code`. Read `PARENT_PAGE` from
`session/page_stack.json` to get `stock_name`.

---

## Step 1 — Fetch data

Issue **all 3 calls simultaneously in one turn**. Tool servers cache results
to disk automatically — do not maintain `data_cache.json`.

| Tool call |
|---|
| `recent_news(code, days=30, limit=20)` |
| `recent_announcements(code, days=90)` |
| `analyst_consensus(code)` |

---

## Step 2 — Write output JSON

Sort all news + announcements by date descending. Group into ISO week buckets.

Use the **Write tool** to write a Python script `gen_json.py`, then run it:
```bash
python3 gen_json.py && rm gen_json.py && echo "DONE"
```
The script must use `json.dumps(data, ensure_ascii=False, indent=2)` and write to
`output/data-<REQUEST_ID>.json`.

**K-line chart:** the server fetches kline (3M) data directly from cache — do NOT
include a `kline_bars_3m` field in your JSON output.

### JSON schema

```json
{
  "meta": {"stock_code": "<code>", "stock_name": "<name>", "skill": "news-timeline", "as_of": "<ISO datetime>"},
  "hero": {"stock_code": "<code>", "stock_name": "<name>", "news_count": 0, "ann_count": 0},
  "timeline": [
    {"type": "news|ann", "date": "YYYY-MM-DD", "title": "<headline>", "url": "<or empty>", "source": "<outlet or 交易所公告>", "summary": "<1-2 sentences>"}
  ],
  "analyst": {
    "available": true,
    "buy_count": null, "neutral_count": null, "sell_count": null,
    "target_mean": null, "target_low": null, "target_high": null,
    "note": "<1 sentence, no recommendation>"
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
