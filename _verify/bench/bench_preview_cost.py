# -*- coding: utf-8 -*-
"""预览取帧真实成本结构测量（刀 A3.5，2026-10-05）。

**为什么写这个**：策略基准（bench_preview_cache.py）证明「LRU vs FIFO vs min()」
几乎无差别（差 0.7%）⇒ 缓存**策略**不是瓶颈。那就必须**测真实耗时**，而不是再猜。

本脚本用真实视频 + **生产类 PreviewManager**（不 mock）测三类操作的耗时：
  · 缓存命中（QImage 直取）
  · 未命中 · 小跳（grab 追赶，便宜）
  · 未命中 · 回退/大跳（cv2 POS_FRAMES seek，贵）

再按「拖动条横扫 N 帧」的真实交互算出总时长，定位瓶颈占比。

用法：python _verify/bench/bench_preview_cost.py [视频路径] [--frames 120]
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

DEFAULT_VIDEO = os.path.join("短剧AI剪辑输出", "_bench_final_opt.mp4")


def ensure_synthetic_video(*, seconds: int = 30, gop: int = 250) -> str:
    """合成一段**长 GOP** 测试视频（脚本自带 ⇒ 测量可复现，不依赖仓库里的素材）。

    为什么要长 GOP：seek 成本与 GOP 长度正相关 —— 短 GOP 的视频测不出真实反扫代价。
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out = os.path.join(root, ".workbuddy", "tmp", "vbench", f"longgop_{seconds}s.mp4")
    if os.path.isfile(out):
        return out
    ffmpeg = os.path.join(root, "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
    if not os.path.isfile(ffmpeg):
        return ""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"（首次运行：合成 {seconds}s / GOP {gop} 测试视频 …）")
    r = subprocess.run(
        [ffmpeg, "-hide_banner", "-y", "-f", "lavfi",
         "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
         "-c:v", "libx264", "-preset", "veryfast", "-g", str(gop),
         "-pix_fmt", "yuv420p", "-b:v", "2500k", out],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return out if r.returncode == 0 and os.path.isfile(out) else ""


def _timeit(fn, repeat=1):
    t0 = time.perf_counter()
    for _ in range(repeat):
        fn()
    return (time.perf_counter() - t0) / repeat * 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", default=DEFAULT_VIDEO)
    ap.add_argument("--frames", type=int, default=120, help="横扫帧数")
    args = ap.parse_args()
    path = os.path.abspath(args.video)
    if not os.path.isfile(path):
        # 缺素材时自动合成（长 GOP）—— 保证"怎么测的"可复现
        path = ensure_synthetic_video()
    if not path or not os.path.isfile(path):
        print(f"SKIP 找不到测试视频，且无法合成：{args.video}")
        return 0

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])   # noqa: F841

    from app.core.preview_manager import PreviewManager

    pm = PreviewManager()
    if not pm.open_video(path, preload=False):
        print(f"SKIP 打不开视频：{path}")
        return 0
    fps = float(pm._video_fps or 30.0)
    total = int(pm._video_frame_count or 0)
    # 素材太短则测不出 seek 成本（帧数少 ⇒ 帧号被反复钳到端点，数据失真）
    if total < 200:
        pm = PreviewManager()
        synth = ensure_synthetic_video()
        if synth and pm.open_video(synth, preload=False):
            print(f"（{os.path.basename(path)} 仅 {total} 帧，样本不足 ⇒ 改用合成长 GOP 素材）")
            path = synth
            fps = float(pm._video_fps or 30.0)
            total = int(pm._video_frame_count or 0)
    print("=" * 70)
    print(f"预览取帧成本结构 · {os.path.basename(path)} · {total} 帧 @ {fps:.2f}fps")
    print("=" * 70)

    span = min(args.frames, max(10, total // 3))
    mid = max(10, total // 2)

    # ① 冷启动：第一次触碰（必然未命中 ⇒ 首次可能是 seek）
    t_first = _timeit(lambda: pm.get_frame_at(mid / fps), repeat=1)
    print(f"① 首次触碰（未命中 · 可能 seek）      {t_first:8.2f} ms")

    # ② 命中：同帧重复取（清空后先取一次预热）
    pm.clear_preview_cache()
    pm.get_frame_at(mid / fps)
    t_hit = _timeit(lambda: pm.get_frame_at(mid / fps), repeat=30)
    print(f"② 缓存命中                          {t_hit:8.2f} ms")

    # ③ 未命中 · 顺序小跳（grab 追赶路径）
    pm.clear_preview_cache()
    seq = [mid + i for i in range(1, 13)]
    t_seq = _timeit(lambda: [pm.get_frame_at(f / fps) for f in seq], repeat=3)
    print(f"③ 未命中 · 顺序前进 12 帧（grab）     {t_seq:8.2f} ms / 12 帧"
          f"（{t_seq / 12:.2f} ms/帧）")

    # ④ 未命中 · 回退（POS_FRAMES seek）
    pm.clear_preview_cache()
    back = [mid - i * 7 for i in range(1, 12)]
    t_back = _timeit(lambda: [pm.get_frame_at(f / fps) for f in back], repeat=3)
    print(f"④ 未命中 · 回退 11 帧（cv2 seek）     {t_back:8.2f} ms / 11 帧"
          f"（{t_back / 11:.2f} ms/帧）")

    # ⑤ 真实交互：拖动条横扫（先清缓存，模拟拖到新区段）
    pm.clear_preview_cache()
    t0 = time.perf_counter()
    for i in range(span):
        pm.get_frame_at((mid + i) / fps)
    t_sweep = (time.perf_counter() - t0) * 1000.0
    print("-" * 70)
    print(f"⑤ 横扫 {span} 帧（缓存冷 + 顺序前进）   {t_sweep:8.2f} ms"
          f"（{t_sweep / span:.2f} ms/帧）")

    # ⑥ 回扫（拖动条往左扫：每帧都要 seek）
    pm.clear_preview_cache()
    t0 = time.perf_counter()
    for i in range(span):
        pm.get_frame_at((mid + span - i) / fps)
    t_backsweep = (time.perf_counter() - t0) * 1000.0
    print(f"⑥ 反扫 {span} 帧（每帧后退 ⇒ seek）    {t_backsweep:8.2f} ms"
          f"（{t_backsweep / span:.2f} ms/帧）")

    print("-" * 70)
    ratio = (t_backsweep / t_sweep) if t_sweep > 0 else 0
    print(f"反扫 / 顺序扫 = {ratio:.2f}×  ⇒ 瓶颈在"
          f"{'**后退 seek**' if ratio > 1.5 else '不明显的 seek 依赖'}")

    # ⑦ 定窗预载 A/B：**同一帧区间**对比（这是唯一公平的比法）
    #
    # 踩过的坑（记录以免重犯）：
    #   ① 缓存里已有别的帧 ⇒ 必须 clear 两个缓存再下发；
    #   ② 探测帧落在窗口之外 ⇒ 永远等不到"就绪"，白等 15s；
    #   ③ 扫掠区间超出窗宽 ⇒ 又把 seek 算进来了，比的不是同一件事。
    win = pm._preload_window_frames()
    fps_i = int(pm._video_fps)
    wstart = max(0, mid - int(win * 0.34))
    wend = min(total - 1, wstart + win)
    # 区间内反扫（避开端点，保证两次扫的是同一批帧）
    sweep_range = list(range(wend - 2, wstart + 1, -1))

    print("-" * 70)
    print(f"⑦ 定窗预载 A/B · 窗口 帧{wstart}..{wend}（宽 {wend - wstart + 1}）"
          f" · 反扫 {len(sweep_range)} 帧")

    # A：无预载
    pm.clear_preview_cache()
    pm.raw_frame_cache.clear()
    t0 = time.perf_counter()
    for f in sweep_range:
        pm.get_frame_at(f / fps_i)
    t_no_pre = (time.perf_counter() - t0) * 1000.0
    per_no = t_no_pre / len(sweep_range)

    # B：有预载（等该窗口帧真的就位）
    pm.clear_preview_cache()
    pm.raw_frame_cache.clear()
    pm._pending_preload_center = mid / fps
    pm._last_preload_start = None
    t0 = time.perf_counter()
    pm._do_preload_window()
    deadline = time.time() + 20.0
    while time.time() < deadline:
        if (wend in pm.raw_frame_cache) or len(pm.raw_frame_cache) >= (wend - wstart + 1):
            break
        time.sleep(0.02)
    t_fill = (time.perf_counter() - t0) * 1000.0
    filled = len(pm.raw_frame_cache)
    t0 = time.perf_counter()
    for f in sweep_range:
        pm.get_frame_at(f / fps_i)
    t_pre = (time.perf_counter() - t0) * 1000.0
    per_pre = t_pre / len(sweep_range)

    print(f"   A 无预载反扫   {t_no_pre:8.2f} ms（{per_no:6.2f} ms/帧）")
    print(f"   B 预载后反扫   {t_pre:8.2f} ms（{per_pre:6.2f} ms/帧）"
          f"   预载耗时 {t_fill:.0f} ms 填入 {filled} 帧")
    if per_pre > 0:
        print(f"   ⇒ 提速 {per_no / per_pre:.1f}×"
              f"{'  ⚠️ 未见提升（需排查）' if per_pre >= per_no else ''}")

    print(f"按 60fps 预算（16.7ms/帧）：顺序扫 {'达标' if t_sweep / span < 16.7 else '不达标'}"
          f" · 反扫(冷) {'达标' if t_backsweep / span < 16.7 else '不达标'}"
          f" · 反扫(预载) {'达标' if per_pre < 16.7 else '不达标'}")
    stats = pm.preview_cache.stats() if hasattr(pm.preview_cache, "stats") else {}
    if stats:
        print(f"缓存统计：{stats}")
    print("BENCH-PREVIEW-COST DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
