"""把同步连接器接进 pasm-framework 的插件。

用法（无需发包，内联注册即可）：

    from pasm_framework import BaseApplication, SimpleApplication
    from pasm_cs.plugin import DBKBSyncPlugin

    app = SimpleApplication("shop-cs", {"name": "小智", "role": "客服"},
        backend_config={
            "knowledge_base": {"enabled": True, "config": {"kb_dir": "./kb"}},
            "db_kb_sync": {"enabled": True, "class": DBKBSyncPlugin,
                           "config": {"source": "csv",
                                      "path": "examples/products.csv",
                                      "interval_seconds": 0,
                                      "state_path": "examples/connector_state.json"}},
        })

``on_init`` 时才懒加载连接器与数据源，因此：没装 sqlalchemy 也不影响导入；
``interval_seconds > 0`` 时启动后台线程周期同步，``interval_seconds == 0`` 则只注册、
由运维脚本/定时任务手动调用 ``plugin.sync_now()``。

``config.source`` 支持 ``demo / csv / sqlite / sql / rest``（复用
``pasm_cs.source_factory``，与 CLI / MCP 入口共用同一份映射，避免行为漂移）。

注意：本文件顶部的 pasm 依赖用 try/except 兜底为**最小替身基类**（不是 ``object``），
目的是让 ``pasm_cs`` 在没有安装 pasm-framework 的纯标准库环境下**不仅能 import，
还能实例化**（演示/单测用）。真正作为插件加载时，pasm 必然已安装，下面就是真类。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

try:  # pragma: no cover - 取决于运行环境
    from pasm_framework.plugins.core import BasePlugin, PluginContext
    _HAS_FW = True
except Exception:  # noqa: BLE001
    _HAS_FW = False

    class BasePlugin:  # type: ignore[no-redef]
        """无 pasm-framework 时的**最小替身基类**。

        早先这里直接 ``BasePlugin = object``，导致 ``object.__init__(self, config)``
        抛 ``TypeError: object.__init__() takes exactly one argument``——
        即"没装框架时也能 import 本模块"这句承诺只对 import 成立，
        一实例化就崩。用替身基类后，离线也能构造、单测连接器装配逻辑。
        """

        def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
            self.config = dict(config or {})

        def __repr__(self) -> str:
            return "<%s v%s (stub)>" % (self.name, self.version)

    class PluginContext:  # type: ignore[no-redef]
        """占位（离线替身）。"""


class DBKBSyncPlugin(BasePlugin):  # type: ignore[valid-type]
    name = "db_kb_sync"
    version = "0.1.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config or {})
        self._conn = None
        self._timer = None

    # —— 懒构造连接器（避免无谓的 import 失败）——
    def _build(self, app: Any) -> Any:
        from .connector import (  # 相对导入，确保与包一起分发
            DBKBSyncConnector, PasmKBSink,
        )
        from .source_factory import make_source
        from .adapters.base import KnowledgeSource

        source_kind = (self.config.get("source") or "demo").lower()
        # 统一走 source_factory，避免与 CLI / MCP 的映射再次漂移
        ex = {
            k: v for k, v in self.config.items()
            if k not in ("source", "state_path", "interval_seconds", "enabled",
                         "class", "source_name")
        }
        ks = KnowledgeSource(
            type=source_kind,
            path=self.config.get("path"),
            url=self.config.get("url"),
            query=self.config.get("query"),
            source_name=self.config.get("source_name", source_kind),
            extra=ex,
        )
        if source_kind == "sql" and not self.config.get("query"):
            raise ValueError("source='sql' 需要 `query` 配置项")
        source = make_source(ks)
        sink = PasmKBSink(app)
        return DBKBSyncConnector(
            source, sink,
            state_path=self.config.get("state_path"),
        )

    def on_init(self, ctx: Any) -> None:
        # 加载为真正的 pasm 插件时 ctx 是 PluginContext（有 .app）；
        # 离线替身场景只要调用方给了带 .app 的对象，也允许装配（便于单测）。
        if not _HAS_FW and not hasattr(ctx, "app"):
            return
        self._conn = self._build(ctx.app)
        interval = int(self.config.get("interval_seconds", 0) or 0)
        if interval > 0:
            import threading
            import time as _t

            def _loop() -> None:
                while True:
                    try:
                        self._conn.sync()
                    except Exception as ex:  # noqa: BLE001
                        # 单轮失败不应拖垮宿主；记录**真实原因**便于观测。
                        try:
                            ctx.store.setdefault("_sync_errors", []).append(
                                "%s: %s" % (type(ex).__name__, ex))
                        except Exception:  # noqa: BLE001 —— store 不可用也不能死循环
                            pass
                    _t.sleep(interval)

            self._timer = threading.Thread(
                target=_loop, name="pasm-db-kb-sync", daemon=True)
            self._timer.start()

    def stop(self) -> None:
        """停止后台同步线程（插件可能被热重载）。"""
        self._timer = None

    def sync_now(self, *, full: bool = False) -> Optional[Any]:
        """手动触发一次同步（运维/定时任务调用）。"""
        if self._conn is None:
            return None
        return self._conn.sync(full=full)
