"""
editor_export_panel.py
======================
EditorExportPanelMixin：从 editor_module.py 抽出的视频导出相关方法（Mixin 模式）。

设计目标（遵循 .trae/rules/2.md §三 架构分层）：
- **最小侵入**：方法体完全照搬，self 访问不变，符合 §二.3 不破坏原有功能
- **零回归风险**：方法签名/实现不变，只是文件位置改变
- **单一职责**：本 Mixin 只承载视频导出相关方法，被 EditorModule 继承
- **不独立实例化**：Mixin 模式，必须混入宿主类使用

迁移的方法（共 8 个）：
1. _has_timeline_edits：判断是否存在需走剪辑拼接/多轨导出的真实编辑
2. _is_export_audio_clip：判断片段是否为独立音频（thin wrapper → editor_export）
3. _collect_export_audio_clips：收集独立音频轨（thin wrapper → editor_export）
4. _collect_export_overlay_clips：收集叠层视频轨（thin wrapper → editor_export）
5. _prebake_overlay_clips_for_export：叠层片段预烘焙（thin wrapper → editor_export）
6. _finalize_multitrack_export：多轨收尾混音（thin wrapper → editor_export）
7. _build_edited_video：依据 store 快照裁剪/拼接主轨成片（thin wrapper → editor_export）
8. _export_video：主导出流程（参数收集 → 时间线拼接 → 统一内核导出 → 字幕/贴纸烧录）

使用方式：
    class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin):
        ...

迁移后 EditorModule 实例通过 self 访问这些方法，MRO 解析到本 Mixin。
所有 self.xxx 属性访问由 EditorModule.__init__ 提供，不会断裂。

依赖说明：
- _burn_subtitles_if_any / _burn_stickers_if_any 仍保留在 EditorModule 中
  （它们有自己的依赖链，且只被 _export_video 调用，通过 self 访问即可）
- export_project / import_project / _save_project / _open_project 是工程文件 I/O，不迁移
- _on_export_script_clicked 是导出 AI 剪辑脚本（JSON 文本），不属于视频导出，不迁移
- show_clear_messagebox 显式 import 补全依赖（原 editor_module.py 缺此 import，属潜在 bug）
"""

import os
import re
import time
import shutil
import logging
import tempfile

from PyQt6.QtWidgets import QMessageBox, QComboBox

from .core import EventType

logger = logging.getLogger("AI短剧编辑器.editor")

# 注意：show_clear_messagebox 不在顶部 import，因为 .modules 模块会反向导入
# .editor_module，而 .editor_module 又导入本 Mixin，形成循环导入。
# 改为在 _export_video 方法内延迟导入（仅时间线为空时才执行），规避循环依赖。


