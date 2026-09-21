# PASM 专业客服系统 · 功能说明与使用手册

> 面向**第一次接触本项目**的人：读完这一篇，你能从零把它跑起来、接到自己的业务数据上、
> 并选一种形态交付给最终用户（开发者 / 图形界面用户 / 普通网民 / 平台大模型）。
>
> 分发与上架操作（ClawHub / WorkBuddy / skills.sh / MCP Registry …）见
> [`DISTRIBUTION.md`](DISTRIBUTION.md)；设计取舍与路线图见 [`../PLAN.md`](../PLAN.md)。

---

## 一、这是什么

一个**有性格、有情绪、有记忆、能随业务数据自动生长资料库**的客服智能体。

和"调一个大模型接口 + 挂个提示词"的常见做法相比，它多出三件东西：

| 能力 | 说明 | 为什么重要 |
|---|---|---|
| **资料库（KB）** | 业务数据（CSV / SQL / REST）经连接器变成可检索的知识条目 | 客服答的是**你的业务事实**，不是模型的通用常识 |
| **自生长** | 连接器按 `updated_at` 游标**增量**同步，业务库改了它跟着变 | 上新/改价/改政策不用重新训练、不用手工维护 |
| **人格与记忆** | persona（name/role/tone/temper/energy/play）+ 会话记忆 | 同一个问题，不同客户得到的是**同一个"人"**在回答 |

还有一条底线：**查不到就如实说查不到，绝不编造**。客服答错内容比答不上来严重得多，
所以检索有一道"相关性闸门"（详见第五节）。

---

## 二、30 秒上手

### 方式 A：pip 安装（推荐给使用者）

```bash
pip install pasm-customer-service
pasm-cs demo          # 看到 DB→KB 同步链路跑通
pasm-cs web           # 起浏览器聊天壳，打开 http://127.0.0.1:8080
```

**零运行时依赖**——标准库实现，装完即用，不需要先装 PASM 引擎。

### 方式 B：源码运行（推荐给二次开发者）

```bash
git clone https://gitee.com/arronzheng/pasm-customer-service   # 或 GitHub: arronJack
cd pasm-customer-service
python -m pasm_cs.cli demo
python -m pasm_cs.cli web --selftest    # 先自检，不启服务
```

### 两个档位（重要）

| 环境 | 能力 | 表现 |
|---|---|---|
| **未装 `pasm-framework`** | 离线关键词检索 | 从已同步的资料库 JSONL 里找最相关条目，并**明确标注"离线模式"**——不假装智能 |
| **装了 `pasm-framework`** | 真实 PASM 认知 | 记忆 / 情绪 / 人格渲染 / 可选 LLM 对话 |

```bash
pip install pasm-framework      # 想升级到真实认知时再装
pasm-cs web --pasm              # 用真实认知起服务
```

> 装了框架但**不装引擎**也在工作——会自动降到 `light` 档，资料库/温度/安全策略照常生效。
> 引擎（`PASM` 核心仓）是私有的，属可选依赖。

---

## 三、功能说明（能力矩阵）

### 3.1 一份规格，多处运行

核心是根目录的 **`agent_spec.toml`**——人格、知识源、能力、平台开关全在这里，
改配置不用改代码：

```toml
[agent]
id = "shop-cs"

[agent.persona]          # 直接对应 BaseAgent 的 persona 字段
name = "小智"
role = "智能客服"
tone = "温暖、专业、耐心"
temper = 0.6             # 主动性 0~1
energy = 0.5             # 活跃度 0~1
play = 0.4               # 俏皮度 0~1

[[agent.knowledge.sources]]
type = "csv"             # demo / csv / sqlite / sql / rest
path = "examples/products.csv"
title_col = "title"
content_col = "description"
source_name = "products"

[agent.knowledge.sync]
interval_seconds = 0     # >0 后台周期同步；0 = 只注册、手动触发
state_path = "examples/connector_state.json"
```

改完先校验：

```bash
pasm-cs validate
```

### 3.2 DB→KB 同步连接器

把业务数据变成资料库条目 `{title, content, source, tags}`，特性三条：
**按内容指纹去重**、**可断点续传**、**幂等**（重复跑不产生重复知识）。

| 数据源类 | 用途 | 依赖 |
|---|---|---|
| `DemoSource` | 内置演示数据，保证开箱即跑 | 无 |
| `CsvSource` | CSV 文件 | 无 |
| `SqliteSource` | **SQLite 增量同步** | 无（标准库 `sqlite3`） |
| `SqlSource` | 生产数据库（MySQL/PG/…） | `sqlalchemy` |
| `RestSource` | HTTP JSON 接口 | 无 |

