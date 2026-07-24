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

    def _browse_bgm(self):
        """选择 BGM 音频文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择BGM音频文件", "",
            "音频文件 (*.mp3 *.wav *.aac *.m4a *.flac *.ogg)"
        )
        if file_path:
            self._bgm_file_input.setText(file_path)
            self._bgm_file = file_path
    
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
        edit_group = QGroupBox("剪辑参数")
        edit_layout = QVBoxLayout(edit_group)
        
        self._quick_cut = QCheckBox("快速卡点组接")
        self._quick_cut.setChecked(True)
        self._quick_cut.setStyleSheet("color: #ffffff;")
        edit_layout.addWidget(self._quick_cut)
        
        trans_layout = QHBoxLayout()
        trans_layout.addWidget(QLabel("转场类型:"))
        trans_layout.addStretch()
        self._autoclip_transition = QComboBox()
        self._autoclip_transition.addItems(["闪白", "淡入淡出", "缩放", "滑动", "无"])
        self._autoclip_transition.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px; min-width: 120px;")
        trans_layout.addWidget(self._autoclip_transition)
        edit_layout.addLayout(trans_layout)
        
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("视频品类:"))
        cat_layout.addStretch()
        self._autoclip_category = QComboBox()
        self._autoclip_category.addItems(["短剧", "Vlog", "美食", "美妆", "知识", "搞笑", "影视剪辑"])
        self._autoclip_category.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px; min-width: 120px;")
        cat_layout.addWidget(self._autoclip_category)
        edit_layout.addLayout(cat_layout)
        
        layout.addWidget(edit_group)
        layout.addStretch()
        return widget
    
    def _create_funclip_tab(self) -> QWidget:
        """创建FunClip精剪升级标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 平台
        plat_group = QGroupBox("平台设置")
        plat_layout = QFormLayout(plat_group)
        self._funclip_platform = QComboBox()
        self._funclip_platform.addItems(["抖音", "快手", "小红书", "视频号"])
        self._funclip_platform.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        plat_layout.addRow("目标平台:", self._funclip_platform)
        layout.addWidget(plat_group)
        
        # BGM
        bgm_group = QGroupBox("BGM 设置")
        bgm_layout = QFormLayout(bgm_group)
        self._funclip_bgm = QComboBox()
        self._funclip_bgm.addItems(["情感叙事", "节奏卡点", "轻快活泼", "悬疑紧张", "史诗大气", "无BGM"])
        self._funclip_bgm.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        bgm_layout.addRow("BGM 类型:", self._funclip_bgm)

        # BGM 文件选择（手动选择背景音乐文件）
        bgm_file_row = QHBoxLayout()
        bgm_file_row.setSpacing(6)
        self._bgm_file_input = QLineEdit()
        self._bgm_file_input.setPlaceholderText("选择BGM音频文件（可选，留空使用内置BGM库）")
        self._bgm_file_input.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        bgm_file_row.addWidget(self._bgm_file_input, 1)
        bgm_browse_btn = QPushButton("📁")
        bgm_browse_btn.setFixedWidth(36)
        bgm_browse_btn.setStyleSheet("QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:4px;}QPushButton:hover{background:#3a3a3a;}")
        bgm_browse_btn.clicked.connect(lambda: self._browse_bgm())
        bgm_file_row.addWidget(bgm_browse_btn)
        bgm_layout.addRow("BGM 文件:", bgm_file_row)
        
        self._funclip_bgm_vol = QDoubleSpinBox()
        self._funclip_bgm_vol.setRange(0.1, 1.0)
        self._funclip_bgm_vol.setSingleStep(0.1)
        self._funclip_bgm_vol.setValue(0.3)
        self._funclip_bgm_vol.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        bgm_layout.addRow("BGM 音量:", self._funclip_bgm_vol)
        
        self._funclip_video_vol = QDoubleSpinBox()
        self._funclip_video_vol.setRange(0.1, 1.0)
        self._funclip_video_vol.setSingleStep(0.1)
        self._funclip_video_vol.setValue(0.8)
        self._funclip_video_vol.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        bgm_layout.addRow("原声音量:", self._funclip_video_vol)
        layout.addWidget(bgm_group)
        
        # 字幕
        sub_group = QGroupBox("字幕设置")
        sub_layout = QFormLayout(sub_group)
        self._funclip_font = QComboBox()
        self._funclip_font.addItems(["默认", "黑体", "微软雅黑", "楷体", "圆体"])
        self._funclip_font.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        sub_layout.addRow("字幕字体:", self._funclip_font)
        self._funclip_sub_style = QComboBox()
        self._funclip_sub_style.addItems(["底部居中", "逐字弹出", "卡拉OK", "描边强调"])
        self._funclip_sub_style.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        sub_layout.addRow("字幕样式:", self._funclip_sub_style)
        layout.addWidget(sub_group)
        
        # 音效
        fx_group = QGroupBox("音效增强")
        fx_layout = QVBoxLayout(fx_group)
        self._funclip_narration = QCheckBox("AI 旁白解说")
        self._funclip_narration.setStyleSheet("color: #ffffff;")
        fx_layout.addWidget(self._funclip_narration)
        self._funclip_sfx = QCheckBox("智能音效（掌声/笑声/紧张音等）")
        self._funclip_sfx.setChecked(True)
        self._funclip_sfx.setStyleSheet("color: #ffffff;")
        fx_layout.addWidget(self._funclip_sfx)
        layout.addWidget(fx_group)
        layout.addStretch()
        return widget
    
    def _create_videofusion_tab(self) -> QWidget:
        """创建VideoFusion画质优化标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        plat_group = QGroupBox("平台设置")
        plat_layout = QFormLayout(plat_group)
        self._vf_platform = QComboBox()
        self._vf_platform.addItems(["抖音", "快手", "小红书", "视频号"])
        self._vf_platform.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        plat_layout.addRow("目标平台:", self._vf_platform)
        self._vf_video_type = QComboBox()
        self._vf_video_type.addItems(["短剧", "Vlog", "开箱", "教程"])
        self._vf_video_type.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        plat_layout.addRow("视频类型:", self._vf_video_type)
        layout.addWidget(plat_group)
        
        enhance_group = QGroupBox("画质增强")
        enhance_layout = QVBoxLayout(enhance_group)
        self._vf_4k = QCheckBox("4K 超分辨率增强")
        self._vf_4k.setStyleSheet("color: #ffffff;")
        enhance_layout.addWidget(self._vf_4k)
        self._vf_skin = QCheckBox("肤色矫正")
        self._vf_skin.setChecked(True)
        self._vf_skin.setStyleSheet("color: #ffffff;")
        enhance_layout.addWidget(self._vf_skin)
        self._vf_stabilize = QCheckBox("动态防抖")
        self._vf_stabilize.setChecked(True)
        self._vf_stabilize.setStyleSheet("color: #ffffff;")
        enhance_layout.addWidget(self._vf_stabilize)
        self._vf_sharpen = QCheckBox("线条锐化")
        self._vf_sharpen.setChecked(True)
        self._vf_sharpen.setStyleSheet("color: #ffffff;")
        enhance_layout.addWidget(self._vf_sharpen)
        self._vf_saturation = QCheckBox("饱和度提升")
        self._vf_saturation.setStyleSheet("color: #ffffff;")
        enhance_layout.addWidget(self._vf_saturation)
        self._vf_denoise = QCheckBox("噪点去除")
        self._vf_denoise.setChecked(True)
        self._vf_denoise.setStyleSheet("color: #ffffff;")
        enhance_layout.addWidget(self._vf_denoise)
        layout.addWidget(enhance_group)
        
        export_group = QGroupBox("导出设置")
        export_layout = QFormLayout(export_group)
        self._vf_aspect = QComboBox()
        self._vf_aspect.addItems(["9:16 竖屏", "16:9 横屏", "1:1 方形", "4:5"])
        self._vf_aspect.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        export_layout.addRow("画面比例:", self._vf_aspect)
        self._vf_format = QComboBox()
        self._vf_format.addItems(["MP4 (H.264)", "MP4 (H.265)", "MOV", "AVI"])
        self._vf_format.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        export_layout.addRow("导出格式:", self._vf_format)
        layout.addWidget(export_group)
        layout.addStretch()
        return widget
    
    def _create_lora_tab(self) -> QWidget:
        """创建LoRA Edit合规引流标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        info = QLabel("此步骤用于规避平台查重机制，通过画面微调和引流元素提升曝光")
        info.setStyleSheet("color: #808080; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        protect_group = QGroupBox("合规保护")
        protect_layout = QVBoxLayout(protect_group)
        self._lora_copyright = QCheckBox("版权检测（自动识别受保护音乐/画面并替换）")
        self._lora_copyright.setChecked(True)
        self._lora_copyright.setStyleSheet("color: #ffffff;")
        protect_layout.addWidget(self._lora_copyright)
        self._lora_face = QCheckBox("明星脸替换（AI 生成相似路人脸代替）")
        self._lora_face.setStyleSheet("color: #ff9800;")
        protect_layout.addWidget(self._lora_face)
        self._lora_logo = QCheckBox("Logo 自动遮挡/模糊")
        self._lora_logo.setChecked(True)
        self._lora_logo.setStyleSheet("color: #ffffff;")
        protect_layout.addWidget(self._lora_logo)
        self._lora_bgm = QCheckBox("BGM 版权替换")
        self._lora_bgm.setChecked(True)
        self._lora_bgm.setStyleSheet("color: #ffffff;")
        protect_layout.addWidget(self._lora_bgm)
        layout.addWidget(protect_group)
        
        sticker_group = QGroupBox("引流贴纸")
        sticker_layout = QFormLayout(sticker_group)
        self._lora_sticker = QCheckBox("添加引流贴纸（关注/点赞/购物车）")
        self._lora_sticker.setChecked(True)
        self._lora_sticker.setStyleSheet("color: #ffffff; font-size: 13px;")
        sticker_layout.addRow("", self._lora_sticker)
        self._lora_sticker_pos = QComboBox()
        self._lora_sticker_pos.addItems(["右下角", "左下角", "顶部居中", "右上角"])
        self._lora_sticker_pos.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        sticker_layout.addRow("贴纸位置:", self._lora_sticker_pos)
        self._lora_sticker_size = QDoubleSpinBox()
        self._lora_sticker_size.setRange(0.3, 2.0)
        self._lora_sticker_size.setSingleStep(0.1)
        self._lora_sticker_size.setValue(1.0)
        self._lora_sticker_size.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        sticker_layout.addRow("贴纸大小 (倍率):", self._lora_sticker_size)
        self._lora_sticker_opacity = QDoubleSpinBox()
        self._lora_sticker_opacity.setRange(0.3, 1.0)
        self._lora_sticker_opacity.setSingleStep(0.1)
        self._lora_sticker_opacity.setValue(0.8)
        self._lora_sticker_opacity.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        sticker_layout.addRow("透明度:", self._lora_sticker_opacity)
        self._lora_sticker_start = QDoubleSpinBox()
        self._lora_sticker_start.setRange(0.0, 30.0)
        self._lora_sticker_start.setSingleStep(1.0)
        self._lora_sticker_start.setValue(2.0)
        self._lora_sticker_start.setSuffix(" 秒")
        self._lora_sticker_start.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        sticker_layout.addRow("出现时间:", self._lora_sticker_start)
        layout.addWidget(sticker_group)
        layout.addStretch()
        return widget
    
    def _create_cover_title_tab(self) -> QWidget:
        """创建封面标题生成标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        cfg_group = QGroupBox("基础配置")
        cfg_layout = QFormLayout(cfg_group)
        self._cover_category = QComboBox()
        self._cover_category.addItems(["短剧", "Vlog", "美食", "美妆", "知识", "搞笑"])
        self._cover_category.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        cfg_layout.addRow("品类:", self._cover_category)
        self._cover_platform = QComboBox()
        self._cover_platform.addItems(["抖音", "快手", "小红书", "视频号"])
        self._cover_platform.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        cfg_layout.addRow("平台:", self._cover_platform)
        layout.addWidget(cfg_group)
        
        cover_group = QGroupBox("封面生成")
        cover_layout = QFormLayout(cover_group)
        self._cover_prompt = QLineEdit()
        self._cover_prompt.setPlaceholderText("如：古装言情剧照风格、高饱和度、人物居中")
        self._cover_prompt.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 8px;")
        cover_layout.addRow("封面提示词:", self._cover_prompt)
        layout.addWidget(cover_group)
        
        title_group = QGroupBox("标题生成")
        title_layout = QFormLayout(title_group)
        self._cover_title_type = QComboBox()
        self._cover_title_type.addItems(["悬念反问", "数字总结", "情感共鸣", "争议话题", "干货罗列"])
        self._cover_title_type.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px;")
        title_layout.addRow("标题风格:", self._cover_title_type)
        self._cover_title_prompt = QLineEdit()
        self._cover_title_prompt.setPlaceholderText("自定义标题提示词（留空则自动生成）")
        self._cover_title_prompt.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 8px;")
        title_layout.addRow("提示词:", self._cover_title_prompt)
        layout.addWidget(title_group)
        
        tag_group = QGroupBox("话题标签")
        tag_layout = QVBoxLayout(tag_group)
        self._cover_hashtags = QLineEdit()
        self._cover_hashtags.setPlaceholderText("用逗号分隔，如：短剧推荐,追剧,上头")
        self._cover_hashtags.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 8px;")
        tag_layout.addWidget(self._cover_hashtags)
        layout.addWidget(tag_group)
        layout.addStretch()
        return widget
    
    def _collect_settings(self) -> Dict[str, Any]:
        """收集所有5个步骤的设置参数"""
        return {
            "autoclip": AutoClipSettings(
                duration=self._autoclip_duration.value(),
                platform=self._autoclip_platform.currentText(),
                highlight_ratio={
                    "core_conflict": self._core_conflict.value(),
                    "emotion_padding": self._emotion_padding.value(),
                    "suspense_end": self._suspense_end.value(),
                },
                force_strong_conflict=self._force_conflict.isChecked(),
                remove_redundant=self._remove_redundant.isChecked(),
                quick_cut=self._quick_cut.isChecked(),
                transition=self._autoclip_transition.currentText(),
                category=self._autoclip_category.currentText(),
            ),
            "funclip": FunClipSettings(
                platform=self._funclip_platform.currentText(),
                bgm_type=self._funclip_bgm.currentText(),
                bgm_volume=self._funclip_bgm_vol.value(),
                video_volume=self._funclip_video_vol.value(),
                subtitle_font=self._funclip_font.currentText(),
                subtitle_style=self._funclip_sub_style.currentText(),
                subtitle_position="底部居中",
                add_narration=self._funclip_narration.isChecked(),
                add_sound_effects=self._funclip_sfx.isChecked(),
            ),
            "videofusion": VideoFusionSettings(
                platform=self._vf_platform.currentText(),
                video_type=self._vf_video_type.currentText(),
                enhance_4k=self._vf_4k.isChecked(),
                skin_correction=self._vf_skin.isChecked(),
                dynamic_stabilization=self._vf_stabilize.isChecked(),
                line_sharpening=self._vf_sharpen.isChecked(),
                saturation_boost=self._vf_saturation.isChecked(),
                noise_removal=self._vf_denoise.isChecked(),
                aspect_ratio=self._vf_aspect.currentText(),
                export_format=self._vf_format.currentText(),
            ),
            "lora": LoRASettings(
                copyright_detection=self._lora_copyright.isChecked(),
                star_face_replacement=self._lora_face.isChecked(),
                logo_blur=self._lora_logo.isChecked(),
                bgm_replacement=self._lora_bgm.isChecked(),
                traffic_sticker=self._lora_sticker.isChecked(),
                sticker_position=self._lora_sticker_pos.currentText(),
                sticker_size=self._lora_sticker_size.value(),
                sticker_opacity=self._lora_sticker_opacity.value(),
                sticker_start_time=self._lora_sticker_start.value(),
            ),
            "cover_title": CoverTitleSettings(
                category=self._cover_category.currentText(),
                platform=self._cover_platform.currentText(),
                cover_prompt=self._cover_prompt.text().strip(),
                title_type=self._cover_title_type.currentText(),
                title_prompt=self._cover_title_prompt.text().strip(),
                hashtags=[t.strip() for t in self._cover_hashtags.text().split(",") if t.strip()],
            ),
        }
    
    def _start_clip_flow(self):
        """启动AI剪辑流程：素材导入→AI分析→自动剪辑→导出 (v2.0)

        5步真实处理管线:
          1. AutoClip:  4层AI分析(ASR→语义→视觉→决策) + ABCD高光提取 + 病毒基因检测
          2. FunClip:   消费AI策略 → BGM智能混音 + 字幕生成 + 音量调整
          3. VideoFusion: 画质增强 (缩放/滤镜/导出)
          4. LoRA Edit: 水印添加 + 版权保护
          5. 封面标题: 消费剧集分析 → AI生成标题/标签 + 封面提取
        """
        if not self._current_video:
            QMessageBox.warning(self, "缺少视频", "请先选择要剪辑的视频文件")
            return

        if not os.path.exists(self._current_video):
            QMessageBox.critical(self, "文件错误", f"视频文件不存在：\n{self._current_video}")
            return

        settings = self._collect_settings()
        vp = self._video_processor

        # ── 创建临时工作目录 ──
        work_dir = os.path.join(tempfile.gettempdir(), "ai_clip_flow")
        os.makedirs(work_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(self._current_video))[0]
        output_base = os.path.join(work_dir, base_name)

        steps = [
            ("🎬 AutoClip",    "4层AI分析：ASR语音→文本语义→视觉场景→剪辑决策"),
            ("🎵 FunClip",     "精剪升级：AI策略驱动的BGM混音与字幕生成"),
            ("🎨 VideoFusion", "画质优化：增强/防抖/调色/导出"),
            ("🛡️ LoRA Edit",  "合规引流：水印添加与版权保护"),
            ("🖼️ 封面标题",   "AI生成封面文案与标题标签(剧集级上下文)"),
        ]

        from PyQt6.QtWidgets import QProgressDialog, QApplication
        progress = QProgressDialog("正在初始化 AI 剪辑引擎...", "取消", 0, len(steps), self)
        progress.setWindowTitle("AI 剪辑流程")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setStyleSheet("""
            QProgressDialog { background-color: #121212; color: #ffffff; }
            QProgressBar { background-color: #2a2a2a; border: none; border-radius: 4px;
                            text-align: center; color: white; }
            QProgressBar::chunk { background-color: #1e6bde; border-radius: 4px; }
        """)

        results: Dict[str, Any] = {}  # step_key → 输出文件路径 / 分析结果
        current_output = self._current_video
        all_ok = True

        try:
            for i, (icon, step_desc) in enumerate(steps):
                if progress.wasCanceled():
                    all_ok = False
                    break

                progress.setLabelText(f"步骤 {i+1}/{len(steps)} {icon}\n{step_desc}...")
                progress.setValue(i)
                QApplication.processEvents()

                if i == 0:
                    current_output = self._step_autoclip(settings, vp, work_dir, base_name, current_output, progress, results)
                elif i == 1:
                    current_output = self._step_funclip(settings, vp, work_dir, base_name, current_output, progress, results)
                elif i == 2:
                    current_output = self._step_videofusion(settings, vp, work_dir, base_name, current_output, progress, results)
                elif i == 3:
                    current_output = self._step_lora_edit(settings, vp, work_dir, base_name, current_output, progress, results)
                elif i == 4:
                    self._step_cover_title(settings, vp, work_dir, base_name, current_output, progress, results)

                progress.setValue(i + 1)

            # ── 最终汇总 ──
            self._finalize_clip_flow(settings, results, current_output, progress, all_ok, steps)

        except Exception as e:
            import traceback
            QMessageBox.critical(self, "流程错误",
                f"AI 剪辑流程执行失败：\n{str(e)}\n\n{traceback.format_exc()}")
            progress.close()
        
        progress.setValue(len(steps))

    def _step_autoclip(self, settings, vp, work_dir, base_name, current_output, progress, results):
        """Step 1: AutoClip — 4层AI分析(ASR→语义→视觉→决策) + ABCD高光提取 + 病毒基因检测。"""
        ac = settings["autoclip"]
        try:
            # 1.1 基础元数据提取
            info = vp.get_info(current_output)
            duration = info.get("duration", 0)
            resolution = info.get("resolution", "未知")
            fps = info.get("fps", 0)
            # 1.2 提取关键帧用于预览/封面
            frames_dir = os.path.join(work_dir, f"{base_name}_frames")
            os.makedirs(frames_dir, exist_ok=True)
            from .video_processor import extract_frames
            extract_frames(current_output, frames_dir, fps=max(0.5, fps / 10))
            # 1.3 AI剧集理解引擎（4层分析：语音+文本+视觉+决策）
            drama = None
            highlights = []
            viral_result = None
            strategy = None
            ai_analysis_detail = {}
            try:
                progress.setLabelText(
                    f"步骤 1/5 🎬 AutoClip\n"
                    f"AI剧集理解引擎启动...\n"
                    f"品类: {ac.category} | 平台: {ac.platform}"
                )
                QApplication.processEvents()
                from .drama_understanding_engine import DramaUnderstandingEngine
                engine = DramaUnderstandingEngine(
                    whisper_model="base",
                    ollama_model="qwen2.5",
                    use_local_ai=True,
                )
                # 4层分析
                progress.setLabelText(
                    f"步骤 1/5 🎬 AutoClip\n"
                    f"第1层: 语音识别(ASR)..."
                )
                QApplication.processEvents()
                drama = engine.analyze_video(current_output)
                # ABCD融合高光提取
                progress.setLabelText(
                    f"步骤 1/5 🎬 AutoClip\n"
                    f"第2-3层: 文本理解+视觉分析..."
                )
                QApplication.processEvents()
                highlights = engine.extract_highlights(
                    drama,
                    target_duration=ac.duration,
                    genre=drama.genre,
                )
                # 生成剪辑策略（BGM/转场/字幕/特效推荐）
                progress.setLabelText(
                    f"步骤 1/5 🎬 AutoClip\n"
                    f"第4层: 生成剪辑策略..."
                )
                QApplication.processEvents()
                strategy = engine.generate_editing_strategy(
                    drama,
                    target_platform=ac.platform,
                    video_style=ac.category,
                )
                ai_analysis_detail = {
                    "title": drama.title,
                    "genre": drama.genre,
                    "characters": [c.name for c in drama.characters],
                    "plot_points": len(drama.plot_points),
                    "scenes": len(drama.scenes),
                    "dialogues": len(drama.dialogues),
                    "themes": drama.themes,
                    "pacing": drama.pacing_analysis.get("pacing_type", "normal"),
                    "emotion_journey_phases": len(drama.emotion_journey),
                    "emotional_arc": drama.emotional_arc_analysis.get("arc_type", "未知"),
                }
            except Exception as ai_err:
                print(f"[AIClipFlow] AI引擎分析异常(将使用基础分析): {ai_err}")
            # 1.4 病毒传播基因检测
            try:
                from app.core.ai.viral_detector import ViralDetector
                progress.setLabelText(
                    f"步骤 1/5 🎬 AutoClip\n"
                    f"病毒传播基因检测..."
                )
                QApplication.processEvents()
                if drama is not None and drama.dialogues:
                    # 从对话生成SRT文本传给ViralDetector
                    srt_lines = []
                    for d in drama.dialogues:
                        start_ts = d.start_time
                        end_ts = d.end_time
                        srt_lines.append(
                            f"{d.start_time:.1f} --> {d.end_time:.1f}\n{d.text}"
                        )
                    srt_text = "\n\n".join(srt_lines)
                    detector = ViralDetector(llm_enhance=True)
                    viral_result = detector.analyze(
                        srt_text=srt_text,
                        total_duration=drama.total_duration,
                        top_k=5,
                    )
                elif drama is not None:
                    # 无对话时用基础检测
                    detector = ViralDetector(llm_enhance=False)
                    viral_result = detector.analyze(
                        total_duration=drama.total_duration,
                    )
                else:
                    viral_result = None
            except Exception as viral_err:
                print(f"[AIClipFlow] 病毒检测异常: {viral_err}")
            # 1.5 汇总结果
            results["autoclip"] = current_output
            results["drama"] = drama
            results["highlights"] = highlights
            results["viral"] = viral_result
            results["strategy"] = strategy
            results["ai_detail"] = ai_analysis_detail
            # 构建进度显示
            highlight_count = len(highlights)
            highlight_names = [h.suggested_title for h in highlights[:3]]
            highlight_preview = "、".join(highlight_names[:3]) if highlight_names else "无"
            viral_score = viral_result.get('composite_score', 0) if isinstance(viral_result, dict) else 0
            viral_genes = viral_result.get('detected_genes', []) if isinstance(viral_result, dict) else []
            # 从segments中提取基因名称
            if not viral_genes and isinstance(viral_result, dict):
                segments = viral_result.get('segments', [])
                all_genes = set()
                for seg in segments:
                    if isinstance(seg, dict):
                        all_genes.update(seg.get('genes_matched', []))
                viral_genes = list(all_genes)
            gene_names = [g.replace('_', ' ') for g in viral_genes[:4]] if viral_genes else []
            summary_lines = [
                f"✅ AutoClip AI分析完成 (v2.0)",
                f"   分辨率: {resolution} | 时长: {duration:.1f}s | 帧率: {fps:.0f}fps",
            ]
            if ai_analysis_detail:
                summary_lines.append(
                    f"   剧集: {ai_analysis_detail.get('title', '未知')} | "
                    f"品类: {ai_analysis_detail.get('genre', ac.category)} | "
                    f"情绪弧: {ai_analysis_detail.get('emotional_arc', '未知')}"
                )
                summary_lines.append(
                    f"   角色: {len(ai_analysis_detail.get('characters', []))} | "
                    f"场景: {ai_analysis_detail.get('scenes', 0)} | "
                    f"情节点: {ai_analysis_detail.get('plot_points', 0)}"
                )
            summary_lines.append(
                f"   高光片段: {highlight_count}个 → {highlight_preview}"
            )
            if gene_names:
                summary_lines.append(
                    f"   病毒基因: {', '.join(gene_names)} (综合分: {viral_score:.0f})"
                )
            if strategy:
                summary_lines.append(
                    f"   剪辑策略: BGM={strategy.bgm_style} | "
                    f"转场={strategy.transition_style} | 节奏={strategy.pacing}"
                )
            progress.setLabelText("\n".join(summary_lines))
        except Exception as e:
            import traceback
            print(f"[AIClipFlow] AutoClip失败: {traceback.format_exc()}")
            # 回退到基础分析
            try:
                info = vp.get_info(current_output)
                frames_dir = os.path.join(work_dir, f"{base_name}_frames")
                os.makedirs(frames_dir, exist_ok=True)
                from .video_processor import extract_frames
                extract_frames(current_output, frames_dir, fps=0.5)
                results["autoclip"] = current_output
            except Exception:
                results["autoclip"] = current_output
            progress.setLabelText(f"⚠️ AutoClip AI分析失败，已回退基础分析\n   {str(e)[:100]}")
    # Step 2: FunClip — BGM + 音频处理 (v2.0: 消费AI策略)


    def _step_funclip(self, settings, vp, work_dir, base_name, current_output, progress, results):
        """Step 2: FunClip — 消费AI策略驱动的 BGM 智能混音与字幕生成。"""
        fc = settings["funclip"]
        step_output = output_base + "_funclip.mp4"
        # 获取 Step 1 产出的AI策略（用于智能BGM/字幕推荐）
        strategy = results.get("strategy")
        ai_detail = results.get("ai_detail", {})
        try:
            operations = []
            # BGM选择优先级: 用户手动选择 > AI推荐 > 内置BGM库
            bgm_file = getattr(self, '_bgm_file', None) or (
                self._bgm_file_input.text().strip()
                if hasattr(self, '_bgm_file_input') else None
            )
            ai_bgm_style = None
            if strategy:
                ai_bgm_style = strategy.bgm_style
                # 如果AI推荐了BGM风格且用户未手动选，标记
                if not bgm_file and ai_bgm_style:
                    progress.setLabelText(
                        f"步骤 2/5 🎵 FunClip\n"
                        f"AI推荐BGM风格: {ai_bgm_style}\n"
                        f"BGM混音中..."
                    )
            if bgm_file and os.path.exists(bgm_file):
                operations.append({
                    "type": "add_bgm",
                    "music_path": bgm_file,
                    "music_volume": fc.bgm_volume,
                    "video_volume": fc.video_volume,
                })
            # AI推荐字幕样式（优先于用户下拉框默认值）
            ai_subtitle = None
            if strategy:
                ai_subtitle = strategy.subtitle_style
                # 如果AI有推荐，也可以传给后续的字幕生成器
            if operations:
                vp.process(
                    current_output, step_output,
                    operations,
                    progress_callback=lambda pct: progress.setLabelText(
                        f"步骤 2/5 🎵 FunClip\nBGM混音中... {pct}%"
                    ),
                )
                current_output = step_output
            results["funclip"] = current_output
            results["ai_bgm_recommendation"] = ai_bgm_style
            results["ai_subtitle_recommendation"] = ai_subtitle
            funclip_summary = [
                f"✅ FunClip 完成",
                f"   BGM: {fc.bgm_type} {'(AI推荐: '+ai_bgm_style+')' if ai_bgm_style and ai_bgm_style != fc.bgm_type else ''} (音量 {fc.bgm_volume:.0%})",
                f"   字幕样式: {fc.subtitle_style} {'(AI推荐: '+ai_subtitle+')' if ai_subtitle and ai_subtitle != fc.subtitle_style else ''} | 字体: {fc.subtitle_font}",
                f"   旁白: {'是' if fc.add_narration else '否'} | 音效: {'是' if fc.add_sound_effects else '否'}",
            ]
            progress.setLabelText("\n".join(funclip_summary))
        except Exception as e:
            progress.setLabelText(f"⚠️ FunClip 部分完成\n   {str(e)[:80]}")
            results["funclip"] = current_output
    # Step 3: VideoFusion — 画质优化


    def _step_videofusion(self, settings, vp, work_dir, base_name, current_output, progress, results):
        """Step 3: VideoFusion — 画质增强(超分/防抖/调色/尺寸调整)。"""
        vf = settings["videofusion"]
        step_output = output_base + "_enhanced.mp4"
        enhancements = []
        operations = []
        try:
            # 构建增强操作列表
            if vf.enhance_4k:
                operations.append({"type": "upscale", "target": "4k"})
                enhancements.append("4K超分")
            if vf.dynamic_stabilization:
                operations.append({"type": "stabilize"})
                enhancements.append("防抖")
            if vf.line_sharpening:
                operations.append({"type": "sharpen"})
                enhancements.append("锐化")
            if vf.saturation_boost:
                operations.append({"type": "saturation", "value": 1.3})
                enhancements.append("饱和度")
            if vf.noise_removal:
                operations.append({"type": "denoise"})
                enhancements.append("降噪")
            # 尺寸调整
            if vf.aspect_ratio == "9:16 竖屏":
                operations.append({"type": "resize", "width": 1080, "height": 1920})
            elif vf.aspect_ratio == "1:1 方形":
                operations.append({"type": "resize", "width": 1080, "height": 1080})
            elif vf.aspect_ratio == "16:9 横屏":
                operations.append({"type": "resize", "width": 1920, "height": 1080})
            elif vf.aspect_ratio == "4:5":
                operations.append({"type": "resize", "width": 720, "height": 900})
            if operations:
                vp.process(
                    current_output, step_output, operations,
                    ExportSettings(
                        format=vf.export_format.lower(),
                    ),
                    progress_callback=lambda pct: progress.setLabelText(
                        f"步骤 3/5 🎨 VideoFusion\n画质优化中... {pct}%"
                    ),
                )
                current_output = step_output
            results["videofusion"] = current_output
            progress.setLabelText(
                f"✅ VideoFusion 完成\n"
                f"   增强: {', '.join(enhancements) if enhancements else '无'}\n"
                f"   输出: {vf.aspect_ratio} / {vf.export_format}"
            )
        except Exception as e:
            progress.setLabelText(f"⚠️ VideoFusion 部分完成\n   {str(e)[:80]}")
            results["videofusion"] = current_output
    # Step 4: LoRA Edit — 水印/版权保护


    def _step_lora_edit(self, settings, vp, work_dir, base_name, current_output, progress, results):
        """Step 4: LoRA Edit — 水印/引流贴纸与版权保护。"""
        lr = settings["lora"]
        step_output = output_base + "_lora.mp4"
        protections = []
        try:
            operations = []
            if lr.traffic_sticker:
                # 生成引导贴纸文字覆盖
                sticker_text = "点击主页看更多精彩内容"
                operations.append({
                    "type": "watermark",
                    "text": sticker_text,
                    "position": lr.sticker_position,
                    "opacity": lr.sticker_opacity,
                })
                protections.append("引流贴纸")
            if lr.logo_blur:
                operations.append({"type": "logo_removal"})
                protections.append("Logo遮挡")
            if lr.copyright_detection:
                protections.append("版权检测")
            if operations:
                vp.process(
                    current_output, step_output, operations,
                    progress_callback=lambda pct: progress.setLabelText(
                        f"步骤 4/5 🛡️ LoRA Edit\n合规处理中... {pct}%"
                    ),
                )
                current_output = step_output
            results["lora"] = current_output
            progress.setLabelText(
                f"✅ LoRA Edit 完成\n"
                f"   保护: {', '.join(protections) if protections else '无'}\n"
                f"   贴纸位置: {lr.sticker_position} | BGM替换: {'是' if lr.bgm_replacement else '否'}"
            )
        except Exception as e:
            progress.setLabelText(f"⚠️ LoRA Edit 部分完成\n   {str(e)[:80]}")
            results["lora"] = current_output
    # Step 5: 封面标题 — AI 生成 (v2.0: 消费剧集分析)


    def _step_cover_title(self, settings, vp, work_dir, base_name, current_output, progress, results):
        """Step 5: 封面标题 — 消费剧集分析, AI 生成标题/标签并提取封面帧。"""
        ct = settings["cover_title"]
        try:
            # 提取封面帧
            from .video_processor import extract_frames
            cover_dir = os.path.join(work_dir, f"{base_name}_cover")
            os.makedirs(cover_dir, exist_ok=True)
            extract_frames(current_output, cover_dir, fps=0.1)
            cover_files = sorted([
                f for f in os.listdir(cover_dir) if f.endswith(('.jpg', '.png'))
            ])
            cover_path = os.path.join(cover_dir, cover_files[0]) if cover_files else ""
            # 获取 AI 分析结果用于增强标题生成
            ai_detail = results.get("ai_detail", {})
            drama = results.get("drama")
            viral = results.get("viral")
            # 构建富含上下文的标题生成提示
            drama_context = ""
            if ai_detail:
                characters = ai_detail.get("characters", [])
                themes = ai_detail.get("themes", [])
                genre = ai_detail.get("genre", ct.category)
                emotional_arc = ai_detail.get("emotional_arc", "")
                char_str = "、".join(characters[:3]) if characters else "主角"
                theme_str = "、".join(themes[:3]) if themes else ""
                drama_context = (
                    f"剧集类型: {genre}，"
                    f"主要角色: {char_str}"
                )
                if theme_str:
                    drama_context += f"，核心主题: {theme_str}"
                if emotional_arc:
                    drama_context += f"，情绪走向: {emotional_arc}"
            # AI 生成标题（使用剧集上下文+病毒基因增强）
            ai_title = ""
            try:
                from app.core.ai_engine import ai_engine
                prompt = (
                    f"为一段{ct.category}类短视频生成一个吸引人的标题。\n"
                    f"平台: {ct.platform}，标题风格: {ct.title_type}。\n"
                )
                if drama_context:
                    prompt += f"视频内容: {drama_context}。\n"
                # 如果有病毒基因信息，用于适配标题风格
                viral_genes = viral.get('detected_genes', []) if isinstance(viral, dict) else []
                if not viral_genes and isinstance(viral, dict):
                    for seg in viral.get('segments', []):
                        if isinstance(seg, dict):
                            viral_genes.extend(seg.get('genes_matched', []))
                if viral_genes:
                    gene_hints = [g.replace('_', ' ') for g in viral_genes[:3]]
                    prompt += f"可利用的爆款基因: {', '.join(gene_hints)}。\n"
                prompt += "要求：15字以内，包含情绪词和悬念，快速吸引注意力。"
                if ct.title_prompt:
                    prompt += f"\n额外要求: {ct.title_prompt}"
                for chunk in ai_engine.chat_with_fallback(
                    messages=[
                        {"role": "system", "content": "你是短视频爆款标题专家，只输出标题文本。"},
                        {"role": "user", "content": prompt},
                    ],
                    template=lambda: "",
                ):
                    if chunk and not chunk.startswith("错误"):
                        ai_title += chunk
                ai_title = ai_title.strip().strip('"\'')
            except Exception as e:
                print(f"[AIClipFlow] AI 标题生成失败: {e}")
                ai_title = ""  # 回退到默认标题
            # 智能话题标签（基于品类+主题+病毒基因）
            ai_hashtags = list(ct.hashtags) if ct.hashtags else []
            if drama_context and not ct.hashtags:
                genre = ai_detail.get("genre", ct.category)
                if genre and genre not in ai_hashtags:
                    ai_hashtags.append(genre)
                themes = ai_detail.get("themes", [])
                for t in themes[:3]:
                    if t not in ai_hashtags:
                        ai_hashtags.append(t)
            if not ai_hashtags:
                ai_hashtags = ["短剧", "推荐"]
            hashtags_str = ', '.join(ai_hashtags[:8])
            results["cover_title"] = cover_path
            results["ai_title"] = ai_title
            results["ai_hashtags"] = ai_hashtags
            progress.setLabelText(
                f"✅ 封面标题完成\n"
                f"   封面帧: {os.path.basename(cover_path) if cover_path else '已生成'}\n"
                f"   AI标题: {ai_title[:50] if ai_title else '（使用默认标题）'}\n"
                f"   标签: #{hashtags_str[:60]}"
            )
        except Exception as e:
            progress.setLabelText(f"⚠️ 封面标题 部分完成\n   {str(e)[:80]}")


    def _finalize_clip_flow(self, settings, results, current_output, progress, all_ok, steps):
        """流程结束后的汇总、文件落盘与事件总线广播。"""
        # ── 最终汇总 ──
        if all_ok and not progress.wasCanceled():
            # 获取AutoClip设置用于命名
            ac_settings = settings["autoclip"]
            # 尝试从AI分析获取更准确的品类名
            ai_detail = results.get("ai_detail", {})
            ai_genre = ai_detail.get("genre", "") if ai_detail else ""
            display_genre = ai_genre or ac_settings.category
            # 复制最终输出到项目输出目录
            final_name = f"{base_name}_AI剪辑_{ac_settings.platform}_{display_genre}.mp4"
            import shutil
            final_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                      "短剧AI剪辑输出")
            os.makedirs(final_dir, exist_ok=True)
            final_path = os.path.join(final_dir, final_name)
            if current_output != final_path and os.path.exists(current_output):
                shutil.copy2(current_output, final_path)
            # 通过事件总线通知（包含AI分析摘要）
            ai_viral = results.get("viral")
            ai_viral_score = ai_viral.get('composite_score', 0) if isinstance(ai_viral, dict) else 0
            self._event_bus.emit(EventType.VIDEO_EXPORTED, {
                "path": final_path,
                "source": "ai_clip_flow",
                "settings": {k: str(v) for k, v in settings.items()},
                "ai_genre": display_genre,
                "ai_viral_score": ai_viral_score,
                "highlight_count": len(results.get("highlights", [])),
            })
            ai_summary = ""
            if ai_detail:
                ai_summary = (
                    f"📊 AI分析: {ai_detail.get('title', '未知')} | "
                    f"品类: {display_genre} | "
                    f"病毒分: {ai_viral_score:.0f}\n"
                )
            progress.setLabelText(
                f"🎉 AI 剪辑流程全部完成！(v2.0)\n\n"
                f"{ai_summary}"
                f"📁 输出: {final_path}\n"
                f"📊 共完成 {len(steps)} 个步骤\n\n"
                f"可在\"导出\"标签页或短剧AI剪辑输出目录查看成品。"
            )
        elif progress.wasCanceled():
            progress.setLabelText("⚠️ 流程已取消\n\n中间文件保存在临时目录。")
        else:
            progress.setLabelText("⚠️ 流程部分完成\n\n请检查各步骤状态。")

