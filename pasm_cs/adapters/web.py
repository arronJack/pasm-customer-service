"""Web 适配器（站点嵌入 / REST，面向完全不懂技术的普通用户）。

``pasm-framework`` 的 ``web_gateway`` 插件已经提供零依赖 HTTP 网关：
  · ``GET  /``            返回一个可直接用的聊天挂件页（访客用 public_token 访问）；
  · ``POST /api/chat``    对接站点后端；
  · ``<iframe src="...">`` 嵌入任意网页。

本适配器：根据 spec 生成一个嵌入代码片段，并提供「启动服务器」入口
（懒加载 pasm-framework，没装时给出明确指引）。
"""
from __future__ import annotations

from typing import Any, Dict

from .base import AgentSpec


def build_widget(snippet_host: str, spec: AgentSpec, *, port: int = 8080) -> str:
    """生成站点嵌入代码片段（iframe 方式）。

    注意：``web_gateway`` 的 ``GET /`` 是**访客页**，需要 ``public_token``
    （双令牌机制：``token`` 管管理接口、``public_token`` 只放行 ``/api/chat`` 与挂件页）。
    未配置 ``public_token`` 时挂件页不公开——请先在 ``backend_config`` 里设置，
    别把管理令牌贴到前端。
    """
    host = snippet_host.rstrip("/")
    return (
        '<!-- PASM 智能客服挂件：把下面这行放进你网站的任意页面即可 -->\n'
        '<!-- 需要服务端已配置 public_token（访客令牌）；不要把管理 token 放前端 -->\n'
        '<iframe src="%s:%d/" width="380" height="600" '
        'frameborder="0" allow="clipboard-write"></iframe>'
    ) % (host, port)


def build_rest_example(spec: AgentSpec, *, port: int = 8080) -> Dict[str, Any]:
    return {
        "chat": {
            "method": "POST",
            "url": "http://<host>:%d/api/chat" % port,
            "body": {"text": "<客户问题>", "session_id": "<客户会话id>"},
            "headers": {"X-PASM-Token": "<public_token（访客令牌）>"},
        },
        "ingest": {
            "method": "POST",
            "url": "http://<host>:%d/api/ingest/text" % port,
            "body": {"text": "<长文资料，自动切块/识别QA>"},
            "headers": {"X-PASM-Token": "<管理 token>"},
        },
    }


def start_server(spec: AgentSpec) -> None:
    """根据 spec 启动一个真实可服务的客服实例。

    两条都必须对：
      ① 用 ``build_cs_agent`` 而不是直接 import ``pasm_framework.apps.customer_service``
         —— 后者所在的 ``apps/`` 目录**没打进 wheel**，源码与安装后都导不到；
      ② 必须 ``enable_gateway=True`` —— ``BaseApplication.serve()`` 在
         ``web_gateway`` 插件未启用时会直接抛 ``FrameworkError``
         （早先 ``cs_agent`` 无条件关网关，于是这条路必然起不来）。
    """
    from ..cs_agent import build_cs_agent, framework_available
    if not framework_available():
        raise RuntimeError(
            "Web 适配器需要 pasm-framework：pip install pasm-framework")
    port = int(spec.platforms.get("web_port", 8080)) if isinstance(spec.platforms, dict) else 8080
    cs = build_cs_agent(
        spec.agent_id,
        persona=spec.persona,
        kb_dir="./%s_kb" % spec.agent_id,
        persist_dir="./%s_state" % spec.agent_id,
        serve_port=port,
        enable_gateway=True,      # ★ 不传这个，serve() 必抛 FrameworkError
    )
    # 首次灌入规格里声明的知识源
    _seed_knowledge(cs, spec)
    print("客服已启动： http://0.0.0.0:%d/  （Ctrl+C 退出）" % port)
    try:
        cs.serve(port=port)
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        try:
            cs.close()
        except Exception:  # noqa: BLE001
            pass


def _seed_knowledge(cs: Any, spec: AgentSpec) -> None:
    from ..source_factory import make_source_for
    from ..connector import DBKBSyncConnector, PasmKBSink
    source, _kind = make_source_for(spec)
    conn = DBKBSyncConnector(
        source,
        PasmKBSink(cs),
        state_path=spec.sync_state_path,
    )
    report = conn.sync()
    print("  知识初始化：%s" % report)
