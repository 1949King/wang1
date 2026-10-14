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

try:  # 云端视觉 enrich 要 base64 图片；本机无此依赖时不至于整体导入失败
    import base64
except ImportError:  # pragma: no cover（base64 是标准库，正常不会缺）
    base64 = None  # type: ignore[assignment]

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


# ── L2 运动级：从深度图推断运镜（2026-10-09 通电，接 video_depth）───────
#
# 为什么用深度而不是直接比像素：像素差受「物体自身运动」干扰（人物走动会造成
# 大面积像素变化，但其实镜头没动）。深度图描述的是**空间结构**，镜头推拉摇移时
# 整幅深度会整体平移/缩放，而物体自身运动只影响局部 ⇒ 对运镜更鲁棒。
#
# 两个估计量（都是标准 CV 方法，不编造）：
#   · 平移：cv2.phaseCorrelate（相位相关，亚像素级平移估计）
#   · 推拉：在候选缩放因子里搜最优（重采样后与另一帧 MSE 最小者）

MOVES = ("static", "dolly_in", "dolly_out", "pan_left", "pan_right", "tilt_up", "tilt_down")

# 运镜结论的**最低置信度**：低于它就不写进「运镜」字段（只留详情）
CAMERA_MOVE_MIN_CONFIDENCE = 0.4
_ZOOM_CANDIDATES = (0.90, 0.94, 0.97, 1.0, 1.03, 1.06, 1.11)

# ── 运镜词表映射（L2 深度术语 → 镜头表「运镜」列中文词）───────────────
#
# 为什么需要：`infer_camera_move` 返回的是 CV 术语（dolly_in/pan_left…），
# 而镜头表「运镜」列用中文影视词（推/拉/摇/移…）—— 同一语义两套词，
# 直接写进去用户看不懂。映射是**保守多对一**：CV 术语没有对应中文词的
# （如 static/unknown）一律映射回空串，交由调用方决定是否留空（不硬凑）。
CAMERA_MOVE_ZH: Dict[str, str] = {
    "dolly_in": "推",
    "dolly_out": "拉",
    "pan_left": "摇",
    "pan_right": "摇",
    "tilt_up": "摇",
    "tilt_down": "摇",
}


def camera_move_zh(move: str) -> str:
    """**纯函数**：把 L2 运镜 CV 术语映射成镜头表「运镜」列中文词。

    没有对应中文词（static/unknown/空）返回空串 —— 调用方据此留空，
    **绝不把「固定」当结论写进去**（固定机位是"没有运动"，不是一种运镜结论）。
    """
    return CAMERA_MOVE_ZH.get(str(move or "").strip().lower(), "")