目的地两类：`FileKBSink`（落 JSONL，便于检查和离线检索）、`PasmKBSink`（灌进真实资料库）。

```python
from pasm_cs.connector import DBKBSyncConnector, CsvSource, PasmKBSink
from pasm_cs.cs_agent import build_cs_agent          # ★ 统一入口

cs = build_cs_agent("shop-cs", kb_dir="./kb")
conn = DBKBSyncConnector(CsvSource("examples/products.csv"), PasmKBSink(cs),
                         state_path="examples/connector_state.json")
print(conn.sync())        # → SyncReport(fetched=6, new=6, skipped=0, cursor=...)
```

真实增量同步（零依赖，可直接看效果）：

```bash
pasm-cs run --source sqlite        # 首轮全量
#   ↑ 业务方在库里 INSERT 一条新 FAQ
pasm-cs run --source sqlite        # 只抓新增，不重复旧数据
pasm-cs run --source sqlite        # 无变化 → new=0（幂等）
pasm-cs run --source sqlite --full # 忽略游标，全量重跑
```

SQLite / SQL 增量的游标列默认是 `updated_at`，SQL 里需自带 `WHERE updated_at > :cursor`：

```python
from pasm_cs.connector import SqlSource
SqlSource("mysql+pymysql://user:pw@host/db",
          "SELECT id,title,body,category,updated_at FROM faq WHERE updated_at > :cursor",
          updated_at_col="updated_at")
```

> 连接抖动/超时有**指数退避重试**；"表不存在"这类确定性错误不重试，直接给可读错误。

### 3.3 客服智能体（`cs_agent`）

| 方法 | 作用 |
|---|---|
| `ask(text)` | 就资料作答（带来源），查不到如实说 |
| `ingest([...])` | 写入知识（`{title, content, source, tags}`） |
| `kb_stats()` | 资料库规模 |
| `needs_escalation(text)` | 是否应转人工，返回原因标签 |

**四类客诉会自动识别并转人工**：`投诉/曝光`、`法律/监管`、`安全/伤害`、`要求赔偿`。
识别到的原因写进**标签记忆**——不会被后续闲聊挤掉。

```python
from pasm_agents import CustomerServiceAgent          # 或 from pasm_cs.cs_agent import build_cs_agent
cs = CustomerServiceAgent("shop-cs")
cs.ingest([{"title": "退换货政策", "content": "签收 7 天内无理由退货，生鲜除外。",
            "source": "faq", "tags": ["退货"]}])
print(cs.answer("怎么退货？"))                        # 就资料作答
print(cs.answer("你们能送到火星吗？"))                 # 如实说查不到
print(cs.needs_escalation("我要起诉你们"))            # → "法律/监管"
```

> **两种来源怎么选**：`pip install pasm-customer-service` 得到的是**完整系统**
> （连接器 + MCP + Web + Studio 场景 + CLI）；`pip install pasm-agents` 的第 4 个产品
> `CustomerServiceAgent` 是**轻量智能体**（只要个"会答客服话"的类时用）。

### 3.4 资料库按智能体隔离

`pasm-framework` 的 `knowledge_base` 插件**默认落点是全机共享的**
`~/.pasm_framework/kb/kb.jsonl`。不隔离会导致**跨智能体串库**，多租户场景直接泄漏。
本系统在产品层强制按实例隔离（`<persist_dir>/kb`）——这是内置行为，无需配置。

---

## 四、四种交付形态（逐步上手）

选哪个，取决于"最终用户是谁"：

| 用户画像 | 用哪种形态 | 入口 |
|---|---|---|
| 开发者 / 运维 | 本地 CLI | `pasm-cs demo / run / serve` |
| 完全不懂技术的人 | **Web 壳**（浏览器） | `pasm-cs web` |
| 习惯图形界面的人 | **PASM Studio 场景** | `pasm-cs studio` → Studio 导入 |
| 已有 MCP 客户端的团队 | **MCP 服务** | `pasm-cs mcp` |

### 4.1 本地 CLI（开发者）

