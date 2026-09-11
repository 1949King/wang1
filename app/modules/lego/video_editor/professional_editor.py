"""
专业编辑面板
==================
整合特效编辑器、字幕编辑器、素材编辑器等专业编辑组件
"""

from typing import Dict, List, Optional, Any
from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QPushButton, QLabel, QSlider, QSpinBox, QComboBox
import logging

from app.core.timeline import timeline_core

logger = logging.getLogger("AI短剧编辑器.professional_editor")


class EffectEditor(QWidget):
    """特效编辑器"""
    
    effect_applied = pyqtSignal(str, str)
    effect_removed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._current_effects = {}
        self._available_effects = {
            'brightness': {'name': '亮度', 'type': 'slider', 'min': -100, 'max': 100, 'default': 0},
            'contrast': {'name': '对比度', 'type': 'slider', 'min': 0, 'max': 200, 'default': 100},
            'saturation': {'name': '饱和度', 'type': 'slider', 'min': 0, 'max': 200, 'default': 100},
            'hue': {'name': '色调', 'type': 'slider', 'min': -180, 'max': 180, 'default': 0},
            'blur': {'name': '模糊', 'type': 'slider', 'min': 0, 'max': 20, 'default': 0},
            'sharpen': {'name': '锐化', 'type': 'slider', 'min': 0, 'max': 100, 'default': 0},
        }
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        for effect_id, effect_config in self._available_effects.items():
            effect_layout = QHBoxLayout()
            effect_layout.setSpacing(8)
            
            label = QLabel(effect_config['name'])
            label.setFixedWidth(80)
            effect_layout.addWidget(label)
            
            if effect_config['type'] == 'slider':
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(effect_config['min'], effect_config['max'])
                slider.setValue(effect_config['default'])
                slider.valueChanged.connect(lambda v: self._apply_effect(effect_id, v))
                effect_layout.addWidget(slider)
            
            elif effect_config['type'] == 'dropdown':
                dropdown = QComboBox()
                dropdown.addItems(['低', '中', '高'])
                dropdown.setCurrentIndex(1)
                dropdown.currentTextChanged.connect(lambda v: self._apply_effect(effect_id, v))
                effect_layout.addWidget(dropdown)
            
            layout.addLayout(effect_layout)
        
        # 应用/重置按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        apply_btn = QPushButton("应用效果")
        apply_btn.clicked.connect(self._apply_all_effects)
        button_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("重置效果")
        reset_btn.clicked.connect(self._reset_all_effects)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
    
    def _apply_effect(self, effect_id: str, value: Any) -> None:
        """应用单个效果"""
        self._current_effects[effect_id] = value
        logger.info(f"应用效果: {effect_id} = {value}")
    
    def _apply_all_effects(self) -> None:
        """应用所有效果"""
        self.effect_applied.emit('all', str(self._current_effects))
        logger.info(f"应用所有效果: {self._current_effects}")
    
    def _reset_all_effects(self) -> None:
        """重置所有效果"""
        for effect_id, effect_config in self._available_effects.items():
            self._current_effects[effect_id] = effect_config['default']
        
        logger.info(f"重置所有效果")
    
    def get_current_effects(self) -> Dict[str, Any]:
        """获取当前效果"""
        return self._current_effects.copy()


