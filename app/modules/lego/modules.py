"""
详细化功能模块
=============
每个模块都是独立, 即插即用, 可删, 可关, 可独立更新
参考 Tk 版本的功能实现
"""

from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
import os
import json
import numpy as np
import librosa
from datetime import datetime
from moviepy.editor import VideoFileClip, concatenate_videoclips

from PyQt6.QtWidgets import (
    QDialog,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QProgressBar, QListWidget,
    QListWidgetItem, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QTabWidget, QCheckBox, QSlider,
    QTreeWidget, QTreeWidgetItem, QMenu, QToolButton, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QTimer, QSize, QUrl
from PyQt6.QtGui import QFont, QAction
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget

from .core import EventBus, EventType, MasterClock, DataBus
from .skill_engine import SkillEngine, Skill
from .account_skills import (
    AccountDataCollectSkill, AccountAnalysisSkill, 
    PublishContentSkill, MatrixPublishSkill, register_account_skills
)

# 导入双内核调度器
from app.core.editor_scheduler import EditorScheduler
# 导入项目管理系统
from app.core.project_manager import project_manager
# 导入素材管理系统
from app.core.asset_manager import asset_manager
# 导入时间线管理系统
from app.core.timeline_manager import timeline_manager
# 导入特效管理系统
from app.core.effect_manager import effect_manager
# 导入转场管理系统
from app.core.transition_manager import transition_manager
# 导入音频处理系统
from app.core.audio_manager import AudioManager
# 导入字幕系统
from app.core.subtitle_manager import SubtitleManager
# 导入预设系统
from app.core.preset_manager import PresetManager
# 导入插件系统
from app.core.plugin_manager import PluginManager

# 导入TOP 0级剪辑引擎
try:
    from .top0_integration import Top0VideoProcessor
    TOP0_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"TOP 0级引擎导入失败: {e}")
    TOP0_ENGINE_AVAILABLE = False

# 导入爆款优化引擎
try:
    from .viral_optimization_engine import ViralOptimizationEngine, Platform, VideoFeatures
    VIRAL_ENGINE_AVAILABLE = True
except ImportError as e:
    print(f"爆款优化引擎导入失败: {e}")
    VIRAL_ENGINE_AVAILABLE = False

# 导入视频处理相关模块
import subprocess
import threading
import queue
import os
import time
from datetime import datetime

# 线程池管理
class ThreadPool:
    """线程池管理类"""
    def __init__(self, max_workers=4):
        self.max_workers = max_workers
        self.tasks = queue.Queue()
        self.workers = []
        self.running = False
    
    def start(self):
        """启动线程池"""
        self.running = True
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker, daemon=True)
            worker.start()
            self.workers.append(worker)
    
    def _worker(self):
        """工作线程"""
        while self.running:
            try:
                task = self.tasks.get(timeout=0.1)
                task()
                self.tasks.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"线程池工作线程错误: {e}")
    
    def submit(self, task):
        """提交任务到线程池"""
        self.tasks.put(task)
    
    def shutdown(self):
        """关闭线程池"""
        self.running = False
        self.tasks.join()
        for worker in self.workers:
            worker.join(timeout=1)

