# PASM 全生态关联图与说明

> 一句话：**一个引擎（私有）→ 两层开发基座（公开）→ 一组成品智能体（公开）→ 多种交付形态（平台/桌面/服务）**。
> 本文是这张网的全景图与逐层说明，用于回答「我现在要用/改/发哪个仓」。

---

## 一、全景图

```
                        ┌──────────────────────────────────────────┐
                        │           使用者 / 消费者                │
                        └──────────────────────────────────────────┘
        ┌───────────────┬───────────────┬──────────────┬──────────────┐
        │ 桌面应用      │ 浏览器/站点   │ AI 客户端    │ 平台智能体   │
        │ (普通人)      │ (任何人)      │ (WorkBuddy/  │ (Coze/       │
        │               │               │  Claude/     │  Character)  │
        │               │               │  Cursor)     │              │
        └───────┬───────┴───────┬───────┴──────┬───────┴──────┬───────┘
                │               │              │              │
        ┌───────▼───────┐ ┌─────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐
        │ pasm-qclaw    │ │ Web 壳     │ │ MCP 服务   │ │ 转译导入   │
        │ Studio 桌面版 │ │ (HTTP)     │ │ (stdio)    │ │ (人格+知识)│
        │ 安装包/升级   │ │            │ │            │ │  ⚠ 记忆不 │
        │               │ │            │ │            │ │    互通    │
        └───────┬───────┘ └─────┬──────┘ └─────┬──────┘ └────────────┘
                │               │              │
                └───────────────┴──────┬───────┘
                                       │  ← 交付形态层（同一批智能体，不同出口）
                        ┌──────────────▼──────────────┐
                        │      pasm-agents  (公开)     │  成品智能体
                        │  NpcAgent / ElderlyCompanion │
                        │  LearningTutor /             │
                        │  CustomerServiceAgent ★      │
                        │  + 8 个验证智能体            │
                        └──────────────┬──────────────┘
                                       │ 依赖
                        ┌──────────────▼──────────────┐
                        │    pasm-framework  (公开)    │  应用开发框架
                        │  BaseApplication / 插件子系统│
                        │  7 个内置插件（含知识库）    │
                        │  web_gateway / CLI / 脚手架  │
                        └──────────────┬──────────────┘
                                       │ 依赖
                        ┌──────────────▼──────────────┐
                        │    pasm-skills  (公开)       │  基座 / SDK
                        │  BaseAgent / AgentState      │
                        │  技能打包库 / 脚手架 / 教程  │
                        │  ★ 零运行时依赖，可独立降级  │
                        └──────────────┬──────────────┘
                                       │ 可选驱动（装上就升级档位）
                        ┌──────────────▼──────────────┐
                        │      PASM  (私有)            │  认知引擎核心
                        │  七层仿生 / 世界模型 /        │
                        │  记忆分层 / 情绪 PAD /       │
                        │  规划器 / 算子库 / IR        │
                        └──────────────────────────────┘

        侧翼服务层
        ┌──────────────────────────────────────────────────────────────┐
        │ pasm-mcp-server (公开)  给「任意」AI 客户端装长期记忆的 MCP 层│
        │ pasm-customer-service (公开) 专业客服系统（本仓）：DB→KB 连接器│
        │                              + 真 MCP 服务 + Web 壳 + Studio 场景│
        │ PASM-Lite (公开)        教学版 + 认知引擎协议参考实现          │
        └──────────────────────────────────────────────────────────────┘
```

**图例**：`★` = 2026-09-21 新增；`⚠` = 有明确能力损失，必须让使用者知道。

---

## 二、八个仓的职责与关系

