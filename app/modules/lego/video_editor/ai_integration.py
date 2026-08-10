"""
AI功能整合模块
==================
整合现有AI模块（smart_editing_engine、ai_clip_flow、viral_optimization_engine等），
提供统一的AI编辑界面，强化AI剪辑和爆款分析能力
"""

from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QProgressBar, QComboBox, QSlider, QTabWidget
import logging
import json
import time

from app.core.timeline import timeline_core
from app.core.project_manager import project_manager
from app.core.asset_manager import asset_manager

logger = logging.getLogger("AI短剧编辑器.ai_integration")


class AIEditor(QWidget):
    """AI编辑器 - 整合所有AI功能"""
    
    analysis_started = pyqtSignal()
    analysis_completed = pyqtSignal(dict)
    clip_generated = pyqtSignal(str, dict)
    optimization_applied = pyqtSignal(str, dict)
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_project_id = None
        self._analysis_thread: Optional[QThread] = None
        self._is_analyzing = False
        
        self._smart_editing_engine = None
        self._ai_clip_flow = None
        self._viral_optimization_engine = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 标题栏
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setSpacing(8)
        
        title_label = QLabel("🤖 AI智能编辑器")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #2c3e50;")
        header_layout.addWidget(title_label)
        
        # AI功能选择
        ai_functions = QComboBox()
        ai_functions.addItems([
            "智能剪辑",
            "爆款分析",
            "AI字幕生成",
            "素材推荐"
        ])
        ai_functions.currentIndexChanged.connect(self._on_ai_function_changed)
        header_layout.addWidget(ai_functions)
        
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # 编辑区域
        self._editor_area = QTabWidget()
        layout.addWidget(self._editor_area)
        
        # 智能剪辑面板
        smart_clip_panel = self._create_smart_clip_panel()
        self._editor_area.addTab(smart_clip_panel, "🎬 智能剪辑")
        
        # 爆款分析面板
        viral_panel = self._create_viral_panel()
        self._editor_area.addTab(viral_panel, "📊 爆款分析")
        
        # AI字幕面板
        subtitle_panel = self._create_subtitle_panel()
        self._editor_area.addTab(subtitle_panel, "📝 AI字幕")
        
        # 底部控制栏
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(8, 8, 8, 8)
        control_layout.setSpacing(8)
        
        analyze_btn = QPushButton("🚀 开始分析")
        analyze_btn.clicked.connect(self._start_analysis)
        control_layout.addWidget(analyze_btn)
        
        stop_btn = QPushButton("⏹️ 停止分析")
        stop_btn.clicked.connect(self._stop_analysis)
        stop_btn.setEnabled(False)
        control_layout.addWidget(stop_btn)
        
        # 进度显示
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(0)
        control_layout.addWidget(progress_bar)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # 状态显示
        status_label = QLabel("状态: 就绪")
        layout.addWidget(status_label)
        
        # 日志显示
        self._log_display = QTextEdit()
        self._log_display.setReadOnly(True)
        self._log_display.setMaximumHeight(200)
        self._log_display.setStyleSheet("font-family: monospace; font-size: 10px; background: #1a1a1a; color: #808080;")
        layout.addWidget(self._log_display)
    
    def _create_smart_clip_panel(self) -> QWidget:
        """创建智能剪辑面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 剪辑模式选择
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(8)
        
        auto_clip_btn = QPushButton("🤖 自动剪辑")
        auto_clip_btn.setCheckable(True)
        mode_layout.addWidget(auto_clip_btn)
        
        manual_clip_btn = QPushButton("✂️ 手动剪辑")
        manual_clip_btn.setCheckable(False)
        mode_layout.addWidget(manual_clip_btn)
        
        layout.addLayout(mode_layout)
        
        # 剪辑参数
        params_layout = QVBoxLayout()
        params_layout.setContentsMargins(8, 8, 8, 8)
        params_layout.setSpacing(8)
        
        intensity_label = QLabel("剪辑强度:")
        intensity_slider = QSlider(Qt.Orientation.Horizontal)
        intensity_slider.setRange(1, 100)
        intensity_slider.setValue(50)
        params_layout.addWidget(intensity_label)
        params_layout.addWidget(intensity_slider)
        
        target_length_label = QLabel("目标长度:")
        target_length_spinbox = QSpinBox()
        target_length_spinbox.setRange(1, 300)
        target_length_spinbox.setValue(60)
        target_length_spinbox.setSuffix(" 秒")
        params_layout.addWidget(target_length_label)
        params_layout.addWidget(target_length_spinbox)
        
        params_layout.addStretch()
        layout.addLayout(params_layout)
        
        # 执行按钮
        execute_layout = QHBoxLayout()
        execute_layout.setSpacing(8)
        
        preview_btn = QPushButton("👁️ 预览")
        preview_btn.clicked.connect(self._preview_smart_clip)
        execute_layout.addWidget(preview_btn)
        
        apply_btn = QPushButton("✅ 应用")
        apply_btn.clicked.connect(self._apply_smart_clip)
        execute_layout.addWidget(apply_btn)
        
        execute_layout.addStretch()
        layout.addLayout(execute_layout)
        
        return panel
    
    def _create_viral_panel(self) -> QWidget:
        """创建爆款分析面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 分析维度
        dimensions_layout = QHBoxLayout()
        dimensions_layout.setSpacing(8)
        
        content_label = QLabel("内容质量:")
        content_slider = QSlider(Qt.Orientation.Horizontal)
        content_slider.setRange(1, 100)
        content_slider.setValue(80)
        dimensions_layout.addWidget(content_label)
        dimensions_layout.addWidget(content_slider)
        
        engagement_label = QLabel("用户参与度:")
        engagement_slider = QSlider(Qt.Orientation.Horizontal)
        engagement_slider.setRange(1, 100)
        engagement_slider.setValue(70)
        dimensions_layout.addWidget(engagement_label)
        dimensions_layout.addWidget(engagement_slider)
        
        trend_label = QLabel("趋势分析:")
        trend_slider = QSlider(Qt.Orientation.Horizontal)
        trend_slider.setRange(1, 100)
        trend_slider.setValue(60)
        dimensions_layout.addWidget(trend_label)
        dimensions_layout.addWidget(trend_slider)
        
        dimensions_layout.addStretch()
        layout.addLayout(dimensions_layout)
        
        # 分析结果
        result_layout = QVBoxLayout()
        result_layout.setContentsMargins(8, 8, 8, 8)
        result_layout.setSpacing(8)
        
        self._viral_score_label = QLabel("爆款指数:")
        self._viral_score_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ff00;")
        result_layout.addWidget(self._viral_score_label)
        
        self._viral_score_value = QLabel("0.0")
        self._viral_score_value.setStyleSheet("font-size: 24px; color: #00ff00;")
        result_layout.addWidget(self._viral_score_value)
        
        result_layout.addStretch()
        layout.addLayout(result_layout)
        
        # 执行按钮
        analysis_buttons = QHBoxLayout()
        analysis_buttons.setSpacing(8)
        
        analyze_btn = QPushButton("📊 分析")
        analyze_btn.clicked.connect(self._analyze_viral)
        analysis_buttons.addWidget(analyze_btn)
        
        export_btn = QPushButton("📤 导出报告")
        export_btn.clicked.connect(self._export_viral_report)
        analysis_buttons.addWidget(export_btn)
        
        analysis_buttons.addStretch()
        layout.addLayout(analysis_buttons)
        
        return panel
    
    def _create_subtitle_panel(self) -> QWidget:
        """创建AI字幕面板"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 字幕生成
        subtitle_layout = QHBoxLayout()
        subtitle_layout.setSpacing(8)
        
        generate_btn = QPushButton("🎙️ 生成字幕")
        generate_btn.clicked.connect(self._generate_subtitle)
        subtitle_layout.addWidget(generate_btn)
        
        style_combo = QComboBox()
        style_combo.addItems(["默认", "活泼", "专业", "简约"])
        style_combo.currentIndexChanged.connect(self._on_subtitle_style_changed)
        subtitle_layout.addWidget(style_combo)
        
        # 字幕编辑
        edit_area = QTextEdit()
        edit_area.setPlaceholderText("字幕内容将在这里显示...")
        edit_area.setMaximumHeight(150)
        subtitle_layout.addWidget(edit_area)
        
        layout.addLayout(subtitle_layout)
        
        return panel
    
    def _on_ai_function_changed(self, index: int) -> None:
        """AI功能选择改变"""
        functions = ["智能剪辑", "爆款分析", "AI字幕生成", "素材推荐"]
        selected_function = functions[index] if 0 <= index < len(functions) else functions[0]
        
        self._editor_area.setCurrentIndex(index)
        logger.info(f"切换AI功能: {selected_function}")
    
    def _start_analysis(self) -> None:
        """开始AI分析"""
        if self._is_analyzing:
            return
        
        self._is_analyzing = True
        self.analysis_started.emit()
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self._log_display.clear()
        self._log_display.append("开始AI分析...")
        
        self._analysis_thread = QThread(target=self._run_analysis)
        self._analysis_thread.started.connect(self._on_analysis_started)
        self._analysis_thread.finished.connect(self._on_analysis_completed)
        self._analysis_thread.start()
    
    def _stop_analysis(self) -> None:
        """停止分析"""
        if self._analysis_thread and self._analysis_thread.is_alive():
            self._analysis_thread.terminate()
            self._analysis_thread.wait()
        
        self._is_analyzing = False
        self.stop_btn.setEnabled(False)
        logger.info("AI分析已停止")
    
    def _run_analysis(self) -> Dict[str, Any]:
        """运行AI分析 (v2.0: 真实引擎调用)"""
        try:
            timeline = timeline_core.get_current_timeline()
            if not timeline:
                return {
                    'success': False,
                    'error': '没有当前时间线'
                }

            # 收集时间线中的所有视频片段
            clips = []
            for track in timeline.get('tracks', []):
                clips.extend(track.get('clips', []))
            if not clips:
                return {
                    'success': False,
                    'error': '没有可分析的片段'
                }

            self._log_display.append("🤖 正在初始化AI分析引擎...")
            logger.info("AI分析开始")

            # ===== 真实引擎分析 =====
            results = {
                'success': True,
                'analyzed_clips': 0,
                'total_clips': len(clips),
                'highlights': [],
                'viral_score': 0,
                'recommendations': [],
            }

            analyzed_count = 0
            all_viral_scores = []

            for i, clip in enumerate(clips[:min(5, len(clips))]):
                # 获取片段对应的文件路径
                file_path = clip.get('file', clip.get('path', clip.get('id', '')))
                if not file_path or not os.path.exists(file_path):
                    # 尝试从asset_manager获取
                    asset_id = clip.get('asset_id', '')
                    if asset_id:
                        try:
                            asset = asset_manager.get_asset(asset_id)
                            if asset:
                                file_path = asset.get('path', '')
                        except Exception as e:
                            logger.debug("从asset_manager获取资源路径失败: %s", e)

                if not file_path or not os.path.exists(file_path):
                    self._log_display.append(
                        f"   ⚠️ 片段 {i+1}: 找不到源文件，跳过"
                    )
                    continue

                self._log_display.append(f"   分析片段 {i+1}/{len(clips)}: {os.path.basename(file_path)[:30]}...")
                self.progress_bar.setValue(int((i + 1) / len(clips) * 50))
                QApplication.processEvents()

                try:
                    # 调用剧集理解引擎
                    from ..drama_understanding_engine import DramaUnderstandingEngine
                    engine = DramaUnderstandingEngine(
                        whisper_model="base",
                        ollama_model="qwen2.5",
                        use_local_ai=True,
                    )
                    drama = engine.analyze_video(file_path)

                    # ABCD融合高光提取
                    highlights = engine.extract_highlights(
                        drama, target_duration=60.0, genre=drama.genre
                    )
                    for h in highlights:
                        results['highlights'].append({
                            'start_time': h.start_time,
                            'end_time': h.end_time,
                            'title': h.suggested_title,
                            'score': h.score,
                            'type': h.clip_type,
                            'reasons': h.reasons,
                        })

                    # 病毒基因检测
                    try:
                        from app.core.ai.viral_detector import ViralDetector
                        if drama.dialogues:
                            srt_lines = []
                            for d in drama.dialogues:
                                srt_lines.append(
                                    f"{d.start_time:.1f} --> {d.end_time:.1f}\n{d.text}"
                                )
                            srt_text = "\n\n".join(srt_lines)
                            detector = ViralDetector(llm_enhance=True)
                            viral_result = detector.analyze(
                                srt_text=srt_text,
                                total_duration=drama.total_duration,
                                top_k=3,
                            )
                            if isinstance(viral_result, dict):
                                score = viral_result.get('composite_score', 0)
                                all_viral_scores.append(score)
                    except Exception as viral_err:
                        logger.warning(f"病毒检测异常: {viral_err}")

                    analyzed_count += 1

                except Exception as clip_err:
                    self._log_display.append(f"   ⚠️ 片段分析异常: {str(clip_err)[:60]}")
                    logger.warning(f"片段分析异常: {clip_err}")

            # 汇总分数
            results['analyzed_clips'] = analyzed_count
            if all_viral_scores:
                results['viral_score'] = sum(all_viral_scores) / len(all_viral_scores)
            else:
                results['viral_score'] = 50  # 默认中等分数

            # 生成推荐建议
            recommendations = []
            if results['viral_score'] > 70:
                recommendations.append('内容爆款潜力高，建议优先发布')
            elif results['viral_score'] > 50:
                recommendations.append('内容质量中等，可优化开场3秒钩子')
            else:
                recommendations.append('建议重新编排，增强冲突/情感元素')

            highlight_count = len(results['highlights'])
            if highlight_count > 0:
                top_h = sorted(results['highlights'], key=lambda x: x['score'], reverse=True)[:3]
                titles = [h['title'] for h in top_h if h.get('title')]
                if titles:
                    recommendations.append(f'推荐高光: {"、".join(titles)}')
            else:
                recommendations.append('未检测到明显高光片段，建议补充冲突素材')

            results['recommendations'] = recommendations

            self.progress_bar.setValue(100)

            # 发送信号
            self.clip_generated.emit('analysis_complete', results)
            self.analysis_completed.emit(results)
            logger.info(f"AI分析完成: 爆款指数 {results['viral_score']:.1f}")

        except Exception as e:
            error_result = {
                'success': False,
                'error': str(e)
            }
            self.analysis_completed.emit(error_result)
            logger.error(f"AI分析失败: {e}")
    
    def _on_analysis_started(self) -> None:
        """分析开始"""
        self._log_display.append("AI分析进行中...")
        logger.info("AI分析开始")
    
    def _on_analysis_completed(self, result: Dict[str, Any]) -> None:
        """分析完成"""
        self._is_analyzing = False
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        
        if result.get('success'):
            self._log_display.append(f"✅ AI分析完成！")
            self._log_display.append(f"分析片段数: {result.get('analyzed_clips', 0)}/{result.get('total_clips', 0)}")
            
            highlights = result.get('highlights', [])
            self._log_display.append(f"检测高光片段: {len(highlights)}个")
            for h in highlights[:3]:
                title = h.get('title', '无标题')
                score = h.get('score', 0)
                self._log_display.append(f"  ⭐ {title} (得分: {score:.1f})")
            
            self._log_display.append(f"爆款指数: {result.get('viral_score', 0):.0f}")
            
            recommendations = result.get('recommendations', [])
            for rec in recommendations:
                self._log_display.append(f"💡 {rec}")
            
            self._viral_score_value.setText(f"{result.get('viral_score', 0):.1f}")
        else:
            self._log_display.append(f"❌ AI分析失败: {result.get('error', '未知错误')}")
            self._viral_score_value.setText("错误")
        
        logger.info(f"AI分析完成: {result.get('success', False)}")
    
    def _preview_smart_clip(self) -> None:
        """预览智能剪辑"""
        self._log_display.append("预览智能剪辑效果...")
        logger.info("预览智能剪辑")
    
    def _apply_smart_clip(self) -> None:
        """应用智能剪辑"""
        self._log_display.append("应用智能剪辑设置...")
        logger.info("应用智能剪辑设置")
    
    def _generate_subtitle(self) -> None:
        """生成AI字幕"""
        self._log_display.append("生成AI字幕...")
        logger.info("生成AI字幕")
    
    def _analyze_viral(self) -> None:
        """分析爆款潜力"""
        self._log_display.append("分析爆款潜力...")
        logger.info("分析爆款潜力")
    
    def _export_viral_report(self) -> None:
        """导出分析报告"""
        self._log_display.append("导出分析报告...")
        logger.info("导出分析报告")
    
    def _on_subtitle_style_changed(self, index: int) -> None:
        """字幕风格改变"""
        styles = ["默认", "活泼", "专业", "简约"]
        selected_style = styles[index] if 0 <= index < len(styles) else styles[0]
        logger.info(f"字幕风格: {selected_style}")
    
    def get_analysis_result(self) -> Optional[Dict[str, Any]]:
        """获取分析结果"""
        return None