# -*- coding: utf-8 -*-
"""回归：画布 ↔ 宿主 的 `/host/*` 端点契约（防止「前端调了后端没有」的静默 404）。

背景：
  `canvas_server.py` 里 47 个 `/host/*` 端点平铺在一条近 2000 行的 `if path == ...` 链里
  （321~2317 行），没有路由表；`bridge.ts` 侧散落着对应的调用。
  两端各写一份字符串 ⇒ 新增/改名端点时**极易只改一边**，表现为点了没反应（静默失败，不报错）。

本脚本做的事：
  1. 从 `canvas_server.py` 抽出服务端路由（精确匹配 `path == "..."` 与前缀 `startswith("...")`）
  2. 从 `bridge.ts`（主库 + 副库）抽出前端调用的 `/host/*`
  3. 双向比对：
     - 前端调了、后端没有 → **FAIL**（真会 404）
     - 后端有、前端没用 → 提示（可能是给别处预留，不算错）
  4. **不可达路由检测**（AST）：路由分支被写在其所在函数体内某条顶层 `return` 之后
     → 永远不会执行 → **FAIL**

第 4 项的由来（真事故）：
  `/host/plugins/install|toggle|uninstall` 三个 POST 端点曾经被追加到文件末尾，
  结果落在了 `_handle_ingest()` 内部、且位于第 1958 行 `return` **之后** ——
  语法合法、静态检查全绿、端点确实「写了」，但永远走到 `do_POST` 末尾的 404。
  这类 bug 不会报错，只会表现为「点插件安装没反应」，所以必须用 AST 兜住。

用法：
    python _verify/check_canvas_routes.py
"""
from __future__ import annotations

import ast
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVER = os.path.join("app", "core", "canvas_server.py")
# 2026-09-27 整改 A4：端点按域迁出 canvas_server.py 到独立路由模块后，
# 只读单文件会让迁出的端点从「服务端路由」里消失 → 前端调用它反而误报
# 「静默 404」（契约检查开天窗）。这里把服务端路由来源列全。
# ⚠️ 约定：以后再拆出新的路由模块（如 canvas_routes_post.py），一并加进此列表。
SERVER_FILES = [
    SERVER,
    os.path.join("app", "core", "canvas_routes_get.py"),
    os.path.join("app", "core", "canvas_routes_post.py"),
    # 2026-10-15：多角色配音编排端点（/host/dub-plan|dub-execute|dub-to-timeline）拆到
    # canvas_routes_dub.py（canvas_routes_post.py 已 1932 行逼近 2000 阈值）。
    os.path.join("app", "core", "canvas_routes_dub.py"),
    # 2026-10-17：粗剪审核卡端点（/host/rough-cut/apply|export）拆到
    # canvas_routes_roughcut.py（canvas_routes_post.py 已 1936 行，同 dub 先例）。
    os.path.join("app", "core", "canvas_routes_roughcut.py"),
]
CLIENTS = [
    # P0-1 Phase 2（2026-10-18）：tauri 侧 src/libtv 副本已删除，两宿主共用真源包，
    # 画布前端调用面只需扫 packages/libtv 一处。
    os.path.join("vendor", "packages", "libtv", "src", "bridge.ts"),
    # ── 新增的前端编排模块也必须登记，否则它调用的端点对契约检查「隐身」 ──
    # 2026-09-14：generationQueue.ts 承载 /host/generation/submit|status|list|cancel
    # 四个异步生成端点（任务制），只扫 bridge.ts 会漏掉它们。
    # ⚠️ 约定：以后新建「直接 fetch /host/*」的前端模块，请一并加进这个列表。
    os.path.join("vendor", "packages", "libtv", "src", "generationQueue.ts"),
    # 2026-09-14：projectZip.ts 承载 /host/project-snapshot/export|import 两个工程快照端点
    os.path.join("vendor", "packages", "libtv", "src", "projectZip.ts"),
    # 2026-09-14：stage3dScene.ts（暂未直接调 /host/*，但归属画布域）
    os.path.join("vendor", "packages", "libtv", "src", "stage3dScene.ts"),
    # 2026-09-14：poseThumbCache.ts（同上）
    os.path.join("vendor", "packages", "libtv", "src", "magnetic", "poseThumbCache.ts"),
    # 2026-10-05（刀 A4）：canvasRun.ts 承载 /host/canvas-run（「运行到此处」的后端规划）。
    # 不登记它，新端点对契约检查就是隐身的（与 generationQueue 同一条约定）。
    os.path.join("vendor", "packages", "libtv", "src", "canvasRun.ts"),
    # 2026-10-15：dubOrchestration.ts 承载 /host/dub-plan|dub-execute|dub-to-timeline
    # （多角色配音编排；bridge.ts 已近规模阈值 ⇒ 照 hostCompliance 先例另开文件）。
    os.path.join("vendor", "packages", "libtv", "src", "dubOrchestration.ts"),
    # 2026-10-17：hostRoughCut.ts 承载 /host/rough-cut/apply|export（画布粗剪审核卡；
    # 同 dubOrchestration 约定 —— 直接 fetch /host/* 的前端模块必须登记）。
    os.path.join("vendor", "packages", "libtv", "src", "hostRoughCut.ts"),
]

