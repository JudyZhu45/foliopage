# Skill: capital-flow

## When to use

Use when `ACTION=drill_down` and `CLICKED_TOPIC=capital_flow`.

---

## Status: v0.2 (in development)

This skill is not yet implemented. Generate a single-section holding page:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>资金流向 — 开发中</title>
  <link rel="stylesheet" href="/static/foliopage.css">
</head>
<body>
  <section class="section" style="padding-top:3rem;text-align:center;">
    <p style="font-size:2.5rem;margin-bottom:.5rem;">🚧</p>
    <h2>资金流向 — v0.2 功能开发中</h2>
    <p class="narrative" style="max-width:480px;margin:1rem auto;">
      机构持仓变动、北向资金净流入、龙虎榜资金动向等功能计划于
      v0.2 版本上线。
    </p>
    <p class="data-as-of">当前版本：v0.1</p>
  </section>
  <footer>
    <p class="disclaimer">本页面由 AI 生成，仅供研究参考，不构成投资建议</p>
  </footer>
  <script src="/static/flipbook.js"></script>
</body>
</html>
```

Write this to `output/page-<REQUEST_ID>.html`, register in page_stack.json,
then print `PAGE_READY: output/page-<REQUEST_ID>.html`.
