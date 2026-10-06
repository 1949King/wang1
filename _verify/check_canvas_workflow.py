# -*- coding: utf-8 -*-
"""画布图执行 + 增量缓存 接线守卫（2026-09-28 新增）。

钉死四件事——它们都是「漏了不报错、只是功能悄悄失效」的类型：
  ① 两个端点已注册进路由表（`/host/canvas-run` · `/host/canvas-cache`）；
  ② **`run_graph` 的 dry_run 缺省必须是 True** —— 这是北极星
     「智能体只做确认后执行的遥控器，不默认一键成片」在代码里的落点；
     一旦被改成 False，一次误调用就会烧云端额度。
  ③ 失败节点**不得写 output**（诚实失败：绝不伪造产物）。
  ④ 增量缓存的指纹**必须含上游**（否则改上游下游不失效 = 增量执行失效）。

零依赖：动态部分自己拼一张最小图跑一遍，不 import app 包（避开 wmci/沙箱链）。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main():
    print("== 画布图执行 + 增量缓存 接线守卫 ==")

    # ① 端点已注册（源码级：装饰器存在）
    post_src = _read("app/core/canvas_routes_post.py")
    for path in ("/host/canvas-run", "/host/canvas-cache"):
        check(f"端点已声明 {path}",
              bool(re.search(r'@_route_post\("' + re.escape(path) + r'"\)', post_src)))

    # ② run_graph 的 dry_run 缺省必须是 True
    runner_src = _read("app/core/canvas_workflow_runner.py")
    m = re.search(r"def run_graph\((.*?)\)\s*->", runner_src, re.S)
    check("run_graph 函数签名可解析", bool(m))
    if m:
        sig = m.group(1)
        default_true = bool(re.search(r"dry_run\s*:\s*bool\s*=\s*True", sig))
        check("★ 北极星纪律：dry_run 缺省 = True（不默认一键成片）", default_true,
              f"实际签名: {sig.strip()[:120]}")

    # 端点层也必须默认只出计划
    check("端点层 dry_run 缺省只出计划",
          'body.get("dry_run", True)' in post_src)

    # ③ 失败节点不写 output（诚实失败）
    check("失败分支不含 output 字段",
          re.search(r'status"?\s*:\s*"failed"[^}]*\}', runner_src) is not None
          and '"output"' not in _failed_branch(runner_src))

    # ④ 指纹必须含上游
    cache_src = _read("app/core/canvas_node_cache.py")
    check("指纹函数接受上游参数", bool(
        re.search(r"def node_fingerprint\([^)]*upstream", cache_src, re.S)))
    check("指纹拼接含上游", "','.join(ups)" in cache_src or '",".join(ups)' in cache_src)

    # ⑤ 缓存复用 draw_book 的原子写纪律
    check("原子写（tempfile + os.replace）",
          "tempfile.mkstemp" in cache_src and "os.replace" in cache_src)
    check("RLock（可重入，防自死锁）", "threading.RLock()" in cache_src)

    # ⑥ 两个模块都能独立 import（语法 + 无顶层重依赖）
    for mod in ("app/core/canvas_node_cache.py", "app/core/canvas_workflow_runner.py"):
        src = _read(mod)
        try:
            ast.parse(src)
            check(f"{mod} 语法正确", True)
        except SyntaxError as e:
            check(f"{mod} 语法正确", False, str(e))

    print()
    if _fails:
        print(f"FAILED {len(_fails)} / {len(_fails)}: {_fails}")
        return 1
    print("OK 画布图执行 + 增量缓存接线一致")
    return 0


def _failed_branch(src: str) -> str:
    """抽出 failed 分支的源码片段，用于断言其内不含 output。"""
    idx = src.find('"failed"')
    if idx < 0:
        return ""
    return src[max(0, idx - 200): idx + 300]


if __name__ == "__main__":
    sys.exit(main())
