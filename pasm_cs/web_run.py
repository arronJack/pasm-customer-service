"""极简 Web 壳：让不懂技术的普通人用浏览器直接对话客服智能体。

两条路，按需自动选择：
  · 已装 ``pasm-framework`` 且本地模型可用 → 接入真实 PASM 认知（记忆 / 情绪 / LLM）。
  · 否则 → 「离线关键词检索」stub：从已同步的资料库 JSONL 里找最相关条目，
          并明确标注这是离线模式（诚实，不假装智能）。

若还没有任何已同步业务资料（例如刚 ``pip install`` 完），自动用**内置演示知识**
兜底并在启动时明确提示，做到"装上就有东西可聊"，而不是对着空资料库干瞪眼。

用法
----
  python -m pasm_cs.web_run            # 启动 HTTP 服务（默认 :8080，局域网可见）
  python -m pasm_cs.web_run --port 9000
  python -m pasm_cs.web_run --host 127.0.0.1   # 仅本机可访问
  python -m pasm_cs.web_run --selftest # 不启服务，仅验证对话逻辑（CI / 冒烟用）

普通人部署：跑起来后，把 http://<服务器IP>:8080 发给大家，浏览器打开即聊。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

#: 默认读哪个知识库 —— 与 `pasm-cs run` 的默认写入落点**同源**（见 pasm_cs/paths.py）。
#: 两处一旦不同，"同步成功但界面说没数据"就会复发。
from .paths import DEFAULT_KB_PATH as DEFAULT_KB  # noqa: E402

INDEX_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>专业客服 · PASM</title>
<style>
  body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;color:#222}
  .wrap{max-width:720px;margin:0 auto;display:flex;flex-direction:column;height:100vh}
  header{background:#2b6de0;color:#fff;padding:14px 18px;font-weight:600}
  #log{flex:1;overflow:auto;padding:16px}
  .msg{padding:10px 13px;border-radius:12px;margin:8px 0;max-width:80%;line-height:1.5}
  .u{background:#2b6de0;color:#fff;margin-left:auto}
  .b{background:#fff;border:1px solid #e3e6ea}
  form{display:flex;gap:8px;padding:12px;border-top:1px solid #e3e6ea;background:#fff}
  input{flex:1;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:15px}
  button{padding:10px 18px;border:0;border-radius:8px;background:#2b6de0;color:#fff;font-size:15px}
</style></head>
<body><div class="wrap">
  <header>小智 · 专业客服（PASM 驱动）</header>
  <div id="log"></div>
  <form id="f"><input id="q" autocomplete="off" placeholder="输入您的问题，例如：退货怎么操作？">
  <button>发送</button></form>
</div>
<script>
const log=document.getElementById('log'),q=document.getElementById('q'),f=document.getElementById('f');
function add(text,cls){const d=document.createElement('div');d.className='msg '+cls;d.textContent=text;log.appendChild(d);log.scrollTop=log.scrollHeight;}
f.onsubmit=async e=>{e.preventDefault();const v=q.value.trim();if(!v)return;add(v,'u');q.value='';
  try{const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:v})});
    const j=await r.json();add(j.reply,'b');}catch(err){add('网络错误：'+err,'b');}};
add('您好，我是小智，您的问题我随时为您解答。','b');
</script></body></html>"""


def load_kb(path: str = None) -> list:
    p = Path(path or DEFAULT_KB)
    items = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if "_fp" in rec:  # FileKBSink 落盘的带 _fp
                    rec = {k: v for k, v in rec.items() if k != "_fp"}
                items.append(rec)
            except Exception:
                pass
    return items


def builtin_kb() -> list:
    """内置演示知识（来自 ``demo_data``），保证**全新安装也有东西可聊**。

    否则 `pip install` 之后直接跑 `pasm-cs web`，资料库是空的：任何提问都只会得到
    「[离线模式] 未接入大模型」，用户会以为坏掉了。这里让 Web 壳在"还没有任何已同步
    资料"时用内置演示知识兜底，并**明确标注**这是内置数据而非真实业务资料。

    ``tags`` 一并带上（不是只取分类）—— 离线检索也按"检索面"判定，
    同义词标签是改写式提问能被召回的前提。
    """
    from .demo_data import DEMO_ROWS, split_tags
    return [{"title": r[1], "content": r[2], "source": "builtin-demo",
             "tags": split_tags(r[4]), "category": r[3]}
            for r in DEMO_ROWS]


