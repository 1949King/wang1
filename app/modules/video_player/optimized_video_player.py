import threading
import time
import os
import logging

logger = logging.getLogger(__name__)

cv2 = None
np = None
Image = None
ImageQt = None
QPixmap = None
QImage = None
Qt = None
QTimer = None
pyqtSignal = None
pyqtSlot = None
QObject = None
QThread = None
QLabel = None
QSlider = None
QPushButton = None
QHBoxLayout = None
QVBoxLayout = None
QWidget = None
QComboBox = None
QStyle = None
QApplication = None
QMediaPlayer = None
QAudioOutput = None
QVideoWidget = None
QMediaMetaData = None

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageQt
    from PyQt6.QtGui import QPixmap, QImage
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot, QObject, QThread, QUrl, QMetaObject, Q_ARG
    from PyQt6.QtWidgets import (QLabel, QSlider, QPushButton, QHBoxLayout,
                                  QVBoxLayout, QWidget, QComboBox, QStyle,
                                  QApplication)
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    logger.info('✓ 视频播放器依赖导入成功 (PyQt6 + QtMultimedia)')
except Exception as e:
    logger.warning(f'警告: 缺少视频播放器依赖: {e}')
    logger.info('视频播放器将在运行时提示缺少依赖')


class FrameReaderThread(QThread): 
    frame_signal = pyqtSignal(np.ndarray) if pyqtSignal else None
    finished_signal = pyqtSignal() if pyqtSignal else None
    error_signal = pyqtSignal(str) if pyqtSignal else None

    def __init__(self, video_path): 
        if QThread:
            super().__init__() 
        self.video_path = video_path 
        self.cap = None 
        self.is_playing = True 
        self.play_speed = 1.0
        self.current_frame = 0 
        self.total_frames = 0 
        self.fps = 30 
        self.seek_request = None
        self._seek_lock = threading.Lock()

    def run(self): 
        if not cv2:
            if self.error_signal:
                self.error_signal.emit("缺少opencv-python依赖")
            return
            
        try: 
            self.cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
            if not self.cap.isOpened(): 
                if self.error_signal:
                    self.error_signal.emit("无法打开视频文件") 
                return 

            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) 
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30 
            frame_delay = 1 / self.fps

            while self.is_playing and self.current_frame < self.total_frames: 
                with self._seek_lock:
                    if self.seek_request is not None:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.seek_request)
                        self.current_frame = self.seek_request
                        self.seek_request = None

                ret, frame = self.cap.read() 
                if not ret: 
                    break 

                if self.frame_signal:
                    self.frame_signal.emit(frame) 
                self.current_frame += 1 

                time.sleep(frame_delay / self.play_speed) 

            if self.finished_signal:
                self.finished_signal.emit() 
        except Exception as e: 
            if self.error_signal:
                self.error_signal.emit(f"播放错误：{str(e)}") 
        finally: 
            if self.cap: 
                self.cap.release() 

    def pause(self): 
        self.is_playing = False 

    def resume(self): 
        self.is_playing = True 

    def set_speed(self, speed): 
        self.play_speed = speed 

    def seek(self, frame_idx): 
        if 0 <= frame_idx < self.total_frames: 
            with self._seek_lock:
                self.seek_request = frame_idx

    def stop(self): 
        self.is_playing = False 
        if QThread:
            self.quit() 
            self.wait() 


