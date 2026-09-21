## v0.2.0 —— 把「答非所问」当成缺陷来修，并把分发链路补齐到可上架

> 这是本仓**第一个正式 Release**（v0.1.0 仅发布到 PyPI）。
> 装它：`pip install pasm-customer-service`

### 为什么发这一版：修一个**产品级缺陷**

v0.1.0 上线后发现客服会**答非所问**：问「请问 CEO 的私人邮箱是多少」时，资料库用「邮箱」
二字命中了**发票开具**条目，于是拿发票内容作答。
客服场景里 **答错比答不上来更严重** —— 这一版的核心就是把这个闸门补上。

### 新增

- **相关性闸门**（`select_knowledge` / `semantic_tokens` / `retrieval_surface` / `touches_surface`）
  —— 命中必须落在**标题或标签**上，与分数无关。
  **为什么不直接用分数阈值**：kb 打分带 `0.6 + 0.4 × recency` 时间衰减，用绝对阈值会让
  老资料库随时间「失忆」。实测真命中最低 **6.00** / 假命中最高 **2.29**，两者太近，绝对阈值分不开。
- **统一资料库路径 `pasm_cs/paths.py`**：此前 `cli run` 默认写 `examples/run_kb.jsonl`，
  而 Web 壳读 `examples/sqlite_kb.jsonl` —— 同步完打开 Web 壳却看不到资料。现已同源。
- **分发元数据**：`server.json`（官方 MCP Registry）+ `smithery.yaml` + `.mcp.json` + `glama.json`，
  以及 README 顶部的 `mcp-name:` 所有权标记。
- **文档三件套**：
  - [`docs/USAGE.md`](https://gitee.com/arronzheng/pasm-customer-service/blob/master/docs/USAGE.md)
    —— 四种形态（CLI / Web 壳 / Studio 场景 / MCP）逐步上手，含**真实截图**；
  - [`docs/DISTRIBUTION.md`](https://gitee.com/arronzheng/pasm-customer-service/blob/master/docs/DISTRIBUTION.md)
    —— 三档分发渠道与上架操作；
  - [`docs/ECOSYSTEM.md`](https://gitee.com/arronzheng/pasm-customer-service/blob/master/docs/ECOSYSTEM.md)
    —— 八仓全生态关联图与说明。
- **真实效果截图**：`docs/images/{cli_demo,web_chat,studio_scene}.png`（真跑产物，非示意图）。
- **反向验证工具** `tools/falsify_checks.py`：注入缺陷 → 确认自检抓得住 → 还原。

### 修复

- **`DemoSource` 自建了一份演示数据副本**（单源违规），且标签只有分类名、没有同义词 →
  开箱即跑的那条路径命中率最差。改为直接复用 `demo_data`。
- **演示数据标签补齐同义词**：`退换货政策` 的标签从 `["售后"]` 扩为
  `["退货","换货","售后","退款","生鲜"]` —— 因为**检索面就是标签**，标签太窄则用户换个说法就问不出来。
- **`agent_spec.toml` 的 `tag_col` 写错**：sqlite 源原把 `category_col` 当检索面，但框架资料库
  **只接受 `tags`、会丢掉 `category`** → 资料同步进去了却检索不到。
- **Web 壳离线检索接上同一闸门**：此前离线模式下问「CEO 的私人邮箱」也会拿「发票」条目作答。
- `examples/products.csv` 与 `examples/cs_demo.db` 改为从 `demo_data` 单源重建。

### 变更

- KB 产物路径统一为 `examples/kb.jsonl`（原 `run_kb.jsonl` / `sqlite_kb.jsonl` 合并）。
- `cli._demo` 不再自建数据源，改为走 `agent_spec.toml` 的 `knowledge.sources`（规格即真相源）。

### 验证

- `tools/selfcheck.py` 全绿，含新增的 `check_relevance_gate()`：**「CEO 私人邮箱」必须答不上来、
  「退货」必须答得上来**；反向用 `tools/falsify_checks.py` 证明「改坏了确实抓得住」。
- 干净虚拟环境验证公开安装：`pip install pasm-customer-service==0.2.0` 后断言
  `pasm_cs.__version__ == "0.2.0"`（PyPI 索引滞后时会**静默装上旧版**，只看「装成功」会得出假结论）。

### 附件说明

`.whl` / `.tar.gz` 是**离线装机用**的发行产物，从 `git archive HEAD` 解包构建，
保证「产物 == 已提交的 tag」。在线安装请仍走 PyPI：

```bash
pip install pasm-customer-service          # 只装
pip install "pasm-customer-service[pasm]"  # 接真 PASM 认知（资料库/记忆/情绪）
```

**核心运行时零第三方依赖**，装完即可 `pasm-cs demo` 跑通。
