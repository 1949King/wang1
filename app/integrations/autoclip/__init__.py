# AutoClip 集成模块
import logging

logger = logging.getLogger(__name__)


class AutoClipIntegration:
    """AutoClip集成类，提供高光识别和批量处理功能"""
    
    def __init__(self):
        """初始化AutoClip集成"""
        self.initialized = False
        self.initialize()
    
    def initialize(self):
        """初始化AutoClip"""
        try:
            # 导入必要的库
            import moviepy.editor as mp
            import os
            import tempfile
            import re
            import requests
            from bs4 import BeautifulSoup
            
            self.initialized = True
            print("AutoClip初始化成功")
        except Exception as e:
            print(f"AutoClip初始化失败: {e}")
            self.initialized = False
    
    def extract_highlights(self, video_path, **kwargs):
        """提取视频高光片段
        
        Args:
            video_path: 视频文件路径或平台链接
            **kwargs: 额外参数
                duration_threshold: 片段最小时长
                intensity_threshold: 高光强度阈值
                max_highlights: 最大高光片段数
                output_format: 输出格式
                output_path: 输出路径
        """
        if not self.initialized:
            raise Exception("AutoClip未初始化")
        
        try:
            import moviepy.editor as mp
            import os
            import tempfile
            import re
            import requests
            from bs4 import BeautifulSoup
            
            # 提取参数
            duration_threshold = kwargs.get("duration_threshold", 3.0)
            intensity_threshold = kwargs.get("intensity_threshold", 0.6)
            max_highlights = kwargs.get("max_highlights", 5)
            output_format = kwargs.get("output_format", "mp4")
            output_path = kwargs.get("output_path", None)
            
            # 检查是否为平台链接
            is_url = re.match(r'https?://', video_path)
            if is_url:
                # 解析平台链接
                video_path = self._parse_platform_link(video_path)
            
            # 如果没有指定输出路径，生成默认路径
            if not output_path:
                base_name = os.path.basename(video_path)
                name_without_ext = os.path.splitext(base_name)[0]
                output_path = os.path.join("短剧AI剪辑输出", f"{name_without_ext}_highlights.{output_format}")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 加载视频
            video = mp.VideoFileClip(video_path)
            video_duration = video.duration
            
            # 分析视频，提取高光片段
            highlights = self._detect_highlights(video, duration_threshold, intensity_threshold, max_highlights)
            
            # 提取高光片段
            clips = []
            for highlight in highlights:
                start = highlight["start"]
                end = highlight["end"]
                clip = video.subclip(start, end)
                clips.append(clip)
            
            # 合并片段
            if clips:
                edited_video = mp.concatenate_videoclips(clips)
                
                # 导出视频
                edited_video.write_videofile(output_path, codec="libx264", audio_codec="aac")
                
                return {
                    "success": True,
                    "output_path": output_path,
                    "highlights": highlights,
                    "total_highlights": len(highlights)
                }
            else:
                return {
                    "success": False,
                    "error": "未检测到高光片段"
                }
                
        except Exception as e:
            print(f"提取高光片段失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def batch_process(self, video_paths, **kwargs):
        """批量处理视频
        
        Args:
            video_paths: 视频文件路径列表
            **kwargs: 额外参数
                process_type: 处理类型 (highlights, edit, format)
                output_format: 输出格式
                output_dir: 输出目录
        """
        if not self.initialized:
            raise Exception("AutoClip未初始化")
        
        try:
            import os
            
            # 提取参数
            process_type = kwargs.get("process_type", "highlights")
            output_format = kwargs.get("output_format", "mp4")
            output_dir = kwargs.get("output_dir", "短剧AI剪辑输出")
            
            # 确保输出目录存在
            os.makedirs(output_dir, exist_ok=True)
            
            # 处理每个视频
            results = []
            for i, video_path in enumerate(video_paths):
                print(f"处理视频 {i+1}/{len(video_paths)}: {video_path}")
                
                # 生成输出路径
                base_name = os.path.basename(video_path)
                name_without_ext = os.path.splitext(base_name)[0]
                output_path = os.path.join(output_dir, f"{name_without_ext}_processed.{output_format}")
                
                # 根据处理类型调用相应的方法
                if process_type == "highlights":
                    result = self.extract_highlights(video_path, output_format=output_format, output_path=output_path)
                elif process_type == "edit":
                    result = self.auto_edit(video_path, output_format=output_format, output_path=output_path)
                elif process_type == "format":
                    result = self.convert_format(video_path, output_format=output_format, output_path=output_path)
                else:
                    result = {
                        "success": False,
                        "error": f"未知的处理类型: {process_type}"
                    }
                
                results.append(result)
            
            return {
                "success": True,
                "results": results,
                "total_processed": len(results),
                "successful_processes": sum(1 for r in results if r.get("success", False))
            }
            
        except Exception as e:
            print(f"批量处理失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def auto_edit(self, video_path, **kwargs):
        """自动编辑视频
        
        Args:
            video_path: 视频文件路径
            **kwargs: 额外参数
                output_format: 输出格式
                output_path: 输出路径
        """
        if not self.initialized:
            raise Exception("AutoClip未初始化")
        
        try:
            import moviepy.editor as mp
            import os
            
            # 提取参数
            output_format = kwargs.get("output_format", "mp4")
            output_path = kwargs.get("output_path", None)
            
            # 如果没有指定输出路径，生成默认路径
            if not output_path:
                base_name = os.path.basename(video_path)
                name_without_ext = os.path.splitext(base_name)[0]
                output_path = os.path.join("短剧AI剪辑输出", f"{name_without_ext}_edited.{output_format}")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 加载视频
            video = mp.VideoFileClip(video_path)
            
            # 提取高光片段
            highlights = self._detect_highlights(video, 3.0, 0.6, 5)
            
            # 提取高光片段
            clips = []
            for highlight in highlights:
                start = highlight["start"]
                end = highlight["end"]
                clip = video.subclip(start, end)
                clips.append(clip)
            
            # 合并片段
            if clips:
                edited_video = mp.concatenate_videoclips(clips)
                
                # 导出视频
                edited_video.write_videofile(output_path, codec="libx264", audio_codec="aac")
                
                return {
                    "success": True,
                    "output_path": output_path,
                    "highlights": highlights
                }
            else:
                return {
                    "success": False,
                    "error": "未检测到高光片段"
                }
                
        except Exception as e:
            print(f"自动编辑失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def convert_format(self, video_path, **kwargs):
        """转换视频格式
        
        Args:
            video_path: 视频文件路径
            **kwargs: 额外参数
                output_format: 输出格式
                output_path: 输出路径
        """
        if not self.initialized:
            raise Exception("AutoClip未初始化")
        
        try:
            import moviepy.editor as mp
            import os
            
            # 提取参数
            output_format = kwargs.get("output_format", "mp4")
            output_path = kwargs.get("output_path", None)
            
            # 如果没有指定输出路径，生成默认路径
            if not output_path:
                base_name = os.path.basename(video_path)
                name_without_ext = os.path.splitext(base_name)[0]
                output_path = os.path.join("短剧AI剪辑输出", f"{name_without_ext}.{output_format}")
            
            # 确保输出目录存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # 加载视频
            video = mp.VideoFileClip(video_path)
            
            # 导出视频
            video.write_videofile(output_path, codec="libx264", audio_codec="aac")
            
            return {
                "success": True,
                "output_path": output_path
            }
            
        except Exception as e:
            print(f"格式转换失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _detect_highlights(self, video, duration_threshold, intensity_threshold, max_highlights):
        """检测高光片段 - 多维特征融合的智能高光检测算法

        检测维度:
          1. 视觉运动分析 (帧差法) — 动作场景/打斗/追逐
          2. 音频能量分析 (RMS) — 高能时刻/欢呼/爆炸
          3. 场景切换检测 (直方图差) — 转场密集 = 节奏快
          4. 面部/人物检测 — 有人物特写的片段更重要
          5. 综合加权评分 — 多维度融合排序
        """
        import numpy as np
        try:
            import cv2
            CV2_AVAILABLE = True
        except ImportError:
            CV2_AVAILABLE = False

        video_duration = video.duration
        seg_samples = min(50, max(10, int(video_duration)))
        seg_dur = max(1.0, video_duration / seg_samples)

        # ── 初始化多维评分矩阵 ──
        scores = {
            "motion": np.zeros(seg_samples),
            "audio": np.zeros(seg_samples),
            "scene_change": np.zeros(seg_samples),
            "face": np.zeros(seg_samples),
            "composite": np.zeros(seg_samples),
        }

        # ── 维度1: 视觉运动分析 ──
        if CV2_AVAILABLE and hasattr(video, 'filename') and video.filename:
            cap = cv2.VideoCapture(video.filename)
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                window_frames = max(1, int(seg_dur * fps))

                prev_seg_last_frame = None
                for i in range(seg_samples):
                    frame_idx = int(i * seg_dur * fps)
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    motion_sum = 0.0
                    prev_frame = None
                    sample_count = 0
                    hist_diffs = []
                    seg_first_frame = None

                    for j in range(0, window_frames, 3):
                        ret, frame = cap.read()
                        if not ret:
                            break
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        gray_small = cv2.resize(gray, (160, 90))

                        # 运动检测
                        if prev_frame is not None:
                            diff = np.mean(np.abs(
                                gray_small.astype(float) - prev_frame.astype(float)
                            ))
                            motion_sum += diff
                            sample_count += 1
                        prev_frame = gray_small

                        # 保存第一帧用于场景切换检测
                        if seg_first_frame is None:
                            seg_first_frame = gray_small

                    # 场景切换检测: 段间直方图差异
                    if prev_seg_last_frame is not None and seg_first_frame is not None:
                        hist_diff = np.mean(np.abs(
                            seg_first_frame.astype(float) - prev_seg_last_frame.astype(float)
                        ))
                        scores["scene_change"][i] = min(1.0, hist_diff / 128.0)

                    prev_seg_last_frame = prev_frame

                    scores["motion"][i] = motion_sum / max(1, sample_count) / 255.0

                cap.release()

        # ── 维度2: 音频能量分析 ──
        try:
            audio = video.audio
            if audio is not None:
                audio_array = audio.to_soundarray()
                if len(audio_array.shape) > 1:
                    audio_array = audio_array.mean(axis=1)
                audio_sr = audio.fps

                for i in range(seg_samples):
                    seg_start_sample = int(i * seg_dur * audio_sr)
                    seg_end_sample = int((i + 1) * seg_dur * audio_sr)
                    seg_audio = audio_array[
                        seg_start_sample : min(seg_end_sample, len(audio_array))
                    ]
                    if len(seg_audio) > 0:
                        # 综合: 峰值能量 + 变化率
                        rms = np.sqrt(np.mean(seg_audio ** 2))
                        peak = np.max(np.abs(seg_audio))
                        # 音频动态范围指示"精彩程度"
                        dynamic_range = np.std(seg_audio) if len(seg_audio) > 1 else 0
                        scores["audio"][i] = min(1.0, (rms * 0.5 + peak * 0.3 + dynamic_range * 0.2) * 3)
        except Exception as e:
            logger.debug(f"音频能量分析失败，跳过音频维度评分: {e}")

        # ── 维度3: 面部检测 (有人物特写 → 高权重) ──
        if CV2_AVAILABLE and hasattr(video, 'filename') and video.filename:
            try:
                face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                )
                cap2 = cv2.VideoCapture(video.filename)
                if cap2.isOpened() and not face_cascade.empty():
                    fps2 = cap2.get(cv2.CAP_PROP_FPS) or 30.0
                    for i in range(seg_samples):
                        mid_frame_idx = int((i + 0.5) * seg_dur * fps2)
                        cap2.set(cv2.CAP_PROP_POS_FRAMES, mid_frame_idx)
                        ret, frame = cap2.read()
                        if ret:
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            faces = face_cascade.detectMultiScale(
                                gray, scaleFactor=1.1, minNeighbors=5,
                                minSize=(60, 60)
                            )
                            if len(faces) > 0:
                                # 人脸面积占比 → 特写程度
                                h, w = gray.shape
                                best_face = max(faces, key=lambda r: r[2] * r[3])
                                face_area_ratio = (best_face[2] * best_face[3]) / (h * w)
                                scores["face"][i] = min(1.0, face_area_ratio * 20)
                    cap2.release()
            except Exception as e:
                logger.debug(f"面部检测失败，跳过面部维度评分: {e}")

        # ── 归一化各维度 ──
        for key in ["motion", "audio", "scene_change", "face"]:
            max_val = np.max(scores[key])
            if max_val > 0:
                scores[key] = scores[key] / max_val

        # ── 维度4: 综合加权评分 ──
        # 权重: 运动40% + 音频25% + 场景切换15% + 面部检测20%
        weights = {"motion": 0.40, "audio": 0.25, "scene_change": 0.15, "face": 0.20}
        scores["composite"] = sum(
            scores[key] * weights[key]
            for key in weights
        )

        # ── 双标准筛选 (峰值 + 多样性) ──
        segments = []
        for i in range(seg_samples):
            seg_start = i * seg_dur
            seg_end = min((i + 1) * seg_dur, video_duration)
            segments.append({
                "start": seg_start,
                "end": seg_end,
                "intensity": round(float(scores["composite"][i]), 3),
                "motion": round(float(scores["motion"][i]), 3),
                "audio": round(float(scores["audio"][i]), 3),
                "faces": round(float(scores["face"][i]), 3),
            })

        # 按综合评分排序
        segments.sort(key=lambda x: x["intensity"], reverse=True)

        # 多样性选择: 避免相邻片段全部入选
        selected = []
        occupied_ranges = []  # 已选片段的时间区间

        for seg in segments:
            if len(selected) >= max_highlights:
                break
            if seg["intensity"] < intensity_threshold * 0.3:
                continue

            # 检查是否与已选片段时间重叠
            overlap = False
            for start_e, end_e in occupied_ranges:
                if seg["start"] < end_e and seg["end"] > start_e:
                    # 重叠超过50%则跳过
                    overlap_dur = min(seg["end"], end_e) - max(seg["start"], start_e)
                    if overlap_dur > 0 and overlap_dur / seg_dur > 0.5:
                        overlap = True
                        break
            if not overlap:
                selected.append(seg)
                occupied_ranges.append((seg["start"], seg["end"]))

        # 按时间排序
        selected.sort(key=lambda x: x["start"])

        return selected

    def _parse_platform_link(self, url):
        """解析平台链接 - 尝试下载视频"""
        temp_video_path = os.path.join("短剧AI剪辑输出", "downloaded_video.mp4")
        os.makedirs(os.path.dirname(temp_video_path), exist_ok=True)
        try:
            result = subprocess.run([
                "yt-dlp", "-f", "best", "-o", temp_video_path, url,
                "--no-playlist", "--max-filesize", "500M"
            ], capture_output=True, text=True, timeout=120,
               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            if result.returncode == 0 and os.path.exists(temp_video_path):
                print(f"视频下载成功: {temp_video_path}")
                return temp_video_path
        except Exception as e:
            print(f"yt-dlp下载失败: {e}")
        try:
            import requests
            resp = requests.get(url, stream=True, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            if resp.status_code == 200 and 'video' in resp.headers.get('Content-Type', ''):
                with open(temp_video_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"视频直链下载成功: {temp_video_path}")
                return temp_video_path
        except Exception as e:
            print(f"HTTP下载失败: {e}")
        print(f"无法解析平台链接: {url}")
        return url

# 创建AutoClip实例
autoclip_integration = AutoClipIntegration()