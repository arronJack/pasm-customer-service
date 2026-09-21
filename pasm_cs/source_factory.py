"""按声明式规格构造数据源 —— CLI / MCP / Web 三个入口共用的唯一实现。

为什么需要收敛
--------------
此前 ``cli.py``、``adapters/mcp.py``、``adapters/web.py`` **各写了一套**
「spec → Source」的映射，且已经漂移出真实差异：

  · ``web.py`` 只认 csv / demo，遇到 sqlite 源直接回落 DemoSource；
  · ``cli.py`` 干脆硬编码 ``examples/products.csv``，完全不读 spec；
  · ``mcp.py`` 认全了类型，但演示资产不存在时会报「no such table」。

同一份 ``agent_spec.toml`` 在不同入口跑出不同结果，属"配置漂移"。
这里把它收敛成一份实现，并统一「演示资产缺失就地重建」的行为，
使 ``pip install`` 之后（CWD 不再是仓库根）依然开箱可跑。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Tuple

from .adapters.base import AgentSpec, KnowledgeSource
from .connector import (
    ConnectorError, CsvSource, DemoSource, RestSource, SqlSource, SqliteSource,
)
from . import demo_data

#: 仓库根（源码运行时）。安装为 wheel 后这里指向 site-packages，
#: 因此所有资产解析都必须有 CWD / 就地重建的兜底，不能依赖它存在。
REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_asset(rel: Optional[str]) -> str:
    """把规格里的相对路径解析成实际可用的路径。

    顺序：原样（绝对路径或相对 CWD）→ 仓库根相对 → 回落 CWD 相对（供就地创建）。
    """
    if not rel:
        return ""
    p = Path(rel)
    if p.exists():
        return str(p)
    alt = REPO_ROOT / rel
    if alt.exists():
        return str(alt)
    return str(p)


def _csv_source(ks: KnowledgeSource) -> CsvSource:
    ex = ks.extra or {}
    path = resolve_asset(ks.path or "examples/products.csv")
    if not Path(path).exists():
        # 安装后仓库 examples/ 不在场 → 就地生成演示 CSV，保证开箱可跑
        path = demo_data.ensure_demo_csv(path or "examples/products.csv")
    return CsvSource(
        path,
        id_col=ex.get("id_col", "id"),
        title_col=ex.get("title_col", "title"),
        content_col=ex.get("content_col", "content"),
        tag_col=ex.get("tag_col"),
        category_col=ex.get("category_col"),
        source_name=ks.source_name or "products",
    )


def _detect_content_col(path: str, table: str, explicit: Optional[str]) -> str:
    """正文列名探测：显式指定优先；否则在表里挑 ``content`` → ``description``。

    演示表用的是 ``description``，真实业务表多数是 ``content``——写死任一个都会
    在另一种库上静默取到空正文（这正是之前"知识入库了但检索不到"的根因）。
    """
    if explicit:
        return explicit
    try:
        import sqlite3
        con = sqlite3.connect(path)
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}
        finally:
            con.close()
    except Exception:  # noqa: BLE001 —— 探测失败就不猜，交回默认值
        return "content"
    for cand in ("content", "description", "detail", "body"):
        if cand in cols:
            return cand
    return "content"


def _sqlite_source(ks: KnowledgeSource) -> SqliteSource:
    ex = ks.extra or {}
    path = resolve_asset(ks.path or "examples/cs_demo.db")
    if not Path(path).exists():
        # 只在「文件根本不存在」时就地建演示库；已存在的库**绝不**擅自建表，
        # 避免污染真实业务库（表缺失由 SqliteSource 报清晰错误）。
        path = demo_data.ensure_demo_sqlite(path or "examples/cs_demo.db")
    table = ex.get("table", demo_data.DEMO_TABLE)
    return SqliteSource(
        path,
        table,
        id_col=ex.get("id_col", "id"),
        title_col=ex.get("title_col", "title"),
        content_col=_detect_content_col(path, table, ex.get("content_col")),
        tag_col=ex.get("tag_col"),
        category_col=ex.get("category_col"),
        updated_at_col=ex.get("updated_at_col", "updated_at"),
        source_name=ks.source_name or "sqlite",
    )


def make_source(ks: KnowledgeSource) -> Any:
    """把一条 ``KnowledgeSource`` 变成可 `fetch(cursor)` 的数据源实例。"""
    t = (ks.type or "demo").lower()
    ex = ks.extra or {}
    if t == "demo":
        return DemoSource()
    if t == "csv":
        return _csv_source(ks)
    if t == "sqlite":
        return _sqlite_source(ks)
    if t == "sql":
        if not ks.url or not ks.query:
            raise ConnectorError("sql 源需要 url 与 query")
        return SqlSource(
            ks.url, ks.query,
            id_col=ex.get("id_col", "id"),
            title_col=ex.get("title_col", "title"),
            content_col=ex.get("content_col", "content"),
            tag_col=ex.get("tag_col"),
            category_col=ex.get("category_col"),
            updated_at_col=ex.get("updated_at_col"),
            source_name=ks.source_name or "sql",
        )
    if t == "rest":
        if not ks.url:
            raise ConnectorError("rest 源需要 url")
        return RestSource(
            ks.url, headers=ex.get("headers"),
            id_field=ex.get("id_field", "id"),
            title_field=ex.get("title_field", "title"),
            content_field=ex.get("content_field", "content"),
            tag_field=ex.get("tag_field"),
            category_field=ex.get("category_field"),
            source_name=ks.source_name or "rest",
        )
    raise ConnectorError("不支持的源类型: %s" % t)


def pick_source(spec: Optional[AgentSpec], source_type: Optional[str]
                ) -> Optional[KnowledgeSource]:
    """按类型挑一条规格里的知识源；``source_type`` 为空取第一条。"""
    sources = spec.knowledge_sources if spec else []
    if source_type:
        for s in sources:
            if (s.type or "").lower() == source_type.lower():
                return s
        return None
    return sources[0] if sources else None


def make_source_for(spec: Optional[AgentSpec],
                    source_type: Optional[str] = None) -> Tuple[Any, str]:
    """spec + 可选类型 → (数据源, 实际类型)。挑不到时回落内置演示源。"""
    ks = pick_source(spec, source_type)
    if ks is None:
        if source_type:
            raise ConnectorError("规格里没有类型为 %s 的知识源" % source_type)
        return DemoSource(), "demo"
    return make_source(ks), (ks.type or "demo").lower()
