"""MCP 适配器（面向 WorkBuddy / ClawHub / Claude Desktop 等 MCP 兼容客户端）。

把专业客服智能体（``CustomerServiceAgent``）通过 MCP 暴露出来，让普通人在
WorkBuddy / ClawHub / Claude 里**直接远程调用你的 PASM 实例**——平台出大模型，
PASM 出「资料库 + 记忆 + 情绪 + 温度」，数据留在你本地。这正是比纯云端平台更强的护城河。

暴露的工具（``cs_*`` 命名空间）
------------------------------
  · ``cs_ask``       直接回答一个客户问题（KB + 温度 + 可选 LLM）。
  · ``cs_search_kb`` 只检索资料库，返回命中条目，让你的模型自己组织回复
                    （适合「PASM 出认知、平台出语言」的高级用法）。
  · ``cs_ingest``    新增 / 补充一条知识（FAQ / 文档）。
  · ``cs_sync``      跑一次 DB→KB 增量同步（复用 ``pasm_cs.connector``）。
  · ``cs_persona``   查看 / 微调客服人格。
  · ``cs_status``    后端可用性 / 资料库规模 / 会话数。

协议：零依赖实现 stdio 上的 JSON-RPC 2.0（与 ``pasm-mcp-server`` 同款协议），
启动快、可被任意语言客户端拉起。**未装 ``pasm-framework`` 时**，
``cs_ask`` / ``cs_search_kb`` / ``cs_ingest`` / ``cs_persona`` 会**诚实说明需要后端**；
``cs_sync`` / ``cs_status`` 仍可正常运行（sync 落到 JSONL，便于检查同步结果）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import __version__  # noqa: F401  保证版本号单一来源
from ..connector import (  # noqa: F401
    DBKBSyncConnector, FileKBSink, PasmKBSink, ConnectorError,
)
from ..source_factory import make_source_for
from .base import AgentSpec, load_spec

# 本地开发逃生口：把 pasm-framework 仓库根挂到 PYTHONPATH，免安装即可联调。
_FRAMEWORK_PATH = os.environ.get("PASM_FRAMEWORK_PATH")
if _FRAMEWORK_PATH:
    sys.path.insert(0, _FRAMEWORK_PATH)


# ============================================================ 协议层（零依赖）
SERVER_NAME = "pasm-cs-mcp"
SERVER_VERSION = __version__

SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2026-07-28")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
CAPABILITIES = {"tools": {}}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _negotiate(client_version: Optional[str]) -> str:
    if client_version and client_version in SUPPORTED_PROTOCOL_VERSIONS:
        return client_version
    return DEFAULT_PROTOCOL_VERSION


def _initialize_result(client_version: Optional[str]) -> Dict[str, Any]:
    return {
        "protocolVersion": _negotiate(client_version),
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "capabilities": CAPABILITIES,
        "instructions": (
            "PASM 专业客服智能体：提供资料库检索、DB→KB 自生长同步、记忆、情绪与温度。"
            "典型用法：先 cs_search_kb 检索资料库，再据命中条目组织回复；"
            "有新知识就 cs_ingest 写进去；业务数据变化就 cs_sync 增量同步。"
            "cs_ask 则可直接给出基于资料库的回复。"
        ),
    }


def _error_response(req_id, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def _result_response(req_id, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _log(msg: str) -> None:
    if os.environ.get("PASM_CS_MCP_QUIET") == "1":
        return
    print("[pasm-cs-mcp] %s" % msg, file=sys.stderr, flush=True)


def _write(out, obj: Dict[str, Any]) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    out.write(data)
    out.flush()


# ============================================================ 智能体桥
def _make_agent(agent_id: str, persona: Optional[Dict[str, Any]],
                persist_root: Path) -> Optional[Any]:
    """构造一个客服智能体；pasm-framework 不可用时返回 None（工具降级并诚实说明）。"""
    try:
        from ..cs_agent import build_cs_agent
    except Exception as ex:  # pragma: no cover
        _log("无法导入 cs_agent：%s" % ex)
        return None
    kb_dir = str(persist_root / ("%s_kb" % agent_id))
    pdir = str(persist_root / agent_id)
    try:
        return build_cs_agent(agent_id, persona=persona,
                              kb_dir=kb_dir, persist_dir=pdir)
    except Exception as ex:  # pragma: no cover —— 取决于运行环境
        _log("构造客服智能体失败：%s" % ex)
        return None


class CsAgentBridge:
    """按 agent_id 管理 CustomerServiceAgent 实例（跨调用共享 KB / 会话 / 记忆）。"""

    def __init__(self, persist_root: Optional[str | Path] = None):
        root = persist_root or os.environ.get("PASM_CS_PERSIST_DIR")
        self.persist_root = Path(root) if root else (Path.home() / ".pasm-cs-mcp")
        self.persist_root.mkdir(parents=True, exist_ok=True)
        self._agents: Dict[str, Any] = {}
        # 负缓存：构造失败（如未装 pasm-framework）只记一次，避免每次调用都
        # 重复 import 探测 + 往 stderr 刷同一行日志。
        self._failed: Dict[str, str] = {}
        try:
            self.spec: Optional[AgentSpec] = load_spec()
        except Exception:
            self.spec = None
        self._default_persona = (self.spec.persona if self.spec
                                 else {"name": "小智", "role": "智能客服",
                                       "tone": "温暖、专业、耐心",
                                       "temper": 0.6, "energy": 0.5, "play": 0.4})

    def get(self, agent_id: str = "default",
            persona: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        if agent_id in self._agents:
            return self._agents[agent_id]
        if agent_id in self._failed:
            return None
        p = dict(self._default_persona)
        if persona:
            p.update(persona)
        ag = _make_agent(agent_id, p, self.persist_root)
        if ag is None:
            self._failed[agent_id] = "pasm-framework 不可用"
            return None
        self._agents[agent_id] = ag
        return ag

    def last_error(self, agent_id: str = "default") -> str:
        return self._failed.get(agent_id, "")

    def agent_ids(self) -> List[str]:
        return sorted(self._agents.keys())

    def save_all(self) -> List[str]:
        saved = []
        for aid, ag in self._agents.items():
            try:
                ag.save()
                saved.append(aid)
            except Exception:
                pass
        return saved


# ============================================================ 工具实现
def _as_int(value: Any, default: int, lo: int, hi: int, name: str) -> int:
    """把工具入参里的可选整数**先校验**再使用。

    这些可选参数（k / 条数）原先放在「后端是否可用」的早返回之后，
    于是 ``cs_search_kb(k="abc")`` 在未装框架时会被误报成「需要 pasm-framework」，
    真正的原因（参数类型错）被吞掉。现在统一先校验，报错信息才指向真问题。
    """
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s 必须是整数，收到 %r" % (name, value))
    return max(lo, min(hi, n))


def _as_str_list(value: Any, name: str) -> List[str]:
    """把 tags 归一到字符串列表；标量/逗号串也接受（LLM 客户端常这么传）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(t).strip() for t in value if str(t).strip()]
    raise ValueError("%s 必须是字符串数组，收到 %r" % (name, value))


