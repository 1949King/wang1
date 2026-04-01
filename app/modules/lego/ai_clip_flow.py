"""
AI剪辑流程模块 (AIClipFlowModule)
==================================
实现从素材到爆款视频的完整AI剪辑流程
基于用户提供的爆款视频剪辑指南
"""

import os
import json
import tempfile
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGroupBox, QFormLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit,
    QTabWidget, QTextEdit, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from .core import EventBus, EventType
from .video_processor import VideoProcessor, ExportSettings


@dataclass
class AutoClipSettings:
    """AutoClip设置"""
    duration: int  # 视频时长
    platform: str  # 平台
    highlight_ratio: Dict[str, int]  # 高光比例
    force_strong_conflict: bool  # 强制前3秒强冲突
    remove_redundant: bool  # 剔除冗余剧情
    quick_cut: bool  # 快速卡点组接
    transition: str  # 转场类型
    category: str  # 品类


@dataclass
class FunClipSettings:
    """FunClip设置"""
    platform: str  # 平台
    bgm_type: str  # BGM类型
    bgm_volume: float  # BGM音量
    video_volume: float  # 视频音量
    subtitle_font: str  # 字幕字体
    subtitle_style: str  # 字幕样式
    subtitle_position: str  # 字幕位置
    add_narration: bool  # 添加旁白
    add_sound_effects: bool  # 添加音效


@dataclass
class VideoFusionSettings:
    """VideoFusion设置"""
    platform: str  # 平台
    video_type: str  # 视频类型
    enhance_4k: bool  # 4K增强
    skin_correction: bool  # 肤色矫正
    dynamic_stabilization: bool  # 动态防抖
    line_sharpening: bool  # 线条锐化
    saturation_boost: bool  # 饱和度提升
    noise_removal: bool  # 噪点去除
    aspect_ratio: str  # 画面比例
    export_format: str  # 导出格式


@dataclass
class LoRASettings:
    """LoRA Edit设置"""
    copyright_detection: bool  # 版权检测
    star_face_replacement: bool  # 明星脸替换
    logo_blur: bool  # Logo遮挡
    bgm_replacement: bool  # BGM替换
    traffic_sticker: bool  # 引流贴纸
    sticker_position: str  # 贴纸位置
    sticker_size: float  # 贴纸大小
    sticker_opacity: float  # 贴纸透明度
    sticker_start_time: float  # 贴纸开始时间


@dataclass
class CoverTitleSettings:
    """封面标题设置"""
    category: str  # 品类
    platform: str  # 平台
    cover_prompt: str  # 封面提示词
    title_type: str  # 标题类型
    title_prompt: str  # 标题提示词
    hashtags: List[str]  # 话题标签


