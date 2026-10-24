# -*- coding: utf-8 -*-
"""预览帧缓存策略基准（刀 A3.5，2026-10-05）。

对比三种淘汰策略在**真实编辑访问模式**下的解码次数（= 缓存缺失数）：
  · A 旧 raw 策略：`dict` + `min(keys())` 淘汰**最小帧号**（PreviewManager 原实现）
  · B FIFO      ：`OrderedDict` 命中不提权（preview_cache 原实现）
  · C 真 LRU    ：`FrameCache`（本次接入）

为什么值得量化：缓存策略错了不会报错、只会「卡」—— 用户感知是「拖回去重放很卡」，
排查时又会以为是解码慢。用访问模式 + 命中率把它变成可复现的数字。

四种模式（按真实剪辑习惯）：
  ① forward_play   顺序播放（预载 + 逐帧前进）
  ② back_scrub     播放后**往回拖**
  ③ jitter         在一点附近**来回微调**（最常用的对帧动作）
  ④ seek_jump      随机跳转（对着分镜点跳）

用法：python _verify/bench/bench_preview_cache.py [--cap 100] [--frames 3600]
"""
import argparse
import os
import random
import sys
import time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.frame_cache import FrameCache


class MinKeyPolicy:
    """原 raw_frame_cache：dict + 淘汰最小 key（帧号）。"""

    def __init__(self, cap):
        self.cap, self.d = cap, {}

    def get(self, k):
        return self.d.get(k)

    def put(self, k):
        self.d[k] = True
        while len(self.d) > self.cap:
            del self.d[min(self.d.keys())]


class FifoPolicy:
    """原 preview_cache：OrderedDict，命中不提权。"""

    def __init__(self, cap):
        self.cap, self.d = cap, OrderedDict()

    def get(self, k):
        return self.d.get(k)          # ← 不 move_to_end（这正是缺陷）

    def put(self, k):
        self.d[k] = True
        while len(self.d) > self.cap:
            self.d.popitem(last=False)


class LruPolicy:
    """本次接入的 FrameCache。"""

    def __init__(self, cap):
        self.c = FrameCache(cap)

    def get(self, k):
        return self.c.get(k)

    def put(self, k):
        self.c[k] = True


def gen_patterns(n_frames, seed=42):
    rnd = random.Random(seed)
    mid = n_frames // 2
    return {
        "① forward_play": list(range(min(n_frames, 900))),
        # 播放到中段后往回拖 400 帧，再往回拖 400 帧
        "② back_scrub": list(range(mid, mid + 300)) + list(range(mid + 300, mid - 400, -1)),
        # 在一点附近来回微调 6 轮
        "③ jitter": [f for _ in range(6) for f in list(range(mid, mid + 40)) + list(range(mid + 40, mid, -1))],
        # 随机跳转 600 次（每次落在跳点后连看 6 帧）
        "④ seek_jump": [f + k for _ in range(600)
                        for f in [rnd.randrange(0, max(1, n_frames - 8))]
                        for k in range(6)],
    }


def run(policy_cls, cap, access):
    p = policy_cls(cap)
    t0 = time.perf_counter()
    miss = 0
    for k in access:
        if p.get(k) is None:
            miss += 1
            p.put(k)
    return miss, (time.perf_counter() - t0) * 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=100, help="缓存容量（raw 默认 100）")
    ap.add_argument("--frames", type=int, default=3600, help="时间线总帧数（30fps≈2 分钟）")
    args = ap.parse_args()

    print("=" * 74)
    print(f"预览帧缓存策略基准 · 容量 {args.cap} 帧 · 时间线 {args.frames} 帧")
    print("=" * 74)
    pats = gen_patterns(args.frames)
    print(f"{'访问模式':<16}{'访问数':>8}{'A 旧(min)':>12}{'B FIFO':>10}{'C 真LRU':>10}{'C vs A':>10}{'C vs B':>10}")
    print("-" * 74)
    totals = {"A": 0, "B": 0, "C": 0}
    for name, access in pats.items():
        ma, _ = run(MinKeyPolicy, args.cap, access)
        mb, _ = run(FifoPolicy, args.cap, access)
        mc, _ = run(LruPolicy, args.cap, access)
        totals["A"] += ma
        totals["B"] += mb
        totals["C"] += mc

        def pct(new, old):
            return "—" if old == 0 else f"{(new - old) / old * 100:+.1f}%"

        print(f"{name:<16}{len(access):>8}{ma:>12}{mb:>10}{mc:>10}{pct(mc, ma):>10}{pct(mc, mb):>10}")
    print("-" * 74)
    print(f"{'合计':<16}{sum(len(a) for a in pats.values()):>8}"
          f"{totals['A']:>12}{totals['B']:>10}{totals['C']:>10}")
    decode_ms = 8.0   # 1080p 单帧 cv2 解码 + 缩放/上色的量级
    for tag, m in (("A 旧(min)", totals["A"]), ("B FIFO", totals["B"]), ("C 真LRU", totals["C"])):
        print(f"  {tag:<10} 解码 {m:>6} 帧 ≈ {m * decode_ms / 1000:.1f} s 累计等待")
    saved = totals["A"] - totals["C"]
    print(f"\n★ 相比旧策略（A）少解码 {saved} 帧 ≈ 少等 {saved * decode_ms / 1000:.1f} s"
          f"（访问序列累计口径）")
    print("BENCH-PREVIEW-CACHE DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
