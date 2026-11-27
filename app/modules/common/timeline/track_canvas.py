"""轨道画布 - 视口裁剪优化的时间线绘制"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QPixmapCache
import os


class TrackCanvas(QWidget):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tracks = []
        self.current_time = 0.0
        self.duration = 60.0
        self.track_height = 40
        self._zoom = 1.0
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

    def set_zoom(self, zoom: float):
        self._zoom = max(0.1, min(5.0, zoom))
        QPixmapCache.clear()
        self.update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QWidget { background-color: #2a2a4a; }")

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.setStyleSheet("")
        if not event.mimeData().hasUrls():
            return

        file_paths = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if local_path and os.path.exists(local_path):
                ext = os.path.splitext(local_path)[1].lower()
                if ext in ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.jpg', '.jpeg', '.png', '.bmp', '.webp'):
                    file_paths.append(local_path)

        if file_paths:
            self.files_dropped.emit(file_paths)

        event.acceptProposedAction()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        clip = event.rect()
        painter.fillRect(clip, QColor(30, 30, 30))

        first_track = max(0, clip.top() // self.track_height)
        last_track = min(len(self.tracks), clip.bottom() // self.track_height + 2)

        pen = QPen(QColor(50, 50, 50), 1)
        painter.setPen(pen)
        for i in range(first_track, last_track + 1):
            y = i * self.track_height
            if y >= clip.top() - 1 and y <= clip.bottom() + 1:
                painter.drawLine(max(0, clip.left()), y, min(self.width(), clip.right()), y)

        for i in range(max(0, first_track - 1), min(len(self.tracks), last_track)):
            track = self.tracks[i]
            y = i * self.track_height
            if not track.get('clips'):
                continue
            for clip_data in track['clips']:
                start_px = int(clip_data.get('start_time', 0) * self._zoom * 50)
                end_px = int((clip_data.get('start_time', 0) + clip_data.get('duration', 1)) * self._zoom * 50)
                if end_px < clip.left() or start_px > clip.right():
                    continue
                x = max(clip.left(), start_px)
                w = min(clip.right(), end_px) - x
                if w < 2:
                    continue
                clip_id = clip_data.get('id', 'unknown')
                cache_key = f"clip_{clip_id}_{self._zoom}_{w}"
                pixmap = QPixmapCache.find(cache_key)
                if pixmap is None:
                    h = self.track_height - 4
                    pixmap = QPixmap(w, h)
                    pixmap.fill(QColor(60, 100, 180))
                    QPixmapCache.insert(cache_key, pixmap)
                painter.drawPixmap(x, y + 2, pixmap)

        playhead_x = int(self.current_time * self._zoom * 50)
        if playhead_x >= clip.left() - 1 and playhead_x <= clip.right() + 1:
            pen = QPen(QColor(30, 107, 222), 2)
            painter.setPen(pen)
            painter.drawLine(playhead_x, max(0, clip.top()), playhead_x, min(self.height(), clip.bottom()))

        painter.end()
