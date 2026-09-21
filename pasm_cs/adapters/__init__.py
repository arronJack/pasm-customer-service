"""平台适配器集合。"""
from __future__ import annotations

from .base import AgentSpec, load_spec, KnowledgeSource, Capability  # noqa: F401
from .coze import to_coze_bot, to_character_card  # noqa: F401
from .web import build_widget, build_rest_example, start_server  # noqa: F401

# mcp 不进 __init__ 的 eager import：`python -m pasm_cs.adapters.mcp` 会先导入本包，
# 若此处 eager 导入会与 `-m` 的执行重复，触发 RuntimeWarning。改用 PEP 562 延迟导入。
_MCP_NAMES = frozenset({
    "CsAgentBridge", "build_mcp_config", "serve", "selftest", "main",
    "list_tools", "call_tool",
})


def __getattr__(name: str):
    if name in _MCP_NAMES:
        from . import mcp as _mcp
        return getattr(_mcp, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


__all__ = [
    "AgentSpec", "load_spec", "KnowledgeSource", "Capability",
    "CsAgentBridge", "build_mcp_config", "serve", "selftest", "main",
    "list_tools", "call_tool",
    "to_coze_bot", "to_character_card",
    "build_widget", "build_rest_example", "start_server",
]