def ensure_kb(path: str = None) -> tuple:
    """取可用资料库：已同步的优先，没有则用内置演示知识。返回 ``(items, builtin)``。"""
    items = load_kb(path)
    if items:
        return items, False
    return builtin_kb(), True


# —— 真实认知的进程内缓存 ——
# 早先每个请求都 `build_cs_agent(...)` 新建一个智能体：记忆/会话在两次提问之间
# **完全断掉**（客服记不住上句），且每次都重新载入 KB、重新初始化插件，慢且浪费。
# 现在按 agent_id 缓存一个常驻实例，线程安全地复用。
_AGENTS: dict = {}
_AGENTS_LOCK = threading.Lock()


def get_pasm_agent(agent_id: str = None, persona: dict = None):
    """取（或首次构造）常驻的客服智能体。pasm-framework 缺席时抛 RuntimeError。"""
    from .cs_agent import build_cs_agent
    from .adapters.base import load_spec
    spec = load_spec()
    aid = agent_id or spec.agent_id
    with _AGENTS_LOCK:
        agent = _AGENTS.get(aid)
        if agent is None:
            agent = build_cs_agent(aid, persona=persona or spec.persona,
                                   kb_dir="./%s_kb" % aid,
                                   persist_dir="./%s_state" % aid)
            _AGENTS[aid] = agent
        return agent


def _score(message: str, blob: str) -> int:
    tokens = []
    # 英文 / 数字词
    tokens += re.findall(r"[A-Za-z0-9_]+", message)
    # 中文按「字 + 2-gram」切分，避免整句当一个 token 导致无法命中
    for seg in re.findall(r"[\u4e00-\u9fff]+", message):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i + 2])
    return sum(1 for t in tokens if t in blob)


#: 离线兜底的门槛：至少要有这么多个 token 与条目重合才算命中。
#: 取 2 而非 1 —— 实测「请问 CEO 的私人邮箱是多少」会靠正文里一个「邮箱」
#: 撞上「电子发票」（1 个 token），于是答非所问。宁可说"查不到"。
OFFLINE_MIN_TOKENS = 2


def _item_blob(it: dict) -> str:
    """一条资料的可检索文本：标题 + 正文 + 标签（标签是人工维护的同义词面）。"""
    return " ".join([
        str(it.get("title") or ""),
        str(it.get("content") or ""),
        " ".join(str(t) for t in (it.get("tags") or [])),
    ])


def offline_reply(message: str, kb: list) -> str:
    """无大模型时的诚实兜底：只做关键词检索，且**明确标注**自己是离线模式。

    判据与真实认知的 ``cs_agent.select_knowledge`` 同构，避免"两种模式行为不一致"：
    先看**检索面命中**（标题/标签），再退回给整体分数兜底。
    """
    from .cs_agent import semantic_tokens, touches_surface

    msg = (message or "").strip()
    qt = semantic_tokens(msg)

    best, best_score, best_on_surface = None, 0, False
    for it in kb:
        s = _score(msg, _item_blob(it))
        on_surface = bool(touches_surface(qt, it)) and s > 0
        # 排序键：检索面命中优先，其次比分数（写成元组比较，语义直白）
        if (best is None
                or (on_surface, s) > (best_on_surface, best_score)):
            best, best_score, best_on_surface = it, s, on_surface

    hit = best is not None and best_score > 0 and (
        best_on_surface or best_score >= OFFLINE_MIN_TOKENS)
    if hit:
        return ("[离线关键词检索] %s\n%s"
                % (best.get("title", ""), best.get("content", "")))
    return ("[离线模式] 我目前未接入本地大模型，只能检索已同步的资料库。"
            "管理员可运行 `python -m pasm_cs.cli run --source sqlite --pasm` "
            "接入真实 PASM 认知（记忆/情绪/LLM 对话）。")


def chat(message: str, kb: list = None, use_pasm: bool = False) -> str:
    kb = kb if kb is not None else load_kb()
    if use_pasm:
        try:
            agent = get_pasm_agent()        # 复用常驻实例：记忆/会话才连续
            return agent.ask(message, session_id="web")
        except Exception as ex:  # noqa: BLE001
            # 真实认知不可用时诚实回落离线检索，不假装
            return offline_reply(message, kb) + "\n（真实认知不可用：%s）" % ex
    return offline_reply(message, kb)


