"""审美量化分析器（真实像素测量 · 非固定基线）
================================================
``five_dimension_scorer`` 原先在缺少 ``quality_scores`` 时，五维一律填 70 分基线
——那是「量化」但不是「审美判断」：同一个 70 分既给糊片也给好片。

本模块用**确定性图像统计**给「画面质量」一个真实分数（无 ML、无网络、可复现）：

======================  ===================================================
子项                     依据
======================  ===================================================
``sharpness``           拉普拉斯方差（清晰度 / 失焦模糊）
``exposure``            平均亮度偏离 0.5 的程度 + 高光/暗部裁剪像素占比
``contrast``            亮度 RMS 对比度（标准差归一化）
``colorfulness``        Hasler & Süsstrunk (2003) 彩色度指标
``noise``               中值滤波残差标准差（高频噪声代理）
======================  ===================================================

另有 :func:`duration_reasonableness`：按短剧剪辑惯用的「1.5~4 秒舒适区」
给镜头时长一个真实分数（越偏离越扣分，含过短与过长两侧）。

诚实边界
--------
* 这些是**技术质量**指标，不等于「艺术审美」；构图只做了保守的
  「能量是否过度堆在正中」启发式，不做主体识别。
* 读不到帧 / 无 cv2 时**返回 None**，由调用方保留基线并如实标注 estimated，
  绝不假装测过。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("AI短剧编辑器.ai.aesthetic")

#: 视频抽帧数（等间隔，取均值 + 最差帧）
DEFAULT_SAMPLE_FRAMES = 9

#: 合成权重（技术质量维度内部，和 = 1.0）
_METRIC_WEIGHTS = {
    "sharpness": 0.32,
    "exposure": 0.18,
    "contrast": 0.18,
    "colorfulness": 0.20,
    "noise": 0.12,
}

#: 噪声对「3×3 中值滤波后拉普拉斯方差」的贡献增益（实测标定，2026-10-11）：
#:   纯灰底 + 高斯噪声 σ ∈ {5,10,15,20,26,32,40}，用本模块同一噪声估计子
#:   ``std(|gray − medianBlur(3)|)`` 测得 lapvar_med / noise_est²
#:   = 2.397 / 2.328 / 2.302 / 2.300 / 2.293 / 2.287 / 2.276
#:   ⇒ 取 2.29（极差 ±2.6%，与 σ 几乎无关，可当常数用）。
#: 扣除该项后，强噪声图不会因为「拉普拉斯方差被噪声顶高」而被误判成很锐。
_LAPLACIAN_NOISE_GAIN = 2.29


def _piecewise(value: float, table: List[Tuple[float, float]]) -> float:
    """分段线性映射（table 需按 x 升序），超出两端取端点值。"""
    if not table:
        return 0.0
    if value <= table[0][0]:
        return float(table[0][1])
    if value >= table[-1][0]:
        return float(table[-1][1])
    for (x0, y0), (x1, y1) in zip(table, table[1:], strict=False):
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y1)
            t = (value - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(table[-1][1])


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ============================================================
# 单帧
# ============================================================

def _imread_unicode(path: str) -> Any:
    """读图片，**兼容中文路径**。

    Windows 上 ``cv2.imread`` 走 ANSI 路径，遇到中文目录（本仓库就是
    ``D:\\拾光剪影\\...``）会静默返回 None。改用 ``np.fromfile`` + ``imdecode``。
    """
    try:
        import cv2

        buf = np.fromfile(path, dtype=np.uint8)
        if buf.size == 0:
            return None
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.debug("读取图片失败 %s: %s", path, e)
        return None


def analyze_frame(bgr: Any) -> Optional[Dict[str, float]]:
    """对单帧 BGR 图像做审美量化。失败返回 None。"""
    if bgr is None:
        return None
    try:
        import cv2
    except Exception as e:  # pragma: no cover - 环境相关
        logger.debug("cv2 不可用: %s", e)
        return None
    if getattr(bgr, "size", 0) == 0:
        return None

    try:
        gray_full = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # ① 噪声：在**原始分辨率**上估（先缩放会把噪声平均掉，导致高分辨率源被低估）
        med_full = cv2.medianBlur(gray_full, 3).astype(np.float32)
        noise = float(np.abs(gray_full.astype(np.float32) - med_full).std())

        # 统一到较小尺寸，让阈值与分辨率解耦
        h, w = bgr.shape[:2]
        scale = 512.0 / max(h, w) if max(h, w) > 512 else 1.0
        if scale < 1.0:
            bgr = cv2.resize(bgr, (max(1, int(w * scale)), max(1, int(h * scale))),
                             interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gf = gray.astype(np.float32)

        # ② 清晰度：拉普拉斯方差，**先用 3×3 中值滤波压下高频噪声**，
        #    再扣掉「噪声本身会贡献的那部分方差」（增益见 _LAPLACIAN_NOISE_GAIN）
        #    —— 否则强噪声图的拉普拉斯方差会暴涨，被误判成「很锐」
        gray_dn = cv2.medianBlur(gray, 3)
        lap = cv2.Laplacian(gray_dn, cv2.CV_64F)
        sharpness = max(0.0, float(lap.var()) - _LAPLACIAN_NOISE_GAIN * noise * noise)

        # ③ 曝光：平均亮度 + 裁剪
        luma = gf / 255.0
        mean_luma = float(luma.mean())
        over = float((gray >= 250).mean())
        under = float((gray <= 5).mean())

        # ④ 对比度：RMS 对比度
        contrast = float(gf.std() / 255.0)

        # ⑤ 彩色度：Hasler & Süsstrunk (2003)
        b, g, r = (bgr[:, :, i].astype(np.float32) for i in range(3))
        rg = r - g
        yb = 0.5 * (r + g) - b
        colorfulness = float(
            np.sqrt(rg.std() ** 2 + yb.std() ** 2)
            + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
        )

        s_sharp = _piecewise(sharpness, [(20, 0), (60, 40), (150, 70), (400, 90), (800, 100)])
        s_expo = _clamp(
            100.0 - 220.0 * abs(mean_luma - 0.5) - 260.0 * over - 260.0 * under
        )
        s_cont = _piecewise(contrast, [(0.0, 0), (0.05, 35), (0.12, 70), (0.20, 90), (0.28, 100)])
        s_colo = _piecewise(colorfulness, [(0, 0), (15, 40), (30, 65), (50, 85), (75, 100)])
        s_nois = _piecewise(noise, [(0, 100), (3, 85), (6, 60), (10, 30), (16, 0)])

        composite = (
            s_sharp * _METRIC_WEIGHTS["sharpness"]
            + s_expo * _METRIC_WEIGHTS["exposure"]
            + s_cont * _METRIC_WEIGHTS["contrast"]
            + s_colo * _METRIC_WEIGHTS["colorfulness"]
            + s_nois * _METRIC_WEIGHTS["noise"]
        )
        return {
            "sharpness": sharpness,
            "mean_luma": mean_luma,
            "over_ratio": over,
            "under_ratio": under,
            "contrast": contrast,
            "colorfulness": colorfulness,
            "noise": noise,
            "sharpness_score": s_sharp,
            "exposure_score": s_expo,
            "contrast_score": s_cont,
            "colorfulness_score": s_colo,
            "noise_score": s_nois,
            "composite": _clamp(composite),
        }
    except Exception as e:
        logger.debug("单帧分析失败: %s", e)
        return None


# ============================================================
# 整段（视频 / 图片）
# ============================================================

def _is_image(path: str) -> bool:
    return os.path.splitext(str(path))[1].lower() in (
        ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
    )


def analyze_media(
    path: str, max_frames: int = DEFAULT_SAMPLE_FRAMES
) -> Optional[Dict[str, Any]]:
    """分析视频或图片，返回逐帧统计 + 汇总分。不可分析返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        import cv2
    except Exception:
        return None

    samples: List[Dict[str, float]] = []
    try:
        if _is_image(path):
            img = _imread_unicode(path)
            one = analyze_frame(img)
            if one is None:
                return None
            samples = [one]
        else:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return None
            try:
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                n = max(1, int(max_frames))
                if total > 0:
                    idxs = [int(round(i * (total - 1) / max(1, n - 1))) for i in range(n)]
                else:  # 帧数未知：顺序读到 n 帧
                    idxs = None
                if idxs is not None:
                    for i in idxs:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                        ok, frame = cap.read()
                        if not ok:
                            continue
                        s = analyze_frame(frame)
                        if s:
                            samples.append(s)
                else:
                    got = 0
                    while got < n:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        s = analyze_frame(frame)
                        if s:
                            samples.append(s)
                        got += 1
            finally:
                cap.release()
    except Exception as e:
        logger.debug("媒体分析失败 %s: %s", path, e)
        return None

    if not samples:
        return None

    keys = ("sharpness", "contrast", "colorfulness", "noise",
            "sharpness_score", "exposure_score", "contrast_score",
            "colorfulness_score", "noise_score", "composite")
    agg: Dict[str, Any] = {
        k: float(np.mean([s[k] for s in samples])) for k in keys
    }
    composites = [s["composite"] for s in samples]
    agg["frames_analyzed"] = len(samples)
    agg["composite_min"] = float(min(composites))
    agg["composite_max"] = float(max(composites))
    agg["composite_std"] = float(np.std(composites))
    # 一两个烂帧不该被好帧平均掉 ⇒ 均值打底，最差帧拉低
    agg["visual_quality"] = _clamp(0.65 * agg["composite"] + 0.35 * agg["composite_min"])
    return agg


