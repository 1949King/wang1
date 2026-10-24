#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长对白 scrub 压测（报告 §6.1「四个未达标点」第 3 条）

背景
----
代码评价报告指出「长对白 scrub 无压测脚本」（§6.1），且把「长对白 scrub 真压测」
列为 §10 优先级一「立刻做」。本脚本补上这一项。

测什么
------
scrub（拖动播放头）每帧**必经的纯计算路径**：

    _clips_at_playhead(t)   ← 全表扫描 + sort（app/modules/lego/editor_module.py:4312）
    _clip_at_playhead(t)    ← 扫描结果上做 video/audio 分组与选层（:4325）

这两步是「每帧 × 时间线片段数」的成本，长对白时间线（几百段）下是掉帧隐患。
真解码/合成（`_render_timeline_frame` → PreviewManager）**不在本脚本覆盖范围**——
它需要 Qt + 真实素材，见文末「未覆盖」说明，脚本会如实标注。

怎么保证测的是真代码
--------------------
不 import `app.*`（会拉起 config_manager 的 wmic 探测，沙箱黑名单），
而是用 **AST 从 editor_module.py 源码中提取这两个函数的真实函数体**编译执行
——源码改了，这里测到的就是改后的逻辑（函数源码 hash 会打印，便于核对）。

用法
----
    python _verify/check_scrub_perf.py                    # 默认 300 段 / 3000 次
    python _verify/check_scrub_perf.py --clips 600 --iters 5000
    python _verify/check_scrub_perf.py --budget-ms 33      # 30fps 一帧预算
退出码：平均步耗时超预算 → 1（可入 CI/run_all_checks），否则 0。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import random
import statistics
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR_SRC = ROOT / "app" / "modules" / "lego" / "editor_module.py"

TARGETS = ("_clips_at_playhead", "_clip_at_playhead")


def extract_funcs(src_path: Path) -> dict:
    """从源码里提取 EditorModule 的目标方法（不 import，避免拉起 app 链）。"""
    text = src_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(text)
    out = {}
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == "EditorModule"):
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in TARGETS:
                mod = ast.Module(body=[item], type_ignores=[])
                ast.fix_missing_locations(mod)
                ns: dict = {}
                exec(compile(mod, str(src_path), "exec"), ns)
                fn = ns[item.name]
                seg = ast.get_source_segment(text, item) or ""
                out[item.name] = (fn, hashlib.sha256(seg.encode("utf-8")).hexdigest()[:12])
    missing = [t for t in TARGETS if t not in out]
    if missing:
        raise SystemExit(f"[scrub-perf] 源码中找不到目标方法: {missing}")
    return out


class StubEditor:
    """只提供两个函数需要的属性（_clips / _playhead_position / _current_clip）。

    `_clip_at_playhead` 内部会调 `self._clips_at_playhead(t)`，故把提取出的
    真实方法用 MethodType 绑到实例上（保证测的仍是源码实现）。
    """

    def __init__(self, clips, clips_at_fn=None):
        self._clips = clips
        self._playhead_position = 0.0
        self._current_clip = None
        if clips_at_fn is not None:
            self._clips_at_playhead = types.MethodType(clips_at_fn, self)


def build_dialogue_timeline(n_clips: int, seg_sec: float = 8.0, tracks: int = 3):
    """构造「长对白」时间线：n_clips 段串联，另加音频轨与字幕轨（模拟真实密度）。

    tracks 控制每条对白段附带的叠层数（音频 / 字幕），使总片段数为 n_clips × tracks，
    更贴近「长对白 + 字幕 + 配音」的实际时间线密度。
    """
    clips = []
    for i in range(n_clips):
        st = i * seg_sec
        clips.append({
            "id": f"v{i}", "type": "video", "track": 0,
            "start_time": st, "duration": seg_sec,
            "in_point": 0.0, "out_point": seg_sec,
            "path": f"assets/voice_{i % 40}.mp4",  # 复用少数文件，模拟真实工程
        })
        clips.append({
            "id": f"a{i}", "type": "audio", "track": 1,
            "start_time": st, "duration": seg_sec,
            "in_point": 0.0, "out_point": seg_sec,
            "path": f"assets/voice_{i % 40}.wav",
        })
        if tracks >= 3:
            clips.append({
                "id": f"s{i}", "type": "subtitle", "track": 2,
                "start_time": st + 0.2, "duration": seg_sec - 0.4,
            })
    return clips


