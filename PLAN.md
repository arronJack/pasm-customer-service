# 专业客服系统 · 可执行开发计划

> 目标：用 PASM 做一个「有不同性格/情绪、有记忆、会成长、能根据业务接口/数据库
> 自动生长出资料库」的专业客服系统，并且**既能给开发者跑（命令/MCP），也能让
> 普通人直接用（Studio 场景 / 网页壳 / 平台导入）**。

---

## 0. 现状盘点（已具备，避免重复造）

| 能力 | 现有件 | 位置 |
|---|---|---|
| 客服应用骨架 | `CustomerServiceAgent`（KB/会话/温度/安全/可观测/可选LLM/网关） | `pasm-framework/apps/customer_service.py` |
| 知识摄取入口 | `BaseApplication.ingest` / `ingest_faq`（字段 `{title,content,source,tags}`） | `pasm_framework/application.py`、`plugins/builtins/knowledge_base.py` |
| 插件钩子链 | `on_init/on_message_in/on_retrieve/on_reply/on_reply_final/on_learn/on_shutdown` | `pasm_framework/plugins/core.py` |
| 本地/远程认知服务 | `pasm-mcp-server`（已把 `BaseAgent` 包成 MCP 工具 `pasm_context` 等） | `pasm-mcp-server/` |
| 网页嵌入 | `web_gateway` 插件（`<iframe>` + `POST /api/chat`） | `pasm_framework/plugins/builtins/web_gateway.py` |
| 情绪/记忆/反馈 | `BaseAgent.feel/feedback/mood/observe/recall` | `pasm_skills/sdk/base.py` |

**结论**：内核与「客服壳」都已齐备。真正缺的两块——**① DB→KB 自生长连接器**（原型已完成并深化）、**② 普通人零配置的使用入口**（Studio 场景配置生成器 + Web 壳已完成；Studio 真实「导入」UI 待加）。

---

## 1. 本次已交付的原型（`pasm-customer-service/`）

```
pasm-customer-service/
├── pasm_cs/
│   ├── connector.py          # ★核心：DB→KB 同步连接器（源/目的地可插拔，指纹去重，幂等）
│   │   ├─ DemoSource/CsvSource/SqlSource/SqliteSource/RestSource   # 五种数据源
│   │   ├─ FileKBSink（演示用）/ PasmKBSink（真·PASM 接入）
│   │   └─ DBKBSyncConnector.sync()  → SyncReport（指纹去重/幂等/增量游标）
│   ├── plugin.py             # 连接器插件骨架：backend_config 内联 class= 即注册
│   ├── cs_agent.py           # ★客服智能体统一入口（优先框架参考实现 / 本地等价回退）
│   ├── studio_loader.py      # Studio 场景配置生成器（对齐 persona/KB 字段）
│   ├── web_run.py            # 极简 Web 壳（普通人浏览器直接对话）
│   ├── agent_spec.toml       # 声明式规格：人格/知识源/能力/平台开关
│   ├── cli.py                # 命令：demo/validate/run/platform/studio/mcp/web
│   └── adapters/
│       ├── base.py           # AgentSpec 加载（tomllib，零依赖）
│       ├── mcp.py            # ★真·stdio MCP 服务：cs_ask/cs_search_kb/cs_ingest/cs_sync/cs_persona/cs_status
│       ├── coze.py           # → Coze / Character（转译导入）
│       └── web.py            # → 站点 <iframe> / REST
├── examples/products.csv     # 演示业务数据
├── examples/mcp_clients.json # MCP 客户端接入配置示例
├── studio_template.yaml      # Studio 场景模板清单（图形界面消费）
├── README.md
└── PLAN.md
```

