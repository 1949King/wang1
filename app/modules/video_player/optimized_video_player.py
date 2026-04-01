import threading 
import time 
import os

# 条件导入
cv2 = None
np = None
Image = None
ImageQt = None
QPixmap = None
QImage = None
Qt = None
QTimer = None
pyqtSignal = None
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

# 尝试导入依赖
try:
    import cv2
    import numpy as np
    from PIL import Image, ImageQt
    from PyQt5.QtGui import QPixmap, QImage
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
    from PyQt5.QtWidgets import (QLabel, QSlider, QPushButton, QHBoxLayout,
                                  QVBoxLayout, QWidget, QComboBox, QStyle,
                                  QApplication)
    print("✓ 视频播放器依赖导入成功")
except Exception as e:
    print(f"警告: 缺少视频播放器依赖: {e}")
    print("视频播放器将在运行时提示缺少依赖") 

# ==================== 帧读取线程（避免UI阻塞）==================== 
class FrameReaderThread(QThread): 
    frame_signal = pyqtSignal(np.ndarray) if pyqtSignal else None  # 帧数据信号 
    finished_signal = pyqtSignal() if pyqtSignal else None          # 播放完成信号 
    error_signal = pyqtSignal(str) if pyqtSignal else None          # 错误信号 

    def __init__(self, video_path): 
        if QThread:
            super().__init__() 
        self.video_path = video_path 
        self.cap = None 
        self.is_playing = True 
        self.play_speed = 1.0  # 播放速度 
        self.current_frame = 0 
        self.total_frames = 0 
        self.fps = 30 

    def run(self): 
        if not cv2:
            if self.error_signal:
                self.error_signal.emit("缺少opencv-python依赖")
            return
            
        try: 
            # 初始化视频捕获（添加参数解决编码问题） 
            self.cap = cv2.VideoCapture(self.video_path) 
            if not self.cap.isOpened(): 
                if self.error_signal:
                    self.error_signal.emit("无法打开视频文件") 
                return 

            # 获取视频信息 
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) 
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30 
            frame_delay = 1 / self.fps  # 单帧间隔 

            # 循环读取帧 
            while self.is_playing and self.current_frame < self.total_frames: 
                ret, frame = self.cap.read() 
                if not ret: 
                    break 

                # 发送帧数据到UI线程 
                if self.frame_signal:
                    self.frame_signal.emit(frame) 
                self.current_frame += 1 

                # 按播放速度控制间隔 
                time.sleep(frame_delay / self.play_speed) 

            # 播放完成 
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
        """跳转到指定帧"""
        if self.cap and cv2 and 0 <= frame_idx < self.total_frames: 
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx) 
            self.current_frame = frame_idx 

    def stop(self): 
        self.is_playing = False 
        if QThread:
            self.quit() 
            self.wait() 

