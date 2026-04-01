import os 
import threading 
import tkinter as tk 
from tkinter import ttk, filedialog, messagebox 
from .plugin_system import BasePlugin

# 条件导入
cv2 = None
np = None
Image = None
ImageTk = None
VideoFileClip = None

# 尝试导入依赖
try:
    import cv2
    import numpy as np
    from PIL import Image, ImageTk
    from moviepy.editor import VideoFileClip
except ImportError as e:
    print(f"警告: 缺少依赖模块: {e}")
    print("插件将在运行时提示缺少依赖") 

class FullVideoEditorPlugin(BasePlugin): 
    def get_name(self): 
        return "视频编辑器（可正常预览播放）" 

    def __init__(self): 
        self.current_clip = None 
        self.playing = False 
        self.cap = None 
        self.preview_thread = None 

    def run(self, *args, **kwargs): 
        # 检查依赖
        if not all([cv2, np, Image, ImageTk, VideoFileClip]):
            messagebox.showerror("错误", "缺少必要的依赖模块，请安装：\n- opencv-python (cv2)\n- numpy (np)\n- Pillow (PIL)\n- moviepy")
            return

        self.win = tk.Toplevel() 
        self.win.title("视频编辑器 - 正常预览播放") 
        self.win.geometry("900x600") 

        # 预览画布 
        self.canvas = tk.Canvas(self.win, bg="black") 
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10) 

        # 控制栏 
        bar = ttk.Frame(self.win) 
        bar.pack(fill=tk.X, padx=10, pady=5) 

        ttk.Button(bar, text="导入视频", command=self.load_video).pack(side=tk.LEFT, padx=5) 
        ttk.Button(bar, text="▶ 播放", command=self.start_play).pack(side=tk.LEFT, padx=5) 
        ttk.Button(bar, text="⏸ 暂停", command=self.pause_play).pack(side=tk.LEFT, padx=5) 

    def load_video(self): 
        path = filedialog.askopenfilename(filetypes=[("视频文件", "*.mp4 *.mov *.avi *.mkv")]) 
        if not path: 
            return 

        self.current_clip = VideoFileClip(path) 
        self.video_path = path 
        messagebox.showinfo("成功", "视频已加载，可以播放预览") 

    def start_play(self): 
        if not hasattr(self, "video_path"): 
            messagebox.showwarning("提示", "先导入视频") 
            return 
        if self.playing: 
            return 

        self.playing = True 

        def play(): 
            self.cap = cv2.VideoCapture(self.video_path) 
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 30 
            delay = int(1000 / fps) 

            while self.playing and self.cap.isOpened(): 
                ret, frame = self.cap.read() 
                if not ret: 
                    break 

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) 
                h, w = frame.shape[:2] 
                cw = self.canvas.winfo_width() 
                ch = self.canvas.winfo_height() 
                scale = min(cw / w, ch / h) 
                nw, nh = int(w * scale), int(h * scale) 
                frame = cv2.resize(frame, (nw, nh)) 

                img = ImageTk.PhotoImage(Image.fromarray(frame)) 
                self.canvas.img = img 
                self.canvas.delete("all") 
                self.canvas.create_image(cw//2, ch//2, image=img, anchor=tk.CENTER) 
                cv2.waitKey(delay) 

            self.cap.release() 
            self.playing = False 

        self.preview_thread = threading.Thread(target=play) 
        self.preview_thread.start() 

    def pause_play(self): 
        self.playing = False 
        if self.cap: 
            self.cap.release() 