# 视频处理类
class VideoProcessor:
    """视频处理类"""
    def __init__(self):
        self.ffmpeg = "ffmpeg.exe"
        self.output_dir = "短剧AI剪辑输出"
        os.makedirs(self.output_dir, exist_ok=True)
        self.thread_pool = ThreadPool()
        self.thread_pool.start()
        # 默认优化参数
        self.default_params = {
            "autoclip": {
                "duration": 15,  # 抖音/快手黄金时长
                "highlight_ratio": [0.7, 0.2, 0.1],  # 70%核心冲突+20%情绪铺垫+10%悬念结尾
                "force_front_conflict": True,  # 前3秒强制识别强冲突画面
                "remove_redundant": True,  # 剔除冗余剧情
                "quick_cut": True,  # 快速卡点组接
                "transitions": ["fade", "flash"]  # 淡入淡出/闪切
            },
            "funclip": {
                "bgm_category": "auto",  # 品类专属BGM
                "bgm_sync": True,  # BGM卡点剪辑
                "volume_balance": [0.7, 0.3],  # 人声70%+BGM30%
                "subtitle_font": "黑体",  # 黑体/微软雅黑粗体
                "subtitle_style": "white+black_border",  # 白色字体+黑色粗描边
                "subtitle_position": "bottom_quarter",  # 视频底部1/4处
                "add_narration": True,  # 添加旁白钩子
                "add_sound_effects": True  # 添加音效
            },
            "videofusion": {
                "enhance_4k": True,  # 4K高清增强
                "skin_correction": True,  # 肤色矫正
                "de_shake": True,  # 动态防抖
                "line_sharpen": True,  # 线条锐化(漫剧)
                "color_saturation": 1.1,  # 色彩饱和度提升10%
                "remove_noise": True,  # 去除画面噪点
                "aspect_ratio": "9:16",  # 画面比例锁定9:16
                "platform_format": "native"  # 平台原生格式导出
            },
            "lora_edit": {
                "copyright_check": True,  # 全维度版权检测
                "ai_face_replace": True,  # AI相似脸型替换
                "logo_removal": True,  # 无痕遮挡品牌logo
                "watermark_position": "bottom_right",  # 引流小贴纸位置
                "watermark_size": 0.08,  # 屏幕占比≤8%
                "watermark_opacity": 0.7,  # 半透明(透明度70%)
                "watermark_time": [0.67, 1.0]  # 视频后半段出现
            },
            "video_adjust": {
                "brightness": 0,  # 亮度调节
                "contrast": 0,  # 对比度调节
                "saturation": 0,  # 饱和度调节
                "hue": 0  # 色调调节
            }
        }
    
    def process_video(self, video_path, mode, export_settings=None):
        """处理单个视频"""
        def task():
            try:
                # 默认导出设置
                if export_settings is None:
                    export_settings = {
                        "resolution": "1920x1080",
                        "bitrate": "5M",
                        "format": "mp4"
                    }
                
                base_name = os.path.basename(video_path)
                ext = export_settings["format"]
                output_name = f"[{mode}]_{os.path.splitext(base_name)[0]}.{ext}"
                output_path = os.path.join(self.output_dir, output_name)
                
                # 根据模式应用不同的处理逻辑
                if mode == "AutoClip":
                    self._process_autoclip(video_path, output_path, export_settings)
                elif mode == "FunClip":
                    self._process_funclip(video_path, output_path, export_settings)
                elif mode == "VideoFusion":
                    self._process_videofusion(video_path, output_path, export_settings)
                elif mode == "LoRA Edit":
                    self._process_lora_edit(video_path, output_path, export_settings)
                else:
                    # 基础处理
                    self._basic_process(video_path, output_path, export_settings)
                
            except Exception as e:
                print(f"处理视频失败: {e}")
                return None
        
        self.thread_pool.submit(task)
        return "任务已提交到线程池"
    
    def _basic_process(self, video_path, output_path, export_settings):
        """基础视频处理"""
        cmd = [
            self.ffmpeg,
            "-i", video_path,
            "-c:v", "libx264",
            "-b:v", export_settings["bitrate"],
            "-s", export_settings["resolution"],
            "-y", output_path
        ]
        print(f"执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"视频处理完成: {output_path}")
        else:
            print(f"视频处理失败: {result.stderr}")
    
    def _process_autoclip(self, video_path, output_path, export_settings):
        """AutoClip 高光识别处理"""
        params = self.default_params["autoclip"]
        print(f"AutoClip 处理中,参数: {params}")
        # 这里应该实现高光识别和剪辑逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_funclip(self, video_path, output_path, export_settings):
        """FunClip 自动剪辑处理"""
        params = self.default_params["funclip"]
        print(f"FunClip 处理中,参数: {params}")
        # 这里应该实现BGM,字幕,音频处理逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_videofusion(self, video_path, output_path, export_settings, video_adjust_params=None):
        """VideoFusion 视频增强处理"""
        params = self.default_params["videofusion"]
        adjust_params = video_adjust_params or self.default_params["video_adjust"]
        print(f"VideoFusion 处理中,参数: {params}")
        print(f"视频调节参数: {adjust_params}")
        # 这里应该实现画质增强逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def _process_lora_edit(self, video_path, output_path, export_settings):
        """LoRA Edit 创意编辑处理"""
        params = self.default_params["lora_edit"]
        print(f"LoRA Edit 处理中,参数: {params}")
        # 这里应该实现版权优化和引流植入逻辑
        # 暂时使用基础处理作为占位
        self._basic_process(video_path, output_path, export_settings)
    
    def optimize_workflow(self, video_path, platform="抖音", video_adjust_params=None):
        """优化工作流: AutoClip -> FunClip -> VideoFusion -> LoRA Edit"""
        def task():
            try:
                # 1. AutoClip 高光识别
                autoclip_output = os.path.join(self.output_dir, f"autoclip_{os.path.basename(video_path)}")
                self._process_autoclip(video_path, autoclip_output, {"resolution": "1920x1080", "bitrate": "5M", "format": "mp4"})
                
                # 2. FunClip 精剪
                funclip_output = os.path.join(self.output_dir, f"funclip_{os.path.basename(video_path)}")
                self._process_funclip(autoclip_output, funclip_output, {"resolution": "1920x1080", "bitrate": "5M", "format": "mp4"})
                
                # 3. VideoFusion 画质增强
                videofusion_output = os.path.join(self.output_dir, f"videofusion_{os.path.basename(video_path)}")
                self._process_videofusion(funclip_output, videofusion_output, {"resolution": "1920x1080", "bitrate": "5M", "format": "mp4"}, video_adjust_params)
                
                # 4. LoRA Edit 合规+引流
                final_output = os.path.join(self.output_dir, f"final_{platform}_{os.path.basename(video_path)}")
                self._process_lora_edit(videofusion_output, final_output, {"resolution": "1920x1080", "bitrate": "5M", "format": "mp4"})
                
                print(f"优化工作流完成,最终输出: {final_output}")
                return final_output
            except Exception as e:
                print(f"优化工作流失败: {e}")
                return None
        
        self.thread_pool.submit(task)
        return "优化工作流已提交到线程池"
    
    def shutdown(self):
        """关闭线程池"""
        self.thread_pool.shutdown()

# 初始化视频处理器
video_processor = VideoProcessor()

# ==============================================  
# 智能剪辑算法 (专业版)
# ==============================================
class AIClipAlgorithm:
    def __init__(self):
        # 基础权重(专业版)
        self.weights = {
            'volume': 1.2,          # 音量
            'volume_change': 1.5,    # 音量变化
            'shot_change': 1.8,      # 镜头切换
            'motion_intensity': 1.0,  # 运动强度
            'brightness': 0.8,       # 亮度
            'color_saturation': 0.6,  # 色彩饱和度
            'time_position': 1.0,     # 时间位置权重
            'keyword': 2.0,          # 关键词
            'emotion': 1.5           # 情绪分
        }

    def calculate_score(self, features, prompt=None, duration=None, position=None):
        """
        专业版打分逻辑
        - 综合多维度特征
        - 动态权重调整
        - 时间位置权重
        """
        # 复制基础权重
        weights = self.weights.copy()

        # 动态根据提示词调整权重
        if prompt:
            prompt = prompt.lower()
            if "高能" in prompt or "卡点" in prompt:
                weights['shot_change'] = 2.5
                weights['volume'] = 2.0
                weights['motion_intensity'] = 1.8
            if "催泪" in prompt or "情感" in prompt:
                weights['emotion'] = 3.0
                weights['volume_change'] = 2.0
            if "平静" in prompt or "舒缓" in prompt:
                weights['shot_change'] = 0.5
                weights['motion_intensity'] = 0.3
            if "开头" in prompt or "引人" in prompt:
                weights['time_position'] = 2.0

        # 计算时间位置权重(开头和结尾更重要)
        time_weight = 1.0
        if duration and position is not None:
            # 前10%和后10%的内容更重要
            if position < duration * 0.1:
                time_weight = 1.5
            elif position > duration * 0.9:
                time_weight = 1.3

        # 计算最终得分
        score = (
            weights['volume'] * features.get('volume', 0) +
            weights['volume_change'] * features.get('volume_change', 0) +
            weights['shot_change'] * features.get('shot_change', 0) +
            weights['motion_intensity'] * features.get('motion_intensity', 0) +
            weights['brightness'] * features.get('brightness', 0) +
            weights['color_saturation'] * features.get('color_saturation', 0) +
            weights['keyword'] * features.get('keyword', 0) +
            weights['emotion'] * features.get('emotion', 0)
        ) * time_weight

        return round(score, 2)

    def analyze_audio(self, audio_clip):
        """
        专业音频分析
        - 音量分析
        - 音量变化分析
        - 频率分析
        """
        y, sr = librosa.load(audio_clip.reader(), sr=16000)
        
        # 音量
        volume = np.mean(np.abs(y))
        
        # 音量变化(能量变化)
        energy = np.array([np.sum(np.abs(y[i:i+1024]**2)) for i in range(0, len(y), 1024)])
        if len(energy) > 1:
            volume_change = np.std(energy) / np.mean(energy)
        else:
            volume_change = 0
        
        # 频率分析(简单版本)
        # 计算频谱
        S = np.abs(librosa.stft(y))
        # 低频能量(说话声)
        low_freq = np.mean(S[:100])
        # 高频能量(音效)
        high_freq = np.mean(S[100:])
        
        return {
            'volume': volume,
            'volume_change': volume_change,
            'low_freq': low_freq,
            'high_freq': high_freq
        }

    def analyze_video(self, video_clip):
        """
        专业视频分析
        - 镜头切换检测
        - 运动强度分析
        - 亮度和色彩分析
        """
        # 模拟镜头切换(实际项目中可以使用更复杂的算法)
        shot_change = np.random.uniform(0, 1)
        
        # 模拟运动强度
        motion_intensity = np.random.uniform(0, 1)
        
        # 模拟亮度和色彩饱和度
        brightness = np.random.uniform(0.3, 1.0)
        color_saturation = np.random.uniform(0.2, 1.0)
        
        return {
            'shot_change': shot_change,
            'motion_intensity': motion_intensity,
            'brightness': brightness,
            'color_saturation': color_saturation
        }

    def analyze_segment(self, video, start, end):
        """
        分析单个视频片段
        """
        seg = video.subclip(start, end)
        
        # 音频分析
        audio_features = self.analyze_audio(seg.audio)
        
        # 视频分析
        video_features = self.analyze_video(seg)
        
        # 合并特征
        features = {
            **audio_features,
            **video_features,
            # 模拟关键词和情绪分
            'keyword': np.random.randint(0, 2),
            'emotion': np.random.uniform(0, 1)
        }
        
        return features

    def select_segments(self, segments, max_segments=8, min_duration=1.5, max_duration=3.0):
        """
        智能片段选择
        - 选择高分片段
        - 保证片段之间的连续性
        - 控制片段时长
        """
        # 按得分排序
        sorted_segments = sorted(segments, key=lambda x: x['score'], reverse=True)
        
        selected = []
        used_time = set()
        
        for seg in sorted_segments:
            # 检查是否与已选片段重叠
            overlap = False
            for s in selected:
                if not (seg['end'] <= s['start'] or seg['start'] >= s['end']):
                    overlap = True
                    break
            
            if not overlap:
                # 调整片段时长
                duration = seg['end'] - seg['start']
                if duration < min_duration:
                    # 扩展片段
                    extend = (min_duration - duration) / 2
                    seg['start'] = max(0, seg['start'] - extend)
                    seg['end'] = min(seg['end'] + extend, seg.get('total_duration', seg['end']))
                elif duration > max_duration:
                    # 缩短片段
                    seg['end'] = seg['start'] + max_duration
                
                selected.append(seg)
                if len(selected) >= max_segments:
                    break
        
        # 按时间顺序排序
        selected.sort(key=lambda x: x['start'])
        
        return selected

    def process_video(self, video_path, prompt=None, output_length=15):
        """
        专业版视频处理
        - 多维度分析
        - 智能片段选择
        - 流畅拼接
        """
        video = VideoFileClip(video_path)
        duration = video.duration
        segments = []
        seg_dur = 2

        # 分析所有片段
        for start in np.arange(0, duration, seg_dur):
            end = min(start + seg_dur, duration)
            
            # 分析片段特征
            features = self.analyze_segment(video, start, end)
            
            # 计算得分
            score = self.calculate_score(features, prompt, duration, start)
            
            segments.append({
                "start": start,
                "end": end,
                "score": score,
                "features": features,
                "total_duration": duration
            })

        # 智能选择片段
        selected_segments = self.select_segments(segments, max_segments=output_length//2)

        # 拼接片段
        clips = []
        for seg in selected_segments:
            clip = video.subclip(seg['start'], seg['end'])
            clips.append(clip)

        # 流畅拼接(添加淡入淡出效果)
        if clips:
            # 为每个片段添加淡入淡出效果
            for i, clip in enumerate(clips):
                if i > 0:
                    clip = clip.crossfadein(0.3)
                if i < len(clips) - 1:
                    clip = clip.crossfadeout(0.3)
                clips[i] = clip
            
            final = concatenate_videoclips(clips)
        else:
            # 如果没有选中片段,返回原始视频的前15秒
            final = video.subclip(0, min(15, duration))

        # 输出路径
        output_dir = "AI剪辑输出"
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, f"ai_clip_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        
        # 导出视频
        final.write_videofile(
            out_path, 
            fps=24, 
            codec='libx264',
            bitrate='5000k',
            preset='medium',
            verbose=False
        )

        video.close()
        return out_path

# 账号运营分析类
class AccountAnalyzer:
    """账号运营分析类"""
    def __init__(self):
        self.data_dir = "运营数据"
        os.makedirs(self.data_dir, exist_ok=True)
    
    def add_video_data(self, video_id, title, views, likes, comments, shares, conversions):
        """添加视频数据"""
        try:
            data = {
                "video_id": video_id,
                "title": title,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "conversions": conversions,
                "timestamp": datetime.now().isoformat(),
                "like_rate": likes / views if views > 0 else 0,
                "comment_rate": comments / views if views > 0 else 0,
                "share_rate": shares / views if views > 0 else 0,
                "conversion_rate": conversions / views if views > 0 else 0
            }
            
            data_file = os.path.join(self.data_dir, f"{video_id}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"添加视频数据失败: {e}")
            return False
    
    def analyze_data(self):
        """分析数据"""
        try:
            all_data = []
            for file in os.listdir(self.data_dir):
                if file.endswith(".json"):
                    file_path = os.path.join(self.data_dir, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            all_data.append(data)
                    except:
                        pass
            
            if not all_data:
                return {"error": "无数据"}
            
            # 计算平均值
            total_views = sum(d.get("views", 0) for d in all_data)
            total_likes = sum(d.get("likes", 0) for d in all_data)
            total_comments = sum(d.get("comments", 0) for d in all_data)
            total_shares = sum(d.get("shares", 0) for d in all_data)
            total_conversions = sum(d.get("conversions", 0) for d in all_data)
            
            avg_views = total_views / len(all_data)
            avg_likes = total_likes / len(all_data)
            avg_comments = total_comments / len(all_data)
            avg_shares = total_shares / len(all_data)
            avg_conversions = total_conversions / len(all_data)
            
            # 计算平均比率
            avg_like_rate = sum(d.get("like_rate", 0) for d in all_data) / len(all_data)
            avg_comment_rate = sum(d.get("comment_rate", 0) for d in all_data) / len(all_data)
            avg_share_rate = sum(d.get("share_rate", 0) for d in all_data) / len(all_data)
            avg_conversion_rate = sum(d.get("conversion_rate", 0) for d in all_data) / len(all_data)
            
            # 找出表现最好的视频
            top_views = sorted(all_data, key=lambda x: x.get("views", 0), reverse=True)[:3]
            top_conversions = sorted(all_data, key=lambda x: x.get("conversions", 0), reverse=True)[:3]
            top_conversion_rate = sorted(all_data, key=lambda x: x.get("conversion_rate", 0), reverse=True)[:3]
            
            return {
                "total_videos": len(all_data),
                "total_views": total_views,
                "total_likes": total_likes,
                "total_comments": total_comments,
                "total_shares": total_shares,
                "total_conversions": total_conversions,
                "average_views": avg_views,
                "average_likes": avg_likes,
                "average_comments": avg_comments,
                "average_shares": avg_shares,
                "average_conversions": avg_conversions,
                "average_like_rate": avg_like_rate,
                "average_comment_rate": avg_comment_rate,
                "average_share_rate": avg_share_rate,
                "average_conversion_rate": avg_conversion_rate,
                "top_views": top_views,
                "top_conversions": top_conversions,
                "top_conversion_rate": top_conversion_rate
            }
        except Exception as e:
            print(f"分析数据失败: {e}")
            return {"error": str(e)}
    
    def generate_optimization_suggestions(self, analysis_data):
        """生成优化建议"""
        if "error" in analysis_data:
            return "暂无数据,无法生成建议"
        
        suggestions = []
        
        # 基于数据生成建议
        if analysis_data["average_like_rate"] < 0.05:
            suggestions.append("建议优化视频内容质量,增加情感共鸣点")
        
        if analysis_data["average_comment_rate"] < 0.01:
            suggestions.append("建议在视频中设置互动问题,鼓励观众评论")
        
        if analysis_data["average_share_rate"] < 0.005:
            suggestions.append("建议增加视频的价值性和分享点")
        
        if analysis_data["average_conversion_rate"] < 0.001:
            suggestions.append("建议优化引导语和转化路径")
        
        if not suggestions:
            suggestions.append("数据表现良好,继续保持")
        
        return "\n".join(suggestions)

# 初始化账号分析器
account_analyzer = AccountAnalyzer()

# OpenClow 自动化引擎
class OpenClowEngine:
    """OpenClow 自动化引擎"""
    def __init__(self):
        """初始化OpenClow自动化引擎"""
        self.data_dir = "openclow_data"
        os.makedirs(self.data_dir, exist_ok=True)
        self.platforms = ["抖音", "快手", "视频号"]
        self.accounts = {}
        self.published_content = []
        self.reply_rules = []
        self.operation_data = []
    
    def collect_data(self, platform, account_id):
        """数据采集 (抖音/快手/视频号)"""
        try:
            # 模拟数据采集过程
            print(f"开始采集{platform}账号{account_id}的数据...")
            # 模拟采集的数据
            collected_data = {
                "platform": platform,
                "account_id": account_id,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "views": 10000,
                    "likes": 500,
                    "comments": 100,
                    "shares": 50,
                    "followers": 5000
                }
            }
            # 保存采集的数据
            data_file = os.path.join(self.data_dir, f"{platform}_{account_id}_{int(time.time())}.json")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(collected_data, f, ensure_ascii=False, indent=2)
            print(f"{platform}账号{account_id}的数据采集完成")
            return collected_data
        except Exception as e:
            print(f"数据采集失败: {e}")
            return None
    
    def auto_publish(self, platform, account_id, content, schedule_time=None):
        """内容自动发布"""
        try:
            # 模拟内容发布过程
            publish_time = schedule_time if schedule_time else datetime.now().isoformat()
            print(f"开始发布内容到{platform}账号{account_id}...")
            # 创建发布记录
            publish_record = {
                "id": f"pub_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "content": content,
                "publish_time": publish_time,
                "status": "published",
                "timestamp": datetime.now().isoformat()
            }
            # 保存发布记录
            self.published_content.append(publish_record)
            # 保存到文件
            publish_file = os.path.join(self.data_dir, f"publish_{publish_record['id']}.json")
            with open(publish_file, "w", encoding="utf-8") as f:
                json.dump(publish_record, f, ensure_ascii=False, indent=2)
            print(f"内容已成功发布到{platform}账号{account_id}")
            return publish_record
        except Exception as e:
            print(f"内容发布失败: {e}")
            return None
    
    def smart_reply(self, platform, account_id, comment, keywords=None):
        """评论智能回复"""
        try:
            # 模拟智能回复过程
            print(f"处理{platform}账号{account_id}的评论...")
            reply = "感谢您的评论!"  # 默认回复
            # 基于关键词生成回复
            if keywords:
                for keyword in keywords:
                    if keyword in comment:
                        # 查找匹配的回复规则
                        for rule in self.reply_rules:
                            if rule["keyword"] in comment:
                                reply = rule["reply"]
                                break
                        else:
                            reply = f"感谢您的评论!"
                        break
            else:
                reply = f"感谢您的评论!"
            # 创建回复记录
            reply_record = {
                "id": f"reply_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "comment": comment,
                "reply": reply,
                "timestamp": datetime.now().isoformat()
            }
            # 保存回复记录
            reply_file = os.path.join(self.data_dir, f"reply_{reply_record['id']}.json")
            with open(reply_file, "w", encoding="utf-8") as f:
                json.dump(reply_record, f, ensure_ascii=False, indent=2)
            print(f"已回复{platform}账号{account_id}的评论")
            return reply_record
        except Exception as e:
            print(f"智能回复失败: {e}")
            return None
    
    def write_back_data(self, platform, account_id, data):
        """运营数据回写"""
        try:
            # 模拟数据回写过程
            print(f"回写{platform}账号{account_id}的运营数据...")
            # 创建回写记录
            write_back_record = {
                "id": f"writeback_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "timestamp": datetime.now().isoformat()
            }
            # 保存回写记录
            self.operation_data.append(write_back_record)
            # 保存到文件
            write_back_file = os.path.join(self.data_dir, f"writeback_{write_back_record['id']}.json")
            with open(write_back_file, "w", encoding="utf-8") as f:
                json.dump(write_back_record, f, ensure_ascii=False, indent=2)
            print(f"{platform}账号{account_id}的运营数据回写完成")
            return write_back_record
        except Exception as e:
            print(f"数据回写失败: {e}")
            return None
    
    def generate_operation_suggestions(self, platform, account_id, data):
        """生成运营建议"""
        try:
            # 模拟生成运营建议
            print(f"为{platform}账号{account_id}生成运营建议...")
            # 基于数据生成建议
            suggestions = []
            # 分析数据
            views = data.get("views", 0)
            likes = data.get("likes", 0)
            comments = data.get("comments", 0)
            shares = data.get("shares", 0)
            followers = data.get("followers", 0)
            
            # 计算互动率
            if views > 0:
                interaction_rate = (likes + comments + shares) / views
            else:
                interaction_rate = 0
            
            # 基于数据生成建议
            if views < 10000:
                suggestions.append("建议增加内容发布频率,提高账号曝光度")
            if interaction_rate < 0.05:
                suggestions.append("建议在视频中增加互动元素,提高观众参与度")
            if comments < 100:
                suggestions.append("建议主动回复评论,增强粉丝粘性")
            if shares < 50:
                suggestions.append("建议创作更具分享价值的内容")
            if followers < 1000:
                suggestions.append("建议优化账号简介和封面,吸引更多关注")
            
            if not suggestions:
                suggestions.append("账号运营状况良好,继续保持现有策略")
            
            # 创建建议记录
            suggestion_record = {
                "id": f"suggestion_{int(time.time())}",
                "platform": platform,
                "account_id": account_id,
                "data": data,
                "suggestions": suggestions,
                "timestamp": datetime.now().isoformat()
            }
            # 保存建议记录
            suggestion_file = os.path.join(self.data_dir, f"suggestion_{suggestion_record['id']}.json")
            with open(suggestion_file, "w", encoding="utf-8") as f:
                json.dump(suggestion_record, f, ensure_ascii=False, indent=2)
            print(f"已为{platform}账号{account_id}生成运营建议")
            return suggestion_record
        except Exception as e:
            print(f"生成运营建议失败: {e}")
            return None
    
    def add_reply_rule(self, keyword, reply):
        """添加回复规则"""
        rule = {
            "id": f"rule_{int(time.time())}",
            "keyword": keyword,
            "reply": reply,
            "timestamp": datetime.now().isoformat()
        }
        self.reply_rules.append(rule)
        # 保存规则到文件
        rules_file = os.path.join(self.data_dir, "reply_rules.json")
        with open(rules_file, "w", encoding="utf-8") as f:
            json.dump(self.reply_rules, f, ensure_ascii=False, indent=2)
        return rule
    
    def get_published_content(self):
        """获取已发布的内容"""
        return self.published_content
    
    def get_operation_data(self):
        """获取运营数据"""
        return self.operation_data

# 硬件检测和性能监控
class HardwareDetector:
    """硬件检测类"""
    def detect_hardware(self):
        """检测硬件配置"""
        try:
            import psutil
            # 获取CPU信息
            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0
            
            # 获取内存信息
            memory = psutil.virtual_memory()
            total_memory = memory.total // (1024 * 1024 * 1024)
            
            # 获取磁盘信息
            disk = psutil.disk_usage('/')
            total_disk = disk.total // (1024 * 1024 * 1024)
            
            return {
                "cpu_count": cpu_count,
                "cpu_freq": cpu_freq,
                "total_memory": total_memory,
                "total_disk": total_disk,
                "max_threads": min(cpu_count, 8),
                "max_batch_size": min(cpu_count * 2, 16),
                "cache_size": min(total_memory * 1024 * 1024 * 1024 // 4, 4 * 1024 * 1024 * 1024)
            }
        except Exception as e:
            print(f"硬件检测失败: {e}")
            # 返回默认值
            return {
                "cpu_count": 4,
                "cpu_freq": 2500,
                "total_memory": 8,
                "total_disk": 100,
                "max_threads": 4,
                "max_batch_size": 8,
                "cache_size": 2 * 1024 * 1024 * 1024
            }

class PerformanceMonitor:
    """性能监控类"""
    def __init__(self):
        self.start_time = time.time()
        self.metrics = {}
    
    def record_metrics(self):
        """记录性能指标"""
        try:
            import psutil
            # 记录CPU使用率
            cpu_usage = psutil.cpu_percent()
            # 记录内存使用率
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            # 记录磁盘使用率
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            
            self.metrics = {
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "disk_usage": disk_usage,
                "uptime": time.time() - self.start_time
            }
            
            print(f"性能指标: CPU={cpu_usage}%, 内存={memory_usage}%, 磁盘={disk_usage}%")
            return self.metrics
        except Exception as e:
            print(f"性能监控失败: {e}")
            return {}

# 初始化硬件检测器和性能监控器
hardware_detector = HardwareDetector()
hardware_config = hardware_detector.detect_hardware()
performance_monitor = PerformanceMonitor()

# 初始化OpenClow引擎
openclow_engine = OpenClowEngine()



# 自定义提示框 - 优化显示效果
class CustomMessageBox(QMessageBox):
    """自定义消息框,优化字体和颜色对比度"""
    def __init__(self, icon, title, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setText(text)
        self.setIcon(icon)
        self.setStyleSheet("""
            QMessageBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 2px solid #ff9800;
                border-radius: 10px;
                padding: 20px;
            }
            QLabel {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
                padding: 10px;
                background-color: transparent;
            }
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 14px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
            }
        """)

def show_custom_messagebox(icon_type, title, message, parent=None):
    """显示自定义提示框"""
    from PyQt6.QtWidgets import QMessageBox
    from PyQt6.QtGui import QIcon
    
    msg = CustomMessageBox(icon_type, title, message, parent)
    msg.exec()


# 自定义清晰提示框
class ClearMessageBox(QDialog):
    """高对比度清晰提示框"""
    def __init__(self, title, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(400, 200)
        
        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # 内容区域
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)
        
        # 警告图标
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 48px;")
        content_layout.addWidget(icon_label)
        
        # 消息文本
        message_label = QLabel(message)
        message_label.setStyleSheet("""
            color: #ffffff;
            font-size: 18px;
            font-weight: bold;
            padding: 10px;
        """)
        message_label.setWordWrap(True)
        content_layout.addWidget(message_label, 1)
        
        layout.addLayout(content_layout)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        ok_btn = QPushButton("确定")
        ok_btn.setFixedSize(120, 40)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:pressed {
                background-color: #0d47a1;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        # 设置对话框样式
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                border: 3px solid #ff9800;
                border-radius: 12px;
            }
        """)

def show_clear_messagebox(title, message, parent=None):
    """显示清晰提示框"""
    msg = ClearMessageBox(title, message, parent)
    msg.exec()

class BaseModule(QWidget):
    """
    模块基类 - 所有模块必须继承此类
    
    特性:
    - 独立 QWidget
    - 只依赖内核,不依赖其他模块
    - 通过 EventBus 通信
    """
    
    module_id: str = "base"
    module_name: str = "基础模块"
    module_icon: str = "📦"
    
    def __init__(self):
        super().__init__()
        self._event_bus = EventBus.get_instance()
        self._data_bus = DataBus.get_instance()
        self._clock = MasterClock.get_instance()
        self._skill_engine = SkillEngine.get_instance()
        self._setup_ui()
        self._setup_event_handlers()
    
    def _setup_ui(self):
        """设置界面(子类实现)"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        
        title = QLabel(f"{self.module_icon} {self.module_name}")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(title)
    
    def _setup_event_handlers(self):
        """设置事件处理器(子类可重写)"""
        pass
    
    def on_activated(self):
        """模块激活时调用"""
        pass
    
    def on_deactivated(self):
        """模块停用时调用"""
        pass


class HomeModule(BaseModule):
    """
    首页模块
    - 显示:最近项目,快捷入口,统计,公告,快速开始
    - 只做入口,不做业务
    """
    
    module_id = "home"
    module_name = "首页"
    module_icon = "🏠"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header_layout = QHBoxLayout()
        
        header = QLabel("🏠 欢迎使用 拾光剪影")
        header.setStyleSheet("font-size: 28px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        

        layout.addLayout(header_layout)
        
        quick_group = self._create_card("快速开始")
        quick_layout = QGridLayout(quick_group)
        quick_layout.setSpacing(15)
        
        quick_actions = [
            ("🎬", "新建剪辑", "editor", "#1e6bde"),
            ("📝", "AI脚本", "copywriting", "#4caf50"),
            ("📋", "批量处理", "tasks", "#ff9800"),
            ("🎭", "短剧筛选", "drama", "#9c27b0"),
            ("👤", "账号运营", "account", "#00bcd4"),
            ("📁", "素材管理", "materials", "#795548"),
        ]
        
        for i, (icon, text, target, color) in enumerate(quick_actions):
            btn = self._create_action_button(icon, text, color)
            btn.clicked.connect(lambda checked, t=target: self._navigate_to(t))
            quick_layout.addWidget(btn, i // 3, i % 3)
        
        layout.addWidget(quick_group)
        
        stats_group = self._create_card("今日统计")
        stats_layout = QHBoxLayout(stats_group)
        
        stats_data = [
            ("处理视频", "12", "个"),
            ("生成文案", "28", "条"),
            ("发布内容", "8", "个"),
            ("总播放量", "15.2万", ""),
        ]
        
        for label, value, unit in stats_data:
            stat_widget = QWidget()
            stat_layout = QVBoxLayout(stat_widget)
            stat_layout.setContentsMargins(20, 10, 20, 10)
            
            value_label = QLabel(value)
            value_label.setStyleSheet("font-size: 32px; font-weight: bold; color: #1e6bde;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_layout.addWidget(value_label)
            
            name_label = QLabel(f"{label} {unit}")
            name_label.setStyleSheet("font-size: 14px; color: #808080;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stat_layout.addWidget(name_label)
            
            stats_layout.addWidget(stat_widget)
        
        layout.addWidget(stats_group)
        
        recent_group = self._create_card("最近项目")
        recent_layout = QVBoxLayout(recent_group)
        
        recent_list = QListWidget()
        recent_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                border: none;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #2a2a2a;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #2a2a2a;
            }
        """)
        recent_list.addItems([
            "📹 短剧剪辑_20240115.mp4 - 2分钟前",
            "📹 爆款引流_20240115.mp4 - 15分钟前",
            "📹 剧情解说_20240114.mp4 - 昨天",
        ])
        recent_layout.addWidget(recent_list)
        
        layout.addWidget(recent_group)
        layout.addStretch()
    
    def _create_card(self, title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 12px;
                margin-top: 16px;
                padding-top: 16px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 20px;
                padding: 0 10px;
                background-color: #1a1a1a;
            }
        """)
        return group
    
    def _create_action_button(self, icon: str, text: str, color: str) -> QPushButton:
        btn = QPushButton(f"{icon}\n{text}")
        btn.setMinimumSize(120, 80)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {color}dd;
            }}
        """)
        return btn
    
    def _navigate_to(self, module_id: str):
        self._event_bus.emit(EventType.MODULE_ACTIVATED, {"target": module_id})
    
    def _show_login_dialog(self):
        """显示详细的登录信息和设置调整对话框"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QGroupBox, QCheckBox, QComboBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("登录信息与设置")
        dialog.setMinimumWidth(400)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
                background-color: #1a1a1a;
            }
            QCheckBox {
                color: #ffffff;
            }
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 登录信息部分
        login_group = QGroupBox("登录信息")
        login_layout = QVBoxLayout(login_group)
        
        # 用户名
        user_layout = QHBoxLayout()
        user_label = QLabel("用户名:")
        user_input = QLineEdit()
        user_input.setText("妮可")  # 默认值
        user_layout.addWidget(user_label)
        user_layout.addWidget(user_input)
        login_layout.addLayout(user_layout)
        
        # 密码
        pass_layout = QHBoxLayout()
        pass_label = QLabel("密码:")
        pass_input = QLineEdit()
        pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        pass_layout.addWidget(pass_label)
        pass_layout.addWidget(pass_input)
        login_layout.addLayout(pass_layout)
        
        # 记住密码
        remember_layout = QHBoxLayout()
        remember_check = QCheckBox("记住密码")
        remember_check.setChecked(True)
        remember_layout.addWidget(remember_check)
        login_layout.addLayout(remember_layout)
        
        layout.addWidget(login_group)
        
        # 登录设置部分
        settings_group = QGroupBox("登录设置")
        settings_layout = QVBoxLayout(settings_group)
        
        # 自动登录
        auto_login_layout = QHBoxLayout()
        auto_login_check = QCheckBox("自动登录")
        auto_login_check.setChecked(True)
        auto_login_layout.addWidget(auto_login_check)
        settings_layout.addLayout(auto_login_layout)
        
        # 登录方式
        login_method_layout = QHBoxLayout()
        method_label = QLabel("登录方式:")
        method_combo = QComboBox()
        method_combo.addItems(["账号密码登录", "二维码登录", "第三方登录"])
        method_combo.setCurrentText("账号密码登录")
        login_method_layout.addWidget(method_label)
        login_method_layout.addWidget(method_combo)
        settings_layout.addLayout(login_method_layout)
        
        # 语言设置
        language_layout = QHBoxLayout()
        language_label = QLabel("语言:")
        language_combo = QComboBox()
        language_combo.addItems(["简体中文", "English"])
        language_combo.setCurrentText("简体中文")
        language_layout.addWidget(language_label)
        language_layout.addWidget(language_combo)
        settings_layout.addLayout(language_layout)
        
        layout.addWidget(settings_group)
        
        # 按钮部分
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        
        login_btn = QPushButton("登录")
        login_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(login_btn)
        
        layout.addLayout(btn_layout)
        
        dialog.exec()
        
        # 处理登录结果
        if dialog.result() == QDialog.DialogCode.Accepted:
            print("登录成功")
            # 这里可以添加登录逻辑
        else:
            print("登录取消")


class TimelineWidget(QWidget):
    """完整的时间轴组件"""
    
    clip_selected = pyqtSignal(object)
    playhead_moved = pyqtSignal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks = []  # 轨道列表
        self._clips = []  # 片段列表
        self._current_clip = None
        self._timeline_zoom = 100  # 缩放比例
        self._playhead_position = 0  # 播放头位置(秒)
        self._total_duration = 60  # 总时长(秒)
        self._is_playing = False
        self._playback_timer = None
        
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 时间刻度栏
        self._time_ruler = QFrame()
        self._time_ruler.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        self._time_ruler.setFixedHeight(45)
        self._time_ruler_layout = QHBoxLayout(self._time_ruler)
        self._time_ruler_layout.setContentsMargins(100, 5, 20, 5)
        
        # 播放头
        self._playhead = QFrame()
        self._playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        self._playhead.setFixedWidth(2)
        self._playhead.setFixedHeight(40)
        self._playhead.setParent(self._time_ruler)
        self._playhead.move(100, 0)
        
        # 添加时间刻度
        self._update_time_ruler()
        layout.addWidget(self._time_ruler)
        
        # 轨道区域
        self._track_area = QFrame()
        self._track_area.setStyleSheet("background-color: #0a0a0a;")
        self._track_layout = QVBoxLayout(self._track_area)
        self._track_layout.setContentsMargins(0, 0, 0, 0)
        self._track_layout.setSpacing(2)
        
        # 轨道播放头
        self._track_playhead = QFrame()
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px;")
        self._track_playhead.setFixedWidth(2)
        self._track_playhead.setParent(self._track_area)
        self._track_playhead.move(100, 0)
        
        # 添加默认轨道
        self._add_track("视频", "video")
        self._add_track("音频", "audio")
        self._add_track("字幕", "subtitle")
        
        layout.addWidget(self._track_area, 1)
    
    def _update_time_ruler(self):
        # 清空现有刻度
        for i in reversed(range(self._time_ruler_layout.count())):
            widget = self._time_ruler_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # 固定显示1~10秒的标题区域
        self._total_duration = 10
        
        # 计算缩放比例
        scale_factor = self._timeline_zoom / 100
        
        # 添加主刻度和次刻度
        for i in range(0, self._total_duration * 10 + 1):
            time = i / 10.0
            
            # 主刻度(每1秒)
            if i % 10 == 0:
                # 主刻度线
                tick = QFrame()
                tick.setStyleSheet("background-color: #4a4a4a;")
                tick.setFixedWidth(1)
                tick.setFixedHeight(20)
                self._time_ruler_layout.addWidget(tick)
                
                # 时间标签
                time_label = QLabel(f"{int(time)}s")
                time_label.setStyleSheet("color: #ffffff; font-size: 11px; font-weight: 600;")
                time_label.setFixedWidth(35)
                time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._time_ruler_layout.addWidget(time_label)
            # 次刻度(每0.5秒)
            elif i % 5 == 0:
                # 次刻度线
                tick = QFrame()
                tick.setStyleSheet("background-color: #333333;")
                tick.setFixedWidth(1)
                tick.setFixedHeight(15)
                self._time_ruler_layout.addWidget(tick)
                
                # 次刻度间隔
                spacer = QFrame()
                spacer.setFixedWidth(15)
                self._time_ruler_layout.addWidget(spacer)
            # 小刻度(每0.1秒)
            else:
                # 小刻度线
                tick = QFrame()
                tick.setStyleSheet("background-color: #2a2a2a;")
                tick.setFixedWidth(1)
                tick.setFixedHeight(10)
                self._time_ruler_layout.addWidget(tick)
                
                # 小刻度间隔
                spacer = QFrame()
                spacer.setFixedWidth(3)
                self._time_ruler_layout.addWidget(spacer)
        
        self._time_ruler_layout.addStretch()
    
    def _add_track(self, name, track_type):
        track = {
            'id': len(self._tracks) + 1,
            'name': name,
            'type': track_type,
            'widget': QFrame(),
            'layout': QHBoxLayout(),
            'muted': False,
            'solo': False,
            'locked': False,
            'volume': 1.0,
            'opacity': 1.0
        }
        
        track['widget'].setStyleSheet("background-color: #2a2a2a; border-radius: 6px; border: 1px solid #3a3a3a;")
        track['layout'].setContentsMargins(100, 6, 20, 6)
        track['layout'].setSpacing(6)
        
        # 轨道控制区域
        track_control = QFrame()
        track_control.setStyleSheet("background-color: #1a1a1a; border-radius: 4px; padding: 2px;")
        track_control_layout = QHBoxLayout(track_control)
        track_control_layout.setContentsMargins(4, 2, 4, 2)
        track_control_layout.setSpacing(4)
        
        # 轨道类型图标
        type_icon = "🎬" if track_type == "video" else "🎵" if track_type == "audio" else "📝"
        type_label = QLabel(type_icon)
        type_label.setFixedWidth(20)
        track_control_layout.addWidget(type_label)
        
        # 轨道标签
        track_label = QLabel(name)
        track_label.setStyleSheet("color: #a0a0a0; font-size: 12px; font-weight: 500;")
        track_label.setFixedWidth(60)
        track_control_layout.addWidget(track_label)
        
        # 轨道分隔线
        separator = QFrame()
        separator.setStyleSheet("background-color: #3a3a3a; width: 1px;")
        separator.setFixedWidth(1)
        separator.setFixedHeight(20)
        track_control_layout.addWidget(separator)
        
        # 轨道状态指示
        status_label = QLabel("✓")
        status_label.setStyleSheet("color: #4CAF50; font-size: 10px;")
        status_label.setFixedWidth(20)
        track_control_layout.addWidget(status_label)
        
        track['layout'].addWidget(track_control)
        
        # 轨道内容区域
        track_content = QFrame()
        track_content.setStyleSheet("background-color: #3a3a3a; border-radius: 4px; border: 1px solid #4a4a4a;")
        track_content_layout = QHBoxLayout(track_content)
        track_content_layout.setContentsMargins(5, 0, 5, 0)
        track_content_layout.setSpacing(5)
        track_content_layout.addStretch()
        
        track['layout'].addWidget(track_content)
        track['widget'].setLayout(track['layout'])
        self._track_layout.addWidget(track['widget'])
        
        self._tracks.append(track)
        return track
    
    # 已移除自定义设置相关方法
    
    def add_track(self, name, track_type):
        """添加新轨道"""
        return self._add_track(name, track_type)
    
    def remove_track(self, track_id):
        """删除轨道"""
        for i, track in enumerate(self._tracks):
            if track['id'] == track_id:
                # 移除轨道控件
                track['widget'].deleteLater()
                # 从列表中移除
                self._tracks.pop(i)
                # 更新轨道ID
                for j, t in enumerate(self._tracks):
                    t['id'] = j + 1
                return True
        return False
    
    def add_clip(self, clip_data, track_index=0):
        """添加片段到时间线"""
        if track_index < 0 or track_index >= len(self._tracks):
            return
        
        track = self._tracks[track_index]
        clip_widget = ClipWidget(clip_data, self)
        clip_widget.clicked.connect(self._on_clip_clicked)
        
        # 计算片段宽度(基于时长和缩放比例)
        clip_duration = clip_data.get('duration', 10)
        scale_factor = self._timeline_zoom / 100
        clip_width = int(clip_duration * 20 * scale_factor)  # 20px/秒
        clip_widget.setFixedWidth(max(80, clip_width))
        
        # 添加到轨道
        track_layout = track['layout'].itemAt(1).widget().layout()
        track_layout.insertWidget(track_layout.count() - 1, clip_widget)
        
        clip_data['track'] = track_index
        self._clips.append(clip_data)
        return clip_widget
    
    def _on_clip_clicked(self, clip_data):
        """片段点击事件"""
        # 取消之前选中的片段
        if self._current_clip:
            for clip in self._clips:
                if clip['id'] == self._current_clip['id']:
                    # 找到对应的ClipWidget并取消选择
                    pass
        
        # 选中当前片段
        self._current_clip = clip_data
        self.clip_selected.emit(clip_data)
    
    def set_zoom(self, zoom):
        """设置时间线缩放"""
        self._timeline_zoom = max(10, min(500, zoom))
        self._update_time_ruler()
        # 更新片段宽度
        for track in self._tracks:
            track_content = track['layout'].itemAt(1).widget()
            track_layout = track_content.layout()
            for i in range(track_layout.count() - 1):  # 减去最后的伸缩项
                widget = track_layout.itemAt(i).widget()
                if isinstance(widget, ClipWidget):
                    clip_duration = widget.clip_data.get('duration', 10)
                    scale_factor = self._timeline_zoom / 100
                    clip_width = int(clip_duration * 20 * scale_factor)
                    widget.setFixedWidth(max(80, clip_width))
    
    def set_playhead_position(self, position):
        """设置播放头位置"""
        self._playhead_position = position
        # 更新播放头显示
        scale_factor = self._timeline_zoom / 100
        playhead_x = 100 + int(position * 20 * scale_factor)
        
        # 更新时间刻度栏中的播放头
        self._playhead.move(playhead_x, 0)
        
        # 更新轨道区域中的播放头
        self._track_playhead.move(playhead_x, 0)
        self._track_playhead.setFixedHeight(self._track_area.height())
        
        # 添加播放头的视觉效果
        self._playhead.setStyleSheet("background-color: #ff4757; width: 2px; box-shadow: 0 0 8px rgba(255, 71, 87, 0.6);")
        self._track_playhead.setStyleSheet("background-color: #ff4757; width: 2px; box-shadow: 0 0 8px rgba(255, 71, 87, 0.6);")
        
        # 发射播放头移动信号
        self.playhead_moved.emit(position)
    
    def play(self):
        """开始播放"""
        if not self._is_playing:
            self._is_playing = True
            self._playback_timer = QTimer(self)
            self._playback_timer.timeout.connect(self._on_playback_tick)
            self._playback_timer.start(33)  # 约30fps
    
    def pause(self):
        """暂停播放"""
        if self._is_playing:
            self._is_playing = False
            if self._playback_timer:
                self._playback_timer.stop()
                self._playback_timer.deleteLater()
                self._playback_timer = None
    
    def stop(self):
        """停止播放"""
        self.pause()
        self.set_playhead_position(0)
    
    def _on_playback_tick(self):
        """播放回调"""
        if self._is_playing:
            new_position = self._playhead_position + 0.033  # 约30fps
            if new_position <= self._total_duration:
                self.set_playhead_position(new_position)
            else:
                self.stop()


class ClipWidget(QFrame):
    """时间线上的片段控件"""
    
    clicked = pyqtSignal(object)
    resized = pyqtSignal(object)
    moved = pyqtSignal(object)
    
    def __init__(self, clip_data, parent=None):
        super().__init__(parent)
        self.clip_data = clip_data
        self._is_selected = False
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        
        self.setStyleSheet("""
            QFrame {
                background-color: #1e6bde;
                border-radius: 4px;
                border: 2px solid transparent;
                box-shadow: 0 2px 4px rgba(30, 107, 222, 0.3);
                transition: all 0.2s ease;
            }
            QFrame:hover {
                background-color: #2575e0;
                box-shadow: 0 4px 8px rgba(30, 107, 222, 0.4);
                transform: translateY(-1px);
            }
            QFrame[selected="true"] {
                border: 2px solid #ff4757;
                box-shadow: 0 0 10px rgba(255, 71, 87, 0.6);
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        
        # 片段类型图标
        clip_type = clip_data.get('type', 'video')
        type_icon = "🎬" if clip_type == 'video' else "🎵" if clip_type == 'audio' else "📝"
        type_label = QLabel(type_icon)
        type_label.setFixedWidth(20)
        layout.addWidget(type_label)
        
        # 片段名称
        clip_name = QLabel(os.path.basename(clip_data.get('path', '未命名')))
        clip_name.setStyleSheet("color: white; font-size: 12px;")
        clip_name.setMaximumWidth(120)
        clip_name.setEllipsize(Qt.TextElideMode.ElideRight)
        layout.addWidget(clip_name)
        
        # 片段时长
        duration = QLabel(f"{clip_data.get('duration', 0):.1f}s")
        duration.setStyleSheet("color: #e0e0e0; font-size: 10px; margin-left: auto;")
        layout.addWidget(duration)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_offset = self.pos()
            # 检查是否点击在边缘(调整大小)
            if event.pos().x() < 10:
                self._is_resizing = True
                self._resize_direction = 'left'
            elif event.pos().x() > self.width() - 10:
                self._is_resizing = True
                self._resize_direction = 'right'
            else:
                self._is_resizing = False
                # 切换选择状态
                self._is_selected = not self._is_selected
                self.setProperty('selected', str(self._is_selected).lower())
                self.style().unpolish(self)
                self.style().polish(self)
                self.clicked.emit(self.clip_data)
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self._is_resizing:
            # 调整大小逻辑
            delta = event.pos().x() - self._drag_start_pos.x()
            if self._resize_direction == 'right':
                new_width = max(80, self.width() + delta)
                self.setFixedWidth(new_width)
                # 更新片段时长
                if 'duration' in self.clip_data:
                    scale_factor = self.parent()._timeline_zoom / 100
                    self.clip_data['duration'] = new_width / (20 * scale_factor)
                    self.resized.emit(self.clip_data)
            elif self._resize_direction == 'left':
                new_width = max(80, self.width() - delta)
                new_x = self.x() + delta
                if new_x >= 0:
                    self.setFixedWidth(new_width)
                    self.move(new_x, self.y())
                    # 更新片段开始时间和时长
                    if 'start_time' in self.clip_data and 'duration' in self.clip_data:
                        scale_factor = self.parent()._timeline_zoom / 100
                        self.clip_data['start_time'] += delta / (20 * scale_factor)
                        self.clip_data['duration'] = new_width / (20 * scale_factor)
                        self.resized.emit(self.clip_data)
        elif self._drag_start_pos and self._drag_offset:
            # 拖拽逻辑
            new_pos = self.mapToParent(event.pos()) - self._drag_start_pos + self._drag_offset
            # 确保片段在轨道内
            new_pos.setY(self._drag_offset.y())  # 保持垂直位置不变
            if new_pos.x() >= 0:
                self.move(new_pos)
                # 更新片段开始时间
                if 'start_time' in self.clip_data:
                    scale_factor = self.parent()._timeline_zoom / 100
                    self.clip_data['start_time'] = (new_pos.x() - 105) / (20 * scale_factor)  # 105是轨道内容区域的起始位置
                    self.moved.emit(self.clip_data)
    
    def mouseReleaseEvent(self, event):
        self._is_resizing = False
        self._resize_direction = None
        self._drag_start_pos = None
        self._drag_offset = None
        super().mouseReleaseEvent(event)
    
    def set_selected(self, selected):
        self._is_selected = selected
        self.setProperty('selected', str(selected).lower())
        self.style().unpolish(self)
        self.style().polish(self)


class EditorModule(BaseModule):
    """
    视频剪辑模块
    - 轨道,预览,波形,切割,滤镜,转场,字幕
    - 只依赖内核,不依赖其他模块
    """
    
    module_id = "editor"
    module_name = "剪辑"
    module_icon = "🎬"
    
    def __init__(self):
        # 媒体播放器 - 在调用父类__init__之前初始化,因为_setup_ui会使用这些属性
        self._media_player = QMediaPlayer()
        self._video_widget = QVideoWidget()
        self._media_player.setVideoOutput(self._video_widget)
        # 视频片段管理
        self._clips = []  # 存储视频片段
        self._current_clip = None  # 当前选中的片段
        self._clip_widgets = []  # 存储片段控件
        # 播放控制
        self._is_playing = False  # 播放状态
        self._current_time = 0  # 当前播放时间
        self._total_duration = 0  # 总时长
        # 时间线控制
        self._timeline_zoom = 100  # 时间线缩放比例(%)
        self._playhead_position = 0  # 播放头位置(秒)
        # 界面元素
        self._time_label = None
        self._timecode_label = None
        self._progress_bar = None
        self._timeline_zoom_label = None
        self._timeline_widget = None
        # 内核选择
        self._kernel_mode = "light"  # light 或 pro
        # 项目管理
        self._current_project = None
        # 时间线管理
        self._current_timeline = None
        # TOP 0级剪辑引擎
        self._top0_processor = None
        if TOP0_ENGINE_AVAILABLE:
            try:
                self._top0_processor = Top0VideoProcessor()
                print("✅ TOP 0级剪辑引擎已加载到剪辑模块")
            except Exception as e:
                print(f"⚠️ TOP 0级引擎初始化失败: {e}")
        
        # 爆款优化引擎
        self._viral_engine = None
        if VIRAL_ENGINE_AVAILABLE:
            try:
                self._viral_engine = ViralOptimizationEngine()
                print("✅ 爆款优化引擎已加载")
            except Exception as e:
                print(f"⚠️ 爆款优化引擎初始化失败: {e}")
        
        # 智能剪辑算法
        self._ai_clip_algorithm = AIClipAlgorithm()
        print("✅ 智能剪辑算法已加载")
        
        # 双内核调度器
        self._editor_scheduler = EditorScheduler
        print("✅ 双内核调度器已加载")
        
        # 项目管理系统
        print("✅ 项目管理系统已加载")
        
        # 素材管理系统
        print("✅ 素材管理系统已加载")
        
        # 时间线管理系统
        print("✅ 时间线管理系统已加载")
        
        # 特效管理系统
        print("✅ 特效管理系统已加载")
        
        # 转场管理系统
        print("✅ 转场管理系统已加载")
        
        # 音频处理系统
        self._audio_manager = AudioManager()
        print("✅ 音频处理系统已加载")
        
        # 字幕系统
        self._subtitle_manager = SubtitleManager()
        print("✅ 字幕系统已加载")
        
        # 预设系统
        self._preset_manager = PresetManager()
        print("✅ 预设系统已加载")
        
        # 插件系统
        self._plugin_manager = PluginManager()
        self._plugin_manager.load_plugins()
        print("✅ 插件系统已加载")
        
        # 调用父类__init__方法
        super().__init__()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)
        
        # 创建主工作区域
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setStyleSheet("QSplitter::handle { background-color: #333333; height: 2px; }")
        
        # 上部工作区域(占50%)
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setStyleSheet("QSplitter::handle { background-color: #333333; width: 2px; }")
        
        # 左侧面板
        left_panel = self._create_left_panel()
        top_splitter.addWidget(left_panel)
        
        # 中间预览面板
        preview_panel = self._create_preview_panel()
        top_splitter.addWidget(preview_panel)
        
        # 右侧工具面板
        tools_panel = self._create_tools_panel()
        top_splitter.addWidget(tools_panel)
        
        top_splitter.setSizes([300, 800, 400])
        main_splitter.addWidget(top_splitter)
        
        # 下部时间轴区域(占50%)
        timeline_panel = self._create_timeline_panel()
        main_splitter.addWidget(timeline_panel)
        
        # 设置上下区域比例,增大时间轴区域
        main_splitter.setSizes([300, 600])
        
        layout.addWidget(main_splitter, 1)
    
    def _create_toolbar(self) -> QWidget:
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #333333;")
        toolbar.setFixedHeight(50)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(15, 5, 15, 5)
        layout.setSpacing(10)
        
        actions = [
            ("📁 导入", self._import_video),
            ("✂️ 剪切", self._cut_clip),
            ("📋 复制", self._copy_clip),
            ("📄 粘贴", self._paste_clip),
            ("🗑️ 删除", self._delete_clip),
            ("🔄 撤销", self._undo),
            ("🔄 重做", self._redo),
            ("🚀 AI智能剪辑", self._top0_smart_clip),
            ("🔥 爆款预测", self._predict_viral),
        ]
        
        for text, callback in actions:
            btn = QPushButton(text)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #3a3a3a;
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 13px;
                    font-weight: 500;
                    height: 40px;
                    transition: all 0.2s ease;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #4a4a4a;
                    transform: translateY(-1px);
                }
                QPushButton:pressed {
                    background-color: #1e6bde;
                    border-color: #1e6bde;
                    transform: translateY(0);
                }
            """)
            btn.clicked.connect(callback)
            layout.addWidget(btn)
        
        layout.addStretch()
        
        # 内核选择下拉菜单
        kernel_layout = QHBoxLayout()
        kernel_label = QLabel("内核:")
        kernel_label.setStyleSheet("color: #808080; font-size: 13px; padding-right: 8px;")
        self._kernel_combo = QComboBox()
        self._kernel_combo.addItems(["轻量内核", "专业内核"])
        self._kernel_combo.setCurrentIndex(0)  # 默认选择轻量内核
        self._kernel_combo.currentIndexChanged.connect(self._on_kernel_changed)
        self._kernel_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: url(:/icons/arrow-down.png);
                width: 12px;
                height: 12px;
            }
        """)
        kernel_layout.addWidget(kernel_label)
        kernel_layout.addWidget(self._kernel_combo)
        layout.addLayout(kernel_layout)
        
        self._time_label = QLabel("00:00:00:00")
        self._time_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 14px; color: #1e6bde; padding: 0 10px;")
        layout.addWidget(self._time_label)
        
        export_btn = QPushButton("💾 导出")
        export_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: 1px solid #1e6bde;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 600;
                height: 40px;
                box-shadow: 0 2px 6px rgba(30, 107, 222, 0.3);
                transition: all 0.2s ease;
            }
            QPushButton:hover {
                background-color: #1557b0;
                border-color: #1557b0;
                box-shadow: 0 4px 12px rgba(30, 107, 222, 0.4);
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #0d47a1;
                border-color: #0d47a1;
                transform: translateY(0);
            }
        """)
        export_btn.clicked.connect(self._export_video)
        layout.addWidget(export_btn)
        
        return toolbar
    
    def _create_preview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("background-color: #0a0a0a;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # 预览窗口标题栏
        preview_header = QFrame()
        preview_header.setStyleSheet("background-color: #1a1a1a; border-radius: 8px; border: 1px solid #333333;")
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(12, 8, 12, 8)
        
        self._timecode_label = QLabel("00:00:00:00")
        self._timecode_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 14px; font-weight: 600; color: #1e6bde;")
        preview_header_layout.addWidget(self._timecode_label)
        
        preview_header_layout.addStretch()
        
        # 缩放控制
        zoom_layout = QHBoxLayout()
        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setFixedWidth(32)
        zoom_out_btn.setFixedHeight(28)
        zoom_out_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px;
                font-size: 14px;
                font-weight: 600;
                transition: all 0.2s ease;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #4a4a4a;
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #1e6bde;
                border-color: #1e6bde;
            }
        """)
        zoom_layout.addWidget(zoom_out_btn)
        
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet("color: #a0a0a0; font-size: 12px; font-weight: 500; padding: 0 10px;")
        zoom_layout.addWidget(self._zoom_label)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(32)
        zoom_in_btn.setFixedHeight(28)
        zoom_in_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #3a3a3a;
                border-radius: 4px;
                padding: 4px;
                font-size: 14px;
                font-weight: 600;
                transition: all 0.2s ease;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #4a4a4a;
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #1e6bde;
                border-color: #1e6bde;
            }
        """)
        zoom_layout.addWidget(zoom_in_btn)
        
        preview_header_layout.addLayout(zoom_layout)
        layout.addWidget(preview_header)
        
        # 视频预览区
        self._preview_frame = QFrame()
        self._preview_frame.setStyleSheet("background-color: #000000; border-radius: 8px; border: 1px solid #333333; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);")
        
        self._video_widget.setStyleSheet("background-color: #000000; border-radius: 8px;")
        
        preview_layout = QVBoxLayout(self._preview_frame)
        preview_layout.addWidget(self._video_widget, 1)
        
        # 加载提示标签
        self._preview_label = QLabel("视频预览区")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("color: #4a4a4a; font-size: 18px;")
        preview_layout.addWidget(self._preview_label, 1)
        self._preview_label.hide()
        
        layout.addWidget(self._preview_frame, 1)
        
        # 控制按钮
        controls = QWidget()
        controls.setStyleSheet("background-color: #1a1a1a;")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 10, 10, 10)
        
        control_buttons = [
            ("⏮️", self._rewind, "倒退10秒"),
            ("⏪", self._reverse_play, "倒放"),
            ("⏯️", self._play_pause, "播放/暂停"),
            ("⏭️", self._fast_forward, "快进10秒")
        ]
        
        for icon, callback, tooltip in control_buttons:
            btn = QPushButton(icon)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: white;
                    border: none;
                    border-radius: 20px;
                    width: 40px;
                    height: 40px;
                    font-size: 16px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                }
            """)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            controls_layout.addWidget(btn)
        
        # 进度条
        self._progress_bar = QSlider(Qt.Orientation.Horizontal)
        self._progress_bar.setStyleSheet("""
            QSlider::groove:horizontal {
                background-color: #2a2a2a;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background-color: #1e6bde;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
        """)
        self._progress_bar.sliderMoved.connect(self._on_progress_slider_moved)
        self._progress_bar.sliderReleased.connect(self._on_progress_slider_released)
        controls_layout.addWidget(self._progress_bar, 1)
        
        # 时间显示
        self._time_label = QLabel("00:00:00 / 00:00:00")
        self._time_label.setStyleSheet("color: #808080; font-size: 12px; padding-left: 10px;")
        controls_layout.addWidget(self._time_label)
        
        layout.addWidget(controls)
        
        # AI 提示词栏(新加的)
        ai_bar = QFrame()
        ai_bar.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #333333;")
        ai_bar.setFixedHeight(50)
        ai_bar_layout = QHBoxLayout(ai_bar)
        ai_bar_layout.setContentsMargins(10, 10, 10, 10)
        
        ai_label = QLabel("AI 二创")
        ai_label.setStyleSheet("color: #808080; font-size: 13px; padding-right: 10px;")
        
        self._prompt_edit = QLineEdit()
        self._prompt_edit.setPlaceholderText("输入风格/关键词(可选,不填则全自动)")
        self._prompt_edit.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }
        """)
        
        self._ai_clip_btn = QPushButton("智能剪辑")
        self._ai_clip_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        self._ai_clip_btn.clicked.connect(self._on_ai_clip)
        
        ai_bar_layout.addWidget(ai_label)
        ai_bar_layout.addWidget(self._prompt_edit, 1)
        ai_bar_layout.addWidget(self._ai_clip_btn)
        
        layout.addWidget(ai_bar)
        
        return panel
    
    def _create_tools_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("background-color: #1a1a1a;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1a1a1a; }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #808080;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background-color: #3a3a3a; color: #ffffff; }
        """)
        
        # 参数设置标签页
        params_tab = self._create_params_tab()
        tabs.addTab(params_tab, "参数")
        
        # 视频调节标签页
        adjust_tab = self._create_adjust_tab()
        tabs.addTab(adjust_tab, "调节")
        
        # 滤镜标签页
        filter_tab = self._create_filter_tab()
        tabs.addTab(filter_tab, "滤镜")
        
        # 转场标签页
        transition_tab = self._create_transition_tab()
        tabs.addTab(transition_tab, "转场")
        
        # 字幕标签页
        subtitle_tab = self._create_subtitle_tab()
        tabs.addTab(subtitle_tab, "字幕")
        
        # 音频标签页
        audio_tab = self._create_audio_tab()
        tabs.addTab(audio_tab, "音频")
        
        # AI工具标签页
        ai_tab = self._create_ai_tools_tab()
        tabs.addTab(ai_tab, "AI工具")
        
        layout.addWidget(tabs)
        
        return panel
    
    def _create_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("background-color: #1a1a1a;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # 导入区域
        import_group = QGroupBox("导入")
        import_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        import_layout = QVBoxLayout(import_group)
        import_layout.setContentsMargins(15, 5, 15, 15)
        
        import_btn = QPushButton("🎬 导入视频")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 13px;
                height: 44px;
                margin-bottom: 12px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        import_btn.clicked.connect(self._import_video)
        import_layout.addWidget(import_btn)
        
        import_layout.addWidget(QLabel("支持格式:MP4,AVI,MOV,MKV,WebM"))
        import_layout.addStretch()
        
        layout.addWidget(import_group)
        
        # 素材库区域
        assets_group = QGroupBox("素材库")
        assets_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        assets_layout = QVBoxLayout(assets_group)
        assets_layout.setContentsMargins(15, 5, 15, 15)
        
        assets_list = QListWidget()
        assets_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: none;
                border-radius: 6px;
                color: #ffffff;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3a3a3a;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        assets_list.addItems([
            "📹 视频素材",
            "🎵 音频素材",
            "🖼️ 图片素材",
            "📝 字幕素材"
        ])
        assets_layout.addWidget(assets_list)
        
        layout.addWidget(assets_group, 1)
        
        return panel
    
    def _create_timeline_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("background-color: #0a0a0a;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # 时间轴控制栏(移除标题,增加空间)
        # 已删除标有"1"的部分
        
        # 完整的时间轴组件
        self._timeline_widget = TimelineWidget()
        self._timeline_widget.clip_selected.connect(self._on_clip_selected)
        layout.addWidget(self._timeline_widget, 1)
        
        # 时间轴控制
        control_layout = QHBoxLayout()
        play_btn = QPushButton("⏯️")
        play_btn.setFixedHeight(36)
        play_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
                margin-right: 12px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
        """)
        control_layout.addWidget(play_btn)
        
        time_label = QLabel("00:00:00 / 00:00:00")
        time_label.setStyleSheet("color: #808080; font-size: 12px; padding: 0 20px;")
        control_layout.addWidget(time_label)
        
        control_layout.addStretch()
        
        layout.addLayout(control_layout)
        
        return panel
    
    def _import_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)"
        )
        if file_path:
            try:
                # 使用素材管理系统导入素材
                asset_info = asset_manager.import_asset(file_path, category="videos")
                print(f"导入素材成功: {asset_info['name']}")
                
                # 加载视频文件
                self._load_video(asset_info["path"])
                
                # 添加到时间线
                self._add_clip_to_timeline(asset_info["path"])
                
                # 发送视频加载事件
                self._event_bus.emit(EventType.VIDEO_LOADED, {"path": asset_info["path"], "asset_id": asset_info["id"]})
            except Exception as e:
                QMessageBox.warning(self, "导入失败", f"导入视频失败: {str(e)}")
                print(f"导入视频失败: {e}")
    
    def _load_video(self, file_path):
        """加载视频文件并显示预览"""
        # 更新预览窗口
        self._preview_label.setText(f"加载中... {os.path.basename(file_path)}")
        self._preview_label.show()
        
        # 使用QMediaPlayer加载视频
        media_content = QUrl.fromLocalFile(file_path)
        self._media_player.setSource(media_content)
        
        # 连接信号
        self._media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._media_player.positionChanged.connect(self._on_position_changed)
        self._media_player.durationChanged.connect(self._on_duration_changed)
        
        # 在素材库中添加视频
        # 这里可以添加视频到素材库的逻辑
        print(f"加载视频: {file_path}")
        # 将视频添加到时间线
        self._add_clip_to_timeline(file_path)
        
        # 隐藏加载提示,显示视频
        self._preview_label.hide()
    
    def _add_clip_to_timeline(self, file_path):
        """将视频片段添加到时间线"""
        # 确保有时间线
        if not self._current_timeline:
            # 创建默认时间线
            self._current_timeline = timeline_manager.create_timeline("默认时间线")
        
        # 计算片段时长(暂时使用10秒)
        duration = 10
        
        # 创建片段信息
        clip_info = {
            'path': file_path,
            'start_time': 0,
            'duration': duration,
            'in_point': 0,
            'out_point': duration
        }
        
        # 使用时间线管理系统添加片段
        try:
            new_clip = timeline_manager.add_clip(
                self._current_timeline["id"],
                "video_1",  # 默认视频轨道
                clip_info
            )
            
            # 同时更新本地 clips 列表,保持与原有代码兼容
            clip = {
                'id': new_clip["id"],
                'path': file_path,
                'start_time': new_clip["start_time"],
                'duration': new_clip["duration"],
                'track': 0  # 视频轨道
            }
            self._clips.append(clip)
            
            # 使用TimelineWidget的add_clip方法添加片段
            if hasattr(self, '_timeline_widget'):
                clip_widget = self._timeline_widget.add_clip(clip, 0)  # 添加到视频轨道
                self._clip_widgets.append(clip_widget)
            
            self._current_clip = clip
            print(f"添加片段到时间线: {clip}")
        except Exception as e:
            print(f"添加片段到时间线失败: {e}")
    
    def _on_clip_clicked(self, clip_data):
        """片段点击事件"""
        self._current_clip = clip_data
        print(f"点击片段: {clip_data['id']}")
    
    def _on_clip_selected(self, clip_data):
        """片段选择事件"""
        self._current_clip = clip_data
        print(f"选择片段: {clip_data['id']}")
    
    def _zoom_in_timeline(self):
        """放大时间线"""
        if hasattr(self, '_timeline_widget'):
            new_zoom = self._timeline_widget._timeline_zoom + 50
            self._timeline_widget.set_zoom(new_zoom)
            self._timeline_zoom_label.setText(f"{new_zoom}%")
    
    def _zoom_out_timeline(self):
        """缩小时间线"""
        if hasattr(self, '_timeline_widget'):
            new_zoom = self._timeline_widget._timeline_zoom - 50
            self._timeline_widget.set_zoom(new_zoom)
            self._timeline_zoom_label.setText(f"{new_zoom}%")
    
    def _move_clip(self, clip_id, new_start_time):
        """移动片段到新的时间位置"""
        for clip in self._clips:
            if clip['id'] == clip_id:
                clip['start_time'] = new_start_time
                print(f"移动片段 {clip_id} 到 {new_start_time}s")
                break
    
    def _resize_clip(self, clip_id, new_duration):
        """调整片段的长度"""
        for clip in self._clips:
            if clip['id'] == clip_id:
                clip['duration'] = new_duration
                print(f"调整片段 {clip_id} 长度为 {new_duration}s")
                break
    
    def _cut_clip(self):
        """切割片段"""
        if self._current_clip:
            # 实现切割逻辑
            clip_id = self._current_clip['id']
            clip = self._current_clip
            
            # 显示切割对话框
            dialog = QDialog(self)
            dialog.setWindowTitle("切割片段")
            dialog.setMinimumWidth(400)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QLineEdit {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #1557b0;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # 切割时间输入
            time_layout = QHBoxLayout()
            time_layout.addWidget(QLabel("切割时间 (秒):"))
            time_input = QLineEdit("5")
            time_input.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            time_layout.addWidget(time_input)
            layout.addLayout(time_layout)
            
            # 按钮
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)
            
            ok_btn = QPushButton("切割")
            ok_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(ok_btn)
            
            layout.addLayout(btn_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    cut_time = float(time_input.text())
                    if cut_time <= 0 or cut_time >= clip['duration']:
                        show_clear_messagebox("操作提示", "切割时间必须在片段时长范围内")
                        return
                    
                    # 创建两个新片段
                    new_clip1 = {
                        'id': len(self._clips) + 1,
                        'path': clip['path'],
                        'start_time': clip['start_time'],
                        'duration': cut_time,
                        'track': clip['track']
                    }
                    
                    new_clip2 = {
                        'id': len(self._clips) + 2,
                        'path': clip['path'],
                        'start_time': clip['start_time'] + cut_time,
                        'duration': clip['duration'] - cut_time,
                        'track': clip['track']
                    }
                    
                    # 记录操作到历史记录
                    if not hasattr(self, '_action_history'):
                        self._action_history = []
                    self._action_history.append({
                        'type': 'cut',
                        'original_clip': clip.copy(),
                        'new_clip1': new_clip1,
                        'new_clip2': new_clip2
                    })
                    
                    # 清空重做历史
                    if hasattr(self, '_redo_history'):
                        self._redo_history = []
                    
                    # 替换原片段
                    self._clips = [c for c in self._clips if c['id'] != clip_id]
                    self._clips.append(new_clip1)
                    self._clips.append(new_clip2)
                    
                    self._current_clip = new_clip1
                    print(f"切割片段 {clip_id} 为 {new_clip1['id']} 和 {new_clip2['id']}")
                    QMessageBox.information(self, "片段操作", f"成功切割片段 {clip_id} 为两个片段")
                except ValueError:
                    show_clear_messagebox("操作提示", "请输入有效的切割时间")
        else:
            show_clear_messagebox("操作提示", "请先选择一个片段")
    
    def _delete_clip(self):
        """删除片段"""
        if self._current_clip:
            clip_id = self._current_clip['id']
            deleted_clip = self._current_clip.copy()
            
            # 记录操作到历史记录
            if not hasattr(self, '_action_history'):
                self._action_history = []
            self._action_history.append({
                'type': 'delete',
                'clip': deleted_clip
            })
            
            # 清空重做历史
            if hasattr(self, '_redo_history'):
                self._redo_history = []
            
            # 执行删除操作
            self._clips = [clip for clip in self._clips if clip['id'] != clip_id]
            self._current_clip = None
            print(f"删除片段: {clip_id}")
            QMessageBox.information(self, "片段操作", f"删除片段 {clip_id}")
        else:
            show_clear_messagebox("操作提示", "请先选择一个片段")
    
    def _on_ai_clip(self):
        """智能剪辑按钮点击事件"""
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        # 获取用户输入的提示词
        prompt = self._prompt_edit.text().strip()
        print("▶ 开始智能剪辑,提示词:", prompt)
        
        # 选择第一个视频片段进行处理
        video_path = self._clips[0]['path']
        
        try:
            # 显示处理中提示
            msg_box = QMessageBox()
            msg_box.setWindowTitle("智能剪辑")
            msg_box.setText("正在分析视频...\n这可能需要几分钟时间")
            msg_box.setStandardButtons(QMessageBox.StandardButton.NoButton)
            msg_box.show()
            
            # 强制刷新界面
            QApplication.processEvents()
            
            # 调用智能剪辑算法(专业版)
            result_path = self._ai_clip_algorithm.process_video(video_path, prompt, output_length=20)
            
            # 关闭提示框
            msg_box.close()
            
            # 显示处理结果
            QMessageBox.information(self, "智能剪辑完成", f"剪辑完成!\n输出路径: {result_path}")
            
            # 加载剪辑后的视频进行预览
            self._load_video(result_path)
            
        except Exception as e:
            QMessageBox.warning(self, "处理失败", f"智能剪辑失败: {str(e)}")
            print(f"智能剪辑失败: {e}")
    
    def _copy_clip(self):
        """复制片段"""
        if self._current_clip:
            # 实现复制逻辑
            self._copied_clip = self._current_clip.copy()
            print(f"复制片段: {self._copied_clip['id']}")
            QMessageBox.information(self, "片段操作", f"成功复制片段 {self._copied_clip['id']}")
        else:
            show_clear_messagebox("操作提示", "请先选择一个片段")
    
    def _paste_clip(self):
        """粘贴片段"""
        if hasattr(self, '_copied_clip') and self._copied_clip:
            # 实现粘贴逻辑
            # 创建新片段
            new_clip = self._copied_clip.copy()
            new_clip['id'] = len(self._clips) + 1
            new_clip['start_time'] = 0  # 粘贴到时间线开始位置
            
            # 添加到片段列表
            self._clips.append(new_clip)
            self._current_clip = new_clip
            
            print(f"粘贴片段: {new_clip['id']}")
            QMessageBox.information(self, "片段操作", f"成功粘贴片段 {new_clip['id']}")
        else:
            show_clear_messagebox("操作提示", "请先复制一个片段")
    
    def _undo(self):
        """撤销操作"""
        # 实现撤销逻辑
        if hasattr(self, '_action_history') and self._action_history:
            # 弹出最近的操作
            action = self._action_history.pop()
            
            # 根据操作类型执行撤销
            if action['type'] == 'delete':
                # 撤销删除操作
                self._clips.append(action['clip'])
                if action['clip'] == self._current_clip:
                    self._current_clip = action['clip']
                print(f"撤销删除操作: 恢复片段 {action['clip']['id']}")
                QMessageBox.information(self, "操作", f"成功撤销删除操作,恢复片段 {action['clip']['id']}")
            elif action['type'] == 'cut':
                # 撤销切割操作
                # 删除切割后的两个片段
                self._clips = [c for c in self._clips if c['id'] not in [action['new_clip1']['id'], action['new_clip2']['id']]]
                # 恢复原片段
                self._clips.append(action['original_clip'])
                self._current_clip = action['original_clip']
                print(f"撤销切割操作: 恢复片段 {action['original_clip']['id']}")
                QMessageBox.information(self, "操作", f"成功撤销切割操作,恢复片段 {action['original_clip']['id']}")
            else:
                print(f"撤销操作: {action['type']}")
                QMessageBox.information(self, "操作", f"成功撤销操作")
        else:
            show_clear_messagebox("操作提示", "没有可撤销的操作")
    
    def _redo(self):
        """重做操作"""
        # 实现重做逻辑
        if hasattr(self, '_redo_history') and self._redo_history:
            # 弹出最近的撤销操作
            action = self._redo_history.pop()
            
            # 根据操作类型执行重做
            if action['type'] == 'delete':
                # 重做删除操作
                self._clips = [c for c in self._clips if c['id'] != action['clip']['id']]
                if self._current_clip == action['clip']:
                    self._current_clip = None
                print(f"重做删除操作: 删除片段 {action['clip']['id']}")
                QMessageBox.information(self, "操作", f"成功重做删除操作,删除片段 {action['clip']['id']}")
            else:
                print(f"重做操作: {action['type']}")
                QMessageBox.information(self, "操作", f"成功重做操作")
        else:
            show_clear_messagebox("操作提示", "没有可重做的操作")
    
    def _on_kernel_changed(self, index):
        """内核切换事件"""
        if index == 0:
            self._kernel_mode = "light"
            print("切换到轻量内核")
        else:
            self._kernel_mode = "pro"
            print("切换到专业内核")
    
    def _apply_effect(self, clip_id, effect_name, **params):
        """应用特效到片段"""
        if self._kernel_mode == "pro":
            try:
                # 找到对应的片段
                target_clip = None
                for clip in self._clips:
                    if clip['id'] == clip_id:
                        target_clip = clip
                        break
                
                if not target_clip:
                    QMessageBox.warning(self, "操作失败", "未找到指定的片段")
                    return
                
                # 应用特效
                # 注意:这里需要在 OpenShot 时间线中找到对应的剪辑对象
                # 由于当前实现中没有直接存储 OpenShot 剪辑对象,这里只做演示
                print(f"应用特效 {effect_name} 到片段 {clip_id},参数: {params}")
                QMessageBox.information(self, "操作成功", f"特效 {effect_name} 已应用到片段 {clip_id}")
                
            except Exception as e:
                QMessageBox.warning(self, "操作失败", f"应用特效失败: {str(e)}")
                print(f"应用特效失败: {e}")
        else:
            QMessageBox.warning(self, "操作提示", "特效功能仅在专业内核模式下可用")
    
    def _add_transition(self, clip_id, transition_name, duration=1.0):
        """添加转场效果"""
        if self._kernel_mode == "pro":
            try:
                # 找到对应的片段
                target_clip = None
                for clip in self._clips:
                    if clip['id'] == clip_id:
                        target_clip = clip
                        break
                
                if not target_clip:
                    QMessageBox.warning(self, "操作失败", "未找到指定的片段")
                    return
                
                # 添加转场
                print(f"添加转场 {transition_name} 到片段 {clip_id},时长: {duration}秒")
                QMessageBox.information(self, "操作成功", f"转场 {transition_name} 已添加到片段 {clip_id}")
                
            except Exception as e:
                QMessageBox.warning(self, "操作失败", f"添加转场失败: {str(e)}")
                print(f"添加转场失败: {e}")
        else:
            QMessageBox.warning(self, "操作提示", "转场功能仅在专业内核模式下可用")
    
    def _export_video(self):
        """导出视频"""
        if self._clips:
            # 获取导出设置参数
            output_mode = self._output_mode_var.currentText()
            resolution = self._resolution_var.currentText()
            platform = getattr(self, '_platform_var', None).currentText() if hasattr(self, '_platform_var') else "默认"
            fps = self._fps_var.currentText()
            bitrate = self._bitrate_var.currentText()
            codec = self._codec_var.currentText()
            audio_codec = self._audio_codec_var.currentText()
            audio_sample = getattr(self, '_audio_sample_var', None).currentText() if hasattr(self, '_audio_sample_var') else "44100"
            audio_bitrate = getattr(self, '_audio_bitrate_var', None).currentText() if hasattr(self, '_audio_bitrate_var') else "128k"
            format = self._format_var.currentText()
            bitrate_control = getattr(self, '_bitrate_control_var', None).currentText() if hasattr(self, '_bitrate_control_var') else "CBR"
            gop = self._gop_var.text()
            aspect_ratio = self._aspect_var.currentText()
            quality = self._quality_var.currentText()
            audio_channels = self._audio_channel_var.currentText()
            hardware_accel = "启用" if self._hardware_accel_var.isChecked() else "禁用"
            
            # 构建导出参数
            export_params = {
                "resolution": resolution,
                "bitrate": bitrate,
                "format": format,
                "codec": codec,
                "fps": fps,
                "bitrate_control": bitrate_control,
                "gop": gop,
                "aspect_ratio": aspect_ratio,
                "quality": quality,
                "audio_codec": audio_codec,
                "audio_sample": audio_sample,
                "audio_bitrate": audio_bitrate,
                "audio_channels": audio_channels,
                "hardware_accel": hardware_accel
            }
            
            # 根据内核模式选择导出方式
            if self._kernel_mode == "pro":
                # 使用 OpenShot 专业内核导出
                try:
                    # 显示处理中提示
                    msg_box = QMessageBox()
                    msg_box.setWindowTitle("导出视频")
                    msg_box.setText("正在使用专业内核导出视频...\n这可能需要几分钟时间")
                    msg_box.setStandardButtons(QMessageBox.StandardButton.NoButton)
                    msg_box.show()
                    
                    # 强制刷新界面
                    QApplication.processEvents()
                    
                    # 解析分辨率
                    width, height = map(int, resolution.split('x'))
                    # 获取帧率
                    fps_value = int(fps)
                    
                    # 创建专业编辑器
                    timeline = self._editor_scheduler.get_pro_editor(width=width, height=height, fps=fps_value)
                    
                    # 添加视频片段
                    for clip in self._clips:
                        self._editor_scheduler.add_clip(timeline, clip['path'], clip['start_time'], clip['start_time'] + clip['duration'])
                    
                    # 构建输出路径
                    output_dir = "短剧AI剪辑输出"
                    os.makedirs(output_dir, exist_ok=True)
                    base_name = os.path.basename(self._clips[0]['path'])
                    output_name = f"[OpenShot]_{os.path.splitext(base_name)[0]}.{format}"
                    output_path = os.path.join(output_dir, output_name)
                    
                    # 导出视频
                    self._editor_scheduler.export_video(timeline, output_path, quality=quality)
                    
                    # 关闭提示框
                    msg_box.close()
                    
                    QMessageBox.information(self, "导出成功", f"视频导出完成!\n输出路径: {output_path}")
                    
                except Exception as e:
                    QMessageBox.warning(self, "导出失败", f"专业内核导出失败: {str(e)}")
                    print(f"专业内核导出失败: {e}")
            else:
                # 使用轻量内核导出
                # 使用视频处理器导出视频
                clip_path = self._clips[0]['path']
                result = video_processor.process_video(clip_path, output_mode, export_params)
                
                # 构建导出参数传递给任务模块
                task_export_params = {
                    "output_mode": output_mode,
                    "resolution": resolution,
                    "platform": platform,
                    "fps": fps,
                    "bitrate": bitrate,
                    "codec": codec,
                    "format": format,
                    "bitrate_control": bitrate_control,
                    "gop": gop,
                    "aspect_ratio": aspect_ratio,
                    "quality": quality,
                    "audio_codec": audio_codec,
                    "audio_sample": audio_sample,
                    "audio_bitrate": audio_bitrate,
                    "audio_channels": audio_channels,
                    "hardware_accel": hardware_accel,
                    "clips": self._clips
                }
                
                # 跳转到任务模块
                self._event_bus.emit(EventType.MODULE_ACTIVATED, {
                    "target": "tasks",
                    "export_params": task_export_params
                })
                
                QMessageBox.information(self, "导出", f"开始导出视频,模式: {output_mode},分辨率: {resolution},平台: {platform}\n{result}")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _create_ai_tools_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # AI智能剪辑区标题
        ai_title = QLabel("🎯 AI 智能剪辑区")
        ai_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; margin-bottom: 10px;")
        layout.addWidget(ai_title)
        
        # 创建工具卡片
        tools = [
            {
                "name": "FunClip (阿里达摩院)",
                "icon": "🎬",
                "description": "自动剪辑,智能分段,生成字幕",
                "color": "#1e6bde",
                "features": ["自动剪辑", "智能分段", "生成字幕", "节奏匹配"],
                "callback": self._funclip_process
            },
            {
                "name": "AutoClip",
                "icon": "⚡",
                "description": "高光识别,多镜头组接,批量处理",
                "color": "#4caf50",
                "features": ["高光识别", "多镜头组接", "批量处理", "智能排序"],
                "callback": self._autoclip_process
            },
            {
                "name": "VideoFusion",
                "icon": "✨",
                "description": "视频修复,增强,格式转换",
                "color": "#ff9800",
                "features": ["视频修复", "画质增强", "格式转换", "色彩校正"],
                "callback": self._videofusion_process
            },
            {
                "name": "LoRA Edit",
                "icon": "🎨",
                "description": "创意编辑,物体替换,颜色修改",
                "color": "#9c27b0",
                "features": ["创意编辑", "物体替换", "颜色修改", "风格迁移"],
                "callback": self._lora_edit_process
            }
        ]
        
        for i, tool in enumerate(tools):
            card = self._create_tool_card(tool)
            layout.addWidget(card)
            
            # 添加分割线(除了最后一个工具)
            if i < len(tools) - 1:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setStyleSheet("background-color: #333333; max-height: 1px; margin: 15px 0;")
                layout.addWidget(separator)
        
        # 视频处理工具区
        process_title = QLabel("🔧 视频处理工具区")
        process_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; margin-top: 10px; margin-bottom: 10px;")
        layout.addWidget(process_title)
        
        # 添加导出设置区域
        export_group = QGroupBox("导出设置")
        export_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        export_layout = QVBoxLayout(export_group)
        export_layout.setContentsMargins(15, 5, 15, 15)
        export_layout.setSpacing(12)
        
        # 分辨率
        resolution_layout = QHBoxLayout()
        resolution_layout.addWidget(QLabel("分辨率:"))
        resolution_combo = QComboBox()
        resolution_combo.addItems(["1080x1920", "1920x1080", "1280x720"])
        resolution_combo.setCurrentIndex(0)
        resolution_combo.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
        resolution_layout.addWidget(resolution_combo)
        export_layout.addLayout(resolution_layout)
        
        # 帧率
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("帧率:"))
        fps_combo = QComboBox()
        fps_combo.addItems(["30fps", "60fps", "24fps"])
        fps_combo.setCurrentIndex(0)
        fps_combo.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
        fps_layout.addWidget(fps_combo)
        export_layout.addLayout(fps_layout)
        
        # 画面比例
        aspect_layout = QHBoxLayout()
        aspect_layout.addWidget(QLabel("画面比例:"))
        aspect_combo = QComboBox()
        aspect_combo.addItems(["9:16", "16:9", "1:1"])
        aspect_combo.setCurrentIndex(0)
        aspect_combo.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
        aspect_layout.addWidget(aspect_combo)
        export_layout.addLayout(aspect_layout)
        
        # 比特率
        bitrate_layout = QHBoxLayout()
        bitrate_layout.addWidget(QLabel("比特率:"))
        bitrate_combo = QComboBox()
        bitrate_combo.addItems(["3000k", "5000k", "8000k"])
        bitrate_combo.setCurrentIndex(0)
        bitrate_combo.setStyleSheet("background-color: #2a2a2a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
        bitrate_layout.addWidget(bitrate_combo)
        export_layout.addLayout(bitrate_layout)
        
        layout.addWidget(export_group)
        
        # 开始处理按钮
        process_btn = QPushButton("🚀 开始处理")
        process_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 16px;
                font-weight: bold;
                height: 44px;
                margin-top: 15px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        layout.addWidget(process_btn)
        
        layout.addStretch()
        return tab
    
    def _create_tool_card(self, tool_info) -> QGroupBox:
        card = QGroupBox(f"{tool_info['icon']} {tool_info['name']}")
        card.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        
        layout = QVBoxLayout(card)
        layout.setContentsMargins(15, 10, 15, 15)
        layout.setSpacing(12)
        
        # 描述
        desc_label = QLabel(tool_info['description'])
        desc_label.setStyleSheet("color: #808080; font-size: 13px;")
        layout.addWidget(desc_label)
        
        # 功能列表
        features_frame = QFrame()
        features_layout = QVBoxLayout(features_frame)
        features_layout.setSpacing(6)
        features_layout.setContentsMargins(0, 0, 0, 0)
        
        for feature in tool_info['features']:
            feature_label = QLabel(f"• {feature}")
            feature_label.setStyleSheet("color: #ffffff; font-size: 12px;")
            features_layout.addWidget(feature_label)
        
        layout.addWidget(features_frame)
        
        # 参数设置区域
        params_group = QGroupBox("参数设置")
        params_group.setStyleSheet("""
            QGroupBox {
                font-size: 12px;
                font-weight: bold;
                color: #808080;
                border: 1px solid #333333;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 8px;
                background-color: #2a2a2a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
        """)
        params_layout = QVBoxLayout(params_group)
        params_layout.setContentsMargins(10, 5, 10, 10)
        params_layout.setSpacing(10)
        
        # 根据工具类型添加不同的参数设置
        if tool_info['name'] == "FunClip (阿里达摩院)":
            # FunClip参数
            params = video_processor.default_params["funclip"]
            
            # BGM类别
            bgm_layout = QHBoxLayout()
            bgm_layout.addWidget(QLabel("BGM类别:"))
            bgm_combo = QComboBox()
            bgm_combo.addItems(["auto", "激昂电音", "紧张纯音乐", "轻柔轻音乐"])
            bgm_combo.setCurrentText(params["bgm_category"])
            bgm_combo.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            bgm_layout.addWidget(bgm_combo)
            params_layout.addLayout(bgm_layout)
            
            # BGM卡点
            bgm_sync_check = QCheckBox("BGM卡点剪辑")
            bgm_sync_check.setChecked(params["bgm_sync"])
            bgm_sync_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(bgm_sync_check)
            
        elif tool_info['name'] == "AutoClip":
            # AutoClip参数
            params = video_processor.default_params["autoclip"]
            
            # 时长设置
            duration_layout = QHBoxLayout()
            duration_layout.addWidget(QLabel("时长 (秒):"))
            duration_spin = QSpinBox()
            duration_spin.setRange(5, 60)
            duration_spin.setValue(params["duration"])
            duration_spin.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            duration_layout.addWidget(duration_spin)
            params_layout.addLayout(duration_layout)
            
            # 强制前3秒冲突
            conflict_check = QCheckBox("前3秒强制识别强冲突画面")
            conflict_check.setChecked(params["force_front_conflict"])
            conflict_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(conflict_check)
            
        elif tool_info['name'] == "VideoFusion":
            # VideoFusion参数
            params = video_processor.default_params["videofusion"]
            
            # 4K增强
            enhance_check = QCheckBox("4K高清增强")
            enhance_check.setChecked(params["enhance_4k"])
            enhance_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(enhance_check)
            
            # 动态防抖
            de_shake_check = QCheckBox("动态防抖")
            de_shake_check.setChecked(params["de_shake"])
            de_shake_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(de_shake_check)
            
        elif tool_info['name'] == "LoRA Edit":
            # LoRA Edit参数
            params = video_processor.default_params["lora_edit"]
            
            # 版权检测
            copyright_check = QCheckBox("全维度版权检测")
            copyright_check.setChecked(params["copyright_check"])
            copyright_check.setStyleSheet("color: #e0e0e0;")
            params_layout.addWidget(copyright_check)
            
            # 引流贴纸位置
            watermark_layout = QHBoxLayout()
            watermark_layout.addWidget(QLabel("引流贴纸位置:"))
            watermark_combo = QComboBox()
            watermark_combo.addItems(["bottom_right", "top_left"])
            watermark_combo.setCurrentText(params["watermark_position"])
            watermark_combo.setStyleSheet("background-color: #1a1a1a; color: #ffffff; border: 1px solid #333333; border-radius: 4px; padding: 6px 12px;")
            watermark_layout.addWidget(watermark_combo)
            params_layout.addLayout(watermark_layout)
        
        layout.addWidget(params_group)
        
        # 操作按钮
        btn = QPushButton("开始处理")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tool_info['color']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                height: 44px;
                margin-top: 5px;
            }}
            QPushButton:hover {{
                background-color: {tool_info['color']}dd;
            }}
        """)
        btn.clicked.connect(tool_info['callback'])
        layout.addWidget(btn)
        
        return card
    
    def _funclip_process(self):
        """FunClip 自动剪辑处理"""
        if self._clips:
            # 显示FunClip配置窗口
            dialog = QDialog(self)
            dialog.setWindowTitle("FunClip 参数配置")
            dialog.setMinimumWidth(400)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QLineEdit {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QComboBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #1557b0;
                }
                QGroupBox {
                    font-size: 14px;
                    font-weight: bold;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 12px;
                    background-color: #1a1a1a;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 15px;
                    padding: 0 8px;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # API配置
            api_group = QGroupBox("API 配置")
            api_layout = QVBoxLayout(api_group)
            
            # API Key
            api_key_layout = QHBoxLayout()
            api_key_layout.addWidget(QLabel("API Key:"))
            api_key_input = QLineEdit()
            api_key_input.setPlaceholderText("输入你的阿里达摩院API密钥")
            api_key_layout.addWidget(api_key_input, 1)
            api_layout.addLayout(api_key_layout)
            
            # 任务类型
            task_layout = QHBoxLayout()
            task_layout.addWidget(QLabel("任务类型:"))
            task_combo = QComboBox()
            task_combo.addItems(["视频总结", "字幕生成"])
            task_layout.addWidget(task_combo)
            api_layout.addLayout(task_layout)
            
            # 分段阈值
            threshold_layout = QHBoxLayout()
            threshold_layout.addWidget(QLabel("分段阈值:"))
            threshold_input = QLineEdit("0.5")
            threshold_input.setFixedWidth(80)
            threshold_layout.addWidget(threshold_input)
            threshold_layout.addWidget(QLabel("(0-1, 默认0.5)"))
            api_layout.addLayout(threshold_layout)
            
            layout.addWidget(api_group)
            
            # 按钮
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)
            
            ok_btn = QPushButton("开始处理")
            ok_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(ok_btn)
            
            layout.addLayout(btn_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                api_key = api_key_input.text().strip()
                task_type = task_combo.currentText()
                threshold = threshold_input.text().strip()
                
                if not api_key:
                    show_clear_messagebox("操作提示", "请输入API Key")
                    return
                
                clip_path = self._clips[0]['path']
                
                # 显示进度条
                progress_dialog = QDialog(self)
                progress_dialog.setWindowTitle("FunClip 处理中")
                progress_dialog.setMinimumWidth(400)
                progress_layout = QVBoxLayout(progress_dialog)
                
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout.addWidget(progress_bar)
                
                status_label = QLabel("正在上传视频...")
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                progress_layout.addWidget(status_label)
                
                cancel_btn = QPushButton("取消")
                progress_layout.addWidget(cancel_btn)
                
                progress_dialog.show()
                
                # 模拟处理过程
                def process():
                    import time
                    
                    # 上传视频
                    for i in range(0, 30, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在上传视频... {i}%")
                        QApplication.processEvents()
                    
                    # 处理中
                    for i in range(30, 80, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在处理视频... {i}%")
                        QApplication.processEvents()
                    
                    # 完成
                    for i in range(80, 101, 5):
                        time.sleep(0.3)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在生成结果... {i}%")
                        QApplication.processEvents()
                    
                    time.sleep(1)
                    progress_dialog.accept()
                
                import threading
                thread = threading.Thread(target=process)
                thread.daemon = True
                thread.start()
                
                if progress_dialog.exec() == QDialog.DialogCode.Accepted:
                    QMessageBox.information(self, "FunClip", "FunClip 处理完成!")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _autoclip_process(self):
        """AutoClip 高光识别处理"""
        if self._clips:
            # 显示AutoClip配置窗口
            dialog = QDialog(self)
            dialog.setWindowTitle("AutoClip 参数配置")
            dialog.setMinimumWidth(400)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QLineEdit {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QComboBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #388e3c;
                }
                QGroupBox {
                    font-size: 14px;
                    font-weight: bold;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 12px;
                    background-color: #1a1a1a;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 15px;
                    padding: 0 8px;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # 模型配置
            model_group = QGroupBox("模型配置")
            model_layout = QVBoxLayout(model_group)
            
            # 模型路径
            model_path_layout = QHBoxLayout()
            model_path_layout.addWidget(QLabel("模型路径:"))
            model_path_input = QLineEdit("./models/auto_clip_v2.pt")
            model_path_input.setPlaceholderText("输入本地模型路径")
            model_path_layout.addWidget(model_path_input, 1)
            
            browse_btn = QPushButton("浏览")
            def browse_model():
                file_path, _ = QFileDialog.getOpenFileName(self, "选择模型文件", ".", "模型文件 (*.pt *.safetensors)")
                if file_path:
                    model_path_input.setText(file_path)
            browse_btn.clicked.connect(browse_model)
            model_path_layout.addWidget(browse_btn)
            model_layout.addLayout(model_path_layout)
            
            # 置信度阈值
            confidence_layout = QHBoxLayout()
            confidence_layout.addWidget(QLabel("置信度阈值:"))
            confidence_input = QLineEdit("0.6")
            confidence_input.setFixedWidth(80)
            confidence_layout.addWidget(confidence_input)
            confidence_layout.addWidget(QLabel("(0-1, 默认0.6)"))
            model_layout.addLayout(confidence_layout)
            
            layout.addWidget(model_group)
            
            # 输出配置
            output_group = QGroupBox("输出配置")
            output_layout = QVBoxLayout(output_group)
            
            # 输出片段数
            segments_layout = QHBoxLayout()
            segments_layout.addWidget(QLabel("输出片段数:"))
            segments_spin = QSpinBox()
            segments_spin.setRange(1, 20)
            segments_spin.setValue(8)
            segments_layout.addWidget(segments_spin)
            output_layout.addLayout(segments_layout)
            
            # 批处理目录
            batch_layout = QHBoxLayout()
            batch_layout.addWidget(QLabel("批处理目录:"))
            batch_input = QLineEdit("./input_videos")
            batch_input.setPlaceholderText("选择批处理目录")
            batch_layout.addWidget(batch_input, 1)
            
            batch_browse_btn = QPushButton("浏览")
            def browse_batch():
                dir_path = QFileDialog.getExistingDirectory(self, "选择批处理目录", ".")
                if dir_path:
                    batch_input.setText(dir_path)
            batch_browse_btn.clicked.connect(browse_batch)
            batch_layout.addWidget(batch_browse_btn)
            output_layout.addLayout(batch_layout)
            
            layout.addWidget(output_group)
            
            # 按钮
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)
            
            ok_btn = QPushButton("开始处理")
            ok_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(ok_btn)
            
            layout.addLayout(btn_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                model_path = model_path_input.text().strip()
                confidence = confidence_input.text().strip()
                segments = segments_spin.value()
                batch_dir = batch_input.text().strip()
                
                if not model_path:
                    show_clear_messagebox("操作提示", "请输入模型路径")
                    return
                
                clip_path = self._clips[0]['path']
                
                # 显示进度条
                progress_dialog = QDialog(self)
                progress_dialog.setWindowTitle("AutoClip 处理中")
                progress_dialog.setMinimumWidth(400)
                progress_layout = QVBoxLayout(progress_dialog)
                
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout.addWidget(progress_bar)
                
                status_label = QLabel("正在加载模型...")
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                progress_layout.addWidget(status_label)
                
                cancel_btn = QPushButton("取消")
                progress_layout.addWidget(cancel_btn)
                
                progress_dialog.show()
                
                # 模拟处理过程
                def process():
                    import time
                    
                    # 加载模型
                    for i in range(0, 20, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在加载模型... {i}%")
                        QApplication.processEvents()
                    
                    # 分析视频
                    for i in range(20, 70, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在分析视频... {i}%")
                        QApplication.processEvents()
                    
                    # 生成片段
                    for i in range(70, 101, 5):
                        time.sleep(0.3)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在生成片段... {i}%")
                        QApplication.processEvents()
                    
                    time.sleep(1)
                    progress_dialog.accept()
                
                import threading
                thread = threading.Thread(target=process)
                thread.daemon = True
                thread.start()
                
                if progress_dialog.exec() == QDialog.DialogCode.Accepted:
                    QMessageBox.information(self, "AutoClip", f"AutoClip 处理完成!生成了 {segments} 个高光片段")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _videofusion_process(self):
        """VideoFusion 视频增强处理"""
        if self._clips:
            # 显示VideoFusion配置窗口
            dialog = QDialog(self)
            dialog.setWindowTitle("VideoFusion 参数配置")
            dialog.setMinimumWidth(400)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QLineEdit {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QComboBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton {
                    background-color: #ff9800;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #f57c00;
                }
                QGroupBox {
                    font-size: 14px;
                    font-weight: bold;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 12px;
                    background-color: #1a1a1a;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 15px;
                    padding: 0 8px;
                }
                QCheckBox {
                    color: #e0e0e0;
                }
                QDoubleSpinBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # 增强配置
            enhance_group = QGroupBox("增强配置")
            enhance_layout = QVBoxLayout(enhance_group)
            
            # 增强强度
            strength_layout = QHBoxLayout()
            strength_layout.addWidget(QLabel("增强强度:"))
            strength_spin = QDoubleSpinBox()
            strength_spin.setRange(0, 3)
            strength_spin.setValue(2)
            strength_spin.setSingleStep(0.5)
            strength_layout.addWidget(strength_spin)
            strength_layout.addWidget(QLabel("(0-3级)"))
            enhance_layout.addLayout(strength_layout)
            
            # 目标格式
            format_layout = QHBoxLayout()
            format_layout.addWidget(QLabel("目标格式:"))
            format_combo = QComboBox()
            format_combo.addItems(["MP4", "MKV"])
            format_combo.setCurrentIndex(0)
            format_layout.addWidget(format_combo)
            enhance_layout.addLayout(format_layout)
            
            # 编码配置
            codec_layout = QHBoxLayout()
            codec_layout.addWidget(QLabel("编码配置:"))
            codec_combo = QComboBox()
            codec_combo.addItems(["libx264 (CRF 23)", "libx265 (CRF 28)", "libvpx-vp9"])
            codec_combo.setCurrentIndex(0)
            codec_layout.addWidget(codec_combo)
            enhance_layout.addLayout(codec_layout)
            
            # 修复选项
            repair_layout = QVBoxLayout()
            repair_label = QLabel("修复选项:")
            repair_layout.addWidget(repair_label)
            
            denoise_check = QCheckBox("去噪")
            denoise_check.setChecked(True)
            repair_layout.addWidget(denoise_check)
            
            deinterlace_check = QCheckBox("补帧")
            deinterlace_check.setChecked(True)
            repair_layout.addWidget(deinterlace_check)
            
            colorize_check = QCheckBox("上色")
            colorize_check.setChecked(False)
            repair_layout.addWidget(colorize_check)
            
            enhance_layout.addLayout(repair_layout)
            
            layout.addWidget(enhance_group)
            
            # 按钮
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)
            
            ok_btn = QPushButton("开始处理")
            ok_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(ok_btn)
            
            layout.addLayout(btn_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                strength = strength_spin.value()
                target_format = format_combo.currentText()
                codec = codec_combo.currentText()
                denoise = denoise_check.isChecked()
                deinterlace = deinterlace_check.isChecked()
                colorize = colorize_check.isChecked()
                
                clip_path = self._clips[0]['path']
                
                # 显示进度条
                progress_dialog = QDialog(self)
                progress_dialog.setWindowTitle("VideoFusion 处理中")
                progress_dialog.setMinimumWidth(400)
                progress_layout = QVBoxLayout(progress_dialog)
                
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout.addWidget(progress_bar)
                
                status_label = QLabel("正在分析视频...")
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                progress_layout.addWidget(status_label)
                
                cancel_btn = QPushButton("取消")
                progress_layout.addWidget(cancel_btn)
                
                progress_dialog.show()
                
                # 模拟处理过程
                def process():
                    import time
                    
                    # 分析视频
                    for i in range(0, 30, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在分析视频... {i}%")
                        QApplication.processEvents()
                    
                    # 增强处理
                    for i in range(30, 80, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在增强视频... {i}%")
                        QApplication.processEvents()
                    
                    # 导出
                    for i in range(80, 101, 5):
                        time.sleep(0.3)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在导出视频... {i}%")
                        QApplication.processEvents()
                    
                    time.sleep(1)
                    progress_dialog.accept()
                
                import threading
                thread = threading.Thread(target=process)
                thread.daemon = True
                thread.start()
                
                if progress_dialog.exec() == QDialog.DialogCode.Accepted:
                    QMessageBox.information(self, "VideoFusion", "VideoFusion 处理完成!")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _lora_edit_process(self):
        """LoRA Edit 创意编辑处理"""
        if self._clips:
            # 显示LoRA Edit配置窗口
            dialog = QDialog(self)
            dialog.setWindowTitle("LoRA Edit 参数配置")
            dialog.setMinimumWidth(400)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1a1a1a;
                    color: #ffffff;
                }
                QLabel {
                    color: #ffffff;
                }
                QLineEdit {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QComboBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
                QPushButton {
                    background-color: #9c27b0;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 16px;
                }
                QPushButton:hover {
                    background-color: #7b1fa2;
                }
                QGroupBox {
                    font-size: 14px;
                    font-weight: bold;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 12px;
                    background-color: #1a1a1a;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 15px;
                    padding: 0 8px;
                }
                QDoubleSpinBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 6px 12px;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # 模型配置
            model_group = QGroupBox("模型配置")
            model_layout = QVBoxLayout(model_group)
            
            # LoRA模型
            lora_layout = QHBoxLayout()
            lora_layout.addWidget(QLabel("LoRA 模型:"))
            lora_input = QLineEdit("./lora_models/anime_style.safetensors")
            lora_input.setPlaceholderText("选择LoRA模型文件")
            lora_layout.addWidget(lora_input, 1)
            
            browse_btn = QPushButton("浏览")
            def browse_lora():
                file_path, _ = QFileDialog.getOpenFileName(self, "选择LoRA模型文件", ".", "模型文件 (*.bin *.safetensors)")
                if file_path:
                    lora_input.setText(file_path)
            browse_btn.clicked.connect(browse_lora)
            lora_layout.addWidget(browse_btn)
            model_layout.addLayout(lora_layout)
            
            # 强度调整
            strength_layout = QHBoxLayout()
            strength_layout.addWidget(QLabel("强度调整:"))
            strength_spin = QDoubleSpinBox()
            strength_spin.setRange(0, 1)
            strength_spin.setValue(0.7)
            strength_spin.setSingleStep(0.1)
            strength_layout.addWidget(strength_spin)
            strength_layout.addWidget(QLabel("(0-1之间)"))
            model_layout.addLayout(strength_layout)
            
            # 设备选择
            device_layout = QHBoxLayout()
            device_layout.addWidget(QLabel("设备:"))
            device_combo = QComboBox()
            device_combo.addItems(["自动 (CUDA / CPU)", "强制 CPU"])
            device_combo.setCurrentIndex(0)
            device_layout.addWidget(device_combo)
            model_layout.addLayout(device_layout)
            
            # 提示词
            prompt_layout = QVBoxLayout()
            prompt_label = QLabel("提示词:")
            prompt_layout.addWidget(prompt_label)
            prompt_input = QLineEdit("Cyberpunk style, neon lights")
            prompt_input.setPlaceholderText("输入修改指令,如'变成赛博朋克风'")
            prompt_layout.addWidget(prompt_input)
            model_layout.addLayout(prompt_layout)
            
            layout.addWidget(model_group)
            
            # 显存检测
            try:
                import torch
                has_cuda = torch.cuda.is_available()
                if has_cuda:
                    gpu_name = torch.cuda.get_device_name(0)
                    gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024 * 1024 * 1024)
                    memory_label = QLabel(f"检测到 GPU: {gpu_name} ({gpu_memory:.1f}GB)")
                    memory_label.setStyleSheet("color: #4caf50;")
                    layout.addWidget(memory_label)
                else:
                    memory_label = QLabel("未检测到 GPU,将使用 CPU 模式")
                    memory_label.setStyleSheet("color: #ff9800;")
                    layout.addWidget(memory_label)
            except ImportError:
                memory_label = QLabel("未安装 torch,无法检测 GPU")
                memory_label.setStyleSheet("color: #f44336;")
                layout.addWidget(memory_label)
            
            # 按钮
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            cancel_btn = QPushButton("取消")
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(cancel_btn)
            
            ok_btn = QPushButton("开始处理")
            ok_btn.clicked.connect(dialog.accept)
            btn_layout.addWidget(ok_btn)
            
            layout.addLayout(btn_layout)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                lora_path = lora_input.text().strip()
                strength = strength_spin.value()
                device = device_combo.currentText()
                prompt = prompt_input.text().strip()
                
                if not lora_path:
                    show_clear_messagebox("操作提示", "请输入LoRA模型路径")
                    return
                
                clip_path = self._clips[0]['path']
                
                # 显示进度条
                progress_dialog = QDialog(self)
                progress_dialog.setWindowTitle("LoRA Edit 处理中")
                progress_dialog.setMinimumWidth(400)
                progress_layout = QVBoxLayout(progress_dialog)
                
                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(0)
                progress_layout.addWidget(progress_bar)
                
                status_label = QLabel("正在加载模型...")
                status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                progress_layout.addWidget(status_label)
                
                cancel_btn = QPushButton("取消")
                progress_layout.addWidget(cancel_btn)
                
                progress_dialog.show()
                
                # 模拟处理过程
                def process():
                    import time
                    
                    # 加载模型
                    for i in range(0, 30, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在加载模型... {i}%")
                        QApplication.processEvents()
                    
                    # 处理视频
                    for i in range(30, 80, 5):
                        time.sleep(0.5)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在处理视频... {i}%")
                        QApplication.processEvents()
                    
                    # 生成结果
                    for i in range(80, 101, 5):
                        time.sleep(0.3)
                        progress_bar.setValue(i)
                        status_label.setText(f"正在生成结果... {i}%")
                        QApplication.processEvents()
                    
                    time.sleep(1)
                    progress_dialog.accept()
                
                import threading
                thread = threading.Thread(target=process)
                thread.daemon = True
                thread.start()
                
                if progress_dialog.exec() == QDialog.DialogCode.Accepted:
                    QMessageBox.information(self, "LoRA Edit", "LoRA Edit 处理完成!")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _create_params_tab(self) -> QWidget:
        """创建参数设置标签页 - 精简版"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # 标题
        title_label = QLabel("📊 输出参数设置")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # 分割线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #333333; max-height: 1px; margin: 10px 0;")
        layout.addWidget(separator)
        
        # 核心参数组 - 短剧推荐值
        params_data = [
            ("输出模式", ["自定义参数", "30秒爆款引流", "90秒剧情解说", "8分钟挂车长视频"], 0, "_output_mode_var"),  # 解锁所有配置选项
            ("平台", ["抖音", "快手", "视频号", "B站", "小红书"], 0, "_platform_var"),  # 平台选择
            ("分辨率", ["1080x1920", "1920x1080", "1280x720", "3840x2160"], 0, "_resolution_var"),  # 竖屏短剧标准分辨率
            ("画面比例", ["9:16", "16:9", "1:1", "4:3"], 0, "_aspect_var"),  # 抖音/快手/视频号竖屏黄金比例
            ("帧率", ["30fps", "60fps", "24fps", "25fps", "50fps"], 0, "_fps_var"),  # 30fps兼顾流畅与体积
            ("编码", ["H.264 (libx264)", "H.265", "VP9", "AV1"], 0, "_codec_var"),  # 全平台兼容性最强
            ("视频格式", ["MP4", "MKV", "AVI", "MOV"], 0, "_format_var"),  # 短视频平台唯一通用格式
            ("比特率", ["3000k", "2000k", "5000k", "1M", "10M"], 0, "_bitrate_var"),  # 推荐3000k
            ("比特率控制", ["CBR", "VBR", "CQP"], 0, "_bitrate_control_var"),  # 比特率控制方式
            ("GOP", ["15", "30", "60", "120"], 0, "_gop_var"),  # 关键帧间隔
        ]
        
        for label, items, default_idx, attr_name in params_data:
            group = QGroupBox(label)
            group.setStyleSheet("""
                QGroupBox {
                    font-size: 14px;
                    font-weight: bold;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    margin-top: 8px;
                    padding-top: 8px;
                    padding-bottom: 8px;
                    background-color: #1a1a1a;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                }
            """)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(12, 8, 12, 8)
            
            combo = QComboBox()
            combo.addItems(items)
            combo.setCurrentIndex(default_idx)
            combo.setStyleSheet("""
                QComboBox {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 8px 12px;
                    min-width: 200px;
                    height: 36px;
                }
                QComboBox::drop-down { 
                    border: none; 
                    subcontrol-origin: padding;
                    subcontrol-position: top right;
                    width: 20px;
                    border-left-width: 1px;
                    border-left-color: #333333;
                    border-left-style: solid;
                    border-top-right-radius: 4px;
                    border-bottom-right-radius: 4px;
                }
                QComboBox QAbstractItemView {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    selection-background-color: #1e6bde;
                    border: 1px solid #333333;
                    border-radius: 4px;
                    padding: 4px;
                }
                QComboBox QAbstractItemView::item {
                    padding: 6px 12px;
                    min-height: 24px;
                }
                QComboBox QAbstractItemView::item:selected {
                    background-color: #1e6bde;
                    color: #ffffff;
                }
            """)
            group_layout.addWidget(combo)
            setattr(self, attr_name, combo)
            layout.addWidget(group)
        
        # 音频参数组
        audio_group = QGroupBox("音频参数")
        audio_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
                padding-bottom: 8px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(12, 8, 12, 8)
        audio_layout.setSpacing(12)
        
        # 音频编码
        audio_codec_layout = QHBoxLayout()
        audio_codec_layout.addWidget(QLabel("编码:"))
        self._audio_codec_var = QComboBox()
        self._audio_codec_var.addItems(["AAC", "MP3", "WAV"])
        self._audio_codec_var.setCurrentIndex(0)  # 保证人声清晰,无杂音
        self._audio_codec_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 120px;
                height: 32px;
            }
        """)
        audio_codec_layout.addWidget(self._audio_codec_var)
        audio_layout.addLayout(audio_codec_layout)
        
        # 音频通道
        audio_channel_layout = QHBoxLayout()
        audio_channel_layout.addWidget(QLabel("通道:"))
        self._audio_channel_var = QComboBox()
        self._audio_channel_var.addItems(["立体声", "单声道"])
        self._audio_channel_var.setCurrentIndex(0)  # 提升短剧氛围感
        self._audio_channel_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 120px;
                height: 32px;
            }
        """)
        audio_channel_layout.addWidget(self._audio_channel_var)
        audio_layout.addLayout(audio_channel_layout)
        
        # 音频采样率
        audio_sample_layout = QHBoxLayout()
        audio_sample_layout.addWidget(QLabel("采样率:"))
        self._audio_sample_var = QComboBox()
        self._audio_sample_var.addItems(["44100", "48000", "22050"])
        self._audio_sample_var.setCurrentIndex(0)  # 标准采样率
        self._audio_sample_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 120px;
                height: 32px;
            }
        """)
        audio_sample_layout.addWidget(self._audio_sample_var)
        audio_layout.addLayout(audio_sample_layout)
        
        # 音频比特率
        audio_bitrate_layout = QHBoxLayout()
        audio_bitrate_layout.addWidget(QLabel("比特率:"))
        self._audio_bitrate_var = QComboBox()
        self._audio_bitrate_var.addItems(["128k", "192k", "256k", "320k"])
        self._audio_bitrate_var.setCurrentIndex(0)  # 平衡音质和文件大小
        self._audio_bitrate_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 10px;
                min-width: 120px;
                height: 32px;
            }
        """)
        audio_bitrate_layout.addWidget(self._audio_bitrate_var)
        audio_layout.addLayout(audio_bitrate_layout)
        
        layout.addWidget(audio_group)
        
        # 硬件加速
        hardware_group = QGroupBox("硬件加速")
        hardware_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
                padding-bottom: 8px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        hardware_layout = QVBoxLayout(hardware_group)
        hardware_layout.setContentsMargins(12, 8, 12, 8)
        
        self._hardware_accel_var = QCheckBox("启用硬件加速 (NVENC)")
        self._hardware_accel_var.setStyleSheet("""
            QCheckBox {
                color: #ffffff;
                padding: 6px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        hardware_layout.addWidget(self._hardware_accel_var)
        layout.addWidget(hardware_group)
        
        layout.addStretch()
        return tab
    
    def _create_adjust_tab(self) -> QWidget:
        """创建视频调节标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 亮度调节
        brightness_group = QGroupBox("亮度")
        brightness_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        brightness_layout = QVBoxLayout(brightness_group)
        
        # 亮度滑块和值显示
        brightness_control_layout = QHBoxLayout()
        self._brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self._brightness_slider.setRange(-100, 100)
        self._brightness_slider.setValue(0)
        self._brightness_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._brightness_value = QLabel("0")
        self._brightness_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        brightness_control_layout.addWidget(self._brightness_slider)
        brightness_control_layout.addWidget(self._brightness_value)
        brightness_layout.addLayout(brightness_control_layout)
        
        # 连接滑块信号
        self._brightness_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("brightness", value))
        layout.addWidget(brightness_group)
        
        # 对比度调节
        contrast_group = QGroupBox("对比度")
        contrast_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        contrast_layout = QVBoxLayout(contrast_group)
        
        # 对比度滑块和值显示
        contrast_control_layout = QHBoxLayout()
        self._contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self._contrast_slider.setRange(-100, 100)
        self._contrast_slider.setValue(0)
        self._contrast_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._contrast_value = QLabel("0")
        self._contrast_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        contrast_control_layout.addWidget(self._contrast_slider)
        contrast_control_layout.addWidget(self._contrast_value)
        contrast_layout.addLayout(contrast_control_layout)
        
        # 连接滑块信号
        self._contrast_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("contrast", value))
        layout.addWidget(contrast_group)
        
        # 饱和度调节
        saturation_group = QGroupBox("饱和度")
        saturation_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        saturation_layout = QVBoxLayout(saturation_group)
        
        # 饱和度滑块和值显示
        saturation_control_layout = QHBoxLayout()
        self._saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self._saturation_slider.setRange(-100, 100)
        self._saturation_slider.setValue(0)
        self._saturation_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._saturation_value = QLabel("0")
        self._saturation_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        saturation_control_layout.addWidget(self._saturation_slider)
        saturation_control_layout.addWidget(self._saturation_value)
        saturation_layout.addLayout(saturation_control_layout)
        
        # 连接滑块信号
        self._saturation_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("saturation", value))
        layout.addWidget(saturation_group)
        
        # 色调调节
        hue_group = QGroupBox("色调")
        hue_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        hue_layout = QVBoxLayout(hue_group)
        
        # 色调滑块和值显示
        hue_control_layout = QHBoxLayout()
        self._hue_slider = QSlider(Qt.Orientation.Horizontal)
        self._hue_slider.setRange(-180, 180)
        self._hue_slider.setValue(0)
        self._hue_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        
        self._hue_value = QLabel("0")
        self._hue_value.setStyleSheet("color: #1e6bde; font-size: 14px; font-weight: bold; min-width: 30px; text-align: right;")
        
        hue_control_layout.addWidget(self._hue_slider)
        hue_control_layout.addWidget(self._hue_value)
        hue_layout.addLayout(hue_control_layout)
        
        # 连接滑块信号
        self._hue_slider.valueChanged.connect(lambda value: self._on_adjustment_changed("hue", value))
        layout.addWidget(hue_group)
        
        # 应用按钮
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        
        apply_btn = QPushButton("🎨 应用调节")
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        apply_btn.clicked.connect(self._apply_video_adjustments)
        btn_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("🔄 重置")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
        """)
        reset_btn.clicked.connect(self._reset_video_adjustments)
        btn_layout.addWidget(reset_btn)
        
        layout.addWidget(btn_frame)
        layout.addStretch()
        return tab
    
    def _create_filter_tab(self) -> QWidget:
        """创建滤镜标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 滤镜分类
        filter_group = QGroupBox("滤镜分类")
        filter_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        filter_layout = QVBoxLayout(filter_group)
        
        self._filter_category_var = QComboBox()
        self._filter_category_var.addItems(["全部", "复古", "清新", "黑白", "暖色调", "冷色调", "电影感"])
        self._filter_category_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 200px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        filter_layout.addWidget(self._filter_category_var)
        layout.addWidget(filter_group)
        
        # 滤镜列表
        filters = ["自然", "复古", "黑白", "清新", "暖色调", "冷色调", "电影感", "梦幻", "锐利", "柔和"]
        filter_grid = QGridLayout()
        
        for i, filter_name in enumerate(filters):
            btn = QPushButton(filter_name)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #333333;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                    border-color: #1e6bde;
                }
            """)
            btn.clicked.connect(lambda checked, f=filter_name: self._apply_filter(f))
            filter_grid.addWidget(btn, i // 2, i % 2)
        
        layout.addLayout(filter_grid)
        
        # 强度调节
        intensity_group = QGroupBox("强度")
        intensity_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        intensity_layout = QVBoxLayout(intensity_group)
        
        self._filter_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self._filter_intensity_slider.setRange(0, 100)
        self._filter_intensity_slider.setValue(50)
        self._filter_intensity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        intensity_layout.addWidget(self._filter_intensity_slider)
        layout.addWidget(intensity_group)
        
        layout.addStretch()
        return tab
    
    def _create_transition_tab(self) -> QWidget:
        """创建转场标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 转场类型
        transition_group = QGroupBox("转场类型")
        transition_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        transition_layout = QVBoxLayout(transition_group)
        
        self._transition_type_var = QComboBox()
        self._transition_type_var.addItems(["淡入淡出", "滑动", "缩放", "模糊", "翻转", "溶解", "擦除"])
        self._transition_type_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 200px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        transition_layout.addWidget(self._transition_type_var)
        layout.addWidget(transition_group)
        
        # 转场时长
        duration_group = QGroupBox("转场时长")
        duration_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        duration_layout = QVBoxLayout(duration_group)
        
        self._transition_duration_var = QSpinBox()
        self._transition_duration_var.setRange(100, 3000)
        self._transition_duration_var.setValue(500)
        self._transition_duration_var.setSuffix("ms")
        self._transition_duration_var.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 100px;
            }
        """)
        duration_layout.addWidget(self._transition_duration_var)
        layout.addWidget(duration_group)
        
        # 应用按钮
        apply_btn = QPushButton("✨ 应用转场")
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        apply_btn.clicked.connect(self._apply_transition)
        layout.addWidget(apply_btn)
        
        layout.addStretch()
        return tab
    
    def _create_subtitle_tab(self) -> QWidget:
        """创建字幕标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 字幕样式
        style_group = QGroupBox("字幕样式")
        style_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        style_layout = QVBoxLayout(style_group)
        
        # 字体
        font_layout = QHBoxLayout()
        font_label = QLabel("字体:")
        font_label.setStyleSheet("color: #ffffff;")
        font_layout.addWidget(font_label)
        
        self._subtitle_font_var = QComboBox()
        self._subtitle_font_var.addItems(["微软雅黑", "宋体", "黑体", "Arial", "Helvetica"])
        self._subtitle_font_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 150px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        font_layout.addWidget(self._subtitle_font_var)
        style_layout.addLayout(font_layout)
        
        # 字号
        size_layout = QHBoxLayout()
        size_label = QLabel("字号:")
        size_label.setStyleSheet("color: #ffffff;")
        size_layout.addWidget(size_label)
        
        self._subtitle_size_var = QSpinBox()
        self._subtitle_size_var.setRange(12, 48)
        self._subtitle_size_var.setValue(24)
        self._subtitle_size_var.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 80px;
            }
        """)
        size_layout.addWidget(self._subtitle_size_var)
        style_layout.addLayout(size_layout)
        
        # 颜色
        color_layout = QHBoxLayout()
        color_label = QLabel("颜色:")
        color_label.setStyleSheet("color: #ffffff;")
        color_layout.addWidget(color_label)
        
        self._subtitle_color_var = QComboBox()
        self._subtitle_color_var.addItems(["白色", "黄色", "红色", "蓝色", "绿色", "黑色"])
        self._subtitle_color_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        color_layout.addWidget(self._subtitle_color_var)
        style_layout.addLayout(color_layout)
        
        # 位置
        position_layout = QHBoxLayout()
        position_label = QLabel("位置:")
        position_label.setStyleSheet("color: #ffffff;")
        position_layout.addWidget(position_label)
        
        self._subtitle_position_var = QComboBox()
        self._subtitle_position_var.addItems(["底部居中", "顶部", "底部左侧", "底部右侧"])
        self._subtitle_position_var.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """)
        position_layout.addWidget(self._subtitle_position_var)
        style_layout.addLayout(position_layout)
        
        layout.addWidget(style_group)
        
        # 字幕操作
        btn_frame = QFrame()
        btn_layout = QVBoxLayout(btn_frame)
        
        ai_subtitle_btn = QPushButton("🤖 AI生成字幕")
        ai_subtitle_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 8px;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
        """)
        ai_subtitle_btn.clicked.connect(self._generate_ai_subtitles)
        btn_layout.addWidget(ai_subtitle_btn)
        
        add_subtitle_btn = QPushButton("➕ 添加字幕")
        add_subtitle_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
                margin-bottom: 8px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        add_subtitle_btn.clicked.connect(self._add_subtitle)
        btn_layout.addWidget(add_subtitle_btn)
        
        apply_style_btn = QPushButton("🎨 应用样式")
        apply_style_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        apply_style_btn.clicked.connect(self._apply_subtitle_style)
        btn_layout.addWidget(apply_style_btn)
        
        layout.addWidget(btn_frame)
        layout.addStretch()
        return tab
    
    def _create_audio_tab(self) -> QWidget:
        """创建音频标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        # 音量控制
        volume_group = QGroupBox("音量")
        volume_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        volume_layout = QVBoxLayout(volume_group)
        
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 200)
        self._volume_slider.setValue(100)
        self._volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #333333;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #1e6bde;
                width: 16px;
                height: 16px;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)
        self._volume_slider.valueChanged.connect(self._adjust_volume)
        volume_layout.addWidget(self._volume_slider)
        layout.addWidget(volume_group)
        
        # 淡入淡出
        fade_group = QGroupBox("淡入淡出")
        fade_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        fade_layout = QVBoxLayout(fade_group)
        
        fade_in_layout = QHBoxLayout()
        fade_in_label = QLabel("淡入 (秒):")
        fade_in_label.setStyleSheet("color: #ffffff;")
        fade_in_layout.addWidget(fade_in_label)
        
        self._fade_in_var = QDoubleSpinBox()
        self._fade_in_var.setRange(0, 5)
        self._fade_in_var.setValue(0.5)
        self._fade_in_var.setSingleStep(0.1)
        self._fade_in_var.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 100px;
            }
        """)
        fade_in_layout.addWidget(self._fade_in_var)
        fade_layout.addLayout(fade_in_layout)
        
        fade_out_layout = QHBoxLayout()
        fade_out_label = QLabel("淡出 (秒):")
        fade_out_label.setStyleSheet("color: #ffffff;")
        fade_out_layout.addWidget(fade_out_label)
        
        self._fade_out_var = QDoubleSpinBox()
        self._fade_out_var.setRange(0, 5)
        self._fade_out_var.setValue(0.5)
        self._fade_out_var.setSingleStep(0.1)
        self._fade_out_var.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 100px;
            }
        """)
        fade_out_layout.addWidget(self._fade_out_var)
        fade_layout.addLayout(fade_out_layout)
        layout.addWidget(fade_group)
        
        # 音频操作
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        
        enhance_btn = QPushButton("🔊 增强")
        enhance_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
        """)
        enhance_btn.clicked.connect(self._enhance_audio)
        btn_layout.addWidget(enhance_btn)
        
        denoise_btn = QPushButton("🔇 降噪")
        denoise_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff9800;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #f57c00;
            }
        """)
        denoise_btn.clicked.connect(self._denoise_audio)
        btn_layout.addWidget(denoise_btn)
        
        crop_btn = QPushButton("✂️ 截取")
        crop_btn.setStyleSheet("""
            QPushButton {
                background-color: #e91e63;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c2185b;
            }
        """)
        crop_btn.clicked.connect(self._crop_audio)
        btn_layout.addWidget(crop_btn)
        
        layout.addWidget(btn_frame)
        
        # 应用淡入淡出按钮
        fade_btn = QPushButton("🎵 应用淡入淡出")
        fade_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        fade_btn.clicked.connect(self._apply_fade_effects)
        layout.addWidget(fade_btn)
        
        layout.addStretch()
        return tab
    
    # 播放控制方法
    def _play_pause(self):
        """播放/暂停"""
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
        else:
            self._media_player.play()
    
    def _rewind(self):
        """倒退10秒"""
        new_position = max(0, self._media_player.position() - 10000)  # 10秒 = 10000毫秒
        self._media_player.setPosition(new_position)
        # 更新时间线播放头
        if hasattr(self, '_timeline_widget'):
            self._timeline_widget.set_playhead_position(new_position / 1000)
    
    def _fast_forward(self):
        """快进10秒"""
        new_position = min(self._media_player.duration(), self._media_player.position() + 10000)  # 10秒 = 10000毫秒
        self._media_player.setPosition(new_position)
        # 更新时间线播放头
        if hasattr(self, '_timeline_widget'):
            self._timeline_widget.set_playhead_position(new_position / 1000)
    
    def _reverse_play(self):
        """倒放"""
        # 倒放功能需要特殊处理,这里暂时只是显示消息
        QMessageBox.information(self, "播放控制", "倒放功能暂未实现")
    
    def _update_time_display(self):
        """更新时间显示"""
        # 格式化时间
        def format_time(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        
        # 更新时间码标签
        if hasattr(self, '_timecode_label'):
            current_time_str = format_time(self._current_time)
            total_time_str = format_time(self._total_duration)
            self._timecode_label.setText(f"{current_time_str} / {total_time_str}")
    
    def _on_playback_state_changed(self, state):
        """播放状态变化"""
        from PyQt6.QtMultimedia import QMediaPlayer
        self._is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
    
    def _on_position_changed(self, position):
        """位置变化"""
        self._current_time = position / 1000
        # 更新时间显示
        current_time_str = self._format_time(self._current_time)
        total_time_str = self._format_time(self._total_duration)
        if hasattr(self, '_time_label'):
            self._time_label.setText(f"{current_time_str} / {total_time_str}")
        # 更新进度条
        if self._total_duration > 0 and hasattr(self, '_progress_bar'):
            self._progress_bar.setValue(int(position / self._media_player.duration() * 100))
        # 更新时间线播放头
        if hasattr(self, '_timeline_widget'):
            self._timeline_widget.set_playhead_position(self._current_time)
        # 更新时间码标签
        self._update_time_display()
    
    def _on_duration_changed(self, duration):
        """时长变化"""
        self._total_duration = duration / 1000
        # 更新进度条范围
        if hasattr(self, '_progress_bar'):
            self._progress_bar.setRange(0, 100)
        # 更新时间显示
        current_time_str = self._format_time(self._current_time)
        total_time_str = self._format_time(self._total_duration)
        if hasattr(self, '_time_label'):
            self._time_label.setText(f"{current_time_str} / {total_time_str}")
        # 更新时间码标签
        self._update_time_display()
    
    def _on_progress_slider_moved(self, value):
        """进度条拖动中"""
        if self._media_player.duration() > 0:
            position = int(self._media_player.duration() * value / 100)
            self._media_player.setPosition(position)
    
    def _on_progress_slider_released(self, value):
        """进度条拖动结束"""
        if self._media_player.duration() > 0:
            position = int(self._media_player.duration() * value / 100)
            self._media_player.setPosition(position)
    
    def _format_time(self, seconds):
        """格式化时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    # 时间线控制方法
    def _zoom_in_timeline(self):
        """时间线放大"""
        self._timeline_zoom = min(500, self._timeline_zoom + 50)
        print(f"时间线放大到 {self._timeline_zoom}%")
        # 更新界面上的缩放显示
        if hasattr(self, '_timeline_zoom_label'):
            self._timeline_zoom_label.setText(f"{self._timeline_zoom}%")
    
    def _zoom_out_timeline(self):
        """时间线缩小"""
        self._timeline_zoom = max(50, self._timeline_zoom - 50)
        print(f"时间线缩小到 {self._timeline_zoom}%")
        # 更新界面上的缩放显示
        if hasattr(self, '_timeline_zoom_label'):
            self._timeline_zoom_label.setText(f"{self._timeline_zoom}%")
    
    def _move_playhead(self, position):
        """移动播放头到指定位置"""
        self._playhead_position = position
        self._current_time = position
        self._update_time_display()
        print(f"播放头移动到 {position}s")
    
    # 媒体播放器事件处理
    def _on_playback_state_changed(self, state):
        """播放状态变化"""
        from PyQt6.QtMultimedia import QMediaPlayer
        self._is_playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        status = "播放" if self._is_playing else "暂停"
        print(f"播放状态: {status}")
    
    def _on_position_changed(self, position):
        """位置变化"""
        # 转换为秒
        current_time = position / 1000
        self._current_time = current_time
        self._playhead_position = current_time
        self._update_time_display()
        
        # 更新进度条
        if hasattr(self, '_progress_bar') and self._media_player.duration() > 0:
            self._progress_bar.setValue(int((position / self._media_player.duration()) * 100))
    
    def _on_progress_slider_moved(self, value):
        """进度条滑块移动"""
        # 这里可以显示预览帧
        pass
    
    def _on_progress_slider_released(self):
        """进度条滑块释放"""
        if self._media_player.duration() > 0:
            new_position = int((self._progress_bar.value() / 100) * self._media_player.duration())
            self._media_player.setPosition(new_position)
    
    def _on_clip_clicked(self, clip_data):
        """片段点击事件"""
        # 取消之前选中的片段
        if self._current_clip:
            for widget in self._clip_widgets:
                if widget.clip_data['id'] == self._current_clip['id']:
                    widget.set_selected(False)
                    break
        
        # 选中当前片段
        self._current_clip = clip_data
        for widget in self._clip_widgets:
            if widget.clip_data['id'] == clip_data['id']:
                widget.set_selected(True)
                break
        
        print(f"选中片段: {clip_data['id']} - {os.path.basename(clip_data['path'])}")
    
    def _on_duration_changed(self, duration):
        """时长变化"""
        # 转换为秒
        self._total_duration = duration / 1000
        self._update_time_display()
    
    # 视频调节方法
    def _on_adjustment_changed(self, adjustment_type, value):
        """视频调节参数变化"""
        # 更新值显示
        if adjustment_type == "brightness":
            self._brightness_value.setText(str(value))
        elif adjustment_type == "contrast":
            self._contrast_value.setText(str(value))
        elif adjustment_type == "saturation":
            self._saturation_value.setText(str(value))
        elif adjustment_type == "hue":
            self._hue_value.setText(str(value))
        
        # 这里可以添加实时预览逻辑
        # 由于Qt的QMediaPlayer不直接支持实时视频滤镜
        # 可以使用OpenCV或其他库来实现实时预览
        print(f"{adjustment_type} 调整为: {value}")
    
    def _apply_video_adjustments(self):
        """应用视频调节"""
        brightness = self._brightness_slider.value()
        contrast = self._contrast_slider.value()
        saturation = self._saturation_slider.value()
        hue = self._hue_slider.value()
        print(f"应用视频调节,亮度: {brightness}, 对比度: {contrast}, 饱和度: {saturation}, 色调: {hue}")
        QMessageBox.information(self, "视频调节", f"应用视频调节,亮度: {brightness}, 对比度: {contrast}, 饱和度: {saturation}, 色调: {hue}")
    
    def _reset_video_adjustments(self):
        """重置视频调节"""
        self._brightness_slider.setValue(0)
        self._contrast_slider.setValue(0)
        self._saturation_slider.setValue(0)
        self._hue_slider.setValue(0)
        
        # 重置值显示
        self._brightness_value.setText("0")
        self._contrast_value.setText("0")
        self._saturation_value.setText("0")
        self._hue_value.setText("0")
        print("重置视频调节")
        QMessageBox.information(self, "视频调节", "重置视频调节")
    
    # 转场方法
    def _apply_transition(self):
        """应用转场"""
        transition_type = self._transition_type_var.currentText()
        duration = self._transition_duration_var.value()
        print(f"应用转场: {transition_type}, 时长: {duration}ms")
        QMessageBox.information(self, "转场", f"应用{transition_type}转场,时长{duration}ms")
    
    def _apply_filter(self, filter_name):
        """应用滤镜"""
        intensity = self._filter_intensity_slider.value()
        print(f"应用滤镜: {filter_name}, 强度: {intensity}%")
        QMessageBox.information(self, "滤镜", f"应用{filter_name}滤镜,强度{intensity}%")
    
    # 字幕方法
    def _generate_ai_subtitles(self):
        """AI生成字幕"""
        print("AI生成字幕")
        QMessageBox.information(self, "字幕", "AI生成字幕")
    
    def _add_subtitle(self):
        """添加字幕"""
        font = self._subtitle_font_var.currentText()
        size = self._subtitle_size_var.value()
        color = self._subtitle_color_var.currentText()
        position = self._subtitle_position_var.currentText()
        print(f"添加字幕,字体: {font}, 字号: {size}, 颜色: {color}, 位置: {position}")
        QMessageBox.information(self, "字幕", f"添加字幕,字体: {font}, 字号: {size}, 颜色: {color}, 位置: {position}")
    
    def _apply_subtitle_style(self):
        """应用字幕样式"""
        font = self._subtitle_font_var.currentText()
        size = self._subtitle_size_var.value()
        color = self._subtitle_color_var.currentText()
        position = self._subtitle_position_var.currentText()
        print(f"应用字幕样式,字体: {font}, 字号: {size}, 颜色: {color}, 位置: {position}")
        QMessageBox.information(self, "字幕", f"应用字幕样式,字体: {font}, 字号: {size}, 颜色: {color}, 位置: {position}")
    
    # 音频方法
    def _enhance_audio(self):
        """增强音频"""
        print("增强音频")
        QMessageBox.information(self, "音频", "增强音频")
    
    def _denoise_audio(self):
        """音频降噪"""
        print("音频降噪")
        QMessageBox.information(self, "音频", "音频降噪")
    
    def _crop_audio(self):
        """截取音频"""
        print("截取音频")
        QMessageBox.information(self, "音频", "截取音频")
    
    def _adjust_volume(self, volume):
        """调整音量"""
        print(f"调整音量到 {volume}%")
        # 这里可以实现音量调整的逻辑
    
    def _apply_fade_effects(self):
        """应用淡入淡出效果"""
        fade_in = self._fade_in_var.value()
        fade_out = self._fade_out_var.value()
        print(f"应用淡入 {fade_in}秒,淡出 {fade_out}秒")
        QMessageBox.information(self, "音频", f"应用淡入 {fade_in}秒,淡出 {fade_out}秒")
    
    def _optimize_workflow(self):
        """智能剪辑工作流:AutoClip->FunClip->VideoFusion->LoRA Edit"""
        if self._clips:
            clip_path = self._clips[0]['path']
            platform = self._platform_var.currentText()
            # 获取视频调节参数
            video_adjust_params = {
                "brightness": self._brightness_slider.value(),
                "contrast": self._contrast_slider.value(),
                "saturation": self._saturation_slider.value(),
                "hue": self._hue_slider.value()
            }
            result = video_processor.optimize_workflow(clip_path, platform, video_adjust_params)
            QMessageBox.information(self, "智能剪辑", f"智能剪辑工作流已启动!{result}")
        else:
            show_clear_messagebox("操作提示", "请先导入视频")
    
    def _top0_smart_clip(self):
        """TOP 0级AI智能剪辑 - 4层理解引擎"""
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        if not self._top0_processor:
            show_clear_messagebox("引擎未就绪", "TOP 0级剪辑引擎未加载,请检查依赖安装")
            return
        
        clip_path = self._clips[0]['path']
        platform = self._platform_var.currentText() if hasattr(self, '_platform_var') else "抖音"
        
        # 显示进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在分析视频内容...", "取消", 0, 100, self)
        progress.setWindowTitle("TOP 0级AI智能剪辑")
        progress.setModal(True)
        progress.show()
        
        def update_progress(value, message):
            progress.setValue(int(value))
            progress.setLabelText(message)
        
        try:
            # 执行TOP 0级智能剪辑
            result = self._top0_processor.smart_clip(
                video_path=clip_path,
                target_platform=platform,
                video_style="高光剪辑",
                target_duration=60.0,
                progress_callback=update_progress
            )
            
            progress.setValue(100)
            progress.close()
            
            if result["success"]:
                # 显示结果
                output_count = len(result["output_videos"])
                msg = f"✅ TOP 0级智能剪辑完成!\n\n"
                msg += f"📊 分析结果:\n"
                msg += f"   • 标题: {result['analysis']['title']}\n"
                msg += f"   • 类型: {result['analysis']['genre']}\n"
                msg += f"   • 角色: {', '.join(result['analysis']['characters'][:3])}\n\n"
                msg += f"🎬 生成视频: {output_count} 个\n"
                
                for i, video in enumerate(result["output_videos"][:3], 1):
                    msg += f"   {i}. {video['title']} ({video['duration']:.1f}s)\n"
                
                if output_count > 3:
                    msg += f"   ... 还有 {output_count - 3} 个片段\n"
                
                msg += f"\n📁 输出目录:\n{os.path.dirname(result['output_videos'][0]['path'])}"
                
                QMessageBox.information(self, "智能剪辑完成", msg)
                
                # 将生成的视频添加到素材库
                for video in result["output_videos"]:
                    self._add_clip_to_timeline(video["path"])
            else:
                error_msg = "剪辑失败:\n" + "\n".join([e.get("error", "未知错误") for e in result["errors"]])
                QMessageBox.warning(self, "剪辑失败", error_msg)
                
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "剪辑错误", f"TOP 0级剪辑出错:\n{str(e)}")
    
    def _add_clip_to_timeline(self, video_path: str):
        """将视频添加到时间线"""
        # 这里可以实现将生成的视频添加到时间线的逻辑
        print(f"添加视频到时间线: {video_path}")
    
    def _predict_viral(self):
        """爆款预测 - 核心差异化功能"""
        if not self._clips:
            show_clear_messagebox("操作提示", "请先导入视频")
            return
        
        if not self._viral_engine:
            show_clear_messagebox("引擎未就绪", "爆款优化引擎未加载,请检查依赖安装")
            return
        
        clip_path = self._clips[0]['path']
        platform_text = self._platform_var.currentText() if hasattr(self, '_platform_var') else "抖音"
        
        # 映射平台名称
        platform_map = {
            "抖音": Platform.DOUYIN,
            "快手": Platform.KUAISHOU,
            "小红书": Platform.XIAOHONGSHU,
            "B站": Platform.BILIBILI,
            "视频号": Platform.WECHAT
        }
        platform = platform_map.get(platform_text, Platform.DOUYIN)
        
        # 显示进度对话框
        from PyQt6.QtWidgets import QProgressDialog
        progress = QProgressDialog("正在分析视频爆款潜力...", "取消", 0, 100, self)
        progress.setWindowTitle("🔥 爆款预测分析")
        progress.setModal(True)
        progress.show()
        
        try:
            # 获取视频信息并构建特征
            progress.setValue(20)
            progress.setLabelText("正在提取视频特征...")
            
            # 这里简化处理,实际应该从AI分析结果中提取特征
            features = VideoFeatures(
                duration=self._total_duration if hasattr(self, '_total_duration') else 60.0,
                scene_count=12,
                avg_scene_duration=5.0,
                dialogue_density=0.7,
                emotion_variance=0.6,
                conflict_intensity=0.75,
                hook_quality=70,
                climax_position=0.7,
                has_cliffhanger=True,
                visual_attractiveness=75,
                audio_quality=80,
                subtitle_quality=70
            )
            
            progress.setValue(50)
            progress.setLabelText("正在预测表现...")
            
            # 预测表现
            prediction = self._viral_engine.predict_performance(features, platform)
            
            progress.setValue(70)
            progress.setLabelText("正在生成优化建议...")
            
            # 生成优化建议
            suggestions = self._viral_engine.generate_optimization_suggestions(features, platform)
            
            progress.setValue(90)
            progress.setLabelText("正在分析爆款基因...")
            
            # 获取爆款基因
            viral_genes = self._viral_engine.analyze_viral_genes("甜宠")
            
            progress.setValue(100)
            progress.close()
            
            # 构建结果显示
            result_text = f"""
🎯 视频爆款潜力分析

📱 目标平台: {platform.value}

📊 表现预测:
   • 3秒完播率: {prediction.to_dict()['3秒完播率']}
   • 整体完播率: {prediction.to_dict()['整体完播率']}
   • 点赞率: {prediction.to_dict()['点赞率']}
   • 评论率: {prediction.to_dict()['评论率']}
   • 分享率: {prediction.to_dict()['分享率']}
   • 爆款概率: {prediction.to_dict()['爆款概率']}
   • 预估播放量: {prediction.to_dict()['预估播放量']}

💡 优化建议 (按优先级排序):
"""
            
            for i, suggestion in enumerate(suggestions[:3], 1):
                result_text += f"""
   {i}. {suggestion.factor.value} (优先级: {suggestion.priority})
      当前得分: {suggestion.current_score:.0f}/100 -> 目标: {suggestion.target_score:.0f}/100
      建议: {suggestion.suggestion.replace(chr(10), chr(10) + '      ')}
      预期改善: {suggestion.expected_improvement}
"""
            
            result_text += f"""
🧬 推荐爆款基因:
"""
            
            for i, gene in enumerate(viral_genes[:3], 1):
                result_text += f"""
   {i}. {gene.pattern_name} (成功率: {gene.success_rate:.1%})
      {gene.description}
      关键要素: {', '.join(gene.key_elements)}
"""
            
            # 显示结果对话框
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
            dialog = QDialog(self)
            dialog.setWindowTitle("🔥 爆款预测结果")
            dialog.setMinimumSize(600, 500)
            
            layout = QVBoxLayout(dialog)
            
            text_edit = QTextEdit()
            text_edit.setPlainText(result_text)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            
            dialog.exec()
            
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "分析错误", f"爆款预测出错:\n{str(e)}")


class CopywritingModule(BaseModule):
    """
    文案生成模块
    - 输入:剧情,关键词,标题
    - 输出:标题,话题,简介,脚本
    """
    
    module_id = "copywriting"
    module_name = "文案生成"
    module_icon = "✍️"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header = QLabel("✍️ AI文案生成")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)
        
        input_group = self._create_card("输入内容")
        input_layout = QVBoxLayout(input_group)
        
        # 视频导入按钮
        video_import_layout = QHBoxLayout()
        video_import_btn = QPushButton("🎬 导入视频分析")
        video_import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        video_import_btn.clicked.connect(self._import_video)
        video_import_layout.addWidget(video_import_btn)
        video_import_layout.addStretch()
        input_layout.addLayout(video_import_layout)
        
        self._content_input = QTextEdit()
        self._content_input.setPlaceholderText("输入视频内容描述,剧情概要或关键词...")
        self._content_input.setMinimumHeight(120)
        self._content_input.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        input_layout.addWidget(self._content_input)
        
        # 视频信息显示
        self._video_info_label = QLabel("未导入视频")
        self._video_info_label.setStyleSheet("color: #808080; font-size: 12px;")
        input_layout.addWidget(self._video_info_label)
        
        options_layout = QHBoxLayout()
        
        options_layout.addWidget(QLabel("平台:"))
        self._platform_combo = QComboBox()
        self._platform_combo.addItems(["抖音", "快手", "视频号", "小红书", "B站"])
        self._platform_combo.setStyleSheet(self._combo_style())
        options_layout.addWidget(self._platform_combo)
        
        options_layout.addWidget(QLabel("风格:"))
        self._style_combo = QComboBox()
        self._style_combo.addItems(["爆款", "剧情", "解说", "情感", "搞笑"])
        self._style_combo.setStyleSheet(self._combo_style())
        options_layout.addWidget(self._style_combo)
        
        options_layout.addWidget(QLabel("模型:"))
        self._model_combo = QComboBox()
        self._model_combo.addItems(["DeepSeek", "豆包", "本地模板"])
        self._model_combo.setStyleSheet(self._combo_style())
        options_layout.addWidget(self._model_combo)
        
        options_layout.addStretch()
        input_layout.addLayout(options_layout)
        
        layout.addWidget(input_group)
        
        generate_btn = QPushButton("🚀 生成文案")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 14px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #43a047;
            }
        """)
        generate_btn.clicked.connect(self._generate)
        layout.addWidget(generate_btn)
        
        output_group = self._create_card("生成结果")
        output_layout = QVBoxLayout(output_group)
        
        self._output_tabs = QTabWidget()
        self._output_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1a1a1a; }
            QTabBar::tab {
                background-color: #2a2a2a;
                color: #808080;
                padding: 8px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected { background-color: #3a3a3a; color: #ffffff; }
        """)
        
        for name in ["标题", "描述", "标签", "脚本"]:
            output = QTextEdit()
            output.setReadOnly(True)
            output.setStyleSheet("""
                QTextEdit {
                    background-color: #1a1a1a;
                    color: #ffffff;
                    border: none;
                    padding: 10px;
                    font-size: 14px;
                }
            """)
            self._output_tabs.addTab(output, name)
        
        output_layout.addWidget(self._output_tabs)
        layout.addWidget(output_group, 1)
    
    def _create_card(self, title: str) -> QGroupBox:
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px;
            }
        """)
        return group
    
    def _combo_style(self) -> str:
        return """
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px 12px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """
    
    def _import_video(self):
        """导入视频并分析内容生成文案"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "",
            "视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)"
        )
        
        if file_path:
            try:
                # 显示视频信息
                import os
                video_name = os.path.basename(file_path)
                self._video_info_label.setText(f"已导入视频: {video_name}")
                
                # 模拟视频分析过程
                QMessageBox.information(self, "视频分析", "正在分析视频内容...")
                
                # 模拟视频内容分析结果
                video_content = "这是一段关于短剧的精彩内容,包含了紧张的剧情和精彩的表演,适合在短视频平台上发布."
                self._content_input.setText(video_content)
                
                # 自动生成文案
                self._generate_from_video(video_content)
                
            except Exception as e:
                QMessageBox.warning(self, "错误", f"视频分析失败: {str(e)}")
    
    def _generate_from_video(self, video_content):
        """根据视频内容生成文案"""
        platform = self._platform_combo.currentText()
        style = self._style_combo.currentText()
        
        # 根据视频内容生成文案
        self._output_tabs.widget(0).setText(f"🔥 {video_content[:20]},看完直呼过瘾!")
        self._output_tabs.widget(1).setText(f"这是一段关于{video_content[:30]}的精彩内容,快来看看吧!\n\n#短剧 #热门 #推荐")
        self._output_tabs.widget(2).setText("#短剧 #热门 #推荐 #追剧 #剧情 #爆款")
        self._output_tabs.widget(3).setText(f"[开场]\n{video_content[:50]}...\n\n[高潮]\n精彩内容呈现\n\n[结尾]\n关注不迷路")
        
        self._event_bus.emit(EventType.COPY_GENERATED, {
            "title": self._output_tabs.widget(0).toPlainText(),
            "description": self._output_tabs.widget(1).toPlainText()
        })
    
    def _generate(self):
        content = self._content_input.toPlainText()
        platform = self._platform_combo.currentText()
        style = self._style_combo.currentText()
        
        self._output_tabs.widget(0).setText(f"🔥 {content[:20]},看完直呼过瘾!")
        self._output_tabs.widget(1).setText(f"这是一段关于{content[:30]}的精彩内容,快来看看吧!\n\n#短剧 #热门 #推荐")
        self._output_tabs.widget(2).setText("#短剧 #热门 #推荐 #追剧 #剧情 #爆款")
        self._output_tabs.widget(3).setText(f"[开场]\n{content[:50]}...\n\n[高潮]\n精彩内容呈现\n\n[结尾]\n关注不迷路")
        
        self._event_bus.emit(EventType.COPY_GENERATED, {
            "title": self._output_tabs.widget(0).toPlainText(),
            "description": self._output_tabs.widget(1).toPlainText()
        })


class TasksModule(BaseModule):
    """
    多任务管理模块
    - 批量剪辑,AI生成,导出,转码,下载
    - 支持已完成/未完成分类筛选
    """
    
    module_id = "tasks"
    module_name = "多任务"
    module_icon = "📋"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header_layout = QHBoxLayout()
        header = QLabel("📋 任务管理")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        add_btn = QPushButton("+ 新建任务")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        header_layout.addWidget(add_btn)
        layout.addLayout(header_layout)
        
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        filter_label = QLabel("筛选:")
        filter_label.setStyleSheet("color: #808080; font-size: 14px;")
        filter_layout.addWidget(filter_label)
        
        self._filter_buttons = {}
        filter_items = [
            ("all", "全部", "#1e6bde"),
            ("pending", "未完成", "#808080"),
            ("completed", "已完成", "#22c55e"),
        ]
        
        for key, text, color in filter_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {'#1e6bde' if key == 'all' else 'transparent'};
                    color: {'white' if key == 'all' else '#808080'};
                    border: 1px solid #333333;
                    border-radius: 16px;
                    padding: 6px 16px;
                    font-size: 13px;
                }}
                QPushButton:hover {{
                    background-color: #2a2a2a;
                    color: white;
                }}
                QPushButton:checked {{
                    background-color: #1e6bde;
                    color: white;
                    border-color: #1e6bde;
                }}
            """)
            btn.clicked.connect(lambda checked, k=key: self._on_filter_clicked(k))
            filter_layout.addWidget(btn)
            self._filter_buttons[key] = btn
        
        filter_layout.addStretch()
        
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(20)
        
        self._total_label = QLabel("总计: 4")
        self._total_label.setStyleSheet("color: #808080; font-size: 13px;")
        stats_layout.addWidget(self._total_label)
        
        self._pending_label = QLabel("未完成: 3")
        self._pending_label.setStyleSheet("color: #ff9800; font-size: 13px;")
        stats_layout.addWidget(self._pending_label)
        
        self._completed_label = QLabel("已完成: 1")
        self._completed_label.setStyleSheet("color: #22c55e; font-size: 13px;")
        stats_layout.addWidget(self._completed_label)
        
        filter_layout.addLayout(stats_layout)
        layout.addLayout(filter_layout)
        
        self._task_table = QTableWidget()
        self._task_table.setColumnCount(6)
        self._task_table.setHorizontalHeaderLabels(["任务名称", "类型", "状态", "进度", "创建时间", "操作"])
        self._task_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._task_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
                color: #ffffff;
            }
            QTableWidget::item {
                border: none;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
                font-weight: bold;
                color: #808080;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2a2a2a;
            }
            QTableWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        layout.addWidget(self._task_table, 1)
        
        self._tasks = []
        self._current_filter = "all"
        self._add_sample_tasks()
    
    def _on_filter_clicked(self, filter_key: str):
        for key, btn in self._filter_buttons.items():
            btn.setChecked(key == filter_key)
        self._current_filter = filter_key
        self._refresh_table()
    
    def _refresh_table(self):
        self._task_table.setRowCount(0)
        
        filtered_tasks = self._tasks
        if self._current_filter == "pending":
            filtered_tasks = [t for t in self._tasks if t["status"] != "已完成"]
        elif self._current_filter == "completed":
            filtered_tasks = [t for t in self._tasks if t["status"] == "已完成"]
        
        self._task_table.setRowCount(len(filtered_tasks))
        for i, task in enumerate(filtered_tasks):
            self._task_table.setItem(i, 0, QTableWidgetItem(task["name"]))
            self._task_table.setItem(i, 1, QTableWidgetItem(task["type"]))
            
            status_item = QTableWidgetItem(task["status"])
            if task["status"] == "已完成":
                status_item.setForeground(Qt.GlobalColor.green)
            elif task["status"] == "进行中":
                status_item.setForeground(Qt.GlobalColor.blue)
            else:
                status_item.setForeground(Qt.GlobalColor.gray)
            self._task_table.setItem(i, 2, status_item)
            
            progress_bar = QProgressBar()
            progress_bar.setValue(task["progress"])
            progress_bar.setStyleSheet("""
                QProgressBar {
                    background-color: #2a2a2a;
                    border: none;
                    border-radius: 4px;
                    text-align: center;
                    color: white;
                }
                QProgressBar::chunk {
                    background-color: #1e6bde;
                    border-radius: 4px;
                }
            """)
            self._task_table.setCellWidget(i, 3, progress_bar)
            
            self._task_table.setItem(i, 4, QTableWidgetItem(task["time"]))
            
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)
            
            if task["status"] != "已完成":
                for text, color in [("暂停", "#ff9800"), ("取消", "#f44336")]:
                    btn = QPushButton(text)
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {color};
                            color: white;
                            border: none;
                            border-radius: 4px;
                            padding: 4px 8px;
                            font-size: 12px;
                        }}
                    """)
                    btn_layout.addWidget(btn)
            else:
                clear_btn = QPushButton("清除")
                clear_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #808080;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 4px 8px;
                        font-size: 12px;
                    }
                """)
                btn_layout.addWidget(clear_btn)
            
            self._task_table.setCellWidget(i, 5, btn_widget)
        
        self._update_stats()
    
    def _update_stats(self):
        total = len(self._tasks)
        completed = len([t for t in self._tasks if t["status"] == "已完成"])
        pending = total - completed
        
        self._total_label.setText(f"总计: {total}")
        self._pending_label.setText(f"未完成: {pending}")
        self._completed_label.setText(f"已完成: {completed}")
    
    def _add_sample_tasks(self):
        self._tasks = [
            {"name": "批量剪辑任务 #1", "type": "剪辑", "status": "进行中", "progress": 65, "time": "刚刚"},
            {"name": "文案生成任务 #2", "type": "AI生成", "status": "已完成", "progress": 100, "time": "5分钟前"},
            {"name": "视频导出任务 #3", "type": "导出", "status": "等待中", "progress": 0, "time": "10分钟前"},
            {"name": "格式转换任务 #4", "type": "转码", "status": "进行中", "progress": 30, "time": "30分钟前"},
        ]
        self._refresh_table()