```bash
pasm-cs demo                      # 内置数据演示同步链路（幂等）
pasm-cs validate                  # 校验 agent_spec.toml
pasm-cs run --source sqlite       # 同步知识源（--pasm 可直灌真实资料库）
pasm-cs platform mcp              # 导出某平台的接入配置
pasm-cs studio                    # 生成 Studio 场景配置
pasm-cs mcp --selftest            # MCP 服务自检
pasm-cs web --selftest            # Web 壳自检
```

真实输出（`pasm-cs demo` + 增量三连）：

![CLI 真实输出](images/cli_demo.png)

> 截图里 `new=4 → new=1 → new=0` 就是增量同步与幂等的实证：业务库新增一条只抓一条，
> 无变化时零新增。

### 4.2 Web 壳（给完全不懂技术的人）

```bash
pasm-cs web                       # http://0.0.0.0:8080
pasm-cs web --host 127.0.0.1      # 只允许本机访问
pasm-cs web --port 9000
pasm-cs web --kb my_kb.jsonl      # 指定资料库
pasm-cs web --pasm                # 接真实 PASM 认知（需 pasm-framework）
```

把地址发给同事/客户，浏览器打开就能对话——**不需要装任何东西**。
服务用多线程（`ThreadingHTTPServer`），一个慢问答不会堵住其他访客。

![Web 壳真实对话](images/web_chat.png)

> 截图里两次回答都是**真实检索结果**：问"退货"命中退换货政策条目；
> 问"生鲜"命中同一条目并给出"生鲜除外"的限定。命中不了会明确告诉你查不到。

**部署提示**：
- `--host 0.0.0.0` 对局域网开放；仅本机自用请加 `--host 127.0.0.1`。
- 公网部署请放在反向代理（Nginx/Caddy）后面并加 HTTPS。
- 要"站点挂件 + 管理台 + 访客令牌"这套完整能力，用 `pasm-cs serve`
  （走 `pasm-framework` 的 `web_gateway` 插件，含 `token`/`public_token` 双令牌、限流、`/embed.js`）。

### 4.3 PASM Studio 场景（图形界面用户）

```bash
pasm-cs studio
# 产出：%APPDATA%/PASMStudio/scenarios/shop-cs.json
#（若设了 PASM_STUDIO_DIR 则跟随它 —— 与 Studio 数据同源）
```

然后在 **PASM Studio ≥ 0.31.2 → 设置 → 📦 场景** 点导入：

![Studio 场景导入页](images/studio_scene.png)

导入后：**人格写进「基本」页，知识源灌进资料库**，一键可跑。
生成的配置对齐 Studio 真实字段（persona 的 name/role/tone/temper/energy/play、
知识源的 type/path/abs_path/url/source_name）。

> 为什么这样设计：Studio 左栏 NAV 是固定 9 项（对话/任务/工作台/自动化/资料库/记忆/技能/团队/工作流），
> 加"外部场景导入"最合适的位置是设置面板——不动 NAV、不影响既有页面归属。

### 4.4 MCP 服务（给已有 MCP 客户端的团队）

**这是"让平台大模型直接用上你的 PASM"的最优路径**——数据留在你的实例，不上传平台。

```bash
pasm-cs mcp                       # 或 python -m pasm_cs.adapters.mcp
pasm-cs mcp --persist-dir ./data  # 指定落盘根目录（默认 ~/.pasm-cs-mcp）
```

客户端配置（WorkBuddy / Claude Desktop / Cursor / ClawHub 通用，见 `examples/mcp_clients.json`）：

```json
{ "mcpServers": { "pasm-cs": {
    "command": "python", "args": ["-m", "pasm_cs.adapters.mcp"] } } }
```

暴露 **6 个工具**：

| 工具 | 参数 | 做什么 |
|---|---|---|
| `cs_ask` | `text`* · session_id · user_id · agent_id | 直接回答（含人格渲染） |
| `cs_search_kb` | `query`* · k · agent_id | **只检索**，返回条目+打分，让平台模型自己组织语言 |
| `cs_ingest` | `title`* · content · source · tags · category | 写入一条知识 |
| `cs_sync` | source · full · agent_id | 跑一次 DB→KB 增量同步 |
| `cs_persona` | persona · agent_id | 查看 / 合并式更新人格 |
| `cs_status` | agent_id | 后端可用性、资料库规模、已加载智能体 |

> **`cs_search_kb` 比 `cs_ask` 更值得优先用**：PASM 出"认知与资料"，
> 平台大模型出"语言表达"，各展所长。

**分级降级是设计的一部分**：未装 `pasm-framework` 时，`cs_ask`/`cs_search_kb`/`cs_ingest`/`cs_persona`
会**诚实返回"不可用"**（而不是假装成功），`cs_sync` 则落到 JSONL 仍然可用。