| 仓 | 角色 | 可见性 | 版本 | 谁该用它 |
|---|---|---|---|---|
| **PASM** | 认知引擎核心（七层仿生、世界模型、记忆分层、情绪、规划器、算子库、IR 抽取） | **私有** | 0.7.2 | 只有你自己/核心开发 |
| **pasm-skills** | **基座**：`BaseAgent` + 状态 + 技能打包库 + 脚手架 + 教程 | 公开 | 0.5.2 | 想「自己写一个智能体」的人 |
| **pasm-framework** | **应用开发框架**：`BaseApplication` + 插件子系统（知识库/会话/温度/安全/web_gateway）+ CLI + 脚手架 | 公开 | 0.4.0 | 想「做一个能干活的 AI 应用」的人（如客服、问答、站点机器人） |
| **pasm-agents** | **成品智能体集**：4 个产品智能体 + 8 个验证智能体 + 5 个技能包 | 公开 | 0.5.0 | 想「直接拿去用」的人 |
| **pasm-mcp-server** | MCP 接入层：给任意 AI 客户端装长期记忆 | 公开 | 0.2.0 | 想让自己已有的 AI 客户端「记住事」的人 |
| **pasm-customer-service** | **专业客服系统**（本仓）：DB→KB 自生长连接器 + 真 stdio MCP 服务 + Web 壳 + Studio 场景 | 公开 | 0.2.0 | 想「让业务数据库自动长成客服资料库」的人 |
| **pasm-qclaw** | 桌面应用发行通道（PASM Studio 安装包 / 升级通道 / 镜像源码） | 公开 | 0.31.1 | 想「装个软件直接用」的普通人 |
| **PASM-Lite** | 教学版：认知引擎解剖 + 协议参考实现 | 公开 | — | 想「看懂内部怎么跑的」的人 |

### 三条最容易搞混的边界

1. **`pasm-skills` ≠ `pasm-agents`**
   - 前者是**基座**（`pip install pasm-skills` 后 `python -m pasm_skills list` 在干净环境里显示 **0 个**智能体）；
   - 后者是**成品**（`pip install pasm-agents` 后 4 个产品智能体经 entry points 自动被基座发现）。
   - 两仓**版本号刻意不对齐**（0.5.2 vs 0.5.0），因为依赖方向是单向的：agents → framework → skills。

2. **`BaseAgent` ≠ `BaseApplication`**
   - `BaseAgent`（基座）：记忆 / 情绪 / 动作池 / 反馈 / 持久化。**没有知识库**。
   - `BaseApplication`（框架）：**是 `BaseAgent` 的子类**，额外带插件子系统（知识库、会话、温度、安全、web_gateway）。
   - 判断口诀：**要「查资料作答」就用 `BaseApplication`；只要「有个性的人」就用 `BaseAgent`**。
   - 4 个产品里，**只有 `CustomerServiceAgent` 是 `BaseApplication` 血统**——因为它必须能查资料库。

3. **`pasm-customer-service` ≠ `pasm-agents` 里的 `CustomerServiceAgent`**
   - `pasm-agents` 里的是**智能体类**（重依赖：需要 `pasm-framework`）；
   - `pasm-customer-service` 是**一整套系统**（数据库连接器 + MCP 服务 + Web 壳 + Studio 场景 + 声明式规格），**且零运行时依赖**（只装它本身就能跑 CLI/Web/MCP，接真认知才需要 `pasm-framework`）。

---

## 三、三层依赖链（PyPI 发布顺序不可颠倒）

```
pasm-skills  ──→  pasm-framework  ──→  pasm-agents
  (基座)            (应用框架)           (成品)
  0.5.2             0.4.0                0.5.0
    │                  │                    │
    └── 零运行时依赖    └── 依赖 skills       └── 依赖 framework + skills
```

- **发布顺序**：`skills → framework → agents`。顺错会发出「装上装不上」的包（依赖解析失败）。
- **`PASM` 不在链上**：核心私有，对 `pasm-skills` 是**可选驱动**——装上就升档（`core`），没装就降级（`light`）并在 `tier` 如实标注。
- **`pasm-customer-service` 独立于这条链**：它自带连接器/MCP/Web，`pasm-framework` 是**可选**依赖（装了走真认知，没装走离线检索并诚实标注）。
- **版本比较别用字符串排序**：`"0.4.10" > "0.4.9"` 为假（Python 按字典序），必须按数字段比。

