from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen

class Timeline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tracks = []
        self.duration = 0
        self.current_time = 0
        self.zoom = 1.0
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        self.setLayout(layout)
        self.setMinimumHeight(200)
    
    def add_track(self, track_type="video"):
        self.tracks.append({
            "type": track_type,
            "clips": []
        })
        self.update()
    
    def remove_track(self, index):
        if 0 <= index < len(self.tracks):
            self.tracks.pop(index)
            self.update()
    
    def set_duration(self, duration):
        self.duration = duration
        self.update()
    
    def set_current_time(self, time):
        self.current_time = time
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        painter.fillRect(self.rect(), QColor(45, 45, 45))
        
        pen = QPen(QColor(100, 100, 100))
        pen.setWidth(1)
        painter.setPen(pen)
        
        for i in range(len(self.tracks) + 1):
            y = i * 40
            painter.drawLine(0, y, self.width(), y)
        
        if self.duration > 0:
            playhead_x = int((self.current_time / self.duration) * self.width())
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawLine(playhead_x, 0, playhead_x, self.height())

__all__ = ['Timeline']
