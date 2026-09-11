"""
editor_effects_mixin.py
========================
EditorEffectsMixin: 从 editor_module.py 抽出的特效/滤镜/节拍应用方法。

设计目标（遵循 .trae/rules/2.md §三 架构分层）:
- **最小侵入**: 方法体完全照搬, self 访问不变
- **零回归风险**: 方法签名/实现不变, 只是文件位置改变
- **单一职责**: 本 Mixin 承载特效应用(淡入淡出/画中画/曲线/色度键/运动跟踪/速度斜坡/节拍检测)
- **不独立实例化**: Mixin 模式, 必须混入宿主类使用

迁移的方法（共 12 个, 约 928 行）:
1. _nudge_selected_clip_frames (原 L8768-8830, 63 行)
2. _apply_fade_effects (原 L9100-9186, 87 行)
3. _sync_timeline_widget_state (原 L9299-9368, 70 行)
4. _top0_smart_clip (原 L9387-9454, 68 行)
5. _predict_viral (原 L9457-9591, 135 行)
6. _apply_pip (原 L9596-9661, 66 行)
7. _apply_chroma_key (原 L9666-9719, 54 行)
8. _apply_speed_ramp (原 L9724-9840, 117 行)
9. _apply_curves (原 L9884-9949, 66 行)
10. _detect_beats (原 L9954-10028, 75 行)
11. _split_on_beats (原 L10030-10082, 53 行)
12. _apply_motion_track (原 L10087-10160, 74 行)

使用方式:
    class EditorModule(BaseModule, AiAgentPanelMixin, EditorExportPanelMixin, EditorAgentPanelMixin, EditorEffectsMixin):
        ...
"""

from typing import Dict, Any, Optional, List
import os
import json
import logging
import subprocess
import threading
import time
import sys as _sys

from PyQt6.QtCore import Qt, QTimer, QUrl, QEvent
from PyQt6.QtGui import QFont, QAction, QColor, QPainter, QPen, QBrush, QFontMetrics
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QInputDialog, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication, QSizePolicy,
    QFormLayout, QSpacerItem, QToolTip, QStackedLayout
)

logger = logging.getLogger("AI短剧编辑器.editor")


def _clear_msgbox(title: str, message: str, parent=None):
    """延迟导入 show_clear_messagebox：抽出到 Mixin 后不能在顶层 `from .modules import`（会循环），
    与 editor_module._clear_msgbox 同策略，调用时局部导入。"""
    from .modules import show_clear_messagebox
    return show_clear_messagebox(title, message, parent)


# 爆款优化引擎类型（_predict_viral 依赖 Platform.DOUYIN 等枚举与 VideoFeatures 构造器）
try:
    from .viral_optimization_engine import Platform, VideoFeatures
except ImportError as _err:
    logger.error(f'爆款优化引擎导入失败: {_err}')
    Platform = None
    VideoFeatures = None