### 4.5 Coze / Character（转译导入）

这两个平台**不支持 MCP**，只能把人格和知识导出来、在平台内重建：

```bash
pasm-cs platform coze          # 或 platform character
```

⚠️ **明确的边界**：转译后 PASM 的记忆与情绪**不互通**，等于在平台里重新养一个。
能接受这个代价再做。

---

## 五、两个设计要点（使用者会问到的）

### 5.1 为什么"答错"比"答不上来"更难接受

资料库检索的打分是 `重叠词 × 字段权重 + 精确率`，且**带时间衰减**（`0.6 + 0.4×recency`）。
这意味着：

- 绝对分数会随资料变老而自然下降 → **不能拿绝对阈值当"查不到"的判据**，否则老库会随时间"失忆"。
- 纯词重叠会让"CEO 的私人邮箱是多少"因为命中"邮箱"二字而匹配到**发票开具**条目 → **答非所问**。

所以主判据是**与分数无关的"命中面"规则**：命中词必须落在**标题或标签**上才算数。
实测分离度：真命中最低 **6.00**、假命中最高 **2.29**。

### 5.2 资料库隔离

见 3.4。一句话：不给 `kb_dir` 就会串库，本系统已在产品层强制隔离。

---

## 六、常见问题

**Q：装完能跑，但回答是"[离线模式]…"？**
A：这是**如实标注**——你还没装 `pasm-framework`，它在用离线关键词检索。
想升级成真实认知：`pip install pasm-framework`，然后加 `--pasm`。

**Q：`pasm-cs web` 起来了，同事打不开？**
A：默认 `--host 0.0.0.0` 已对局域网开放，但对方要用**你的内网 IP**（不是 `127.0.0.1`），
并确认防火墙放行该端口。

**Q：`pasm-cs run --source sqlite` 第一次就显示 `new=0`？**
A：说明游标状态文件里已有进度（之前跑过）。想看完整全量，先删
`examples/connector_state__sqlite.json`，或直接加 `--full`。

**Q：资料库文件在哪？**
A：`FileKBSink` 落 JSONL（默认 `examples/*.jsonl`）；真实认知用 `PasmKBSink`，
落 `<persist_dir>/kb/kb.jsonl`（按智能体隔离）。MCP 模式的默认根目录是 `~/.pasm-cs-mcp`。

**Q：能接到我自己的数据库吗？**
A：能。用 `SqlSource`（需 `pip install sqlalchemy` + 对应驱动），
SQL 里带 `WHERE updated_at > :cursor` 即可增量；改 `agent_spec.toml` 的
`knowledge.sources` 声明它，之后 `pasm-cs run --source sql`。

**Q：想改人格 / 换个开场风格？**
A：改 `agent_spec.toml` 的 `[agent.persona]`（或 MCP 调 `cs_persona`），
`temper` 调主动性、`play` 调俏皮度。

**Q：`pasm-cs serve` 报"需要 pasm-framework"？**
A：`serve` 走的是框架的 `web_gateway` 插件（站点挂件 + 管理台 + 双令牌），
是唯一**硬依赖**框架的形态。没有框架时请用 `pasm-cs web`。

---

## 七、自检与验证

```bash
pasm-cs demo                  # 内置链路（含幂等断言）
pasm-cs validate              # 规格合法性
pasm-cs mcp --selftest        # MCP 工具 + 离线降级路径
pasm-cs web --selftest        # 检索命中 + 无匹配回落 + --pasm 诚实降级
python tools/selfcheck.py     # 全项目一键自检（36 项）
```

`tools/selfcheck.py` 是本仓库的一键体检入口，也是改代码后最快的回归手段。

---

## 八、相关仓库与文档

| 文档 | 内容 |
|---|---|
| [`../README.md`](../README.md) | 快速开始与命令速查 |
| [`../PLAN.md`](../PLAN.md) | 设计取舍、阶段进度、发布现状 |
| [`DISTRIBUTION.md`](DISTRIBUTION.md) | 已发布渠道 + 其他可分发平台清单与操作路径 |
| [`../pasm_cs/agent_spec.toml`](../pasm_cs/agent_spec.toml) | 声明式规格（带注释） |

生态关系：`pasm-skills`(基座) → `pasm-framework`(应用框架) → 本仓(客服系统)，
成品智能体另见 `pasm-agents`。