def tool_cs_ask(args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    """直接回答一个客户问题：检索资料库 → （可选 LLM）→ 温暖回复。"""
    text = str(args.get("text") or "").strip()
    if not text:                      # 参数校验先行——与后端是否可用无关
        raise ValueError("text 不能为空")
    aid = str(args.get("agent_id") or "default")
    agent = bridge.get(aid)
    if agent is None:
        return {
            "agent_id": aid, "ok": False, "backend": "unavailable", "reply": None,
            "error": "未安装 pasm-framework（pip install pasm-framework），无法运行客服智能体。",
            "hint": "装好并重启 MCP 服务后，cs_ask 将基于资料库+记忆+情绪回答。",
        }
    session_id = str(args.get("session_id") or "default")
    reply = agent.ask(text, session_id=session_id, user_id=args.get("user_id"))
    return {"agent_id": agent.agent_id, "session_id": session_id,
            "reply": reply, "backend": "cs-agent", "ok": True}


def tool_cs_search_kb(args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    """检索资料库，返回命中条目（标题/摘要/标签/来源/打分）——让平台模型组织回复。"""
    query = str(args.get("query") or "").strip()
    if not query:                     # 参数校验先行
        raise ValueError("query 不能为空")
    k = _as_int(args.get("k"), 5, 1, 50, "k")   # 可选参数也先行校验
    aid = str(args.get("agent_id") or "default")
    agent = bridge.get(aid)
    if agent is None:
        return {"agent_id": aid, "ok": False,
                "error": "需要 pasm-framework 才能检索资料库。",
                "hint": bridge.last_error(aid),
                "hits": []}
    kb = agent.plugins.get("knowledge_base") if hasattr(agent, "plugins") else None
    hits = kb.recall(query, k=k) if kb else []
    return {"agent_id": aid, "query": query, "count": len(hits), "hits": hits, "ok": True}


def tool_cs_ingest(args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    """新增 / 补充一条知识（FAQ / 文档），写进客服资料库。"""
    title = str(args.get("title") or "").strip()
    if not title:                     # 参数校验先行
        raise ValueError("title 不能为空")
    tags = _as_str_list(args.get("tags"), "tags")   # 可选参数也先行校验
    aid = str(args.get("agent_id") or "default")
    agent = bridge.get(aid)
    if agent is None:
        return {"agent_id": aid, "ok": False,
                "error": "需要 pasm-framework 才能写入资料库。",
                "hint": bridge.last_error(aid), "ingested": 0}
    item = {
        "title": title,
        "content": str(args.get("content") or ""),
        "source": str(args.get("source") or "manual"),
        "tags": tags,
        "category": str(args.get("category") or "manual"),
    }
    n = agent.ingest([item])
    try:
        agent.save()
    except Exception:
        pass
    return {"agent_id": aid, "ingested": n, "ok": True}


def tool_cs_sync(args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    """跑一次 DB→KB 增量同步。有后端时灌进客服资料库，否则落到 JSONL。"""
    aid = str(args.get("agent_id") or "default")
    source_type = args.get("source") or None
    if source_type is not None:
        source_type = str(source_type).strip().lower()
    full = bool(args.get("full", False))

    # 源构造收敛到 source_factory（与 CLI / Web 同一份实现）
    src, actual_type = make_source_for(bridge.spec, source_type)

    agent = bridge.get(aid)
    if agent is not None:
        sink: object = PasmKBSink(agent)
        target = "agent_kb"
    else:
        sink = FileKBSink(str(bridge.persist_root / ("%s_kb.jsonl" % aid)))
        target = "jsonl"

    # 状态文件落在 persist_root，避免依赖 CWD；且**按源类型分名**，
    # 否则"先同步 csv 再同步 sqlite"会共用游标/指纹而误判 skipped。
    spec_state = bridge.spec.sync_state_path if bridge.spec else None
    base = Path(spec_state).stem if spec_state else "sync_state"
    state_path = str(bridge.persist_root / ("%s__%s.json" % (base, actual_type)))

    conn = DBKBSyncConnector(src, sink, state_path=state_path)
    rep = conn.sync(full=full)
    return {
        "agent_id": aid, "source_type": actual_type, "target": target,
        "fetched": rep.fetched, "new": rep.new, "skipped": rep.skipped,
        "cursor": rep.cursor, "elapsed": round(rep.elapsed, 3), "ok": True,
    }


def tool_cs_persona(args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    """查看 / （合并式）更新客服人格。"""
    patch = args.get("persona")
    if patch is not None and not isinstance(patch, dict):
        raise ValueError("persona 必须是对象")       # 参数校验先行
    aid = str(args.get("agent_id") or "default")
    agent = bridge.get(aid)
    if agent is None:
        return {"agent_id": aid, "ok": False,
                "error": "需要 pasm-framework 才能读取/修改人格。",
                "hint": bridge.last_error(aid), "persona": None}
    if patch:
        if hasattr(agent, "set_persona"):
            agent.set_persona(patch)
        else:
            try:
                agent.persona.update(patch)  # type: ignore[union-attr]
            except Exception:
                pass
        try:
            agent.save()
        except Exception:
            pass
    return {"agent_id": aid, "persona": dict(agent.persona),  # type: ignore[union-attr]
            "updated": bool(patch), "ok": True}


def tool_cs_status(args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    """状态快照：后端可用性 / 资料库规模 / 已加载智能体。"""
    aid = str(args.get("agent_id") or "default")
    agent = bridge.get(aid)
    backend_present = agent is not None
    # 「装了 pasm-framework」与「成功构造出智能体」是两件事：前者是安装事实，
    # 后者可能因配置/依赖异常失败。分开报告，避免把构造失败误报成"没装"。
    try:
        from ..cs_agent import framework_available
        installed = framework_available()
    except Exception:  # noqa: BLE001
        installed = False
    info: Dict[str, Any] = {
        "agent_id": aid,
        "pasm_framework_installed": installed,
        "agent_ready": backend_present,
        "loaded_agents": bridge.agent_ids(),
        "spec_loaded": bridge.spec is not None,
    }
    if agent is not None:
        kb = agent.plugins.get("knowledge_base") if hasattr(agent, "plugins") else None
        info["kb"] = kb.stats() if kb else None
        info["persona"] = dict(agent.persona)  # type: ignore[union-attr]
    else:
        info["error"] = bridge.last_error(aid) or "智能体未就绪"
        info["hint"] = ("未安装 pasm-framework：cs_ask/cs_search_kb/cs_ingest/cs_persona "
                        "暂不可用；cs_sync 会落到 JSONL。装好并重启即可启用完整客服能力。")
    return info


# ============================================================ 注册表
ToolFn = Callable[[Dict[str, Any], CsAgentBridge], Dict[str, Any]]

CS_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "cs_ask",
        "description": (
            "直接回答一个客户问题。基于已同步的资料库检索相关说明，"
            "由客服智能体（含温度/情绪渲染，可选 LLM）给出回复；"
            "查不到则如实说不知道。返回 {reply, backend, session_id}。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "客户的问题"},
                "session_id": {"type": "string", "description": "会话 id，用于隔离不同客户，默认 default"},
                "user_id": {"type": "string", "description": "客户 id（可选）"},
                "agent_id": {"type": "string", "description": "客服智能体 id，默认 default"},
            },
            "required": ["text"],
        },
        "fn": tool_cs_ask,
    },
    {
        "name": "cs_search_kb",
        "description": (
            "检索客服资料库，返回与 query 相关的条目（标题/摘要/标签/来源/打分）。"
            "适合「PASM 出认知、平台大模型出语言」的高级用法：你拿命中条目自己组织回复。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词（可整句）"},
                "k": {"type": "integer", "description": "返回条数，默认 5", "default": 5},
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": ["query"],
        },
        "fn": tool_cs_search_kb,
    },
    {
        "name": "cs_ingest",
        "description": "新增/补充一条知识（FAQ/文档）到客服资料库。title 必填，content 为说明正文。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "知识标题"},
                "content": {"type": "string", "description": "知识正文"},
                "source": {"type": "string", "description": "来源标记，默认 manual", "default": "manual"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                "category": {"type": "string", "description": "分类，默认 manual", "default": "manual"},
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": ["title"],
        },
        "fn": tool_cs_ingest,
    },
    {
        "name": "cs_sync",
        "description": (
            "跑一次 DB→KB 增量同步（复用 pasm_cs.connector）。"
            "有 pasm-framework 时灌进客服资料库；否则落到 JSONL 便于检查。"
            "source 可选 demo/csv/sqlite/sql/rest（不传用规格首个源）；full=true 全量重跑。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "知识源类型（不传用规格首个）"},
                "full": {"type": "boolean", "description": "是否全量重跑（忽略游标），默认 false", "default": False},
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": [],
        },
        "fn": tool_cs_sync,
    },
    {
        "name": "cs_persona",
        "description": "查看（不传 persona）或合并式更新（传 persona）客服人格。常用键：name/tone/temper/energy/play。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "persona": {"type": "object", "description": "要合并进去的人格字段（可选）"},
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": [],
        },
        "fn": tool_cs_persona,
    },
    {
        "name": "cs_status",
        "description": "查看客服后端状态：pasm-framework 是否可用、资料库规模、已加载的智能体。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "default": "default"},
            },
            "required": [],
        },
        "fn": tool_cs_status,
    },
]

