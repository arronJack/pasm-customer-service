"""Studio 场景加载器：把 agent_spec.toml 转成 Studio 可识别的智能体场景配置。

重要边界（诚实说明）
--------------------
当前 PASM Studio（``desktop/pasm_companion.py``）的左栏 NAV 是固定 9 项
（对话/任务/工作台/自动化/资料库/记忆/技能/团队/工作流），**没有「外部场景 /
智能体导入」入口**；``pasm/cognitive/workspace.py`` 的目录也只按 7 个分类组织，
没有「场景」目录。

因此本加载器做的是「**配置生成器**」：产出一份对齐 Studio 真实 persona 字段
与 KB 源结构的场景配置 JSON，写入约定目录
``%APPDATA%/PASMStudio/scenarios/<agent_id>.json``，并附带接入说明。
真实「一键加载」需要在 Studio 加一个 UI 入口（见 ``PLAN.md`` 阶段二后半），
但配置 schema 已与 Studio 的 persona / 知识源字段对齐，未来可直接 import。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .adapters.base import load_spec


def studio_scenarios_dir() -> str:
    """Studio 场景配置约定目录（与 Studio 的 APPDATA/PASMStudio 根对齐）。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(base, "PASMStudio", "scenarios")
    os.makedirs(d, exist_ok=True)
    return d


def build_scenario(spec) -> dict:
    """把 AgentSpec 翻译成 Studio 场景配置 JSON（schema 对齐 Studio persona）。"""
    persona = spec.persona or {}
    sources = []
    for s in spec.knowledge_sources:
        sources.append({
            "type": getattr(s, "type", "unknown"),
            "path": getattr(s, "path", None),
            "url": getattr(s, "url", None),
            "source_name": getattr(s, "source_name", getattr(s, "type", "unknown")),
        })
    caps = [
        {"name": c.name, "description": c.description}
        for c in (spec.capabilities or [])
    ]
    return {
        "schema": "pasm-studio-scenario/v1",
        "agent_id": spec.agent_id,
        "display_name": "%s·专业客服" % (persona.get("name") or spec.agent_id),
        # 对齐 pasm_skills.sdk.BaseAgent.persona 与 Studio 伴侣 persona 字段
        "persona": {
            "name": persona.get("name", spec.agent_id),
            "role": persona.get("role", "智能客服"),
            "tone": persona.get("tone", "温暖、专业、耐心"),
            "temper": persona.get("temper", 0.6),
            "energy": persona.get("energy", 0.5),
            "play": persona.get("play", 0.4),
        },
        "knowledge_sources": sources,
        "capabilities": caps,
        "platforms": spec.platforms or {},
        "launch": {
            "cli_dryrun": "python -m pasm_cs.cli run --source sqlite",
            "cli_pasm": "python -m pasm_cs.cli run --source sqlite --pasm",
            "mcp": bool((spec.platforms or {}).get("mcp")),
            "web": bool((spec.platforms or {}).get("web")),
            "web_port": (spec.platforms or {}).get("web_port", 8080),
        },
        "note": "由 pasm-customer-service 生成；Studio 当前需加「导入场景」入口方可一键加载。",
        "generated_by": "pasm-customer-service studio_loader",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def write_scenario(spec, out_dir: str = None) -> str:
    sc = build_scenario(spec)
    d = out_dir or studio_scenarios_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.json" % spec.agent_id)
    Path(path).write_text(
        json.dumps(sc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