def _make_handler(kb: list, use_pasm: bool):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/"):
                self._send(404, b'{"error":"not found"}')
                return
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            if self.path != "/api/chat":
                self._send(404, b'{"error":"not found"}')
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(n) if n else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                reply = chat(data.get("message", ""), kb=kb, use_pasm=use_pasm)
                self._send(200, json.dumps({"reply": reply}, ensure_ascii=False).encode("utf-8"))
            except Exception as ex:  # noqa: BLE001
                self._send(500, json.dumps({"error": str(ex)}, ensure_ascii=False).encode("utf-8"))

        def log_message(self, *args):  # 静默默认访问日志
            pass

    return Handler


def serve(port: int = 8080, use_pasm: bool = False, kb_path: str = None,
          host: str = "0.0.0.0"):
    """启动 Web 壳。

    用 ``ThreadingHTTPServer`` 而非 ``HTTPServer``：单个慢请求（接了本地 LLM 时
    一次问答可能十几秒）不会把**其他所有访客**堵在队列里——客服场景必须并发。
    """
    from http.server import ThreadingHTTPServer
    kb, builtin = ensure_kb(kb_path)
    httpd = ThreadingHTTPServer((host, port), _make_handler(kb, use_pasm))
    httpd.daemon_threads = True
    shown = "127.0.0.1" if host in ("127.0.0.1", "localhost") else "<本机IP>"
    print("客服 Web 壳已启动： http://%s:%d/  （Ctrl+C 退出）" % (shown, port))
    print("监听：%s:%d | 资料库条目数：%d | 真实 PASM 认知：%s"
          % (host, port, len(kb), "开" if use_pasm else "关(离线检索)"))
    if builtin:
        print("提示：尚未同步业务资料，当前用的是**内置演示知识**。"
              "执行 `pasm-cs run --source sqlite` 灌入演示库，或跑 `pasm-cs demo`。")
    if host == "0.0.0.0":
        print("提示：0.0.0.0 表示对局域网开放；仅本机自用请加 --host 127.0.0.1。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()


def selftest() -> bool:
    # 用 ensure_kb 而非 load_kb：全新安装（还没跑过 run/demo）也应有东西可检索，
    # 否则这个自检在干净环境里必然失败，等于"自检本身就坏"。
    kb, builtin = ensure_kb()
    print("资料库条目数：%d%s" % (len(kb), "（内置演示知识）" if builtin else ""))
    r1 = chat("退货怎么操作", kb=kb)
    print("Q: 退货怎么操作\nA: %s" % r1)
    assert "退换货" in r1, "离线检索未命中退货政策！"
    r2 = chat("今天天气真好 unrelated xyz", kb=kb)
    print("Q: 今天天气真好\nA: %s" % r2)
    assert "离线" in r2, "无匹配时应回落离线说明！"
    # use_pasm 在未装框架时必须诚实回落（不能抛异常、也不能假装智能）
    r3 = chat("退货怎么操作", kb=kb, use_pasm=True)
    if _framework_missing():
        assert "离线" in r3, "未装框架时 use_pasm 应诚实回落离线！"
        assert "真实认知不可用" in r3, "回落时必须标注真实原因！"
        print("Q: 退货怎么操作 (--pasm)\nA: %s" % r3)
    print("✅ Web 壳对话逻辑自测通过（离线关键词检索 + 无匹配回落 + --pasm 诚实降级）。")
    return True


def _framework_missing() -> bool:
    try:
        from .cs_agent import framework_available
        return not framework_available()
    except Exception:  # noqa: BLE001
        return True


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（局域网可见）")
    ap.add_argument("--pasm", action="store_true", help="接入真实 PASM 认知（需 pasm-framework）")
    ap.add_argument("--selftest", action="store_true", help="仅验证对话逻辑，不启服务")
    ap.add_argument("--kb", default=None, help="指定 KB JSONL 路径")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(0 if selftest() else 1)
    serve(port=a.port, use_pasm=a.pasm, kb_path=a.kb, host=a.host)
