# 分发渠道清单（哪些平台能推、怎么推）

> 结论先说：**PASM 的智能体有两种可被平台直接消费的形态 ——「MCP 服务」和「技能包（SKILL.md）」**。
> 凡是支持这两种形态中任意一种的平台，都能**直接跑你的 PASM**（记忆/情绪/资料库留在你自己这边）；
> 两者都不支持的平台（Coze / Character.AI），只能**转译重建**，PASM 的记忆与情绪不互通。

本文按「现在能不能做」分三档。**截至 2026-09-21 的实测状态**。

---

## A 档 · 已上线（无需再做什么）

| 渠道 | 形态 | 状态 | 证据 |
|---|---|---|---|
| **PyPI** | Python 包 | ✅ `pasm-customer-service 0.2.0` | `pip install pasm-customer-service` |
| **ClawHub** | 技能包 × 5 | ✅ 已提交（`arronjack/pasm-*`） | `npx clawhub@latest inspect arronjack/pasm-cs-agent` |
| **本机 WorkBuddy** | 技能包 × 5 | ✅ `~/.workbuddy/skills/pasm-*` v0.5.0 | 逐字节 sha256 与源包一致 |

---

## B 档 · 一处小动作即可上（推荐优先做）

### B1. `skills.sh` —— 一次提交覆盖约 48 个 agent 运行时 ★性价比最高

- **它是什么**：跨运行时的技能索引。它按**仓库目录结构**自动发现技能，装到 Claude Code / Cursor / Codex / WorkBuddy 等约 48 个支持 `SKILL.md` 的运行时。
- **我们已具备**：本仓上游 `pasm-agents` 已生成仓库内 `skills/<name>/SKILL.md`（5 个），实测 `npx skills@latest add <repo> --list` **能列出全部 5 个**。
- **要做的**：把 `pasm-agents` 的仓库地址提交给它（或直接让用户用 `npx skills@latest add arronJack/pasm-agents` 自取）。**无需改代码。**

### B2. Smithery —— MCP 生态里最像「Docker Hub」的目录（7000+ server）

- **要什么**：仓库根放 `smithery.yaml` + `.mcp.json`（**两个都要，只放前者会被扫描器判失败**），然后到 `smithery.ai` → Submit server。
- **我们已具备**：`smithery.yaml` 与 `.mcp.json` 已放进本仓根目录。Python 包按 `uvx` 拉起。
- **阻塞点**：需要网页提交（登录）。

### B3. `mcp.so` —— 社区目录（19000+ server）

- **要什么**：提交 GitHub issue 或网页表单，填**公开仓库 URL + 名字**即可；有付费加速通道（可选）。
- **阻塞点**：需网页/issue 提交。无所有权校验，门槛最低。

### B4. Glama —— 元注册中心（Anthropic / GitHub / PulseMCP / Microsoft 维护）

- **要什么**：站上点「Add Server」，提交公开 GitHub 仓库；若要求归属校验则补 `glama.json`。
- **我们已具备**：`glama.json` 已放进本仓根目录。

### B5. PulseMCP

- **要什么**：站上 Submit 流程，需提供公开仓库、安装命令、**工具清单**、鉴权变量、许可证、维护者联系方式。
- 我们的 6 个 `cs_*` 工具清单现成（见 `docs/USAGE.md`）。
- **注意**：它**不发布稳定的提交 schema**，提交时以当时的表单为准。

### B6. `awesome-mcp-servers`（GitHub PR）

- **要什么**：先有 Glama 条目 → fork `punkpeye/awesome-mcp-servers` → 在合适分类里按字母序加一行 → 提 PR。

### B7. 官方 MCP Registry（`registry.modelcontextprotocol.io`）

- **要什么**：`server.json`（本仓根目录已备好）+ `mcp-publisher` CLI：
  ```bash
  npx mcp-publisher@latest login     # 证明 io.github.<user>/ 命名空间归属
  npx mcp-publisher@latest validate  # 校验 server.json
  npx mcp-publisher@latest publish
  ```
