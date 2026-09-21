"""反例对照：证明 ``selfcheck.py`` 里的断言真能抓住它们要防的缺陷。

为什么需要这个文件
------------------
测试套件最常见的失效方式不是"报错"，而是**假绿**：断言写得太松（或压根没接线），
坏代码进来也照样通过，于是所有人以为有保障。本项目已经踩过两次同类坑
（`check_core_fork.py` 扫不到 `hidden_imports`、技能包构建早于正文修改）。

所以判定"检查有效"的**唯一**可信方法是反例对照：
    注入坏行为 → 断言必须变红；还原 → 断言必须复绿。
若注入后仍全绿，说明这套检查是假绿，必须修它自己。

注入的坏行为（都是本项目真实出现过、且不易察觉的）
--------------------------------------------------
  A. **内置演示知识不带同义词标签** —— ``DemoSource`` 原先把 ``tags`` 只填成分类
     （如 ``["售后"]``）。中文二字词不按字面切分，「售后」匹配不上「退货」，
     于是用户问「退货怎么操作」时演示数据里的「退换货政策」反而召不回来：
     "开箱即跑"的默认路径恰好是召回率最差的一条。
  B. **检索闸门被关掉** —— ``touches_surface`` 恒返回 True，则问
     「请问 CEO 的私人邮箱是多少」会靠正文里一个「邮箱」答成「电子发票」，
     即**答非所问**（客服场景下比答不上来更严重）。

用法
----
    python tools/falsify_checks.py      # 退出码 0=检查有效，1=存在假绿
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import selfcheck as SC                       # noqa: E402
from pasm_cs import cs_agent, web_run        # noqa: E402


def run_web_checks() -> list:
    """跑 ``check_web``，返回它记录的失败项（先清空，各轮互不影响）。"""
    SC.FAILURES.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        SC.check_web()
    return list(SC.FAILURES)


def report(tag: str, fails: list) -> None:
    if fails:
        print("  [%s] 抓到 %d 项失败：" % (tag, len(fails)))
        for f in fails:
            print("      - %s" % f)
    else:
        print("  [%s] 全绿（未抓到）" % tag)


def main() -> int:
    problems: list = []

    print("=" * 66)
    print("① 干净态：应全绿（否则说明工作区本身就是坏的）")
    print("=" * 66)
    base = run_web_checks()
    report("clean", base)
    if base:
        problems.append("干净态不绿：%s" % base)

    print()
    print("=" * 66)
    print("② 注入 A：内置知识不带同义词标签（旧 DemoSource 的行为）")
    print("=" * 66)
    from pasm_cs.demo_data import DEMO_ROWS
    orig_builtin = web_run.builtin_kb
    try:
        web_run.builtin_kb = lambda: [
            {"title": r[1], "content": r[2], "source": "builtin-demo",
             "tags": [r[3]], "category": r[3]}
            for r in DEMO_ROWS
        ]
        fa = run_web_checks()
    finally:
        web_run.builtin_kb = orig_builtin
    report("A 无同义词标签", fa)
    if not fa:
        problems.append("注入 A 未被抓到 → 「标签是召回旋钮」这条检查是假绿")

    print()
    print("=" * 66)
    print("③ 注入 B：关掉检索闸门（touches_surface 恒 True）")
    print("=" * 66)
    orig_ts = cs_agent.touches_surface
    try:
        cs_agent.touches_surface = lambda *a, **k: True
        fb = run_web_checks()
    finally:
        cs_agent.touches_surface = orig_ts
    report("B 闸门关掉", fb)
    if not fb:
        problems.append("注入 B 未被抓到 → 「不许答非所问」这条检查是假绿")

    print()
    print("=" * 66)
    print("④ 还原后复测：应恢复全绿")
    print("=" * 66)
    after = run_web_checks()
    report("restored", after)
    if after:
        problems.append("还原后仍失败：%s" % after)

    print()
    if problems:
        print("❌ 存在假绿：")
        for p in problems:
            print("  - %s" % p)
        return 1
    print("✅ 反例对照通过：注入全部被抓住，还原后恢复全绿 —— 这套检查是有效的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