_PATH_LIT = r'[\'"`](/host/[A-Za-z0-9_\-/{}$.]+)[\'"`]'


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def server_routes(src: str):
    """返回 (exact, prefixes)：精确路由集合 与 startswith 前缀集合。

    服务端有四种写法，都得认，否则会误报/漏检：
      - `path == "/host/x"`
      - `path in ("/host/x", "/host/y")`   ← 元组写法（如 ai-config-patch / providers）
      - `path.startswith("/host/x")`
      - `@_route_get("/host/x")` / `@_route_post("/host/x")`  ← **路由表注册（P1-1 起的新写法）**

    ⚠️ 第 4 种必须认：不认的话，迁进路由表的端点会从「服务端路由」里消失，
    前端调用它时本脚本反而看不见，等于给契约检查开了个后门。
    """
    exact = set(re.findall(r'path\s*==\s*' + _PATH_LIT, src))
    exact |= set(re.findall(r'(?:self\.)?path\.split\(""\?""\)\[0\]\s*==\s*' + _PATH_LIT, src))
    for group in re.findall(r'path\s+in\s+\(([^)]*)\)', src):
        exact |= set(re.findall(_PATH_LIT, group))
    exact |= set(re.findall(r'@_route_(?:get|post)\(\s*' + _PATH_LIT, src))
    prefixes = set(re.findall(r'path\.startswith\(\s*' + _PATH_LIT, src))
    return exact, prefixes


