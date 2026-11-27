"""
视频时序稳定器（后滤波）
========================
对逐帧超分后的帧序列做时序一致性校正，抑制帧间亮度/色度闪烁。

原理：相邻帧 Farneback 光流 → 前帧 warp 到当前帧 → 运动掩码区分
低运动区（小 alpha 混合平滑）与高运动区（保留原细节防鬼影）→
亮度/色度 EMA 钳制校正。

诚实标注：这是「时序稳定后滤波」，非时序超分模型。
光流参数组复用 ai_interpolation.py:259（Farneback 0.5/3/15/3/5/1.2/0）。

失败一律返回 False，不阻断上层后处理管线。
"""

import logging
import os
from typing import Callable, Optional

logger = logging.getLogger("AI短剧编辑器.video_temporal_stabilize")


def _imread_unicode(path: str):
    """Unicode 安全 imread（绕过 OpenCV Windows 非 ASCII 路径限制）。"""
    import cv2
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _imwrite_unicode(path: str, img) -> bool:
    """Unicode 安全 imwrite（绕过 OpenCV Windows 非 ASCII 路径限制）。"""
    import cv2
    try:
        ok, buf = cv2.imencode(".png", img)
        if ok:
            buf.tofile(path)
            return True
        return False
    except Exception:
        return False


def _safe_progress(callback: Optional[Callable[[int, str], None]], pct: int, msg: str) -> None:
    """安全进度回调：异常不阻断主流程。"""
    if callback is None:
        return
    try:
        callback(int(pct), msg)
    except Exception:
        logger.debug("时序稳定进度回调异常", exc_info=True)


def stabilize_frame_sequence(
    frame_dir: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    strength: float = 0.2,
) -> bool:
    """对帧序列做时序稳定后滤波，原地覆写帧文件。

    Args:
        frame_dir: 含 f_000001.png ... 的帧目录
        progress_callback: 可选 (pct 0-100, message)
        strength: 混合强度 0..1，0=几乎不变，默认 0.2 保守

    Returns:
        True=成功（含单帧无需处理），False=目录无效/空/异常
    """
    if not frame_dir or not os.path.isdir(frame_dir):
        return False

    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.debug("[TemporalStabilize] cv2/numpy 不可用，跳过")
        return False

    try:
        frames_files = sorted(
            f for f in os.listdir(frame_dir) if f.startswith("f_") and f.endswith(".png")
        )
        if not frames_files:
            return False
        if len(frames_files) == 1:
            return True  # 单帧无需稳定

        total = len(frames_files)
        # 读取首帧作为 EMA 参考
        prev = _imread_unicode(os.path.join(frame_dir, frames_files[0]))
        if prev is None:
            return False

        # 亮度 EMA 参考（LAB 空间 L 通道均值）
        prev_lab = cv2.cvtColor(prev, cv2.COLOR_BGR2LAB)
        ema_l = float(np.mean(prev_lab[:, :, 0]))

        for idx in range(1, total):
            _safe_progress(progress_callback, int(idx * 100 / total), f"时序稳定 {idx}/{total - 1}")

            cur_path = os.path.join(frame_dir, frames_files[idx])
            cur = _imread_unicode(cur_path)
            if cur is None:
                continue

            h, w = cur.shape[:2]

            # ─── 场景切变检测：全局帧差过大 ⇒ 跳过混合（防鬼影）───
            global_diff = float(np.mean(cv2.absdiff(prev, cur)))
            if global_diff > 50.0:
                # 场景切变，保留原帧不做任何混合
                prev = cur
                prev_lab = cv2.cvtColor(cur, cv2.COLOR_BGR2LAB)
                ema_l = 0.7 * ema_l + 0.3 * float(np.mean(prev_lab[:, :, 0]))
                continue

            # ─── 光流（参数组复用 ai_interpolation.py:259）───
            g1 = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
            g2 = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY)
            flow = cv2.calcOpticalFlowFarneback(g1, g2, None, 0.5, 3, 15, 3, 5, 1.2, 0)

            # 前帧 warp 到当前帧坐标
            grid_x, grid_y = np.meshgrid(
                np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32)
            )
            fx, fy = flow[..., 0], flow[..., 1]
            warp_prev = cv2.remap(
                prev, (grid_x + fx).astype(np.float32),
                (grid_y + fy).astype(np.float32),
                cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
            )

            # ─── 运动掩码：光流幅度大的区域保留原细节（防鬼影）───
            mag = np.sqrt(fx * fx + fy * fy)
            # 阈值：幅度 > 2px 视为高运动，不混合
            motion_mask = (mag > 2.0).astype(np.float32)
            # 低运动区混合权重 = strength * (1 - motion_mask)
            alpha_map = strength * (1.0 - motion_mask)
            alpha_3ch = alpha_map[:, :, np.newaxis]

            # 混合：低运动区用 warp_prev 平滑，高运动区保留 cur
            blended = (cur.astype(np.float32) * (1.0 - alpha_3ch)
                       + warp_prev.astype(np.float32) * alpha_3ch)
            stabilized = np.clip(blended, 0, 255).astype(np.uint8)

            # ─── 亮度 EMA 钳制校正（防全局亮度漂移，强度随 strength 缩放）───
            cur_lab = cv2.cvtColor(stabilized, cv2.COLOR_BGR2LAB)
            cur_l = float(np.mean(cur_lab[:, :, 0]))
            # EMA 更新
            ema_l = 0.7 * ema_l + 0.3 * cur_l
            # 钳制：当前帧亮度偏离 EMA 超过 8 时拉回（strength=0 时不校正）
            drift = cur_l - ema_l
            if abs(drift) > 8.0 and strength > 0.01:
                correction = -drift * 0.5 * strength
                lab_f = cur_lab.astype(np.float32)
                lab_f[:, :, 0] = np.clip(lab_f[:, :, 0] + correction, 0, 255)
                stabilized = cv2.cvtColor(lab_f.astype(np.uint8), cv2.COLOR_LAB2BGR)

            # 原地覆写
            _imwrite_unicode(cur_path, stabilized)
            prev = stabilized
            prev_lab = cv2.cvtColor(stabilized, cv2.COLOR_BGR2LAB)

        _safe_progress(progress_callback, 100, "时序稳定完成")
        return True

    except Exception as exc:
        logger.warning(f"[TemporalStabilize] 时序稳定异常，跳过: {exc}")
        return False