class OptimizedVideoPlayer(QWidget): 
    def __init__(self, parent=None): 
        if QWidget:
            super().__init__(parent) 
            self.setStyleSheet("background-color: #1E1E2E;") 
        self.video_path = None 
        self.reader_thread = None 
        self.is_playing = False 
        self.volume = 0.8
        self.play_speed = 1.0
        self._use_qt_multimedia = True

        self.has_dependencies = all([QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QSlider, QComboBox, QStyle])
        if self.has_dependencies:
            self.init_ui() 
            self.init_signals() 

    def init_ui(self): 
        main_layout = QVBoxLayout(self) 
        main_layout.setContentsMargins(0, 0, 0, 0) 
        main_layout.setSpacing(8) 

        self.preview_label = QLabel() 
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #000000;
                border-radius: 8px;
                min-height: 300px;
            }
        """) 
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter) 
        self.preview_label.setText("📹 请导入视频文件") 
        main_layout.addWidget(self.preview_label) 

        self.video_widget = QVideoWidget() if QVideoWidget else None
        if self.video_widget:
            self.video_widget.setStyleSheet("background-color: #000000; border-radius: 8px;")
            self.video_widget.hide()
            main_layout.addWidget(self.video_widget)

        control_layout = QHBoxLayout() 
        control_layout.setSpacing(10) 

        self.play_btn = QPushButton() 
        if QStyle:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)) 
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 50%;
                width: 40px;
                height: 40px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """) 
        control_layout.addWidget(self.play_btn) 

        self.progress_slider = QSlider(Qt.Orientation.Horizontal) 
        self.progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #333333;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                background: #4CAF50;
                border-radius: 8px;
                margin: -5px 0;
            }
            QSlider::sub-page:horizontal {
                background: #4CAF50;
                border-radius: 3px;
            }
        """) 
        self.progress_slider.setRange(0, 1000) 
        control_layout.addWidget(self.progress_slider, stretch=1) 

        self.speed_combo = QComboBox() 
        self.speed_combo.addItems(["0.5x", "1.0x", "1.5x", "2.0x"]) 
        self.speed_combo.setStyleSheet("""
            QComboBox {
                background-color: #2D2D3F;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 6px;
                min-width: 80px;
            }
        """) 
        control_layout.addWidget(self.speed_combo) 

        self.volume_slider = QSlider(Qt.Orientation.Horizontal) 
        self.volume_slider.setRange(0, 100) 
        self.volume_slider.setValue(80) 
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #333333;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px;
                height: 14px;
                background: #4CAF50;
                border-radius: 7px;
                margin: -4px 0;
            }
        """) 
        self.volume_slider.setMaximumWidth(80) 
        control_layout.addWidget(QLabel("🔊")) 
        control_layout.addWidget(self.volume_slider) 

        main_layout.addLayout(control_layout) 

        self._media_player = None
        self._audio_output = None
        self._duration = 0

    def init_signals(self): 
        if self.has_dependencies:
            self.play_btn.clicked.connect(self.toggle_play) 
            self.speed_combo.currentTextChanged.connect(self.on_speed_change) 
            self.volume_slider.valueChanged.connect(self.on_volume_change) 
            self.progress_slider.sliderPressed.connect(self.on_progress_pressed) 
            self.progress_slider.sliderReleased.connect(self.on_progress_released) 

    def load_video(self, video_path): 
        if not self.has_dependencies:
            if hasattr(self, 'preview_label'):
                self.preview_label.setText("❌ 缺少PyQt5依赖")
            return
            
        if self._use_qt_multimedia and QMediaPlayer and QVideoWidget:
            self._load_video_qt_multimedia(video_path)
        else:
            self._load_video_opencv(video_path)

    def _load_video_qt_multimedia(self, video_path): 
        self.video_path = video_path 
        self.is_playing = False 

        if self._media_player:
            self._media_player.stop()
            self._media_player = None
        
        if self._audio_output:
            self._audio_output = None

        if self.video_widget:
            self.video_widget.show()
            self.preview_label.hide()

        self._audio_output = QAudioOutput()
        self._media_player = QMediaPlayer()
        self._media_player.setAudioOutput(self._audio_output)
        self._media_player.setVideoOutput(self.video_widget)
        
        self._media_player.setSource(QUrl.fromLocalFile(video_path))
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._media_player.errorOccurred.connect(self._on_media_error)

        self._audio_output.setVolume(self.volume)
        
        if hasattr(self, 'preview_label'):
            self.preview_label.setText(f"📹 加载中: {os.path.basename(video_path)}") 

        self._media_player.play()
        self._media_player.pause()

    def _load_video_opencv(self, video_path): 
        self.video_path = video_path 
        self.is_playing = False 
        
        if self.reader_thread: 
            self.reader_thread.stop() 
            self.reader_thread = None 

        if self.video_widget:
            self.video_widget.hide()
            self.preview_label.show()
        
        self.reader_thread = FrameReaderThread(video_path) 
        if hasattr(self.reader_thread, 'frame_signal') and self.reader_thread.frame_signal:
            self.reader_thread.frame_signal.connect(self.update_frame) 
        if hasattr(self.reader_thread, 'finished_signal') and self.reader_thread.finished_signal:
            self.reader_thread.finished_signal.connect(self.on_play_finished) 
        if hasattr(self.reader_thread, 'error_signal') and self.reader_thread.error_signal:
            self.reader_thread.error_signal.connect(self.on_error) 

        if hasattr(self, 'preview_label'):
            self.preview_label.setText(f"📹 加载中: {os.path.basename(video_path)}") 

        self.reader_thread.start() 

    def _on_position_changed(self, position): 
        if hasattr(self, 'progress_slider') and self._duration > 0: 
            progress = int((position / self._duration) * 1000) 
            self.progress_slider.setValue(progress) 

    def _on_duration_changed(self, duration): 
        self._duration = duration 

    def _on_media_status_changed(self, status): 
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.on_play_finished()

    def _on_media_error(self, error, error_string): 
        logger.error(f'QtMultimedia 错误: {error_string}')
        self._use_qt_multimedia = False
        if self.video_path:
            self._load_video_opencv(self.video_path)

    def toggle_play(self): 
        if self._use_qt_multimedia and self._media_player:
            if self.is_playing:
                self._media_player.pause()
                if hasattr(self, 'play_btn') and QStyle:
                    self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            else:
                self._media_player.play()
                if hasattr(self, 'play_btn') and QStyle:
                    self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.is_playing = not self.is_playing
        elif self.reader_thread: 
            if self.is_playing: 
                self.reader_thread.pause() 
                if hasattr(self, 'play_btn') and QStyle:
                    self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)) 
            else: 
                self.reader_thread.resume() 
                if hasattr(self, 'play_btn') and QStyle:
                    self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause)) 
            self.is_playing = not self.is_playing 

    def update_frame(self, frame): 
        if not all([cv2, QImage, QPixmap, Qt]):
            return
            
        try: 
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) 
            h, w, ch = frame.shape 
            bytes_per_line = ch * w 
            q_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888) 
            
            if hasattr(self, 'preview_label'):
                preview_size = self.preview_label.size() 
                scaled_image = q_image.scaled(preview_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) 
                self.preview_label.setPixmap(QPixmap.fromImage(scaled_image)) 
                
                if self.reader_thread and hasattr(self, 'progress_slider'): 
                    progress = int((self.reader_thread.current_frame / self.reader_thread.total_frames) * 1000) 
                    self.progress_slider.setValue(progress) 
        except Exception as e: 
            logger.error(f'更新帧失败: {e}')

    def on_speed_change(self, speed_text): 
        try: 
            speed = float(speed_text.replace('x', '')) 
            self.play_speed = speed
            if self._use_qt_multimedia and self._media_player:
                self._media_player.setPlaybackRate(speed)
            elif self.reader_thread:
                self.reader_thread.set_speed(speed)
        except ValueError as e:
            logger.debug(f"播放速度解析失败，忽略本次速度切换: {e}")

    def on_volume_change(self, value): 
        self.volume = value / 100.0 
        if self._audio_output:
            self._audio_output.setVolume(self.volume)

    def on_progress_pressed(self): 
        if self._use_qt_multimedia and self._media_player and self.is_playing:
            self._media_player.pause()
        elif self.reader_thread and self.is_playing: 
            self.reader_thread.pause() 

    def on_progress_released(self): 
        if hasattr(self, 'progress_slider'):
            progress = self.progress_slider.value() / 1000.0 
            if self._use_qt_multimedia and self._media_player and self._duration > 0:
                target_pos = int(progress * self._duration)
                self._media_player.setPosition(target_pos)
                if self.is_playing:
                    self._media_player.play()
            elif self.reader_thread:
                target_frame = int(progress * self.reader_thread.total_frames) 
                self.reader_thread.seek(target_frame) 
                if self.is_playing: 
                    self.reader_thread.resume() 

    def on_play_finished(self): 
        self.is_playing = False 
        if hasattr(self, 'play_btn') and QStyle:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)) 

    def on_error(self, error_msg): 
        if hasattr(self, 'preview_label'):
            self.preview_label.setText(f"❌ 错误: {error_msg}") 
        self.is_playing = False 
        if hasattr(self, 'play_btn') and QStyle:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)) 

    def closeEvent(self, event): 
        if self.reader_thread: 
            self.reader_thread.stop() 
        if self._media_player:
            self._media_player.stop()
        if event: 
            event.accept()
    
    def show(self):
        if QWidget:
            super().show()
    
    def resize(self, width, height):
        if QWidget:
            super().resize(width, height)
    
    def winId(self):
        if QWidget:
            return super().winId()
        return None
    
    def play(self):
        self.is_playing = True
        if self._use_qt_multimedia and self._media_player:
            self._media_player.play()
            if hasattr(self, 'play_btn') and QStyle:
                self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        elif self.reader_thread:
            self.reader_thread.resume()
            if hasattr(self, 'play_btn') and QStyle:
                self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))