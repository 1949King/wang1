# -*- coding: utf-8 -*-
"""editor_ai_tools_mixin.py
============================
EditorAiToolsMixin: 从 editor_module.py 抽出的「纯 AI 工具按钮回调」方法。

承载: AI 生成/增强入口、AI 进度信号、数据闭环、角色偏好、Ollama 诊断、
漫剧/横屏导出预设、五维打分展示、剪辑脚本导入导出。
均为独立按钮回调或轻量辅助，不直接写 `_clips` 核心状态机，不触碰
playback-av / canvas-transform / clip-transform 冻结区。

迁移的方法（共 22 个, 约 297 行）。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QListWidget, QListWidgetItem, QCheckBox, QFileDialog, QMessageBox,
    QApplication,
)

# 爆款优化引擎（懒加载，失败降级，与 editor_module 顶部逻辑保持一致）
try:
    from .viral_optimization_engine import ViralOptimizationEngine, Platform, VideoFeatures
    VIRAL_ENGINE_AVAILABLE = True
except ImportError as e:
    ViralOptimizationEngine = None  # type: ignore
    Platform = VideoFeatures = None  # type: ignore
    VIRAL_ENGINE_AVAILABLE = False

logger = logging.getLogger("AI短剧编辑器.editor")


def _clear_msgbox(title: str, message: str, parent=None):
    """延迟导入 modules.show_clear_messagebox 后调用，避免循环导入。"""
    from .modules import show_clear_messagebox
    return show_clear_messagebox(title, message, parent)


class EditorAiToolsMixin:
    """AI 工具按钮回调 Mixin: 承载 AI 生成/增强/数据闭环/角色/诊断/打分/脚本。"""

    # 抽取自 editor_module.py L719-730
    def _ensure_viral_engine(self):
        """懒加载爆款引擎"""
        if self._viral_initialized:
            return self._viral_engine
        self._viral_initialized = True
        if VIRAL_ENGINE_AVAILABLE:
            try:
                self._viral_engine = ViralOptimizationEngine()
                logger.info('✅ 爆款优化引擎已加载')
            except Exception as e:
                logger.error(f'⚠️ 爆款优化引擎初始化失败: {e}')
        return self._viral_engine

    # 抽取自 editor_module.py L732-744
    def _ensure_ai_clip_algorithm(self):
        """懒加载AI剪辑算法（避免顶层导入 PyQt6 重模块引发循环依赖）。"""
        if getattr(self, "_ai_clip_initialized", False):
            return getattr(self, "_ai_clip_algorithm", None)
        self._ai_clip_initialized = True
        try:
            from app.modules.lego.modules import AIClipAlgorithm
            self._ai_clip_algorithm = AIClipAlgorithm()
            logger.info('✅ 智能剪辑算法已加载')
        except Exception as _e:
            logger.warning("AIClipAlgorithm 加载失败: %s", _e)
            self._ai_clip_algorithm = None
        return self._ai_clip_algorithm

    # 抽取自 editor_module.py L4218-4220
    def _generate_ai_subtitles(self):
        from app.modules.lego.editor_subtitle_panel import generate_ai_subtitles
        generate_ai_subtitles(self)

    # 抽取自 editor_module.py L4239-4244
    def _emit_ai_progress(self, value, message):
        """从后台线程安全地发射进度信号"""
        try:
            self.ai_progress_signal.emit(value, message)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    # 抽取自 editor_module.py L4246-4251
    def _emit_ai_fail(self, message):
        """从后台线程安全地发射失败信号"""
        try:
            self.ai_fail_signal.emit(message)
        except Exception as _e:
            logger.warning("操作异常（已忽略）: %s", _e)

    # 抽取自 editor_module.py L4285-4288
    def connect_to_data_analyzer(self):
        """连接到数据分析器"""
        from .data_analyzer import get_data_analyzer
        self._data_analyzer = get_data_analyzer()

    # 抽取自 editor_module.py L4290-4294
    def get_recommendations(self):
        """获取推荐策略"""
        if hasattr(self, '_data_analyzer'):
            return self._data_analyzer.get_recommendations("douyin")
        return {}

    # 抽取自 editor_module.py L4296-4305
    def record_edit_action(self, action_type, data):
        """记录编辑操作（用于数据回流）"""
        if hasattr(self, '_data_analyzer'):
            record = {
                "timestamp": datetime.now().isoformat(),
                "action_type": action_type,
                "data": data,
                "clip_count": len(self._clips)
            }
            self._data_analyzer._record_workflow(record)

    # 抽取自 editor_module.py L4308-4325
    def enhance_with_ai(self):
        """使用AI增强视频"""
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        
        video_path = self._clips[0]['path']
        
        from app.core.ai_engine import AIEngine
        ai_engine = AIEngine.get_instance()
        
        result = ai_engine.enhance_video(video_path)
        
        if result.get("success"):
            enhanced_path = result.get("output_path")
            if enhanced_path and os.path.exists(enhanced_path):
                self._load_video(enhanced_path)
                QMessageBox.information(self, "AI增强完成", "视频已完成AI增强")

    # 抽取自 editor_module.py L4327-4345
    def smart_cut_with_ai(self):
        """AI智能剪辑"""
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return
        
        video_path = self._clips[0]['path']
        
        from app.core.ai_engine import AIEngine
        ai_engine = AIEngine.get_instance()
        
        result = ai_engine.smart_cut(video_path, duration=60)
        
        if result.get("success"):
            clips = result.get("clips", [])
            for clip in clips:
                if clip.get("path"):
                    self._add_clip_to_timeline(clip["path"])
            QMessageBox.information(self, "AI剪辑完成", f"已生成 {len(clips)} 个片段")

    # 抽取自 editor_module.py L5366-5377
    def _bind_character_row_events(self, name: str, keep_check: QCheckBox,
                                   slider, pct_label):
        """绑定角色行的交互事件"""
        def _on_keep_changed(checked):
            self._write_character_pref(name, bool(checked), slider.value() / 100.0)

        def _on_weight_changed(val):
            pct_label.setText(f"{val}%")
            self._write_character_pref(name, keep_check.isChecked(), val / 100.0)

        keep_check.toggled.connect(_on_keep_changed)
        slider.valueChanged.connect(_on_weight_changed)

    # 抽取自 editor_module.py L5379-5389
    def _write_character_pref(self, name: str, keep: bool, weight: float):
        """写回角色偏好到 AnalysisCache"""
        try:
            from .character_cache import AnalysisCache
            cache = AnalysisCache()
            video_path = getattr(self, "_video_source", None)
            if not video_path:
                return
            cache.set_character_pref(video_path, name, keep=keep, weight=float(weight))
        except Exception as e:
            logger.error(f'   ⚠️ 角色偏好写入失败: {e}')

    # 抽取自 editor_module.py L5391-5393
    def _create_ai_tools_tab(self) -> QWidget:
        from app.modules.lego.editor_ai_panel import build_ai_panel_tab
        return build_ai_panel_tab(self)

    # 抽取自 editor_module.py L5395-5406
    def _record_ai_tool_history(self, text: str):
        """把 AI 工具处理结果写入「处理历史」列表（此前控件创建后从未写入，永远是空的）"""
        history_list = getattr(self, "_ai_history_list", None)
        if history_list is None:
            return
        try:
            from datetime import datetime
            history_list.insertItem(0, f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
            while history_list.count() > 50:
                history_list.takeItem(history_list.count() - 1)
        except Exception:
            pass

    # 抽取自 editor_module.py L5409-5439
    def _refresh_ollama_diagnose_ui(self):
        """把 Ollama diagnose() 摘要显示在 AI 页。"""
        label = getattr(self, "_ollama_status_label", None)
        if label is None:
            return
        try:
            from app.modules.lego.ollama_client import ollama_client
            report = ollama_client.diagnose()
            self._last_ollama_report = report
            if report.get("service_running"):
                models = ollama_client.list_models()
                n = len(models or [])
                label.setText(f"● 运行中 · {report.get('base_url','')} · 模型 {n} 个")
                label.setStyleSheet("color:#22c55e;font-size:10px;font-weight:600;")
                if n == 0:
                    label.setText(
                        f"● 运行中但无模型 · {report.get('base_url','')} · 请 ollama pull <模型>"
                    )
                    label.setStyleSheet("color:#f59e0b;font-size:10px;font-weight:600;")
            elif not report.get("installed"):
                label.setText("● 未安装 · " + (report.get("suggestion") or "请安装 Ollama")[:80])
                label.setStyleSheet("color:#ef4444;font-size:10px;")
            else:
                err = report.get("error") or "服务未运行"
                label.setText(f"● 未运行 · {err}")
                label.setStyleSheet("color:#ef4444;font-size:10px;")
            tip = ollama_client.format_diagnose_report(report)
            label.setToolTip(tip)
        except Exception as e:
            label.setText(f"● 诊断失败: {e}")
            label.setStyleSheet("color:#f59e0b;font-size:10px;")

    # 抽取自 editor_module.py L5441-5448
    def _show_ollama_diagnose_detail(self):
        """弹窗展示完整 diagnose() 文案。"""
        try:
            from app.modules.lego.ollama_client import ollama_client
            msg = ollama_client.diagnose_user_message()
        except Exception as e:
            msg = f"诊断失败: {e}"
        QMessageBox.information(self, "Ollama 诊断", msg)

    # 抽取自 editor_module.py L5696-5706
    def _apply_manju_portrait_preset(self) -> None:
        """一键漫剧竖屏：抖音系 9:16 / 1080x1920。"""
        self._apply_export_video_preset(
            platform="抖音",
            resolution="1080x1920",
            aspect="9:16",
            bitrate="5000k",
            fps="30fps",
            output_mode="漫剧竖屏快切",
        )
        self._notify_edit("已套用漫剧竖屏：1080×1920 · 9:16（导出等比+黑边）")

    # 抽取自 editor_module.py L5708-5718
    def _apply_landscape_preset(self) -> None:
        """一键横屏：B站系 16:9 / 1920x1080。"""
        self._apply_export_video_preset(
            platform="B站",
            resolution="1920x1080",
            aspect="16:9",
            bitrate="5000k",
            fps="30fps",
            output_mode="B站横屏长视频",
        )
        self._notify_edit("已套用横屏：1920×1080 · 16:9（导出等比+黑边）")

    # 抽取自 editor_module.py L8128-8153
    def _build_agent_score_card(self, parent_layout: QVBoxLayout):
        """构造五维打分结果卡。"""
        card = QFrame()
        card.setObjectName("agentScoreCard")
        card.setStyleSheet("QFrame#agentScoreCard{background:#0d1217;border:1px solid #1f4d7a;border-radius:10px;}")
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        t = QLabel("📊 五维打分结果")
        t.setStyleSheet("color:#58a6ff;font-size:12px;font-weight:700;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)

        self._agent_score_list = QListWidget()
        self._agent_score_list.setFixedHeight(110)
        self._agent_score_list.setStyleSheet(
            "QListWidget{background:#0f1117;color:#c9d1d9;border:1px solid #21262d;border-radius:6px;font-size:11px;}"
            "QListWidget::item{padding:4px 8px;}")
        lay.addWidget(self._agent_score_list)

        self._agent_score_card = card
        parent_layout.addWidget(card)

    # 抽取自 editor_module.py L8155-8199
    def _render_score_results(self, scored_results: List[Dict[str, Any]]):
        """把五维打分结果渲染到打分卡。"""
        lst = getattr(self, "_agent_score_list", None)
        card = getattr(self, "_agent_score_card", None)
        if lst is None or card is None:
            return
        lst.clear()
        if not scored_results:
            card.setVisible(False)
            return
        grade_color = {"S": "#ffd700", "A": "#7ee787", "B": "#d29922", "C": "#fb8500", "D": "#ff7b72"}
        for idx, sc in enumerate(scored_results, 1):
            grade = sc.get("grade", "C")
            color = grade_color.get(grade, "#c9d1d9")
            score = sc.get("weighted_score", 0.0)
            cid = sc.get("clip_id", f"#{idx}")
            drop = sc.get("should_drop", False)
            dims = sc.get("dimensions", {}) or {}
            q = dims.get("画面质量", dims.get("visual_quality", 0))
            n = dims.get("高光叙事价值", dims.get("narrative_highlight",
                  dims.get("narrative_value", 0)))
            s_ = dims.get("文案匹配度", dims.get("copy_match", 0))
            b = dims.get("BGM适配度", dims.get("bgm_match",
                  dims.get("bgm_fit", 0)))
            d_ = dims.get("镜头时长合理性", dims.get("shot_duration",
                   dims.get("duration_reasonable", 0)))
            drop_tag = "  ⚠️ 已剔除" if drop else ""
            # 修复：缺 quality_scores 时各维度用固定 70 分基线填充（避免误判 D
            # 级），但此前 UI 完全不标注，用户会把基线分当成真实 AI 质检结果。
            estimated = sc.get("estimated_dims") or []
            est_tag = f'  <span style="color:#d29922;">（{len(estimated)}/5维为估算基线）</span>' if estimated else ""
            html = (f'<span style="color:{color};font-weight:800;">[{grade}]</span> '
                    f'<span style="color:#e6edf3;">镜头{idx} {cid}</span>  '
                    f'<span style="color:{color};font-weight:700;">{score:.1f}分</span>  '
                    f'<span style="color:#8b949e;">(画面{q:.0f}/叙事{n:.0f}/文案{s_:.0f}/BGM{b:.0f}/时长{d_:.0f})</span>'
                    f'<span style="color:#ff7b72;">{drop_tag}</span>{est_tag}')
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, sc)
            lbl = QLabel(html)
            lbl.setStyleSheet("background:transparent;")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lst.addItem(it)
            lst.setItemWidget(it, lbl)
            it.setSizeHint(lbl.sizeHint())
        card.setVisible(True)

    # 抽取自 editor_module.py L8205-8217
    def _on_copy_script_clicked(self):
        """复制当前剪辑脚本为 JSON 到剪贴板。"""
        script = getattr(self, "_last_editing_script", None)
        if not script:
            QMessageBox.information(self, "复制脚本", "暂无可用的剪辑脚本。")
            return
        try:
            import json
            text = json.dumps(script, ensure_ascii=False, indent=2)
            QApplication.clipboard().setText(text)
            self._append_agent_message("系统", "剪辑脚本 JSON 已复制到剪贴板。")
        except Exception as e:
            QMessageBox.warning(self, "复制失败", str(e))

    # 抽取自 editor_module.py L8219-8236
    def _on_export_script_clicked(self):
        """导出当前剪辑脚本到 JSON 文件（父窗口传 self，符合 PyQt6 弹窗铁律）。"""
        script = getattr(self, "_last_editing_script", None)
        if not script:
            QMessageBox.information(self, "导出脚本", "暂无可用的剪辑脚本。")
            return
        try:
            import json
            path, _ = QFileDialog.getSaveFileName(
                self, "导出剪辑脚本", "editing_script.json", "JSON Files (*.json)"
            )
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            self._append_agent_message("系统", f"剪辑脚本已导出：{path}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))

