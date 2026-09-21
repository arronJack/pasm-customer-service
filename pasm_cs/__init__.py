"""pasm-customer-service：基于 PASM 的专业客服系统（原型）。

一份声明式规格（agent_spec.toml），多种运行形态：
  · 本地命令运行（cli.py）
  · PASM Studio 场景模板（图形界面）
  · MCP 适配器（WorkBuddy / ClawHub / Claude Desktop）
  · Web 适配器（站点 <iframe> / REST）
  · Coze / Character 适配器（转译导入）

核心差异点：DB→KB 同步连接器让资料库随业务数据自动生长，且数据留在本地。
"""
from __future__ import annotations

__version__ = "0.1.0"

from .connector import (  # noqa: F401
    DBKBSyncConnector,
    DemoSource,
    CsvSource,
    SqlSource,
    SqliteSource,
    RestSource,
    FileKBSink,
    PasmKBSink,
    KBItem,
    SyncReport,
)
from .cs_agent import build_cs_agent, cs_available, framework_available  # noqa: F401

__all__ = [
    "DBKBSyncConnector", "DemoSource", "CsvSource", "SqlSource", "SqliteSource",
    "RestSource", "FileKBSink", "PasmKBSink", "KBItem", "SyncReport",
    "build_cs_agent", "cs_available", "framework_available",
]
