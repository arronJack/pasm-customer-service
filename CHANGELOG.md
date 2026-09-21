# Changelog

本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.2.0] — 2026-09-21

> 主题：**把「答非所问」当成缺陷来修**，并把分发链路补齐到可上架。

### 新增
- **相关性闸门**（`pasm_cs.select_knowledge` / `semantic_tokens` / `retrieval_surface` /
  `touches_surface`）：客服「答错」比「答不上来」更严重。闸门要求命中必须落在**标题或标签**上，
  与分数无关 —— 因为 kb 打分带 `0.6+0.4×recency` 时间衰减，用绝对阈值会让老资料库随时间"失忆"。
  实测：真命中最低 6.00 / 假命中最高 2.29，两者太近，绝对阈值分不开。
- **统一资料库路径 `pasm_cs/paths.py`**：此前 `cli run` 默认写 `examples/run_kb.jsonl`，
  而 Web 壳读 `examples/sqlite_kb.jsonl` —— 同步完打开 Web 壳却看不到任何资料。现在同源。
- **分发元数据**：`server.json`（官方 MCP Registry）+ `smithery.yaml` + `.mcp.json` + `glama.json`，
  以及 README 顶部的 `mcp-name:` 所有权标记。
- **文档**：`docs/USAGE.md`（四种形态逐步上手，含真实截图）、`docs/DISTRIBUTION.md`
  （三档分发渠道与上架操作）、`docs/ECOSYSTEM.md`（八仓全生态关联图与说明）。
- **真实效果截图**：`docs/images/{cli_demo,web_chat,studio_scene}.png`（真跑产物，非示意图）。
- **反向验证工具** `tools/falsify_checks.py`：注入缺陷 → 确认自检抓得住 → 还原。

### 修复
- **`DemoSource` 自建了一份演示数据副本**（单源违规），且标签只有分类名、没有同义词 →
  开箱即跑的那条路径检索命中率最差。改为直接复用 `demo_data`。
- **演示数据标签补齐同义词**：`退换货政策` 的标签从 `["售后"]` 扩为
  `["退货","换货","售后","退款","生鲜"]` 等 —— 因为**检索面就是标签**，标签太窄则
  用户换个说法就问不出来。
- **`agent_spec.toml` 的 `tag_col` 写错**：sqlite 源原写 `category_col` 当检索面，但
  框架的资料库**只接受 `tags`、会丢掉 `category`** → 资料同步进去了却检索不到。
- **Web 壳的离线检索也接上闸门**：此前离线模式下问「CEO 的私人邮箱」会拿"发票"条目作答。
- `examples/products.csv` 与 `examples/cs_demo.db` 改为从 `demo_data` 单源重建，
  避免两份数据各自漂移。

### 变更
- `-kb` 产物路径统一为 `examples/kb.jsonl`（原 `run_kb.jsonl` / `sqlite_kb.jsonl` 合并）。
- `cli._demo` 不再自建数据源，改为走 `agent_spec.toml` 的 `knowledge.sources`（规格即真相源）。

## [0.1.0] — 2026-09-21

- 首个版本：DB→KB 同步连接器（CSV/SQL/REST/SQLite，内容指纹去重、增量游标、指数退避重试）、
  声明式规格 `agent_spec.toml`、真 stdio MCP 服务（6 个 `cs_*` 工具）、零依赖 Web 壳、
  Studio 场景生成器、自足化智能体入口 `build_cs_agent`（`pip install pasm-framework` 即可跑）。
