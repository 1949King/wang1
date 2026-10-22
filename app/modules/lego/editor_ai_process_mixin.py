"""
editor_ai_process_mixin.py
============================
EditorAiProcessMixin: 从 editor_module.py 抽出的 AI 处理方法。

承载: AI 拼接/FunClip/VideoFusion/AutoClip/LoRA 编辑/无损裁剪/插件转场渲染。
迁移的方法（共 7 个, 约 472 行）。
"""

import os, logging, subprocess, threading
import sys as _sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QMessageBox, QApplication
)

logger = logging.getLogger("AI短剧编辑器.editor")


def _clear_msgbox(title: str, message: str, parent=None):
    """延迟导入 show_clear_messagebox：抽出到 Mixin 后不能在顶层 `from .modules import`（会循环），
    与 editor_module._clear_msgbox 同策略，调用时局部导入。"""
    from .modules import show_clear_messagebox
    return show_clear_messagebox(title, message, parent)


class EditorAiProcessMixin:
    """AI 处理 Mixin: 承载 AI 拼接/FunClip/VideoFusion/AutoClip/LoRA/无损裁剪/插件转场。"""

    # 抽取自 editor_module.py L5407-5523
    def _run_ai_concat_after_picks(
        self,
        busy_box,
        *,
        title: str,
        hint: str,
        clip_path: str,
        segments,
        output_path: str,
        mute_audio: bool,
        history_label: str,
        done_title: str,
        extra_note: str = "",
    ):
        """场景/高光建议勾选后，再拼接入轨（不默认全写）。"""
        try:
            if busy_box is not None:
                busy_box.close()
        except Exception:
            logger.debug("关闭 busy 提示框失败（UI 容错）", exc_info=True)
        from app.modules.lego.suggest_checklist import pick_checked_indices

        labels = []
        for i, item in enumerate(segments, 1):
            s, e = float(item[0]), float(item[1])
            extra = str(item[2]) if len(item) > 2 and item[2] else ""
            label = f"{i}. {s:.1f}s – {e:.1f}s（{e - s:.1f}s）"
            if extra:
                label += f" · {extra}"
            labels.append(label)
        picked = pick_checked_indices(
            self,
            title=title,
            hint=hint,
            labels=labels,
            default_checked=True,
            ok_text="拼接并入轨",
        )
        if picked is None:
            QMessageBox.information(self, done_title, "已取消，未写入时间线")
            return
        chosen = [segments[i] for i in picked]
        if not chosen:
            QMessageBox.information(self, done_title, "未勾选任何片段，未写入时间线")
            return
        msg = QMessageBox(self)
        msg.setWindowTitle(done_title)
        msg.setText(f"正在拼接 {len(chosen)} 段…")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()

        def encode():
            try:
                list_path = output_path + ".txt"
                with open(list_path, "w", encoding="utf-8") as f:
                    for item in chosen:
                        s, e = float(item[0]), float(item[1])
                        f.write(f"file '{clip_path}'\ninpoint {s}\noutpoint {e}\n")
                cmd = [
                    self._get_ffmpeg(), "-y", "-f", "concat", "-safe", "0",
                    "-segment_time_metadata", "1",
                    "-i", list_path,
                    "-vf", "select=concatdec_select,setpts=PTS-STARTPTS",
                    "-c:v", "libx264", "-preset", "fast",
                ]
                if mute_audio:
                    cmd.append("-an")
                cmd.append(output_path)
                ffres = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0,
                )
                if ffres.returncode != 0 or not os.path.isfile(output_path):
                    err = (ffres.stderr or "")[-500:]
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(
                            self, done_title, f"导出失败，未写入时间线:\n{err or '输出文件不存在'}"
                        ),
                    ))
                    return
                cover_note = ""
                try:
                    from app.core.highlight_detect import grab_mid_jpeg
                    s0, e0 = float(chosen[0][0]), float(chosen[0][1])
                    cover = os.path.splitext(output_path)[0] + "_cover.jpg"
                    if grab_mid_jpeg(
                        clip_path, (s0 + e0) / 2.0, cover, ffmpeg=self._get_ffmpeg()
                    ):
                        cover_note = f"\n封面: {cover}"
                except Exception:
                    cover_note = ""
                note = f"\n\n{extra_note}" if extra_note else ""
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    self._add_clip_to_timeline(output_path),
                    self._record_ai_tool_history(
                        f"{history_label} → {os.path.basename(output_path)}（{len(chosen)} 段）"
                    ),
                    QMessageBox.information(
                        self,
                        done_title,
                        f"已按勾选拼接并加入时间线。\n输出: {output_path}{cover_note}{note}",
                    ),
                ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}"),
                ))

        threading.Thread(target=encode, daemon=True).start()

    # 抽取自 editor_module.py L5525-5582
    def _funclip_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_funclip.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("FunClip")
        msg.setText("正在使用场景检测自动分段...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                from app.core.highlight_detect import (
                    detect_scene_segments,
                    detect_silences_ffmpeg,
                    merge_silence_into_segments,
                )
                segs = detect_scene_segments(clip_path, min_len=2.0, max_scenes=10)
                sil = detect_silences_ffmpeg(clip_path, ffmpeg=self._get_ffmpeg())
                if sil:
                    segs = merge_silence_into_segments(segs, sil, min_len=2.0)
                if not segs:
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "FunClip", "未检测到有效场景（空结果）。请换有镜头切换的素材。")
                    ))
                    return
                QTimer.singleShot(0, lambda: self._run_ai_concat_after_picks(
                    msg,
                    title="FunClip 场景建议",
                    hint="勾选要保留的镜头，确认后才会拼接并入轨。未勾选则不改时间线。切点来自顺序解码+静音边界，非语义理解。",
                    clip_path=clip_path,
                    segments=segs,
                    output_path=output_path,
                    mute_audio=True,
                    history_label="FunClip 场景检测",
                    done_title="FunClip",
                    extra_note="⚠️ 该成片仅保留视频画面，不含原始音轨",
                ))
            except ImportError:
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "提示", "请安装cv2: pip install opencv-python")
                ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    # 抽取自 editor_module.py L5625-5681
    def _autoclip_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_highlight.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("AutoClip")
        msg.setText("正在分析高光片段...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                from app.core.highlight_detect import (
                    detect_motion_segments,
                    detect_silences_ffmpeg,
                    merge_silence_into_segments,
                )
                segs = detect_motion_segments(clip_path, top_n=8, window_sec=2.0)
                sil = detect_silences_ffmpeg(clip_path, ffmpeg=self._get_ffmpeg())
                if sil:
                    segs = merge_silence_into_segments(segs, sil, min_len=1.0)
                if not segs:
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", "未检测到有效高光片段（视频过短或无法解码）")
                    ))
                    return
                QTimer.singleShot(0, lambda: self._run_ai_concat_after_picks(
                    msg,
                    title="AutoClip 高光建议",
                    hint="按运动量排序后的候选镜头。勾选后才会拼接并入轨；这是启发式高光，不是语义理解。",
                    clip_path=clip_path,
                    segments=segs,
                    output_path=output_path,
                    mute_audio=False,
                    history_label="AutoClip 高光检测",
                    done_title="AutoClip",
                ))
            except ImportError:
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "提示", "请安装cv2: pip install opencv-python")
                ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    # 抽取自 editor_module.py L5683-5731
    def _lossless_trim_selected(self):
        """按选中片段入出点做关键帧对齐 trim，确认后才入轨。"""
        clip = getattr(self, "_current_clip", None)
        if not isinstance(clip, dict) and self._clips:
            clip = self._clips[0]
        if not isinstance(clip, dict):
            _clear_msgbox("操作提示", "请先选中或导入视频片段")
            return
        src = clip.get("path") or ""
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "无损裁切", "源文件不存在")
            return
        in_p = float(clip.get("in_point") or 0)
        dur = float(clip.get("duration") or 0)
        out_p = float(clip.get("out_point") or 0)
        if out_p <= in_p:
            out_p = in_p + dur
        if out_p <= in_p + 0.05:
            QMessageBox.warning(self, "无损裁切", "入出点无效")
            return
        reply = QMessageBox.question(
            self,
            "无损裁切",
            f"将按入出点 {in_p:.2f}s–{out_p:.2f}s 导出。\n"
            "优先关键帧对齐 copy；无法对齐时会重编码并标明。\n确认后才会加入时间线。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            QMessageBox.information(self, "无损裁切", "已取消，未写入时间线")
            return
        out_dir = "短剧AI剪辑输出"
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.basename(src).rsplit(".", 1)[0]
        dst = os.path.join(out_dir, f"{base}_trim_{in_p:.1f}-{out_p:.1f}.mp4")
        from app.core.lossless_trim import lossless_trim
        result = lossless_trim(
            src, in_p, out_p, dst,
            ffmpeg=self._get_ffmpeg(),
        )
        if not result.get("success"):
            QMessageBox.warning(
                self, "无损裁切", result.get("error") or "导出失败，未写入时间线"
            )
            return
        extra = "（已重编码）" if result.get("reencoded") else "（copy）"
        self._add_clip_to_timeline(dst)
        self._record_ai_tool_history(f"无损裁切{extra} → {os.path.basename(dst)}")
        QMessageBox.information(self, "无损裁切", f"已加入时间线{extra}\n{dst}")

    # 抽取自 editor_module.py L5733-5794
    def _videofusion_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        reply = QMessageBox.question(
            self,
            "Fusion 画质增强",
            "将用 FFmpeg 锐化/降噪滤镜生成新片段并加入时间线（不是神经网络超分）。\n确认后才会入轨。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_enhanced.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("VideoFusion")
        msg.setText("正在增强画质...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                filters = [
                    "unsharp=5:5:1.0:5:5:0.0",
                    "hqdn3d=4:3:6:4",
                    "format=yuv420p"
                ]
                filter_str = ",".join(filters)
                result = subprocess.run([
                    self._get_ffmpeg(), "-y", "-i", clip_path,
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0 and os.path.isfile(output_path):
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        self._add_clip_to_timeline(output_path),
                        self._record_ai_tool_history(f"Fusion 画质增强完成 → {os.path.basename(output_path)}"),
                        QMessageBox.information(self, "VideoFusion", f"画质增强完成，已添加到时间线！输出: {output_path}")
                    ))
                else:
                    err = result.stderr
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", f"增强失败（未写入时间线）:\n{err or '输出文件不存在'}")
                    ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    # 抽取自 editor_module.py L5796-5859
    def _lora_edit_process(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        reply = QMessageBox.question(
            self,
            "风格化（滤镜近似）",
            "将用 FFmpeg 调色滤镜生成新片段并加入时间线（不是 LoRA / 神经网络风格迁移）。\n确认后才会入轨。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        clip_path = self._clips[0]['path']
        output_dir = "短剧AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.basename(clip_path).rsplit('.', 1)[0]
        output_path = os.path.join(output_dir, f"{base_name}_stylized.mp4")
        msg = QMessageBox(self)
        msg.setWindowTitle("风格化（滤镜近似）")
        msg.setText("正在应用风格化效果（FFmpeg 调色滤镜近似，非 LoRA/神经网络风格迁移）...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        QApplication.processEvents()
        def process():
            try:
                filters = [
                    "eq=brightness=0.05:contrast=1.1:saturation=1.3",
                    "colorbalance=rs=0.1:gs=-0.05:bs=-0.1",
                    "hue=h=5",
                    "vignette=PI/4",
                    "unsharp=3:3:0.8",
                ]
                filter_str = ",".join(filters)
                result = subprocess.run([
                    self._get_ffmpeg(), "-y", "-i", clip_path,
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "medium",
                    "-crf", "20", "-c:a", "copy",
                    output_path
                ], capture_output=True, text=True, timeout=300,
                   creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0 and os.path.exists(output_path):
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        self._add_clip_to_timeline(output_path),
                        self._record_ai_tool_history(f"风格化完成 → {os.path.basename(output_path)}"),
                        QMessageBox.information(self, "完成", f"风格化完成，已添加到时间线！输出: {output_path}")
                    ))
                else:
                    err = (result.stderr or "")[-500:]
                    QTimer.singleShot(0, lambda: (
                        msg.close(),
                        QMessageBox.warning(self, "失败", f"处理失败: {err}")
                    ))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: (
                    msg.close(),
                    QMessageBox.warning(self, "失败", f"处理失败: {err}")
                ))
        t = threading.Thread(target=process, daemon=True)
        t.start()

    # 抽取自 editor_module.py L6790-6854
    def _try_render_plugin_transition(self, timeline_t: float, video_hits, pm):
        """
        片尾转场窗内：解出/入两帧，走 ITransitionPlugin / apply()。
        成功返回 BGR；否则 None（回退叠层 + dissolve 近似）。
        """
        candidates = list(video_hits or [])
        # 也检查即将结束、尚在转场窗内的片（下片可能尚未命中）
        for c in getattr(self, "_clips", None) or []:
            if str(c.get("type", "")).lower() == "audio":
                continue
            tr = self._clip_outgoing_transition(c)
            if not tr:
                continue
            st = float(c.get("start_time", 0) or 0)
            end = st + float(c.get("duration", 0) or 0)
            fade = float(tr.get("duration", 0.5) or 0.5)
            if end - fade <= timeline_t <= end + 0.02:
                if c not in candidates:
                    candidates.append(c)
        for clip in candidates:
            tr = self._clip_outgoing_transition(clip)
            if not tr:
                continue
            fade = float(tr.get("duration", 0.5) or 0.5)
            if fade <= 0.05:
                continue
            st = float(clip.get("start_time", 0) or 0)
            end = st + float(clip.get("duration", 0) or 0)
            if not (end - fade <= timeline_t <= end + 0.02):
                continue
            nxt = self._find_next_clip_same_track(clip)
            if not nxt:
                continue
            # 允许邻接或轻微重叠
            nst = float(nxt.get("start_time", 0) or 0)
            if nst > end + 0.15:
                continue
            progress = (timeline_t - (end - fade)) / fade
            progress = max(0.0, min(1.0, progress))
            plugin_id = tr.get("plugin_id") or tr.get("type") or tr.get("name")
            try:
                from app.core.transition_plugin_registry import (
                    apply_frames, resolve_plugin_id, easing_from_curve,
                )
            except Exception:
                from core.transition_plugin_registry import (
                    apply_frames, resolve_plugin_id, easing_from_curve,
                )
            pid = resolve_plugin_id(str(plugin_id or "")) or str(plugin_id or "")
            if not pid:
                continue
            a = self._decode_clip_bgr_at(clip, min(timeline_t, end - 1e-3), pm)
            b = self._decode_clip_bgr_at(nxt, max(timeline_t, nst), pm)
            if a is None or b is None:
                continue
            params = {
                "duration": fade,
                "easing": easing_from_curve(str(tr.get("curve") or "线性")),
                "direction": tr.get("direction") or "right",
            }
            mixed = apply_frames(pid, a, b, progress, params)
            if mixed is None:
                continue
            return mixed
        return None

    # ── 入轨治理闸门（刀3 / E2 · 2026-10-23）──────────────────────────
    # 为什么放在 mixin：`editor_module.py` 已顶到单文件规模守卫上限（9717+30），
    # 而那正是本方法要服务的宿主。闸门逻辑全部委托 `app/core/ingest_gate.py`
    # （纯函数、可单测），本方法只做「判定 → 组装拒绝响应」的薄壳，
    # 保证宿主侧只多一行调用、且判定语义只有一个来源。
    def _gate_before_ingest(self, clips, *, enforce: bool = True):
        """入轨前过治理闸门；返回**拒绝载荷**（通过则返回 None）。

        * `enforce=False` ⇒ 不判定，直接放行（既有调用方的零行为变化路径）；
        * 无分数素材**不判定、放行**——治理只判「测过的坏素材」，不判用户
          自己导入的文件（`_add_clip_to_timeline` 有 13 个调用方，其中包含
          用户手动导入，误拦代价极高）；
        * 任一 block ⇒ 整批拒绝（坏素材混进来就不许整段过）；
        * `review` 不拦，但会在成功消息里如实计数（不静默）。
        """
        if not enforce:
            return None
        try:
            from app.core.ingest_gate import decide_batch, rejection_payload
        except ImportError:  # 兼容 `core.*` 旧导入路径
            try:
                from core.ingest_gate import decide_batch, rejection_payload  # type: ignore
            except ImportError:
                return None  # 治理模块缺失 ⇒ 不拦（诚实降级，不让它炸入轨）
        try:
            verdict = decide_batch(clips)
        except Exception:
            logger.warning("入轨治理判定异常，按放行处理（不拦入轨）", exc_info=True)
            return None
        if verdict.get("verdict") == "block":
            return rejection_payload(verdict, stage="agent_replace_timeline_clips")
        return None

