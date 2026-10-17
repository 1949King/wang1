# -*- coding: utf-8 -*-
"""画布端口模型守卫（2026-09-28 新增）。

钉死三件事：
  ① **前端真源 `ports.ts` 的 `NODE_PORTS` 能被后端解析**（22 个 kind 一个不少）
     —— 格式一改，后端就瞎，且**静默降级成宽松表**（不报错），故必须有守卫盯着。
  ② **类型系统关键判据成立**（音乐必须能接进视频的配乐位——靠 PORT_COMPAT）。
  ③ **编组必须是 associate 边**（不参与数据流、不做类型校验）——否则编组会被误判非法。

零项目依赖：按文件路径直接加载 `canvas_port_model.py`，不 import app 包
（避开 `canvas_server` → config_manager → wmic 的沙箱黑名单链）。
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TS_REL = os.path.join("vendor", "packages", "libtv", "src", "ports.ts")
PY_REL = os.path.join("app", "core", "canvas_port_model.py")

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _load_pm():
    """按路径加载 canvas_port_model，绕开 app 包导入链。"""
    path = os.path.join(ROOT, PY_REL)
    spec = importlib.util.spec_from_file_location("_pm_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    print("== 画布端口模型守卫（typed slots）==")

    ts_path = os.path.join(ROOT, TS_REL)
    check("前端真源存在", os.path.exists(ts_path), TS_REL)
    if not os.path.exists(ts_path):
        print("\nFAILED 1: 前端真源缺失")
        return 1

    with open(ts_path, encoding="utf-8") as f:
        ts_src = f.read()

    # ① 源文件结构自检（不依赖 Python 解析，直接看 TS 文本）
    decl = re.findall(
        r"^\s*(\w+):\s*\{\s*accepts:\s*\{[^}]*\}\s*,\s*produces:\s*\{[^}]*\}\s*\},?\s*$",
        ts_src, re.M)
    check("ports.ts 含 NODE_PORTS 表（22 行）", len(decl) == 22,
          f"实际解析到 {len(decl)} 行")
    check("ports.ts 导出 isValidConnection 所需纯函数 canConnect",
          "export function canConnect" in ts_src)
    check("ports.ts 导出 validateGraph", "export function validateGraph" in ts_src)
    check("ports.ts 含 PORT_COMPAT（类型兼容表）",
          "export const PORT_COMPAT" in ts_src)
    check("ports.ts 区分 data / associate 两种边",
          'export type EdgeKind = "data" | "associate"' in ts_src)

    # ② 后端解析健康度
    pm = _load_pm()
    st = pm.stats()
    check("后端解析成功（parse_ok）", st.get("parsed_ok") is True, str(st))
    check("后端解析出 22 个 kind", st.get("kinds") == 22, str(st))
    check("后端读到 PORT_COMPAT 规则", st.get("compat_rules", 0) >= 1, str(st))

    # ③ 关键判据（与 ports.test.ts 同源，双端必须一致）
    cases = [
        ("script", "shot", True, "剧本文本 → 镜头"),
        ("image", "video", True, "图生视频"),
        ("music", "video", True, "★ 音乐配乐（靠 PORT_COMPAT）"),
        ("video", "text", False, "★ 视频不能当文本输入"),
        ("audio", "image", False, "★ 音频不能当图像输入"),
        ("director", "audio", False, "★ 3D 场景不产音频"),
        ("image", "image", True, "图生图/参考图"),
        ("group", "image", True, "★ 编组边恒放行（associate）"),
        ("audio", "group", True, "★ 反向编组边也放行"),
    ]
    for s, t, want, desc in cases:
        got = pm.can_connect(s, t)["ok"]
        check(f"{desc}（{s} → {t}）", got == want, f"期望 {want}，实得 {got}")

    # ④ 编组必须是 associate，且 associate 不做类型校验
    check("group 边判为 associate", pm.edge_kind_for("group", "image") == "associate")
    check("普通边判为 data", pm.edge_kind_for("script", "shot") == "data")
    check("未知 kind 走宽松兜底（不误拦新节点）",
          pm.can_connect("__brand_new__", "image")["ok"] is True)

    # ⑤ 与前端同语义：整图校验能抓出非法连接与成环
    graph = {
        "nodes": [{"id": "a", "data": {"kind": "audio"}},
                  {"id": "b", "data": {"kind": "image"}}],
        "edges": [{"source": "a", "target": "b"}],
    }
    probs = pm.validate_graph(graph["nodes"], graph["edges"])
    check("整图校验抓出类型不匹配", any(p["code"] == "type-mismatch" for p in probs),
          str(probs))

    cyc = {"nodes": [{"id": "x", "data": {"kind": "image"}},
                     {"id": "y", "data": {"kind": "image"}}],
           "edges": [{"source": "x", "target": "y"}, {"source": "y", "target": "x"}]}
    check("整图校验抓出数据流成环",
          any(p["code"] == "cycle" for p in pm.validate_graph(cyc["nodes"], cyc["edges"])))

    asg = {"nodes": [{"id": "g", "data": {"kind": "group"}},
                     {"id": "h", "data": {"kind": "group"}}],
           "edges": [{"source": "g", "target": "h"}, {"source": "h", "target": "g"}]}
    check("编组成环不报（associate 不参与数据流）",
          not any(p["code"] == "cycle" for p in pm.validate_graph(asg["nodes"], asg["edges"])))

    print()
    if _fails:
        print(f"FAILED {len(_fails)}: {_fails}")
        return 1
    print("OK 画布端口模型一致（前端真源 ↔ 后端镜像）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