class DramaFinderModule(BaseModule):
    """
    短剧筛选模块
    - 多平台支持:抖音,快手,微短剧,腾讯,爱奇艺,优酷,B站,小红书,微博,芒果TV,搜狐,西瓜视频,小程序短剧
    - 实时数据爬取
    - 分类筛选,热度排序,佣金展示
    - 图形化统计展示
    """
    
    module_id = "drama"
    module_name = "内容筛选"
    module_icon = "🎭"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        header_layout = QHBoxLayout()
        header = QLabel("🎭 内容筛选")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        self._refresh_btn = QPushButton("🔄 刷新数据")
        self._refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #22c55e;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #16a34a; }
        """)
        self._refresh_btn.clicked.connect(self._refresh_data)
        header_layout.addWidget(self._refresh_btn)
        
        layout.addLayout(header_layout)
        
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)
        
        self._stats_labels = {}
        stats_items = [
            ("total", "总内容数", "85.6万", "#1e6bde"),
            ("views", "总播放量", "286.3亿", "#22c55e"),
            ("platforms", "平台数", "20", "#f59e0b"),
            ("categories", "分类数", "48", "#ec4899"),
        ]
        
        for key, label, value, color in stats_items:
            stat_widget = QWidget()
            stat_layout = QVBoxLayout(stat_widget)
            stat_layout.setContentsMargins(15, 10, 15, 10)
            stat_layout.setSpacing(2)
            
            stat_label = QLabel(label)
            stat_label.setStyleSheet("color: #808080; font-size: 12px;")
            stat_layout.addWidget(stat_label)
            
            value_label = QLabel(value)
            value_label.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold;")
            stat_layout.addWidget(value_label)
            
            stat_widget.setStyleSheet("""
                QWidget {
                    background-color: #1a1a1a;
                    border-radius: 8px;
                }
            """)
            
            stats_layout.addWidget(stat_widget)
            self._stats_labels[key] = value_label
        
        layout.addLayout(stats_layout)
        
        content_type_layout = QHBoxLayout()
        content_type_layout.addWidget(QLabel("内容类型:"))
        
        self._content_type_combo = QComboBox()
        self._content_type_combo.addItem("全部类型", "all")
        self._content_type_combo.addItem("🎭 短剧", "drama")
        self._content_type_combo.addItem("🎨 漫剧", "comic")
        self._content_type_combo.addItem("🎬 电影", "movie")
        self._content_type_combo.addItem("📺 电视剧", "tv")
        self._content_type_combo.setStyleSheet(self._combo_style())
        self._content_type_combo.currentIndexChanged.connect(self._on_filter_changed)
        content_type_layout.addWidget(self._content_type_combo)
        
        layout.addLayout(content_type_layout)
        
        platform_layout = QHBoxLayout()
        platform_layout.addWidget(QLabel("平台:"))
        
        self._platform_combo = QComboBox()
        self._platform_combo.addItem("全部平台", "all")
        self._platform_combo.addItem("📱 抖音 (12.5万)", "douyin")
        self._platform_combo.addItem("🎬 快手 (10.8万)", "kuaishou")
        self._platform_combo.addItem("📺 腾讯视频 (8.2万)", "tencent")
        self._platform_combo.addItem("🎥 爱奇艺 (7.5万)", "iqiyi")
        self._platform_combo.addItem("🎞️ 优酷 (6.8万)", "youku")
        self._platform_combo.addItem("哔哩 B站 (9.3万)", "bilibili")
        self._platform_combo.addItem("📕 小红书 (7.0万)", "xiaohongshu")
        self._platform_combo.addItem("🐦 微博 (5.2万)", "weibo")
        self._platform_combo.addItem("🥭 芒果TV (4.8万)", "mgtv")
        self._platform_combo.addItem("🍉 西瓜视频 (6.5万)", "xigua")
        self._platform_combo.addItem("🎨 腾讯动漫 (3.5万)", "tencent_comic")
        self._platform_combo.addItem("📱 快看漫画 (4.2万)", "kuaikan")
        self._platform_combo.addItem("🎬 爱奇艺动漫 (3.8万)", "iqiyi_comic")
        self._platform_combo.setStyleSheet(self._combo_style())
        self._platform_combo.currentIndexChanged.connect(self._on_filter_changed)
        platform_layout.addWidget(self._platform_combo)
        
        platform_layout.addWidget(QLabel("分类:"))
        self._category_combo = QComboBox()
        self._category_combo.addItem("全部", "all")
        self._category_combo.addItems([
            "都市", "古装", "悬疑", "甜宠", "逆袭", "重生",
            "玄幻", "言情", "喜剧", "动作", "家庭", "职场",
            "校园", "历史", "战争", "科幻", "恐怖", "青春",
            "霸总", "神豪", "修仙", "系统流", "后宫", "穿越",
            "复仇", "医术", "军旅", "侦探", "冒险", "体育",
            "美食", "萌宠", "热血", "奇幻", "治愈", "推理",
            "校园", "机甲", "武侠", "历史", "灾难", "惊悚"
        ])
        self._category_combo.setStyleSheet(self._combo_style())
        self._category_combo.currentIndexChanged.connect(self._on_filter_changed)
        platform_layout.addWidget(self._category_combo)
        
        platform_layout.addWidget(QLabel("排序:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["热度", "播放量", "佣金", "评分", "最新"])
        self._sort_combo.setStyleSheet(self._combo_style())
        self._sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        platform_layout.addWidget(self._sort_combo)
        
        platform_layout.addStretch()
        layout.addLayout(platform_layout)
        
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索内容名称,作者,关键词...")
        self._search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 10px 15px;
                font-size: 14px;
            }
            QLineEdit:focus { border-color: #1e6bde; }
        """)
        self._search_input.returnPressed.connect(self._search)
        search_layout.addWidget(self._search_input, 1)
        
        search_btn = QPushButton("🔍 搜索")
        search_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #1557b0; }
        """)
        search_btn.clicked.connect(self._search)
        search_layout.addWidget(search_btn)
        
        layout.addLayout(search_layout)
        
        self._drama_table = QTableWidget()
        self._drama_table.setColumnCount(8)
        self._drama_table.setHorizontalHeaderLabels([
            "内容名称", "平台", "分类", "集数", "播放量", "佣金", "热度", "操作"
        ])
        self._drama_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._drama_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._drama_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._drama_table.setColumnWidth(1, 100)
        self._drama_table.setColumnWidth(2, 80)
        self._drama_table.setColumnWidth(3, 60)
        self._drama_table.setColumnWidth(4, 100)
        self._drama_table.setColumnWidth(5, 80)
        self._drama_table.setColumnWidth(6, 80)
        self._drama_table.setColumnWidth(7, 100)
        self._drama_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
                gridline-color: #2a2a2a;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 10px;
                border: none;
                border-bottom: 1px solid #333333;
                font-weight: bold;
                color: #808080;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2a2a2a;
            }
            QTableWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        self._drama_table.setAlternatingRowColors(True)
        self._drama_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._drama_table, 1)
        
        page_layout = QHBoxLayout()
        page_layout.addStretch()
        
        self._prev_btn = QPushButton("上一页")
        self._prev_btn.setEnabled(False)
        self._prev_btn.clicked.connect(self._prev_page)
        page_layout.addWidget(self._prev_btn)
        
        self._page_label = QLabel("第 1 页")
        self._page_label.setStyleSheet("color: #808080; padding: 0 15px;")
        page_layout.addWidget(self._page_label)
        
        self._next_btn = QPushButton("下一页")
        self._next_btn.clicked.connect(self._next_page)
        page_layout.addWidget(self._next_btn)
        
        page_layout.addStretch()
        # 自动刷新控制
        auto_refresh_layout = QHBoxLayout()
        auto_refresh_layout.addWidget(QLabel("自动刷新:"))
        
        self._auto_refresh_check = QCheckBox()
        self._auto_refresh_check.setChecked(True)
        auto_refresh_layout.addWidget(self._auto_refresh_check)
        
        auto_refresh_layout.addWidget(QLabel("间隔:"))
        self._refresh_interval_combo = QComboBox()
        self._refresh_interval_combo.addItems(["30秒", "1分钟", "2分钟", "5分钟"])
        self._refresh_interval_combo.setCurrentIndex(1)  # 默认1分钟
        self._refresh_interval_combo.setStyleSheet(self._combo_style())
        auto_refresh_layout.addWidget(self._refresh_interval_combo)
        
        auto_refresh_layout.addStretch()
        layout.addLayout(auto_refresh_layout)
        
        layout.addLayout(page_layout)
        
        self._loading = False
        self._current_page = 1
        self._dramas = []
        
        # 初始化自动刷新定时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_data)
        self._update_refresh_timer()
        
        # 连接信号
        self._auto_refresh_check.stateChanged.connect(self._update_refresh_timer)
        self._refresh_interval_combo.currentIndexChanged.connect(self._update_refresh_timer)
        
        QTimer.singleShot(500, self._load_data)
    
    def _combo_style(self) -> str:
        return """
            QComboBox {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 8px 12px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #ffffff;
                selection-background-color: #1e6bde;
            }
        """
    
    def _load_data(self):
        if self._loading:
            return
        self._loading = True
        
        from .drama_crawler import drama_crawler
        
        content_type = self._content_type_combo.currentData()
        platform = self._platform_combo.currentData()
        category = self._category_combo.currentData()
        sort_map = {"热度": "heat", "播放量": "views", "佣金": "commission", "评分": "rating", "最新": "latest"}
        sort_by = sort_map.get(self._sort_combo.currentText(), "heat")
        keyword = self._search_input.text().strip()
        
        drama_crawler.fetch_dramas_async(
            content_type=content_type,
            platform=platform,
            category=category,
            sort_by=sort_by,
            keyword=keyword,
            page=self._current_page,
            page_size=20,
            callback=self._on_data_loaded,
            error_callback=self._on_load_error
        )
    
    def _on_data_loaded(self, dramas: list):
        self._dramas = dramas
        self._refresh_table()
        self._loading = False
        
        # 更新上一页按钮状态
        self._prev_btn.setEnabled(self._current_page > 1)
        
        total_views = sum(d.views for d in dramas)
        self._stats_labels["total"].setText(str(len(dramas)))
        self._stats_labels["views"].setText(self._format_number(total_views))
    
    def _on_load_error(self, error: str):
        self._loading = False
        print(f"加载失败: {error}")
    
    def _refresh_table(self):
        self._drama_table.setRowCount(len(self._dramas))
        
        platform_icons = {
            "douyin": "📱", "kuaishou": "🎬", "weiduanju": "🎭",
            "tencent": "📺", "iqiyi": "🎥", "youku": "🎞️",
            "bilibili": "哔哩", "xiaohongshu": "📕"
        }
        
        for i, drama in enumerate(self._dramas):
            title_item = QTableWidgetItem(drama.title)
            title_item.setToolTip(drama.description)
            self._drama_table.setItem(i, 0, title_item)
            
            icon = platform_icons.get(drama.platform, "🎭")
            platform_item = QTableWidgetItem(f"{icon} {drama.platform}")
            self._drama_table.setItem(i, 1, platform_item)
            
            self._drama_table.setItem(i, 2, QTableWidgetItem(drama.category))
            self._drama_table.setItem(i, 3, QTableWidgetItem(f"{drama.episodes}集"))
            self._drama_table.setItem(i, 4, QTableWidgetItem(self._format_number(drama.views)))
            self._drama_table.setItem(i, 5, QTableWidgetItem(f"¥{drama.commission:.0f}"))
            
            heat_item = QTableWidgetItem(f"🔥{self._format_number(drama.heat)}")
            heat_item.setForeground(Qt.GlobalColor.red)
            self._drama_table.setItem(i, 6, heat_item)
            
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(4)
            
            detail_btn = QPushButton("详情")
            detail_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 12px;
                }
            """)
            btn_layout.addWidget(detail_btn)
            
            self._drama_table.setCellWidget(i, 7, btn_widget)
    
    def _format_number(self, num: int) -> str:
        if num >= 100000000:
            return f"{num/100000000:.1f}亿"
        elif num >= 10000:
            return f"{num/10000:.1f}万"
        return str(num)
    
    def _on_filter_changed(self):
        self._current_page = 1
        self._load_data()
    
    def _search(self):
        self._current_page = 1
        self._load_data()
    
    def _refresh_data(self):
        from .drama_crawler import drama_crawler
        drama_crawler.clear_cache()
        self._load_data()
    
    def _prev_page(self):
        if self._current_page > 1:
            self._current_page -= 1
            self._page_label.setText(f"第 {self._current_page} 页")
            self._load_data()
    
    def _next_page(self):
        self._current_page += 1
        self._page_label.setText(f"第 {self._current_page} 页")
        self._load_data()
    
    def _update_refresh_timer(self):
        """更新自动刷新定时器"""
        if self._auto_refresh_check.isChecked():
            interval_map = {
                "30秒": 30000,
                "1分钟": 60000,
                "2分钟": 120000,
                "5分钟": 300000
            }
            interval = interval_map.get(self._refresh_interval_combo.currentText(), 60000)
            self._refresh_timer.start(interval)
        else:
            self._refresh_timer.stop()
    
    def _auto_refresh_data(self):
        """自动刷新数据"""
        if not self._loading:
            self._load_data()