# ==================== 视频预览播放器（优化版）==================== 
class OptimizedVideoPlayer(QWidget): 
    def __init__(self, parent=None): 
        if QWidget:
            super().__init__(parent) 
            self.setStyleSheet("background-color: #1E1E2E;") 
        self.video_path = None 
        self.reader_thread = None 
        self.is_playing = False 
        self.volume = 0.8  # 音量（0.0-1.0）
        self.has_dependencies = all([QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QSlider, QComboBox, QStyle])
        if self.has_dependencies:
            self.init_ui() 
            self.init_signals() 

    def init_ui(self): 
        # 主布局 
        main_layout = QVBoxLayout(self) 
        main_layout.setContentsMargins(0, 0, 0, 0) 
        main_layout.setSpacing(8) 

        # 1. 视频预览区域 
        self.preview_label = QLabel() 
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #000000;
                border-radius: 8px;
                min-height: 300px;
            }
        """) 
        self.preview_label.setAlignment(Qt.AlignCenter) 
        self.preview_label.setText("📹 请导入视频文件") 
        main_layout.addWidget(self.preview_label) 

        # 2. 控制栏布局 
        control_layout = QHBoxLayout() 
        control_layout.setSpacing(10) 

        # 播放/暂停按钮 
        self.play_btn = QPushButton() 
        if QStyle:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay)) 
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

        # 进度条 
        self.progress_slider = QSlider(Qt.Horizontal) 
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

        # 播放速度 
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

        # 音量控制 
        self.volume_slider = QSlider(Qt.Horizontal) 
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

    def init_signals(self): 
        """初始化信号连接"""
        if self.has_dependencies:
            self.play_btn.clicked.connect(self.toggle_play) 
            self.speed_combo.currentTextChanged.connect(self.on_speed_change) 
            self.volume_slider.valueChanged.connect(self.on_volume_change) 
            self.progress_slider.sliderPressed.connect(self.on_progress_pressed) 
            self.progress_slider.sliderReleased.connect(self.on_progress_released) 

    def load_video(self, video_path): 
        """加载视频文件"""
        if not self.has_dependencies:
            if hasattr(self, 'preview_label'):
                self.preview_label.setText("❌ 缺少PyQt5依赖")
            return
            
        if not cv2:
            if hasattr(self, 'preview_label'):
                self.preview_label.setText("❌ 缺少opencv-python依赖")
            return
            
        self.video_path = video_path 
        self.is_playing = False 
        
        # 停止之前的线程 
        if self.reader_thread: 
            self.reader_thread.stop() 
            self.reader_thread = None 
        
        # 创建新的读取线程 
        self.reader_thread = FrameReaderThread(video_path) 
        if hasattr(self.reader_thread, 'frame_signal') and self.reader_thread.frame_signal:
            self.reader_thread.frame_signal.connect(self.update_frame) 
        if hasattr(self.reader_thread, 'finished_signal') and self.reader_thread.finished_signal:
            self.reader_thread.finished_signal.connect(self.on_play_finished) 
        if hasattr(self.reader_thread, 'error_signal') and self.reader_thread.error_signal:
            self.reader_thread.error_signal.connect(self.on_error) 
        
        # 更新UI 
        if hasattr(self, 'preview_label'):
            self.preview_label.setText(f"📹 加载中: {os.path.basename(video_path)}") 
        
        # 开始线程 
        self.reader_thread.start() 

    def toggle_play(self): 
        """切换播放/暂停状态"""
        if not self.reader_thread: 
            return 
        
        if self.is_playing: 
            # 暂停 
            self.reader_thread.pause() 
            if hasattr(self, 'play_btn') and QStyle:
                self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay)) 
        else: 
            # 播放 
            self.reader_thread.resume() 
            if hasattr(self, 'play_btn') and QStyle:
                self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause)) 
        
        self.is_playing = not self.is_playing 

    def update_frame(self, frame): 
        """更新视频帧"""
        if not all([cv2, QImage, QPixmap, Qt]):
            return
            
        try: 
            # 转换BGR为RGB 
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) 
            
            # 获取帧尺寸 
            h, w, ch = frame.shape 
            
            # 转换为QImage 
            bytes_per_line = ch * w 
            q_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888) 
            
            # 调整大小以适应预览区域 
            if hasattr(self, 'preview_label'):
                preview_size = self.preview_label.size() 
                scaled_image = q_image.scaled(preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation) 
                
                # 显示图像 
                self.preview_label.setPixmap(QPixmap.fromImage(scaled_image)) 
                
                # 更新进度条 
                if self.reader_thread and hasattr(self, 'progress_slider'): 
                    progress = int((self.reader_thread.current_frame / self.reader_thread.total_frames) * 1000) 
                    self.progress_slider.setValue(progress) 
        except Exception as e: 
            print(f"更新帧失败: {e}") 

    def on_speed_change(self, speed_text): 
        """处理播放速度变更"""
        if not self.reader_thread: 
            return 
        
        try: 
            speed = float(speed_text.replace('x', '')) 
            self.reader_thread.set_speed(speed) 
        except ValueError: 
            pass 

    def on_volume_change(self, value): 
        """处理音量变更"""
        self.volume = value / 100.0 

    def on_progress_pressed(self): 
        """进度条按下时暂停播放"""
        if self.reader_thread and self.is_playing: 
            self.reader_thread.pause() 

    def on_progress_released(self): 
        """进度条释放时跳转到指定位置"""
        if not self.reader_thread: 
            return 
        
        # 计算目标帧 
        if hasattr(self, 'progress_slider'):
            progress = self.progress_slider.value() / 1000.0 
            target_frame = int(progress * self.reader_thread.total_frames) 
            
            # 跳转到目标帧 
            self.reader_thread.seek(target_frame) 
            
            # 恢复播放（如果之前是播放状态）
            if self.is_playing: 
                self.reader_thread.resume() 

    def on_play_finished(self): 
        """播放完成处理"""
        self.is_playing = False 
        if hasattr(self, 'play_btn') and QStyle:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay)) 

    def on_error(self, error_msg): 
        """错误处理"""
        if hasattr(self, 'preview_label'):
            self.preview_label.setText(f"❌ 错误: {error_msg}") 
        self.is_playing = False 
        if hasattr(self, 'play_btn') and QStyle:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay)) 

    def closeEvent(self, event): 
        """关闭事件处理"""
        if self.reader_thread: 
            self.reader_thread.stop() 
        if event: 
            event.accept()
    
    def show(self):
        """显示播放器"""
        if QWidget:
            super().show()
    
    def resize(self, width, height):
        """调整播放器大小"""
        if QWidget:
            super().resize(width, height)
    
    def winId(self):
        """获取窗口ID"""
        if QWidget:
            return super().winId()
        return None
    
    def play(self):
        """开始播放视频"""
        if self.reader_thread:
            self.is_playing = True
            self.reader_thread.resume()
            if hasattr(self, 'play_btn') and QStyle:
                self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause)) 

# 导入必要的模块
import os
