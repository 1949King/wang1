"""
视频特效和编辑增强模块
========================
包含转场、调色、字幕、音频处理等功能
"""

import os
import logging
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import numpy as np
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip, 
    concatenate_videoclips, afx, vfx, TextClip, ColorClip
)
from moviepy.video.fx.all import fadein, fadeout, crossfadein

logger = logging.getLogger("AI短剧编辑器.video_effects")


class TransitionType(Enum):
    """转场类型"""
    FADE = "淡入淡出"
    CROSSFADE = "交叉淡化"
    SLIDE_LEFT = "向左滑动"
    SLIDE_RIGHT = "向右滑动"
    SLIDE_UP = "向上滑动"
    SLIDE_DOWN = "向下滑动"
    WIPE = "擦除"
    ZOOM_IN = "放大"
    ZOOM_OUT = "缩小"


@dataclass
class ColorAdjustment:
    """调色参数"""
    brightness: float = 1.0  # 亮度 (0.0 - 2.0)
    contrast: float = 1.0    # 对比度 (0.0 - 2.0)
    saturation: float = 1.0  # 饱和度 (0.0 - 2.0)
    gamma: float = 1.0       # 伽马值 (0.1 - 3.0)
    hue: float = 0.0         # 色调偏移 (-180 - 180)


@dataclass
class SubtitleStyle:
    """字幕样式"""
    font: str = "Arial"
    fontsize: int = 24
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    position: Tuple[str, str] = ("center", "bottom")  # (horizontal, vertical)
    bg_color: Optional[str] = None
    bg_opacity: float = 0.5