def read_bgr(path: str):
    """读彩色图（estimate_depth_bgr 要 BGR）。

    ⚠️ 与 read_gray_small 同理：**不能用 cv2.imread**（本项目路径含中文，
    OpenCV 在 Windows 上会静默返回 None）。用 np.fromfile + cv2.imdecode。
    """
    import cv2
    import numpy as np

    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except Exception as e:
        logger.debug("[reference_breakdown] 读彩色图失败 %s: %s", path, e)
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def infer_camera_move(depth_a, depth_b, *,
                      pan_thresh: float = 0.8,
                      zoom_thresh: float = 0.02) -> Dict[str, Any]:
    """**纯函数**：从「段首深度图 + 段尾深度图」推断运镜（L2）。

    Args:
        depth_a/depth_b: 两个二维深度图（同尺寸；DPT 输出越大越近）
        pan_thresh:  平移判定阈值（像素，160x90 尺度下的经验值）
        zoom_thresh: 缩放判定阈值（比例，如 0.02 = 2%）

    Returns:
        {"move": MOVES 之一, "confidence": 0~1, "dx"/"dy": 平移像素,
         "scale": 缩放比（>1 表示画面变大=推近）, "reason": 人类可读依据}
    全平/尺寸不符等无法判断的情况 ⇒ move="unknown" + reason（**不猜**）。
    """
    import cv2
    import numpy as np

    a = np.asarray(depth_a, dtype="float32")
    b = np.asarray(depth_b, dtype="float32")
    if a.ndim != 2 or b.ndim != 2 or a.shape != b.shape or a.size == 0:
        return {"move": "unknown", "confidence": 0.0, "dx": 0.0, "dy": 0.0,
                "scale": 1.0, "reason": "深度图尺寸不符或为空"}
    # 归一化到 [0,1]（不同帧的绝对深度尺度不可比，只比结构）
    def _norm(x):
        lo, hi = float(x.min()), float(x.max())
        return (x - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(x)
    na, nb = _norm(a), _norm(b)
    if float(na.std()) < 1e-6 or float(nb.std()) < 1e-6:
        return {"move": "unknown", "confidence": 0.0, "dx": 0.0, "dy": 0.0,
                "scale": 1.0, "reason": "深度图近似全平（无结构可比）"}

    # ① 平移：相位相关
    try:
        # response 是相位相关的相关性质量（0~1）：可作后续「平移估计可靠性」的信号
        # —— 目前未纳入置信度，先留着不丢（故以下划线前缀，避免误报未使用）。
        (dx, dy), _resp = cv2.phaseCorrelate(na, nb)
    except Exception:
        dx = dy = 0.0

    # ② 推拉：候选缩放里搜最优
    h, w = na.shape
    best_scale, best_err = 1.0, None
    base_err = float(np.mean((na - nb) ** 2))
    for sc in _ZOOM_CANDIDATES:
        if sc == 1.0:
            err = base_err
        else:
            M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 0.0, sc)
            warped = cv2.warpAffine(nb, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
            err = float(np.mean((na - warped) ** 2))
        if best_err is None or err < best_err:
            best_err, best_scale = err, sc

    # ③ 判定（2026-10-09 重写：改用「**谁更能解释差异**」——残差改善量）
    #
    # 为什么不用「平移像素 vs 缩放比例」直接比：两者量纲不同，用不同常数归一化
    # 纯属拍脑袋 —— 实测把「右摇 12px」误判成推拉（8% 的横移被 11% 的缩放"抢走"）。
    # 正确做法：分别用「平移模型」与「缩放模型」去补偿 nb，看谁把与 na 的差异
    # 解释得更好（残差下降更多），谁解释力强就是谁。
    def _mse(x, y):
        return float(np.mean((x - y) ** 2))

    err_raw = _mse(na, nb)
    # 平移补偿：b 相对 a 位移 (dx,dy) ⇒ 反向搬回去
    Ms = np.float32([[1, 0, -dx], [0, 1, -dy]])
    shifted = cv2.warpAffine(nb, Ms, (w, h), borderMode=cv2.BORDER_REPLICATE)
    err_shift = _mse(na, shifted)
    gain_shift = err_raw - err_shift

    # 缩放补偿：best_scale 是「nb 缩放多少能匹配 na」⇒ 直接用它
    Mz = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 0.0, best_scale)
    zoomed = cv2.warpAffine(nb, Mz, (w, h), borderMode=cv2.BORDER_REPLICATE)
    err_zoom = _mse(na, zoomed)
    gain_zoom = err_raw - err_zoom

    # 改善量显著性门槛：至少要把原始差异解释掉 5%，否则算「没动」
    sig = max(err_raw * 0.05, 1e-6)
    best_gain = max(gain_shift, gain_zoom)

    if best_gain <= sig:
        return {"move": "static", "confidence": 0.5, "dx": round(float(dx), 3),
                "dy": round(float(dy), 3), "scale": round(best_scale, 4),
                "reason": "平移/缩放模型都无法解释差异 ⇒ 固定机位"}

    conf = round(min(1.0, best_gain / max(err_raw, 1e-6)), 3)
    if gain_shift >= gain_zoom:
        # 方向语义（写清楚，避免再次写反）：
        #   phaseCorrelate(a,b) 给的是 **b 相对 a** 的位移
        #   dx > 0 ⇒ b 的内容相对 a 右移 ⇒ 镜头向左摇（pan_left）
        #   dy > 0 ⇒ b 的内容下移        ⇒ 镜头向上摇（tilt_up）
        if abs(dx) >= abs(dy):
            move = "pan_left" if dx > 0 else "pan_right"
            why = f"深度水平平移 {dx:+.2f}px（{'内容右移⇒镜头左摇' if dx > 0 else '内容左移⇒镜头右摇'}）"
        else:
            move = "tilt_up" if dy > 0 else "tilt_down"
            why = f"深度垂直平移 {dy:+.2f}px（{'内容下移⇒镜头上摇' if dy > 0 else '内容上移⇒镜头下摇'}）"
    else:
        # best_scale < 1 ⇒ nb 需缩小才能匹配 na ⇒ nb 比 na 大 ⇒ 画面变大 ⇒ 推近
        move = "dolly_in" if best_scale < 1.0 else "dolly_out"
        why = (f"深度整体缩放 {best_scale:.3f}"
               f"（{'<1 ⇒ 画面变大 ⇒ 推近' if best_scale < 1.0 else '>1 ⇒ 画面变小 ⇒ 拉远'}）")
    return {"move": move, "confidence": conf,
            "dx": round(float(dx), 3), "dy": round(float(dy), 3),
            "scale": round(best_scale, 4), "reason": why}