**已验证（全部实跑通过）**：
- `demo` 幂等（二次 skipped=4/new=0）、**SQLite 增量**（首轮全量 4 → 次轮仅抓新增 1 → 三轮 0 新增幂等）；
- `run --source csv` 同步 6 条、`run --source sqlite --pasm` 真实灌库路径；
- `validate` 规格加载、`platform mcp|coze` 产出合法配置；
- `studio` 生成场景配置（对齐 Studio persona/KB 字段，落 `APPDATA/PASMStudio/scenarios/`）；
- `web --selftest` 离线关键词检索命中 + 无匹配回落；Web 壳 HTTP 端到端（GET / 返回聊天页、POST /api/chat 命中 FAQ、无匹配回落）均通过；
- `PasmKBSink` 适配（只传内核认识的字段）；
- **MCP 服务端到端（阶段三）**：以子进程跑 `python -m pasm_cs.adapters.mcp`、按真实客户端协议驱动 `initialize → tools/list → cs_status → cs_ingest → cs_search_kb → cs_ask → cs_sync`，全部通过；`cs_sync` 二次幂等（new=0）；framework 缺席时 `cs_ask` 诚实返回 `unavailable`、`cs_sync` 落 JSONL。
- **客服智能体双路径验证**：① 有框架仓库源码时用参考实现；② 模拟 `pip install`（`apps/` 不在包里）用本地等价实现均应答对；③ **无引擎**（只在 path 放 framework+skills）时降级到 `light` 档，KB/温度/安全仍工作。

---

## 2. 分阶段开发计划

### 阶段一 · 连接器深化（核心价值）— 原型核心已完成 ✅
- [x] **零依赖 SQLite 增量源**：新增 `SqliteSource`（标准库 sqlite3，无需装包即可演示真实增量），按 `updated_at` 游标 `WHERE > cursor` 只抓新增/变更，回写游标。
- [x] **增量而非全量**：`SqlSource`(sqlalchemy) 支持 `:cursor` 绑定透传；`SqliteSource` 默认增量；`DBKBSyncConnector.sync(full=)` 支持全量/增量切换 + 状态持久化。
- [x] **失败重试**：`_with_retry` 指数退避（连接抖动/超时），已作用于 SQL 源。
- [ ] **生产级 SQL 源**：`SqlSource` 扩 MySQL/PG 连接池、大表分批（当前单条 fetch 全结果集）。
- [ ] **字段映射可视化**：Studio 向导根据 CSV 表头自动建议 `title/content/tag` 列。
- [ ] **质量门**：内容为空/过短不入库；重复率超阈值告警（防脏数据灌爆资料库）。
- [ ] **同步异常进 `observability` 指标**（MCP 链路可观测）。
- 验收（原型已达成）：`demo` 中 SQLite 增量 4→1→0 通过；`run --source sqlite --pasm` 真实灌库路径通。

### 阶段二 · Studio 场景模板 + 普通人入口 — 配置生成器 + Web 壳已完成 ✅
> **重要边界**：当前 PASM Studio（`desktop/pasm_companion.py`）NAV 固定 9 项、**无外部场景导入入口**；workspace 仅按 7 分类目录组织。故「一键加载」需后续在桌面端加 UI（见下"待接入"）。
- [x] **Studio 场景配置生成器**：`studio_loader.py` 读 `agent_spec.toml` → 生成对齐 Studio persona/KB 字段的 `scenarios/<agent_id>.json`（落 `APPDATA/PASMStudio/scenarios/`），CLI `studio` 已验证。
- [x] **Web 壳（普通人浏览器直接用）**：`web_run.py` 极简 HTTP 服务（stdlib，零依赖），接真 PASM 认知（装了 pasm-framework）或离线关键词检索（未装时诚实标注）；GET / 聊天页、POST /api/chat 已端到端验证。
- [ ] **Studio 真实「导入场景」UI**（待接入）：在 `pasm_companion.py` 加 NAV 入口或技能页按钮，读 `scenarios/*.json` 实例化 `CustomerServiceAgent`。
- [ ] **数据源向导**：图形选 CSV/SQL/REST → 生成 `agent_spec.toml` 的 `knowledge.sources`。
- [ ] **一键启动网关**：模板默认开 `web_gateway`，生成 `<iframe>` 片段。
- [ ] **人格切换器**：内置 3 套 persona（温柔/专业/活泼）下拉切换。
- [ ] **本地模型默认**：模板默认走本地 Ollama（qwen2.5:7b），离线也能答。
- 验收（已达成雏形）：普通人跑 `python -m pasm_cs.web_run` → 浏览器打开即用；或管理员导入 Studio 场景后图形对话。

### 阶段三 · 多平台分发 — MCP 真·接线已完成 ✅
- [x] **MCP 真·接线（已落地并端到端验证）**：`pasm_cs/adapters/mcp.py` 实现**零依赖 stdio MCP 服务**（协议与 `pasm-mcp-server` 同款），暴露 `cs_ask` / `cs_search_kb` / `cs_ingest` / `cs_sync` / `cs_persona` / `cs_status`。子进程按真实客户端协议驱动全部通过。
  - 设计取向：**不扩展 `pasm-mcp-server` 的 `CognitiveBridge`**（那会引入跨仓耦合 + 让通用包依赖未发的原型），而是**在原型内自足实现**，复用连接器与 `CustomerServiceAgent`；`pasm-mcp-server` 仍是通用认知服务（`pasm_*` 工具），二者可同时挂载。