def visual_quality_from_media(path: str, max_frames: int = DEFAULT_SAMPLE_FRAMES) -> Optional[float]:
    """便捷入口：直接拿 0-100 的「画面质量」分。不可分析返回 None。"""
    agg = analyze_media(path, max_frames=max_frames)
    return None if agg is None else float(agg["visual_quality"])


# ============================================================
# 镜头时长合理性
# ============================================================

#: 短剧剪辑的「舒适区」（秒）—— 1.5~4s 内满分
IDEAL_SHOT_RANGE = (1.5, 4.0)
#: 时长打分曲线：(秒, 分)
_DURATION_TABLE = [
    (0.0, 0.0),
    (0.3, 15.0),
    (0.6, 38.0),
    (1.0, 62.0),
    (1.5, 100.0),
    (4.0, 100.0),
    (5.0, 92.0),
    (6.0, 82.0),
    (8.0, 62.0),
    (10.0, 48.0),
    (15.0, 32.0),
    (30.0, 15.0),
    (60.0, 8.0),
]


def duration_reasonableness(duration: float) -> float:
    """镜头时长合理性 0-100（越接近舒适区越高，过短/过长两侧都扣分）。"""
    try:
        d = float(duration)
    except (TypeError, ValueError):
        return 50.0
    if d <= 0:
        return 0.0
    return _clamp(_piecewise(d, _DURATION_TABLE))


def rhythm_consistency(durations: List[float]) -> Optional[float]:
    """相邻镜头时长节律一致性 0-100（变异系数越小越稳；样本 <3 返回 None）。

    仅作诊断/建议用，不直接进五维权重（权重是用户定稿的）。
    """
    ds = [float(d) for d in durations if d and float(d) > 0]
    if len(ds) < 3:
        return None
    mean = float(np.mean(ds))
    if mean <= 0:
        return None
    cv = float(np.std(ds) / mean)
    return _clamp(_piecewise(cv, [(0.0, 100), (0.25, 88), (0.5, 68), (0.8, 42), (1.2, 18)]))


def analyze_clip(path: str, duration: float = 0.0,
                 max_frames: int = DEFAULT_SAMPLE_FRAMES) -> Optional[Dict[str, Any]]:
    """综合入口：返回 ``{"visual_quality", "shot_duration", 明细...}``。"""
    media = analyze_media(path, max_frames=max_frames)
    if media is None:
        return None
    out: Dict[str, Any] = dict(media)
    out["shot_duration"] = duration_reasonableness(duration)
    return out
