"""
简洁轨道组件 — 设计参考 Adobe Premiere / DaVinci Resolve
=========================================================
扁平化、无边框、清晰分层的轨道 UI
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import pyqtSignal, Qt


class TrackRow(QWidget):
    """单条轨道行"""
    
    mute_toggled = pyqtSignal(bool)
    
    def __init__(self, name="轨道", track_type="video", index=0):
        super().__init__()
        self.setFixedHeight(38)
        self._muted = False
        
        # 交替背景
        bg = "#1a1a1a" if index % 2 == 0 else "#161616"
        self.setStyleSheet(f"background:{bg};")
        
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        
        # ---- 左侧: 轨道标签 (80px) ----
        ctrl = QWidget()
        ctrl.setFixedWidth(80)
        cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(8, 0, 6, 0)
        cl.setSpacing(4)
        
        icons = {"video": "🎬", "audio": "🎵", "subtitle": "📝", "overlay": "🖼"}
        lb = QLabel(f"{icons.get(track_type, '📌')} {name}")
        lb.setStyleSheet("color:#888;font-size:10px;font-weight:500;")
        cl.addWidget(lb)
        cl.addStretch()
        
        mute = QPushButton("M")
        mute.setFixedSize(18, 18)
        mute.setCheckable(True)
        mute.setCursor(Qt.CursorShape.PointingHandCursor)
        mute.setStyleSheet("""
            QPushButton { background:transparent; color:#555; border:none; font:9px bold; border-radius:3px; }
            QPushButton:hover { background:#333; color:#aaa; }
            QPushButton:checked { background:#d32f2f; color:#fff; }
        """)
        mute.clicked.connect(lambda checked: self._toggle_mute(checked))
        cl.addWidget(mute)
        
        h.addWidget(ctrl)
        
        # ---- 分隔线 ----
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#2a2a2a;")
        sep.setFixedWidth(1)
        h.addWidget(sep)
        
        # ---- 右侧: 片段区域 ----
        self._clip_area = QWidget()
        self._clip_area.setStyleSheet("background:transparent;")
        self._clip_layout = QHBoxLayout(self._clip_area)
        self._clip_layout.setContentsMargins(4, 2, 4, 2)
        self._clip_layout.setSpacing(2)
        self._clip_layout.addStretch()
        h.addWidget(self._clip_area, 1)
        
        self._mute_btn = mute
    
    def _toggle_mute(self, checked):
        self._muted = checked
        self.mute_toggled.emit(checked)
    
    def add_clip_button(self, text, width=60, color="#1e6bde"):
        """添加片段方块"""
        clip = QPushButton(text[:8])
        clip.setFixedSize(max(30, width), 32)
        clip.setCursor(Qt.CursorShape.PointingHandCursor)
        clip.setStyleSheet(f"""
            QPushButton {{ background:{color}; color:#fff; border:none; border-radius:4px; font:10px; padding:2px 6px; }}
            QPushButton:hover {{ background:{color}cc; }}
        """)
        pos = self._clip_layout.count() - 1
        self._clip_layout.insertWidget(pos, clip)
        return clip
    
    @property
    def clip_layout(self):
        return self._clip_layout


class TimelineTracks(QWidget):
    """轨道容器 — 多个 TrackRow 的垂直排列"""
    
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:#111;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._tracks = []
        self.add_track("视频", "video")
        self.add_track("音频", "audio")
    
    def add_track(self, name, ttype):
        row = TrackRow(name, ttype, len(self._tracks))
        self._layout.addWidget(row)
        self._tracks.append({"name": name, "type": ttype, "row": row})
        return row
    
    @property
    def tracks(self):
        return self._tracks


class RulerBar(QWidget):
    """时间刻度栏 — 简洁扁平"""
    
    def __init__(self):
        super().__init__()
        self.setFixedHeight(26)
        self.setStyleSheet("background:#181818;border-bottom:1px solid #2a2a2a;")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(80, 2, 0, 0)
        self._layout.setSpacing(0)
        self._redraw(60)
    
    def set_duration(self, seconds):
        """更新时间刻度范围"""
        self._redraw(int(seconds))
    
    def _redraw(self, duration):
        while self._layout.count():
            w = self._layout.takeAt(0).widget()
            if w: w.deleteLater()
        for s in range(0, duration + 1, 10):
            m, sec = divmod(s, 60)
            lbl = QLabel(f"{m}:{sec:02d}")
            lbl.setStyleSheet("color:#555;font:8px Consolas;")
            lbl.setFixedWidth(150)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self._layout.addWidget(lbl)
        self._layout.addStretch()