- [x] **客服智能体自足化**：新增 `pasm_cs/cs_agent.py`，修掉「直连 `pasm_framework.apps` 必崩」的隐患（`apps/` 未打包）；`pip install pasm-framework` 即可跑，无引擎自动降级 `light`。
- [ ] **Web 部署**：容器化 + 公网域名，提供 `public_token` 访客挂件（已有双令牌机制）。
- [ ] **Coze/Character 转译**：`adapters/coze.py` 已出骨架，补「导出知识文件包」并写导入指引。
- [ ] **打包/发布**：本原型目前**未打 `pyproject.toml`、未入 git**；要 `pip install`/发布须先补包定义（见「6. 发布与依赖现状」）。
- 验收（MCP 部分已达成）：MCP 客户端配置 `pasm-cs` 后，用平台 LLM 经 `cs_*` 直接对话、PASM 提供资料库/记忆/人格，数据留本地。

### 阶段四 · 企业级（多用户场景）
- [ ] **多租户隔离**：每个客户/商家独立 KB 与记忆（`agent_id` 维度隔离，`web_gateway` 按租户路由）。
- [ ] **鉴权与审计**：`web_gateway` 接入 API Key / 登录态；对话与 ingest 留痕。
- [ ] **批量部署**：一套模板，N 个商家各一份数据，互不可见。
- 验收：同一套系统服务 10 个商家，资料库与记忆零串扰。

---

## 3. 平台分发策略（回答「发布到那些平台能否直接跑」）

| 平台 | 能否直接跑 PASM 智能体 | 怎么做 |
|---|---|---|
| **本地命令** | ✅ 是 | `python -m pasm_cs.cli run --pasm`（开发者） |
| **PASM Studio** | 🟡 配置已生成（真实一键加载需改桌面端 NAV） | `studio` 命令生成 `scenarios/*.json`；接入 UI 见阶段二"待接入" |
| **WorkBuddy / ClawHub** | ✅ 是（MCP 兼容，**已打通**） | 平台 LLM 经 `pasm_cs.adapters.mcp`（或通用 `pasm-mcp-server`）远程调用你的实例，**数据留在你这** |
| **Claude Desktop / Cursor** | ✅ 是（MCP 兼容） | 同 MCP，配置 `mcpServers` 指向你的实例 |
| **网页壳 / 挂件** | ✅ 是 | `web_run.py`（自带 HTTP 壳）或 `web_gateway` 的 `<iframe>` / REST，嵌任意网站 |
| **Coze** | ⚠️ 部分（需转译重建） | 用 `adapters/coze.py` 导出「人格+知识+插件」配置，在 Coze 内重建；**PASM 记忆/情绪无法跨平台**，语言与运行时归 Coze |
| **Character.ai** | ⚠️ 部分（需转译重建） | 同上，转译 persona 卡片 |

**关键认知**：WorkBuddy/ClawHub 这类 **MCP 原生**平台，能直接调用你自托管的 PASM
智能体（平台出 LLM，PASM 出认知），是「大众直接用」的最优路径；Coze/Character 不是
MCP，只能把你的**人格与知识**转译后在其平台重建，认知状态不互通。所以要「共用于大众」，
首选 **MCP 路线 + Web 壳/Studio 路线**。

---

## 4. 连接器插件骨架（已写，注册方式）

无需发包，内联即可把连接器挂进客服应用：

```python
from pasm_framework import SimpleApplication
from pasm_cs.plugin import DBKBSyncPlugin

app = SimpleApplication("shop-cs", {"name": "小智", "role": "客服"},
    backend_config={
        "knowledge_base": {"enabled": True, "config": {"kb_dir": "./kb"}},
        "db_kb_sync": {"enabled": True, "class": DBKBSyncPlugin,
                       "config": {"source": "csv",
                                  "path": "examples/products.csv",
                                  "interval_seconds": 0,   # >0 后台周期同步
                                  "state_path": "examples/connector_state.json"}},
    })
# 手动触发：app.plugins.get("db_kb_sync").sync_now()
```

