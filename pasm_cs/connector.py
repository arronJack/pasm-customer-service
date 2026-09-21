"""DB→KB 同步连接器（核心原型）。

把业务数据库 / API / 文件的结构化数据，转换成 PASM 资料库条目
``{title, content, source, tags}``（与 ``pasm_framework`` 的 ``knowledge_base.ingest`` 对齐），
增量同步、按指纹去重、可断点续传。

设计原则（与 PASM 内核一致，且保证"开箱即跑"）：
- 核心逻辑**只依赖标准库**，无需 pasm / sqlalchemy 即可单测与演示；
- 数据源（Source）与目的地（Sink）都是可插拔 Protocol，方便接 CSV / SQL / REST；
- 真·PASM 接入仅通过一个薄适配层 ``PasmKBSink``，不污染核心逻辑；
- 去重用「内容指纹 + 状态文件」，既支持全量重跑幂等，也支持按游标增量。
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# KB 条目字段（必须与 pasm_framework knowledge_base.ingest 对齐）
EXPECTED_FIELDS = ("title", "content", "source", "tags")


@dataclass
class KBItem:
    """一条待入库的知识。``ref`` 是业务主键，用于指纹去重。"""

    title: str
    content: str
    source: str
    tags: List[str] = field(default_factory=list)
    category: str = "kb"
    ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "tags": list(self.tags),
            "category": self.category,
        }

    def fingerprint(self) -> str:
        h = hashlib.sha1()
        h.update((self.ref or self.title).encode("utf-8"))
        h.update(self.content.encode("utf-8"))
        return h.hexdigest()


@dataclass
class SyncReport:
    fetched: int = 0
    new: int = 0
    skipped: int = 0
    cursor: Optional[str] = None
    elapsed: float = 0.0

    def __str__(self) -> str:
        return (
            f"SyncReport(fetched={self.fetched}, new={self.new}, "
            f"skipped={self.skipped}, cursor={self.cursor!r}, "
            f"elapsed={self.elapsed:.2f}s)"
        )


class ConnectorError(Exception):
    pass


# ============================================================ 数据源

class DemoSource:
    """内置演示数据源：模拟「商品/知识表」，无需任何外部依赖即可跑通链路。

    ★ 演示数据只有**一个来源**：``pasm_cs.demo_data``。这里不再自带一份副本。

    为什么必须这样（曾经是个真缺陷）
    --------------------------------
    本类原先自己硬编码了 4 条演示数据，且 ``tags`` 只填了分类（如 ``["售后"]``）。
    而检索相关性闸门（``cs_agent.select_knowledge``）要求**命中落在标题/标签上**——
    「售后」这个词组不出「退货」这个 2-gram（中文二字词不按字面切分），于是
    用户问「退货怎么操作」时，演示数据里的「退换货政策」**反而召不回来**：
    「开箱即跑」的默认路径恰好是召回率最差的一条路。

    把数据源收敛到 ``demo_data``（那份带同义词标签）之后，演示路径与真实
    同步路径口径一致：问「多久能发货」能命中「配送时效」（标签里有「发货/多久」）。
    """

    name = "demo"

    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None) -> None:
        self._rows = rows if rows is not None else _demo_rows()

    def fetch(self, cursor: Optional[str] = None) -> Tuple[List[KBItem], Optional[str]]:
        items: List[KBItem] = []
        for r in self._rows:
            items.append(KBItem(
                title=str(r.get("title", "")).strip(),
                content=str(r.get("description", r.get("content", ""))).strip(),
                source="demo",
                tags=[str(t).strip() for t in (r.get("tags") or []) if str(t).strip()],
                category=str(r.get("category", "kb")),
                ref=str(r.get("id", r.get("title", ""))),
            ))
        return items, None


def _demo_rows() -> List[Dict[str, Any]]:
    """把 ``demo_data.DEMO_ROWS`` 转成本数据源认识的 dict 形态（唯一来源）。"""
    from .demo_data import DEMO_ROWS, split_tags
    out: List[Dict[str, Any]] = []
    for r in DEMO_ROWS:
        # 行格式：(id, title, description, category, tags_csv, updated_at)
        out.append({
            "id": r[0], "title": r[1], "description": r[2],
            "category": r[3], "tags": split_tags(r[4]),
        })
    return out


class CsvSource:
    """CSV 文件数据源。适合把导出的业务表（商品/工单/FAQ）喂进资料库。"""

    name = "csv"

    def __init__(
        self,
        path: str,
        *,
        id_col: str = "id",
        title_col: str = "title",
        content_col: str = "content",
        tag_col: Optional[str] = None,
        category_col: Optional[str] = None,
        source_name: str = "csv",
    ) -> None:
        self.path = Path(path)
        self.id_col = id_col
        self.title_col = title_col
        self.content_col = content_col
        self.tag_col = tag_col
        self.category_col = category_col
        self.source_name = source_name

    def fetch(self, cursor: Optional[str] = None) -> Tuple[List[KBItem], Optional[str]]:
        if not self.path.exists():
            raise ConnectorError("CSV 不存在: %s" % self.path)
        items: List[KBItem] = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                title = (row.get(self.title_col) or "").strip()
                content = (row.get(self.content_col) or "").strip()
                if not title and not content:
                    continue
                tags = []
                if self.tag_col and row.get(self.tag_col):
                    tags = [t.strip() for t in str(row[self.tag_col]).split(",") if t.strip()]
                category = (row.get(self.category_col) or "kb") if self.category_col else "kb"
                items.append(KBItem(
                    title=title or content[:60],
                    content=content,
                    source=self.source_name,
                    tags=tags,
                    category=str(category).strip(),
                    ref=str(row.get(self.id_col) or title),
                ))
        return items, None


def _sqlalchemy_available() -> bool:
    try:
        import sqlalchemy  # type: ignore
        return True
    except ImportError:  # pragma: no cover
        return False


def _with_retry(fn, retries: int = 3, backoff: float = 0.5,
                retry_on: Optional[Tuple[type, ...]] = None):
    """对 transient 故障做指数退避重试（数据库连接抖动 / 超时）。

    ``retry_on`` 为 ``None`` 时对除 ``KeyboardInterrupt`` / ``SystemExit`` 之外的所有
    异常重试；显式给出元组时**只重试**这些类型，其余异常立刻抛出——避免把
    「表不存在 / SQL 语法错」这类**确定性**错误白白重试 3 轮（每次还 sleep）。

    ``retries <= 1`` 视为不重试。
    """
    attempts = max(1, int(retries or 1))
    last: Optional[BaseException] = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as e:  # noqa: BLE001
            if retry_on is not None and not isinstance(e, retry_on):
                raise
            last = e
            if i < attempts:
                time.sleep(backoff * (2 ** (i - 1)))
    raise ConnectorError("重试 %d 次仍失败: %s" % (attempts, last))


class SqlSource:
    """SQL 数据源（可选依赖 sqlalchemy）。把查询结果映射成知识条目。

    增量同步：提供 ``updated_at_col`` 后，``fetch(cursor)`` 会把游标作为绑定参数
    ``:cursor`` 透传给 ``query``——请在 SQL 里写 ``WHERE updated_at > :cursor``
    （或自行用 ``:cursor`` 占位），即可只拉新增/变更的行。
    """

    name = "sql"

    def __init__(
        self,
        url: str,
        query: str,
        *,
        id_col: str = "id",
        title_col: str = "title",
        content_col: str = "content",
        tag_col: Optional[str] = None,
        category_col: Optional[str] = None,
        updated_at_col: Optional[str] = None,
        source_name: str = "sql",
        retries: int = 3,
        retry_backoff: float = 0.5,
    ) -> None:
        self.url = url
        self.query = query
        self.id_col = id_col
        self.title_col = title_col
        self.content_col = content_col
        self.tag_col = tag_col
        self.category_col = category_col
        self.updated_at_col = updated_at_col
        self.source_name = source_name
        self.retries = retries
        self.retry_backoff = retry_backoff

    def _rows(self, cursor):
        from sqlalchemy import create_engine, text  # type: ignore
        engine = create_engine(self.url)
        with engine.connect() as conn:
            stmt = text(self.query)
            if cursor is not None and self.updated_at_col:
                stmt = stmt.bindparams(cursor=cursor)
            return [dict(r._mapping) for r in conn.execute(stmt)]

    def fetch(self, cursor: Optional[str] = None) -> Tuple[List[KBItem], Optional[str]]:
        try:
            rows = _with_retry(lambda: self._rows(cursor), self.retries, self.retry_backoff)
        except ConnectorError:
            if not _sqlalchemy_available():
                raise ConnectorError(
                    "SqlSource 需要 sqlalchemy：pip install sqlalchemy")
            raise
        items: List[KBItem] = []
        for d in rows:
            title = str(d.get(self.title_col) or "").strip()
            content = str(d.get(self.content_col) or "").strip()
            if not title and not content:
                continue
            tags = []
            if self.tag_col and d.get(self.tag_col):
                tags = [t.strip() for t in str(d[self.tag_col]).split(",") if t.strip()]
            category = (d.get(self.category_col) or "kb") if self.category_col else "kb"
            items.append(KBItem(
                title=title or content[:60],
                content=content,
                source=self.source_name,
                tags=tags,
                category=str(category).strip(),
                ref=str(d.get(self.id_col) or title),
            ))
        return items, None


class SqliteSource:
    """SQLite 数据源（标准库 sqlite3，**零依赖即可演示真实增量同步**）。

    这是演示「DB→KB 增量自生长」的最佳载体：无需装任何包，就能看到
    「只同步新增/变更的行」的游标增量效果。生产可换成 ``SqlSource``(sqlalchemy)。

    增量机制：按 ``updated_at_col``（ISO 字符串时间戳，可直接比较）排序；
    首次 ``cursor=None`` 全量，返回 ``max(updated_at)`` 作为新游标；后续
    ``WHERE updated_at > cursor`` 只拉新增/变更行。
    """

    name = "sqlite"

    def __init__(
        self,
        database: str,
        table: str,
        *,
        id_col: str = "id",
        title_col: str = "title",
        content_col: str = "content",
        tag_col: Optional[str] = None,
        category_col: Optional[str] = None,
        updated_at_col: str = "updated_at",
        source_name: str = "sqlite",
        retries: int = 3,
        retry_backoff: float = 0.5,
    ) -> None:
        self.database = database
        self.table = table
        self.id_col = id_col
        self.title_col = title_col
        self.content_col = content_col
        self.tag_col = tag_col
        self.category_col = category_col
        self.updated_at_col = updated_at_col
        self.source_name = source_name
        self.retries = retries
        self.retry_backoff = retry_backoff

    def _rows(self, cursor):
        import sqlite3
        con = sqlite3.connect(self.database)
        con.row_factory = sqlite3.Row
        try:
            # 先做 schema 预检：表/列不存在属**确定性**错误，不该走重试（否则白等 1.5s）
            names = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            if self.table not in names:
                raise ConnectorError(
                    "SQLite 库 %s 里没有表 %r（现有：%s）"
                    % (self.database, self.table,
                       ", ".join(sorted(names)) or "无"))
            cols = {r[1] for r in con.execute("PRAGMA table_info(%s)" % self.table)}
            missing = [c for c in (self.id_col, self.title_col, self.content_col,
                                   self.updated_at_col if cursor else None)
                       if c and c not in cols]
            if missing:
                raise ConnectorError(
                    "表 %s 缺少列 %s（现有：%s）"
                    % (self.table, ", ".join(missing), ", ".join(sorted(cols))))
            if cursor:
                q = "SELECT * FROM %s WHERE %s > ? ORDER BY %s ASC" % (
                    self.table, self.updated_at_col, self.updated_at_col)
                params = (cursor,)
            else:
                q = "SELECT * FROM %s ORDER BY %s ASC" % (
                    self.table, self.updated_at_col)
                params = ()
            return [dict(r) for r in con.execute(q, params).fetchall()]
        finally:
            con.close()

    def fetch(self, cursor: Optional[str] = None) -> Tuple[List[KBItem], Optional[str]]:
        import sqlite3
        try:
            # 只重试临时性故障（库忙/被锁、IO 抖动）；schema 错误由 _rows 直接抛 ConnectorError
            rows = _with_retry(lambda: self._rows(cursor), self.retries,
                               self.retry_backoff,
                               retry_on=(sqlite3.OperationalError, OSError))
        except sqlite3.OperationalError as ex:
            raise ConnectorError(
                "SQLite 访问 %s.%s 失败（可能被占用）：%s"
                % (self.database, self.table, ex))
        items: List[KBItem] = []
        max_ts: Optional[str] = cursor
        for d in rows:
            title = str(d.get(self.title_col) or "").strip()
            content = str(d.get(self.content_col) or "").strip()
            if not title and not content:
                continue
            tags = []
            if self.tag_col and d.get(self.tag_col):
                tags = [t.strip() for t in str(d[self.tag_col]).split(",") if t.strip()]
            category = (d.get(self.category_col) or "kb") if self.category_col else "kb"
            ts = str(d.get(self.updated_at_col) or "")
            items.append(KBItem(
                title=title or content[:60],
                content=content,
                source=self.source_name,
                tags=tags,
                category=str(category).strip(),
                ref=str(d.get(self.id_col) or title),
            ))
            if ts and (max_ts is None or ts > max_ts):
                max_ts = ts
        return items, max_ts


class RestSource:
    """REST API 数据源（可选依赖 requests）。把 JSON 列表映射成知识条目。"""

    name = "rest"

    def __init__(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        id_field: str = "id",
        title_field: str = "title",
        content_field: str = "content",
        tag_field: Optional[str] = None,
        category_field: Optional[str] = None,
        source_name: str = "rest",
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self.id_field = id_field
        self.title_field = title_field
        self.content_field = content_field
        self.tag_field = tag_field
        self.category_field = category_field
        self.source_name = source_name

    def fetch(self, cursor: Optional[str] = None) -> Tuple[List[KBItem], Optional[str]]:
        try:
            import urllib.request
        except ImportError as ex:  # pragma: no cover
            raise ConnectorError("RestSource 需要 urllib（标准库自带）。%s" % ex)
        req = urllib.request.Request(self.url, headers=self.headers or {})
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        items: List[KBItem] = []
        for d in rows:
            if not isinstance(d, dict):
                continue
            title = str(d.get(self.title_field) or "").strip()
            content = str(d.get(self.content_field) or "").strip()
            if not title and not content:
                continue
            tags = []
            if self.tag_field and d.get(self.tag_field):
                val = d[self.tag_field]
                tags = [str(t).strip() for t in (val if isinstance(val, list) else str(val).split(","))]
            category = (d.get(self.category_field) or "kb") if self.category_field else "kb"
            items.append(KBItem(
                title=title or content[:60],
                content=content,
                source=self.source_name,
                tags=tags,
                category=str(category).strip(),
                ref=str(d.get(self.id_field) or title),
            ))
        return items, None


# ============================================================ 目的地

class FileKBSink:
    """落盘 JSONL 的目的地，用于演示与单测（无需 pasm-framework）。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen: set = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._seen.add(json.loads(line)["_fp"])
                except Exception:
                    pass

    def known_hashes(self) -> set:
        return set(self._seen)

    def ingest(self, items: List[Dict[str, Any]]) -> int:
        n = 0
        with self.path.open("a", encoding="utf-8") as f:
            for it in items:
                fp = hashlib.sha1(
                    ((it.get("title", "") or "") + "|" + (it.get("content", "") or "")).encode("utf-8")
                ).hexdigest()
                if fp in self._seen:
                    continue
                rec = dict(it)
                rec["_fp"] = fp
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                self._seen.add(fp)
                n += 1
        return n


