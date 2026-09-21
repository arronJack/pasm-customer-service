"""内置演示数据（零依赖）：保证「开箱即跑」，且 ``pip install`` 之后依然可用。

为什么单独一个模块
------------------
演示 SQLite 库 / 演示 CSV 原先只存在于仓库的 ``examples/`` 目录。一旦
``pip install pasm-customer-service``，运行时的 CWD 不再等于仓库根，
``examples/cs_demo.db`` 找不到 → ``SqliteSource`` 报「no such table」，
``cs_sync`` / ``run --source sqlite`` 全线失效（但源码目录下跑得好好的，
属于「本地绿、安装后红」的隐蔽故障）。

把「生成演示数据」的能力放进包内后，任何运行形态（CLI / MCP / Web）都能在
目标文件缺失时**就地重建**，不再依赖仓库在不在 CWD 上。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Sequence, Tuple

#: 演示表名与列序（与 SqliteSource 默认列名对齐）
DEMO_TABLE = "faq"
DEMO_COLUMNS: Tuple[str, ...] = ("id", "title", "description", "category", "updated_at")

#: 首轮全量同步会用到的 4 行
DEMO_ROWS: Tuple[Tuple[str, ...], ...] = (
    ("F001", "会员等级与权益", "黄金会员全年包邮、专属客服、生日礼券。", "会员", "2026-01-01"),
    ("F002", "退换货政策", "签收 7 天内无理由退货，生鲜除外。", "售后", "2026-01-02"),
    ("F003", "配送时效", "现货 24h 发货，偏远地区 3-5 天。", "物流", "2026-01-03"),
    ("F004", "电子发票", "发货次日发送电子发票至注册邮箱。", "财务", "2026-01-04"),
)

#: 用于演示「增量」的新增行（时间戳最大）
DEMO_EXTRA_ROW: Tuple[str, ...] = (
    "F005", "跨境税费", "海外订单税费到岸计算，结算页实时展示。", "财务", "2026-01-05",
)

#: 演示 CSV（examples/products.csv 的等价内容）
DEMO_CSV_HEADER: Tuple[str, ...] = ("id", "title", "description", "category")
DEMO_CSV_ROWS: Tuple[Tuple[str, ...], ...] = (
    ("P001", "会员等级与权益", "黄金会员享全年包邮、专属客服、生日礼券；白银会员享月度包邮。", "会员"),
    ("P002", "退换货政策", "商品签收后 7 天内可无理由退货，需保持吊牌与包装完整，生鲜除外。", "售后"),
    ("P003", "配送时效", "现货 24 小时内发货，偏远地区 3-5 天送达，支持实时物流追踪。", "物流"),
    ("P004", "电子发票", "下单时可勾选电子发票，发票于发货次日发送至注册邮箱，支持增值税专票。", "财务"),
    ("P005", "会员积分", "消费 1 元积 1 分，积分可在结算页抵扣，100 分抵 1 元。", "会员"),
    ("P006", "售后服务", "支持 7×12 小时在线客服，紧急工单 2 小时内响应。", "售后"),
)


def _mkdirs(path: Path) -> None:
    parent = path.parent
    if str(parent) and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def ensure_demo_sqlite(path: str, *, rebuild: bool = False,
                       rows: Sequence[Sequence[str]] = DEMO_ROWS) -> str:
    """确保演示 SQLite 库存在（或 ``rebuild=True`` 时重建）并含 ``faq`` 表。返回路径。"""
    p = Path(path)
    _mkdirs(p)
    if p.exists() and not rebuild:
        # 已存在但可能是空文件/无表 —— 检查后按需补建，避免「找不到表」的误报
        try:
            con = sqlite3.connect(str(p))
            try:
                has = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (DEMO_TABLE,)).fetchone()
            finally:
                con.close()
            if has:
                return str(p)
        except sqlite3.DatabaseError:
            pass
    if p.exists() and rebuild:
        p.unlink()
    con = sqlite3.connect(str(p))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS %s(id TEXT, title TEXT, description TEXT, "
            "category TEXT, updated_at TEXT)" % DEMO_TABLE)
        con.executemany(
            "INSERT INTO %s VALUES(?,?,?,?,?)" % DEMO_TABLE, list(rows))
        con.commit()
    finally:
        con.close()
    return str(p)


def append_row(path: str, row: Sequence[str]) -> None:
    """往演示库里追加一行（模拟「业务库新增数据」）。"""
    con = sqlite3.connect(path)
    try:
        con.execute("INSERT INTO %s VALUES(?,?,?,?,?)" % DEMO_TABLE, tuple(row))
        con.commit()
    finally:
        con.close()


def ensure_demo_csv(path: str, *, rebuild: bool = False,
                    rows: Iterable[Sequence[str]] = DEMO_CSV_ROWS) -> str:
    """确保演示 CSV 存在（``utf-8-sig``，Excel 直接可读）。返回路径。"""
    import csv
    p = Path(path)
    _mkdirs(p)
    if p.exists() and not rebuild:
        return str(p)
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(DEMO_CSV_HEADER)
        for r in rows:
            w.writerow(list(r))
    return str(p)