---

## 5. 风险与边界
- **PASM 当前是单机本地架构**，做企业多用户需补多租户隔离（阶段四）。
- **Coze/Character 无法共享 PASM 记忆/情绪**——这是平台封闭性决定的，不是技术缺陷；要保留完整认知请用 MCP 路线。
- **连接器增量同步依赖业务表有可靠时间戳/主键**，否则只能全量+指纹去重（已支持）。
- **Studio 真实「导入场景」入口尚未实现**（桌面端 NAV 固定 9 项）；`studio_loader` 已产出对齐格式的配置文件，接入只需在桌面端加一个读 `scenarios/*.json` 并实例化 `CustomerServiceAgent` 的 UI。

---

## 6. 发布与依赖现状（回答「PyPI / 已发布智能体 / 各平台是否要重发」）

### 6.1 三个 PyPI 包与 mcp-server：**本地 = PyPI，无需更新**
| 包 | 本地版本 | PyPI 版本 | 本地工作树 | 结论 |
|---|---|---|---|---|
| pasm-skills | 0.5.2 | 0.5.2（2026-09-20） | clean | **无需更新** |
| pasm-framework | 0.4.0 | 0.4.0（2026-09-20） | clean | **无需更新** |
| pasm-agents | 0.4.11 | 0.4.11（2026-09-20） | clean | **无需更新** |
| pasm-mcp-server | 0.2.0 | 0.2.0（2026-09-15） | clean | **无需更新** |

本次改动的对象是**尚未发布的原型 `pasm-customer-service`**，四个已发布包**一行未改**。
因此：**PyPI 不需要更新**。

### 6.2 唯一发现的真问题：`pasm-framework` 的 `apps/` 未打包
- `pasm-framework/pyproject.toml`：`packages = ["pasm_framework", "pasm_framework.plugins", "pasm_framework.plugins.builtins"]`，**不含 `apps`**。
- 后果：`from pasm_framework.apps.customer_service import CustomerServiceAgent` 在源码与 `pip install` 下**都会失败**（原型原 `web_run.py`/`cli.py` 因此存在隐患，之前只跑过离线路径未暴露）。
- **已在原型侧修掉**（`pasm_cs/cs_agent.py`：优先框架参考实现，否则本地等价实现，只需已发布的 `BaseApplication`）。
- **若想让下游都能 `from pasm_framework.apps...` 导入**，需改框架：把 `apps` 加进 `packages`（或在 `pasm-agents` 里把客服固化为一个**产品智能体**）。这属于**框架/成品层变更 → 需要发新版本**（如 `pasm-framework 0.4.1` 或 `pasm-agents 0.5.0`）。**是否做由你定**；不做也不影响本原型运行。

### 6.3 已发布的智能体（NpcAgent / ElderlyCompanion / LearningTutor + 验证智能体）
- 它们**未被改动**，PyPI 上的 `pasm-agents 0.4.11` 即最新 → **无需重新生成、无需重发**。
- 客服系统是**新增**能力，不属于已发布的三个产品智能体；要不要把它固化成第 4 个产品智能体（进 `pasm-agents`）另行决定。

### 6.4 各平台是否需要「重新发布」
| 平台 | 是否需要重发 | 说明 |
|---|---|---|
| **PyPI** | ❌ 不需要 | 本地=线上、四包 clean；除非决定改框架 `apps` 打包（则发 `pasm-framework 0.4.1`） |
| **WorkBuddy 开放平台** | ❌ 现有技能/智能体无需重发 | 若要把**客服系统**作为新技能上架，才需要新发一次（且需先补 `pyproject.toml`） |
| **ClawHub** | ❌ 现有物无需重发 | 同上；MCP 形态一般走「客户端配置」而非上架 |
| **Character.ai** | ❌ 非必需 | 非 MCP，只能转译 persona 卡片；想做才做 |
| **Coze** | ❌ 非必需 | 非 MCP，只能转译机器人配置；想做才做 |

**一句话**：本次只动了未发布的新原型 ⇒ **PyPI 与已发布智能体都不用动**；
**ClawHub / WorkBuddy / Character / Coze 也不必重发**。
真正要做的决策只有一个：**要不要把客服系统的 MCP 能力正式化**（补 `pyproject.toml` + 入 git，
可选：进 `pasm-agents` 或发 PyPI / 上架 WorkBuddy&ClawHub）。
