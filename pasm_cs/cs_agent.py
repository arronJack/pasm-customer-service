"""客服智能体统一入口。

为什么需要这一层
----------------
``pasm-framework`` 仓库里的 ``apps/customer_service.py`` 是**参考实现**，
但它位于仓库根的 ``apps/`` 目录、**未打进 wheel**
（``[tool.setuptools] packages = ["pasm_framework", ...]`` 不含 ``apps``）。
所以 ``from pasm_framework.apps.customer_service import CustomerServiceAgent``
无论是从源码还是 ``pip install pasm-framework`` 之后都会失败。

因此本模块：
  1. 优先使用**框架自带的参考实现**（若未来框架把 ``apps`` 打进包，或仓库根在 sys.path 上）；
  2. 否则回落到**本地等价实现** ``_LocalCustomerServiceAgent``（只依赖已发布的
     ``pasm_framework.BaseApplication`` + 内置插件，行为与参考实现一致）；
  3. 对外统一暴露 ``build_cs_agent(...)`` 与 ``cs_available()``，
     避免各适配器（cli / web_run / mcp）各写一套易错的 import 路径。

这样，``pip install pasm-framework`` 装好后即可跑起专业客服，无需框架仓库源码。
"""
from __future__ import annotations

import importlib.util
from typing import Any, Dict, List, Optional


def framework_available() -> bool:
    """``pasm_framework`` 本身是否可用（发布包，P0 依赖）。"""
    return importlib.util.find_spec("pasm_framework") is not None


def _canonical_class():
    """尽力拿到框架参考实现；拿不到返回 None。"""
    for mod in ("pasm_framework.apps.customer_service", "apps.customer_service"):
        try:
            m = __import__(mod, fromlist=["CustomerServiceAgent"])
            return getattr(m, "CustomerServiceAgent")
        except Exception:
            continue
    return None


# ---- 本地等价实现（与框架参考实现同源，仅依赖已发布的 BaseApplication） ----
def _default_cs_config(kb_dir: Optional[str] = None,
                       llm: Optional[Dict[str, Any]] = None,
                       serve_port: int = 8080,
                       enable_gateway: bool = False) -> Dict[str, Any]:
    """智能客服的后端开关表（对应框架参考实现里的同名字段）。

    与参考实现的**唯一差异**：``web_gateway`` 默认关闭（``enable_gateway=False``）。
    参考实现无条件开着网关，是被 ``cs.serve()`` 显式拉起时才真正监听；但在
    MCP / 纯认知调用场景下，多一个"随时可能被误启动、占住 8080"的插件没有意义。
    需要站点 ``<iframe>`` / REST 接入时，传 ``enable_gateway=True``
    （``adapters/web.py`` 与 ``cli serve`` 就是这么做的）——
    因为 ``BaseApplication.serve()`` 在网关插件未启用时会直接抛 ``FrameworkError``。
    """
    return {
        "safety": {"enabled": True, "config": {"mode": "warn"}},
        "sessions": {"enabled": True, "config": {"max_history": 20}},
        "knowledge_base": {"enabled": True,
                           "config": ({"kb_dir": kb_dir} if kb_dir else {})},
        "warmth": {"enabled": True, "config": {}},
        "observability": {"enabled": True, "config": {}},
        "llm_responder": {"enabled": bool(llm), "config": llm or {}},
        "web_gateway": {"enabled": bool(enable_gateway),
                        "config": {"port": serve_port, "allowed_origins": "*"}},
    }


def _builtin_config() -> Dict[str, Any]:
    return _default_cs_config()


def _make_local_class():
    from pasm_framework import BaseApplication

    class _LocalCustomerServiceAgent(BaseApplication):
        """站点 / 平台智能客服（自足实现，行为对齐框架参考实现）。"""

        def __init__(self, agent_id: str, persona: Optional[Dict[str, Any]] = None,
                     *, kb_dir: Optional[str] = None,
                     llm: Optional[Dict[str, Any]] = None,
                     serve_port: int = 8080,
                     enable_gateway: bool = False,
                     persist_dir: Optional[str] = None) -> None:
            self._serve_port = serve_port
            persona = persona or {
                "name": "小智", "role": "智能客服",
                "tone": "温暖、专业、耐心",
                "temper": 0.6, "energy": 0.5, "play": 0.4,
            }
            super().__init__(
                agent_id, persona, persist_dir=persist_dir,
                backend_config=_default_cs_config(kb_dir=kb_dir, llm=llm,
                                                  serve_port=serve_port,
                                                  enable_gateway=enable_gateway),
            )

        def action_pool(self) -> List[str]:
            return ["reply", "escalate"]

        def _render_reply(self, text: str, facts: List[Dict[str, Any]],
                          mood: float) -> str:
            """只依据“有来源的知识”作答；查不到如实说不知道（不编造）。"""
            knowledge = [f for f in facts if f.get("source")]
            if knowledge:
                top = knowledge[0]
                brief = (top.get("brief") or top.get("title") or "").strip()
                src = str(top.get("source", ""))
                answer = "关于您的问题，我们查到相关说明：%s" % brief
                if src.startswith("knowledge_base"):
                    answer += "（资料来源：%s）" % src.split(":", 1)[-1]
                return answer
            return ("抱歉，我暂时没有查到关于这个问题的资料，已记录您的问题。"
                    "您可以拨打我们的客服热线，或稍后再试，我们会尽快完善答案。")

        def ingest_faq(self, items: List[Dict[str, Any]]) -> int:
            return self.ingest(items)

        def ask(self, text: str, session_id: str = "default",
                user_id: Optional[str] = None) -> str:
            return self.handle(text, session_id=session_id, user_id=user_id)

        def serve(self, host: str = "0.0.0.0", port: Optional[int] = None) -> None:
            super().serve(host=host, port=port or self._serve_port)

    return _LocalCustomerServiceAgent


def cs_available() -> bool:
    """能否构造客服智能体（需要 pasm-framework）。"""
    return framework_available()


def build_cs_agent(agent_id: str, persona: Optional[Dict[str, Any]] = None, *,
                   kb_dir: Optional[str] = None,
                   llm: Optional[Dict[str, Any]] = None,
                   serve_port: int = 8080,
                   enable_gateway: bool = False,
                   persist_dir: Optional[str] = None):
    """构造一个客服智能体。优先框架参考实现，否则本地等价实现。

    ``enable_gateway=True`` 时启用 ``web_gateway``（站点 ``<iframe>`` / REST 接入所需）；
    调用 ``.serve()`` 之前**必须**为真，否则 ``BaseApplication.serve()`` 抛
    ``FrameworkError``。注意框架参考实现无条件启用网关，该开关对它无效（也不冲突）。

    ``pasm-framework`` 缺席时抛 ``RuntimeError``（由调用方决定降级策略）。
    """
    cls = _canonical_class()
    if cls is None:
        if not framework_available():
            raise RuntimeError(
                "需要 pasm-framework：pip install pasm-framework")
        cls = _make_local_class()
        return cls(agent_id, persona=persona, kb_dir=kb_dir, llm=llm,
                   serve_port=serve_port, enable_gateway=enable_gateway,
                   persist_dir=persist_dir)
    # 参考实现没有 enable_gateway 形参（它总是启用网关），保持一致签名调用
    return cls(agent_id, persona=persona, kb_dir=kb_dir, llm=llm,
               serve_port=serve_port, persist_dir=persist_dir)