---

## 四、数据如何流动（以客服为例，最完整的一条链路）

```
 业务数据库 (MySQL/PostgreSQL/SQLite)
        │
        │  ① 增量拉取：WHERE updated_at > :cursor（只抓新增/变更）
        ▼
 pasm_cs/connector.py  ── 内容指纹去重（幂等）、指数退避重试
        │
        │  ② 转成 KB 条目 {title, content, source, tags}
        ▼
 ┌──────────────────┬────────────────────┐
 │ PasmKBSink       │ FileKBSink         │
 │ (真实 PASM 资料库)│ (JSONL 落盘)      │
 │ 装了 framework 时 │ 没装时（离线档）   │
 └────────┬─────────┴──────────┬─────────┘
          │                     │
          │                     └──→ Web 壳离线关键词检索（明确标注「离线模式」）
          ▼
  知识库插件 (knowledge_base)
        │
        │  ③ 检索：recall(query, k) → 打分 + 时间衰减(0.6+0.4×recency)
        ▼
  相关性闸门 select_knowledge()
        │   命中面规则（与分数无关，抗时间衰减）：问题词必须落在**标题或标签**上
        │   ★ 过不去 → 「没有查到」；过得去 → 就资料作答
        ▼
  CustomerServiceAgent
        │   ④ 温暖度 / 安全插件 / 会话记忆 / 客诉识别（→ 写标签记忆，闲聊挤不掉）
        ▼
  ┌──────────┬──────────┬──────────┬──────────┐
  │ cs_ask   │ cs_search_kb        │ Web 壳    │
  │ (MCP)    │ (MCP，平台模型组织语言)│ (浏览器) │
  └──────────┴──────────┴──────────┴──────────┘
```

**一个关键设计**：`tags` 是检索面。资料库插件**会丢掉 `category` 字段**，只保留 `tags`——
所以业务表的分类列必须**同时写进 `tag_col`**，否则资料同步进去了却检索不到（这正是
`agent_spec.toml` 里 `tag_col = "tags"` 与 `tag_col = "category"` 要写对的原因）。

---

## 五、交付形态 × 平台支持矩阵

| 目标平台 | 支持 MCP？ | 支持 SKILL.md？ | 我们能给的形态 | 数据在哪 | 能力损失 |
|---|---|---|---|---|---|
| **本机 WorkBuddy** | ✅ | ✅ | 技能包 + MCP 服务 | 本地 | 无 |
| **ClawHub** | ✅ | ✅ | 技能包 × 5 | 本地 | 无 |
| **Claude Desktop / Cursor / Codex** | ✅ | ✅ | MCP 服务（`cs_*` 工具） | 本地 | 无 |
| **skills.sh**（约 48 个运行时） | — | ✅ | 仓库内 `skills/<name>/SKILL.md` | 本地 | 无 |
| **Smithery / mcp.so / Glama / PulseMCP / 官方 MCP Registry** | ✅ | — | MCP 服务（元数据已备） | 本地 | 无 |
| **PASM Studio 桌面版** | — | — | 场景配置（`scenarios/*.json`） | 本地 | 无 |
| **任意网站** | — | — | Web 壳 `<iframe>` / REST | 你的服务器 | 无 |
| **Coze / 扣子** | ❌ | ❌ | 转译人格+知识 | **平台侧** | 记忆/情绪不互通 |
| **Character.AI** | ❌ | ❌ | 转译角色卡 | **平台侧** | 只剩人格，无资料库，会编造 |
| **Dify / FastGPT** | ❌ | ❌ | 当 PASM 的前端（HTTP 调 Web 壳） | 你的服务器 | 需自搭桥 |
| **ModelScope / 魔搭** | ❌ | 部分 | 技能包当资产上传 | 平台侧 | 运行环境不保证 |

