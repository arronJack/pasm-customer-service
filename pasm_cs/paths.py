"""运行时产物的落点常量（**单一来源**）。

为什么要有这个模块
------------------
原先 KB 产物路径散落在三处、且**互不一致**：

* ``cli._run`` 默认写 ``examples/run_kb.jsonl``；
* ``cli._demo_sqlite`` 写 ``examples/sqlite_kb.jsonl``；
* ``web_run.DEFAULT_KB`` 读 ``examples/sqlite_kb.jsonl``。

后果是个很典型的"看起来对、实际空"：用户按文档跑完 ``pasm-cs run``（默认落到
``run_kb.jsonl``），再打开 Web 壳 —— 它去读 ``sqlite_kb.jsonl``，于是显示
**资料库空、只会说"离线模式"**。同步明明成功了，界面却说没数据。

统一到一个常量后，"写"与"读"必然同源。

⚠️ 注意这里是**相对 CWD 的路径**（与 ``--out`` / ``--kb`` 的语义一致）：
安装为库后 CWD 未必是仓库根。要放到别处请显式传 ``--kb`` / ``--out``。
"""

from __future__ import annotations

#: 默认知识库（JSONL）落点：``run`` / ``demo`` 写它，Web 壳读它。
DEFAULT_KB_PATH = "examples/kb.jsonl"

__all__ = ["DEFAULT_KB_PATH"]
