"""时间线片段控件模块
====================
从 timeline_widget.py 抽取的 ClipWidget（时间线片段控件）。
- ClipWidget: 时间线中的单个片段（拖拽 / 裁剪 / 关键帧 / 胶片条 / 波形）。
延迟导入 TimelineWidget 以解除与 timeline_widget 的循环依赖。
"""
import os
import logging

from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPoint
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFontMetrics, QPolygon, QPixmap,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolTip

from .editor_timeline_tools import (
    apply_batch_start_delta,
    clip_compatible_with_track,
    CLIP_DRAG_THRESHOLD_PX,
)
from .timeline_subwidgets import (
    AUDIO_EXTS,
    _media_worker_gate,
    _TIMELINE_MIN_CLIP_PX,
    _timeline_pps,
    _quantize_time,
    _extract_filmstrip_frames,
)

logger = logging.getLogger("AI短剧编辑器.timeline_widget")

class ClipWidget(QFrame):
    """ """

    clicked = pyqtSignal(object)
    resized = pyqtSignal(object)
    moved = pyqtSignal(object)
    keyframe_clicked = pyqtSignal(object, dict)  # (clip_data, keyframe)
    trim_committed = pyqtSignal(object)  # 拖拽/裁剪松手后发出

    # 补短 P1#8：关键帧可视化 - 属性->颜色 映射
    KEYFRAME_COLORS = {
        'position_x': '#00d4ff', 'position_y': '#00d4ff',
        'scale_x': '#ff9500', 'scale_y': '#ff9500',
        'rotation': '#9c27b0',
        'opacity': '#ffffff',
        'volume': '#4caf50',
        'speed': '#f44336',
        'brightness': '#ffeb3b', 'contrast': '#ffeb3b',
        'saturation': '#ffeb3b', 'hue': '#ffeb3b',
        'blur': '#9e9e9e', 'vignette': '#9e9e9e', 'sharpen': '#9e9e9e',
        'crop_top': '#795548', 'crop_bottom': '#795548',
        'crop_left': '#795548', 'crop_right': '#795548',
    }

    def __init__(self, clip_data, parent=None):
        super().__init__(parent)
        self.clip_data = clip_data
        self._is_selected = False
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False

        # 补短 P1#8：关键帧数据 - 数据契约见 _get_keyframes()/set_keyframes()
        # 期望格式（clip_data['keyframes'] 或显式调用 set_keyframes 传入）：
        #   [
        #     {"time_offset": 1.2, "value": 0.5, "prop": "opacity", "easing": "linear"},
        #     ...
        #   ]
        # 没有数据时不做任何绘制 - 完全不影响现有 clip 外观
        self._keyframes = self._coerce_keyframes(clip_data.get('keyframes'))
        self._kf_hit_radius = 7  # 命中半径（px），与绘制点尺寸匹配

        # 缩略图（剪映式胶片条）和波形缓存
        self._thumbnail_cache = []
        self._thumb_key = None  # (path, in, out, n, thumb_h)
        self._thumb_aspect = 0.0  # 0=未知，绘制/格宽用首帧比例
        self._thumb_gen_token = 0  # 丢弃过期 worker 结果
        self._waveform_peaks = None  # None=未就绪, []=失败, list=成功
        self._waveform_failed = False
        self._waveform_scheduled = False
        self._thumbnails_generated = False
        # 胶片条绘制缓存：(thumb_h, cell_w, fast) → {src_idx: QPixmap}
        self._scaled_thumb_cache = {}
        self._scaled_thumb_cache_key = None

        # 工作线程引用 - 用于生命周期管理
        self._thumbnail_worker = None
        self._waveform_worker = None
        try:
            self.destroyed.connect(self._on_clip_widget_destroyed)
        except Exception:
            pass

        self._thumb_debounce = QTimer(self)
        self._thumb_debounce.setSingleShot(True)
        self._thumb_debounce.setInterval(120)
        self._thumb_debounce.timeout.connect(self._schedule_thumbnail_generation)

        self.setFixedHeight(48)  # 与 TRACK_H 一致；最终以 position_clip_widget 为准
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 异步调度缩略图/波形：先让代理任务抢跑，再采胶片（长片避免与代理/预览抢解码）
        QTimer.singleShot(450, self._request_thumbnail_refresh)
        if self._is_audio_clip():
            QTimer.singleShot(200, lambda: self._schedule_waveform_generation(200))
        # 音频轨道使用不同的背景色
        is_audio = self._is_audio_clip()
        bg_color = "#1a4a3a" if is_audio else "#0d1f3a"
        hover_color = "#225a4a" if is_audio else "#132a4a"
        
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 3px;
                border: none;
            }}
            QFrame:hover {{
                background-color: {hover_color};
            }}
            QFrame[selected="true"] {{
                border: 1.5px solid #ff4757;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        # 音频片不显示文字标签，只显示波形
        if not is_audio:
            # 片段名称叠在缩略图上（半透明底，不占纵向空间）
            clip_text = os.path.basename(clip_data.get('path', '未命名'))
            clip_name = QLabel()
            clip_name.setStyleSheet(
                "color:#fff;font-size:10px;background:rgba(0,0,0,110);"
                "border:none;border-radius:2px;padding:1px 4px;"
            )
            clip_name.setMaximumWidth(120)
            clip_name.setText(QFontMetrics(clip_name.font()).elidedText(clip_text, Qt.TextElideMode.ElideRight, 120))
            layout.addWidget(clip_name, 0, Qt.AlignmentFlag.AlignTop)

            layout.addStretch()

            # 时长标签
            dur = clip_data.get('duration', 0)
            dur_lbl = QLabel(f"{dur:.1f}s" if dur < 60 else f"{int(dur//60)}:{int(dur%60):02d}")
            dur_lbl.setStyleSheet(
                "color:#e8f0ff;font-size:9px;background:rgba(0,0,0,110);"
                "border:none;border-radius:2px;padding:1px 4px;"
            )
            layout.addWidget(dur_lbl, 0, Qt.AlignmentFlag.AlignTop)

    def _find_timeline(self):
        """沿父链查找 TimelineWidget。"""
        w = self.parent()
        while w is not None:
            if hasattr(w, "_tracks") and hasattr(w, "find_track_index_by_type"):
                return w
            w = w.parent()
        return None

    def _is_audio_clip(self) -> bool:
        """按 type / 扩展名 / 所在轨 type 判断是否为音频片（不写死 track==1）。"""
        if str(self.clip_data.get("type", "")).lower() == "audio":
            return True
        path = self.clip_data.get("path", "") or ""
        if path and any(path.lower().endswith(e) for e in AUDIO_EXTS):
            return True
        ti = int(self.clip_data.get("track", 0) or 0)
        timeline = self._find_timeline()
        if timeline is not None and 0 <= ti < len(timeline._tracks):
            if timeline._tracks[ti].get("type") == "audio":
                return True
        return False

    # ------------------------------------------------------------------
    # 补短 P1#8：关键帧数据接入（最小侵入 - 不影响无关键帧的 clip）
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_keyframes(raw):
        """
        规整关键帧数据：
          - 接受 None / 缺失 / 非 list 都返回空列表
          - 过滤掉缺 time_offset 的项
        """
        if not raw or not isinstance(raw, (list, tuple)):
            return []
        out = []
        for kf in raw:
            if not isinstance(kf, dict):
                continue
            if 'time_offset' not in kf and 't' not in kf:
                continue
            out.append({
                'time_offset': float(kf.get('time_offset', kf.get('t', 0.0))),
                'value': kf.get('value', 0.0),
                'prop': str(kf.get('prop', kf.get('property', 'value'))),
                'easing': str(kf.get('easing', 'linear')),
            })
        # 按时间排序，方便绘制与命中
        out.sort(key=lambda x: x['time_offset'])
        return out

    def set_keyframes(self, keyframes):
        """
        公开 API：更新关键帧数据并触发重绘。

        用法：
            clip_widget.set_keyframes([
                {"time_offset": 1.2, "value": 0.5, "prop": "opacity"},
            ])
        """
        self._keyframes = self._coerce_keyframes(keyframes)
        # 同步回 clip_data，保证序列化和撤销栈一致
        self.clip_data['keyframes'] = [
            {**kf, 'time_offset': kf['time_offset']} for kf in self._keyframes
        ]
        self.update()  # 触发 paintEvent

    def get_keyframes(self):
        """返回当前关键帧数据副本（防止外部误改内部状态）"""
        return [dict(kf) for kf in self._keyframes]

    def _color_for_prop(self, prop_name):
        return self.KEYFRAME_COLORS.get(prop_name, '#ffffff')

    def _time_to_x(self, time_offset):
        """关键帧时间偏移 -> clip 内 x 坐标（与 TimelineWidget 的 px_per_sec 算法保持一致）"""
        try:
            scale_factor = self.parent()._zoom / 100
        except (AttributeError, TypeError):
            scale_factor = 1.0
        return int(time_offset * 20 * scale_factor)

    def _keyframe_rects(self):
        """
        返回所有关键帧点的 (x, y_center, color, kf_dict)，
        x 会被裁剪到 [2, width-2]，保证不出 clip 边界。
        """
        rects = []
        w = self.width()
        h = self.height()
        # 关键帧点固定画在底部 6px 高的条带上（不与顶部 QLabel 文字冲突）
        band_top = h - 7
        y_center = band_top + 3
        for kf in self._keyframes:
            x = self._time_to_x(kf['time_offset'])
            if x < 2:
                x = 2
            elif x > w - 2:
                x = w - 2
            rects.append((x, y_center, self._color_for_prop(kf['prop']), kf))
        return rects

    def paintEvent(self, event):
        """
        补短 P1#8：在 QFrame 原样式（stylesheet 背景）之上叠加关键帧菱形点。

        关键设计：
          1. 先 super().paintEvent() 让 QFrame 走自己的 stylesheet，保持原样
          2. 再用 QPainter 叠加绘制 - 不修改 QSS、不增加子控件
          3. 无关键帧时直接走 super().paintEvent，零开销零影响
          4. 选中态点稍大、描边亮；非选中态点 5x5、描边半透明
          5. 视频片段显示缩略图预览条，音频片段显示波形可视化
        """
        super().paintEvent(event)
        
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            
            clip_path = self.clip_data.get('path', '') or self.clip_data.get('name', '')
            is_audio = self._is_audio_clip()
            
            # ── 视频胶片条：一格一帧（按时间等距映射），铺满轨高 ──
            if not is_audio and self.width() > 20:
                thumb_h = max(1, self.height())
                aspect = float(getattr(self, "_thumb_aspect", 0) or 0) or (16.0 / 9.0)
                valid = [
                    pm for pm in (self._thumbnail_cache or [])
                    if pm is not None and not pm.isNull() and pm.height() > 0
                ]
                if valid:
                    aspect = float(valid[0].width()) / float(valid[0].height())
                    self._thumb_aspect = aspect
                cell_w = max(14, int(round(thumb_h * aspect)))
                segments = max(1, (self.width() + cell_w - 1) // max(1, cell_w))
                n_cache = len(valid)
                timeline = self._find_timeline_widget()
                fast = bool(
                    timeline is not None and timeline.is_clip_interaction_active()
                )
                xform = (
                    Qt.TransformationMode.FastTransformation
                    if fast
                    else Qt.TransformationMode.SmoothTransformation
                )
                scale_key = (thumb_h, cell_w, fast, id(valid[0]) if valid else 0)
                if scale_key != getattr(self, "_scaled_thumb_cache_key", None):
                    self._scaled_thumb_cache = {}
                    self._scaled_thumb_cache_key = scale_key

                if valid:
                    for i in range(segments):
                        x = i * cell_w
                        if x >= self.width():
                            break
                        # 等距映射到缓存帧，禁止 i%N 循环刷同一帧
                        if segments <= 1 or n_cache <= 1:
                            idx = 0
                        else:
                            idx = int(round(i * (n_cache - 1) / max(1, segments - 1)))
                            idx = max(0, min(n_cache - 1, idx))
                        pixmap = valid[idx]
                        draw_w = min(cell_w, self.width() - x)
                        scaled = self._scaled_thumb_cache.get(idx)
                        if scaled is None or scaled.isNull():
                            scaled = pixmap.scaledToHeight(thumb_h, xform)
                            if scaled.width() < draw_w:
                                scaled = pixmap.scaled(
                                    draw_w, thumb_h,
                                    Qt.AspectRatioMode.IgnoreAspectRatio,
                                    xform,
                                )
                            self._scaled_thumb_cache[idx] = scaled
                        if scaled.width() < draw_w:
                            painter.drawPixmap(x, 0, scaled)
                        else:
                            x_off = max(0, (scaled.width() - draw_w) // 2)
                            painter.drawPixmap(
                                x, 0, draw_w, thumb_h,
                                scaled, x_off, 0, draw_w, thumb_h,
                            )
                else:
                    for i in range(segments):
                        x = i * cell_w
                        if x >= self.width():
                            break
                        draw_w = min(cell_w, self.width() - x)
                        shade = 160 + (i % 3) * 20
                        painter.fillRect(x, 0, draw_w, thumb_h, QColor(30, 90, shade, 220))
            
            # ── 音频片段波形可视化（按轨 type / 扩展名，不写死 track==1）──
            if is_audio:
                wave_height = 28
                bar_count = max(4, self.width() // 6)
                bar_width = max(2, (self.width() - 4) // bar_count - 2)
                wave_y = (self.height() - wave_height) // 2

                if self._waveform_peaks is None and not self._waveform_failed:
                    # 加载中：浅色中线，不刷假随机波形
                    if not self._waveform_scheduled:
                        self._schedule_waveform_generation(bar_count)
                    painter.setPen(QPen(QColor(46, 204, 113, 80), 1))
                    mid = wave_y + wave_height // 2
                    painter.drawLine(2, mid, max(3, self.width() - 2), mid)
                elif self._waveform_failed or not self._waveform_peaks:
                    # 失败 / 无音轨：明确空态中线
                    painter.setPen(QPen(QColor(129, 199, 132, 100), 1, Qt.PenStyle.DashLine))
                    mid = wave_y + wave_height // 2
                    painter.drawLine(2, mid, max(3, self.width() - 2), mid)
                else:
                    peaks = self._waveform_peaks
                    peak_max = max(peaks) if peaks else 0.0
                    # 可视化增益：弱信号放大到可见，全 0 已走失败态
                    gain = (0.85 / peak_max) if peak_max > 1e-6 else 1.0
                    for i in range(bar_count):
                        x = 2 + i * (bar_width + 2)
                        peak_val = peaks[i % len(peaks)] if peaks else 0.0
                        peak_val = min(1.0, peak_val * gain)
                        h = max(4, int(peak_val * wave_height))
                        c = QColor(46, 204, 113, 200)
                        painter.fillRect(x, wave_y + (wave_height - h) // 2, bar_width, h, c)
            
            # ── 关键帧绘制 ──
            if not self._keyframes:
                painter.end()
                return

            # 选中时画一层底部高亮带（提示用户该 clip 有动画）
            if self._is_selected and self._keyframes:
                band_color = QColor(0, 0, 0, 60)
                painter.fillRect(0, self.height() - 7, self.width(), 7, band_color)

            size = 5 if self._is_selected else 4
            for x, y, color_hex, _kf in self._keyframe_rects():
                color = QColor(color_hex)
                # 填充菱形
                if self._is_selected:
                    painter.setBrush(QBrush(color))
                    painter.setPen(QPen(QColor(255, 255, 255), 1.2))
                else:
                    # 非选中：半透明 + 深色描边
                    fill = QColor(color)
                    fill.setAlpha(200)
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(QColor(0, 0, 0, 180), 1))

                # 菱形（4 个顶点） - 用 QPolygon 即可
                half = size
                poly = QPolygon([
                    QPoint(x, y - half),
                    QPoint(x + half, y),
                    QPoint(x, y + half),
                    QPoint(x - half, y),
                ])
                painter.drawPolygon(poly)
        finally:
            painter.end()

    def _hit_test_keyframe(self, pos):
        """
        鼠标位置命中关键帧点测试。命中返回 kf dict，否则返回 None。
        使用曼哈顿距离（菱形近似），半径 = self._kf_hit_radius。
        """
        for x, y, _color, kf in self._keyframe_rects():
            if abs(pos.x() - x) + abs(pos.y() - y) <= self._kf_hit_radius:
                return kf
        return None
        
    def _find_timeline_widget(self):
        from .timeline_widget import TimelineWidget  # 延迟导入，避免与 timeline_widget 循环依赖
        w = self.parent()
        while w is not None:
            if isinstance(w, TimelineWidget):
                return w
            w = w.parent()
        return None

    def _write_fields(self, **kv) -> None:
        """clip_data 字段写统一入口：经 timeline 引用取 store 走唯一写缝（刀8 形态A）；
        独立场景（无 timeline 祖先）直写活 dict 保持行为不变。"""
        timeline = self._find_timeline_widget()
        if timeline is not None:
            timeline._write_clip_fields(self.clip_data, **kv)
        else:
            for k, v in kv.items():
                self.clip_data[k] = v

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            timeline = self._find_timeline_widget()
            if timeline is not None:
                timeline.show_clip_context_menu(
                    self.clip_data,
                    event.globalPosition().toPoint(),
                )
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            timeline = self._find_timeline_widget()
            if timeline is not None and timeline.is_razor_mode():
                # 刀片：点片段即在指针时间切开（含联动音画由 Editor 处理）
                event.accept()
                timeline._razor_cut_at_global(event.globalPosition().toPoint())
                return
            self._drag_start_pos = event.pos()
            self._drag_offset = self.pos()
            self._batch_drag_starts = None
            try:
                import copy
                self._edit_before = copy.deepcopy({
                    "id": self.clip_data.get("id"),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "track": int(self.clip_data.get("track", 0) or 0),
                })
            except Exception:
                self._edit_before = None
            # 检查是否点击在边缘(调整大小)
            edge = max(8, min(18, self.width() // 8))
            if event.pos().x() < edge:
                self._is_resizing = True
                self._resize_direction = 'left'
                self._resize_snapshot = {
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "direction": "left",
                }
            elif event.pos().x() > self.width() - edge:
                self._is_resizing = True
                self._resize_direction = 'right'
                self._resize_snapshot = {
                    "duration": float(self.clip_data.get("duration", 0) or 0),
                    "in_point": float(self.clip_data.get("in_point", 0) or 0),
                    "out_point": float(self.clip_data.get("out_point", 0) or 0),
                    "start_time": float(self.clip_data.get("start_time", 0) or 0),
                    "direction": "right",
                }
            else:
                # 补短 P1#8：若点击命中关键帧点，发 keyframe_clicked 而非切换选中
                # 这样不打断用户的"先看 clip 再细看关键帧"的操作流
                kf_hit = self._hit_test_keyframe(event.pos())
                if kf_hit is not None:
                    self.keyframe_clicked.emit(self.clip_data, kf_hit)
                    # 不进入选中/拖拽流程，但仍消费事件
                    super().mousePressEvent(event)
                    return

                self._is_resizing = False
                # 选区由 TimelineWidget 根据修饰键决定，此处只发点击
                self.clicked.emit(self.clip_data)
                # 多选批量拖：若本片已在选区且选区>1，记录组内起点
                self._batch_drag_starts = None
                timeline = self._find_timeline_widget()
                if timeline is not None:
                    ids = timeline.get_selected_ids()
                    cid = self.clip_data.get("id")
                    if cid not in ids:
                        # Ctrl 取消选中：不进入拖拽，避免拖走「已取消」的片
                        self._drag_start_pos = None
                        self._drag_offset = None
                    elif cid in ids and len(ids) > 1:
                        starts = {}
                        tracks0 = {}
                        for c in getattr(timeline, "_clips", []) or []:
                            if c.get("id") in ids:
                                starts[c.get("id")] = float(c.get("start_time", 0) or 0)
                                tracks0[c.get("id")] = int(c.get("track", 0) or 0)
                        self._batch_drag_starts = starts
                        self._batch_drag_tracks0 = tracks0
            if getattr(self, "_is_resizing", False):
                self._resize_global_x0 = float(event.globalPosition().x())
                self._resize_width0 = int(self.width())
                self._resize_x0 = int(self.x())
                self._batch_drag_starts = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_razor_mode():
            timeline._update_razor_hover(event.globalPosition().toPoint())
            event.accept()
            return
        # 补短 P1#8：未在拖拽/调整大小时，命中关键帧点 -> 显示 tooltip
        if not self._is_resizing and not (self._drag_start_pos and self._drag_offset):
            kf_hit = self._hit_test_keyframe(event.pos())
            if kf_hit is not None:
                tip = self._format_keyframe_tooltip(kf_hit)
                QToolTip.showText(event.globalPosition().toPoint(), tip, self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QToolTip.hideText()
                # 不强制重置 cursor，避免和 track 拖拽的 cursor 冲突
            # tooltip 处理完直接返回，不影响原有拖拽/调整大小逻辑
            return

        if self._is_resizing:
            # 误触保护：片缘微抖不触发 trim
            gx0 = float(getattr(self, "_resize_global_x0", event.globalPosition().x()))
            dx_probe = float(event.globalPosition().x()) - gx0
            if not self._did_edit_drag and abs(dx_probe) < CLIP_DRAG_THRESHOLD_PX:
                return
            # 用全局 dx + 按下时宽/位置，trim 跟手不漂移
            self._did_edit_drag = True
            timeline = self._find_timeline_widget()
            if timeline is not None:
                timeline.set_clip_interaction_active(True)
                timeline.register_active_drag_clip(self)
                try:
                    self.grabKeyboard()
                except Exception:
                    pass
            pps = timeline.px_per_sec() if timeline is not None else _timeline_pps(100)
            fd = timeline.frame_duration() if timeline is not None else (1.0 / 30.0)
            w0 = int(getattr(self, "_resize_width0", self.width()))
            x0 = int(getattr(self, "_resize_x0", self.x()))
            dx = dx_probe
            snap = getattr(self, "_resize_snapshot", None) or {}
            if self._resize_direction == 'right':
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(w0 + dx)))
                end_t = (x0 + new_width) / max(1e-6, pps)
                if timeline is not None:
                    end_t = timeline.snap_time(
                        end_t,
                        exclude_id=self.clip_data.get("id"),
                        track_i=int(self.clip_data.get("track", 0) or 0),
                    )
                st = float(snap.get("start_time", self.clip_data.get("start_time", 0)) or 0)
                new_dur = max(fd, end_t - st)
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(new_dur * pps)))
                self.setFixedWidth(new_width)
                in_p = float(self.clip_data.get("in_point", snap.get("in_point", 0)) or 0)
                self._write_fields(duration=new_dur, out_point=in_p + new_dur)
                self.resized.emit(self.clip_data)
            elif self._resize_direction == 'left':
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(w0 - dx)))
                new_x = max(0, int(round(x0 + (w0 - new_width))))
                st = new_x / max(1e-6, pps)
                if timeline is not None:
                    st = timeline.snap_time(
                        st,
                        exclude_id=self.clip_data.get("id"),
                        track_i=int(self.clip_data.get("track", 0) or 0),
                    )
                end = float(snap.get("start_time", 0) or 0) + float(snap.get("duration", 0) or 0)
                new_dur = max(fd, end - st)
                new_x = max(0, int(round(st * pps)))
                new_width = max(_TIMELINE_MIN_CLIP_PX, int(round(new_dur * pps)))
                self.setFixedWidth(new_width)
                self.move(new_x, 0)
                dt = float(snap.get("duration", 0) or 0) - new_dur
                in_new = max(0.0, float(snap.get("in_point", 0) or 0) + dt)
                self._write_fields(start_time=st, duration=new_dur,
                                   in_point=in_new, out_point=in_new + new_dur)
                self.resized.emit(self.clip_data)
        elif self._drag_start_pos and self._drag_offset:
            # 误触保护：短距离移动视为点击，不挪片
            if not self._did_edit_drag:
                try:
                    if (event.pos() - self._drag_start_pos).manhattanLength() < CLIP_DRAG_THRESHOLD_PX:
                        return
                except Exception:
                    pass
            # 拖拽：允许跨轨（Y），X 映射 start_time；拖动中实时吸附
            self._did_edit_drag = True
            timeline = self._find_timeline_widget()
            if timeline is not None:
                timeline.set_clip_interaction_active(True)
                timeline.register_active_drag_clip(self)
                try:
                    self.grabKeyboard()
                except Exception:
                    pass
            parent = self.parent()
            new_pos = self.mapToParent(event.pos()) - self._drag_start_pos + self._drag_offset
            if new_pos.x() < 0:
                new_pos.setX(0)
            batch_starts = getattr(self, "_batch_drag_starts", None)
            if batch_starts and timeline is not None and len(batch_starts) > 1:
                # 多选同步平移 + 跨轨（同类型）；吸附参照指针下兼容轨
                px = max(1e-6, timeline.px_per_sec())
                proposed = max(0.0, new_pos.x() / px)
                gy = event.globalPosition().toPoint().y()
                drop_ti, drop_ok = timeline.resolve_drop_track(gy, self.clip_data)
                timeline.set_drop_track_feedback(drop_ti, drop_ok)
                snap_ti = drop_ti if (drop_ok and drop_ti is not None) else int(
                    self.clip_data.get("track", 0) or 0
                )
                apply_batch_start_delta(
                    timeline,
                    batch_starts,
                    self.clip_data.get("id"),
                    proposed,
                    exclude_ids=list(batch_starts.keys()),
                    snap_track_i=snap_ti,
                )
                if drop_ok and drop_ti is not None:
                    for cid in list(batch_starts.keys()):
                        w = next(
                            (cw for cw in timeline.all_clip_widgets()
                             if cw.clip_data.get("id") == cid),
                            None,
                        )
                        if w is None:
                            continue
                        cd = w.clip_data
                        if not clip_compatible_with_track(cd, timeline._tracks[drop_ti]):
                            continue
                        if int(cd.get("track", -1) or -1) == drop_ti:
                            continue
                        timeline.reparent_clip_to_track(w, drop_ti)
                        for c in timeline._clips:
                            if c.get("id") == cid:
                                timeline._write_clip_fields(c, track=drop_ti)
                                break
                self.moved.emit(self.clip_data)
                return
            if timeline is not None:
                gy = event.globalPosition().toPoint().y()
                drop_ti, drop_ok = timeline.resolve_drop_track(gy, self.clip_data)
                timeline.set_drop_track_feedback(drop_ti, drop_ok)
                if drop_ok and drop_ti is not None:
                    track = timeline._tracks[drop_ti]
                    if parent is not track.get("clip_container"):
                        self.setParent(track["clip_container"])
                        self._write_fields(track=drop_ti)
                        parent = track["clip_container"]
                        self.show()
                # 不兼容轨：不 reparent，仍可横向拖；吸附用当前轨
                px = max(1e-6, timeline.px_per_sec())
                st = max(0.0, new_pos.x() / px)
                snap_ti = int(self.clip_data.get("track", 0) or 0)
                st = timeline.snap_start_time(
                    self.clip_data,
                    st,
                    exclude_id=self.clip_data.get("id"),
                    track_i=snap_ti,
                )
                self._write_fields(start_time=st)
                timeline.position_clip_widget(self)
                self.moved.emit(self.clip_data)
            else:
                self.move(max(0, new_pos.x()), 0)

    def mouseReleaseEvent(self, event):
        # 松手时按最终宽度规范化 in/out，保证导出与预览一致
        if self._did_edit_drag:
            try:
                timeline = self._find_timeline_widget()
                px = timeline.px_per_sec() if timeline is not None else _timeline_pps(100)
                fd = timeline.frame_duration() if timeline is not None else (1.0 / 30.0)
                batch_starts = getattr(self, "_batch_drag_starts", None)
                # ── 多选批量平移提交（一条 undo）──
                if batch_starts and timeline is not None and len(batch_starts) > 1 and not self._is_resizing:
                    items = []
                    tracks0 = getattr(self, "_batch_drag_tracks0", None) or {}
                    for cid, st0 in batch_starts.items():
                        clip = next(
                            (c for c in timeline._clips if c.get("id") == cid),
                            None,
                        )
                        if clip is None:
                            continue
                        st = _quantize_time(float(clip.get("start_time", 0) or 0), fd)
                        timeline._write_clip_fields(clip, start_time=st)
                        w = next(
                            (cw for cw in timeline.all_clip_widgets() if cw.clip_data.get("id") == cid),
                            None,
                        )
                        if w is not None:
                            w._write_fields(start_time=st)
                            timeline.position_clip_widget(w)
                        before = {
                            "id": cid,
                            "start_time": float(st0),
                            "duration": float(clip.get("duration", 0) or 0),
                            "in_point": float(clip.get("in_point", 0) or 0),
                            "out_point": float(clip.get("out_point", 0) or 0),
                            "track": int(tracks0.get(cid, clip.get("track", 0)) or 0),
                        }
                        after = {
                            "start_time": st,
                            "track": int(clip.get("track", 0) or 0),
                            "duration": float(clip.get("duration", 0) or 0),
                            "in_point": float(clip.get("in_point", 0) or 0),
                            "out_point": float(clip.get("out_point", 0) or 0),
                        }
                        items.append({"clip_id": cid, "before": before, "after": after, "clip": clip})
                    if timeline is not None:
                        timeline.clear_snap_guide(fade=True)
                        timeline.clear_drop_track_feedback()
                    self.trim_committed.emit({"_batch_move": True, "items": items})
                    self._batch_drag_starts = None
                    self._batch_drag_tracks0 = None
                    self._is_resizing = False
                    self._resize_direction = None
                    self._drag_start_pos = None
                    self._drag_offset = None
                    self._resize_snapshot = None
                    self._did_edit_drag = False
                    self._edit_before = None
                    if timeline is not None:
                        timeline.set_clip_interaction_active(False)
                        timeline._active_drag_clip = None
                    try:
                        self.releaseKeyboard()
                    except Exception:
                        pass
                    super().mouseReleaseEvent(event)
                    return

                dur = max(fd, self.width() / max(1e-6, px))
                # 帧量化，避免亚帧碎口
                if timeline is not None:
                    st0 = float(self.clip_data.get("start_time", 0) or 0)
                    self._write_fields(start_time=_quantize_time(st0, fd))
                    dur = max(fd, _quantize_time(dur, fd))
                snap = self._resize_snapshot
                if snap and snap.get("direction") == "right":
                    in_p = float(self.clip_data.get("in_point", snap.get("in_point", 0)) or 0)
                    self._write_fields(duration=dur, out_point=in_p + dur)
                    # 片尾吸附
                    if timeline is not None:
                        st = float(self.clip_data.get("start_time", 0) or 0)
                        end = timeline.snap_time(
                            st + dur,
                            exclude_id=self.clip_data.get("id"),
                            track_i=int(self.clip_data.get("track", 0) or 0),
                        )
                        new_dur = max(fd, end - st)
                        self._write_fields(duration=new_dur, out_point=in_p + new_dur)
                        timeline.position_clip_widget(self)
                elif snap and snap.get("direction") == "left":
                    end = float(snap["start_time"]) + float(snap["duration"])
                    dt = float(snap["duration"]) - dur
                    in_new = max(0.0, float(snap["in_point"]) + dt)
                    self._write_fields(duration=dur, start_time=max(0.0, end - dur),
                                       in_point=in_new, out_point=in_new + dur)
                    # 片头吸附
                    if timeline is not None:
                        st = timeline.snap_time(
                            float(self.clip_data.get("start_time", 0) or 0),
                            exclude_id=self.clip_data.get("id"),
                            track_i=int(self.clip_data.get("track", 0) or 0),
                        )
                        new_dur = max(fd, end - st)
                        in_new = max(0.0, float(snap["in_point"]) + (float(snap["duration"]) - new_dur))
                        self._write_fields(start_time=st, duration=new_dur,
                                           in_point=in_new, out_point=in_new + new_dur)
                        timeline.position_clip_widget(self)
                else:
                    # 纯平移：吸附播放头 / 邻片
                    st = float(self.clip_data.get("start_time", 0) or 0)
                    if timeline is not None:
                        st = timeline.snap_start_time(
                            self.clip_data, st, exclude_id=self.clip_data.get("id"))
                        self._write_fields(start_time=st)
                        timeline.position_clip_widget(self)
                # 附带 before 供撤销
                payload = self.clip_data
                if getattr(self, "_edit_before", None):
                    payload = dict(self.clip_data)
                    payload["_edit_before"] = self._edit_before
                self.trim_committed.emit(payload)
                # trim 改变 in/out → 胶片条内容随源区间移动
                self._request_thumbnail_refresh()
                if timeline is not None:
                    timeline.clear_snap_guide(fade=True)
                    timeline.clear_drop_track_feedback()
            except Exception as e:
                logger.info(f'clip trim commit failed: {e}')
                timeline = self._find_timeline_widget()
                if timeline is not None:
                    timeline.clear_snap_guide(fade=False)
                    timeline.clear_drop_track_feedback()

        timeline = self._find_timeline_widget()
        if timeline is not None:
            timeline.clear_drop_track_feedback()
            timeline.set_clip_interaction_active(False)
            if getattr(timeline, "_active_drag_clip", None) is self:
                timeline._active_drag_clip = None
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False
        self._edit_before = None
        self._batch_drag_starts = None
        super().mouseReleaseEvent(event)

    def cancel_edit_drag(self) -> bool:
        """Esc：放弃本次拖拽/trim，还原按下时的时间与轨。"""
        if not getattr(self, "_did_edit_drag", False) and getattr(
            self, "_drag_start_pos", None
        ) is None:
            return False
        timeline = self._find_timeline_widget()
        before = getattr(self, "_edit_before", None)
        batch_starts = getattr(self, "_batch_drag_starts", None)
        tracks0 = getattr(self, "_batch_drag_tracks0", None) or {}
        try:
            if batch_starts and timeline is not None and len(batch_starts) > 1:
                for cid, st0 in batch_starts.items():
                    clip = next(
                        (c for c in timeline._clips if c.get("id") == cid), None
                    )
                    w = next(
                        (cw for cw in timeline.all_clip_widgets()
                         if cw.clip_data.get("id") == cid),
                        None,
                    )
                    if clip is not None:
                        ti0 = int(tracks0.get(cid, clip.get("track", 0)) or 0)
                        timeline._write_clip_fields(clip, start_time=float(st0), track=ti0)
                    if w is not None:
                        w._write_fields(start_time=float(st0))
                        ti0 = int(tracks0.get(cid, w.clip_data.get("track", 0)) or 0)
                        if int(w.clip_data.get("track", -1) or -1) != ti0:
                            timeline.reparent_clip_to_track(w, ti0)
                        else:
                            w._write_fields(track=ti0)
                        timeline.position_clip_widget(w)
            elif before and isinstance(before, dict):
                restore = {k: before[k] for k in
                           ("start_time", "duration", "in_point", "out_point") if k in before}
                self._write_fields(**restore)
                ti0 = int(before.get("track", self.clip_data.get("track", 0)) or 0)
                self._write_fields(track=ti0)
                if timeline is not None:
                    if int(self.clip_data.get("track", -1) or -1) != ti0:
                        timeline.reparent_clip_to_track(self, ti0)
                    timeline.position_clip_widget(self)
        except Exception as e:
            logger.debug("还原拖拽状态失败: %s", e)
        if timeline is not None:
            try:
                timeline.clear_snap_guide(fade=False)
                timeline.clear_drop_track_feedback()
                timeline.set_clip_interaction_active(False)
                timeline._active_drag_clip = None
            except Exception:
                pass
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        self._resize_snapshot = None
        self._did_edit_drag = False
        self._edit_before = None
        self._batch_drag_starts = None
        self._batch_drag_tracks0 = None
        self.update()
        return True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.cancel_edit_drag():
                event.accept()
                return
        super().keyPressEvent(event)

    def set_selected(self, selected):
        self._is_selected = selected
        self.setProperty('selected', str(selected).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        # 补短 P1#8：选中态变化需重绘关键帧
        self.update()

    # ------------------------------------------------------------------
    # 补短 P1#8：内部辅助
    # ------------------------------------------------------------------
    def _format_keyframe_tooltip(self, kf):
        """关键帧 tooltip 文案：属性 @ 时间 = 值 (缓动)"""
        try:
            value = kf.get('value', 0.0)
            value_str = f"{float(value):.3f}".rstrip('0').rstrip('.')
        except Exception:
            value_str = str(value)
        t = kf.get('time_offset', 0.0)
        return (
            f"◆ {kf.get('prop', 'value')}\n"
            f"  @ {t:.2f}s = {value_str}\n"
            f"  easing: {kf.get('easing', 'linear')}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._is_audio_clip():
            self._request_thumbnail_refresh()

    def _source_in_out(self):
        """片段源时间窗 [in, out)。"""
        in_p = float(self.clip_data.get("in_point", 0) or 0)
        out_p = float(self.clip_data.get("out_point", 0) or 0)
        if out_p <= in_p + 1e-6:
            out_p = in_p + max(0.05, float(self.clip_data.get("duration", 10) or 10))
        return in_p, out_p

    def _filmstrip_cell_w(self, thumb_h: int = None) -> int:
        h = max(8, int(thumb_h if thumb_h is not None else (self.height() or 48)))
        aspect = float(getattr(self, "_thumb_aspect", 0) or 0) or (16.0 / 9.0)
        return max(14, int(round(h * aspect)))

    def _desired_thumb_count(self) -> int:
        cell_w = self._filmstrip_cell_w()
        w = max(1, int(self.width() or 1))
        return max(1, min(48, (w + cell_w - 1) // max(1, cell_w)))

    def _current_thumb_key(self):
        path = self._resolve_clip_media_path()
        in_p, out_p = self._source_in_out()
        n = self._desired_thumb_count()
        thumb_h = max(8, int(self.height() or 48))
        return (
            path,
            round(in_p, 3),
            round(out_p, 3),
            int(n),
            int(thumb_h),
        )

    def _should_wait_proxy_before_filmstrip(self) -> bool:
        """长视频在代理未就绪时先等一拍，避免与代理转码/预览抢开同一文件。"""
        if self._is_audio_clip():
            return False
        proxy = str(self.clip_data.get("proxy_path") or "")
        if proxy and os.path.isfile(proxy):
            return False
        if getattr(self, "_filmstrip_proxy_wait_done", False):
            return False
        dur = float(self.clip_data.get("duration", 0) or 0)
        # 短片 / 静图：不等代理
        if dur > 0 and dur < 12.0:
            return False
        ext = os.path.splitext(str(self.clip_data.get("path") or ""))[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"):
            return False
        return True

    def _on_filmstrip_proxy_wait_timeout(self):
        """代理等待结束：无论是否就绪都采一次（有代理则走代理路径）。"""
        self._filmstrip_proxy_wait_done = True
        try:
            self._request_thumbnail_refresh()
        except Exception as e:
            logger.debug("代理等待后采胶片失败: %s", e)

    def _request_thumbnail_refresh(self):
        """合并缩放/布局抖动后重采胶片条。"""
        if self._is_audio_clip():
            return
        if self._parent_track_collapsed():
            return
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_clip_interaction_active():
            return
        if timeline is not None and not timeline.is_clip_widget_visible(self):
            return  # 视口外懒加载，滚动后再采
        # 代理优先：长片先 defer，等 proxy_path 或超时后再采
        if self._should_wait_proxy_before_filmstrip():
            timer = getattr(self, "_filmstrip_proxy_timer", None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(2800)
                timer.timeout.connect(self._on_filmstrip_proxy_wait_timeout)
                self._filmstrip_proxy_timer = timer
            if not timer.isActive():
                timer.start()
            return
        timer = getattr(self, "_thumb_debounce", None)
        if timer is None:
            self._schedule_thumbnail_generation()
            return
        timer.start()

    def _schedule_thumbnail_generation(self):
        """按 in/out 均匀采样，异步生成剪映式胶片条。"""
        if self._is_audio_clip():
            self._thumbnails_generated = True
            return
        if self._parent_track_collapsed():
            return
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_clip_interaction_active():
            return
        if timeline is not None and not timeline.is_clip_widget_visible(self):
            return

        clip_path = self._resolve_clip_media_path()
        if not clip_path or not os.path.exists(clip_path):
            self._thumbnails_generated = True
            return

        ext = os.path.splitext(clip_path)[1].lower()
        if ext in AUDIO_EXTS:
            self._thumbnails_generated = True
            return

        key = self._current_thumb_key()
        if key == getattr(self, "_thumb_key", None) and self._thumbnail_cache:
            self._thumbnails_generated = True
            return

        # 停止旧 worker，避免结果乱序覆盖
        old = getattr(self, "_thumbnail_worker", None)
        if old is not None:
            try:
                old.thumbnails_ready.disconnect(self._on_thumbnails_ready)
            except Exception:
                pass
            try:
                if old.isRunning():
                    old.requestInterruption()
                    old.quit()
            except Exception as e:
                logger.debug("停止旧缩略图线程: %s", e)
            self._thumbnail_worker = None

        in_p, out_p = self._source_in_out()
        n = int(key[3])
        thumb_h = max(48, int(key[4]) * 2)  # 稍高分辨率，绘制再 scaledToHeight
        span = max(0.05, out_p - in_p)
        timestamps = [in_p + (i + 0.5) / n * span for i in range(n)]

        self._thumb_gen_token = int(getattr(self, "_thumb_gen_token", 0) or 0) + 1
        token = self._thumb_gen_token
        pending_key = key

        from PyQt6.QtCore import QThread, pyqtSignal

        class FilmstripWorker(QThread):
            thumbnails_ready = pyqtSignal(list, float)  # pixmaps, aspect

            def __init__(self, path, timestamps, height):
                super().__init__()
                self._path = path
                self._timestamps = list(timestamps)
                self._height = int(height)

            def run(self):
                thumbs, aspect = _extract_filmstrip_frames(
                    self._path, self._timestamps, self._height, self.isInterruptionRequested
                )
                if self.isInterruptionRequested():
                    return
                self.thumbnails_ready.emit(thumbs, aspect)

        # 排队中的旧请求（尚未真正 start）先撤销，避免同一 widget 占多个名额
        _media_worker_gate.cancel_owner(self)

        worker = FilmstripWorker(clip_path, timestamps, thumb_h)
        self._thumbnail_worker = worker
        worker.thumbnails_ready.connect(
            lambda thumbs, aspect, t=token, k=pending_key: self._on_thumbnails_ready(
                thumbs, aspect, token=t, key=k
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(_media_worker_gate.release)
        _media_worker_gate.request(self, worker.start)

    def _on_thumbnails_ready(self, thumbnails, aspect=0.0, token=None, key=None):
        """胶片条生成完成；丢弃过期 token。"""
        if token is not None and token != getattr(self, "_thumb_gen_token", None):
            return
        self._thumbnail_cache = list(thumbnails or [])
        if aspect and aspect > 0.05:
            self._thumb_aspect = float(aspect)
        elif self._thumbnail_cache:
            pm0 = self._thumbnail_cache[0]
            if pm0 is not None and not pm0.isNull() and pm0.height() > 0:
                self._thumb_aspect = float(pm0.width()) / float(pm0.height())
        if key is not None:
            self._thumb_key = key
        self._thumbnails_generated = True
        self._scaled_thumb_cache = {}
        self._scaled_thumb_cache_key = None
        self.update()

    def _resolve_clip_media_path(self) -> str:
        """解析片段媒体路径；胶片条优先代理（导出仍用 clip['path'] 原片）。"""
        # 预览/胶片条：代理就绪则用代理
        proxy = str(self.clip_data.get("proxy_path") or "")
        if proxy and os.path.isfile(proxy):
            return os.path.normpath(proxy)
        raw = self.clip_data.get("path", "") or ""
        if not raw:
            return ""
        if os.path.exists(raw):
            return raw
        candidates = [
            os.path.normpath(os.path.join(os.getcwd(), raw)),
            os.path.normpath(os.path.join(os.getcwd(), "app", raw)),
        ]
        # 从本文件位置推工程根
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
            candidates.append(os.path.normpath(os.path.join(project_root, raw)))
            candidates.append(os.path.normpath(os.path.join(project_root, "app", raw)))
        except Exception as e:
            logger.debug("解析片段媒体路径工程根失败: %s", e)
        for c in candidates:
            if c and os.path.exists(c):
                self.clip_data["path"] = c
                return c
        return raw

    def _on_clip_widget_destroyed(self, *_args):
        try:
            self._cleanup_workers()
        except Exception:
            pass

    def _parent_track_collapsed(self) -> bool:
        """所在轨道是否折叠（折叠轨不调度媒体后台任务）。"""
        try:
            timeline = self._find_timeline_widget()
            if timeline is None:
                return False
            ti = int(self.clip_data.get("track", 0) or 0)
            tracks = getattr(timeline, "_tracks", None) or []
            if 0 <= ti < len(tracks):
                return bool(tracks[ti].get("collapsed", False))
        except Exception:
            pass
        return False

    def sleep_media_workers(self):
        """折叠/休眠：停止缩略图与波形线程。

        注意：本函数的三步都**必须留痕**（不用裸 pass），原因：
          1. token 自增失败 → 旧缩略图任务回写覆盖新状态，表现为"拖动后缩略图错帧"；
          2. gate 取消失败 → worker 泄漏，轨道反复折叠/展开后线程越滚越多。
        两者都是"静默即难查"的类型，宁可日志吵也不要瞎。
        """
        try:
            if getattr(self, "_thumb_debounce", None) is not None:
                self._thumb_debounce.stop()
        except Exception as e:
            logger.debug("休眠：停止缩略图防抖失败: %s", e, exc_info=True)
        try:
            _media_worker_gate.cancel_owner(self)
        except Exception as e:
            logger.debug("休眠：取消媒体 worker 归属失败（可能泄漏 worker）: %s", e, exc_info=True)
        try:
            self._thumb_gen_token = int(getattr(self, "_thumb_gen_token", 0) or 0) + 1
        except Exception as e:
            # 这里吞掉会导致旧任务回写覆盖新状态，必须可见
            logger.debug("休眠：缩略图代际 token 自增失败（旧任务可能回写）: %s", e, exc_info=True)
        for attr in ("_thumbnail_worker", "_waveform_worker"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if hasattr(w, "requestInterruption"):
                    w.requestInterruption()
                if w.isRunning():
                    w.quit()
                    w.wait(500)
            except RuntimeError:
                # C++ 侧已析构（控件销毁时序），无需处理；下面统一清空引用。
                pass
            except Exception as e:
                logger.debug("停媒体 worker 失败: %s", e, exc_info=True)
            setattr(self, attr, None)
        self._waveform_scheduled = False
        self._scaled_thumb_cache = {}
        self._scaled_thumb_cache_key = None

    def wake_media_workers(self):
        """展开轨道后重新调度媒体预览。"""
        if self._parent_track_collapsed():
            return
        self._request_thumbnail_refresh()
        if self._is_audio_clip() and self._waveform_peaks is None and not self._waveform_failed:
            self._waveform_scheduled = False
            QTimer.singleShot(80, lambda: self._schedule_waveform_generation(200))

    def _schedule_waveform_generation(self, num_samples):
        """调度异步波形生成（防重入，仅音频片）。"""
        if not self._is_audio_clip():
            return
        if self._parent_track_collapsed():
            return
        timeline = self._find_timeline_widget()
        if timeline is not None and timeline.is_clip_interaction_active():
            return
        if timeline is not None and not timeline.is_clip_widget_visible(self):
            return
        if self._waveform_scheduled or self._waveform_peaks is not None or self._waveform_failed:
            return

        clip_path = self._resolve_clip_media_path()
        if not clip_path or not os.path.exists(clip_path):
            self._waveform_failed = True
            self._waveform_peaks = []
            self.update()
            return

        self._waveform_scheduled = True
        from PyQt6.QtCore import QThread, pyqtSignal
        
        class WaveformWorker(QThread):
            waveform_ready = pyqtSignal(list)
            
            def __init__(self, clip_path, num_samples):
                super().__init__()
                self._clip_path = clip_path
                self._num_samples = num_samples
            
            def run(self):
                try:
                    from app.core.waveform_generator import waveform_generator
                    data = waveform_generator.generate(self._clip_path, num_samples=self._num_samples)
                    if data and data.peaks and max(data.peaks) > 1e-6:
                        self.waveform_ready.emit(list(data.peaks))
                    else:
                        self.waveform_ready.emit([])
                except Exception as e:
                    logger.error(f"波形生成失败: {e}")
                    self.waveform_ready.emit([])
        
        _media_worker_gate.cancel_owner(self)

        self._waveform_worker = WaveformWorker(clip_path, num_samples)
        self._waveform_worker.waveform_ready.connect(self._on_waveform_ready)
        self._waveform_worker.finished.connect(self._waveform_worker.deleteLater)
        self._waveform_worker.finished.connect(_media_worker_gate.release)
        _media_worker_gate.request(self, self._waveform_worker.start)
    
    def _on_waveform_ready(self, peaks):
        """波形生成完成回调。空列表表示失败/无音轨。"""
        if peaks and max(peaks) > 1e-6:
            self._waveform_peaks = peaks
            self._waveform_failed = False
        else:
            self._waveform_peaks = []
            self._waveform_failed = True
        self.update()
    
    def _cleanup_workers(self):
        """清理所有工作线程 - 在widget销毁前调用"""
        try:
            _media_worker_gate.cancel_owner(self)
        except Exception:
            pass
        if hasattr(self, '_thumbnail_worker') and self._thumbnail_worker is not None:
            try:
                if self._thumbnail_worker.isRunning():
                    if hasattr(self._thumbnail_worker, 'requestInterruption'):
                        self._thumbnail_worker.requestInterruption()
                    self._thumbnail_worker.quit()
                    self._thumbnail_worker.wait(2000)
            except RuntimeError as e:
                logger.debug("停止缩略图工作线程失败: %s", e)
            self._thumbnail_worker = None
        if hasattr(self, '_waveform_worker') and self._waveform_worker is not None:
            try:
                if self._waveform_worker.isRunning():
                    if hasattr(self._waveform_worker, 'requestInterruption'):
                        self._waveform_worker.requestInterruption()
                    self._waveform_worker.quit()
                    self._waveform_worker.wait(2000)
            except RuntimeError as e:
                logger.debug("停止波形工作线程失败: %s", e)
            self._waveform_worker = None
    
    def closeEvent(self, event):
        """Widget关闭事件 - 确保工作线程安全终止"""
        self._cleanup_workers()
        super().closeEvent(event)