- **PyPI 包的所有权校验方式（关键）**：注册中心会去**包的 README（即 PyPI 页面描述）**里找
  `mcp-name: <server.json 里的 name>` 字符串。**可以用 HTML 注释藏起来**，但值必须逐字一致。
  本仓 README 顶部已写入 `<!-- mcp-name: io.github.arronjack/pasm-customer-service -->`。
  ⚠️ **这一标记要生效，必须重新发一次 PyPI**（README 变更随包走描述）。
- **阻塞点**：`login` 默认走 GitHub device flow，本机网络对 `github.com/login/device` 不可达。
  需要能访问该域名，或改用域名归属校验（需自有域名）。

### B8. 其它可顺手登记的目录

`mcpservers.org`、`MCP Central`、`mcp-marketplace.io`、`MCPMarket.com`（社区目录，10k+）、
Cursor Marketplace（需 `plugin.json`，且需公开 Git 仓 + README）。
**登记时统一用同一份元数据**（同名 / 同描述 / 同仓库 / 同许可证 / 同工具清单），否则版本与安全通告会各自漂移。

---

## C 档 · 只能转译重建（PASM 记忆/情绪不互通）

| 平台 | 为什么不通用 | 我们能给什么 | 代价 |
|---|---|---|---|
| **Coze / 扣子** | 非 MCP，插件与知识库格式私有 | `pasm-cs platform coze` 导出**人格 + 知识条目**，在平台内重建 | 记忆/情绪/资料库不在 PASM，**不共享** |
| **Character.AI** | 只吃角色卡（persona），无工具调用、无知识库 | `pasm-cs platform character` 导出角色卡 | 只剩人格，**没有资料库**，会「编造」 |
| **Dify / FastGPT** | 无状态工作流平台，非 MCP 原生 | 可作 PASM 的**前端**，通过 HTTP 调 PASM 的 Web 壳 | 需自己搭桥；Dify 侧只当 UI |
| **ModelScope / 魔搭** | 模型为主，智能体托管形态与 PASM 不同 | 可把技能包当资产上传 | 运行环境不保证 |

> **判断口诀**：平台问「你支持 MCP 吗」→ 支持就能直连（数据留本地）；
> 平台只问「角色设定写什么」→ 就只能转译（记忆必丢）。

---

## 本仓已备好的上架元数据

| 文件 | 给谁用 | 说明 |
|---|---|---|
| `server.json` | 官方 MCP Registry | 含 `pypi` 包类型 + `stdio` 传输 + `uvx` 运行提示 |
| `smithery.yaml` | Smithery | 元数据（类别/许可证/仓库） |
| `.mcp.json` | Smithery 扫描器 + 各 MCP 客户端 | **真正被用来拉起服务的就是这份** |
| `glama.json` | Glama | 维护者归属 |
| `README.md` 顶部 `mcp-name:` | 官方 MCP Registry | PyPI 所有权校验标记（可藏在 HTML 注释里） |

**上架前务必先本地自检**，否则上架了也是坏服务：

```bash
pip install pasm-customer-service
pasm-cs mcp --selftest     # 协议 + 离线降级 + 参数校验，不启服务
pasm-cs web --selftest     # Web 壳对话逻辑
pasm-cs validate           # 声明式规格
```

---

## 推荐动作顺序

1. **`skills.sh`** —— 零改动、覆盖面最大（48 个运行时），先做这个。
2. **官方 MCP Registry** —— 顺手把 `mcp-name:` 标记随下次 PyPI 发版带上，然后 `mcp-publisher publish`。
3. **Smithery + mcp.so + Glama** —— 三个网页提交，元数据都已备好，一次做完。
4. **PulseMCP + awesome-mcp-servers PR** —— 锦上添花。
5. **Coze / Character** —— 只有明确需要面向那边的用户时才做，且**要接受记忆不互通**。