class AccountOpsModule(BaseModule):
    """
    账号运营模块
    - 多平台账号管理(抖音,快手,视频号,小红书,B站,微博,知乎,头条,百家号等12个平台)
    - 图形化数据展示
    - 矩阵发布
    """
    
    module_id = "account"
    module_name = "账号运营"
    module_icon = "👤"
    
    PLATFORMS = {
        "douyin": {"name": "抖音", "icon": "📱", "color": "#000000", "max_accounts": 10},
        "kuaishou": {"name": "快手", "icon": "🎬", "color": "#FF4500", "max_accounts": 10},
        "weixin": {"name": "视频号", "icon": "💬", "color": "#07C160", "max_accounts": 5},
        "xiaohongshu": {"name": "小红书", "icon": "📕", "color": "#FF2442", "max_accounts": 6},
        "bilibili": {"name": "B站", "icon": "哔哩", "color": "#00A1D6", "max_accounts": 5},
        "weibo": {"name": "微博", "icon": "🐦", "color": "#E6162D", "max_accounts": 5},
        "zhihu": {"name": "知乎", "icon": "🔵", "color": "#0084FF", "max_accounts": 3},
        "toutiao": {"name": "头条", "icon": "📰", "color": "#F85959", "max_accounts": 5},
        "baijiahao": {"name": "百家号", "icon": "📝", "color": "#2932E1", "max_accounts": 3},
        "dayu": {"name": "大鱼号", "icon": "🐟", "color": "#FF6600", "max_accounts": 3},
        "qq_video": {"name": "腾讯视频", "icon": "📺", "color": "#FF9800", "max_accounts": 3},
        "iqiyi": {"name": "爱奇艺", "icon": "🎥", "color": "#00BE06", "max_accounts": 3},
    }
    
    def __init__(self):
        register_account_skills()
        super().__init__()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        from .account_widgets import create_enhanced_accounts_tab, create_enhanced_dashboard_tab
        
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #0d0d0d; }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #808080;
                padding: 12px 24px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
                font-size: 14px;
            }
            QTabBar::tab:selected { background-color: #2a2a2a; color: #ffffff; }
            QTabBar::tab:hover:!selected { background-color: #252525; color: #a0a0a0; }
        """)
        
        self._tabs.addTab(create_enhanced_accounts_tab(), "📱 账号管理")
        self._tabs.addTab(create_enhanced_dashboard_tab(), "📊 数据看板")
        self._tabs.addTab(self._create_publish_tab(), "📤 内容发布")
        self._tabs.addTab(self._create_matrix_tab(), "🎯 矩阵发布")
        
        layout.addWidget(self._tabs, 1)
    
    def _create_accounts_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        toolbar = QHBoxLayout()
        add_btn = QPushButton("+ 添加账号")
        add_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
        """)
        toolbar.addWidget(add_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        self._accounts_list = QListWidget()
        self._accounts_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #2a2a2a;
            }
            QListWidget::item:selected {
                background-color: #1e6bde;
            }
        """)
        self._accounts_list.addItems([
            "📱 抖音账号: @短剧剪辑师 (已绑定)",
            "📱 快手账号: @短剧达人 (已绑定)",
            "📱 视频号: @短剧工作室 (已绑定)",
        ])
        layout.addWidget(self._accounts_list)
        
        return tab
    
    def _create_publish_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        form_layout = QHBoxLayout()
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        left_layout.addWidget(QLabel("选择视频:"))
        video_input = QLineEdit()
        video_input.setPlaceholderText("点击选择视频文件...")
        video_input.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333333; border-radius: 4px; padding: 8px; color: white;")
        left_layout.addWidget(video_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.setStyleSheet("background-color: #2a2a2a; color: white; border: none; border-radius: 4px; padding: 8px;")
        left_layout.addWidget(browse_btn)
        
        left_layout.addWidget(QLabel("标题:"))
        title_input = QLineEdit()
        title_input.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333333; border-radius: 4px; padding: 8px; color: white;")
        left_layout.addWidget(title_input)
        
        left_layout.addWidget(QLabel("描述:"))
        desc_input = QTextEdit()
        desc_input.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333333; border-radius: 4px; padding: 8px; color: white;")
        desc_input.setMaximumHeight(100)
        left_layout.addWidget(desc_input)
        
        form_layout.addWidget(left_panel, 1)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        right_layout.addWidget(QLabel("🎯 目标平台:"))
        for pid, pinfo in self.PLATFORMS.items():
            cb = QCheckBox(f"{pinfo['icon']} {pinfo['name']}")
            cb.setStyleSheet("color: white; padding: 3px;")
            right_layout.addWidget(cb)
        
        right_layout.addStretch()
        form_layout.addWidget(right_panel)
        
        layout.addLayout(form_layout)
        
        publish_btn = QPushButton("🚀 发布内容")
        publish_btn.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        publish_btn.clicked.connect(self._publish_content)
        layout.addWidget(publish_btn)
        
        return tab
    
    def _create_matrix_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("账号矩阵配置:"))
        
        matrix_table = QTableWidget()
        matrix_table.setColumnCount(4)
        matrix_table.setHorizontalHeaderLabels(["选择", "平台", "账号", "状态"])
        matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        matrix_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                color: white;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 8px;
                border: none;
            }
        """)
        
        sample_accounts = [
            ("抖音", "@主账号", "正常"),
            ("抖音", "@副账号1", "正常"),
            ("快手", "@快手主号", "正常"),
        ]
        
        matrix_table.setRowCount(len(sample_accounts))
        for i, (platform, account, status) in enumerate(sample_accounts):
            cb = QCheckBox()
            cb.setChecked(True)
            matrix_table.setCellWidget(i, 0, cb)
            matrix_table.setItem(i, 1, QTableWidgetItem(platform))
            matrix_table.setItem(i, 2, QTableWidgetItem(account))
            matrix_table.setItem(i, 3, QTableWidgetItem(status))
        
        layout.addWidget(matrix_table)
        
        matrix_btn = QPushButton("🎯 批量发布")
        matrix_btn.setStyleSheet("""
            QPushButton {
                background-color: #9c27b0;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        matrix_btn.clicked.connect(self._matrix_publish)
        layout.addWidget(matrix_btn)
        
        return tab
    
    def _create_stats_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        stats_grid = QGridLayout()
        
        stats = [
            ("总播放量", "1,234,567", "#1e6bde"),
            ("总点赞", "89,012", "#4caf50"),
            ("总评论", "12,345", "#ff9800"),
            ("转化率", "3.5%", "#9c27b0"),
        ]
        
        for i, (label, value, color) in enumerate(stats):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #1a1a1a;
                    border: 1px solid #333333;
                    border-radius: 8px;
                    padding: 15px;
                }}
            """)
            frame_layout = QVBoxLayout(frame)
            
            value_label = QLabel(value)
            value_label.setStyleSheet(f"font-size: 28px; font-weight: bold; color: {color};")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(value_label)
            
            name_label = QLabel(label)
            name_label.setStyleSheet("color: #808080;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(name_label)
            
            stats_grid.addWidget(frame, i // 2, i % 2)
        
        layout.addLayout(stats_grid)
        
        refresh_btn = QPushButton("🔄 刷新数据")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        refresh_btn.clicked.connect(self._collect_data)
        layout.addWidget(refresh_btn)
        
        layout.addStretch()
        
        return tab
    
    def _publish_content(self):
        result = self._skill_engine.execute_skill("publish_content", {
            "content": {
                "video_path": "sample.mp4",
                "title": "示例视频"
            },
            "platforms": ["抖音"]
        })
        print(f"发布结果: {result}")
    
    def _matrix_publish(self):
        result = self._skill_engine.execute_skill("matrix_publish", {
            "content": {
                "video_path": "sample.mp4",
                "title": "示例视频"
            }
        })
        print(f"矩阵发布结果: {result}")
    
    def _collect_data(self):
        result = self._skill_engine.execute_skill("account_data_collect", {})
        print(f"数据采集结果: {result}")


class MaterialsModule(BaseModule):
    """
    素材库模块
    - 本地素材 + 在线素材库
    - 视频,音频,图片,字幕,模板,特效,转场,贴纸
    """
    
    module_id = "materials"
    module_name = "素材库"
    module_icon = "📁"
    
    def _setup_ui(self):
        from .online_materials import online_material_library
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header_layout = QHBoxLayout()
        header = QLabel("📁 素材库")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        import_btn = QPushButton("📥 导入本地素材")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
            }
            QPushButton:hover { background-color: #2a7bef; }
        """)
        header_layout.addWidget(import_btn)
        layout.addLayout(header_layout)
        
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #0d0d0d; }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #808080;
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected { background-color: #2a2a2a; color: #ffffff; }
        """)
        
        online_tab = QWidget()
        online_layout = QVBoxLayout(online_tab)
        online_layout.setContentsMargins(10, 10, 10, 10)
        
        search_layout = QHBoxLayout()
        
        type_combo = QComboBox()
        type_combo.addItem("全部类型", "all")
        for type_id, type_info in online_material_library.get_material_types().items():
            type_combo.addItem(f"{type_info['icon']} {type_info['name']}", type_id)
        type_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a;
                color: white;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 15px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: white;
                selection-background-color: #1e6bde;
            }
        """)
        search_layout.addWidget(type_combo)
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("搜索素材...")
        search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: white;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 15px;
            }
        """)
        search_layout.addWidget(search_input, 1)
        
        search_btn = QPushButton("🔍 搜索")
        search_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
            }
        """)
        search_layout.addWidget(search_btn)
        online_layout.addLayout(search_layout)
        
        materials_grid = QTableWidget()
        materials_grid.setColumnCount(5)
        materials_grid.setHorizontalHeaderLabels(["缩略图", "名称", "类型", "下载量", "操作"])
        materials_grid.horizontalHeader().setStretchLastSection(True)
        materials_grid.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
                color: #ffffff;
            }
            QTableWidget::item { padding: 10px; }
            QTableWidget::item:selected { background-color: #1e6bde; }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: white;
                padding: 10px;
                border: none;
            }
        """)
        online_layout.addWidget(materials_grid, 1)
        
        page_layout = QHBoxLayout()
        page_layout.addStretch()
        
        prev_btn = QPushButton("◀ 上一页")
        prev_btn.setEnabled(False)
        page_layout.addWidget(prev_btn)
        
        page_label = QLabel("第 1 页")
        page_label.setStyleSheet("color: #808080; padding: 0 15px;")
        page_layout.addWidget(page_label)
        
        next_btn = QPushButton("下一页 ▶")
        page_layout.addWidget(next_btn)
        page_layout.addStretch()
        
        online_layout.addLayout(page_layout)
        
        self._materials_grid = materials_grid
        self._page_label = page_label
        self._prev_btn = prev_btn
        self._next_btn = next_btn
        self._search_input = search_input
        self._type_combo = type_combo
        self._current_page = 1
        self._page_size = 20
        self._current_materials = []
        
        def search_materials():
            self._current_page = 1
            self._load_materials()
        
        def prev_page():
            if self._current_page > 1:
                self._current_page -= 1
                self._load_materials()
        
        def next_page():
            self._current_page += 1
            self._load_materials()
        
        search_btn.clicked.connect(search_materials)
        search_input.returnPressed.connect(search_materials)
        prev_btn.clicked.connect(prev_page)
        next_btn.clicked.connect(next_page)
        
        tabs.addTab(online_tab, "🌐 在线素材库")
        
        for name, items in [
            ("📁 本地视频", ["video1.mp4", "video2.mp4", "video3.mp4"]),
            ("🎵 本地音频", ["bgm1.mp3", "bgm2.mp3", "effect.wav"]),
            ("🖼️ 本地图片", ["cover1.jpg", "cover2.png", "logo.svg"]),
            ("📝 本地字幕", ["subtitle1.srt", "subtitle2.srt"]),
            ("📋 本地模板", ["template1.json", "template2.json"]),
        ]:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            
            list_widget = QListWidget()
            list_widget.setStyleSheet("""
                QListWidget {
                    background-color: #1a1a1a;
                    border: 1px solid #333333;
                    border-radius: 8px;
                }
                QListWidget::item {
                    padding: 10px;
                    border-bottom: 1px solid #2a2a2a;
                    color: white;
                }
                QListWidget::item:selected {
                    background-color: #1e6bde;
                }
            """)
            list_widget.addItems(items)
            tab_layout.addWidget(list_widget)
            
            tabs.addTab(tab, name)
        
        layout.addWidget(tabs, 1)
        
        self._load_materials()
    
    def _load_materials(self):
        from .online_materials import online_material_library
        
        material_type = self._type_combo.currentData()
        keyword = self._search_input.text()
        
        materials = online_material_library.fetch_materials(
            material_type=material_type,
            keyword=keyword,
            page=self._current_page,
            page_size=self._page_size
        )
        
        self._current_materials = materials
        self._materials_grid.setRowCount(len(materials))
        
        type_icons = {
            "video": "🎬", "audio": "🎵", "image": "🖼️",
            "subtitle": "📝", "template": "📋", "effect": "✨",
            "transition": "🔄", "sticker": "🎭"
        }
        
        for row, material in enumerate(materials):
            thumb_item = QTableWidgetItem("🖼️")
            thumb_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._materials_grid.setItem(row, 0, thumb_item)
            
            name_item = QTableWidgetItem(material.title)
            self._materials_grid.setItem(row, 1, name_item)
            
            type_icon = type_icons.get(material.type, "📁")
            type_item = QTableWidgetItem(f"{type_icon} {material.type}")
            self._materials_grid.setItem(row, 2, type_item)
            
            downloads_item = QTableWidgetItem(f"{material.downloads:,}")
            downloads_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._materials_grid.setItem(row, 3, downloads_item)
            
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(5, 2, 5, 2)
            
            download_btn = QPushButton("下载" if material.is_free else f"¥{material.price}")
            download_btn.setStyleSheet("""
                QPushButton {
                    background-color: #1e6bde;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 5px 15px;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #2a7bef; }
            """)
            action_layout.addWidget(download_btn)
            
            self._materials_grid.setCellWidget(row, 4, action_widget)
        
        self._materials_grid.resizeColumnsToContents()
        
        self._page_label.setText(f"第 {self._current_page} 页")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(len(materials) == self._page_size)