CS_TOOL_INDEX: Dict[str, Dict[str, Any]] = {t["name"]: t for t in CS_TOOLS}


def list_tools() -> List[Dict[str, Any]]:
    return [{"name": t["name"], "description": t["description"],
             "inputSchema": t["inputSchema"]} for t in CS_TOOLS]


def call_tool(name: str, args: Dict[str, Any], bridge: CsAgentBridge) -> Dict[str, Any]:
    tool = CS_TOOL_INDEX.get(name)
    if tool is None:
        raise KeyError(name)
    return tool["fn"](args or {}, bridge)


# ============================================================ 主循环
def _as_params(value: Any) -> Dict[str, Any]:
    """把 ``params`` 归一成 dict。

    JSON-RPC 允许 ``params`` 是**数组**，现实里客户端偶尔也会传字符串。
    早先直接 ``params.get(...)`` → ``AttributeError: 'list' object has no
    attribute 'get'``，而 ``serve()`` 的主循环当时没有兜底 → **整个服务进程退出**。
    这里统一归一：非 dict 一律当空参数处理（错误留给具体 tool 的参数校验去报）。
    """
    return value if isinstance(value, dict) else {}


def handle_message(msg: Dict[str, Any], bridge: CsAgentBridge) -> Optional[Dict[str, Any]]:
    """协议入口：任何内部异常都翻译成 JSON-RPC error，绝不向上抛（否则会杀死服务）。"""
    req_id = msg.get("id") if isinstance(msg, dict) else None
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error_response(req_id, INVALID_REQUEST,
                               "Invalid Request: jsonrpc must be '2.0'")
    try:
        return _dispatch(msg, bridge)
    except Exception as ex:  # noqa: BLE001 —— 兜底：协议层永不崩
        _log("处理 %r 时内部错误：%s" % (msg.get("method"), ex))
        return _error_response(req_id, INTERNAL_ERROR, "Internal error: %s" % ex)


