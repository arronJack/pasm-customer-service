"""命令行入口：本地运行 / 演示 / 校验 / 平台导出。

示例
----
  # 演示：用内置数据跑通 DB→KB 链路，并展示幂等（第二次无新增）
  python -m pasm_cs.cli demo

  # 校验声明式规格
  python -m pasm_cs.cli validate

  # 按规格把知识源同步到本地 JSONL（dry-run，不依赖 pasm）
  # 不传 --source 时用 agent_spec.toml 里声明的第一个源（csv）
  python -m pasm_cs.cli run --out examples/kb_demo.jsonl
  python -m pasm_cs.cli run --source sqlite            # 指定源类型
  python -m pasm_cs.cli run --source sqlite --full     # 忽略游标全量重跑

  # 按规格真实灌入 PASM 资料库（需 pasm-framework 已安装）
  python -m pasm_cs.cli run --source csv --pasm

  # 导出各平台配置
  python -m pasm_cs.cli platform mcp
  python -m pasm_cs.cli platform coze

  # 普通人可直接对话的两种形态
  python -m pasm_cs.cli web            # 极简 Web 壳（离线检索或接 PASM）
  python -m pasm_cs.cli serve          # PASM 原生网关（站点 iframe / REST）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import demo_data, source_factory, web_run
from .connector import DBKBSyncConnector, FileKBSink, PasmKBSink  # noqa: F401
from .adapters.base import load_spec
from .studio_loader import write_scenario


def _ensure_demo_sqlite(db_path: str, *, rebuild: bool = False) -> str:
    """创建一个带 updated_at 的演示库。返回库路径（委托 demo_data，安装后同样可用）。"""
    return demo_data.ensure_demo_sqlite(db_path, rebuild=rebuild)


def _demo_sqlite() -> int:
    """SQLite 增量同步演示（零依赖）：首轮全量 → 插入新行 → 次轮只抓增量 → 三轮幂等。"""
    print("\n== SQLite 增量同步演示（agent_spec 的 knowledge.sync，零依赖）==")
    db = "examples/cs_demo.db"
    # 每次演示重建一个干净库，保证可重复
    db = _ensure_demo_sqlite(db, rebuild=True)

    src = source_factory.make_source(
        _ks("sqlite", db, source_name="faq"))
    sink = FileKBSink("examples/sqlite_kb.jsonl")
    conn = DBKBSyncConnector(src, sink, state_path="examples/sqlite_state.json")

    print("  [首轮·全量] ", end="")
    r1 = conn.sync()
    print(r1)

    # 模拟业务库新增一条
    demo_data.append_row(db, demo_data.DEMO_EXTRA_ROW)

    print("  [次轮·增量] 业务库新增 1 条 → ", end="")
    r2 = conn.sync()
    print(r2)
    assert r2.new == 1 and r2.fetched == 1, "增量失败：应只抓到 1 条新增！"

    print("  [三轮·幂等] 无变化 → ", end="")
    r3 = conn.sync()
    print(r3)
    assert r3.new == 0 and r3.fetched == 0, "幂等失败：无变化时不应有新条目！"

    print("  ✅ 增量同步正确：首轮全量 %d 条，次轮仅抓新增 %d 条，三轮 0 新增（幂等）。"
          % (r1.new, r2.new))
    return 0


def _ks(type_name: str, path=None, **extra):
    """快速构造一条 KnowledgeSource（供演示与 run 使用）。"""
    from .adapters.base import KnowledgeSource
    return KnowledgeSource(type=type_name, path=path, extra=dict(extra))


def _demo() -> int:
    # 清理历史 demo 专用 state 与产物，保证每次演示都是干净首跑
    for st in ("examples/demo_state.json", "examples/csv_state.json",
               "examples/sqlite_state.json", "examples/cs_demo.db",
               "examples/demo_kb.jsonl", "examples/csv_kb.jsonl",
               "examples/sqlite_kb.jsonl", "examples/sqlite_run.jsonl",
               "examples/run_kb.jsonl"):
        try:
            Path(st).unlink()
        except FileNotFoundError:
            pass
    out = Path("examples/demo_kb.jsonl")
    print("== Demo：内置业务数据 → 资料库（FileKBSink）==")
    sink = FileKBSink(str(out))
    conn = DBKBSyncConnector(source_factory.make_source(_ks("demo")), sink,
                             state_path="examples/demo_state.json")
    r1 = conn.sync()
    print("  第一次同步：%s" % r1)
    r2 = conn.sync()
    print("  第二次同步（幂等验证）：%s" % r2)
    print("  说明：两次内容相同，第二次 skipped=%d、new=%d，证明按指纹去重生效。"
          % (r2.skipped, r2.new))

    print("\n== CSV 数据源演示（examples/products.csv）→ 资料库 ==")
    sink2 = FileKBSink("examples/csv_kb.jsonl")
    conn2 = DBKBSyncConnector(
        source_factory.make_source(_ks("csv", "examples/products.csv",
                                       source_name="products")),
        sink2, state_path="examples/csv_state.json",
    )
    print("  同步：%s" % conn2.sync())
    _demo_sqlite()
    return 0


def _validate() -> int:
    spec = load_spec()
    print(spec.summary())
    print("\n各知识源：")
    for s in spec.knowledge_sources:
        print("  - type=%s path=%s url=%s" % (s.type, s.path, s.url))
    return 0


def _state_path_for(spec, source_kind: str) -> str:
    """按**源类型**派生的状态文件路径。

    早先所有 `--source` 共用 `spec.sync_state_path`，于是「先跑 sqlite 再跑 csv」
    会共用同一份游标与指纹集合 → 第二源被误判成 skipped（看着"没同步"其实是被
    上一个源的状态挡住了）。同源重跑仍幂等（这正是我们要的），跨源互不干扰。
    """
    base = Path(spec.sync_state_path) if spec.sync_state_path else Path("examples/connector_state.json")
    return str(base.with_name("%s__%s%s" % (base.stem, source_kind, base.suffix or ".json")))


def _run(args: argparse.Namespace) -> int:
    spec = load_spec()
    src_kind = (args.source or "").strip().lower() or None
    try:
        src, actual_kind = source_factory.make_source_for(spec, src_kind)
    except Exception as ex:  # noqa: BLE001 —— 规格/源配置类错误给可读提示而非堆栈
        print("构造数据源失败：%s" % ex)
        return 2

    if args.pasm:
        from .cs_agent import build_cs_agent, framework_available
        if not framework_available():
            print("需要 pasm-framework：pip install pasm-framework")
            return 3
        cs = build_cs_agent(spec.agent_id, persona=spec.persona,
                            kb_dir="./%s_kb" % spec.agent_id,
                            persist_dir="./%s_state" % spec.agent_id)
        sink: object = PasmKBSink(cs)
    else:
        out = args.out or "examples/run_kb.jsonl"
        sink = FileKBSink(out)

    conn = DBKBSyncConnector(src, sink,
                             state_path=_state_path_for(spec, actual_kind))
    print("源=%s 目的地=%s" % (actual_kind, type(sink).__name__))
    print("同步：%s" % conn.sync(full=args.full))
    return 0


def _serve(args: argparse.Namespace) -> int:
    """启动 PASM 原生 HTTP 网关（站点 <iframe> / REST），需 pasm-framework。"""
    spec = load_spec()
    if args.port:
        spec.platforms = dict(spec.platforms or {})
        spec.platforms["web_port"] = args.port
    from .adapters.web import start_server
    try:
        start_server(spec)
    except RuntimeError as ex:
        print(ex)
        return 3
    return 0


def _platform(args: argparse.Namespace) -> int:
    spec = load_spec()
    if args.name == "mcp":
        from .adapters.mcp import build_mcp_config
        print("MCP 配置（供 WorkBuddy/ClawHub/Claude Desktop 连接）：")
        import json
        print(json.dumps(build_mcp_config(spec), ensure_ascii=False, indent=2))
        print("\n启动方式：")
        print("  python -m pasm_cs.adapters.mcp            # 起 MCP 服务（stdio）")
        print("  python -m pasm_cs.adapters.mcp --selftest # 自检")
        print("\n说明：该服务用 cs_* 工具暴露专业客服智能体；")
        print("未装 pasm-framework 时 cs_ask 等会诚实返回「不可用」，cs_sync 落到 JSONL。")
    elif args.name == "coze":
        from .adapters.coze import to_coze_bot
        import json
        print(json.dumps(to_coze_bot(spec), ensure_ascii=False, indent=2))
    elif args.name == "character":
        from .adapters.coze import to_character_card
        import json
        print(json.dumps(to_character_card(spec), ensure_ascii=False, indent=2))
    elif args.name == "web":
        from .adapters.web import build_widget, build_rest_example
        print(build_widget("http://你的服务器", spec))
        import json
        print(json.dumps(build_rest_example(spec), ensure_ascii=False, indent=2))
    else:
        print("未知平台：%s（支持 mcp/coze/character/web）" % args.name)
        return 2
    return 0


def _studio() -> int:
    spec = load_spec()
    path = write_scenario(spec)
    print("已生成 Studio 场景配置：%s" % path)
    print("说明：当前 Studio（desktop/pasm_companion.py）NAV 固定 9 项，无外部导入入口；")
    print("该配置已对齐 Studio 的 persona / KB 源字段，未来加「导入场景」UI 即可一键加载。")
    print("普通人使用更推荐走 Web 壳：python -m pasm_cs.web_run")
    return 0


def _web(args: argparse.Namespace) -> int:
    if args.selftest:
        return 0 if web_run.selftest() else 1
    web_run.serve(port=args.port, use_pasm=args.pasm,
                  kb_path=getattr(args, "kb", None),
                  host=getattr(args, "host", "0.0.0.0"))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pasm_cs", description="PASM 专业客服系统 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("demo", help="内置数据演示 DB→KB 同步链路（幂等）")
    sub.add_parser("validate", help="校验声明式规格 agent_spec.toml")

    rp = sub.add_parser("run", help="按规格同步知识源到资料库")
    rp.add_argument("--source", default=None,
                    choices=["demo", "csv", "sqlite", "sql", "rest"],
                    help="知识源类型；不传则用规格里声明的第一个源（不再硬编码）")
    rp.add_argument("--out", default=None, help="dry-run 落盘 JSONL 路径")
    rp.add_argument("--full", action="store_true", help="忽略游标，全量重跑")
    rp.add_argument("--pasm", action="store_true", help="真实灌入 PASM 资料库（需 pasm-framework）")

    pp = sub.add_parser("platform", help="导出某平台配置")
    pp.add_argument("name", choices=["mcp", "coze", "character", "web"])

    sub.add_parser("studio", help="生成 Studio 场景配置文件（对齐 persona/KB）")

    mp = sub.add_parser("mcp", help="启动 MCP 服务（stdio，供 WorkBuddy/Claude 调用）")
    mp.add_argument("--persist-dir", default=None, help="落盘根目录，默认 ~/.pasm-cs-mcp")
    mp.add_argument("--selftest", action="store_true", help="本地自检，不起服务")

    sp = sub.add_parser("serve", help="启动 PASM 原生 HTTP 网关（站点 iframe / REST，需 pasm-framework）")
    sp.add_argument("--port", type=int, default=None, help="监听端口，默认用规格里的 web_port")

    wp = sub.add_parser("web", help="启动浏览器聊天壳（普通人直接对话）")
    wp.add_argument("--port", type=int, default=8080)
    wp.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（局域网可见）")
    wp.add_argument("--kb", default=None, help="指定 KB JSONL 路径")
    wp.add_argument("--pasm", action="store_true", help="接入真实 PASM 认知（需 pasm-framework）")
    wp.add_argument("--selftest", action="store_true", help="仅验证对话逻辑，不启服务")

    args = p.parse_args(argv)
    if args.cmd == "demo":
        return _demo()
    if args.cmd == "validate":
        return _validate()
    if args.cmd == "run":
        return _run(args)
    if args.cmd == "platform":
        return _platform(args)
    if args.cmd == "studio":
        return _studio()
    if args.cmd == "serve":
        return _serve(args)
    if args.cmd == "mcp":
        from .adapters.mcp import main as mcp_main
        mcp_argv = []
        if args.selftest:
            mcp_argv.append("--selftest")
        if args.persist_dir:
            mcp_argv += ["--persist-dir", args.persist_dir]
        return mcp_main(mcp_argv)
    if args.cmd == "web":
        return _web(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
