import json
import os
from config import OUTPUT_PATH
from modules.utils.logger import logger

class AITools:
    def __init__(self):
        # 尝试导入cv2和numpy，用于视频处理
        self.cv2 = None
        self.np = None
        try:
            import cv2
            import numpy as np
            self.cv2 = cv2
            self.np = np
        except ImportError:
            logger.warning("缺少cv2或numpy模块，视频处理功能将不可用")
    
    def detect_highlights(self, video_path, threshold=0.7):
        """检测视频中的精彩片段"""
        if not self.cv2 or not self.np:
            logger.error("缺少必要的视频处理模块")
            return []
        
        cap = self.cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"无法打开视频文件: {video_path}")
            return []
        
        highlights = []
        fps = cap.get(self.cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(self.cv2.CAP_PROP_FRAME_COUNT))
        frame_interval = int(fps * 1)  # 每秒检测一帧
        
        current_frame = 0
        while current_frame < total_frames:
            cap.set(self.cv2.CAP_PROP_POS_FRAMES, current_frame)
            ret, frame = cap.read()
            if not ret:
                break
            
            # 计算帧的活跃度（边缘检测）
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            edges = self.cv2.Canny(gray, 50, 150)
            activity = self.np.sum(edges) / (frame.shape[0] * frame.shape[1])
            
            # 如果活跃度超过阈值，标记为精彩片段
            if activity > threshold:
                start_time = current_frame / fps
                end_frame = current_frame
                while end_frame < total_frames and activity > threshold:
                    end_frame += frame_interval
                    cap.set(self.cv2.CAP_PROP_POS_FRAMES, end_frame)
                    ret, frame = cap.read()
                    if ret:
                        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
                        edges = self.cv2.Canny(gray, 50, 150)
                        activity = self.np.sum(edges) / (frame.shape[0] * frame.shape[1])
                    else:
                        break
                end_time = end_frame / fps
                highlights.append((start_time, end_time))
            
            current_frame += frame_interval
        
        cap.release()
        logger.info(f"检测到 {len(highlights)} 个精彩片段")
        return highlights
    
    def auto_layout_subtitles(self, subtitle_path):
        """一键排版字幕"""
        if not os.path.exists(subtitle_path):
            logger.error(f"字幕文件不存在: {subtitle_path}")
            return False
        
        # 读取字幕文件
        with open(subtitle_path, "r", encoding="utf-8") as f:
            subtitles = json.load(f)
        
        # 自动调整字幕位置和样式
        for subtitle in subtitles:
            # 设置默认位置（底部居中）
            subtitle["position"] = {"x": 0.5, "y": 0.9, "anchor": "center"}
            # 设置默认样式
            subtitle["style"] = {
                "font": "微软雅黑",
                "font_size": 24,
                "color": "#FFFFFF",
                "stroke_color": "#000000",
                "stroke_width": 2
            }
        
        # 保存排版后的字幕
        output_path = os.path.join(OUTPUT_PATH, "auto_layout_subtitles.json")
        os.makedirs(OUTPUT_PATH, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(subtitles, f, ensure_ascii=False, indent=2)
        
        logger.info(f"字幕排版成功: {output_path}")
        return True