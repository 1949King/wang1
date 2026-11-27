"""
生成后处理管线
==============
把语义画质档位的 ``upscale`` / ``face_restore`` / ``frame_interpolate`` 标志，
落到已生成图像 / 视频的本地后处理上。

原则（诚实降级）：
  - 后处理失败一律返回原产物，绝不因此让生成本身失败
  - 全部使用本地能力（OpenCV / FFmpeg / 现有 super_resolution / face_restore）
  - 无可用后端时自动跳过并记日志
"""

import logging
import os
import subprocess
import tempfile
from typing import Any, Callable, Dict, Optional

from app.core.ffmpeg_utils import mux_source_audio, probe_has_audio
from app.core.video_temporal_stabilize import stabilize_frame_sequence

logger = logging.getLogger("AI短剧编辑器.generation_postprocess")


def _report_progress(callback: Optional[Callable[[int, str], None]], pct: int, message: str) -> None:
    """安全回调进度：回调异常不阻断后处理主流程。"""
    if callback is None:
        return
    try:
        callback(int(pct), message)
    except Exception:
        logger.debug("后处理进度回调异常", exc_info=True)


def _scaled_progress(callback: Optional[Callable[[int, str], None]], start: int, end: int):
    """把子阶段 0-100 进度映射到 [start, end] 区间；callback 为空返回 None。"""
    if callback is None:
        return None

    def _wrap(pct: int, message: str = "") -> None:
        mapped = int(start + (end - start) * max(0, min(100, pct)) / 100.0)
        _report_progress(callback, mapped, message)

    return _wrap