def extract_frame_with_backoff(video: str, at: float, out_path: str, *,
                              backoff: float = 0.15, tries: int = 4) -> Optional[float]:
    """在 ``at`` 秒取一帧；失败则**向前回退重试**（2026-10-09 修）。

    为什么需要回退而不是只 clamp：容器时长（如 2.0s）与**最后一帧时刻**（如 1.9s）
    不是一回事 —— ``end-0.05`` 可能已越过最后一帧，``-ss`` 直接返回空。
    L1 与 L2 都踩过这个坑，故统一成「取不到就往前退 0.15s，最多退 4 次」。

    Returns: 实际取到帧的时刻；全失败返回 None（调用方如实留空，不编造）。
    """
    for i in range(max(1, tries)):
        t = max(0.0, at - i * backoff)
        if extract_frame(video, t, out_path):
            return t
    return None


def camera_move_trusted(move: str, confidence: float) -> bool:
    """**纯函数**：这条运镜结论可不可信（决定要不要写进「运镜」字段）。

    判据：① 是有效运动（非 unknown/static）② 置信度 ≥ CAMERA_MOVE_MIN_CONFIDENCE。
    低置信度的推断只留在 `camera_move` 详情里，**不污染表格结论**。
    """
    if not move or move in ("unknown", "static"):
        return False
    try:
        return float(confidence) >= CAMERA_MOVE_MIN_CONFIDENCE
    except (TypeError, ValueError):
        return False