class AIClipFlowModule(QWidget):
    """AI剪辑流程模块"""
    
    module_id = "ai_clip_flow"
    module_name = "AI剪辑流程"
    module_icon = "🎬"
    
    def __init__(self):
        super().__init__()
        self._event_bus = EventBus.get_instance()
        self._video_processor = VideoProcessor()
        self._current_video = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # 标题
        header = QLabel("🎬 AI剪辑流程 - 爆款视频生成")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)
        
        # 视频导入
        import_group = QGroupBox("视频导入")
        import_layout = QHBoxLayout(import_group)
        
        self._video_path = QLineEdit()
        self._video_path.setPlaceholderText("选择要剪辑的视频文件")
        self._video_path.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 8px;")
        import_layout.addWidget(self._video_path, 1)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        browse_btn.clicked.connect(self._browse_video)
        import_layout.addWidget(browse_btn)
        
        layout.addWidget(import_group)
        
        # 流程步骤
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #0a0a0a;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #808080;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                color: #1e6bde;
                background-color: #0a0a0a;
                border-bottom: 2px solid #1e6bde;
            }
            QTabBar::tab:hover:!selected {
                color: #ffffff;
            }
        """)
        
        # 步骤1: AutoClip
        self._autoclip_tab = self._create_autoclip_tab()
        self._tabs.addTab(self._autoclip_tab, "1️⃣ AutoClip 高光剪辑")
        
        # 步骤2: FunClip
        self._funclip_tab = self._create_funclip_tab()
        self._tabs.addTab(self._funclip_tab, "2️⃣ FunClip 精剪升级")
        
        # 步骤3: VideoFusion
        self._videofusion_tab = self._create_videofusion_tab()
        self._tabs.addTab(self._videofusion_tab, "3️⃣ VideoFusion 画质优化")
        
        # 步骤4: LoRA Edit
        self._lora_tab = self._create_lora_tab()
        self._tabs.addTab(self._lora_tab, "4️⃣ LoRA Edit 合规引流")
        
        # 步骤5: 封面标题
        self._cover_title_tab = self._create_cover_title_tab()
        self._tabs.addTab(self._cover_title_tab, "5️⃣ 封面标题生成")
        
        layout.addWidget(self._tabs)
        
        # 开始按钮
        start_btn = QPushButton("🚀 开始AI剪辑流程")
        start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """)
        start_btn.clicked.connect(self._start_clip_flow)
        layout.addWidget(start_btn)
    
    def _browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)"
        )
        if file_path:
            self._video_path.setText(file_path)
            self._current_video = file_path
    
    def _create_autoclip_tab(self) -> QWidget:
        """创建AutoClip设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 平台选择
        platform_group = QGroupBox("平台设置")
        platform_layout = QFormLayout(platform_group)
        
        self._autoclip_platform = QComboBox()
        self._autoclip_platform.addItems(["抖音", "快手", "小红书", "视频号"])
        self._autoclip_platform.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        platform_layout.addRow("目标平台:", self._autoclip_platform)
        
        # 时长设置
        self._autoclip_duration = QSpinBox()
        self._autoclip_duration.setRange(15, 40)
        self._autoclip_duration.setValue(20)
        self._autoclip_duration.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        platform_layout.addRow("视频时长 (秒):", self._autoclip_duration)
        
        layout.addWidget(platform_group)
        
        # 高光设置
        highlight_group = QGroupBox("高光识别设置")
        highlight_layout = QVBoxLayout(highlight_group)
        
        self._force_conflict = QCheckBox("前3秒强制识别强冲突画面")
        self._force_conflict.setChecked(True)
        self._force_conflict.setStyleSheet("color: #ffffff;")
        highlight_layout.addWidget(self._force_conflict)
        
        self._remove_redundant = QCheckBox("剔除冗余剧情")
        self._remove_redundant.setChecked(True)
        self._remove_redundant.setStyleSheet("color: #ffffff;")
        highlight_layout.addWidget(self._remove_redundant)
        
        # 高光比例
        ratio_layout = QHBoxLayout()
        ratio_layout.addWidget(QLabel("高光比例:"))
        
        self._core_conflict = QSpinBox()
        self._core_conflict.setRange(50, 90)
        self._core_conflict.setValue(70)
        self._core_conflict.setSuffix("%")
        self._core_conflict.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 4px;")
        ratio_layout.addWidget(QLabel("核心冲突:"))
        ratio_layout.addWidget(self._core_conflict)
        
        self._emotion_padding = QSpinBox()
        self._emotion_padding.setRange(10, 40)
        self._emotion_padding.setValue(20)
        self._emotion_padding.setSuffix("%")
        self._emotion_padding.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 4px;")
        ratio_layout.addWidget(QLabel("情绪铺垫:"))
        ratio_layout.addWidget(self._emotion_padding)
        
        self._suspense_end = QSpinBox()
        self._suspense_end.setRange(5, 20)
        self._suspense_end.setValue(10)
        self._suspense_end.setSuffix("%")
        self._suspense_end.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 4px;")
        ratio_layout.addWidget(QLabel("悬念结尾:"))
        ratio_layout.addWidget(self._suspense_end)
        
        highlight_layout.addLayout(ratio_layout)
        
        layout.addWidget(highlight_group)
        
        # 镜头组接