class PasmKBSink:
    """真·PASM 接入：把条目交给 ``CustomerServiceAgent.ingest``（即 knowledge_base.ingest）。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    def known_hashes(self) -> set:
        # PASM 知识库自身有去重，这里不二次去重，交给内核处理。
        return set()

    def ingest(self, items: List[Dict[str, Any]]) -> int:
        # 移除连接器内部字段（_fp 等），只传内核认识的字段。
        clean = [{k: v for k, v in it.items() if k in EXPECTED_FIELDS or k == "category"}
                 for it in items]
        return self.app.ingest(clean)


# ============================================================ 连接器本体

class DBKBSyncConnector:
    """把数据源的增量，按指纹去重后灌入目的地。"""

    def __init__(
        self,
        source: Any,
        sink: Any,
        *,
        state_path: Optional[str] = None,
        transform=None,
    ) -> None:
        self.source = source
        self.sink = sink
        self.state_path = state_path
        self.transform = transform or (lambda it: it.to_dict())
        self._state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path and Path(self.state_path).exists():
            try:
                return json.loads(Path(self.state_path).read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"cursor": None, "hashes": []}

    def _save_state(self) -> None:
        if self.state_path:
            Path(self.state_path).write_text(
                json.dumps(self._state, ensure_ascii=False), encoding="utf-8"
            )

    def sync(self, *, full: bool = False) -> SyncReport:
        """执行一次同步。``full=True`` 忽略游标从头拉。"""
        t0 = time.time()
        cursor = None if full else self._state.get("cursor")
        known = set(self.sink.known_hashes()) | set(self._state.get("hashes", []))

        items, new_cursor = self.source.fetch(cursor)
        report_new = 0
        report_skip = 0
        to_ingest: List[Dict[str, Any]] = []

        for it in items:
            fp = it.fingerprint()
            if fp in known:
                report_skip += 1
                continue
            to_ingest.append(self.transform(it))
            known.add(fp)
            self._state.setdefault("hashes", []).append(fp)
            report_new += 1

        if to_ingest:
            self.sink.ingest(to_ingest)

        self._state["cursor"] = new_cursor
        self._save_state()
        return SyncReport(
            fetched=len(items),
            new=report_new,
            skipped=report_skip,
            cursor=new_cursor,
            elapsed=time.time() - t0,
        )
