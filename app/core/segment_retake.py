# -*- coding: utf-8 -*-
"""片段重拍（Segment Retake）—— 只重做视频里的一小段（2026-10-06）。

对标 LibTV「片段重拍」：对已生成视频的**指定时间段**（如 00:19—00:24）局部重生成，
**不必整条返工**。

本模块负责**除"生成"以外的全部工程问题**（生成那一步由上层调用模型完成）：
  ① **规划**：时间段是否合法、把边界**吸附到场景切点**（接缝藏起来的关键）、
     给出保留段与替换段的精确时长 —— `plan_retake()`（**纯函数**，好测）；
  ② **拼接**：原片 + 新段 + 原片，**保留原音轨**，并把新段**对齐到原片规格**
     （分辨率/帧率/时长）—— `splice_retake()`。

⚠️ **诚实纪律（本模块的红线）**
============================
· **接缝是真实存在的**：生成出来的新段与前后文的色调/运动连续性来自不同的推理，
  边界**可能跳一下**。所以本模块**必须**：
  · 尽量建议把切点放在**场景切换处**（那里本来就跳，看不出接缝）；
  · 返回 `seams[]`（接缝时间点）与 `seam_risk`（是否落在切点上），
    **让用户知道该检查哪一秒**，而不是假装无缝；
  · 不做"用滤镜平滑掉接缝"这种**用损失掩盖问题**的手脚（要平滑请显式要求并承担画质代价）。
· **时长口径**：新段与原段时长不一致时默认**对齐到原时长**（裁掉或补最后一帧），
  并在返回值里**如实说明**是裁了还是补了 —— 否则整条片子的时间轴会悄悄错位。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MIN_SEGMENT = 0.20          # 秒：短于此的"重拍"没有意义（不如整条重生成）
CUT_SNAP_TOLERANCE = 0.30   # 秒：边界离切点这么近就认为"本来就该切在这儿"


def _ffmpeg() -> Optional[str]:
    from app.core.ffmpeg_utils import find_ffmpeg

    return find_ffmpeg()


def probe_duration(video: str) -> float:
    """时长（复用拉片模块的实现，避免两处各写一份）。"""
    from app.core import reference_breakdown as rb

    return rb.probe_duration(video)


def probe_wh_fps(video: str) -> Dict[str, float]:
    """宽高与帧率（对齐拼接用）；拿不到返回 0。"""
    ff = _ffmpeg()
    if not ff:
        return {"w": 0, "h": 0, "fps": 0.0}
    out = {"w": 0, "h": 0, "fps": 0.0}
    try:
        r = subprocess.run([ff, "-i", video], capture_output=True, text=True, timeout=60)
        err = r.stderr or ""
        m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
        if m:
            out["w"], out["h"] = int(m.group(1)), int(m.group(2))
        f = re.search(r"(\d+(?:\.\d+)?)\s*fps", err)
        if f:
            out["fps"] = float(f.group(1))
    except Exception as e:
        logger.debug("[segment_retake] 取规格失败: %s", e)
    return out


def _has_audio_stream(video: str) -> bool:
    """探测视频是否含音频流（2026-10-09 通电新增：拼接音轨判定的前置）。"""
    ff = _ffmpeg()
    if not ff:
        return False
    try:
        r = subprocess.run([ff, "-i", video], capture_output=True, text=True, timeout=60)
        return "Audio:" in (r.stderr or "")
    except Exception:
        return False


def nearest_cut(t: float, cuts: Sequence[float]) -> Tuple[Optional[float], float]:
    """离 `t` 最近的切点及其距离（没有切点则返回 (None, inf)）。"""
    best, dist = None, float("inf")
    for c in cuts or []:
        d = abs(float(c) - float(t))
        if d < dist:
            best, dist = float(c), d
    return best, dist


def plan_retake(duration: float, start: float, end: float, *,
                cuts: Sequence[float] = (),
                min_segment: float = MIN_SEGMENT,
                snap_tolerance: float = CUT_SNAP_TOLERANCE) -> Dict[str, Any]:
    """**纯函数**：校验并规划一次片段重拍。

    返回（失败时 `ok=False` 且 `reason` 说明为什么 —— 不静默改用户的输入）：
      · `start/end/duration`：**实际**要重拍的时间段（可能因吸附切点而微调）
      · `snapped`：是否吸附过；`snap_delta`：吸附了多少秒
      · `keep_before/keep_after`：前后保留段时长
      · `seam_risk`：`low`（边界落在切点上）/ `medium`（离切点较远，接缝可能可见）
      · `note`：给用户看的说明
    """
    if not (duration and duration > 0):
        return {"ok": False, "reason": "拿不到视频时长，无法规划重拍"}
    s, e = float(start), float(end)
    if s < 0 or e < 0:
        return {"ok": False, "reason": "时间不能为负"}
    if e <= s:
        return {"ok": False, "reason": f"结束时间（{e:.2f}s）必须大于开始时间（{s:.2f}s）"}
    if e > duration + 1e-3:
        return {"ok": False, "reason": f"结束时间（{e:.2f}s）超出视频时长（{duration:.2f}s）"}
    if (e - s) < min_segment:
        return {"ok": False, "reason": f"重拍段太短（{e - s:.2f}s < {min_segment:.2f}s），建议整条重生成"}

    # 边界吸附切点：接缝藏在场景切换处最不容易被看出来
    # 2026-10-09 修真 bug：旧版 start/end **各自用对方的旧值**判断合法性，
    # start 吸附到 > end 的切点时区间会倒置/小于 min_segment（产出非法计划）。
    # 正解：吸附后**立即重算**另一侧的约束（用当前最新值），并做最终区间自检。
    snapped = False
    snap_delta = 0.0
    for which in ("start", "end"):
        t = s if which == "start" else e
        c, d = nearest_cut(t, cuts)
        if c is None or d > snap_tolerance:
            continue
        if which == "start" and c < e - min_segment:
            snap_delta = c - s
            s = c
            snapped = True
        elif which == "end" and c > s + min_segment:
            snap_delta = c - e
            e = c
            snapped = True
    # 吸附后自检：区间仍必须合法（不倒置、不过短、不出界）
    if e <= s or (e - s) < min_segment or e > duration + 1e-3 or s < 0:
        return {"ok": False,
                "reason": (f"吸附场景切点后区间非法（{s:.2f}-{e:.2f}s），"
                           f"请手动指定重拍范围")}

    # 接缝风险：两端是否都落在切点附近
    risk_pts = []
    for t in (s, e):
        _, d = nearest_cut(t, cuts)
        risk_pts.append(d)
    if cuts:
        worst = max(risk_pts)
        seam_risk = "low" if worst <= snap_tolerance else "medium"
    else:
        seam_risk = "medium"   # 没有切点信息 ⇒ 不能保证，按 medium 报（不吹 low）

    return {
        "ok": True, "duration": round(duration, 3),
        "start": round(s, 3), "end": round(e, 3), "length": round(e - s, 3),
        "snapped": snapped, "snap_delta": round(snap_delta, 3),
        "keep_before": round(s, 3), "keep_after": round(max(0.0, duration - e), 3),
        "seam_risk": seam_risk,
        "seams": [round(s, 3), round(e, 3)],
        "note": ("边界已吸附到场景切点 ⇒ 接缝不容易被看出来" if snapped
                 else ("没有可用的场景切点信息，接缝可能可见，建议检查这两秒" if not cuts
                       else "边界离最近的场景切点较远，接缝可能可见，建议检查")),
    }


def splice_retake(original: str, replacement: str, out_path: str, *,
                  start: float, end: float, conform: bool = True,
                  keep_audio: bool = True,
                  cuts: Sequence[float] = ()) -> Dict[str, Any]:
    """把 `original` 的 [start, end) 用 `replacement` 替换后输出。

    · **对齐**：新段被缩放到原片分辨率/帧率；`conform=True` 时**对齐到原段时长**
      （长了裁、短了补最后一帧），保证整条片子**总时长不变**、时间轴不错位。
    · **音轨**：默认保留原音轨（只替换段的音频用新段的；新段没音频则该段静音）。
    · 返回 `conformed`（`trimmed`/`padded`/`exact`）与 `seams` —— **如实报告**做了什么。
    """
    ff = _ffmpeg()
    if not ff:
        return {"ok": False, "reason": "ffmpeg 不可用（拼接依赖它）"}
    for p in (original, replacement):
        if not os.path.isfile(p):
            return {"ok": False, "reason": f"找不到文件: {p}"}

    dur = probe_duration(original)
    rep_dur = probe_duration(replacement)
    # `cuts` 由上层从 L1 拉片（reference_breakdown）拿来 ⇒ 可判断接缝是否落在场景切换处
    plan = plan_retake(dur, start, end, cuts=cuts)
    if not plan.get("ok"):
        return plan
    s, e = plan["start"], plan["end"]
    target = plan["length"]

    spec = probe_wh_fps(original)
    if not spec["w"] or not spec["h"]:
        return {"ok": False, "reason": "读不到原片分辨率"}
    w, h = int(spec["w"]), int(spec["h"])
    fps = spec["fps"] or 25.0

    conformed = "exact"
    if conform:
        if rep_dur > target + 0.05:
            conformed = "trimmed"
        elif rep_dur < target - 0.05:
            conformed = "padded"

    # 三段拼接：原[0,s) + 新段(对齐到 target) + 原[e,EOF)
    # 用 filter_complex 统一规格后再 concat（不同分辨率/帧率直接 concat 会失败）
    try:
        v_new = (f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                 f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}")
        if conform and conformed == "trimmed":
            v_new += f",trim=duration={target:.3f},setpts=PTS-STARTPTS"
        elif conform and conformed == "padded":
            v_new += f",tpad=stop_mode=clone:stop_duration={max(0.0, target - rep_dur) + 0.2:.3f}"
            v_new += f",trim=duration={target:.3f},setpts=PTS-STARTPTS"
        else:
            v_new += ",setpts=PTS-STARTPTS"
        v_new += "[v1]"

        # 2026-10-09 通电修复：无音轨的输入会让 [0:a]/[1:a] 引用失败（e2e 实测抓到）。
        # 解法：keep_audio 时给每个输入加 "0:a?"（可选流）+ 无声源兜底 —— 更稳的做法是
        # 探测两输入是否有音轨：任一没有 ⇒ 整体走 -an（诚实：输出无音轨，而不是硬造静音）。
        has_a0 = _has_audio_stream(original)
        has_a1 = _has_audio_stream(replacement)
        keep_audio = keep_audio and has_a0 and has_a1
        if not keep_audio and (has_a0 or has_a1):
            logger.info("[segment_retake] 输入音轨不齐 ⇒ 输出改为无音轨（诚实处理，不硬造静音）")

        parts = [
            f"[0:v]trim=start=0:end={s:.3f},setpts=PTS-STARTPTS,setsar=1[v0]",
            v_new,
            f"[0:v]trim=start={e:.3f},setpts=PTS-STARTPTS,setsar=1[v2]",
        ]
        if keep_audio:
            parts += [
                # ⚠️ atrim 的第二个参数必须是具名的 `end=` —— 写成 `atrim=start=0:0.5` 是非法滤镜
                #   （实测踩过：拼接整条失败）。修复后真机通过。
                "[0:a]atrim=start=0:end={s:.3f},asetpts=PTS-STARTPTS,aresample=48000[a0]".format(s=s),
                f"[1:a]atrim=start=0:end={target:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                f"apad,atrim=duration={target:.3f}[a1]",
                "[0:a]atrim=start={e:.3f},asetpts=PTS-STARTPTS,aresample=48000[a2]".format(e=e),
                "[a0][a1][a2]concat=n=3:v=0:a=1[aout]",
            ]
        fc = ";".join(parts) + ";[v0][v1][v2]concat=n=3:v=1:a=0[vout]"
        if keep_audio:
            fc += ";[aout]anull[aoutx]"

        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", original, "-i", replacement,
               "-filter_complex", fc, "-map", "[vout]"]
        cmd += ["-map", "[aoutx]"] if keep_audio else ["-an"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast"]
        if keep_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += [out_path]

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            return {"ok": False, "reason": f"拼接失败: {(r.stderr or '')[-600:]}"}

        out_dur = probe_duration(out_path)
        return {"ok": True, "out": out_path, "plan": plan, "conformed": conformed,
                "replacement_duration": round(rep_dur, 3), "target_duration": round(target, 3),
                "out_duration": round(out_dur, 3),
                "kept_audio": bool(keep_audio),
                "seams": plan["seams"], "seam_risk": plan["seam_risk"],
                "note": f"已用新段替换 {s:.2f}-{e:.2f}s"
                        + (f"（新段 {rep_dur:.2f}s 已{'裁到' if conformed == 'trimmed' else '补到'}"
                           f" {target:.2f}s 以对齐时间轴）" if conformed != "exact" else "（时长恰好一致）")
                        + f"；接缝风险 {plan['seam_risk']}"}
    except Exception as e:
        logger.exception("[segment_retake] splice_retake 失败")
        return {"ok": False, "reason": str(e)}