def _l2_camera_move(video: str, shot: Dict[str, Any], duration: float) -> Dict[str, Any]:
    """L2：取段首/尾帧 → 深度 → 运镜（**深度不可用就诚实留空**，不编造）。

    返回要 merge 进 shot 的字段；任何一步失败都返回带说明的空结果。
    """
    try:
        from app.core import video_depth as vd
    except Exception as e:
        logger.debug("[reference_breakdown] L2 跳过（video_depth 不可用）: %s", e)
        return {"运镜": "", "camera_move": {"move": "unknown", "reason": "深度模块不可用"}}
    av = vd.available()
    if not av.get("available"):
        return {"运镜": "", "camera_move": {"move": "unknown",
                                            "reason": av.get("reason") or "深度模型不可用"}}
    td = _tmp_dir()
    idx = shot["index"]
    pa = os.path.join(td, f"_rb_l2a_{idx}.jpg")
    pb = os.path.join(td, f"_rb_l2b_{idx}.jpg")
    t_a = shot["start"] + 0.05
    # 段尾取帧要 clamp：末尾镜头 end-0.05 可能超过最后一帧时刻（L1 已踩过此坑）
    t_b = min(shot["end"] - 0.05, max(t_a + 0.05, (duration or shot["end"]) - 0.05))
    if t_b <= t_a:
        return {"运镜": "", "camera_move": {"move": "unknown", "reason": "段太短，取不到两帧"}}
    try:
        # 用带回退的取帧（段尾越界是这个模块的老坑，统一在这里兜住）
        if extract_frame_with_backoff(video, t_a, pa) is None:
            return {"运镜": "", "camera_move": {"move": "unknown", "reason": "段首帧取不到"}}
        if extract_frame_with_backoff(video, t_b, pb) is None:
            return {"运镜": "", "camera_move": {"move": "unknown", "reason": "段尾帧取不到"}}
        ia, ib = read_bgr(pa), read_bgr(pb)
        if ia is None or ib is None:
            return {"运镜": "", "camera_move": {"move": "unknown", "reason": "帧读取失败"}}
        da, db = vd.estimate_depth_bgr(ia), vd.estimate_depth_bgr(ib)
        if da is None or db is None:
            return {"运镜": "", "camera_move": {"move": "unknown", "reason": "深度推理失败"}}
        mv = infer_camera_move(da, db)
        move = mv.get("move") or "unknown"
        conf = float(mv.get("confidence") or 0.0)
        # ★ 置信度门槛（2026-10-09）：低置信度的推断**不写进「运镜」字段**，
        #   只在 camera_move 详情里保留 —— 表格里的运镜应当是"可据以决策"的结论，
        #   而不是"算法猜了个但不自信"。实测：构造的明确平移/缩放可达 0.94~1.0，
        #   而生成图案（非真实场景）只有 0.13 ⇒ 用 0.4 分界能干净区分。
        trustworthy = camera_move_trusted(move, conf)
        # 运镜列写**中文影视词**（推/拉/摇），CV 术语只留在 camera_move 详情里
        # （2026-10-14：加词表映射前这里直接写 dolly_in 等英文，用户看不懂）
        return {"运镜": (camera_move_zh(move) if trustworthy else ""),
                "camera_move": mv,
                "camera_move_trusted": trustworthy}
    finally:
        for p in (pa, pb):
            try:
                os.remove(p)
            except Exception:  # stability-gate: allow-swallow（临时帧清理；失败只留一个临时文件）
                pass


# ── 景别/画面描述 enrich：云端视觉模型（2026-10-14）───────────────────
#
# 为什么放在本模块（而不是复用 canvas_shot_vision）：
#   canvas_shot_vision 服务的是**另一条线**（/host/video-storyboard 的
#   前端分镜表，字段是 shot/camera/description 英文键），且只走本机 Ollama；
#   本模块是**镜头表 owner**（景别/运镜两列的中文键），且按用户要求走
#   **云端视觉模型**（素材出域，需显式开启）。两线的词表与渠道都不同，
#   强行合并只会两边都别扭 —— 这里只复用它的抽帧 helper（同一套安全路径）。
#
# 诚实降级（红线）：
#   · 云端 provider 未配置 / 不可用 / 单镜解析失败 → 该镜景别**留空**，
#     绝不回填默认值（"中景/固定"这类默认值会让用户以为算法真看出来了）；
#   · 视觉模型的「运镜」结论优先写进「运镜」列（人眼判断比相位相关可靠），
#     深度推断的结果继续留在 camera_move 详情里，两者不互相覆盖丢失。

# 景别/运镜词表（与前端分镜表列候选一致）
_SHOT_SIZES = ("特写", "近景", "中景", "全景", "远景")
_CAMERAS = ("固定", "推", "拉", "摇", "移", "跟", "升", "降", "手持", "环绕")

_VISION_PROMPT = (
    "你是影视分镜助理。给你同一镜头的起始帧与结束帧（也可能只有 1 帧）。"
    "只输出一个 JSON 对象，不要任何多余文字，字段如下：\n"
    '{"shot_size":"特写|近景|中景|全景|远景",'
    '"camera":"固定|推|拉|摇|移|跟|升|降|手持|环绕",'
    '"description":"不超过30字，概括画面内容与镜头语言"}\n'
    "若画面无明显位移或缩放、无法判断运镜，camera 填「固定」。"
)

# 云端视觉模型候选（provider, model）：按「便宜能用」排序，第一个可用者胜出。
# qwen-vl 系列走阿里云 DashScope 的 OpenAI 兼容端点（ai_engine 已有 qwen provider），
# doubao 是火山方舟（同 ai_engine 既有 provider）—— **不新增任何渠道**。
_CLOUD_VISION_CANDIDATES = (
    ("qwen", "qwen-vl-max-latest"),
    ("qwen", "qwen-vl-plus-latest"),
    ("doubao", "doubao-vision-pro-32k"),
)


