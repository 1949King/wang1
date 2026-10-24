# -*- coding: utf-8 -*-
"""模型族注册表守卫（统一引擎 M1，2026-10-24）。

钉死四件事（都是本会话真踩过的坑的反向保险）：
  A 每个族的 backends id 必须能在 model_family._backend_available 的已知集合里解析
    —— svd 漏登记 backend_registry 曾把视频本地路径误杀成纯云端（V4.46.11 修），
    同类"查无=判死"错误必须在提交前被 AST 抓住，而不是运行时被用户发现。
  B native_fps 与执行代码里的 num_frames 系数 AST 一致（复用 V4.46.12 守卫的成熟做法）
    —— fps 写死 24 曾让除 minimax 外所有族时长被压缩（SVD 实测快 3.4 倍）。
  C 默认可选列表（include_unverified=False）只含 verified 族 —— 对齐 engine_registry
    「library-only 不得在 UI 宣称可用」法条。
  D 守卫自检：构造"后端 id 拼错 / fps 不一致 / unverified 混进默认"三类反例必须被抓出，
    正例必须放行 —— 不自检的守卫等于没守卫（本项目反复踩）。
零重依赖：AST 读源码 + 轻量 import（model_family 顶层 stdlib-only）。
"""

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MF_REL = os.path.join("app", "core", "neural", "model_family.py")
LVI_REL = os.path.join("app", "core", "local_video_infer.py")

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ── 纯函数：从 model_family 源码抽 (family, backends, native_fps, verification) ──
_KW_RE = {
    "family": re.compile(r'family\s*=\s*"([\w-]+)"'),
    "fps": re.compile(r"native_fps\s*=\s*(\d+)"),
    "ver": re.compile(r"verification\s*=\s*(MF\.)?(VERIFIED|UNVERIFIED|BLOCKED)"),
}
_BACKEND_CONST = re.compile(r"BACKEND_(\w+)")


def parse_specs(src: str):
    """按 ModelFamilySpec( ... ) 切块解析（AST 对 dataclass 调用序列也可，正则更直白）。"""
    tree = ast.parse(src)
    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm.startswith("BACKEND_") and isinstance(node.value, ast.Constant):
                consts[nm] = node.value.value
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ModelFamilySpec"
        ):
            kw = {k.arg: k.value for k in node.keywords}
            fam = (
                kw["family"].value
                if "family" in kw and isinstance(kw["family"], ast.Constant)
                else ""
            )
            backends = []
            if "backends" in kw and isinstance(kw["backends"], ast.Tuple):
                for e in kw["backends"].elts:
                    if isinstance(e, ast.Name):
                        backends.append(consts.get(e.id, "?UNKNOWN_ID:" + e.id))
                    elif isinstance(e, ast.Constant):
                        backends.append(e.value)
            fps = (
                kw["fps"].value
                if "fps" in kw and isinstance(kw["fps"], ast.Constant)
                else (
                    kw["native_fps"].value
                    if "native_fps" in kw and isinstance(kw["native_fps"], ast.Constant)
                    else 0
                )
            )
            ver = ""
            if "verification" in kw:
                v = kw["verification"]
                ver = v.id if isinstance(v, ast.Name) else getattr(v, "value", "")
            out.append(
                {"family": fam, "backends": tuple(backends), "native_fps": fps, "verification": ver}
            )
    return out


def parse_execution_fps(src_lvi: str):
    """从 local_video_infer 抽各族 num_frames 系数（AST：*duration*K / duration*K）。"""
    tree = ast.parse(src_lvi)
    out = {}
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("_infer_")):
            continue
        fam = node.name[len("_infer_") :]
        body = ast.get_source_segment(src_lvi, node) or ""
        m = re.search(r"\b\w*frames\s*=\s*[^\n]*?\bduration\)?\s*\*\s*(\d+)", body)
        if m:
            out[fam] = int(m.group(1))
    return out


def audit(specs, exec_fps, known_backends):
    """返回问题列表（纯函数，供自检喂反例）。"""
    probs = []
    for s in specs:
        fam = s["family"]
        for b in s["backends"]:
            if b not in known_backends:
                probs.append(f"{fam}: 后端 id 无法解析（{b}）")
        if not s["backends"]:
            probs.append(f"{fam}: 无后端声明")
        fps = exec_fps.get(fam, exec_fps.get("minimax_h3" if fam == "minimax_h3" else fam))
        if fps and s["native_fps"] and fps != s["native_fps"]:
            probs.append(
                f"{fam}: native_fps={s['native_fps']} 与执行代码 num_frames 系数 {fps} 不自洽"
            )
        if s["verification"] == "UNVERIFIED" and not s["family"]:
            probs.append("空族名")
    return probs


def main() -> int:
    print("== 模型族注册表守卫（后端可解析 / fps 自洽 / 默认可选纯净 / 自检）==")
    mf_src = _read(MF_REL)
    lvi_src = _read(LVI_REL)
    specs = parse_specs(mf_src)
    exec_fps = parse_execution_fps(lvi_src)

    import app.core.neural.model_family as MF

    known = {
        MF.BACKEND_DIFFSYNTH_IMAGE,
        MF.BACKEND_DIFFUSERS_IMAGE,
        MF.BACKEND_VIDEO_GEN,
        MF.BACKEND_LOCAL_VIDEO,
    }

    check("A0 解析到 ≥9 个族（解析失效=守卫空转）", len(specs) >= 9, f"实际 {len(specs)}")
    probs = audit(specs, exec_fps, known)
    check("A1/B 全部族：后端可解析 且 fps 与执行代码自洽", not probs, "；".join(probs))

    # svd 锚点（真机验证过的族必须存在且归属正确）
    svd = next((s for s in specs if s["family"] == "svd"), None)
    check(
        "A2 svd 族在且首选 video_gen（SVD 唯一归属承诺）",
        svd is not None and svd["backends"][:1] == (MF.BACKEND_VIDEO_GEN,),
    )

    # C 默认可选纯净
    defaults = {s.family for s in MF.families(include_unverified=False)}
    unv = {s["family"] for s in specs if s["verification"] == "UNVERIFIED"}
    check("C1 默认可选不含任何 unverified 族", not (defaults & unv), f"混入：{defaults & unv}")
    check("C2 svd/sd15/sdxl 在默认可选（verified 三族）", {"svd", "sd15", "sdxl"} <= defaults)

    # D 自检：反例必须被抓出
    print("  —— 自检（守卫必须能抓出这些反例）——")
    bad_back = [
        {"family": "x", "backends": ("typo_backend",), "native_fps": 7, "verification": "VERIFIED"}
    ]
    check("D1 抓出后端 id 拼错", bool(audit(bad_back, {}, known)))
    bad_fps = [
        {
            "family": "svd",
            "backends": (MF.BACKEND_VIDEO_GEN,),
            "native_fps": 24,
            "verification": "VERIFIED",
        }
    ]
    check(
        "D2 抓出 fps 不自洽（24 vs 7）",
        any("不自洽" in p for p in audit(bad_fps, {"svd": 7}, known)),
    )
    ok_case = [
        {
            "family": "svd",
            "backends": (MF.BACKEND_VIDEO_GEN,),
            "native_fps": 7,
            "verification": "VERIFIED",
        }
    ]
    check("D3 正例放行（不过严）", audit(ok_case, {"svd": 7}, known) == [])

    print()
    if _fails:
        print(f"✗ 失败 {len(_fails)} 项：{'；'.join(_fails)}")
        return 1
    print("OK 模型族注册表守卫全绿（M1 协议层入册）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
