# -*- coding: utf-8 -*-
"""字幕/贴纸烧录（从 editor_module 抽出）。"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

try:
    from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont, QFontMetrics
except Exception:  # pragma: no cover
    QPixmap = QColor = QPainter = QFont = QFontMetrics = None  # type: ignore

def burn_subtitles_if_any(editor, video_path: str) -> str:
    """若有字幕则按样式烧录到成片（优先 ASS+libass，回退 SRT）。"""
    import shutil
    try:
        sm = editor._ensure_subtitle_manager()
        subs = sm.list_subtitles() if sm else []
    except Exception:
        subs = []
    if not subs or not video_path or not os.path.exists(video_path):
        return video_path
    ffmpeg = None
    try:
        ffmpeg = editor._get_ffmpeg() if hasattr(editor, "_get_ffmpeg") else None
    except Exception:
        ffmpeg = None
    if not ffmpeg:
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            from app.modules.lego.video_processor import _find_ffmpeg_path
            ffmpeg = _find_ffmpeg_path()
        except Exception:
            ffmpeg = "ffmpeg"
    if not ffmpeg:
        return video_path
    base, ext = os.path.splitext(video_path)
    ass_path = base + "_burn.ass"
    srt_path = base + "_burn.srt"
    out_path = base + "_sub" + ext
    burned = False
    try:
        # 探测成片分辨率，使 ASS PlayRes 与画面一致
        play_res = (1920, 1080)
        try:
            import json as _json
            ffprobe = ffmpeg.replace("ffmpeg", "ffprobe").replace("FFmpeg", "ffprobe")
            if os.path.exists(ffprobe) or shutil.which("ffprobe"):
                probe_bin = ffprobe if os.path.exists(ffprobe) else "ffprobe"
                pr = subprocess.run(
                    [
                        probe_bin, "-v", "quiet", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "json", video_path,
                    ],
                    capture_output=True, text=True, timeout=30,
                )
                if pr.returncode == 0 and pr.stdout:
                    streams = (_json.loads(pr.stdout).get("streams") or [{}])[0]
                    pw, ph = int(streams.get("width") or 0), int(streams.get("height") or 0)
                    if pw > 0 and ph > 0:
                        play_res = (pw, ph)
        except Exception as _pe:
            logger.warning("探测分辨率失败，使用默认 PlayRes: %s", _pe)

        use_ass = False
        if hasattr(sm, "export_subtitles_ass"):
            use_ass = bool(sm.export_subtitles_ass(ass_path, play_res=play_res))
        sub_file = ass_path if use_ass else srt_path
        if not use_ass:
            sm.export_subtitles(srt_path, format="srt")
        if not os.path.exists(sub_file):
            return video_path

        esc = sub_file.replace("\\", "/").replace(":", "\\:")
        # ASS 用 ass=；SRT 用 subtitles=
        vf = f"ass='{esc}'" if use_ass else f"subtitles='{esc}'"
        cmd = [
            ffmpeg, "-y", "-i", video_path,
            "-vf", vf,
            "-c:a", "copy",
            out_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 and use_ass:
            # libass 不可用时回退 SRT
            logger.error(f"ASS 烧录失败，回退 SRT: {(r.stderr or '')[-400:]}")
            sm.export_subtitles(srt_path, format="srt")
            esc2 = srt_path.replace("\\", "/").replace(":", "\\:")
            cmd = [
                ffmpeg, "-y", "-i", video_path,
                "-vf", f"subtitles='{esc2}'",
                "-c:a", "copy",
                out_path,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and os.path.exists(out_path):
            burned = True
            try:
                os.replace(out_path, video_path)
            except Exception:
                return out_path
            return video_path
        if r.returncode != 0:
            logger.error(f"字幕烧录失败: {(r.stderr or '')[-500:]}")
    except Exception as e:
        logger.error(f'字幕烧录失败: {e}')
    finally:
        for p in (ass_path, srt_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
        if not burned:
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception as _e:
                logger.warning("操作异常（已忽略）: %s", _e)
    return video_path


def burn_stickers_if_any(editor, video_path: str) -> str:
    """导出后把贴纸烧进成片（emoji→临时 PNG + overlay）。"""
    stickers = getattr(editor, "_active_stickers", None) or []
    if not stickers or not video_path or not os.path.exists(video_path):
        return video_path
    ffmpeg = None
    try:
        ffmpeg = editor._get_ffmpeg() if hasattr(editor, "_get_ffmpeg") else None
    except Exception:
        ffmpeg = None
    if not ffmpeg:
        try:
            from app.core.ffmpeg_utils import find_ffmpeg
            ffmpeg = find_ffmpeg()
        except Exception:
            ffmpeg = None
    if not ffmpeg:
        import shutil as _sh
        ffmpeg = _sh.which("ffmpeg")
    if not ffmpeg:
        return video_path

    import tempfile
    temp_pngs = []
    try:
        # 探测分辨率
        bw, bh = 1920, 1080
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                bw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or bw
                bh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or bh
            cap.release()
        except Exception as e:
            logger.debug("cv2 分辨率探测失败: %s", e)

        inputs = ["-i", video_path]
        prep = []
        overlays = []
        for i, stk in enumerate(stickers):
            path = stk.get("path")
            size_pct = float(stk.get("size", 100) or 100)
            opacity = float(stk.get("opacity", 1.0) or 1.0)
            if opacity > 1.0:
                opacity = opacity / 100.0
            opacity = max(0.05, min(1.0, opacity))
            rot = float(stk.get("rotation", 0) or 0)
            x = float(stk.get("x", 50) or 50) / 100.0
            y = float(stk.get("y", 50) or 50) / 100.0

            if path and os.path.exists(path):
                img_path = path
            else:
                # 用预览同逻辑渲染 emoji 到 PNG（优先 Qt，回退 PIL）
                tw = max(64, int(bw * 0.18 * size_pct / 100.0))
                emoji = str(stk.get("emoji") or "★")
                img_path = tempfile.mktemp(suffix=f"_stk{i}.png")
                temp_pngs.append(img_path)
                rendered = False
                try:
                    pm = QPixmap(tw, tw)
                    pm.fill(QColor(0, 0, 0, 0))
                    p = QPainter(pm)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                    font = QFont("Segoe UI Emoji")
                    font.setPixelSize(max(20, int(tw * 0.75)))
                    p.setFont(font)
                    p.setPen(QColor(255, 255, 255))
                    fm = QFontMetrics(font)
                    p.drawText(
                        (tw - fm.horizontalAdvance(emoji)) // 2,
                        (tw + fm.ascent() - fm.descent()) // 2,
                        emoji,
                    )
                    p.end()
                    rendered = pm.save(img_path, "PNG")
                except Exception:
                    rendered = False
                if not rendered:
                    try:
                        from PIL import Image, ImageDraw, ImageFont
                        im = Image.new("RGBA", (tw, tw), (0, 0, 0, 0))
                        draw = ImageDraw.Draw(im)
                        try:
                            font = ImageFont.truetype("seguiemj.ttf", max(20, int(tw * 0.7)))
                        except Exception:
                            try:
                                font = ImageFont.truetype("C:/Windows/Fonts/seguiemj.ttf", max(20, int(tw * 0.7)))
                            except Exception:
                                font = ImageFont.load_default()
                        draw.text((tw * 0.1, tw * 0.1), emoji, font=font, fill=(255, 255, 255, 255))
                        im.save(img_path, "PNG")
                    except Exception as e:
                        logger.warning("贴纸 PNG 生成失败: %s", e)
                        continue
            inputs.extend(["-i", img_path])
            # scale + rotate + opacity（兼容 FFmpeg 8 rotate 语法）
            scale_w = max(16, int(bw * 0.18 * size_pct / 100.0))
            chain = f"[{i+1}:v]format=rgba,scale={scale_w}:-1"
            if abs(rot) > 0.1:
                chain += f",rotate={rot}*PI/180:fillcolor=0x00000000"
            if opacity < 0.999:
                chain += f",colorchannelmixer=aa={opacity:.3f}"
            chain += f"[st{i}]"
            prep.append(chain)
            dist_x = f"(main_w-overlay_w)*{x:.4f}"
            dist_y = f"(main_h-overlay_h)*{y:.4f}"
            # 入出点：此前烧录时全程可见，与预览的 start_time/end_time 不一致
            st_t = max(0.0, float(stk.get("start_time", 0) or 0))
            et_t = float(stk.get("end_time", 1e9) or 1e9)
            enable_expr = f":enable='between(t,{st_t:.3f},{et_t:.3f})'" if et_t < 1e8 or st_t > 0.001 else ""
            if i == 0:
                overlays.append(f"[0:v][st0]overlay={dist_x}:{dist_y}:format=auto{enable_expr}[out0]")
            else:
                overlays.append(
                    f"[out{i-1}][st{i}]overlay={dist_x}:{dist_y}:format=auto{enable_expr}[out{i}]"
                )

        if not prep:
            return video_path
        filter_str = ";".join(prep + overlays)
        out_path = video_path + ".stk.tmp.mp4"
        last = len(prep) - 1
        cmd = [
            ffmpeg, "-y", *inputs,
            "-filter_complex", filter_str,
            "-map", f"[out{last}]",
            "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-shortest",
            out_path,
        ]
        r = subprocess.run(
            cmd, capture_output=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            try:
                os.replace(out_path, video_path)
            except Exception:
                return out_path
            return video_path
        err = (r.stderr or b"").decode("utf-8", "ignore")[-400:]
        logger.error(f'贴纸烧录失败: {err}')
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception as e:
            logger.debug("贴纸烧录失败后清理临时文件异常: %s", e)
        return video_path
    except Exception as e:
        logger.error(f'贴纸烧录失败: {e}')
        return video_path
    finally:
        for p in temp_pngs:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception as e:
                logger.debug("贴纸临时文件清理异常: %s", e)

