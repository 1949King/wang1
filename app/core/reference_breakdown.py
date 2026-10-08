# -*- coding: utf-8 -*-
"""逐帧拉片 · L1（结构级）—— 参考片 → 结构化镜头表（2026-10-06）。

对标 LibTV「逐帧拉片 / 爆款复刻」的**第一级**：把一部参考片拆成
**镜头段（切点 + 时长）+ 每段关键帧 + 每段可测的画面指标**。

三级路线（本模块只做 L1，且**只做算得出来的**）
============================================
  · **L1 结构级（本模块）**：场景切分（真实像素差异）+ 关键帧导出 + **可测指标**
    （运动量 / 亮度 / 对比度）⇒ 产出**结构化镜头表**。全部**无 AI、可复现、零成本**。
  · L2 运动级（待做）：在每段上跑深度/姿势（我们已有 `video_depth`）推断推拉摇移。
  · L3 复刻级（待做）：把 L1+L2 变成可执行的分镜节点序列（换角色/换场景）。

⚠️ **诚实边界（重要）**：本模块**不猜景别、不猜运镜、不猜光线**。
那些需要模型判断，硬猜就是编造。L1 只给**能算出来的东西**：
切点、时长、每段关键帧、以及由像素直接统计出的运动量/亮度/对比度
（景别/运镜留给 L2 或人工，表里明确留空 —— **宁可空着，不编**）。

与既有能力的边界（别重复造）
==========================
`add_keyframe` / `set_keyframes` 是**剪辑动画关键帧**，与本模块的"镜头关键帧"不是一回事；
仓库里也**没有**场景切分实现（已核实），故本模块是新增而不是重复。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SCENE_THRESHOLD = 0.30
DEFAULT_MIN_SHOT = 0.40  # 秒：短于此的段并入前一段（避免把闪帧当镜头）

# ffmpeg metadata=print 的输出形如：
#   frame:12   pts:512   pts_time:2
#   lavfi.scene_score=0.456789
_PTS_RE = re.compile(r"pts_time:([0-9.]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def _ffmpeg() -> Optional[str]:
    from app.core.ffmpeg_utils import find_ffmpeg

    return find_ffmpeg()


def parse_scene_points(text: str) -> List[Dict[str, float]]:
    """从 ffmpeg 输出里解析切点（**纯函数**，便于用真实样例做测试）。

    返回 `[{"time": 秒, "score": 场景分}]`，按时间排序。
    """
    out: List[Dict[str, float]] = []
    pending: Optional[Dict[str, float]] = None
    for line in (text or "").splitlines():
        m = _PTS_RE.search(line)
        if m:
            if pending:
                out.append(pending)
            pending = {"time": float(m.group(1)), "score": 0.0}
            continue
        s = _SCORE_RE.search(line)
        if s and pending:
            pending["score"] = float(s.group(1))
    if pending:
        out.append(pending)
    return sorted(out, key=lambda d: d["time"])


def probe_duration(video: str) -> float:
    """用 ffprobe/ffmpeg 拿时长；拿不到返回 0.0（调用方如实处理）。"""
    ff = _ffmpeg()
    if not ff:
        return 0.0
    try:
        r = subprocess.run([ff, "-i", video], capture_output=True, text=True, timeout=60)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
        if not m:
            return 0.0
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s
    except Exception as e:
        logger.debug("[reference_breakdown] 取时长失败: %s", e)
        return 0.0


def merge_short_shots(cuts: List[float], duration: float,
                      min_shot: float = DEFAULT_MIN_SHOT) -> List[Dict[str, float]]:
    """把切点整理成镜头段（**纯函数**）：短于 `min_shot` 的段并入前一段。

    为什么需要：闪帧/叠化会被场景检测切成极小段，直接当"镜头"会让表不可读。
    """
    # 边界处理（2026-10-09 优化）：
    #   · 切点 ≤0 或 ≥duration 的**越界值**依旧丢弃（那是脏数据）；
    #   · **首个镜头太短**时无处可并（没有前一段）—— 旧版会静默丢弃它，
    #     导致开头 0~0.3s 凭空消失。现在改为**并入后一段**（保住素材完整性）。
    points = [0.0] + [c for c in cuts if 0.0 < c < (duration or c)] + ([duration] if duration else [])
    points = sorted(set(round(p, 3) for p in points))
    if len(points) < 2:
        return []
    # 归一化段列表（先全部生成，再做短段合并——首段并入后段，其余并入前段）
    raw = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    merged: List[List[float]] = []
    for start, end in raw:
        if (end - start) < min_shot:
            if merged:
                merged[-1][1] = end          # 有前段 ⇒ 并入前段
            elif raw.index((start, end)) < len(raw) - 1:
                continue                      # 是首段且后面还有段 ⇒ 并入后段（先跳过）
            else:
                merged.append([start, end])   # 全片只有一个短段 ⇒ 保留（不能空手而归）
        else:
            merged.append([start, end])
    # 处理被跳过的首段：把后段起点前移（真正"并入后段"）
    if raw and merged and merged[0][0] > raw[0][0]:
        merged[0][0] = raw[0][0]
    shots: List[Dict[str, float]] = []
    for start, end in merged:
        shots.append({"index": len(shots) + 1, "start": round(start, 3),
                      "end": round(end, 3)})
    for s_ in shots:
        s_["duration"] = round(s_["end"] - s_["start"], 3)
    return shots


def detect_scenes(video: str, *, threshold: float = DEFAULT_SCENE_THRESHOLD,
                  min_shot: float = DEFAULT_MIN_SHOT) -> Dict[str, Any]:
    """场景切分（真实像素差异，无 AI）。返回镜头段列表。"""
    ff = _ffmpeg()
    if not ff:
        return {"ok": False, "reason": "ffmpeg 不可用（场景切分依赖它）"}
    if not os.path.isfile(video):
        return {"ok": False, "reason": f"找不到视频: {video}"}
    try:
        cmd = [ff, "-hide_banner", "-i", video, "-an",
               "-vf", f"select='gt(scene,{threshold})',metadata=print",
               "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        pts = parse_scene_points(r.stderr or "")
        dur = probe_duration(video)
        shots = merge_short_shots([p["time"] for p in pts], dur, min_shot)
        if not shots:
            return {"ok": False, "duration": dur,
                    "reason": "没检出镜头段（视频可能过短或切点阈值偏高）"}
        return {"ok": True, "duration": round(dur, 3), "threshold": threshold,
                "cuts": [round(p["time"], 3) for p in pts],
                "shots": shots, "count": len(shots),
                "note": "切点由真实像素差异检出；景别/运镜**未推断**（留给 L2 或人工）"}
    except Exception as e:
        logger.exception("[reference_breakdown] 场景切分失败")
        return {"ok": False, "reason": str(e)}


def _tmp_dir() -> str:
    """本模块的临时目录（固定 `.workbuddy/tmp`，**绝不落项目根**）。"""
    d = os.path.join(repo_root(), ".workbuddy", "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def frame_metrics(img_bgr) -> Dict[str, float]:
    """单帧可测指标（**纯统计，无 AI**）：亮度 / 对比度。"""
    import numpy as np

    g = np.asarray(img_bgr)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)
    g = g.astype("float32") / 255.0
    return {"brightness": round(float(g.mean()), 4), "contrast": round(float(g.std()), 4)}


def motion_between(a, b) -> float:
    """两帧之间的运动量（0~1，**纯统计**）：平均绝对差。"""
    import numpy as np

    x = np.asarray(a, dtype="float32") / 255.0
    y = np.asarray(b, dtype="float32") / 255.0
    if x.ndim == 3:
        x = x.mean(axis=2)
    if y.ndim == 3:
        y = y.mean(axis=2)
    if x.shape != y.shape:
        return 0.0
    return round(float(np.abs(x - y).mean()), 4)


def extract_frame(video: str, at: float, out_path: str) -> bool:
    """在 `at` 秒处导出一帧（关键帧）。"""
    ff = _ffmpeg()
    if not ff:
        return False
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                            "-ss", f"{max(0.0, at):.3f}", "-i", video,
                            "-frames:v", "1", "-q:v", "3", out_path],
                           capture_output=True, text=True, timeout=180)
        return r.returncode == 0 and os.path.isfile(out_path)
    except Exception as e:
        logger.debug("[reference_breakdown] 导帧失败 %.3fs: %s", at, e)
        return False


def read_gray_small(path: str):
    """读图为 160x90 灰度。

    ⚠️ **不能用 `cv2.imread`**：本项目路径含中文（`D:////拾光剪影////...`），
    OpenCV 在 Windows 上对非 ASCII 路径会**读不到并静默返回 None**（实测踩过：
    指标变成 None 而 `ok` 仍为 True ⇒ 静默降级）。改用 `np.fromfile + cv2.imdecode`。
    """
    import cv2
    import numpy as np

    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except Exception as e:
        logger.debug("[reference_breakdown] 读图失败 %s: %s", path, e)
        return None
    if buf.size == 0:
        return None
    img = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)


def build_shot_table(video: str, *, out_dir: str,
                     threshold: float = DEFAULT_SCENE_THRESHOLD,
                     keyframes: bool = True) -> Dict[str, Any]:
    """L1 主入口：参考片 → **结构化镜头表**（含关键帧与可测指标）。

    产物：
      · `shots[]`：镜号 / 起止 / 时长 / 关键帧路径 / 运动量 / 亮度 / 对比度
      · `table_markdown`：可直接贴进文档或作为分镜参考的表格
    ⚠️ 景别、运镜、光线基调**不做推断**（表里明确留空，避免编造）。
    """
    det = detect_scenes(video, threshold=threshold)
    if not det.get("ok"):
        return det
    shots: List[Dict[str, Any]] = []
    os.makedirs(out_dir, exist_ok=True)

    for s in det["shots"]:
        mid = (s["start"] + s["end"]) / 2.0
        item: Dict[str, Any] = {"index": s["index"], "start": s["start"],
                                "end": s["end"], "duration": s["duration"],
                                "景别": "", "运镜": "", "keyframe": ""}
        if keyframes:
            kf = os.path.join(out_dir, f"shot_{s['index']:03d}.jpg")
            if extract_frame(video, mid, kf):
                item["keyframe"] = kf
                g = read_gray_small(kf)
                if g is not None:
                    item.update(frame_metrics(g))
                else:
                    logger.warning("[reference_breakdown] 关键帧读不到，指标留空（不编数）: %s", kf)
        # 运动量：段首帧 vs 段中帧（真实像素差）
        # ⚠️ 只再抽**一帧**（段首），段中直接用已导出的关键帧：
        #   ① 更省一次 ffmpeg 调用；
        #   ② 实测踩过边界 —— 取 `end - 0.05` 在末尾镜头会**超出最后一帧的时刻**，
        #      取帧失败 ⇒ 指标静默缺失（表里显示「—」却不知道原因）。
        if keyframes and item.get("keyframe") and s["duration"] > 0.2:
            td = _tmp_dir()   # 不用 tempfile.gettempdir()（本沙箱会回退到 cwd=项目根）
            p1 = os.path.join(td, f"_rb_head_{s['index']}.jpg")
            if extract_frame(video, s["start"] + 0.05, p1):
                g1 = read_gray_small(p1)
                g2 = read_gray_small(item["keyframe"])
                if g1 is not None and g2 is not None:
                    item["motion"] = motion_between(g1, g2)
                else:
                    logger.warning("[reference_breakdown] 运动量算不出（读帧失败），留空不编数: 镜%d", s["index"])
            else:
                logger.warning("[reference_breakdown] 段首帧取不到，运动量留空不编数: 镜%d", s["index"])
            try:
                os.remove(p1)
            except Exception:  # stability-gate: allow-swallow（删临时帧的清理动作；删不掉只留一个临时文件，不掩盖任何崩溃根因）
                pass
        shots.append(item)

    return {"ok": True, "video": video, "duration": det["duration"],
            "count": len(shots), "threshold": det["threshold"],
            "shots": shots, "table_markdown": shots_to_markdown(shots),
            "note": "L1 结构级：切点/时长/关键帧/可测指标均为真实计算结果；"
                    "景别与运镜**未推断**（诚实留空，留给 L2 或人工）"}


def shots_to_markdown(shots: List[Dict[str, Any]]) -> str:
    """镜头表 → Markdown（纯函数）。"""
    head = ("| 镜号 | 起点(s) | 时长(s) | 运动量 | 亮度 | 对比度 | 景别 | 运镜 | 关键帧 |\n"
            "|---|---|---|---|---|---|---|---|---|\n")
    rows = []
    for s in shots:
        rows.append("| {i} | {a:.2f} | {d:.2f} | {m} | {b} | {c} | {sz} | {mv} | {kf} |".format(
            i=s["index"], a=s["start"], d=s["duration"],
            m=(f"{s['motion']:.3f}" if isinstance(s.get("motion"), float) else "—"),
            b=(f"{s['brightness']:.3f}" if isinstance(s.get("brightness"), float) else "—"),
            c=(f"{s['contrast']:.3f}" if isinstance(s.get("contrast"), float) else "—"),
            sz=s.get("景别") or "—", mv=s.get("运镜") or "—",
            kf=os.path.basename(s["keyframe"]) if s.get("keyframe") else "—",
        ))
    return head + "\n".join(rows) + "\n"