def make_scrub_positions(total_sec: float, iters: int, seed: int = 20260927):
    """模拟人手拖动：70% 连续小步（近似匀速拖动）+ 30% 跳跃（点选远处）。"""
    rnd = random.Random(seed)
    pos, out = 0.0, []
    for _ in range(iters):
        if rnd.random() < 0.7:
            pos = min(total_sec - 0.01, pos + rnd.uniform(0.05, 0.45))
        else:
            pos = rnd.uniform(0.0, total_sec - 0.01)
        out.append(pos)
    return out


def bench(clips_at, clip_at, stub, positions):
    """返回 (耗时列表 ms, 命中数列表)。两函数都调，模拟真实每帧路径。"""
    times, hits = [], []
    for p in positions:
        t0 = time.perf_counter()
        h = clips_at(stub, p)
        sel = clip_at(stub, p)
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
        hits.append((len(h), sel is not None))
    return times, hits


def pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    k = min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))
    return sorted_vals[k]


def main() -> int:
    ap = argparse.ArgumentParser(description="长对白 scrub 压测")
    ap.add_argument("--clips", type=int, default=300, help="对白段数（每段 8 秒）")
    ap.add_argument("--iters", type=int, default=3000, help="scrub 采样次数")
    ap.add_argument("--budget-ms", type=float, default=33.0,
                    help="单帧预算（30fps=33ms / 60fps=16ms）")
    args = ap.parse_args()

    funcs = extract_funcs(EDITOR_SRC)
    clips_at, h1 = funcs["_clips_at_playhead"]
    clip_at, h2 = funcs["_clip_at_playhead"]
    print("=" * 68)
    print("长对白 scrub 压测（纯计算路径：命中查找 + 选层）")
    print("=" * 68)
    print(f"源码      : {EDITOR_SRC.relative_to(ROOT)}")
    print(f"函数指纹  : _clips_at_playhead={h1}  _clip_at_playhead={h2}")
    print("未覆盖    : 真解码/合成（_render_timeline_frame → PreviewManager），"
          "需 Qt + 真实素材")

    print()
    print("-" * 68)
    print(f"{'段数':>6} {'总片段':>7} {'p50':>8} {'p95':>8} {'p99':>8} "
          f"{'max':>8} {'均值':>8} {'超预算':>8} {'每秒步':>8}")
    print("-" * 68)
    worst_mean = 0.0
    for n in (args.clips // 2, args.clips, args.clips * 2):
        if n < 10:
            continue
        clips = build_dialogue_timeline(n)
        stub = StubEditor(clips, clips_at)
        total_sec = n * 8.0
        positions = make_scrub_positions(total_sec, args.iters)
        # 预热（首次调用有解释器/缓存抖动）
        bench(clips_at, clip_at, stub, positions[:50])
        times, _ = bench(clips_at, clip_at, stub, positions)
        st = sorted(times)
        over = sum(1 for t in times if t > args.budget_ms)
        mean = statistics.fmean(times)
        worst_mean = max(worst_mean, mean)
        print(f"{n:>6} {len(clips):>7} {pct(st,0.50):>8.3f} {pct(st,0.95):>8.3f} "
              f"{pct(st,0.99):>8.3f} {st[-1]:>8.3f} {mean:>8.3f} "
              f"{over:>5}/{len(times):<2} {1000.0/mean:>8.0f}")

    print("-" * 68)
    print(f"单帧预算: {args.budget_ms:.1f} ms（30fps=33 / 60fps=16）")
    ok = worst_mean <= args.budget_ms
    if ok:
        print(f"✅ 纯计算路径均值 {worst_mean:.3f} ms ≤ 预算 {args.budget_ms:.1f} ms")
    else:
        print(f"❌ 纯计算路径均值 {worst_mean:.3f} ms > 预算 {args.budget_ms:.1f} ms"
              "——长对白下查找层已成为掉帧源，考虑对 _clips 按 start_time 建索引")
    print()
    print("读法：本脚本量的是「每帧 × 片段数」的线性成本。若数字随段数近似线性增长，")
    print("      说明 _clips_at_playhead 的全表扫描是长对白瓶颈（当前实现为 O(n)+sort）。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
