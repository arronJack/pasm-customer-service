"""Studio 场景加载器：把 agent_spec.toml 转成 Studio 可识别的智能体场景配置。

与 Studio 的对接（2026-09-21 起是**真·一键加载**，不再是"只有说明书"）
--------------------------------------------------------------------
PASM Studio >= 0.31.2 在设置面板加了「📦 场景」页（对应 ``desktop/scenario.py``）：
列出本目录下的 ``*.json``，点「导入此场景」即把人格填进「🎭 基本」页、
把知识源（inline / csv / sqlite / jsonl / demo）灌进本机资料库。

⚠️ **目录必须两边同源**：Studio 侧走 ``logsetup.data_dir()``（``PASM_STUDIO_DIR``
优先），本模块的 ``studio_scenarios_dir()`` 已对齐同一优先级 —— 否则设了隔离时
两边各写各的，表现为「生成了却一个都看不见」。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .adapters.base import load_spec


def _roaming_appdata() -> str:
    """系统标准 Roaming 目录。

    优先用系统 API 而不是先读 ``APPDATA`` 环境变量 —— 从终端（bash）启动时
    ``APPDATA`` 可能为空，会让同一台机器上「双击」与「命令行」写到两个不同的地方
    （用户表现为"数据不见了"）。与 Studio 侧 ``logsetup.roaming_appdata()`` 同款做法。
    """
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_APPDATA = 0x1A（即 Roaming）
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x1A, None, 0, buf) == 0:
                if buf.value:
                    return buf.value
        except Exception:                                       # noqa: BLE001
            pass
    return os.environ.get("APPDATA") or os.path.expanduser("~/.config")


def studio_scenarios_dir() -> str:
    """Studio 场景配置目录 —— 必须与 Studio 侧 `logsetup.data_dir()` **同源**。

    ⚠️ 顺序不能改：
      ① ``PASM_STUDIO_DIR`` 优先。那是 Studio 的隔离 / 多实例开关；不认它的话，
         设了隔离时 `pasm-cs studio` 仍写 ``%APPDATA%``，而 Studio 去隔离目录找，
         **一个场景都看不见**（2026-09-21 修）。
      ② 否则 Roaming/``PASMStudio``。
    """
    base = os.environ.get("PASM_STUDIO_DIR")
    if not base:
        base = os.path.join(_roaming_appdata(), "PASMStudio")
    d = os.path.join(base, "scenarios")
    os.makedirs(d, exist_ok=True)
    return d


PKG_ROOT = Path(__file__).resolve().parent.parent  # pasm-customer-service/


def _abs_asset(rel) -> str:
    """把知识源里的相对路径解析成本机绝对路径；找不到返回空串。

    为什么需要：``path`` 是**相对本仓**的（如 ``examples/products.csv``）。
    Studio 在别的 CWD 下跑时按相对路径找不到，CSV/SQLite 源就会导入失败。
    多存一份 ``abs_path`` 让本机导入直接命中，同时保留 ``path`` 供换机 / 归档重定位。
    """
    if not rel:
        return ""
    try:
        if os.path.isabs(rel):
            return rel if os.path.exists(rel) else ""
        for c in (os.path.abspath(rel), str(PKG_ROOT / rel)):
            if os.path.exists(c):
                return c
    except Exception:                                           # noqa: BLE001
        pass
    return ""


def build_scenario(spec) -> dict:
    """把 AgentSpec 翻译成 Studio 场景配置 JSON（schema 对齐 Studio persona）。"""
    persona = spec.persona or {}
    sources = []
    for s in spec.knowledge_sources:
        rel = getattr(s, "path", None)
        item = {
            "type": getattr(s, "type", "unknown"),
            "path": rel,
            "url": getattr(s, "url", None),
            "source_name": getattr(s, "source_name", getattr(s, "type", "unknown")),
        }
        ab = _abs_asset(rel)
        if ab:
            item["abs_path"] = ab          # 本机导入优先用它，path 留给换机重定位
        sources.append(item)
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
        "note": "由 pasm-customer-service 生成；在 PASM Studio >= 0.31.2 的"
                "「设置 → 📦 场景」页可一键导入（人格进「基本」页，知识进资料库）。",
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