class VideoEffects:
    """视频特效处理器"""
    
    @staticmethod
    def apply_transition(clip1: VideoFileClip, clip2: VideoFileClip, 
                        transition_type: TransitionType, duration: float = 1.0) -> VideoFileClip:
        """
        应用转场效果
        
        Args:
            clip1: 第一个视频片段
            clip2: 第二个视频片段
            transition_type: 转场类型
            duration: 转场持续时间（秒）
        
        Returns:
            合并后的视频片段
        """
        try:
            if transition_type == TransitionType.FADE:
                # 淡入淡出
                clip1 = fadeout(clip1, duration)
                clip2 = fadein(clip2, duration)
                return concatenate_videoclips([clip1, clip2])
            
            elif transition_type == TransitionType.CROSSFADE:
                # 交叉淡化
                clip2 = crossfadein(clip2, duration)
                return concatenate_videoclips([clip1, clip2], method="compose")
            
            elif transition_type == TransitionType.SLIDE_LEFT:
                # 向左滑动
                w, h = clip1.size
                clip2 = clip2.set_position(lambda t: (w * (1 - t/duration), 0))
                return CompositeVideoClip([clip1, clip2.set_start(clip1.duration - duration)])
            
            elif transition_type == TransitionType.ZOOM_IN:
                # 放大效果
                clip2 = clip2.fx(vfx.resize, lambda t: 1 + 0.2 * (1 - t/duration) if t < duration else 1)
                return concatenate_videoclips([clip1, clip2])
            
            else:
                # 默认直接拼接
                return concatenate_videoclips([clip1, clip2])
                
        except Exception as e:
            logger.error(f"应用转场效果失败: {e}")
            return concatenate_videoclips([clip1, clip2])
    
    @staticmethod
    def apply_color_adjustment(clip: VideoFileClip, 
                              adjustment: ColorAdjustment) -> VideoFileClip:
        """
        应用调色效果
        
        Args:
            clip: 视频片段
            adjustment: 调色参数
        
        Returns:
            调色后的视频片段
        """
        try:
            # 亮度调整
            if adjustment.brightness != 1.0:
                clip = clip.fx(vfx.colorx, adjustment.brightness)
            
            # 对比度调整
            if adjustment.contrast != 1.0:
                clip = clip.fx(vfx.lum_contrast, 
                             lum=0, contrast=adjustment.contrast - 1.0)
            
            # 饱和度调整
            if adjustment.saturation != 1.0:
                clip = clip.fx(vfx.saturation, adjustment.saturation)
            
            # 伽马调整
            if adjustment.gamma != 1.0:
                clip = clip.fx(vfx.gamma_corr, adjustment.gamma)
            
            return clip
            
        except Exception as e:
            logger.error(f"应用调色效果失败: {e}")
            return clip
    
    @staticmethod
    def add_subtitle(clip: VideoFileClip, text: str, 
                    start_time: float, duration: float,
                    style: SubtitleStyle = None) -> VideoFileClip:
        """
        添加字幕
        
        Args:
            clip: 视频片段
            text: 字幕文本
            start_time: 开始时间（秒）
            duration: 持续时间（秒）
            style: 字幕样式
        
        Returns:
            添加字幕后的视频片段
        """
        if style is None:
            style = SubtitleStyle()
        
        try:
            # 创建字幕剪辑
            txt_clip = TextClip(
                text,
                fontsize=style.fontsize,
                color=style.color,
                stroke_color=style.stroke_color,
                stroke_width=style.stroke_width,
                font=style.font,
                method='caption',
                size=(clip.w * 0.9, None)
            )
            
            # 设置字幕位置和持续时间
            txt_clip = txt_clip.set_start(start_time).set_duration(duration)
            
            # 计算位置
            x_pos = style.position[0]
            y_pos = style.position[1]
            
            if x_pos == "center":
                x_pos = "center"
            elif x_pos == "left":
                x_pos = 20
            elif x_pos == "right":
                x_pos = clip.w - txt_clip.w - 20
            
            if y_pos == "bottom":
                y_pos = clip.h - txt_clip.h - 50
            elif y_pos == "top":
                y_pos = 50
            elif y_pos == "center":
                y_pos = "center"
            
            txt_clip = txt_clip.set_position((x_pos, y_pos))
            
            # 添加背景
            if style.bg_color:
                bg_clip = ColorClip(
                    size=(txt_clip.w + 20, txt_clip.h + 10),
                    color=style.bg_color
                ).set_opacity(style.bg_opacity)
                bg_clip = bg_clip.set_start(start_time).set_duration(duration)
                bg_clip = bg_clip.set_position((x_pos, y_pos))
                return CompositeVideoClip([clip, bg_clip, txt_clip])
            
            return CompositeVideoClip([clip, txt_clip])
            
        except Exception as e:
            logger.error(f"添加字幕失败: {e}")
            return clip
    
    @staticmethod
    def add_audio_effects(audio_clip: AudioFileClip, 
                         volume: float = 1.0,
                         fade_in: float = 0.0,
                         fade_out: float = 0.0) -> AudioFileClip:
        """
        添加音频效果
        
        Args:
            audio_clip: 音频片段
            volume: 音量倍数
            fade_in: 淡入时间（秒）
            fade_out: 淡出时间（秒）
        
        Returns:
            处理后的音频片段
        """
        try:
            # 调整音量
            if volume != 1.0:
                audio_clip = audio_clip.volumex(volume)
            
            # 淡入效果
            if fade_in > 0:
                audio_clip = audio_clip.fx(afx.audio_fadein, fade_in)
            
            # 淡出效果
            if fade_out > 0:
                audio_clip = audio_clip.fx(afx.audio_fadeout, fade_out)
            
            return audio_clip
            
        except Exception as e:
            logger.error(f"添加音频效果失败: {e}")
            return audio_clip
    
    @staticmethod
    def add_watermark(clip: VideoFileClip, watermark_path: str,
                     position: Tuple[str, str] = ("right", "bottom"),
                     opacity: float = 0.5,
                     scale: float = 0.1) -> VideoFileClip:
        """
        添加水印
        
        Args:
            clip: 视频片段
            watermark_path: 水印图片路径
            position: 水印位置
            opacity: 透明度
            scale: 缩放比例
        
        Returns:
            添加水印后的视频片段
        """
        try:
            from moviepy.editor import ImageClip
            
            # 加载水印
            watermark = ImageClip(watermark_path)
            
            # 调整大小
            watermark = watermark.resize(scale)
            
            # 设置透明度
            watermark = watermark.set_opacity(opacity)
            
            # 设置位置
            x_pos, y_pos = position
            if x_pos == "right":
                x_pos = clip.w - watermark.w - 20
            elif x_pos == "left":
                x_pos = 20
            elif x_pos == "center":
                x_pos = "center"
            
            if y_pos == "bottom":
                y_pos = clip.h - watermark.h - 20
            elif y_pos == "top":
                y_pos = 20
            elif y_pos == "center":
                y_pos = "center"
            
            watermark = watermark.set_position((x_pos, y_pos))
            watermark = watermark.set_duration(clip.duration)
            
            return CompositeVideoClip([clip, watermark])
            
        except Exception as e:
            logger.error(f"添加水印失败: {e}")
            return clip
    
    @staticmethod
    def create_title_card(text: str, duration: float = 3.0,
                         size: Tuple[int, int] = (1920, 1080),
                         bg_color: str = "black",
                         text_color: str = "white") -> VideoFileClip:
        """
        创建片头/片尾卡片
        
        Args:
            text: 标题文本
            duration: 持续时间（秒）
            size: 视频尺寸
            bg_color: 背景颜色
            text_color: 文字颜色
        
        Returns:
            标题卡片视频片段
        """
        try:
            # 创建背景
            bg_clip = ColorClip(size=size, color=bg_color).set_duration(duration)
            
            # 创建文字
            txt_clip = TextClip(
                text,
                fontsize=60,
                color=text_color,
                font="Arial",
                stroke_color="black",
                stroke_width=2
            ).set_duration(duration)
            
            txt_clip = txt_clip.set_position("center")
            
            # 添加淡入淡出效果
            txt_clip = fadein(txt_clip, 0.5)
            txt_clip = fadeout(txt_clip, 0.5)
            
            return CompositeVideoClip([bg_clip, txt_clip])
            
        except Exception as e:
            logger.error(f"创建标题卡片失败: {e}")
            return ColorClip(size=size, color=bg_color).set_duration(duration)
    
    @staticmethod
    def speed_adjustment(clip: VideoFileClip, speed: float = 1.0) -> VideoFileClip:
        """
        调整视频速度
        
        Args:
            clip: 视频片段
            speed: 速度倍数 (>1加速, <1减速)
        
        Returns:
            调整速度后的视频片段
        """
        try:
            return clip.fx(vfx.speedx, speed)
        except Exception as e:
            logger.error(f"调整视频速度失败: {e}")
            return clip
    
    @staticmethod
    def reverse_clip(clip: VideoFileClip) -> VideoFileClip:
        """
        倒放视频
        
        Args:
            clip: 视频片段
        
        Returns:
            倒放后的视频片段
        """
        try:
            return clip.fx(vfx.time_mirror)
        except Exception as e:
            logger.error(f"倒放视频失败: {e}")
            return clip
    
    @staticmethod
    def resize_clip(clip: VideoFileClip, width: Optional[int] = None,
                   height: Optional[int] = None,
                   aspect_ratio: Optional[float] = None) -> VideoFileClip:
        """
        调整视频尺寸
        
        Args:
            clip: 视频片段
            width: 目标宽度
            height: 目标高度
            aspect_ratio: 目标宽高比
        
        Returns:
            调整尺寸后的视频片段
        """
        try:
            if aspect_ratio:
                # 保持宽高比
                current_ratio = clip.w / clip.h
                if aspect_ratio > current_ratio:
                    # 需要增加宽度
                    new_width = int(clip.h * aspect_ratio)
                    new_height = clip.h
                else:
                    # 需要增加高度
                    new_width = clip.w
                    new_height = int(clip.w / aspect_ratio)
                
                clip = clip.resize((new_width, new_height))
            
            elif width and height:
                clip = clip.resize((width, height))
            
            elif width:
                clip = clip.resize(width=width)
            
            elif height:
                clip = clip.resize(height=height)
            
            return clip
            
        except Exception as e:
            logger.error(f"调整视频尺寸失败: {e}")
            return clip


