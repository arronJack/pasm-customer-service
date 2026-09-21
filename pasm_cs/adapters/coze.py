"""Coze 适配器（把 spec 转译成 Coze 机器人导入配置）。

重要澄清：Coze / Character 这类平台**不是 MCP 兼容**，不能「上传 PASM 智能体让它的
LLM 直接跑」。可行路径是：把 spec 转译成它们各自的「机器人配置」（人格提示词 +
知识库说明 + 插件说明），在平台内**重建**一个等价的客服机器人。知识库可由本项目的
连接器先导出成文件，再在 Coze 侧上传。

本适配器输出一个与 Coze 导入格式接近的 dict（提示词 + 知识库占位），可直接在
Coze 的「导入 Bot」里落地后再微调。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import AgentSpec


def _system_prompt(spec: AgentSpec) -> str:
    p = spec.persona
    tone = p.get("tone", "专业、耐心")
    lines = [
        f"你是{p.get('name', '小智')}，一名{p.get('role', '智能客服')}。",
        f"你的语气风格：{tone}。",
        "你拥有长期记忆（客户偏好、历史工单）与情绪感知，请在回复中自然体现。",
        "你可以通过工具完成：",
    ]
    for c in spec.capabilities:
        lines.append(f"  - {c.name}：{c.description}")
    lines.append(
        "回答必须基于资料库中的事实；查不到时如实告知并引导转人工，绝不编造。"
    )
    return "\n".join(lines)


def to_coze_bot(spec: AgentSpec) -> Dict[str, Any]:
    """输出 Coze 机器人导入配置（近似结构，平台导入后按需微调）。"""
    knowledge_files: List[str] = [
        "products.csv（由 DB→KB 连接器首次导出，建议在 Coze 知识库上传）"
    ]
    return {
        "bot_name": spec.persona.get("name", "小智客服"),
        "description": "%s · 由 PASM 规格转译" % spec.persona.get("role", "智能客服"),
        "prompt": {
            "system_prompt": _system_prompt(spec),
        },
        "knowledge": {
            "files": knowledge_files,
            "note": "知识由本项目连接器从业务库同步导出，保持与业务数据一致。",
        },
        "plugins": [
            {"name": c.name, "desc": c.description} for c in spec.capabilities
        ],
        "warning": (
            "Coze 用自己的 LLM 与运行时，PASM 仅作为「人格+知识来源」被转译，"
            "记忆/情绪无法跨平台共享；如要保留 PASM 认知，请用 MCP 适配器。"
        ),
    }


def to_character_card(spec: AgentSpec) -> Dict[str, Any]:
    """Character.ai 风格 persona 卡片（近似结构）。"""
    p = spec.persona
    return {
        "name": p.get("name", "小智"),
        "title": p.get("role", "智能客服"),
        "greeting": "您好，我是%s，很高兴为您服务～请问有什么可以帮您？" % p.get("name", "小智"),
        "definition": _system_prompt(spec),
        "visibility": "private",
        "note": "Character 同样用自己的模型，PASM 认知无法跨平台；仅转译人格与知识。",
    }
