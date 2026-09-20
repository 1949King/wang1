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
CLIENTS = [
    os.path.join("vendor", "shiguang-canvas", "src", "bridge.ts"),
    os.path.join("vendor", "AI-Canvas-tauri", "src", "libtv", "bridge.ts"),
    # ── 新增的前端编排模块也必须登记，否则它调用的端点对契约检查「隐身」 ──
    # 2026-09-14：generationQueue.ts 承载 /host/generation/submit|status|list|cancel
    # 四个异步生成端点（任务制），只扫 bridge.ts 会漏掉它们。
    # ⚠️ 约定：以后新建「直接 fetch /host/*」的前端模块，请一并加进这个列表。
    os.path.join("vendor", "shiguang-canvas", "src", "generationQueue.ts"),
    # 2026-09-14：projectZip.ts 承载 /host/project-snapshot/export|import 两个工程快照端点
    os.path.join("vendor", "shiguang-canvas", "src", "projectZip.ts"),
    # 2026-09-14：stage3dScene.ts（暂未直接调 /host/*，但归属画布域）
    os.path.join("vendor", "shiguang-canvas", "src", "stage3dScene.ts"),
    # 2026-09-14：poseThumbCache.ts（同上）
    os.path.join("vendor", "shiguang-canvas", "src", "magnetic", "poseThumbCache.ts"),
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


def client_paths(src: str):
    """前端调用过的 /host/* 路径。

    注意：bridge.ts 大量使用模板字符串 `` `${BRIDGE}/host/xxx` ``，
    所以不能只匹配「引号紧跟 /host/」，得直接扫 `/host/` 起始的片段。
    模板占位 `${...}` 归一化为 `*`，便于与服务端前缀路由比较。
    """
    found = set()
    for raw in re.findall(r"/host/[A-Za-z0-9_\-/{}$.]+", src):
        p = re.sub(r"\$\{[^}]*\}", "*", raw)
        # 去掉末尾残留的分隔符/标点
        p = p.rstrip("/.,;:")
        if p.endswith("/*"):
            p = p[:-2] + "*"
        found.add(p)
    return found


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
    """
    exact = set(re.findall(r'path\s*==\s*' + _PATH_LIT, src))
    for group in re.findall(r'path\s+in\s+\(([^)]*)\)', src):
        exact |= set(re.findall(_PATH_LIT, group))
    return exact


def table_routes(src: str) -> set:
    """用 @_route_get / @_route_post 注册进路由表的端点。"""
    return set(re.findall(r'@_route_(?:get|post)\(\s*' + _PATH_LIT, src))


def covered(path: str, exact: set, prefixes: set) -> bool:
    if path in exact:
        return True
    base = path.split("*")[0]
    return any(base.startswith(pre) or path.startswith(pre) for pre in prefixes)


def main() -> int:
    server_src = _read(SERVER)
    exact, prefixes = server_routes(server_src)

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

    print("\n[1] 前端调用但服务端没实现（会静默 404）")
    if broken:
        for p in broken:
            print(f"  ✗ {p}")
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
    dup = sorted(table_routes(server_src) & legacy_routes(server_src))
    if dup:
        for p in dup:
            print(f"  ✗ {p}  同时在路由表和老链里 —— 迁进表后请把老链的分支删掉")
    else:
        print(f"  ✓ 无（路由表 {len(table_routes(server_src))} 条 / 老链 "
              f"{len(legacy_routes(server_src))} 条，不重叠）")

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
    if broken or dead or dup:
        return 1
    print("OK 画布端点契约一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