def _norm_choice(value: Any, allowed: tuple, default: str = "") -> str:
    """把模型输出规整到词表内：含关键词即命中，否则回退 default（诚实降级）。"""
    text = str(value or "").strip()
    for a in allowed:
        if a and a in text:
            return a
    return default


def _resolve_cloud_vision(model: str = "") -> tuple:
    """选一个可用的云端视觉模型，返回 (provider, model)；都不可用返回 ("", "")。

    显式传了 `vision_model` 时优先尝试它（provider 由候选表推断；推断不出
    则按 qwen 渠道试一次 —— 失败也只是这一镜解析失败，不影响别的镜头）。
    """
    if model:
        for prov, m in _CLOUD_VISION_CANDIDATES:
            if m == model:
                return prov, m
        return "qwen", model
    for prov, m in _CLOUD_VISION_CANDIDATES:
        try:
            from app.core.ai_engine import ai_engine

            ai_engine._ensure_clients()
            if ai_engine.is_provider_available(prov):
                return prov, m
        except Exception as e:
            logger.debug("[reference_breakdown] 视觉 provider 探测失败 %s: %s", prov, e)
    return "", ""


def _ask_cloud_vision(provider: str, model: str, frames: List[bytes]) -> Optional[Dict[str, Any]]:
    """把帧发给云端视觉模型（OpenAI 兼容多模态消息），返回解析后的 dict。"""
    if not frames or base64 is None:
        return None
    images = ["data:image/jpeg;base64," + base64.b64encode(b).decode("ascii") for b in frames]
    content: List[Dict[str, Any]] = [{"type": "text", "text": _VISION_PROMPT}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": img}})
    messages = [{"role": "user", "content": content}]
    try:
        from app.core.ai_engine import ai_engine

        parts = list(ai_engine.chat(provider, messages, model=model,
                                    stream=False, use_cache=False))
        text = "".join(parts).strip()
    except Exception as e:
        logger.warning("[reference_breakdown] 云端视觉解析调用失败: %s", e)
        return None
    if not text or text.startswith("错误") or text.startswith("API 错误"):
        logger.debug("[reference_breakdown] 云端视觉返回异常: %s", text[:120])
        return None
    return _parse_json_obj_loose(text)


def _parse_json_obj_loose(text: str) -> Optional[Dict[str, Any]]:
    """容错解析模型输出：先直取 JSON，再退而截取首个 {...} 片段。"""
    import json as _json

    try:
        data = _json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        # 直取失败属正常路径（模型常在 JSON 前后带话）——走片段兜底，但留痕便于排查。
        logger.debug("参考素材拆解：模型输出非直取 JSON，转片段兜底", exc_info=True)
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = _json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            return None
    return None


def _apply_vision_enrich(shots: List[Dict[str, Any]], video: str, *,
                         model: str = "") -> Dict[str, Any]:
    """逐镜调云端视觉模型补「景别/运镜/描述」（就地回填 shots）。

    返回 enrich 结果摘要（vision_used / vision_model / vision_message），
    由 build_shot_table 合并进返回值 —— 失败也如实写 message，不静默。
    """
    out: Dict[str, Any] = {"vision_used": False, "vision_model": "",
                           "vision_message": ""}
    if not shots:
        out["vision_message"] = "无可解析的镜头"
        return out
    provider, resolved = _resolve_cloud_vision(model)
    if not provider:
        out["vision_message"] = "没有可用的云端视觉模型（请在模型管理配置 Key）"
        return out
    out["vision_model"] = f"{provider}/{resolved}"

    # 抽帧 helper 复用 canvas_shot_vision（同一套 .workbuddy/tmp 安全路径）
    try:
        from app.core.canvas_shot_vision import _extract_vision_frames
    except ImportError:
        from core.canvas_shot_vision import _extract_vision_frames  # type: ignore

    enriched = 0
    for item in shots:
        try:
            frames = _extract_vision_frames(video, float(item.get("start") or 0.0),
                                            float(item.get("end") or 0.0))
        except Exception as e:
            logger.debug("[reference_breakdown] 镜%d 抽帧失败: %s", item.get("index"), e)
            frames = []
        parsed = _ask_cloud_vision(provider, resolved, frames)
        if not parsed:
            continue
        size = _norm_choice(parsed.get("shot_size"), _SHOT_SIZES)
        if size:
            item["景别"] = size
        camera = _norm_choice(parsed.get("camera"), _CAMERAS)
        if camera and camera != "固定":
            # 视觉运镜优先于深度推断（人眼判断更可靠）；深度结果仍在详情里
            item["运镜"] = camera
        desc = str(parsed.get("description") or "").strip()
        if desc:
            item["描述"] = desc[:60]
        item["vision"] = True
        enriched += 1

    out["vision_used"] = enriched > 0
    if enriched == 0:
        out["vision_message"] = "云端视觉模型未返回可用结果，景别/运镜保持留空"
    elif enriched < len(shots):
        out["vision_message"] = f"视觉解析 {enriched}/{len(shots)} 镜，其余留空"
    else:
        out["vision_message"] = f"视觉解析完成：{enriched} 镜（{out['vision_model']}）"
    return out


def build_shot_table(video: str, *, out_dir: str,
                     threshold: float = DEFAULT_SCENE_THRESHOLD,
                     keyframes: bool = True,
                     with_depth: bool = False,
                     use_vision: bool = False,
                     vision_model: str = "") -> Dict[str, Any]:
    """L1 主入口：参考片 → **结构化镜头表**（含关键帧与可测指标）。

    产物：
      · `shots[]`：镜号 / 起止 / 时长 / 关键帧路径 / 运动量 / 亮度 / 对比度
      · `table_markdown`：可直接贴进文档或作为分镜参考的表格
    当 ``with_depth=True`` 时额外跑 **L2 运动级**：取每段首/尾帧的深度图，
    用 ``infer_camera_move``（相位相关 + 缩放搜索）推断**运镜**（推拉摇移/固定）。
    当 ``use_vision=True`` 时再跑 **景别/画面描述 enrich**（云端视觉模型，
    素材会出域，需用户显式开启；失败/未配置时诚实留空并标注）。

    ⚠️ 诚实边界（四条）：
      1. 默认**景别、光线基调不推断**（留空）；``use_vision=True`` 才调云端视觉模型；
      2. 运镜只在**置信度 ≥ CAMERA_MOVE_MIN_CONFIDENCE** 时才写进「运镜」字段 ——
         低置信度的推断只留在 `camera_move` 详情里（`camera_move_trusted=False`）；
      3. **固有局限**：本方法比较的是「整幅深度结构的变化」，因此**无法区分
         「镜头在动」与「画面内大物体在动」**。拍摄场景相对静态时结论可靠；
         画面内有大幅物体运动时可能混淆 —— 置信度会下降，但不保证；
      4. ``use_vision`` 的视觉结论**优先于**深度运镜结论写进「运镜」列
         （人眼判断比相位相关更可靠），深度结果退守 `camera_move` 详情不丢失。
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
        # ── L2 运动级（2026-10-09 通电）：深度 → 运镜推断 ──
        if with_depth:
            item.update(_l2_camera_move(video, s, det.get("duration") or 0.0))
        shots.append(item)

    # ── 景别/画面描述 enrich（2026-10-14）：云端视觉模型（素材出域，显式开启）──
    vision_info: Dict[str, Any] = {}
    if use_vision:
        vision_info = _apply_vision_enrich(shots, video, model=vision_model)

    result: Dict[str, Any] = {"ok": True, "video": video, "duration": det["duration"],
                              "count": len(shots), "threshold": det["threshold"],
                              "shots": shots, "table_markdown": shots_to_markdown(shots),
                              "note": ("L1 结构级：切点/时长/关键帧/可测指标均为真实计算结果"
                                       + ("；景别/运镜已由云端视觉模型 enrich" if use_vision else "；景别**未推断**（诚实留空）")
                                       + ("；L2 运动级已启用（运镜由深度图推断，带 confidence）"
                                          if with_depth else "；运镜未跑（with_depth=False）"))}
    if vision_info:
        result.update(vision_info)
    return result


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