> **判断口诀**：平台支持 MCP 或 SKILL.md → **直连，数据留本地**；
> 平台只问「角色设定写什么」→ **只能转译，记忆必丢**。

---

## 六、版本同频表（发版前对照）

| 组件 | 当前版本 | 真相源文件 | 发版动作 |
|---|---|---|---|
| PASM 引擎 | 0.7.2 | （私有） | 不进 PyPI |
| pasm-skills | 0.5.2 | `pyproject.toml` + `pasm_skills/__init__.py` | PyPI + 双端 tag |
| pasm-framework | 0.4.0 | `pyproject.toml` + `pasm_framework/__init__.py` | PyPI + 双端 tag |
| pasm-agents | 0.5.0 | `pyproject.toml` + `pasm_agents/__init__.py` | PyPI + 双端 tag + Release + 技能包 × 5 |
| pasm-mcp-server | 0.2.0 | `pyproject.toml` | PyPI |
| pasm-customer-service | 0.2.0 | `pyproject.toml` + `pasm_cs/__init__.py` | PyPI + 双端 tag |
| PASM Studio | 0.31.1 | `desktop/appinfo.py` 的 `APP_VERSION` | PyInstaller + Inno + 双端 Release + `latest.json` |

**四条铁律**：
1. 改版本号必须**同时改两处**（`pyproject.toml` 与包内 `__version__`），否则 PyPI 描述与运行时自报不一致。
2. **改完源码必须重建产物**，并核对**产物 mtime ≥ 源文件 mtime**——否则会拿旧产物验新代码、得出假结论。
3. PyPI 索引会滞后：验证新版本必须**断言 `__version__ == '<新版>'`**，不能只看 `pip install` 成功。
4. Release 正文里所有数量（产品数 / 技能数 / 插件数）都要跟代码实际对得上。

---

## 七、我想做某件事，该动哪个仓？

| 我想… | 动这个仓 | 具体位置 |
|---|---|---|
| 自己写一个「有个性会记忆」的智能体 | `pasm-skills` | `pasm_skills.sdk.BaseAgent` + `templates/` + `docs/BUILD-AGENT.md` |
| 做一个「能查资料作答」的 AI 应用（客服/问答/站点机器人） | `pasm-framework` | `BaseApplication` + 插件（`knowledge_base` / `web_gateway`） |
| 加一个框架插件（限流、审计、新数据源…） | `pasm-framework` | `pasm_framework/plugins/builtins/` 或配置内联 `class=` |
| 改客服业务逻辑 / 换数据源 / 换检索口径 | `pasm-customer-service` | `pasm_cs/connector.py` · `cs_agent.py` · `agent_spec.toml` |
| 让业务数据库自动喂给客服 | `pasm-customer-service` | `agent_spec.toml` 的 `[[agent.knowledge.sources]]` + `pasm-cs run` |
| 加一个新产品智能体 | `pasm-agents` | `agents/product/<name>/` + `pasm_agents/<name>.py` 转发层 + CLI + 守门登记 |
| 给任意 AI 客户端装长期记忆 | `pasm-mcp-server` | `pasm_mcp_server/` |
| 改桌面软件界面/能力 | `PASM`（`desktop/`，镜像到 `pasm-qclaw`） | ⚠ 遵守**分叉铁律**（同名模块只能别名导出） |
| 打包 / 发版桌面版 | `pasm-qclaw` | `tools/publish_release_multi.py` + `latest.json` |

---

## 八、相关文档

- 客服系统使用手册：[`USAGE.md`](./USAGE.md)
- 分发渠道与上架操作：[`DISTRIBUTION.md`](./DISTRIBUTION.md)
- 客服系统路线图：[`../PLAN.md`](../PLAN.md)
- 基座（自己写智能体）：`pasm-skills/docs/BUILD-AGENT.md`
- 框架（写应用/插件）：`pasm-framework/docs/`