def _dispatch(msg: Dict[str, Any], bridge: CsAgentBridge) -> Optional[Dict[str, Any]]:
    method = msg.get("method")
    req_id = msg.get("id")
    params = _as_params(msg.get("params"))

    if method == "notifications/initialized" or (
            isinstance(method, str) and method.startswith("notifications/")):
        return None

    if method == "initialize":
        return _result_response(req_id, _initialize_result(params.get("protocolVersion")))

    if method == "ping":
        return _result_response(req_id, {})

    if method == "tools/list":
        return _result_response(req_id, {"tools": list_tools()})

    if method == "tools/call":
        name = params.get("name")
        a = _as_params(params.get("arguments"))
        try:
            result = call_tool(name, a, bridge)
        except KeyError:
            return _error_response(req_id, INVALID_PARAMS, "Unknown tool: %s" % name)
        except ValueError as ex:
            return _result_response(req_id, {
                "content": [{"type": "text", "text": "参数错误：%s" % ex}], "isError": True})
        except ConnectorError as ex:
            return _result_response(req_id, {
                "content": [{"type": "text", "text": "同步错误：%s" % ex}], "isError": True})
        except Exception as ex:  # noqa: BLE001
            _log("tool %s failed: %s" % (name, ex))
            return _result_response(req_id, {
                "content": [{"type": "text", "text": "cs 工具 %s 执行失败：%s" % (name, ex)}],
                "isError": True})
        payload: Dict[str, Any] = {
            "content": [{"type": "text",
                         "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "isError": False,
        }
        payload["structuredContent"] = result
        return _result_response(req_id, payload)

    if method == "shutdown":
        bridge.save_all()
        return _result_response(req_id, {})

    return _error_response(req_id, METHOD_NOT_FOUND, "Method not found: %s" % method)


def serve(bridge: Optional[CsAgentBridge] = None) -> int:
    bridge = bridge or CsAgentBridge()
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    _log("starting (persist=%s)" % bridge.persist_root)
    try:
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except Exception:
                _write(out, _error_response(None, PARSE_ERROR, "Parse error"))
                continue
            # 单帧出错也只回一条错误响应，继续服务下一帧
            # （handle_message 内部已兜底，这里是双保险，覆盖序列化等意外）
            try:
                resp = handle_message(msg, bridge)
            except Exception as ex:  # noqa: BLE001
                _log("帧处理失败（已跳过）：%s" % ex)
                resp = _error_response(msg.get("id") if isinstance(msg, dict) else None,
                                       INTERNAL_ERROR, "Internal error: %s" % ex)
            if resp is not None:
                try:
                    _write(out, resp)
                except (BrokenPipeError, ValueError):
                    break            # 客户端已断开
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        saved = bridge.save_all()
        if saved:
            _log("saved on exit: %s" % ", ".join(saved))
    return 0


def selftest() -> int:
    """本地自检：不起 stdio，把协议与工具跑一遍（含离线降级路径）。"""
    import tempfile
    ok = True

    def check(cond: bool, msg: str) -> None:
        nonlocal ok
        print("  %s %s" % ("v" if cond else "x", msg))
        if not cond:
            ok = False

    print("pasm-cs-mcp selftest v%s" % SERVER_VERSION)
    with tempfile.TemporaryDirectory() as td:
        bridge = CsAgentBridge(persist_root=td)

        # initialize 版本协商
        r = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2024-11-05"}}, bridge)
        check(r["result"]["protocolVersion"] == "2024-11-05", "版本协商回显客户端版本")
        check(r["result"]["serverInfo"]["name"] == SERVER_NAME, "serverInfo 正确")

        # tools/list
        r = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, bridge)
        names = [t["name"] for t in r["result"]["tools"]]
        check(set(["cs_ask", "cs_search_kb", "cs_ingest", "cs_sync",
                   "cs_persona", "cs_status"]).issubset(set(names)),
              "tools/list 含全部 cs_* 工具")
        check("fn" not in r["result"]["tools"][0], "对外清单不含内部 fn 字段")

        # cs_status：未装 framework 时应诚实说明不可用
        r = handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "cs_status", "arguments": {}}}, bridge)
        st = r["result"]["structuredContent"]
        check(st["agent_ready"] is False, "cs_status 诚实报告智能体未就绪")
        check(st["pasm_framework_installed"] is False, "cs_status 报告 framework 未安装")
        check("hint" in st, "cs_status 给出降级提示")

        # cs_sync：未装 framework 时落到 JSONL，仍应成功
        r = handle_message({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                            "params": {"name": "cs_sync",
                                       "arguments": {"source": "demo"}}}, bridge)
        sr = r["result"]["structuredContent"]
        check(r["result"]["isError"] is False and sr["ok"] is True, "cs_sync 离线落到 JSONL 成功")
        check(sr["new"] >= 1, "cs_sync 抓到至少 1 条（demo 源）")
        check(sr["target"] == "jsonl", "cs_sync 目标为 jsonl（framework 缺席时）")

        # cs_sync 幂等：连跑第二次不应重复入库
        r = handle_message({"jsonrpc": "2.0", "id": 41, "method": "tools/call",
                            "params": {"name": "cs_sync",
                                       "arguments": {"source": "demo"}}}, bridge)
        sr2 = r["result"]["structuredContent"]
        check(sr2["new"] == 0 and sr2["skipped"] >= 1, "cs_sync 二次同步幂等（new=0）")

        # cs_sync 未知源 → 同步错误（而非内部错误）
        r = handle_message({"jsonrpc": "2.0", "id": 42, "method": "tools/call",
                            "params": {"name": "cs_sync",
                                       "arguments": {"source": "nope"}}}, bridge)
        check(r["result"]["isError"] is True, "cs_sync 未知源返回 isError")

        # cs_ask：未装 framework 时应返回 unavailable 而非崩溃
        r = handle_message({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                            "params": {"name": "cs_ask",
                                       "arguments": {"text": "怎么退货？"}}}, bridge)
        ar = r["result"]["structuredContent"]
        check(ar["ok"] is False and ar["backend"] == "unavailable",
              "cs_ask 在 framework 缺席时诚实返回 unavailable")

        # cs_search_kb：framework 缺席返回空 hits + 错误说明
        r = handle_message({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                            "params": {"name": "cs_search_kb",
                                       "arguments": {"query": "退货"}}}, bridge)
        kr = r["result"]["structuredContent"]
        check(kr["ok"] is False and kr["hits"] == [], "cs_search_kb 缺席时返回空 hits")

        # 未知工具 → 协议错误
        r = handle_message({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                            "params": {"name": "nope", "arguments": {}}}, bridge)
        check("error" in r and r["error"]["code"] == INVALID_PARAMS, "未知工具返回协议错误")

        # 参数缺失 → isError
        r = handle_message({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                            "params": {"name": "cs_ask", "arguments": {}}}, bridge)
        check(r["result"]["isError"] is True, "cs_ask 缺 text 返回 isError")

        # ★ 回归：params 为 JSON 数组（协议允许）→ 必须给错误响应，绝不能抛异常
        try:
            r = handle_message({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                "params": ["cs_status"]}, bridge)
            check(r is not None and "error" in r,
                  "params 为数组时不崩、返回协议错误")
        except Exception as ex:  # noqa: BLE001
            check(False, "params 为数组时抛出 %s（应被兜底）" % type(ex).__name__)

        # ★ 回归：可选参数类型错 → 报「参数错误」而不是「后端不可用」
        r = handle_message({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                            "params": {"name": "cs_search_kb",
                                       "arguments": {"query": "退货", "k": "abc"}}}, bridge)
        check(r["result"]["isError"] is True
              and "k 必须是整数" in r["result"]["content"][0]["text"],
              "cs_search_kb 的 k 类型错报参数错误（不被后端缺失掩盖）")

        # ★ 回归：tags 传逗号串也能接受（LLM 客户端常见传法）
        r = handle_message({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                            "params": {"name": "cs_ingest",
                                       "arguments": {"title": "t", "tags": "a, b"}}}, bridge)
        check(r["result"]["isError"] is False, "cs_ingest 接受逗号串 tags")

        # 通知类不回复
        check(handle_message({"jsonrpc": "2.0",
                              "method": "notifications/initialized"}, bridge) is None,
              "通知类消息不回复")

        # 非法 jsonrpc → Invalid Request（不崩）
        r = handle_message({"id": 12, "method": "tools/list"}, bridge)
        check(r["error"]["code"] == INVALID_REQUEST, "缺少 jsonrpc 字段返回 Invalid Request")

    print("pasm-cs-mcp selftest:", "通过" if ok else "失败")
    return 0 if ok else 1