class SubtitleEditor(QWidget):
    """字幕编辑器"""
    
    subtitle_added = pyqtSignal(str, dict)
    subtitle_removed = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._subtitles = {}
        self._current_subtitle_id = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 字幕列表
        subtitle_list = QComboBox()
        subtitle_list.currentIndexChanged.connect(self._on_subtitle_selected)
        layout.addWidget(QLabel("字幕:"))
        layout.addWidget(subtitle_list)
        
        # 字幕内容编辑
        content_layout = QVBoxLayout()
        
        text_label = QLabel("字幕内容:")
        content_layout.addWidget(text_label)
        
        from PyQt6.QtWidgets import QTextEdit
        self._subtitle_text = QTextEdit()
        self._subtitle_text.setPlaceholderText("输入字幕内容...")
        content_layout.addWidget(self._subtitle_text)
        
        layout.addLayout(content_layout)
        
        # 字幕控制按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        add_btn = QPushButton("添加字幕")
        add_btn.clicked.connect(self._add_subtitle)
        button_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("删除字幕")
        remove_btn.clicked.connect(self._remove_subtitle)
        button_layout.addWidget(remove_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
    
    def _on_subtitle_selected(self, index: int) -> None:
        """字幕选择改变"""
        if index >= 0:
            subtitle_id = list(self._subtitles.keys())[index]
            self._current_subtitle_id = subtitle_id
            logger.info(f"选择字幕: {subtitle_id}")
    
    def _add_subtitle(self) -> None:
        """添加字幕"""
        import uuid
        subtitle_id = f"subtitle_{uuid.uuid4().hex}"
        
        subtitle_data = {
            'id': subtitle_id,
            'content': self._subtitle_text.toPlainText(),
            'start_time': 0.0,
            'duration': 5.0,
            'style': 'default'
        }
        
        self._subtitles[subtitle_id] = subtitle_data
        self.subtitle_added.emit(subtitle_id, subtitle_data)
        logger.info(f"添加字幕: {subtitle_id}")
    
    def _remove_subtitle(self) -> None:
        """删除字幕"""
        if self._current_subtitle_id and self._current_subtitle_id in self._subtitles:
            del self._subtitles[self._current_subtitle_id]
            self.subtitle_removed.emit(self._current_subtitle_id)
            logger.info(f"删除字幕: {self._current_subtitle_id}")
    
    def get_subtitles(self) -> Dict[str, Dict[str, Any]]:
        """获取所有字幕"""
        return self._subtitles.copy()
    
    def get_current_subtitle(self) -> Optional[Dict[str, Any]]:
        """获取当前字幕"""
        if self._current_subtitle_id:
            return self._subtitles.get(self._current_subtitle_id)
        return None


class MaterialEditor(QWidget):
    """素材编辑器"""
    
    material_selected = pyqtSignal(str, dict)
    material_imported = pyqtSignal(str, dict)
    
    def __init__(self):
        super().__init__()
        self._materials = {}
        self._current_material_id = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 素材列表
        material_list = QComboBox()
        material_list.currentIndexChanged.connect(self._on_material_selected)
        layout.addWidget(QLabel("素材:"))
        layout.addWidget(material_list)
        
        # 素材预览
        preview_label = QLabel("素材预览:")
        layout.addWidget(preview_label)
        
        from PyQt6.QtWidgets import QLabel
        self._material_preview = QLabel("选择素材查看预览")
        self._material_preview.setStyleSheet("border: 1px solid #ccc; padding: 10px; min-height: 100px;")
        layout.addWidget(self._material_preview)
        
        layout.addLayout(preview_label)
        
        # 素材控制按钮
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        import_btn = QPushButton("导入素材")
        import_btn.clicked.connect(self._import_material)
        button_layout.addWidget(import_btn)
        
        remove_btn = QPushButton("删除素材")
        remove_btn.clicked.connect(self._remove_material)
        button_layout.addWidget(remove_btn)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
    
    def _on_material_selected(self, index: int) -> None:
        """素材选择改变"""
        if index >= 0:
            material_id = list(self._materials.keys())[index]
            self._current_material_id = material_id
            logger.info(f"选择素材: {material_id}")
    
    def _import_material(self) -> None:
        """导入素材"""
        import uuid
        material_id = f"material_{uuid.uuid4().hex}"
        
        material_data = {
            'id': material_id,
            'name': f"素材 {len(self._materials) + 1}",
            'path': "",
            'type': 'image',
            'duration': 0.0
        }
        
        self._materials[material_id] = material_data
        self.material_imported.emit(material_id, material_data)
        logger.info(f"导入素材: {material_id}")
    
    def _remove_material(self) -> None:
        """删除素材"""
        if self._current_material_id and self._current_material_id in self._materials:
            del self._materials[self._current_material_id]
            self.material_removed.emit(self._current_material_id)
            logger.info(f"删除素材: {self._current_material_id}")
    
    def get_materials(self) -> Dict[str, Dict[str, Any]]:
        """获取所有素材"""
        return self._materials.copy()
    
    def get_current_material(self) -> Optional[Dict[str, Any]]:
        """获取当前素材"""
        if self._current_material_id:
            return self._materials.get(self._current_material_id)
        return None


class ProfessionalEditor(QWidget):
    """专业编辑面板 - 整合所有编辑器"""
    
    def __init__(self):
        super().__init__()
        self._effect_editor = EffectEditor()
        self._subtitle_editor = SubtitleEditor()
        self._material_editor = MaterialEditor()
        
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标签页
        tab_widget = QTabWidget()
        tab_widget.addTab(self._effect_editor, "🎨 特效")
        tab_widget.addTab(self._subtitle_editor, "📝 字幕")
        tab_widget.addTab(self._material_editor, "📁 素材")
        
        layout.addWidget(tab_widget)
    
    def get_effect_editor(self) -> EffectEditor:
        """获取特效编辑器"""
        return self._effect_editor
    
    def get_subtitle_editor(self) -> SubtitleEditor:
        """获取字幕编辑器"""
        return self._subtitle_editor
    
    def get_material_editor(self) -> MaterialEditor:
        """获取素材编辑器"""
        return self._material_editor
    
    def get_current_tab(self) -> int:
        """获取当前标签页"""
        return self.findChild(QTabWidget).currentIndex()
    
    def set_current_tab(self, index: int) -> None:
        """设置当前标签页"""
        self.findChild(QTabWidget).setCurrentIndex(index)
        logger.info(f"切换到标签页: {index}")