class EditorExportPanelMixin:
    """视频导出相关方法 Mixin。

    本 Mixin 从 editor_module.py 抽出，承载视频导出相关方法。被 EditorModule
    继承后，通过 self 访问 EditorModule 的所有属性和其他方法。

    设计原则：
    - 方法体与原 editor_module.py 完全一致，零改动
    - 不引入新依赖，不修改方法签名
    - 异常处理保持原有 try/except 结构
    """

    # ────────────── 时间线编辑判断 ──────────────

    def _has_timeline_edits(self) -> bool:
        """判断是否存在需走剪辑拼接/多轨导出的真实编辑。"""
        # 刀7（2026-10-19）：导出消费出口统一改读真相源 store 快照
        # （锁内浅拷 list、元素仍是 live dict 引用，与旧直读字段级等价）
        clips = self._timeline_store.snapshot()
        if not clips:
            return False
        if len(clips) > 1:
            return True
        for clip in clips:
            if float(clip.get("start_time", 0) or 0) > 0.01:
                return True
            if abs(float(clip.get("volume", 1.0) or 1.0) - 1.0) > 0.01:
                return True
            if abs(float(clip.get("speed", 1.0) or 1.0) - 1.0) > 0.01:
                return True
            if abs(float(clip.get("opacity", 1.0) or 1.0) - 1.0) > 0.01:
                return True
            if abs(float(clip.get("scale", 1.0) or 1.0) - 1.0) > 0.01:
                return True
            if clip.get("pip_x") is not None or clip.get("pip_y") is not None or clip.get("pip_scale") is not None:
                return True
            if isinstance(clip.get("transform"), dict):
                return True
            pos = clip.get("position")
            if isinstance(pos, dict) and (abs(float(pos.get("x", 0) or 0)) > 1 or abs(float(pos.get("y", 0) or 0)) > 1):
                return True
            if clip.get("filter") or clip.get("transition") or clip.get("transitions"):
                return True
            eff = clip.get("effects")
            if isinstance(eff, dict) and any(
                eff.get(k) for k in ("filter", "color_params", "fade_in", "fade_out", "opacity", "scale")
            ):
                return True
            if str(clip.get("type", "")).lower() == "audio":
                return True
            if clip.get("keyframes"):
                return True
            ti = int(clip.get("track", 0) or 0)
            tw = getattr(self, "_timeline_widget", None)
            if tw is not None:
                tracks = getattr(tw, "_tracks", []) or []
                if 0 <= ti < len(tracks) and tracks[ti].get("type") in ("audio", "subtitle"):
                    return True
        clip = clips[0]
        src = clip.get("path")
        dur = self._probe_video_duration(src) if src else 0.0
        in_p = float(clip.get("in_point", 0) or 0)
        out_p = float(clip.get("out_point", dur) or dur)
        return in_p > 0.01 or (dur > 0 and abs(out_p - dur) > 0.01)

    # ────────────── 导出辅助 thin wrapper（委托给 editor_export 模块） ──────────────

    def _is_export_audio_clip(self, c) -> bool:
        from app.modules.lego.editor_export import is_export_audio_clip
        return is_export_audio_clip(self, c)

    def _collect_export_audio_clips(self) -> list:
        from app.modules.lego.editor_export import collect_export_audio_clips
        return collect_export_audio_clips(self)

    def _collect_export_overlay_clips(self, base_track: int) -> list:
        from app.modules.lego.editor_export import collect_export_overlay_clips
        return collect_export_overlay_clips(self, base_track)

    def _prebake_overlay_clips_for_export(self, overlays: list, frame_w: int, frame_h: int, ffmpeg_path: str) -> list:
        from app.modules.lego.editor_export import prebake_overlay_clips_for_export
        return prebake_overlay_clips_for_export(overlays, frame_w, frame_h, ffmpeg_path)

    def _finalize_multitrack_export(self, video_path: str, ffmpeg_path: str = "ffmpeg") -> str:
        """主线成片后：叠上层视频轨 → 混入独立音频轨（实现见 editor_export）。"""
        from app.modules.lego.editor_export import finalize_multitrack_export
        return finalize_multitrack_export(self, video_path, ffmpeg_path)

    def _build_edited_video(self, output_path: str) -> bool:
        """依据 store 快照裁剪/烘焙/拼接主轨成片（实现见 editor_export）。"""
        from app.modules.lego.editor_export import build_edited_video
        return build_edited_video(self, output_path)

    # ────────────── 时间线互操作导出（OTIO / EDL / FCPXML）──────────────

    def _export_timeline_document(
        self, save_path: str, resolution: str = "", fps: str = ""
    ) -> bool:
        """把当前时间线导出为 OTIO / EDL / FCPXML（**不渲染视频**）。

        * 未安装 ``opentimelineio`` 时明确失败，绝不产出空/假文件；
        * 真正的 OTIO 读写发生在独立子进程（Qt 进程 import 它会在 PyQt6 之后段错误）；
        * EDL(CMX3600) 天生只支持单条视频轨，多轨时会自动取主力视频轨（并告知）。
        """
        from app.core.interchange import otio_adapter
        from app.core.interchange.editor_timeline_bridge import adapter_for_path

        if not otio_adapter.is_available():
            QMessageBox.warning(
                self, "导出失败",
                "未安装 opentimelineio，无法导出 OTIO / EDL / FCPXML。\n"
                "请执行：pip install opentimelineio\n"
                "（EDL / FCPXML 另需：pip install otio-cmx3600-adapter otio-fcp-adapter）",
            )
            return False

        width, height = 1920, 1080
        m = re.match(r"\s*(\d+)\s*[xX*]\s*(\d+)", str(resolution or ""))
        if m:
            width, height = int(m.group(1)), int(m.group(2))
        try:
            fps_val = float(re.sub(r"[^\d.]", "", str(fps or "")) or 30.0)
        except (TypeError, ValueError):
            fps_val = 30.0
        if fps_val <= 0:
            fps_val = 30.0

        if not self._timeline_store.snapshot():
            QMessageBox.warning(self, "导出失败", "时间线为空，没有可导出的片段")
            return False

        project_name = os.path.splitext(os.path.basename(save_path))[0]
        try:
            self._notify_edit("导出时间线（OTIO / EDL / FCPXML）…")
            # 刀3（2026-10-18）：消费端改读真相源 canonical 视图（store 锁内快照+桥接构建）
            timeline = self._timeline_store.to_timeline(
                name=project_name or "拾光剪影时间线",
                fps=fps_val,
                width=width,
                height=height,
            )
            otio_adapter.export_otio(timeline, save_path, adapter=adapter_for_path(save_path))
        except Exception as e:
            logger.error("时间线导出失败: %s", e)
            QMessageBox.warning(self, "导出失败", f"时间线导出失败：\n{e}")
            return False

        fmt = os.path.splitext(save_path)[1].lstrip(".").upper() or "OTIO"
        video_tracks = sum(
            1 for t in timeline.tracks if getattr(t, "type", None) and t.type.value != "audio"
        )
        extra = (
            "\n提示：EDL 仅支持单条视频轨，已取片段最多的主力视频轨；"
            "需保留全部轨道请改用 OTIO / FCPXML。" if video_tracks > 1 and fmt == "EDL" else ""
        )
        self._notify_edit("时间线导出完成")
        QMessageBox.information(
            self, "导出成功",
            f"时间线已导出（{fmt}）：\n{save_path}\n\n"
            f"片段：{sum(len(t.clips) for t in timeline.tracks)} 个｜"
            f"轨道：{len(timeline.tracks)} 条\n"
            f"可导入 Premiere / DaVinci Resolve / Final Cut 等专业剪辑软件。{extra}",
        )
        return True

    # ────────────── 时间线互操作导入（OTIO / EDL / FCPXML）──────────────

    def _import_timeline_document(self) -> bool:
        """导入 OTIO / EDL / FCPXML 为时间线片段（**追加模式**，整包可撤销）。

        * OTIO 读写发生在独立子进程（Qt 进程 import 它会在 PyQt6 之后段错误）；
        * 未安装 ``opentimelineio`` 时明确失败，绝不产假数据；
        * 当前时间线非空时经确认**追加**在既有片段之后（不覆盖用户成果）；
        * 轨道落位：音频片段→音频轨、其余→视频轨（``timeline_widget.add_clip``
          强制对齐 track/type，多轨文档合并到主轨）；
        * 素材路径按文档原样；缺失文件如实提示（片段仍入轨，需重新链接素材）。
        """
        from PyQt6.QtWidgets import QFileDialog

        from app.core.interchange import otio_adapter
        from app.core.interchange.editor_timeline_bridge import (
            import_timeline_to_clips,
            timeline_export_filters,
        )

        if not otio_adapter.is_available():
            QMessageBox.warning(
                self, "导入失败",
                "未安装 opentimelineio，无法导入 OTIO / EDL / FCPXML。\n"
                "请执行：pip install opentimelineio\n"
                "（EDL / FCPXML 另需：pip install otio-cmx3600-adapter otio-fcp-adapter）",
            )
            return False

        open_path, _ = QFileDialog.getOpenFileName(
            self, "导入时间线（OTIO / EDL / FCPXML）",
            getattr(self, "_last_timeline_doc_dir", ""),
            timeline_export_filters())
        if not open_path:
            return False
        self._last_timeline_doc_dir = os.path.dirname(open_path)

        try:
            self._notify_edit("导入时间线…")
            imported = import_timeline_to_clips(open_path)
        except Exception as e:
            logger.error("时间线导入失败: %s", e)
            QMessageBox.warning(self, "导入失败", f"时间线导入失败：\n{e}")
            return False
        if not imported:
            QMessageBox.warning(self, "导入失败", "文档里没有可导入的片段")
            return False

        clips = self._timeline_store.snapshot()  # 刀7：导入追加分支改读 store 快照
        if clips:
            reply = QMessageBox.question(
                self, "确认导入",
                f"当前时间线已有 {len(clips)} 个片段。\n"
                "导入将**追加**在现有片段之后（不覆盖）。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                self._notify_edit("已取消导入")
                return False

        tw = getattr(self, "_timeline_widget", None)
        video_ti, audio_ti = 0, 1
        if tw is not None and hasattr(tw, "find_track_index_by_type"):
            video_ti = tw.find_track_index_by_type("video", default=0)
            audio_ti = tw.find_track_index_by_type("audio", default=1)
        base = self._timeline_total_duration() if clips else 0.0
        existing_ids = {c.get("id") for c in clips}
        import time as _time
        missing = 0
        seq = 0
        steps: list = []
        for item in imported:
            clip = dict(item)
            clip["track"] = audio_ti if str(clip.get("type", "")).lower() == "audio" else video_ti
            clip["start_time"] = float(clip.get("start_time", 0.0) or 0.0) + base
            cid = str(clip.get("id") or "")
            if not cid or cid in existing_ids:
                seq += 1
                cid = f"clip_import_{int(_time.time() * 1000)}_{seq}"
                clip["id"] = cid
            existing_ids.add(cid)
            if clip.get("path") and not os.path.exists(str(clip["path"])):
                missing += 1
            self._timeline_store.add(clip)
            self._timeline_add_clip_widget(clip)
            steps.append({"type": "add_clip", "clip": clip, "audio_clip": None})

        # 一条 compound 撤销：Ctrl+Z 一次回滚整包导入（复用 add_clip 既有语义）
        try:
            self._record_action({"type": "compound", "steps": steps, "label": "import_timeline"})
        except Exception:
            logger.debug("import_timeline 撤销记录失败", exc_info=True)
        try:
            self._sync_kernel_timeline()
        except Exception:
            logger.debug("导入后同步内核时间线失败", exc_info=True)
        try:
            total = self._timeline_total_duration()
            if tw is not None and hasattr(tw, "set_total_duration") and total > 0:
                tw.set_total_duration(max(total + 2.0, total * 1.02))
        except Exception:
            logger.debug("导入后同步时间线总时长失败", exc_info=True)
        self._preview_seg_key = None  # 重置预览缓存
        self._notify_edit("时间线导入完成")
        tip = f"已导入 {len(steps)} 个片段（{os.path.basename(open_path)}）。"
        if missing:
            tip += f"\n注意：{missing} 个素材文件路径无效（片段已入轨，请重新链接素材）。"
        QMessageBox.information(self, "导入成功", tip)
        return True

    # ────────────── 主导出流程 ──────────────

    def _export_video(self):
        """ """
        if self._timeline_store.snapshot():  # 刀7：主导出入口判空改读 store 快照
            self._refresh_export_project_info()

            def _ct(attr, default=""):
                w = getattr(self, attr, None)
                if w is None:
                    return default
                try:
                    return w.currentText()
                except Exception:
                    cmb = w.findChild(QComboBox) if hasattr(w, "findChild") else None
                    return cmb.currentText() if cmb is not None else default

            # 获取导出设置参数（优先工程画幅 SSOT，与控件双向同步）
            output_mode = _ct("_output_mode_var", "自定义参数")
            sf = getattr(self, "_sequence_format", None)
            if sf is None:
                try:
                    self._sync_sequence_format_from_export_combos(prefer_aspect=False)
                    sf = getattr(self, "_sequence_format", None)
                except Exception:
                    sf = None
            if sf is not None:
                resolution = sf.resolution_str()
                aspect_ratio = sf.aspect
                scale_fit = "crop" if (sf.fit_mode or "contain") == "cover" else "pad"
            else:
                resolution = _ct("_resolution_var", "1080x1920")
                aspect_ratio = _ct("_aspect_var", "9:16")
                scale_fit = "pad"
            platform = _ct("_platform_var", "抖音")
            fps = _ct("_fps_var", "30fps")
            bitrate = _ct("_bitrate_var", "3000k")
            codec = _ct("_codec_var", "H.264")
            audio_codec = _ct("_audio_codec_var", "AAC")
            audio_sample = _ct("_audio_sample_var", "44100")
            audio_bitrate = _ct("_audio_bitrate_var", "128k")
            format = _ct("_format_var", "MP4").lower()
            bitrate_control = _ct("_bitrate_control_var", "CBR")
            gop = "30"
            try:
                gop_w = getattr(self, "_gop_var", None)
                if gop_w is not None:
                    gop = gop_w.text() if hasattr(gop_w, "text") else str(gop_w.value())
            except Exception:
                gop = "30"
            quality = _ct("_quality_var", "高")
            audio_channels = _ct("_audio_channel_var", "立体声")
            hw = getattr(self, "_hardware_accel_var", None)
            hardware_accel = "启用" if (hw is not None and hw.isChecked()) else "禁用"

            # 构建导出参数
            export_params = {
                "resolution": resolution,
                "bitrate": bitrate,
                "format": format,
                "codec": codec,
                "fps": fps,
                "bitrate_control": bitrate_control,
                "gop": gop,
                "aspect_ratio": aspect_ratio,
                "scale_fit": scale_fit,
                "quality": quality,
                "audio_codec": audio_codec,
                "audio_sample": audio_sample,
                "audio_bitrate": audio_bitrate,
                "audio_channels": audio_channels,
                "hardware_accel": hardware_accel,
                "output_mode": output_mode,
            }

            # —— 关键修复：让工具栏的剪切/删除/复制粘贴真正作用到导出视频 ——
            # 若存在时间线编辑(多段/裁剪区间)，先按 in/out 裁剪拼接出已剪辑中间产物，
            # 再交给统一内核套用分辨率/平台等设置；否则走原始单文件逻辑。
            # 刀7：单次取 store 快照供 video_srcs/source_clip_path 共用
            # （锁内浅拷 list、元素仍是 live dict 引用，与旧直读字段级等价）
            export_clips = self._timeline_store.snapshot()
            video_srcs = [
                c for c in export_clips
                if c.get("path") and os.path.exists(c.get("path"))
                and not self._is_export_audio_clip(c)
            ]
            source_clip_path = (video_srcs[0]["path"] if video_srcs
                                else export_clips[0].get("path", ""))
            if not source_clip_path:
                QMessageBox.warning(self, "导出失败", "没有可导出的视频片段")
                return

            # ── 先让用户选导出位置与格式（含时间线互操作格式）──
            # 放在拼接/转码之前：若选的是 OTIO/EDL/FCPXML，直接导出时间线文档，
            # 省掉整条 ffmpeg 拼接渲染（秒级完成）。
            from PyQt6.QtWidgets import QFileDialog
            base_name = os.path.basename(source_clip_path)
            kernel_prefix = "Pro" if self._kernel_mode == "pro" else "Fast"
            default_name = f"[{kernel_prefix}]_{os.path.splitext(base_name)[0]}.{format}"
            _format_filters = {
                "mp4": "MP4 视频 (*.mp4)",
                "mov": "MOV 视频 (*.mov)",
                "mkv": "MKV 视频 (*.mkv)",
                "avi": "AVI 视频 (*.avi)",
            }
            filter_str = _format_filters.get(format, "视频文件 (*.*)")
            # 装了 opentimelineio 才提供互操作格式（未装则不出现，避免误导）
            try:
                from app.core.interchange import otio_adapter as _oa
                if _oa.is_available():
                    from app.core.interchange.editor_timeline_bridge import (
                        timeline_export_filters,
                    )
                    filter_str += ";;" + timeline_export_filters()
            except Exception as _ie:
                logger.debug("时间线互操作格式探测失败: %s", _ie)
            save_path, _sel_filter = QFileDialog.getSaveFileName(
                self, "选择导出位置", default_name, filter_str
            )
            if not save_path:
                self._notify_edit("导出已取消")
                return
            # 时间线互操作（OTIO / EDL / FCPXML）：只导出时间线文档，不渲染视频
            try:
                from app.core.interchange.editor_timeline_bridge import (
                    is_timeline_extension,
                )
                if is_timeline_extension(save_path):
                    self._export_timeline_document(save_path, resolution, fps)
                    return
            except Exception as _ie:
                logger.debug("时间线导出判定失败: %s", _ie)
            # 确保扩展名与用户选择的格式一致
            if not save_path.lower().endswith(f".{format}"):
                save_path = os.path.splitext(save_path)[0] + f".{format}"
            output_path = save_path
            edited_temp_path = None
            self._last_export_error = ""
            self._notify_edit("导出：准备中…")
            # 非 xfade 精确对齐的转场：导出前诚实提示（bake / 近似）
            try:
                from app.core.transition_plugin_registry import collect_transition_export_notes
                _tr_list = []
                for _c in self._timeline_store.snapshot():  # 刀7：转场提示收集改读 store 快照
                    if not isinstance(_c, dict):
                        continue
                    _t = _c.get("transition")
                    if isinstance(_t, dict):
                        _tr_list.append(_t)
                    for _t2 in (_c.get("transitions") or []):
                        if isinstance(_t2, dict):
                            _tr_list.append(_t2)
                _notes = collect_transition_export_notes(_tr_list)
                if _notes:
                    self._notify_edit("导出转场：" + "；".join(_notes))
            except Exception:
                pass
            if self._has_timeline_edits():
                try:
                    edited_temp_path = os.path.join(
                        tempfile.gettempdir(), f"sgxj_edited_{int(time.time() * 1000)}.mp4")
                    self._notify_edit("导出：拼接时间线…")
                    built = self._build_edited_video(edited_temp_path)
                    if not built:
                        # 仅音频/叠轨编辑：复制源片再混轨
                        import shutil as _sh
                        if video_srcs and (
                            self._collect_export_audio_clips()
                            or self._collect_export_overlay_clips(
                                min(int(c.get("track", 0) or 0) for c in video_srcs)
                            )
                        ):
                            _sh.copy2(video_srcs[0]["path"], edited_temp_path)
                            built = os.path.exists(edited_temp_path)
                    if built:
                        try:
                            from app.core.editor_scheduler import editor_scheduler as _es
                            _ff = getattr(_es.get_video_processor(), "ffmpeg_path", "ffmpeg")
                        except Exception:
                            _ff = "ffmpeg"
                        self._notify_edit("导出：叠轨 / 混音…")
                        edited_temp_path = self._finalize_multitrack_export(
                            edited_temp_path, ffmpeg_path=_ff
                        )
                    else:
                        edited_temp_path = None
                        self._last_export_error = "时间线拼接失败"
                except Exception as _e:
                    logger.error(f'构建剪辑后视频失败，回退原始文件: {_e}')
                    self._last_export_error = f"时间线构建失败: {_e}"
                    edited_temp_path = None
            clip_path = edited_temp_path or source_clip_path
            if not os.path.exists(clip_path):
                QMessageBox.warning(
                    self, "导出失败",
                    f"视频文件不存在\n{self._last_export_error or ''}".strip(),
                )
                return

            export_params["platform"] = platform
            platform_map = {
                "抖音": "抖音",
                "快手": "快手",
                "B站": "B站",
                "小红书": "小红书",
                "视频号": "视频号",
                "默认": "通用HD",
            }
            render_platform = platform_map.get(platform, "通用HD")

            # 无 FFmpeg 时：未剪辑可直接复制；有剪辑则明确提示
            # 使用统一的 FFmpeg 路径检测（包含项目内置的 thirdparty/ffmpeg）
            import shutil
            try:
                from app.core.ffmpeg_utils import find_ffmpeg
                _ff = find_ffmpeg()
            except ImportError:
                _ff = shutil.which("ffmpeg")

            if not _ff:
                if edited_temp_path is None and not self._has_timeline_edits():
                    try:
                        shutil.copy2(clip_path, output_path)
                        QMessageBox.information(
                            self,
                            "导出成功",
                            f"未检测到 FFmpeg，已复制原片到:\n{output_path}\n"
                            f"安装 FFmpeg 并加入 PATH 后可支持剪辑导出与转码。",
                        )
                        return
                    except Exception as _ce:
                        QMessageBox.warning(self, "导出失败", f"复制失败: {_ce}")
                        return
                QMessageBox.warning(
                    self,
                    "导出失败",
                    "未检测到 FFmpeg，无法导出已剪辑时间线。\n"
                    "请安装 FFmpeg 并加入系统 PATH 后重试。",
                )
                return

            render_error = ""
            try:
                try:
                    from app.core.editor_scheduler import editor_scheduler
                except ImportError:
                    from core.editor_scheduler import editor_scheduler

                self._notify_edit("导出：转码封装…")
                # 统一内核调度器内部自主选择轻量/专业，并处理渲染后端回退。
                result = editor_scheduler.export_video(
                    clip_path,
                    output_path=output_path,
                    platform=render_platform,
                    params=export_params,
                )
                success = result.get("success") if isinstance(result, dict) else getattr(result, "success", False)
                if success:
                    try:
                        self._notify_edit("导出：字幕烧录…")
                        output_path = self._burn_subtitles_if_any(output_path)
                    except Exception as _be:
                        logger.info(f'字幕烧录跳过: {_be}')
                    try:
                        self._notify_edit("导出：贴纸烧录…")
                        output_path = self._burn_stickers_if_any(output_path)
                    except Exception as _se:
                        logger.info(f'贴纸烧录跳过: {_se}')
                    try:
                        # G1 合规（2026-11-12）：AI 生成内容标识（角标 + 元数据）
                        from app.core.compliance_label import apply_ai_label_inplace
                        _label = apply_ai_label_inplace(output_path)
                        if _label.get("applied"):
                            self._notify_edit("导出：已写入 AI 生成标识")
                        else:
                            logger.info("AI 标识未写入: %s", _label.get("reason"))
                    except Exception as _le:  # stability-gate: allow-swallow（标识失败不得毁掉已导出的成品）
                        logger.info(f'AI 标识写入跳过: {_le}')
                    output_size = result.get("output_size", 0) if isinstance(result, dict) else getattr(result, "output_size", 0)
                    processing_time = result.get("processing_time", 0) if isinstance(result, dict) else getattr(result, "processing_time", 0)
                    self._notify_edit("导出完成")
                    QMessageBox.information(
                        self,
                        "导出成功",
                        f"视频导出完成!\n输出路径: {output_path}\n"
                        f"耗时: {processing_time:.1f}s\n"
                        f"大小: {output_size / 1024 / 1024:.1f}MB"
                    )
                    return
                render_error = result.get("error_message", "") if isinstance(result, dict) else getattr(result, "error_message", "")
                render_error = render_error or "统一内核导出失败"
            except Exception as e:
                render_error = str(e)
                logger.error(f'统一内核导出失败: {e}')
            finally:
                if edited_temp_path and os.path.exists(edited_temp_path):
                    try:
                        if os.path.abspath(edited_temp_path) != os.path.abspath(output_path):
                            os.remove(edited_temp_path)
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)

            if render_error or getattr(self, "_last_export_error", ""):
                detail = render_error or self._last_export_error
                self._notify_edit("导出失败")
                # 继续尝试下方回退路径，但先让用户知道内核失败原因
                logger.error(f'导出内核失败摘要: {detail}')

            task_export_params = {
                "output_mode": output_mode,
                "resolution": resolution,
                "platform": platform,
                "fps": fps,
                "bitrate": bitrate,
                "codec": codec,
                "format": format,
                "bitrate_control": bitrate_control,
                "gop": gop,
                "aspect_ratio": aspect_ratio,
                "scale_fit": scale_fit,
                "quality": quality,
                "audio_codec": audio_codec,
                "audio_sample": audio_sample,
                "audio_bitrate": audio_bitrate,
                "audio_channels": audio_channels,
                "hardware_accel": hardware_accel,
                # 刀7：交 EventBus 的改为快照 list（锁内浅拷），消灭活体列表直交并发遍历隐患
                "clips": self._timeline_store.snapshot()
            }

            self._event_bus.emit(EventType.MODULE_ACTIVATED, {
                "target": "tasks",
                "export_params": task_export_params
            })

            fail_detail = render_error or getattr(self, "_last_export_error", "") or "未知错误"
            QMessageBox.warning(
                self,
                "导出失败",
                f"统一内核导出失败，已同步任务参数到任务模块。\n原因: {fail_detail}"
            )
        else:
            # 延迟导入：规避 editor_export_panel → .modules → .editor_module → editor_export_panel 的循环依赖
            from .modules import show_clear_messagebox
            show_clear_messagebox("操作提示", "请先导入视频")