class BatchVideoProcessor:
    """批量视频处理器"""
    
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        from concurrent.futures import ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    def batch_add_subtitles(self, video_path: str, subtitles: List[Dict[str, Any]],
                           output_path: str, style: SubtitleStyle = None):
        """
        批量添加字幕
        
        Args:
            video_path: 输入视频路径
            subtitles: 字幕列表，每个字幕包含text, start_time, duration
            output_path: 输出视频路径
            style: 字幕样式
        """
        try:
            with VideoFileClip(video_path) as clip:
                # 添加所有字幕
                for sub in subtitles:
                    clip = VideoEffects.add_subtitle(
                        clip,
                        sub['text'],
                        sub['start_time'],
                        sub['duration'],
                        style or SubtitleStyle()
                    )
                
                # 导出视频
                clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
            
            logger.info(f"批量添加字幕完成: {output_path}")
            
        except Exception as e:
            logger.error(f"批量添加字幕失败: {e}")
    
    def batch_apply_effects(self, video_paths: List[str], 
                           effect_func, output_dir: str, **kwargs):
        """
        批量应用效果
        
        Args:
            video_paths: 输入视频路径列表
            effect_func: 效果处理函数
            output_dir: 输出目录
            **kwargs: 传递给效果函数的参数
        """
        def process_single(video_path):
            try:
                filename = os.path.basename(video_path)
                output_path = os.path.join(output_dir, f"processed_{filename}")
                
                with VideoFileClip(video_path) as clip:
                    processed_clip = effect_func(clip, **kwargs)
                    processed_clip.write_videofile(output_path, codec='libx264', audio_codec='aac')
                
                return True, output_path, ""
                
            except Exception as e:
                logger.error(f"处理视频失败 {video_path}: {e}")
                return False, None, str(e)
        
        # 提交所有任务
        futures = [self.executor.submit(process_single, path) for path in video_paths]
        
        # 收集结果
        results = []
        for future in futures:
            results.append(future.result())
        
        return results
    
    def shutdown(self):
        """关闭处理器"""
        self.executor.shutdown(wait=True)
