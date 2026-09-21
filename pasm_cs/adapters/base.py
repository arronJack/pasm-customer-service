"""Agent Spec 加载与统一描述。

规格文件用 TOML（Python 3.11+ 内置 ``tomllib``，零额外依赖）。
``load_spec`` 返回结构化的 ``AgentSpec``，供各平台适配器消费。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_SPEC_PATH = Path(__file__).resolve().parent.parent / "agent_spec.toml"


@dataclass
class KnowledgeSource:
    type: str
    path: Optional[str] = None
    url: Optional[str] = None
    query: Optional[str] = None
    source_name: str = "spec"
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Capability:
    name: str
    description: str


@dataclass
class AgentSpec:
    agent_id: str
    persona: Dict[str, Any]
    knowledge_sources: List[KnowledgeSource] = field(default_factory=list)
    sync_interval: int = 0
    sync_state_path: Optional[str] = None
    capabilities: List[Capability] = field(default_factory=list)
    platforms: Dict[str, Any] = field(default_factory=dict)

    def platform_enabled(self, name: str) -> bool:
        v = self.platforms.get(name)
        if isinstance(v, bool):
            return v
        if isinstance(v, dict):
            return bool(v.get("enabled", False))
        return bool(v)

    def summary(self) -> str:
        lines = [
            "AgentSpec(agent_id=%s)" % self.agent_id,
            "  persona: %s" % self.persona.get("name", "?"),
            "  knowledge sources: %s" % ", ".join(s.type for s in self.knowledge_sources),
            "  capabilities: %s" % ", ".join(c.name for c in self.capabilities),
            "  platforms: %s" % ", ".join(
                k for k, v in self.platforms.items()
                if (v is True) or (isinstance(v, dict) and v.get("enabled"))
            ),
        ]
        return "\n".join(lines)


def load_spec(path: Optional[str] = None) -> AgentSpec:
    p = Path(path) if path else _SPEC_PATH
    if not p.exists():
        raise FileNotFoundError("规格文件不存在: %s" % p)

    toml = _load_toml(p)
    agent = toml.get("agent", {})
    persona = agent.get("persona", {})
    knowledge = agent.get("knowledge", {})

    sources: List[KnowledgeSource] = []
    for s in knowledge.get("sources", []):
        sources.append(KnowledgeSource(
            type=s.get("type", "demo"),
            path=s.get("path"),
            url=s.get("url"),
            query=s.get("query"),
            source_name=s.get("source_name", s.get("type", "spec")),
            extra={k: v for k, v in s.items()
                   if k not in ("type", "path", "url", "query", "source_name")},
        ))
    sync = knowledge.get("sync", {})

    caps: List[Capability] = [
        Capability(name=c.get("name", ""), description=c.get("description", ""))
        for c in agent.get("capabilities", [])
    ]
    return AgentSpec(
        agent_id=agent.get("id", "unnamed"),
        persona=persona,
        knowledge_sources=sources,
        sync_interval=int(sync.get("interval_seconds", 0) or 0),
        sync_state_path=sync.get("state_path"),
        capabilities=caps,
        platforms=agent.get("platforms", {}),
    )


def _load_toml(p: Path) -> Dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib
        with p.open("rb") as f:
            return tomllib.load(f)
    # 老版本回退到 tomli（如有）
    try:  # pragma: no cover
        import tomli  # type: ignore
        with p.open("rb") as f:
            return tomli.load(f)
    except ImportError as ex:  # pragma: no cover
        raise RuntimeError(
            "需要 tomllib（Python>=3.11）或 pip install tomli 来解析规格文件。"
        ) from ex