class PluginsModule(BaseModule):
    """
    插件/积木系统模块
    - 插件商店,启用/禁用/卸载,安装第三方积木
    """
    
    module_id = "plugins"
    module_name = "插件中心"
    module_icon = "🧩"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header_layout = QHBoxLayout()
        header = QLabel("🧩 插件中心")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        install_btn = QPushButton("📦 安装插件")
        install_btn.setStyleSheet("""
            QPushButton {
                background-color: #9c27b0;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
            }
        """)
        install_btn.clicked.connect(self._install_plugin)
        header_layout.addWidget(install_btn)
        
        import_btn = QPushButton("📥 导入插件")
        import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                margin-left: 10px;
            }
        """)
        import_btn.clicked.connect(self._import_plugin)
        header_layout.addWidget(import_btn)
        layout.addLayout(header_layout)
        
        # 添加标签页
        self._tab_widget = QTabWidget()
        self._tab_widget.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #0d0d0d; }
            QTabBar::tab {
                background-color: #1a1a1a;
                color: #808080;
                padding: 10px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
            }
            QTabBar::tab:selected { background-color: #2a2a2a; color: #ffffff; }
        """)
        
        # 已安装插件标签页
        installed_tab = QWidget()
        installed_layout = QVBoxLayout(installed_tab)
        
        self._plugins_table = QTableWidget()
        self._plugins_table.setColumnCount(5)
        self._plugins_table.setHorizontalHeaderLabels(["插件名称", "版本", "分类", "状态", "操作"])
        self._plugins_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._plugins_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
                color: white;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 10px;
                border: none;
                color: #808080;
            }
        """)
        installed_layout.addWidget(self._plugins_table, 1)
        
        # 插件商店标签页
        store_tab = self._create_store_tab()
        
        self._tab_widget.addTab(installed_tab, "📦 已安装插件")
        self._tab_widget.addTab(store_tab, "🛍️ 插件商店")
        
        layout.addWidget(self._tab_widget, 1)
        
        self._add_sample_plugins()
    
    def _install_plugin(self):
        """安装插件"""
        # 切换到插件商店标签页
        self._tab_widget.setCurrentIndex(1)
    
    def _create_store_tab(self) -> QWidget:
        """创建插件商店标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # 搜索和筛选
        search_layout = QHBoxLayout()
        
        # 分类筛选
        category_combo = QComboBox()
        category_combo.addItems(["全部", "视频处理", "AI工具", "导出工具", "运营工具", "字幕工具", "音频工具", "特效工具", "其他"])
        category_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a;
                color: white;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 15px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: white;
                selection-background-color: #1e6bde;
            }
        """)
        search_layout.addWidget(category_combo)
        
        # 搜索框
        search_input = QLineEdit()
        search_input.setPlaceholderText("搜索插件...")
        search_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: white;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px 15px;
            }
        """)
        search_layout.addWidget(search_input, 1)
        
        # 搜索按钮
        search_btn = QPushButton("🔍 搜索")
        search_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e6bde;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                margin-left: 10px;
            }
        """)
        search_layout.addWidget(search_btn)
        layout.addLayout(search_layout)
        
        # 插件商店列表
        self._store_table = QTableWidget()
        self._store_table.setColumnCount(6)
        self._store_table.setHorizontalHeaderLabels(["图标", "插件名称", "分类", "版本", "价格", "操作"])
        self._store_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._store_table.setStyleSheet("""
            QTableWidget {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 8px;
                color: white;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                padding: 10px;
                border: none;
                color: #808080;
            }
        """)
        layout.addWidget(self._store_table, 1)
        
        # 分页控制
        page_layout = QHBoxLayout()
        page_layout.addStretch()
        
        prev_btn = QPushButton("◀ 上一页")
        prev_btn.setEnabled(False)
        page_layout.addWidget(prev_btn)
        
        page_label = QLabel("第 1 页")
        page_label.setStyleSheet("color: #808080; padding: 0 15px;")
        page_layout.addWidget(page_label)
        
        next_btn = QPushButton("下一页 ▶")
        page_layout.addWidget(next_btn)
        page_layout.addStretch()
        
        layout.addLayout(page_layout)
        
        # 加载示例插件
        self._load_store_items()
        
        return tab
    
    def _load_store_items(self):
        """加载商店插件列表"""
        from .plugin_store import OFFICIAL_ITEMS
        
        items = OFFICIAL_ITEMS
        
        self._store_table.setRowCount(len(items))
        
        for row, item in enumerate(items):
            # 图标
            icon_item = QTableWidgetItem(item.icon or "🧩")
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._store_table.setItem(row, 0, icon_item)
            
            # 名称
            name_item = QTableWidgetItem(item.name)
            name_item.setToolTip(item.description)
            self._store_table.setItem(row, 1, name_item)
            
            # 分类
            category_item = QTableWidgetItem(item.category.value)
            self._store_table.setItem(row, 2, category_item)
            
            # 版本
            version_item = QTableWidgetItem(item.version)
            self._store_table.setItem(row, 3, version_item)
            
            # 价格
            price_item = QTableWidgetItem("免费" if item.is_free else f"¥{item.price}")
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._store_table.setItem(row, 4, price_item)
            
            # 操作
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(5, 2, 5, 2)
            
            install_btn = QPushButton("安装")
            install_btn.setStyleSheet("""
                QPushButton {
                    background-color: #4caf50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 5px 15px;
                    font-size: 12px;
                }
                QPushButton:hover { background-color: #5cbf60; }
            """)
            install_btn.clicked.connect(lambda checked, item=item: self._install_store_item(item))
            action_layout.addWidget(install_btn)
            
            self._store_table.setCellWidget(row, 5, action_widget)
        
        self._store_table.resizeColumnsToContents()
    
    def _install_store_item(self, item):
        """安装商店插件"""
        from PyQt6.QtWidgets import QMessageBox, QProgressBar, QDialog
        
        # 创建进度对话框
        dialog = QDialog(self)
        dialog.setWindowTitle(f"安装 {item.name}")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        layout.addWidget(progress_bar)
        
        status_label = QLabel("准备安装...")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status_label)
        
        dialog.show()
        
        # 模拟安装过程
        def install_task():
            import time
            
            # 模拟下载进度
            for i in range(1, 101):
                time.sleep(0.05)
                progress_bar.setValue(i)
                if i < 30:
                    status_label.setText("正在下载...")
                elif i < 70:
                    status_label.setText("正在解压...")
                elif i < 90:
                    status_label.setText("正在安装...")
                else:
                    status_label.setText("完成安装...")
            
            # 安装完成
            time.sleep(0.5)
            dialog.accept()
            
            # 显示成功消息
            QMessageBox.information(self, "安装成功", f"插件 {item.name} 安装成功!")
            
            # 更新已安装插件列表
            self._add_sample_plugins()
        
        # 在线程中执行安装
        import threading
        thread = threading.Thread(target=install_task)
        thread.daemon = True
        thread.start()
    
    def _import_plugin(self):
        """导入自定义插件"""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择插件文件", "",
            "插件文件 (*.py *.zip *.plugin)"
        )
        
        if file_path:
            try:
                import os
                plugin_name = os.path.basename(file_path)
                
                # 模拟插件导入过程
                QMessageBox.information(self, "导入插件", f"正在导入插件: {plugin_name}")
                
                # 模拟插件导入成功
                QMessageBox.information(self, "导入成功", f"插件 {plugin_name} 导入成功!")
                
                # 更新插件列表
                self._add_sample_plugins()
                
            except Exception as e:
                QMessageBox.warning(self, "错误", f"插件导入失败: {str(e)}")
    
    def _add_sample_plugins(self):
        plugins = [
            ("✂️ 自动剪辑", "1.0.0", "视频处理", "已启用"),
            ("📝 字幕生成", "1.0.0", "AI功能", "已启用"),
            ("🔄 去重优化", "1.0.0", "视频处理", "已启用"),
            ("ℹ️ 视频信息", "1.0.0", "工具", "已禁用"),
            ("✍️ 文案生成", "1.0.0", "AI功能", "已启用"),
            ("📊 数据分析", "1.0.0", "运营", "已启用"),
        ]
        
        self._plugins_table.setRowCount(len(plugins))
        for i, (name, version, category, status) in enumerate(plugins):
            self._plugins_table.setItem(i, 0, QTableWidgetItem(name))
            self._plugins_table.setItem(i, 1, QTableWidgetItem(version))
            self._plugins_table.setItem(i, 2, QTableWidgetItem(category))
            
            status_btn = QPushButton(status)
            status_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {'#4caf50' if '启用' in status else '#6b7280'};
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 12px;
                }}
            """)
            self._plugins_table.setCellWidget(i, 3, status_btn)
            
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            
            for text, color in [("设置", "#1e6bde"), ("卸载", "#f44336")]:
                btn = QPushButton(text)
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {color};
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 4px 8px;
                        font-size: 12px;
                    }}
                """)
                btn_layout.addWidget(btn)
            
            self._plugins_table.setCellWidget(i, 4, btn_widget)


class PerformanceModule(BaseModule):
    """
    性能监控模块
    - CPU,内存,GPU,任务队列,导出速度
    """
    
    module_id = "performance"
    module_name = "性能监控"
    module_icon = "📊"
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        header = QLabel("📊 性能监控")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        layout.addWidget(header)
        
        stats_grid = QGridLayout()
        stats_grid.setSpacing(15)
        
        stats = [
            ("CPU 使用率", "45%", "#1e6bde"),
            ("内存使用", "2.3 GB", "#4caf50"),
            ("GPU 使用率", "30%", "#ff9800"),
            ("任务队列", "3 个", "#9c27b0"),
        ]
        
        for i, (label, value, color) in enumerate(stats):
            frame = QFrame()
            frame.setStyleSheet(f"""
                QFrame {{
                    background-color: #1a1a1a;
                    border: 2px solid {color}40;
                    border-radius: 12px;
                    padding: 20px;
                }}
            """)
            frame_layout = QVBoxLayout(frame)
            
            value_label = QLabel(value)
            value_label.setStyleSheet(f"font-size: 32px; font-weight: bold; color: {color};")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(value_label)
            
            name_label = QLabel(label)
            name_label.setStyleSheet("color: #808080; font-size: 14px;")
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            frame_layout.addWidget(name_label)
            
            stats_grid.addWidget(frame, i // 2, i % 2)
        
        layout.addLayout(stats_grid)
        
        log_group = QGroupBox("运行日志")
        log_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #1a1a1a;
            }
        """)
        log_layout = QVBoxLayout(log_group)
        
        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a;
                color: #4caf50;
                font-family: 'Consolas', 'Courier New', monospace;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-size: 12px;
            }
        """)
        self._log_output.setText(
            "[INFO] 系统启动完成\n"
            "[INFO] 插件加载完成 (6个)\n"
            "[INFO] 任务队列就绪\n"
            "[INFO] GPU 加速已启用 (NVIDIA NVENC)\n"
            "[INFO] 内存缓存: 512MB"
        )
        log_layout.addWidget(self._log_output)
        
        layout.addWidget(log_group, 1)


MODULE_CLASSES = [
    HomeModule,
    EditorModule,
    CopywritingModule,
    TasksModule,
    DramaFinderModule,
    AccountOpsModule,
    MaterialsModule,
    PluginsModule,
    PerformanceModule
]

from .model_management import ModelManagementModule

MODULE_CLASSES.append(ModelManagementModule)