def _decode_data_url(data_url: str):
    """data URL → BGR numpy 数组；失败返回 None。"""
    if not data_url or "," not in data_url:
        return None
    try:
        import base64

        import cv2
        import numpy as np

        header, b64 = data_url.split(",", 1)
        if "base64" not in header.lower():
            return None
        raw = base64.b64decode(b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.debug(f"[PostProcess] 图像解码失败: {exc}")
        return None


def _encode_data_url(image) -> str:
    """BGR numpy 数组 → PNG data URL。"""
    try:
        import base64

        import cv2

        ok, buf = cv2.imencode(".png", image)
        if not ok:
            return ""
        return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception as exc:
        logger.debug(f"[PostProcess] 图像编码失败: {exc}")
        return ""


def apply_image_postprocess(image_data_url: str, flags: Dict[str, Any]) -> str:
    """对生成的图像执行人脸修复 + 超分，返回新的 data URL（失败返回原输入）。

    Args:
        image_data_url: 原始生成的 data URL
        flags: 画质参数字典（含 face_restore / upscale 布尔字段）
    """
    need_face = bool(flags.get("face_restore"))
    need_sr = bool(flags.get("upscale"))
    if not (need_face or need_sr):
        return image_data_url

    image = _decode_data_url(image_data_url)
    if image is None:
        return image_data_url

    try:
        # 先人脸修复（在原始分辨率下），再整体超分
        if need_face:
            try:
                from app.core.neural.face_restore import FaceRestoreEngine

                image = FaceRestoreEngine().enhance(image)
            except Exception as exc:
                logger.debug(f"[PostProcess] 人脸修复失败，降级跳过: {exc}")

        if need_sr:
            try:
                from app.core.neural.super_resolution import SuperResolutionEngine

                engine = SuperResolutionEngine()
                if engine.load(scale=2):
                    upscaled = engine.upscale(image)
                    if upscaled is not None:
                        image = upscaled
            except Exception as exc:
                logger.debug(f"[PostProcess] 超分失败，降级跳过: {exc}")

        encoded = _encode_data_url(image)
        return encoded or image_data_url
    except Exception as exc:
        logger.warning(f"[PostProcess] 图像后处理异常，返回原图: {exc}")
        return image_data_url


def _read_video_fps(video_path: str) -> float:
    """读取视频 fps，失败返回 0。"""
    try:
        from app.core.ffmpeg_utils import get_ffprobe

        ffprobe = get_ffprobe()
        cmd = [
            ffprobe, "-v", "quiet", "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", video_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        raw = (r.stdout or "").strip()
        if not raw:
            return 0.0
        # "30000/1001" 或 "30"
        if "/" in raw:
            num, den = raw.split("/", 1)
            den = float(den)
            return float(num) / den if den else 0.0
        return float(raw)
    except Exception as exc:
        logger.debug(f"[PostProcess] 读取 fps 失败: {exc}")
        return 0.0


def _extract_frames(ffmpeg: str, video_path: str, out_dir: str) -> int:
    """用 ffmpeg 抽帧到 out_dir，返回帧数。"""
    pattern = os.path.join(out_dir, "f_%06d.png")
    cmd = [ffmpeg, "-y", "-i", video_path, "-vsync", "0", "-start_number", "1", pattern]
    subprocess.run(cmd, capture_output=True, check=False, timeout=600)
    frames = sorted(
        f for f in os.listdir(out_dir) if f.startswith("f_") and f.endswith(".png")
    )
    return len(frames)


def _encode_frames(ffmpeg: str, frame_dir: str, out_path: str, fps: float) -> bool:
    """把 frame_dir 内的帧序列编码成视频。"""
    pattern = os.path.join(frame_dir, "f_%06d.png")
    cmd = [
        ffmpeg, "-y", "-framerate", str(fps), "-start_number", "1", "-i", pattern,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, check=False, timeout=600)
    return r.returncode == 0 and os.path.isfile(out_path)


def _interpolate_frames(frame_dir: str, progress_callback: Optional[Callable[[int, str], None]] = None) -> None:
    """线性补帧：相邻帧差较小时插入中间帧，使帧数翻倍。"""
    try:
        import cv2
        import numpy as np

        frames = sorted(
            f for f in os.listdir(frame_dir) if f.startswith("f_") and f.endswith(".png")
        )
        if len(frames) < 2:
            return

        total = len(frames)
        # 逐帧输出原帧，并在帧差较小时插入混合中间帧
        out_idx = 0
        for i in range(len(frames)):
            img_a = cv2.imread(os.path.join(frame_dir, frames[i]))
            if img_a is None:
                continue
            _report_progress(progress_callback, int(i * 100 / total), f"补帧 {i + 1}/{total}")
            cv2.imwrite(os.path.join(frame_dir, f"out_{out_idx:06d}.png"), img_a)
            out_idx += 1

            if i < len(frames) - 1:
                img_b = cv2.imread(os.path.join(frame_dir, frames[i + 1]))
                if img_b is not None:
                    diff = float(np.mean(cv2.absdiff(img_a, img_b)))
                    if diff < 40.0:
                        mid = cv2.addWeighted(img_a, 0.5, img_b, 0.5, 0.0)
                        cv2.imwrite(os.path.join(frame_dir, f"out_{out_idx:06d}.png"), mid)
                        out_idx += 1

        # 删除原始帧，将 out_* 重命名为 f_*
        for f in frames:
            try:
                os.remove(os.path.join(frame_dir, f))
            except OSError:
                logger.debug("删除原始帧失败: %s", f)
        out_frames = sorted(
            f for f in os.listdir(frame_dir) if f.startswith("out_") and f.endswith(".png")
        )
        for i, f in enumerate(out_frames, 1):
            dst = os.path.join(frame_dir, f"f_{i:06d}.png")
            os.replace(os.path.join(frame_dir, f), dst)
    except Exception as exc:
        logger.debug(f"[PostProcess] 补帧失败: {exc}")


def _upscale_frames(frame_dir: str, progress_callback: Optional[Callable[[int, str], None]] = None) -> bool:
    """对帧序列逐帧超分（2x），失败返回 False。"""
    try:
        import cv2

        from app.core.neural.super_resolution import SuperResolutionEngine

        engine = SuperResolutionEngine()
        # T2（2026-11-20）：优先 RealESRGAN（权重须用户自取，绝不自动下载）；
        # 缺失时 load 返 False ⇒ 保留原帧（诚实降级，上层保留原片）。
        if not engine.load(scale=2, use_realesrgan=True):
            return False
        frames = sorted(
            f for f in os.listdir(frame_dir) if f.startswith("f_") and f.endswith(".png")
        )
        total = len(frames)
        for idx, f in enumerate(frames, 1):
            path = os.path.join(frame_dir, f)
            img = cv2.imread(path)
            if img is None:
                continue
            up = engine.upscale(img)
            if up is not None:
                # RealESRGAN 固定 4x 输出 ⇒ resize 0.5 得**净 2x**（上游 esrgan trick）；
                # ESPCN/bicubic 已是 2x，不再缩。
                if getattr(engine, "_model_name", "") == "realesrgan":
                    h, w = img.shape[:2]
                    up = cv2.resize(up, (w * 2, h * 2), interpolation=cv2.INTER_AREA)
                cv2.imwrite(path, up)
            _report_progress(progress_callback, int(idx * 100 / total), f"超分 {idx}/{total}")
        return True
    except Exception as exc:
        logger.debug(f"[PostProcess] 视频超分失败: {exc}")
        return False


def apply_video_postprocess(
    video_path: str,
    flags: Dict[str, Any],
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> str:
    """对生成的视频执行补帧 + 超分，返回新的视频路径（失败返回原路径）。

    Args:
        video_path: 原始生成的本地视频路径
        flags: 画质参数字典（含 frame_interpolate / upscale 布尔字段）
        progress_callback: 可选进度回调 (pct 0-100, message)，逐阶段回传
    """
    need_fi = bool(flags.get("frame_interpolate"))
    need_sr = bool(flags.get("upscale"))
    if not (need_fi or need_sr) or not os.path.isfile(video_path):
        return video_path

    try:
        from app.core.ffmpeg_utils import get_ffmpeg

        _report_progress(progress_callback, 3, "准备视频后处理...")

        ffmpeg = get_ffmpeg()
        if not ffmpeg or not os.path.isfile(ffmpeg):
            logger.debug("[PostProcess] FFmpeg 不可用，跳过视频后处理")
            return video_path

        fps = _read_video_fps(video_path)
        if fps <= 0:
            fps = 24.0

        work_dir = tempfile.mkdtemp(prefix="shiguang_post_")
        frame_dir = os.path.join(work_dir, "frames")
        os.makedirs(frame_dir, exist_ok=True)

        _report_progress(progress_callback, 8, "抽帧中...")
        frame_count = _extract_frames(ffmpeg, video_path, frame_dir)
        if frame_count <= 0:
            return video_path
        _report_progress(progress_callback, 15, f"已抽帧 {frame_count} 张")

        new_fps = fps
        # 先补帧（帧数翻倍 → fps 翻倍）
        if need_fi:
            _report_progress(progress_callback, 20, "补帧中...")
            _interpolate_frames(
                frame_dir,
                progress_callback=_scaled_progress(progress_callback, 20, 45),
            )
            new_fps = fps * 2.0
            _report_progress(progress_callback, 45, "补帧完成")

        # 再超分（分辨率翻倍）
        if need_sr:
            _report_progress(progress_callback, 50, "超分中...")
            _upscale_frames(
                frame_dir,
                progress_callback=_scaled_progress(progress_callback, 50, 88),
            )
            _report_progress(progress_callback, 88, "超分完成")

        # 时序稳定后滤波（抑制逐帧超分闪烁，失败仅 warning 不阻断）
        if need_sr:
            stabilize_frame_sequence(
                frame_dir,
                progress_callback=_scaled_progress(progress_callback, 88, 90),
            )

        _report_progress(progress_callback, 90, "视频编码中...")
        out_path = os.path.join(
            os.path.dirname(video_path),
            f"{os.path.splitext(os.path.basename(video_path))[0]}_post.mp4",
        )
        if _encode_frames(ffmpeg, frame_dir, out_path, new_fps):
            # 补回源音轨（源无音轨/mux 失败 ⇒ 保留无声产物＝旧行为）
            if probe_has_audio(video_path):
                mux_path = os.path.join(
                    os.path.dirname(video_path),
                    f"{os.path.splitext(os.path.basename(video_path))[0]}_post_mux.mp4",
                )
                if mux_source_audio(out_path, video_path, mux_path):
                    logger.info(f"[PostProcess] 视频后处理完成(含音轨): {mux_path}")
                    _report_progress(progress_callback, 100, "视频后处理完成")
                    return mux_path
            logger.info(f"[PostProcess] 视频后处理完成: {out_path}")
            _report_progress(progress_callback, 100, "视频后处理完成")
            return out_path

        return video_path
    except Exception as exc:
        logger.warning(f"[PostProcess] 视频后处理异常，返回原视频: {exc}")
        return video_path