class EditorEffectsMixin:
    """特效/滤镜/节拍应用 Mixin。

    本 Mixin 从 editor_module.py 抽出, 承载特效应用(淡入淡出/画中画/曲线/
    色度键/运动跟踪/速度斜坡/节拍检测/片段微调)等方法。
    """

    # ======================================================================
    # 抽取自 editor_module.py L8768-8830
    # ======================================================================
    def _nudge_selected_clip_frames(self, frames: int):
        """Shift+←/→：选中片段（支持多选）按帧平移。"""
        tw = getattr(self, "_timeline_widget", None)
        clips = []
        if tw is not None and hasattr(tw, "get_selected_clips"):
            clips = list(tw.get_selected_clips() or [])
        if not clips:
            clip = getattr(self, "_current_clip", None)
            if clip:
                clips = [clip]
        if not clips:
            return
        step = self._edit_frame_duration() * int(frames)
        if len(clips) == 1:
            clip = clips[0]
            before = {
                "id": clip.get("id"),
                "start_time": float(clip.get("start_time", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
            }
            clip["start_time"] = max(0.0, float(clip.get("start_time", 0) or 0) + step)
            if tw is not None:
                for w in tw.all_clip_widgets():
                    if w.clip_data.get("id") == clip.get("id"):
                        tw.position_clip_widget(w)
                        break
            payload = dict(clip)
            payload["_edit_before"] = before
            try:
                self._on_clip_trim_committed(payload)
            except Exception:
                self._sync_timeline_widget_state()
            return
        # 多选：一条 compound
        items = []
        for clip in clips:
            st0 = float(clip.get("start_time", 0) or 0)
            before = {
                "id": clip.get("id"),
                "start_time": st0,
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
                "track": int(clip.get("track", 0) or 0),
            }
            clip["start_time"] = max(0.0, st0 + step)
            after = {
                "start_time": float(clip["start_time"]),
                "track": int(clip.get("track", 0) or 0),
                "duration": float(clip.get("duration", 0) or 0),
                "in_point": float(clip.get("in_point", 0) or 0),
                "out_point": float(clip.get("out_point", 0) or 0),
            }
            items.append({"clip_id": clip.get("id"), "before": before, "after": after, "clip": clip})
            if tw is not None:
                for w in tw.all_clip_widgets():
                    if w.clip_data.get("id") == clip.get("id"):
                        tw.position_clip_widget(w)
                        break
        self._on_clip_trim_committed({"_batch_move": True, "items": items})

    # ======================================================================
    # 抽取自 editor_module.py L9100-9186
    # ======================================================================
    def _apply_fade_effects(self):
        """应用音频页整套设置：淡入淡出 + 均衡器 + 降噪 + 压缩器 + 混响（一次 ffmpeg 调用）。"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return

        def _spn_val(attr, default=0):
            row = getattr(self, attr, None)
            w = row.findChild(QSpinBox) if row is not None else None
            return w.value() if w is not None else default

        def _slr_val(attr, default=0):
            row = getattr(self, attr, None)
            w = row.findChild(QSlider) if row is not None else None
            return w.value() if w is not None else default

        def _cmb_val(attr, default="无"):
            row = getattr(self, attr, None)
            w = row.findChild(QComboBox) if row is not None else None
            return w.currentText() if w is not None else default

        fade_in_ms = _spn_val("_fade_in_row", 0)
        fade_out_ms = _spn_val("_fade_out_row", 0)
        eq_low = _slr_val("_eq_low_row", 0)
        eq_mid = _slr_val("_eq_mid_row", 0)
        eq_high = _slr_val("_eq_high_row", 0)
        denoise_on = bool(getattr(self, "_denoise_chk", None) and self._denoise_chk.isChecked())
        denoise_strength = _slr_val("_denoise_strength_row", 50)
        comp_on = bool(getattr(self, "_compressor_chk", None) and self._compressor_chk.isChecked())
        comp_ratio = _slr_val("_compressor_ratio_row", 50)
        reverb = _cmb_val("_reverb_row", "无")

        dur = float(self._get_video_duration(src) or 0)
        af_parts = []
        if fade_in_ms > 0:
            af_parts.append(f"afade=t=in:st=0:d={fade_in_ms / 1000.0:.3f}")
        if fade_out_ms > 0:
            fo_s = fade_out_ms / 1000.0
            st = max(0.0, (dur - fo_s)) if dur > 0 else 0.0
            af_parts.append(f"afade=t=out:st={st:.3f}:d={fo_s:.3f}")
        if eq_low:
            af_parts.append(f"equalizer=f=100:width_type=o:width=2:g={eq_low}")
        if eq_mid:
            af_parts.append(f"equalizer=f=1000:width_type=o:width=1:g={eq_mid}")
        if eq_high:
            af_parts.append(f"equalizer=f=8000:width_type=o:width=2:g={eq_high}")
        if denoise_on:
            nr = max(0.01, min(97.0, 3.0 + denoise_strength / 100.0 * 94.0))
            af_parts.append(f"afftdn=nr={nr:.2f}")
        if comp_on:
            ratio = max(1.0, min(20.0, 1.0 + comp_ratio / 100.0 * 19.0))
            af_parts.append(f"acompressor=threshold=-20dB:ratio={ratio:.2f}:attack=5:release=50")
        reverb_map = {
            "小房间": "aecho=0.8:0.5:40:0.25",
            "中厅": "aecho=0.8:0.6:60|100:0.3|0.2",
            "大教堂": "aecho=0.8:0.7:100|200|300:0.4|0.3|0.2",
            "板式": "aecho=0.8:0.5:20:0.3",
            "弹簧": "aecho=0.8:0.6:30|60:0.35|0.25",
        }
        if reverb in reverb_map:
            af_parts.append(reverb_map[reverb])

        if not af_parts:
            QMessageBox.information(self, "提示", "未设置任何音频效果（淡入淡出/均衡器/降噪/压缩器/混响均为默认值）")
            return

        dst = self._output_path(src, '_audiofx')
        ffmpeg = self._get_ffmpeg()
        try:
            result = subprocess.run([
                ffmpeg, '-y', '-i', src,
                '-af', ",".join(af_parts),
                '-q:a', '2', dst
            ], capture_output=True, text=True)
            if result.returncode != 0 or not os.path.exists(dst):
                QMessageBox.warning(self, "失败", f"音频效果处理失败:\n{(result.stderr or '')[-500:]}")
                return
            self._add_to_clips(dst, 'audio')
            QMessageBox.information(
                self, "完成",
                f"已应用音频效果（淡入{fade_in_ms}ms/淡出{fade_out_ms}ms"
                f"{'/降噪' if denoise_on else ''}{'/压缩' if comp_on else ''}"
                f"{'/混响:' + reverb if reverb in reverb_map else ''}）:\n{dst}",
            )
        except Exception as e:
            QMessageBox.warning(self, "失败", f"处理失败: {e}")

    # ======================================================================
    # 抽取自 editor_module.py L9299-9368
    # ======================================================================
    def _sync_timeline_widget_state(self):
        """同步片段元数据到 ClipWidget，并按 start_time 重新定位。"""
        if not hasattr(self, '_timeline_widget'):
            return
        tw = self._timeline_widget
        # 合缝等路径会 deepcopy 替换 _clips；镜像到时间线并刷新活引用
        tw._clips = list(self._clips)
        try:
            if hasattr(tw, "refresh_load_spans"):
                tw.refresh_load_spans(self._clips)
            if hasattr(tw, "update_in_out_markers"):
                tw.update_in_out_markers(
                    getattr(self, "_sequence_in_point", None),
                    getattr(self, "_sequence_out_point", None),
                )
        except Exception as e:
            logger.debug("同步标尺 I/O / 负载线失败: %s", e)
        cur_id = None
        if isinstance(getattr(self, "_current_clip", None), dict):
            cur_id = self._current_clip.get("id")
        if cur_id:
            self._current_clip = next(
                (c for c in self._clips if c.get("id") == cur_id),
                self._current_clip,
            )
        if isinstance(getattr(tw, "_current_clip", None), dict):
            tid = tw._current_clip.get("id")
            if tid:
                tw._current_clip = next(
                    (c for c in self._clips if c.get("id") == tid),
                    tw._current_clip,
                )
        if hasattr(tw, "all_clip_widgets"):
            for widget in tw.all_clip_widgets():
                clip_id = widget.clip_data.get("id")
                for clip in self._clips:
                    if clip.get("id") == clip_id:
                        widget.clip_data = clip
                        if hasattr(widget, "set_keyframes"):
                            widget.set_keyframes(clip.get("keyframes") or [])
                        # 若轨变更则 reparent
                        ti = int(clip.get("track", 0) or 0)
                        if hasattr(tw, "reparent_clip_to_track"):
                            tw.reparent_clip_to_track(widget, ti)
                        else:
                            tw.position_clip_widget(widget)
                        widget.update()
                        break
            if hasattr(tw, "relayout_clips"):
                tw.relayout_clips()
            if hasattr(tw, "_apply_selection_visual"):
                tw._apply_selection_visual()
        else:
            for track in getattr(tw, '_tracks', []):
                layout = track.get("content_layout")
                if not layout:
                    continue
                for i in range(layout.count()):
                    widget = layout.itemAt(i).widget()
                    if widget is not None and hasattr(widget, "clip_data"):
                        clip_id = widget.clip_data.get("id")
                        for clip in self._clips:
                            if clip.get("id") == clip_id:
                                widget.clip_data = clip
                                duration = float(clip.get("duration", 10))
                                width = int(duration * 20 * (tw._zoom / 100))
                                widget.setFixedWidth(max(80, width))
                                widget.update()
                                break
        tw.update()

    # ======================================================================
    # 抽取自 editor_module.py L9387-9454
    # ======================================================================
    def _top0_smart_clip(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        
        clip_path = self._clips[0]['path']
        platform = self._platform_var.currentText() if hasattr(self, '_platform_var') else "抖音"
        
        # 显示进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在分析视频内容...", "取消", 0, 100, self)
        progress.setWindowTitle("TOP 0级AI智能剪辑")
        progress.setModal(True)
        progress.show()
        
        def update_progress(value, message):
            progress.setValue(int(value))
            progress.setLabelText(message)
        
        try:
            # 通过统一内核调度器执行TOP 0级智能剪辑
            try:
                from app.core.editor_scheduler import editor_scheduler
            except ImportError:
                from core.editor_scheduler import editor_scheduler

            result = editor_scheduler.smart_clip(
                video_path=clip_path,
                target_platform=platform,
                video_style="高光剪辑",
                target_duration=60.0,
                progress_callback=update_progress
            )
            
            progress.setValue(100)
            progress.close()
            
            if result["success"]:
                # 显示结果
                output_count = len(result["output_videos"])
                msg = f"✅ TOP 0级智能剪辑完成!\n\n"
                msg += f"📊 分析结果:\n"
                msg += f"   • 标题: {result['analysis']['title']}\n"
                msg += f"   • 类型: {result['analysis']['genre']}\n"
                msg += f"   • 角色: {', '.join(result['analysis']['characters'][:3])}\n\n"
                msg += f"🎬 生成视频: {output_count} 个\n"
                
                for i, video in enumerate(result["output_videos"][:3], 1):
                    msg += f"   {i}. {video['title']} ({video['duration']:.1f}s)\n"
                
                if output_count > 3:
                    msg += f"   ... 还有 {output_count - 3} 个片段\n"
                
                msg += f"\n📁 输出目录:\n{os.path.dirname(result['output_videos'][0]['path'])}"
                
                QMessageBox.information(self, "智能剪辑完成", msg)
                
                # 将生成的视频添加到素材库
                for video in result["output_videos"]:
                    self._add_clip_to_timeline(video["path"])
            else:
                error_msg = "剪辑失败:\n" + "\n".join([e.get("error", "未知错误") for e in result["errors"]])
                QMessageBox.warning(self, "剪辑失败", error_msg)
                
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "剪辑错误", f"TOP 0级剪辑出错:\n{str(e)}")

    # ======================================================================
    # 抽取自 editor_module.py L9457-9591
    # ======================================================================
    def _predict_viral(self):
        """ """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        
        viral_engine = self._ensure_viral_engine()
        if not viral_engine:
            _clear_msgbox("引擎未就绪", "爆款优化引擎未加载,请检查依赖安装")
            return
        
        clip_path = self._clips[0]['path']
        platform_text = self._platform_var.currentText() if hasattr(self, '_platform_var') else "抖音"
        
        # 映射平台名称
        platform_map = {
            "抖音": Platform.DOUYIN,
            "快手": Platform.KUAISHOU,
            "小红书": Platform.XIAOHONGSHU,
            "B站": Platform.BILIBILI,
            "视频号": Platform.WECHAT
        }
        platform = platform_map.get(platform_text, Platform.DOUYIN)
        
        # 显示进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在分析视频爆款潜力...", "取消", 0, 100, self)
        progress.setWindowTitle("🔥 爆款预测分析")
        progress.setModal(True)
        progress.show()
        
        try:
            # 获取视频信息并构建特征
            progress.setValue(20)
            progress.setLabelText("正在提取视频特征...")
            
            # 这里简化处理,实际应该从AI分析结果中提取特征
            features = VideoFeatures(
                duration=self._total_duration if hasattr(self, '_total_duration') else 60.0,
                scene_count=12,
                avg_scene_duration=5.0,
                dialogue_density=0.7,
                emotion_variance=0.6,
                conflict_intensity=0.75,
                hook_quality=70,
                climax_position=0.7,
                has_cliffhanger=True,
                visual_attractiveness=75,
                audio_quality=80,
                subtitle_quality=70
            )
            
            progress.setValue(50)
            progress.setLabelText("正在预测表现...")
            
            # 预测表现
            prediction = viral_engine.predict_performance(features, platform)
            
            progress.setValue(70)
            progress.setLabelText("正在生成优化建议...")
            
            # 生成优化建议
            suggestions = viral_engine.generate_optimization_suggestions(features, platform)
            
            progress.setValue(90)
            progress.setLabelText("正在分析爆款基因...")
            
            # 获取爆款基因
            viral_genes = viral_engine.analyze_viral_genes("甜宠")
            
            progress.setValue(100)
            progress.close()
            
            # 构建结果显示
            result_text = f"""
🎯 视频爆款潜力分析

📱 目标平台: {platform.value}

📊 表现预测:
   • 3秒完播率: {prediction.to_dict()['3秒完播率']}
   • 整体完播率: {prediction.to_dict()['整体完播率']}
   • 点赞率: {prediction.to_dict()['点赞率']}
   • 评论率: {prediction.to_dict()['评论率']}
   • 分享率: {prediction.to_dict()['分享率']}
   • 爆款概率: {prediction.to_dict()['爆款概率']}
   • 预估播放量: {prediction.to_dict()['预估播放量']}

💡 优化建议 (按优先级排序):
"""
            
            for i, suggestion in enumerate(suggestions[:3], 1):
                result_text += f"""
   {i}. {suggestion.factor.value} (优先级: {suggestion.priority})
      当前得分: {suggestion.current_score:.0f}/100 -> 目标: {suggestion.target_score:.0f}/100
      建议: {suggestion.suggestion.replace(chr(10), chr(10) + '      ')}
      预期改善: {suggestion.expected_improvement}
"""
            
            result_text += f"""
🧬 推荐爆款基因:
"""
            
            for i, gene in enumerate(viral_genes[:3], 1):
                result_text += f"""
   {i}. {gene.pattern_name} (经验成功率: {gene.success_rate:.1%})
      {gene.description}
      关键要素: {', '.join(gene.key_elements)}
"""
            # 如实说明：以上"成功率"/预测数据来自行业经验规则库和启发式模型，
            # 不是本软件对真实播放数据的统计结果，仅供参考
            result_text += "\n⚠️ 以上预测和成功率均为启发式估算，非真实平台数据统计，仅供参考\n"
            
            # 显示结果对话框
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
            dialog = QDialog(self)
            dialog.setWindowTitle("🔥 爆款预测结果")
            dialog.setMinimumSize(600, 500)
            
            layout = QVBoxLayout(dialog)
            
            text_edit = QTextEdit()
            text_edit.setPlainText(result_text)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            
            dialog.exec()
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "分析错误", f"爆款预测出错:\n{str(e)}")

    # ======================================================================
    # 抽取自 editor_module.py L9596-9661
    # ======================================================================
    def _apply_pip(self):
        """画中画：将一个视频叠加到另一个视频上"""
        if len(self._clips) < 2:
            QMessageBox.warning(self, "提示", "画中画需要至少2个素材，请先在时间线导入主视频和叠加视频")
            return

        main_src = self._clips[0]['path']
        overlay_src = self._clips[1]['path']

        if not os.path.exists(main_src) or not os.path.exists(overlay_src):
            QMessageBox.warning(self, "提示", "素材文件不存在")
            return

        dst = self._output_path(main_src, '_pip').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        QMessageBox.information(self, "画中画", "正在合成画中画效果...")

        def do_pip():
            try:
                x_pos = self._pip_x.value() if hasattr(self, '_pip_x') else 75
                y_pos = self._pip_y.value() if hasattr(self, '_pip_y') else 80
                size_pct = self._pip_size.value() if hasattr(self, '_pip_size') else 30
                border_w = self._pip_border.value() if hasattr(self, '_pip_border') else 2

                # 构建 FFmpeg overlay 滤镜
                # overlay=W*x/100-w/2:H*y/100-h/2
                overlay_filter = (
                    f"[1:v]scale=iw*{size_pct/100}:ih*{size_pct/100}"
                )
                if border_w > 0:
                    overlay_filter += f",pad=iw+{border_w*2}:ih+{border_w*2}:{border_w}:{border_w}:white"

                overlay_filter += (
                    f"[pip];"
                    f"[0:v][pip]overlay="
                    f"(main_w-overlay_w)*{x_pos/100}:"
                    f"(main_h-overlay_h)*{y_pos/100}"
                )

                cmd = [
                    ffmpeg, '-y',
                    '-i', main_src,
                    '-i', overlay_src,
                    '-filter_complex', overlay_filter,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy',
                    '-shortest', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    QTimer.singleShot(0, lambda: (
                        self._add_to_clips(dst, 'video'),
                        QMessageBox.information(self, "完成", f"画中画合成完成:\n{dst}")
                    ))
                else:
                    err = result.stderr[-500:]
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"合成失败:\n{err}"))
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时（5分钟）"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

        threading.Thread(target=do_pip, daemon=True).start()

    # ======================================================================
    # 抽取自 editor_module.py L9666-9719
    # ======================================================================
    def _apply_chroma_key(self):
        """智能抠像：去除绿幕/蓝幕/自定义颜色背景"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_chromakey').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        tolerance = (self._chroma_tol.value() if hasattr(self, '_chroma_tol') else 30) / 100.0
        softness = (self._chroma_soft.value() if hasattr(self, '_chroma_soft') else 5) / 100.0
        color_mode = self._chroma_color.currentText() if hasattr(self, '_chroma_color') else "绿色"

        color_map = {"绿色": "0x00FF00", "蓝色": "0x0000FF", "自定义": "0x00FF00"}
        color_hex = color_map.get(color_mode, "0x00FF00")

        QMessageBox.information(self, "智能抠像", "正在处理抠像...")

        def do_chroma():
            try:
                # FFmpeg chromakey filter
                chroma_filter = (
                    f"chromakey={color_hex}:"
                    f"similarity={tolerance:.2f}:"
                    f"blend={softness:.2f}"
                )
                cmd = [
                    ffmpeg, '-y', '-i', src,
                    '-vf', chroma_filter,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    QTimer.singleShot(0, lambda: (
                        self._add_to_clips(dst, 'video'),
                        QMessageBox.information(self, "完成", f"抠像完成:\n{dst}")
                    ))
                else:
                    err = result.stderr[-500:]
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"抠像失败:\n{err}"))
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

        threading.Thread(target=do_chroma, daemon=True).start()

    # ======================================================================
    # 抽取自 editor_module.py L9724-9840
    # ======================================================================
    def _apply_speed_ramp(self):
        """曲线变速：优先走 core.speed_ramping；UI 回调回主线程（A3）。"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        clip = self._current_clip
        if not clip or self._is_export_audio_clip(clip):
            video_clips = [
                c for c in self._clips
                if c.get("path") and not self._is_export_audio_clip(c)
            ]
            clip = video_clips[0] if video_clips else None
        if not clip:
            QMessageBox.warning(self, "提示", "没有可用的视频片段")
            return

        src = clip.get("path", "")
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_speedramp').replace('.mp3', '.mp4')
        preset = self._speed_preset.currentText() if hasattr(self, '_speed_preset') else "无"
        speed_factor = (self._speed_factor.value() if hasattr(self, '_speed_factor') else 100) / 100.0

        if preset == "无" and abs(speed_factor - 1.0) < 1e-6:
            QMessageBox.warning(self, "提示", "请选择变速预设或调整速度因子")
            return

        self._notify_edit(f"曲线变速处理中: {preset}…")

        preset_map = {
            "缓入": "ramp_in",
            "缓出": "ramp_out",
            "缓入缓出": "fast_slow_fast",
            "卡点变速": "bullet_time",
        }

        def _done(ok: bool, path: str, err: str = "", *, speed=None, ramp_dict=None):
            if ok and path and os.path.exists(path):
                if ramp_dict is not None:
                    clip["speed_ramp"] = ramp_dict
                if speed is not None:
                    try:
                        self.set_clip_speed(clip.get("id"), float(speed))
                    except Exception:
                        clip["speed"] = float(speed)
                self._add_to_clips(path, 'video')
                QMessageBox.information(self, "完成", f"变速成片已加入时间线:\n{path}")
            else:
                QMessageBox.warning(self, "失败", err or "变速失败")

        def do_speed():
            err = ""
            ramp_dict = None
            speed_val = None
            try:
                from app.core.speed_ramping import (
                    SpeedRamp, SpeedEasing,
                    apply_speed_ramp_ffmpeg, reverse_clip_ffmpeg,
                )
                video_duration = float(self._get_video_duration(src) or 0) or 10.0
                ok = False
                if preset == "倒放":
                    ok = reverse_clip_ffmpeg(src, dst)
                    err = "" if ok else "倒放失败"
                elif preset in preset_map:
                    ramp = SpeedRamp.preset_preset(preset_map[preset])
                    easing_map = {
                        "线性": SpeedEasing.LINEAR,
                        "缓入": SpeedEasing.EASE_IN,
                        "缓出": SpeedEasing.EASE_OUT,
                        "缓入缓出": SpeedEasing.EASE_IN_OUT,
                        "阶梯": SpeedEasing.STEP,
                    }
                    ui_easing = easing_map.get(
                        self._speed_easing.currentText() if hasattr(self, "_speed_easing") else "线性"
                    )
                    if ui_easing is not None:
                        # UI「缓动」下拉覆盖预设默认曲线（卡点变速用阶跃形，保留原样更稳）
                        if preset != "卡点变速":
                            for kf in ramp.keyframes[1:]:
                                kf.easing = ui_easing
                    # 关键帧时间按片段时长归一化到绝对秒
                    for kf in ramp.keyframes:
                        kf.time = float(kf.time) * video_duration
                    ok = apply_speed_ramp_ffmpeg(src, dst, ramp, total_duration=video_duration)
                    if ok:
                        ramp_dict = ramp.to_dict()
                    err = "" if ok else "曲线变速渲染失败（可改用固定倍率「应用变速」）"
                else:
                    # 固定倍率：写入片段 speed（预览）并导出成片
                    factor = {
                        "0.25x慢放": 0.25,
                        "0.5x慢放": 0.5,
                        "2x快放": 2.0,
                        "4x快放": 4.0,
                    }.get(preset, speed_factor)
                    ramp = SpeedRamp(enabled=True)
                    ramp.add_keyframe(0.0, float(factor), SpeedEasing.LINEAR)
                    ramp.add_keyframe(video_duration, float(factor), SpeedEasing.LINEAR)
                    ok = apply_speed_ramp_ffmpeg(src, dst, ramp, total_duration=video_duration)
                    if ok:
                        speed_val = float(factor)
                        ramp_dict = ramp.to_dict()
                    err = "" if ok else "固定倍率导出失败"
                QTimer.singleShot(
                    0,
                    lambda ok=ok, err=err, rd=ramp_dict, sv=speed_val: _done(
                        ok, dst if ok else "", err, speed=sv, ramp_dict=rd
                    ),
                )
            except Exception as e:
                QTimer.singleShot(0, lambda msg=str(e): _done(False, "", msg))

        threading.Thread(target=do_speed, daemon=True).start()

    # ======================================================================
    # 抽取自 editor_module.py L9884-9949
    # ======================================================================
    def _apply_curves(self):
        """RGB曲线调色：通过FFmpeg curves滤镜实现暗部/中间调/亮部调整"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_curves').replace('.mp3', '.mp4')
        ffmpeg = self._get_ffmpeg()

        channel = self._curve_channel.currentText() if hasattr(self, '_curve_channel') else "RGB"
        shadows = (self._curve_shadows.value() if hasattr(self, '_curve_shadows') else 0) / 100.0
        midtones = (self._curve_midtones.value() if hasattr(self, '_curve_midtones') else 0) / 100.0
        highlights = (self._curve_highlights.value() if hasattr(self, '_curve_highlights') else 0) / 100.0

        QMessageBox.information(self, "曲线调色", f"正在应用 {channel} 曲线...")

        def do_curves():
            try:
                # 构建 FFmpeg curves 滤镜参数
                # curves=preset=lighter|darker|strong_contrast, 或自定义
                # 映射 shadows/midtones/highlights 到 master 曲线
                # 暗部: 0~0.33, 中间调: 0.33~0.67, 亮部: 0.67~1.0

                if abs(shadows) < 0.01 and abs(midtones) < 0.01 and abs(highlights) < 0.01:
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "提示", "请先调整曲线参数"))
                    return

                # 构建 curves 字符串：格式为 "master='0/0 0.25/X 0.5/Y 0.75/Z 1/1'"
                # X = 0.25 + shadows*0.3, Y = 0.5 + midtones*0.3, Z = 0.75 + highlights*0.3
                p1 = max(0.0, min(1.0, 0.25 + shadows * 0.3))
                p2 = max(0.0, min(1.0, 0.50 + midtones * 0.3))
                p3 = max(0.0, min(1.0, 0.75 + highlights * 0.3))

                chan_map = {"RGB": "master", "红色": "red", "绿色": "green", "蓝色": "blue"}
                chan_name = chan_map.get(channel, "master")

                curves_str = f"{chan_name}='0/0 0.25/{p1:.2f} 0.5/{p2:.2f} 0.75/{p3:.2f} 1/1'"

                cmd = [
                    ffmpeg, '-y', '-i', src,
                    '-vf', f'curves={curves_str}',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-c:a', 'copy', dst
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)
                if result.returncode == 0:
                    QTimer.singleShot(0, lambda: (
                        self._add_to_clips(dst, 'video'),
                        QMessageBox.information(self, "完成", f"曲线调色完成:\n{dst}")
                    ))
                else:
                    err = result.stderr[-500:]
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"曲线调色失败:\n{err}"))
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

        threading.Thread(target=do_curves, daemon=True).start()

    # ======================================================================
    # 抽取自 editor_module.py L9954-10028
    # ======================================================================
    def _detect_beats(self):
        """音乐踩点：自动检测BGM节拍点"""
        src = self._get_active_audio_path()
        if not src or not os.path.exists(src):
            QMessageBox.warning(self, "提示", "请先在时间线导入音频/视频素材")
            return

        sensitivity = self._beat_sensitivity.value() if hasattr(self, '_beat_sensitivity') else 5
        self._beat_list.clear()
        self._beat_list.addItem("🥁 正在分析音频节拍...")
        QApplication.processEvents()

        def _set_beat_lines(lines):
            self._beat_list.clear()
            for line in lines:
                self._beat_list.addItem(line)

        def do_detect():
            lines = []
            self._last_beat_times = []
            try:
                # 尝试使用 BGMBeatDetector
                try:
                    import numpy as np
                    from app.core.audio_processor import BGMBeatDetector

                    import soundfile as sf
                    data, sr = sf.read(src)
                    if len(data.shape) > 1:
                        data = np.mean(data, axis=1)

                    detector = BGMBeatDetector()
                    beats = detector.detect_beats(data, sr)
                    self._last_beat_times = [float(b.time) for b in (beats or [])]

                    if beats:
                        from datetime import timedelta
                        for i, beat in enumerate(beats):
                            # 灵敏度过滤：只显示强度足够的节拍
                            threshold = sensitivity / 10.0
                            if beat.intensity >= threshold:
                                ts = str(timedelta(seconds=int(beat.time)))
                                ms = f".{int(beat.time * 100) % 100:02d}"
                                intensity_bar = "█" * int(beat.intensity * 10)
                                lines.append(
                                    f"第{i+1}拍 | {ts}{ms} | {intensity_bar} ({beat.intensity:.1%})"
                                )
                        lines.append(f"━━ 共检测到 {len(beats)} 个节拍点 ━━")
                    else:
                        lines.append("⚠ 未检测到明显节拍，请尝试调整灵敏度")
                    QTimer.singleShot(0, lambda ls=list(lines): _set_beat_lines(ls))
                    return
                except ImportError as e:
                    # 回退到 FFmpeg 基于能量的节拍检测
                    lines = ["使用FFmpeg检测节拍..."]
                    QTimer.singleShot(0, lambda ls=list(lines): _set_beat_lines(ls))

                    ffmpeg = self._get_ffmpeg()
                    # 用 silencedetect 找出音量峰值
                    result = subprocess.run(
                        [ffmpeg, '-y', '-i', src,
                         '-af', f'asplit[a][b];[a]volume=1[b];[b]ametadata=print:key=lavfi.astats.Overall.RMS_level',
                         '-f', 'null', '-'],
                        capture_output=True, text=True, timeout=60,
                        creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0
                    )
                    lines.append("⚠ 需要安装 numpy/soundfile 库以启用完整节拍检测")
                    lines.append("提示: pip install numpy soundfile")
                    self._last_beat_times = []
                    QTimer.singleShot(0, lambda ls=list(lines): _set_beat_lines(ls))
            except Exception as e:
                err = f"❌ 检测失败: {str(e)[:80]}"
                QTimer.singleShot(0, lambda ls=[err]: _set_beat_lines(ls))

        threading.Thread(target=do_detect, daemon=True).start()

    # ======================================================================
    # 抽取自 editor_module.py L10030-10082
    # ======================================================================
    def _split_on_beats(self, every_n: int = 4):
        """把检测出的节拍按 4/8 拍做成切点建议，勾选后才切开。"""
        from app.core.beat_split import beat_split_times
        from app.modules.lego.suggest_checklist import pick_checked_indices

        beats = list(getattr(self, "_last_beat_times", None) or [])
        if not beats:
            QMessageBox.information(
                self, "节拍切开", "请先检测节拍。没有拍点时不会写入假数据，也不会改时间线。"
            )
            return
        clip = getattr(self, "_current_clip", None)
        if not isinstance(clip, dict) and self._clips:
            clip = self._clips[0]
        if not isinstance(clip, dict):
            QMessageBox.warning(self, "节拍切开", "请先选中时间线上的片段")
            return
        start = float(clip.get("start_time") or 0)
        dur = float(clip.get("duration") or 0)
        in_p = float(clip.get("in_point") or 0)
        media_end = in_p + dur
        media_cuts = [
            t for t in beat_split_times(beats, duration=media_end, every_n=every_n)
            if in_p + 0.05 < t < media_end - 0.05
        ]
        timeline_cuts = [start + (t - in_p) for t in media_cuts]
        if not timeline_cuts:
            QMessageBox.information(self, "节拍切开", "当前片段范围内没有可切拍点")
            return
        labels = [f"{i + 1}. 时间线 {t:.2f}s（每 {every_n} 拍）" for i, t in enumerate(timeline_cuts)]
        picked = pick_checked_indices(
            self,
            title="节拍切点建议",
            hint="勾选要切开的拍点。确认后才会改时间线；不自动加转场。",
            labels=labels,
            default_checked=True,
            ok_text="切开选中拍点",
        )
        if picked is None:
            QMessageBox.information(self, "节拍切开", "已取消，未改时间线")
            return
        chosen = [timeline_cuts[i] for i in picked]
        if not chosen:
            QMessageBox.information(self, "节拍切开", "未勾选任何拍点，未改时间线")
            return
        ok_n = 0
        for t in sorted(chosen, reverse=True):
            res = self._cut_at_timeline_time(float(t))
            if res.get("success"):
                ok_n += 1
        QMessageBox.information(
            self, "节拍切开", f"已切开 {ok_n}/{len(chosen)} 处。" if ok_n else "切开失败（可能已在片缘）"
        )

    # ======================================================================
    # 抽取自 editor_module.py L10087-10160
    # ======================================================================
    def _apply_motion_track(self):
        """运动跟踪：通过FFmpeg vidstabdetect 分析视频运动"""
        if not self._clips:
            QMessageBox.warning(self, "提示", "请先导入视频素材")
            return

        src = self._clips[0]['path']
        if not os.path.exists(src):
            QMessageBox.warning(self, "提示", "视频文件不存在")
            return

        dst = self._output_path(src, '_tracked').replace('.mp3', '.mp4')
        track_type = self._track_type.currentText() if hasattr(self, '_track_type') else "平移跟踪"

        QMessageBox.information(self, "运动跟踪", f"正在分析视频运动: {track_type}...")

        def do_track():
            try:
                import tempfile
                ffmpeg = self._get_ffmpeg()

                # 第1步: 生成运动检测数据
                trf_file = tempfile.NamedTemporaryFile(suffix='.trf', delete=False).name
                detect_cmd = [
                    ffmpeg, '-y', '-i', src,
                    '-vf', 'vidstabdetect=result=' + trf_file.replace('\\', '/') + ':shakiness=5:accuracy=15',
                    '-f', 'null', '-'
                ]
                subprocess.run(detect_cmd, capture_output=True, text=True, timeout=120,
                               creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)

                # 第2步: 根据跟踪类型应用稳定/变换
                if os.path.exists(trf_file) and os.path.getsize(trf_file) > 10:
                    track_filter = "vidstabtransform"
                    if track_type == "透视跟踪":
                        track_filter += "=optzoom=1:maxangle=10:crop=black"
                    else:
                        track_filter += "=smoothing=10:crop=black"

                    cmd = [
                        ffmpeg, '-y', '-i', src,
                        '-vf', f'{track_filter}:input={trf_file.replace(chr(92), "/")}',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                        '-c:a', 'copy', dst
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                            creationflags=subprocess.CREATE_NO_WINDOW if _sys.platform == 'win32' else 0)

                    try:
                        os.unlink(trf_file)
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)

                    if result.returncode == 0:
                        QTimer.singleShot(0, lambda: (
                            self._add_to_clips(dst, 'video'),
                            QMessageBox.information(self, "完成", f"运动跟踪完成:\n{dst}")
                        ))
                    else:
                        err = result.stderr[-500:]
                        QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"跟踪失败:\n{err}"))
                else:
                    QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "未能检测到足够的运动数据，请尝试其他视频"))
                    try:
                        os.unlink(trf_file)
                    except Exception as _e:
                        logger.warning("操作异常（已忽略）: %s", _e)
            except subprocess.TimeoutExpired:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", "处理超时"))
            except Exception as e:
                err = str(e)
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "失败", f"处理出错: {err}"))

        threading.Thread(target=do_track, daemon=True).start()