# ============================================================ CLI
def build_mcp_config(spec: AgentSpec) -> Dict[str, Any]:
    """生成给 MCP 客户端的启动配置（stdio）。平台的大模型通过 cs_* 工具调用你的实例。"""
    return {
        "mcpServers": {
            spec.agent_id: {
                "command": "python",
                "args": ["-m", "pasm_cs.adapters.mcp"],
                "env": {},
                "note": (
                    "平台的大模型通过 cs_search_kb 拿到资料库命中条目、据 cs_status 看后端，"
                    "再组织成自然的回复；cs_sync 让资料库随业务数据自生长。"
                    "数据留在你本地运行实例，不上传平台。"
                ),
            }
        }
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pasm_cs_mcp", description="PASM 专业客服 MCP 服务器（stdio）")
    ap.add_argument("--persist-dir", default=None,
                    help="状态/知识库落盘根目录，默认 ~/.pasm-cs-mcp")
    ap.add_argument("--selftest", action="store_true",
                    help="本地自检（不起 stdio），用于验证安装是否可用")
    ap.add_argument("--version", action="version",
                    version="%(prog)s " + SERVER_VERSION)
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    return serve(CsAgentBridge(persist_root=args.persist_dir))


if __name__ == "__main__":
    raise SystemExit(main())
