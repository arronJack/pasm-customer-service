"""一键自检：把本项目的全部验收点跑一遍（离线可跑，无需任何第三方依赖）。

覆盖
----
  1. 连接器：demo/csv/sqlite 三种源 + 指纹去重幂等 + sqlite 增量游标
  2. 连接器错误路径：表不存在 → 立刻报可读错误（**不得**白等重试）
  3. 规格：agent_spec.toml 可解析且源类型齐全
  4. Web 壳：离线检索命中 / 无匹配回落 / --pasm 诚实降级
  5. MCP：自检 + **真实 stdio 子进程**端到端（畸形帧不杀服务、幂等、各源跑通）
  6. 平台导出：mcp / coze / character / web 配置都能生成

用法
----
    python tools/selfcheck.py            # 全跑，打印逐项结果
    python tools/selfcheck.py --fast     # 跳过 stdio 子进程测试

判据说明：每项都落在**可观察事实**上（返回值 / 退出码 / 进程存活），
不是"函数被调用了"。MCP 那项特意用子进程跑真实 stdio，因为协议层异常
只在"服务是否还活着"这一层才看得见。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

FAILURES: list = []


def check(cond: bool, msg: str) -> None:
    print("  %s %s" % ("v" if cond else "x", msg))
    if not cond:
        FAILURES.append(msg)


def section(title: str) -> None:
    print("\n== %s ==" % title)


# ---------------------------------------------------------------- 1/2 连接器
def check_connector() -> None:
    section("连接器（源 → 指纹去重 → 增量游标）")
    from pasm_cs import demo_data, source_factory
    from pasm_cs.adapters.base import KnowledgeSource
    from pasm_cs.connector import DBKBSyncConnector, ConnectorError, FileKBSink

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # demo 源：全量 → 幂等
        sink = FileKBSink(str(td / "demo.jsonl"))
        conn = DBKBSyncConnector(source_factory.make_source(KnowledgeSource(type="demo")),
                                 sink, state_path=str(td / "demo_state.json"))
        r1, r2 = conn.sync(), conn.sync()
        check(r1.new == 4, "demo 首轮 new=4（实际 %s）" % r1.new)
        check(r2.new == 0 and r2.skipped == 4, "demo 二次幂等 new=0（实际 %s）" % r2)

        # sqlite 源：增量游标
        db = demo_data.ensure_demo_sqlite(str(td / "cs.db"), rebuild=True)
        src = source_factory.make_source(
            KnowledgeSource(type="sqlite", path=db, extra={"table": "faq"}))
        sink2 = FileKBSink(str(td / "s.jsonl"))
        conn2 = DBKBSyncConnector(src, sink2, state_path=str(td / "s_state.json"))
        a = conn2.sync()
        check(a.new == 4 and a.cursor == "2026-01-04",
              "sqlite 首轮全量 4 条 + 游标正确（实际 %s / %r）" % (a.new, a.cursor))
        demo_data.append_row(db, demo_data.DEMO_EXTRA_ROW)
        b = conn2.sync()
        check(b.new == 1 and b.fetched == 1 and b.cursor == "2026-01-05",
              "sqlite 次轮只抓 1 条新增（实际 %s）" % b)
        c = conn2.sync()
        check(c.new == 0 and c.fetched == 0, "sqlite 三轮幂等（实际 %s）" % c)

        # 错误路径：表不存在 → 立刻 ConnectorError（不得走重试白等）
        bad = KnowledgeSource(type="sqlite", path=db, extra={"table": "no_such_table"})
        t0 = time.time()
        try:
            source_factory.make_source(bad).fetch(None)
            check(False, "缺表时应抛 ConnectorError")
        except ConnectorError as ex:
            dt = time.time() - t0
            check("没有表" in str(ex), "缺表错误信息可读（%s）" % str(ex)[:48])
            check(dt < 0.3, "缺表是确定性错误，未白等重试（耗时 %.2fs）" % dt)


# ---------------------------------------------------------------- 3 规格
def check_spec() -> None:
    section("声明式规格")
    from pasm_cs.adapters.base import load_spec
    spec = load_spec()
    kinds = [s.type for s in spec.knowledge_sources]
    check(spec.agent_id == "shop-cs", "agent_id 正确（%s）" % spec.agent_id)
    check({"csv", "sqlite", "demo"} <= set(kinds), "规格含 csv/sqlite/demo 源（%s）" % kinds)
    check(len(spec.capabilities) >= 1, "规格含能力声明（%d 条）" % len(spec.capabilities))


# ---------------------------------------------------------------- 4 Web 壳
def check_web() -> None:
    section("Web 壳（普通人直接对话）")
    from pasm_cs import web_run

    # 夹具必须**带上 tags**：检索闸门要求命中落在检索面（标题/标签/分类）上，
    # 只有标题的条目对"退货怎么操作"这类中文改写是召不回的（见 cs_agent.touches_surface）。
    # 真实同步进来的条目都带 tags（见 demo_data / agent_spec.toml 的 tag_col）。
    kb = [{"title": "退换货政策", "content": "签收 7 天内无理由退货，生鲜除外。",
           "tags": ["退货", "换货", "退款", "售后", "生鲜"]}]
    r1 = web_run.offline_reply("退货怎么操作", kb)
    check("退换货" in r1, "离线检索命中退货政策")
    r2 = web_run.offline_reply("今天天气真好 unrelated xyz", kb)
    check("离线" in r2, "无匹配时诚实回落离线说明")
    r3 = web_run.chat("退货怎么操作", kb=kb, use_pasm=True)
    check("真实认知不可用" in r3 or "退换货" in r3, "--pasm 走真实或诚实降级，不崩")

    # ★ 闸门的核心反例：只在**正文**里偶然重合、检索面完全不相干的提问，
    #   必须回答"查不到"而不是答非所问（这正是它存在的理由）
    kb2 = [{"title": "电子发票", "content": "发货次日发送电子发票至注册邮箱。",
            "tags": ["发票", "开票", "税务"]}]
    r_bad = web_run.offline_reply("请问 CEO 的私人邮箱是多少", kb2)
    check("离线" in r_bad and "发票" not in r_bad,
          "★ 正文偶然重合不许答非所问（CEO 邮箱 ≠ 电子发票）")

    # ★ 全新安装（还没跑过 run/demo，KB 文件不存在）也必须可用 ——
    # 否则 `pasm-cs web --selftest` 在干净环境里必然 AssertionError
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        items, builtin = web_run.ensure_kb(str(Path(td) / "nope.jsonl"))
        check(builtin is True and len(items) >= 4,
              "无业务资料时回落到内置演示知识（%d 条）" % len(items))
        r4 = web_run.offline_reply("退货怎么操作", items)
        check("退换货" in r4, "内置知识也能被检索命中（内置数据带同义词标签）")
        r5 = web_run.offline_reply("多久能发货", items)
        check("配送" in r5, "改写式提问也能召回（标签里有「发货/多久」）")

        # 真跑一次 selftest —— 但**把它指向空目录**，否则它读的是仓库里的
        # 运行时 KB 文件（内容随上次同步而变），断言就变得不可复现。
        old = web_run.DEFAULT_KB
        try:
            web_run.DEFAULT_KB = str(Path(td) / "nope.jsonl")
            try:
                ok = web_run.selftest()
                check(ok is True, "web selftest 在无 KB 时仍通过（回落内置知识）")
            except AssertionError as ex:
                check(False, "web selftest 失败：%s" % ex)
        finally:
            web_run.DEFAULT_KB = old


# ---------------------------------------------------------------- 5 MCP stdio
def check_mcp_stdio() -> None:
    section("MCP 服务（真实 stdio 子进程）")
    td = tempfile.mkdtemp(prefix="pasm_cs_mcp_")
    env = dict(os.environ)
    env["PASM_CS_MCP_QUIET"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "pasm_cs.adapters.mcp", "--persist-dir", td],
        cwd=str(REPO), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env,
    )

    def send(payload) -> bool:
        line = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        try:
            proc.stdin.write((line + "\n").encode("utf-8"))
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            # 子进程已死 → 写管道失败。这正是"服务被杀"的可观察证据。
            return False

    def recv(timeout: float = 8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                return None
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                return json.loads(line.decode("utf-8"))
            except Exception:
                continue
        return None

    try:
        check(send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"}}), "initialize 帧可发送")
        r = recv()
        check(bool(r) and "result" in r, "initialize 有响应")

        # ★ 畸形帧：params 是数组（协议允许但少见）
        check(send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": ["cs_status"]}), "畸形帧可发送")
        r = recv()
        check(r is not None, "畸形 params 帧有响应（未被静默丢弃）")
        check(proc.poll() is None, "★ 畸形帧之后服务进程仍存活")

        check(send({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}), "后续帧可发送")
        r = recv()
        names = [t["name"] for t in r["result"]["tools"]] if (r and "result" in r) else []
        check("cs_ask" in names, "畸形帧之后仍能正常 tools/list")

        send("{ not json ")
        r = recv()
        check(bool(r) and r.get("error", {}).get("code") == -32700, "非法 JSON 返回 Parse error")
        send({"jsonrpc": "2.0", "id": 5, "method": "nope/nope", "params": {}})
        r = recv()
        check(bool(r) and r.get("error", {}).get("code") == -32601, "未知方法返回 -32601")
        send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
              "params": {"name": "nope", "arguments": {}}})
        r = recv()
        check(bool(r) and r.get("error", {}).get("code") == -32602, "未知工具返回 -32602")

        # 幂等 + 各源
        send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
              "params": {"name": "cs_sync", "arguments": {"source": "demo"}}})
        r1 = recv()
        send({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
              "params": {"name": "cs_sync", "arguments": {"source": "demo"}}})
        r2 = recv()
        try:
            n1 = r1["result"]["structuredContent"]["new"]
            n2 = r2["result"]["structuredContent"]["new"]
            check(n1 >= 1 and n2 == 0, "cs_sync 首次 new=%s、二次 new=%s（幂等）" % (n1, n2))
        except Exception as ex:  # noqa: BLE001
            check(False, "cs_sync 结构化返回异常：%s" % ex)

        send({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
              "params": {"name": "cs_sync", "arguments": {"source": "sqlite"}}})
        r = recv()
        check(bool(r) and r["result"]["structuredContent"].get("ok") is True,
              "cs_sync --source sqlite 跑通")

        check(proc.poll() is None, "★ 全部畸形输入后服务进程仍存活")
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def check_mcp_selftest() -> None:
    section("MCP 自检（协议层，不起服务）")
    p = subprocess.run([sys.executable, "-m", "pasm_cs.adapters.mcp", "--selftest"],
                       cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    check(p.returncode == 0, "mcp --selftest 退出码 0")
    check("通过" in (p.stdout or ""), "自检报告通过")


# ------------------------------------------------- 4b 检索相关性闸门
def check_relevance_gate() -> None:
    """「答错内容」比「答不上来」严重 —— 这里守住"宁可说查不到"。

    为什么单独成节：闸门是**纯函数**，不需要 pasm-framework 就能验；
    而它的失效方式很隐蔽 —— 不会报错，只会开始**答非所问**。
    """
    section("检索相关性闸门（答错比答不上来更严重）")
    from pasm_cs.cs_agent import (DEFAULT_SCORE_FLOOR, select_knowledge,
                                  semantic_tokens, touches_surface)

    # ① 分词口径：单字不作数（「你」「么」这类高频字会造成大量误命中）
    check({"怎么", "么退", "退货"} <= semantic_tokens("怎么退货"),
          "中文按 2-gram 切分")
    check(semantic_tokens("a 我们") == {"我们"}, "单字 / 单字母不作数")

    # ② 检索面 = 标题 + 标签；正文**不算**检索面
    fact = {"title": "电子发票", "tags": ["发票", "开票"],
            "content": "发货次日发送电子发票至注册邮箱。", "score": 2.29}
    check(touches_surface(semantic_tokens("发票怎么开"), fact),
          "命中落在标题/标签上 → 算数")
    check(not touches_surface(semantic_tokens("CEO 的私人邮箱是多少"), fact),
          "★ 只撞正文里的「邮箱」→ 不算命中（此前正是这里答非所问）")

    # ③ 主判据：检索面命中即采纳
    check(len(select_knowledge("发票怎么开", [fact])) == 1, "检索面命中 → 采纳")

    # ④ 假命中且低于兜底门槛 → 拒绝（2.29 < 4.0）
    check(select_knowledge("CEO 的私人邮箱是多少", [fact]) == [],
          "★ 假命中（score 2.29 < %.1f）→ 拒绝" % DEFAULT_SCORE_FLOOR)

    # ⑤ 分数兜底：检索面没撞上但分数够高仍采纳 —— 防"改写式提问被漏判"
    strong = {"title": "配送时效", "tags": [],
              "content": "现货 24h 发货。", "score": 6.0}
    check(len(select_knowledge("多久能发货", [strong])) == 1,
          "分数兜底可救回强命中（改写式提问不被漏判）")

    # ⑥ 边界：空候选不抛异常
    check(select_knowledge("", []) == [], "空候选返回空列表（不抛异常）")

    # ⑦ 离线检索走同一套判据（两种模式行为必须一致）
    from pasm_cs import web_run
    kb = web_run.builtin_kb()
    check("配送" in web_run.offline_reply("多久能发货", kb),
          "★ 离线模式靠标签召回改写式提问")
    check("离线模式" in web_run.offline_reply("请问 CEO 的私人邮箱是多少", kb),
          "★ 离线模式同样不瞎答（答不上来就明说）")


# ---------------------------------------------------------------- 6 平台导出
def check_platforms() -> None:
    section("平台配置导出")
    from pasm_cs.adapters.base import load_spec
    from pasm_cs.adapters.coze import to_coze_bot, to_character_card
    from pasm_cs.adapters.mcp import build_mcp_config
    from pasm_cs.adapters.web import build_widget, build_rest_example
    spec = load_spec()
    check("mcpServers" in build_mcp_config(spec), "MCP 配置可生成")
    check("prompt" in to_coze_bot(spec), "Coze 机器人配置可生成")
    check("greeting" in to_character_card(spec), "Character 卡片可生成")
    check("<iframe" in build_widget("http://h", spec), "站点挂件片段可生成")
    check("chat" in build_rest_example(spec), "REST 示例可生成")


def main() -> int:
    fast = "--fast" in sys.argv
    print("pasm-customer-service 自检  (repo=%s)" % REPO)
    check_connector()
    check_spec()
    check_web()
    check_relevance_gate()
    check_mcp_selftest()
    if not fast:
        check_mcp_stdio()
    check_platforms()

    print("\n" + "=" * 46)
    if FAILURES:
        print("失败 %d 项：" % len(FAILURES))
        for f in FAILURES:
            print("  - %s" % f)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
