# -*- coding: utf-8 -*-
"""本地视频「编码链路」守卫（V4.46.12，2026-10-24）。

为什么必须有这条守卫（两个潜伏 bug 的同一根因）：
  ① V4.46.11 真机暴露：SVD 出片必崩 —— `_save_video_frames` 在 cv2 分支先读
     `frames[0].shape`，而 SVD 给的是 PIL.Image。
  ② 同轮暴露：fps 写死 24，而各族 num_frames 按自己原生帧率算（SVD=7、wan=16…）
     ⇒ 除 minimax 外所有族时长被压缩、播放过快（SVD 实测快 3.4 倍）。

两个 bug 能潜伏至今的**共同原因**：视频族的真编码链路从没被测试覆盖过
（并行会话 V4.46.6 的测试文件头明确写「不加载模型、不联网」，只测 resolve_image_path）。
功能"有提交、有测试"，实际出片既崩又时长错。

本守卫把教训固化成机器检查（纯 AST/正则读源码，**不加载模型、不碰 GPU**）：
  A `_save_video_frames` 必须有 fps 形参（禁止写死帧率）；
  B 每个 `_infer_*` 族：其 num_frames 乘数 K 必须与 _native_fps 相等，且调用编码时
    必须传 fps=_native_fps —— 「帧数怎么算」与「按什么帧率写」必须自洽；
  C 编码链路必须有**真产物断言**（ffprobe 或 getsize>0）且必须断言 fps 改变时长
    —— 防止有人把测试删回"只测不加载模型"那一层；
  D 自检：守卫必须能抓出上述各类反例（不自检的守卫等于没守卫，本项目反复踩）。
"""

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LVI_REL = os.path.join("app", "core", "local_video_infer.py")
TEST_REL = os.path.join("app", "tests", "test_local_video_save_frames.py")

_fails = []


