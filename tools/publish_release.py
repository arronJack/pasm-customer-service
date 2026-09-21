# -*- coding: utf-8 -*-
"""publish_release —— 双端（Gitee + GitHub）建 Release 并上传发行产物附件。

本仓是**纯 Python 包**，没有安装包，所以附件是 `dist/` 里的
`sdist (.tar.gz)` 与 `wheel (.whl)` —— 给"离线装机 / 内网 / 想核对产物"的人用，
PyPI 仍是在线安装的主渠道。

用法
----
    # 1) 从 git HEAD 构建产物（**别用工作区**，否则可能把未提交的改动打进去）
    git archive HEAD | tar -x -C /tmp/src
    python -m build --outdir /tmp/out          # 在 /tmp/src 里跑

    # 2) 建 Release（默认读环境变量 GITEE_TOKEN / GITHUB_TOKEN）
    python tools/publish_release.py --ver 0.2.0 \\
        --title "v0.2.0 · 相关性闸门与分发链路" \\
        --body-file CHANGELOG.md \\
        --dist /tmp/out

    # 只想看看会发生什么，不真的发
    python tools/publish_release.py --ver 0.2.0 --body-file x.md --dist x --dry-run

令牌
----
优先 `GITEE_TOKEN` / `GITHUB_TOKEN` 环境变量；也可 `--token-file` 指向一个
每行 `名字=值` 的文件。**不要把令牌写进仓库。**

坑位备忘（都踩过）
------------------
  - Gitee 建 Release **必须带 `target_commitish`**，缺了报 400。
  - Gitee 上传附件的字段名是 **`file`**（multipart），文档写的 `attach_files` 会报
    `file is missing`；接口路径是 `/releases/{id}/attach_files`（用 release 的 **id**，
    不是 tag）。
  - Gitee 附件配额按仓 1GB，**发新版要删旧版附件**，否则某天忽然传不上去。
  - GitHub 上传走 `uploads.github.com`，`Content-Type` 要给
    `application/octet-stream`（或按文件后缀给准），否则偶发 422。
  - 两个平台的 token 权限不同：Gitee 用私人令牌；GitHub 用 classic PAT 的
    `repo` 权限（fine-grained 需要 Contents: Read and write）。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

GITEE_OWNER_REPO = "arronzheng/pasm-customer-service"
GITHUB_OWNER_REPO = "arronJack/pasm-customer-service"

TOKEN_ENV = {"gitee": "GITEE_TOKEN", "github": "GITHUB_TOKEN"}


# --------------------------------------------------------------------------- #
# 令牌
# --------------------------------------------------------------------------- #
def read_tokens(token_file: str = "") -> dict:
    """按 平台 -> token 读出令牌；找不到就留空（该平台跳过）。"""
    out = {}
    for plat, env in TOKEN_ENV.items():
        v = (os.environ.get(env) or "").strip()
        if v:
            out[plat] = v
    if token_file and os.path.isfile(token_file):
        with open(token_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip().lower()
                if k in TOKEN_ENV and v.strip():
                    out[k] = v.strip()
    return out


# --------------------------------------------------------------------------- #
# HTTP 小工具（只用标准库，本仓"零依赖"的承诺不能因为一个发布脚本破掉）
# --------------------------------------------------------------------------- #
def _req(url, token, data=None, method="GET", headers=None, ctype=None):
    h = {"User-Agent": "pasm-cs-release"}
    if token:
        h["Authorization"] = "token %s" % token
    if headers:
        h.update(headers)
    if ctype:
        h["Content-Type"] = ctype
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            raw = resp.read()
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                                    # noqa: BLE001
        return 0, str(e).encode("utf-8")


def _json(status, raw):
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:                                          # noqa: BLE001
        return {}


def _multipart(field, path):
    """手工拼 multipart/form-data —— 只为避开第三方依赖。"""
    boundary = "----pasm" + uuid.uuid4().hex
    name = os.path.basename(path)
    guess = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        blob = fh.read()
    body = b"".join([
        ("--%s\r\n" % boundary).encode(),
        ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (field, name)).encode(),
        ("Content-Type: %s\r\n\r\n" % guess).encode(),
        blob,
        ("\r\n--%s--\r\n" % boundary).encode(),
    ])
    return body, "multipart/form-data; boundary=%s" % boundary


# --------------------------------------------------------------------------- #
# Gitee
# --------------------------------------------------------------------------- #
def gitee_release(ver, title, body, dists, token, dry=False):
    tag = "v%s" % ver
    api = "https://gitee.com/api/v5/repos/%s/releases" % GITEE_OWNER_REPO
    payload = {
        "tag_name": tag,
        "name": title,
        "body": body,
        "target_commitish": tag,          # ★ 缺了报 400
        "prerelease": False,
    }
    if dry:
        print("[gitee][dry] POST %s tag=%s target=%s 附件=%d 个" % (api, tag, tag, len(dists)))
        return True
    st, raw = _req(api, token, data=json.dumps(payload).encode("utf-8"),
                   method="POST", ctype="application/json")
    if st not in (200, 201):
        print("[gitee][ERR] 建 Release 失败 %s %s" % (st, raw.decode("utf-8", "replace")[:400]))
        return None
    rid = _json(st, raw).get("id")
    print("[gitee][OK] Release 已建 id=%s tag=%s" % (rid, tag))

    for p in dists:
        data, ctype = _multipart("file", p)     # ★ 字段名必须是 file
        up = "%s/%s/attach_files" % (api, rid)
        st, raw = _req(up, token, data=data, method="POST", ctype=ctype)
        if st in (200, 201):
            print("[gitee][OK] 附件 %s" % os.path.basename(p))
        else:
            print("[gitee][ERR] 附件 %s 失败 %s %s"
                  % (os.path.basename(p), st, raw.decode("utf-8", "replace")[:300]))
    return rid


# --------------------------------------------------------------------------- #
# GitHub
# --------------------------------------------------------------------------- #
def github_release(ver, title, body, dists, token, dry=False):
    tag = "v%s" % ver
    api = "https://api.github.com/repos/%s/releases" % GITHUB_OWNER_REPO
    payload = {"tag_name": tag, "name": title, "body": body,
               "draft": False, "prerelease": False}
    if dry:
        print("[github][dry] POST %s tag=%s 附件=%d 个" % (api, tag, len(dists)))
        return True
    st, raw = _req(api, token, data=json.dumps(payload).encode("utf-8"),
                   method="POST", ctype="application/json",
                   headers={"Accept": "application/vnd.github+json"})
    if st not in (200, 201):
        print("[github][ERR] 建 Release 失败 %s %s" % (st, raw.decode("utf-8", "replace")[:400]))
        return None
    js = _json(st, raw)
    print("[github][OK] Release 已建 id=%s" % js.get("id"))

    tpl = js.get("upload_url", "")
    base = tpl.split("{")[0]
    for p in dists:
        name = os.path.basename(p)
        with open(p, "rb") as fh:
            blob = fh.read()
        up = "%s?name=%s" % (base, urllib.parse.quote(name))
        st, raw = _req(up, token, data=blob, method="POST",
                       ctype="application/octet-stream",
                       headers={"Accept": "application/vnd.github+json"})
        if st in (200, 201):
            print("[github][OK] 附件 %s" % name)
        else:
            print("[github][ERR] 附件 %s 失败 %s %s" % (name, st, raw.decode("utf-8", "replace")[:300]))
    return js.get("id")


def main(argv=None):
    ap = argparse.ArgumentParser(description="双端建 Release 并上传发行产物")
    ap.add_argument("--ver", required=True, help="版本号，如 0.2.0（tag 会自动加 v）")
    ap.add_argument("--title", default="", help="Release 标题；默认 v<ver>")
    ap.add_argument("--body-file", required=True, help="Release 正文（markdown 文件）")
    ap.add_argument("--dist", default="dist", help="产物目录，上传其中的 *.whl / *.tar.gz")
    ap.add_argument("--token-file", default="", help="每行 name=value 的令牌文件")
    ap.add_argument("--only", default="", help="只发某端：gitee 或 github")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    title = a.title or ("v%s" % a.ver)
    with open(a.body_file, "r", encoding="utf-8") as fh:
        body = fh.read()

    dists = []
    if os.path.isdir(a.dist):
        for n in sorted(os.listdir(a.dist)):
            if n.endswith((".whl", ".tar.gz")):
                dists.append(os.path.join(a.dist, n))
    print("[info] 版本=%s 附件=%d 个" % (a.ver, len(dists)))
    for d in dists:
        print("       %s (%d 字节)" % (os.path.basename(d), os.path.getsize(d)))

    tokens = read_tokens(a.token_file)
    ok = 0
    if a.only in ("", "gitee"):
        if tokens.get("gitee"):
            if gitee_release(a.ver, title, body, dists, tokens["gitee"], a.dry_run):
                ok += 1
        else:
            print("[warn] 无 Gitee 令牌，跳过")
    if a.only in ("", "github"):
        if tokens.get("github"):
            if github_release(a.ver, title, body, dists, tokens["github"], a.dry_run):
                ok += 1
        else:
            print("[warn] 无 GitHub 令牌，跳过")
    print("[done] 完成 %d 端" % ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