def _strip_ts_comments(src: str) -> str:
    """剥掉 TS/JS 的**整行注释**与 JSDoc 块注释，再拿去扫端点。

    ★ 2026-10-05 加（踩到假阳性）：某前端模块在文档注释里写了 ``/host/generation/*``
    说明数据流，守卫把它当成「前端调用了 /host/generation」并报「服务端没实现」。
    **注释里的路径不是调用** —— 不剥注释的话，往后谁写文档提到端点都会误报，
    最终逼着大家"绕开写文档"，比误报本身更糟。

    ⚠️ 只能剥**行首**的 ``//``（含缩进）：URL 里的 ``http://`` 不能被误剥。
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)      # JSDoc / 块注释
    src = re.sub(r"^[ \t]*//.*$", "", src, flags=re.M)   # 整行行注释
    return src


def client_paths(src: str):
    """前端调用过的 /host/* 路径（已剔除注释，见 `_strip_ts_comments`）。

    注意：bridge.ts 大量使用模板字符串 `` `${BRIDGE}/host/xxx` ``，
    所以不能只匹配「引号紧跟 /host/」，得直接扫 `/host/` 起始的片段。
    模板占位 `${...}` 归一化为 `*`，便于与服务端前缀路由比较。
    """
    found = set()
    for raw in re.findall(r"/host/[A-Za-z0-9_\-/{}$.]+", _strip_ts_comments(src)):
        p = re.sub(r"\$\{[^}]*\}", "*", raw)
        # 去掉末尾残留的分隔符/标点
        p = p.rstrip("/.,;:")
        if p.endswith("/*"):
            p = p[:-2] + "*"
        found.add(p)
    return found


def client_pairs(src: str):
    """前端调用过的 **(方法, 路径)** 二元组。

    ★ 2026-10-05（刀 A4 第 1 项）新增。**为什么必须有**：只比路径会漏掉
    「前端 POST、后端只注册 GET」这类错配 —— `/host/model-preload` 正是如此静默 404 的
    （后端 handler 里 `self.command == "POST"` 那段分支直接成了不可达代码）。

    判定：扫 `fetch(...)` 调用，在调用尾巴 ~260 字符内找 `method: "POST"`，
    找不到就按 GET（fetch 默认 GET）。路径中的 `${...}` 归一化为 `*`。
    """
    pairs = set()
    for m in re.finditer(r"fetch\(\s*([`\"'])(.*?)\1([\s\S]{0,260})", _strip_ts_comments(src)):
        url, tail = m.group(2), m.group(3)
        if "/host/" not in url:
            continue
        p = re.sub(r"\$\{[^}]*\}", "*", url)
        p = re.sub(r"^.*?(/host/)", r"\1", p)     # 去掉 `${BRIDGE}` 之类前缀
        p = p.split("?")[0].split("#")[0].rstrip("/")
        if not p.startswith("/host/"):
            continue
        mm = re.search(r"method\s*:\s*[\"'](\w+)[\"']", tail, re.I)
        pairs.add(((mm.group(1) if mm else "GET").upper(), p))
    return pairs


_ROUTE_CMP = re.compile(r"path\s*(?:==|in\b|startswith)")


def unreachable_routes(src: str):
    """用 AST 找出「写在所在函数体顶层 return 之后」的路由分支。

    只查函数体**顶层**的 return（即 `body[idx]`），不进入 if/for/try ——
    否则会把 `if x: return` 之后的正常代码误判成死代码。

    返回 [(所在函数名, 起始行, 路由表达式)]。
    """
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        for idx, st in enumerate(body):
            if not isinstance(st, ast.Return):
                continue
            tail = body[idx + 1:]
            if not tail:
                continue
            # 把尾部语句包进临时 Module 便于 walk
            seg_mod = ast.Module(body=tail, type_ignores=[])
            for sub in ast.walk(seg_mod):
                if not isinstance(sub, ast.Compare):
                    continue
                seg = ast.get_source_segment(src, sub) or ""
                if not _ROUTE_CMP.search(seg):
                    continue
                out.append((node.name, sub.lineno, " ".join(seg.split())[:80]))
            break  # 只看第一条顶层 return，后面的都属于同一段死区
    return out


def legacy_routes(src: str) -> set:
    """老 if 链里的路由（`path == "..."` / `path in (...)`），不含路由表注册。

    用来查「同一个端点既在路由表又留在老链里」—— 表是优先分发的，
    老链那条会变成死代码（和插件端点当年一模一样的死法）。

    ⚠️ 必须传**单个方法体**（见 method_bodies）：GET 与 POST 同名端点
    （如 /host/video-batch 的查询与启动）是合法的，整文件扫描会误判。
    """
    exact = set(re.findall(r'path\s*==\s*' + _PATH_LIT, src))
    for group in re.findall(r'path\s+in\s+\(([^)]*)\)', src):
        exact |= set(re.findall(_PATH_LIT, group))
    return exact


def method_bodies(src: str) -> dict:
    """按 do_GET / do_POST 切出方法体源码 → {方法名: 源码}。

    重复注册检测必须**按 HTTP 方法**分别做：同名不同方法是正常设计。
    """
    out: dict = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
            "do_GET",
            "do_POST",
        ):
            seg = ast.get_source_segment(src, node) or ""
            out[node.name] = out.get(node.name, "") + "\n" + seg
    return out


def table_routes(src: str) -> set:
    """用 @_route_get / @_route_post 注册进路由表的端点。"""
    return set(re.findall(r'@_route_(?:get|post)\(\s*' + _PATH_LIT, src))


def covered(path: str, exact: set, prefixes: set) -> bool:
    if path in exact:
        return True
    base = path.split("*")[0]
    return any(base.startswith(pre) or path.startswith(pre) for pre in prefixes)


def main() -> int:
    exact, prefixes = set(), set()
    srcs = []
    for rel in SERVER_FILES:
        if not os.path.exists(os.path.join(ROOT, rel)):
            continue
        text = _read(rel)
        srcs.append(f"# ==== {rel} ====\n{text}")
        e, p = server_routes(text)
        exact |= e
        prefixes |= p
    # [3]/[4] 走 AST + 正则，需要完整源码 —— 拼接全部服务端路由文件
    # （各文件顶层结构独立，拼接后 AST 仍可解析；行号含各文件自身上下文）。
    server_src = "\n".join(srcs)

    client_all = set()
    per_client = {}
    for rel in CLIENTS:
        if not os.path.exists(os.path.join(ROOT, rel)):
            per_client[rel] = None
            continue
        paths = client_paths(_read(rel))
        per_client[rel] = paths
        client_all |= paths

    print(f"服务端精确路由 {len(exact)} · 前缀路由 {len(prefixes)}")
    for rel, paths in per_client.items():
        tag = "缺失文件" if paths is None else f"{len(paths)} 个调用"
        print(f"  前端 {rel}: {tag}")

    # 前端调了但后端没有
    broken = sorted(p for p in client_all if not covered(p, exact, prefixes))
    # 后端有但前端没用
    unused = sorted(p for p in exact if p not in client_all
                    and not any(p.startswith(c.split("*")[0]) and c.endswith("*") for c in client_all))

    # ── [0] 路由表内部重复注册（★ 2026-10-05 新增；此前只查"表 vs 老 if 链"）──
    #
    # 为什么必须查：`_route_get/_route_post` 对同一路径**二次注册会直接 raise**，
    # 而 raise 发生在**类定义期** ⇒ 整个画布服务起不来（import 就炸）。
    # 2026-10-05 实际发生过一次：新增 /host/canvas-run 时没发现该端点已存在，
    # 重复定义把 `import canvas_routes_post` 打成 ValueError。
    # 旧守卫只看「路由表 vs 老 if 链」，**表内重复完全漏检** —— 这次补上。
    dup_reg = []
    seen_reg: dict = {}
    for rel in SERVER_FILES:
        if not os.path.exists(os.path.join(ROOT, rel)):
            continue
        t = _read(rel)
        for meth, pat in (("GET", r'@_route_get\(\s*' + _PATH_LIT),
                          ("POST", r'@_route_post\(\s*' + _PATH_LIT)):
            for p in re.findall(pat, t):
                key = (meth, p)
                if key in seen_reg:
                    dup_reg.append(f"{meth} {p}（{seen_reg[key]} 与 {rel}）")
                else:
                    seen_reg[key] = rel
    print("\n[0] 路由表内部重复注册（会 raise ⇒ 服务 import 即失败）")
    if dup_reg:
        for d in sorted(set(dup_reg)):
            print(f"  ✗ {d}")
    else:
        print(f"  ✓ 无（GET+POST 共 {len(seen_reg)} 条，路径唯一）")

    print("\n[1] 前端调用但服务端没实现（会静默 404）")
    if broken:
        for p in broken:
            print(f"  ✗ {p}")
    else:
        print("  ✓ 无")

    # ── [1b] 方法错配：路径存在、但**方法**没注册（★ 2026-10-05 新增）──
    # 只比路径会漏掉这类错配：前端 POST、后端只注册 GET ⇒ 静默 404，
    # 而且后端 handler 里按 self.command 写的 POST 分支会变成不可达代码。
    server_pairs = set()
    for rel in SERVER_FILES:
        if not os.path.exists(os.path.join(ROOT, rel)):
            continue
        t = _read(rel)
        for p in re.findall(r'@_route_get\(\s*' + _PATH_LIT, t):
            server_pairs.add(("GET", p))
        for p in re.findall(r'@_route_post\(\s*' + _PATH_LIT, t):
            server_pairs.add(("POST", p))
    _bodies = method_bodies(server_src)
    for p in legacy_routes(_bodies.get("do_GET", "")):
        server_pairs.add(("GET", p))
    for p in legacy_routes(_bodies.get("do_POST", "")):
        server_pairs.add(("POST", p))
    server_paths = {pp for _m, pp in server_pairs}
    method_mismatch = []
    for rel in CLIENTS:
        if not os.path.exists(os.path.join(ROOT, rel)):
            continue
        for meth, p in client_pairs(_read(rel)):
            if "*" in p or p not in server_paths:
                continue                     # 前缀/未实现路由交给 [1] 判
            if (meth, p) not in server_pairs:
                have = sorted({m for m, pp in server_pairs if pp == p})
                method_mismatch.append((rel, meth, p, have))
    print("\n[1b] 方法错配（路径在、方法没注册 ⇒ 前端拿到 404）")
    if method_mismatch:
        for rel, meth, p, have in method_mismatch:
            print(f"  ✗ {rel} 以 {meth} 调用 {p}，但服务端只注册了 {'/'.join(have)}")
    else:
        print("  ✓ 无")

    print("\n[2] 服务端已实现但前端未调用（信息，不算错）")
    for p in unused[:40]:
        print(f"  · {p}")
    if len(unused) > 40:
        print(f"  · …另有 {len(unused) - 40} 个")

    print("\n[3] 服务端「写了但永远走不到」的路由（死代码 · 表现为点了没反应）")
    dead = unreachable_routes(server_src)
    if dead:
        for fn, ln, expr in dead:
            print(f"  ✗ {fn}() 第 {ln} 行  {expr}")
    else:
        print("  ✓ 无")

    print("\n[4] 路由表与老 if 链重复注册（老链那条会变成死代码）")
    # 按 HTTP 方法分别比对：GET 表 vs do_GET 老链、POST 表 vs do_POST 老链。
    bodies = method_bodies(server_src)
    dup = set()
    for _method, _deco in (("do_GET", "get"), ("do_POST", "post")):
        table_m = set(re.findall(r'@_route_' + _deco + r'\(\s*' + _PATH_LIT, server_src))
        legacy_m = legacy_routes(bodies.get(_method, ""))
        dup |= table_m & legacy_m
    dup = sorted(dup)
    if dup:
        for p in dup:
            print(f"  ✗ {p}  同时在路由表和老链里 —— 迁进表后请把老链的分支删掉")
    else:
        n_table = len(re.findall(r'@_route_(?:get|post)\(\s*' + _PATH_LIT, server_src))
        n_legacy = len(legacy_routes(bodies.get("do_GET", ""))
                       | legacy_routes(bodies.get("do_POST", "")))
        print(f"  ✓ 无（路由表 {n_table} 条 / 老链 {n_legacy} 条，按方法比对不重叠）")

    print()
    if broken:
        print(f"✗ 发现 {len(broken)} 个断链端点：")
        for p in broken:
            print("   -", p)
    if dead:
        print(f"✗ 发现 {len(dead)} 条不可达路由：")
        for fn, ln, expr in dead:
            print(f"   - {fn}() L{ln}: {expr}")
    if dup:
        print(f"✗ 发现 {len(dup)} 个重复注册端点：")
        for p in dup:
            print("   -", p)
    if method_mismatch:
        print(f"✗ 发现 {len(method_mismatch)} 处方法错配（前端会拿到 404）：")
        for _rel, meth, p, have in method_mismatch:
            print(f"   - {p}: 前端 {meth} vs 服务端 {'/'.join(have)}")
    if dup_reg:
        print(f"✗ 发现 {len(set(dup_reg))} 处路由表内部重复注册（服务会 import 失败）：")
        for d in sorted(set(dup_reg)):
            print(f"   - {d}")
    if broken or dead or dup or method_mismatch or dup_reg:
        return 1
    print("OK 画布端点契约一致（路径 + 方法）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
