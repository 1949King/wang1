# -*- coding: utf-8 -*-
"""预览定窗预载守卫（刀 A3.5，2026-10-05）。

钉死三件**实测挣来**的事，防后人无意改回：

  ① **`_seek_to` 必须请求定窗预载**。没有它，反扫每一帧都是一次 cv2 后退 seek。
     实测（`_verify/bench/bench_preview_cost.py`，长 GOP 30s/720p）：
     顺序扫 3.4ms/帧 vs **反扫 11.1ms/帧**，单次后退 seek 16~17ms。
  ② **`set_preload_range` 必须真的被调用**。此前它**全仓零调用** ——
     预载线程启动后只会 `sleep(0.05)` 空转 = 死代码。
  ③ **预载不得再被 `_use_threaded_reading` / `_enable_preloading` 挡住**。
     这两道门（默认都是 False，后者还是硬编码）叠加，正是「预载从未运行」的根因；
     而预载线程自带独立 cv2 句柄，**不需要**那条更激进的线程读路径。

另：窗口必须**有内存预算**（未压缩 RGB：1080p 单帧 6.2MB，100 帧就是 620MB）——
没有预算的自适应窗宽等于埋内存炸弹。

零依赖：只读源码 + AST，不 import preview_manager（避免拉 Qt）。
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PM_REL = os.path.join("app", "core", "preview_manager.py")

_fails = []


def _fail(msg: str) -> None:
    _fails.append(msg)


def _func_src(src: str, name: str) -> str:
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        _fail(f"preview_manager.py 语法错误：{e}")
        return ""
    lines = src.split("\n")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return ""


def _strip_explanation(code: str) -> str:
    """去掉 docstring 与注释后再判断（解释文字里会提到这些名字，否则永远命中）。"""
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    code = re.sub(r"^\s*#.*$", "", code, flags=re.M)
    return code


def check_seek_requests_preload(src: str) -> None:
    fn = _func_src(src, "_seek_to")
    if not fn:
        _fail("① 找不到 _seek_to")
    elif "request_preload_window(" not in _strip_explanation(fn):
        _fail("① _seek_to 未请求定窗预载 ⇒ 反扫会退化为每帧一次 cv2 seek（实测 11ms/帧）")


def check_set_preload_range_called(src: str) -> None:
    """★ 死代码复活锁：`set_preload_range` 必须有**调用点**。"""
    call_sites = [ln for ln in src.splitlines()
                  if "set_preload_range" in ln and "def " not in ln]
    if not call_sites:
        _fail("② set_preload_range 只有定义、无调用 ⇒ 预载线程空转（死代码回流）")


def check_preloader_not_gated(src: str) -> None:
    fn = _strip_explanation(_func_src(src, "_ensure_preloader"))
    if not fn:
        _fail("③ 找不到 _ensure_preloader")
        return
    for gate in ("_use_threaded_reading", "_enable_preloading"):
        if gate in fn:
            _fail(f"③ _ensure_preloader 又被 {gate} 挡住 ⇒ 预载会重回「从不运行」状态")


def check_window_memory_bounded(src: str) -> None:
    fn = _strip_explanation(_func_src(src, "_preload_window_frames"))
    if not fn:
        _fail("④ 找不到 _preload_window_frames（窗宽无预算 = 内存炸弹）")
        return
    if "PRELOAD_MEMORY_BUDGET_MB" not in fn:
        _fail("④ 窗宽未按内存预算计算（未压缩 RGB：1080p 100 帧 ≈ 620MB）")
    if "max_raw_cache_size" not in fn:
        _fail("④ 窗宽未受 raw 缓存上限约束 ⇒ 预载会自我淘汰")
    if not re.search(r"max\(12,", fn):
        _fail("④ 窗宽缺少下限（过小则预载无意义）")


def check_debounce_present(src: str) -> None:
    fn = _strip_explanation(_func_src(src, "request_preload_window"))
    if "SingleShot" not in fn and "setSingleShot(True)" not in src:
        _fail("⑤ 定窗请求缺少防抖（拖动中会连续打断解码线程，反而更卡）")


def check_get_frame_at_untouched(src: str) -> None:
    """本次**没有**改动冻结符号 `get_frame_at`（playback-av）—— 只是换了协作对象。"""
    fn = _func_src(src, "get_frame_at")
    for probe in ("self.preview_cache.get(cache_key)",
                  "raw_frame = self.raw_frame_cache.get(frame_idx)",
                  "self.preview_cache[cache_key] = qimage"):
        if probe not in fn:
            _fail(f"⑥ get_frame_at 内缓存用法被改动（冻结符号）：{probe}")


def check_frame_cache_wired(src: str) -> None:
    if "from app.core.frame_cache import FrameCache" not in src:
        _fail("⑦ 未接入 FrameCache（缓存退化为 FIFO / O(n) 扫描）")
    if "min(self.raw_frame_cache.keys())" in src:
        _fail("⑦ 旧的 min(keys()) 淘汰回流（往回拖动会丢掉即将要用的帧，且是 O(n)）")


def main() -> int:
    print("=" * 62)
    print("预览定窗预载守卫（刀 A3.5）")
    print("=" * 62)
    path = os.path.join(ROOT, PM_REL)
    if not os.path.isfile(path):
        _fail(f"文件缺失：{PM_REL}")
        src = ""
    else:
        src = open(path, encoding="utf-8").read()
    for fn in (check_seek_requests_preload, check_set_preload_range_called,
               check_preloader_not_gated, check_window_memory_bounded,
               check_debounce_present, check_get_frame_at_untouched,
               check_frame_cache_wired):
        try:
            fn(src)
        except Exception as e:
            _fail(f"{fn.__name__} 抛异常: {type(e).__name__}: {e}")

    if _fails:
        print("✗ 失败项：")
        for p in _fails:
            print(f"  - {p}")
        return 1
    print("OK 定窗预载接线 · 内存有界 · 防抖 · 死代码已复活 · 冻结符号未动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