def check(name, ok, detail=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        _fails.append(name)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ── 纯函数：从函数源码提取「帧数乘数」与「_native_fps」，便于自检喂反例 ──
# 帧数乘数：兼容两种写法
#   num_frames=int(duration * 24)                       —— minimax/wan/cogvideox/hunyuan/ltx/mochi
#   n_frames = max(2, int(round(float(duration) * 7)))  —— svd（变量名与嵌套都不同）
_MULT_RE = re.compile(r"\b\w*frames\s*=\s*[^\n]*?\bduration\)?\s*\*\s*(\d+)")
_FPS_RE = re.compile(r"_native_fps\s*=\s*(\d+)")
_SAVE_CALL_RE = re.compile(r"_save_video_frames\s*\(([^)]*)\)")


def frame_multiplier(src: str):
    m = _MULT_RE.search(src)
    return int(m.group(1)) if m else None


def declared_fps(src: str):
    m = _FPS_RE.search(src)
    return int(m.group(1)) if m else None


def passes_fps_kwarg(src: str):
    """该函数里对 _save_video_frames 的调用是否传了 fps=_native_fps。"""
    for args in _SAVE_CALL_RE.findall(src):
        if "fps=_native_fps" not in args:
            return False
    return bool(_SAVE_CALL_RE.findall(src))


def audit_families(src: str):
    """返回 [(族函数名, 问题列表)]。只查既有 num_frames 计算的族。"""
    tree = ast.parse(src)
    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_infer_"):
            continue
        body = ast.get_source_segment(src, node) or ""
        mult = frame_multiplier(body)
        if mult is None:
            continue  # 该族不按 duration*fps 算帧数 ⇒ 不在本检查域
        probs = []
        fps = declared_fps(body)
        if fps is None:
            probs.append("缺 _native_fps 定义")
        elif fps != mult:
            probs.append(f"_native_fps={fps} 与帧数乘数 {mult} 不自洽")
        if not passes_fps_kwarg(body):
            probs.append("调用 _save_video_frames 未传 fps=_native_fps")
        out.append((node.name, probs))
    return out


def main() -> int:
    print("== 本地视频编码链路守卫（帧数↔fps 自洽 + 真产物断言）==")
    src = _read(LVI_REL)

    # ── A 编码函数必须有 fps 形参 ──
    sig = re.search(r"def _save_video_frames\((.*?)\)\s*->", src, re.S)
    check(
        "A1 _save_video_frames 有 fps 形参（禁写死帧率）",
        bool(sig) and re.search(r"\bfps\s*:", sig.group(1)) is not None,
    )
    check(
        "A2 编码函数体内不再出现裸写死 24.0/24 帧率",
        "fourcc, 24.0" not in src and "fps=24," not in src,
    )

    # ── B 各族帧数乘数与 _native_fps 自洽 ──
    fams = audit_families(src)
    check("B0 至少审到 5 个族（审不到=检查失效）", len(fams) >= 5, f"实际 {len(fams)}")
    bad = [(n, p) for n, p in fams if p]
    check(
        f"B1 全部 {len(fams)} 个族的 fps 与帧数乘数自洽且传参",
        not bad,
        "；".join(f"{n}:{'/'.join(p)}" for n, p in bad),
    )
    # SVD 是本轮真机验证过的族，必须在内（防止有人误删）
    check("B2 svd 族在审（真机验证过的锚点）", any(n == "_infer_svd" for n, _ in fams))

    # ── C 测试必须有真产物断言 + 断言 fps 改变时长 ──
    tst = _read(TEST_REL)
    check(
        "C1 测试断言真实落盘文件（getsize/isfile，不许只断言 ok=True）",
        "getsize" in tst and "isfile" in tst,
    )
    check(
        "C2 测试用 ffprobe 断言 fps 影响时长（防 fps 再被写死）",
        "ffprobe" in tst and "respects_fps" in tst,
    )
    check(
        "C3 测试覆盖 PIL 帧与 numpy 帧两种输入",
        "accepts_pil_images" in tst and "accepts_numpy_images" in tst,
    )

    # ── D 自检：守卫必须能抓出反例（不自检=没守卫）───────────────────
    print("  —— 自检（守卫必须能抓出这些反例）——")
    bad_src = """
def _infer_demo(*, duration=5):
    result = pipe(num_frames=int(duration * 16))
    frames = result.frames[0]
    return _save_video_frames(frames, "out", 8765)
"""
    r = audit_families(bad_src)
    probs = r[0][1] if r else ["审不到"]
    check("D1 抓出「缺 _native_fps」", any("缺 _native_fps" in x for x in probs), str(probs))
    check("D2 抓出「调用未传 fps=_native_fps」", any("未传 fps" in x for x in probs), str(probs))

    bad2 = """
def _infer_demo2(*, duration=5):
    _native_fps = 24
    result = pipe(num_frames=int(duration * 7))
    return _save_video_frames([], "o", 1, fps=_native_fps)
"""
    r2 = audit_families(bad2)
    check(
        "D3 抓出「fps 与帧数乘数不自洽」（24 vs 7）",
        r2 and any("不自洽" in x for x in r2[0][1]),
        str(r2),
    )

    bad3 = """
def _infer_demo3(*, duration=5):
    _native_fps = 16
    result = pipe(num_frames=int(duration * 16))
    return _save_video_frames([], "o", 1)
"""
    r3 = audit_families(bad3)
    check(
        "D4 抓出「有 _native_fps 却没传」", r3 and any("未传 fps" in x for x in r3[0][1]), str(r3)
    )

    # 正例必须放行（防守卫过严变成噪音）
    good = """
def _infer_ok(*, duration=5):
    _native_fps = 16
    result = pipe(num_frames=int(duration * 16))
    return _save_video_frames([], "o", 1, fps=_native_fps)
"""
    rg = audit_families(good)
    check("D5 正例放行（不过严）", rg and rg[0][1] == [], str(rg))

    print()
    if _fails:
        print(f"✗ 失败 {len(_fails)} 项：{'；'.join(_fails)}")
        return 1
    print("OK 本地视频编码链路守卫全绿（帧数↔fps 自洽 + 真产物断言 + 自检）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
