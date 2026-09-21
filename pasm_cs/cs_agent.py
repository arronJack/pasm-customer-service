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
import re
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


# ============================================================ 检索相关性闸门
#: 与框架 ``knowledge_base`` 同口径的分词：英文/数字词（≥2 字符）+ 中文 bigram。
#: **单字不作数** —— 「你」「么」这类高频字会造成大量误命中。
_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")

#: 次级判据的分数门槛（见 ``select_knowledge``）。
DEFAULT_SCORE_FLOOR: float = 4.0

NO_ANSWER_TEXT = ("抱歉，我暂时没有查到关于这个问题的资料，已记录您的问题。"
                  "您可以拨打我们的客服热线，或稍后再试，我们会尽快完善答案。")


def semantic_tokens(text: str) -> set:
    """把文本切成检索用的 token（与框架同口径）。"""
    out: set = set()
    for seg in _WORD_RE.findall(text or ""):
        if seg[0].isascii():
            if len(seg) >= 2:
                out.add(seg.lower())
        elif len(seg) >= 2:
            for i in range(len(seg) - 1):
                out.add(seg[i:i + 2])
    return out


def retrieval_surface(fact: Dict[str, Any]) -> str:
    """条目的**检索面**：标题 + 标签（+ 分类，若上游带过来）。

    为什么是这三个：标题和标签是人工维护的"这条讲什么"的声明；
    ``category`` 来自业务数据（如 SQLite 的 category 列），同样是人工分类。
    正文（``content``）**不算检索面** —— 见 ``touches_surface``。
    """
    parts = [str(fact.get("title") or ""), str(fact.get("category") or "")]
    parts += [str(t) for t in (fact.get("tags") or [])]
    return " ".join(parts)


def touches_surface(query_tokens: set, fact: Dict[str, Any]) -> bool:
    """这条命中是否落在条目的检索面上（标题 / 标签 / 分类）。

    为什么要这道闸门（实测数据，不是拍脑袋）
    ------------------------------------------
    ``knowledge_base`` 的分数是 ``(重叠词×字段权重 + 精确率) × 时间衰减``。
    在 4 条起步资料库上实测：

    * 真问题（「怎么退货？」「发票怎么开？」「会员权益有哪些」…）分数 **6.00 ~ 24.00**；
    * 假命中：问「请问 CEO 的私人邮箱是多少」，靠正文里一个「邮箱」命中了
      **电子发票** —— 分数 **2.29**，回复于是**答非所问**。

    想用绝对分数分开它们有个陷阱：假命中 2.29 与真命中里较弱的
    「发货要几天」2.40 只差 0.11 —— **任何阈值都分不开**。
    而分数还带**时间衰减**（``0.6 + 0.4 × recency``），资料库放一个月后
    真命中会被压到 0.6 倍，固定阈值必然开始"失忆"。

    所以主判据用**与分数、与时间都无关**的规则：**命中必须落在检索面上**。
    只跟正文里一个偶然重合的词撞上，几乎都是假命中。
    """
    return bool(query_tokens & semantic_tokens(retrieval_surface(fact)))


def select_knowledge(text: str, knowledge: List[Dict[str, Any]],
                     score_floor: float = DEFAULT_SCORE_FLOOR
                     ) -> List[Dict[str, Any]]:
    """从候选知识里挑出**真正相关**的那些；挑不出返回 ``[]``。

    两级判据，顺序不能反：

    1. **检索面命中**（主判据，与分数/时间无关）—— 只要能落在标题/标签上就采纳；
    2. **分数兜底**（次级）—— 检索面没撞上、但分数足够高（默认 ≥ 4.0）也采纳。

    第 2 级是必要的：像「多久能发货」这种改写，若资料的标签里没有「发货」，
    纯检索面规则会漏判。兜底门槛取 4.0 而不是 2.0，是因为实测假命中能到 2.29
    （见 ``touches_surface``）。

    ⚠️ **给资料维护者的契约**：想让改写式提问（"多久能发货"→"配送时效"）命中，
    正解是**把同义词写进 tags**，而不是调低阈值 —— 阈值一松就会放回假命中。
    """
    if not knowledge:
        return []
    qt = semantic_tokens(text)
    hit = [f for f in knowledge if touches_surface(qt, f)]
    if hit:
        return hit
    return [f for f in knowledge
            if float(f.get("score") or 0.0) >= score_floor]


def _wrap_gate(cls):
    """给任意客服实现套上相关性闸门（无论走参考实现还是本地实现，行为一致）。

    为什么用子类包装而不是改各自的方法：``build_cs_agent`` 有两条来源
    （框架参考实现 / 本地等价实现），行为必须一致；包装一次，两边都受管。
    """
    inner = cls._render_reply

    def _render_reply(self, text, facts, mood):
        # ① 先按"有来源"过滤（排除对话记忆被当成知识），
        # ② 再过相关性闸门，③ 剩下什么就交给底层渲染。
        knowledge = self.knowledge_facts(facts)
        picked = select_knowledge(text, knowledge)
        if not picked:
            return NO_ANSWER_TEXT
        return inner(self, text, picked, mood)

    return type(cls.__name__, (cls,), {"_render_reply": _render_reply})


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
            """渲染回复。

            ``facts`` 到这里时已经过 ``_wrap_gate`` 的两道过滤
            （只留"有来源的知识" + 过相关性闸门），所以这里只管措辞。
            """
            knowledge = self.knowledge_facts(facts)
            if not knowledge:
                return NO_ANSWER_TEXT
            top = knowledge[0]
            brief = (top.get("brief") or top.get("title") or "").strip()
            src = str(top.get("source", ""))
            answer = "关于您的问题，我们查到相关说明：%s" % brief
            if src.startswith("knowledge_base"):
                answer += "（资料来源：%s）" % src.split(":", 1)[-1]
            return answer

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

    **无论走哪条来源，返回的实例都带检索相关性闸门**（见 ``select_knowledge``）：
    查不到就如实说查不到，不会拿一条只沾一个词的资料答非所问。

    ``pasm-framework`` 缺席时抛 ``RuntimeError``（由调用方决定降级策略）。
    """
    cls = _canonical_class()
    if cls is None:
        if not framework_available():
            raise RuntimeError(
                "需要 pasm-framework：pip install pasm-framework")
        cls = _make_local_class()
        return _wrap_gate(cls)(agent_id, persona=persona, kb_dir=kb_dir, llm=llm,
                               serve_port=serve_port,
                               enable_gateway=enable_gateway,
                               persist_dir=persist_dir)
    # 参考实现没有 enable_gateway 形参（它总是启用网关），保持一致签名调用
    return _wrap_gate(cls)(agent_id, persona=persona, kb_dir=kb_dir, llm=llm,
                           serve_port=serve_port, persist_dir=persist_dir)
