"""
自动字幕生成引擎
提供语音转字幕（Whisper集成）、字幕样式统一、错别字纠错、批量样式应用
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime
import json


class SubtitleFormat(Enum):
    """字幕格式"""
    SRT = "srt"
    ASS = "ass"
    VTT = "vtt"
    TXT = "txt"


class SubtitleStyle(Enum):
    """字幕样式"""
    CLASSIC = "classic"
    MODERN = "modern"
    ELEGANT = "elegant"
    PLAYFUL = "playful"
    CUSTOM = "custom"


class SubtitlePosition(Enum):
    """字幕位置"""
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    TOP_CENTER = "top_center"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"


@dataclass
class SubtitleSegment:
    """字幕片段"""
    id: str
    start_time: float
    end_time: float
    text: str
    confidence: float
    speaker: Optional[str] = None
    language: str = "zh"
    style: SubtitleStyle = SubtitleStyle.CLASSIC
    position: SubtitlePosition = SubtitlePosition.BOTTOM_CENTER
    
    @property
    def duration(self) -> float:
        """片段时长"""
        return self.end_time - self.start_time
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "text": self.text,
            "confidence": self.confidence,
            "speaker": self.speaker,
            "language": self.language,
            "style": self.style.value,
            "position": self.position.value
        }


@dataclass
class SubtitleStyleConfig:
    """字幕样式配置"""
    font_name: str = "Microsoft YaHei"
    font_size: int = 24
    font_color: str = "#FFFFFF"
    background_color: str = "#000000"
    background_opacity: float = 0.7
    border_color: str = "#000000"
    border_width: int = 2
    shadow_color: str = "#000000"
    shadow_offset: int = 2
    line_spacing: float = 1.2
    alignment: str = "center"
    
    def to_dict(self) -> Dict:
        return {
            "font_name": self.font_name,
            "font_size": self.font_size,
            "font_color": self.font_color,
            "background_color": self.background_color,
            "background_opacity": self.background_opacity,
            "border_color": self.border_color,
            "border_width": self.border_width,
            "shadow_color": self.shadow_color,
            "shadow_offset": self.shadow_offset,
            "line_spacing": self.line_spacing,
            "alignment": self.alignment
        }


@dataclass
class TypoCorrection:
    """错别字纠错"""
    original_text: str
    corrected_text: str
    confidence: float
    corrections: List[Dict[str, Any]] = field(default_factory=list)


class WhisperTranscriber:
    """Whisper语音转写器 — 统一走 app.core.ai.whisper_asr"""
    
    def __init__(self, model_size: str = "base"):
        self._model_size = model_size
        self._lock = RLock()
        self._model = True  # 占位：可用性由 whisper_asr 判定
    
    def _load_model(self):
        """兼容旧调用；实际加载在 whisper_asr._load_model。"""
        return None
    
    def transcribe_audio(self, audio_path: str,
                        language: str = "zh",
                        progress_callback: Optional[callable] = None) -> List[SubtitleSegment]:
        """转写音频为真实字幕片段（无模型时返回空，不再生成假文案）。"""
        if progress_callback:
            progress_callback(0, "开始语音转写...")
        
        with self._lock:
            try:
                from app.core.ai.whisper_asr import is_available, transcribe, get_backend
            except Exception:
                try:
                    from core.ai.whisper_asr import is_available, transcribe, get_backend
                except Exception as e:
                    print(f"whisper_asr 不可用: {e}")
                    if progress_callback:
                        progress_callback(100, "语音识别模块不可用")
                    return []

            if not is_available():
                print("Whisper 未安装（请 pip install faster-whisper）")
                if progress_callback:
                    progress_callback(100, "未安装 Whisper")
                return []

            try:
                if progress_callback:
                    progress_callback(15, f"加载模型 ({get_backend()}/{self._model_size})...")
                raw = transcribe(
                    audio_path,
                    model_size=self._model_size,
                    language=language or "zh",
                )
                if progress_callback:
                    progress_callback(80, "整理字幕片段...")
                segments: List[SubtitleSegment] = []
                for i, seg in enumerate(raw or []):
                    text = (seg.get("text") or "").strip()
                    if not text:
                        continue
                    segments.append(SubtitleSegment(
                        id=f"seg_{i}",
                        start_time=float(seg.get("start", 0) or 0),
                        end_time=float(seg.get("end", 0) or 0),
                        text=text,
                        confidence=float(seg.get("avg_logprob", 0.0) or 0.0),
                        language=language or "zh",
                    ))
                if progress_callback:
                    progress_callback(100, f"转写完成 ({len(segments)} 条)")
                return segments
            except Exception as e:
                print(f"语音转写失败: {e}")
                if progress_callback:
                    progress_callback(100, f"转写失败: {e}")
                return []
    
    def _simulate_transcription(self, audio_path: str,
                           progress_callback: Optional[callable] = None) -> List[SubtitleSegment]:
        """已废弃：禁止输出与画面无关的假字幕。"""
        if progress_callback:
            progress_callback(100, "模拟转写已禁用")
        return []


class TypoCorrector:
    """错别字纠错器"""
    
    def __init__(self):
        # 默认不自动替换常用字（的/得/在/再…），避免把正确对白改坏。
        # 仅保留明确同音错词时可由 add_correction 追加。
        self._corrections: Dict[str, str] = {}
        self._lock = RLock()
    
    def correct_text(self, text: str,
                   confidence: float = 0.8) -> TypoCorrection:
        """纠错文本"""
        with self._lock:
            corrections = []
            corrected_text = text
            
            for wrong, right in self._corrections.items():
                if wrong in corrected_text and confidence > 0.7:
                    corrected_text = corrected_text.replace(wrong, right)
                    corrections.append({
                        "original": wrong,
                        "corrected": right,
                        "position": text.find(wrong)
                    })
            
            correction = TypoCorrection(
                original_text=text,
                corrected_text=corrected_text,
                confidence=confidence,
                corrections=corrections
            )
            
            return correction
    
    def add_correction(self, wrong: str, right: str):
        """添加纠错规则"""
        with self._lock:
            self._corrections[wrong] = right
    
    def remove_correction(self, wrong: str):
        """移除纠错规则"""
        with self._lock:
            if wrong in self._corrections:
                del self._corrections[wrong]


class SubtitleStyler:
    """字幕样式器"""
    
    def __init__(self):
        self._styles: Dict[SubtitleStyle, SubtitleStyleConfig] = {}
        self._lock = RLock()
        self._initialize_default_styles()
    
    def _initialize_default_styles(self):
        """初始化默认样式"""
        self._styles = {
            SubtitleStyle.CLASSIC: SubtitleStyleConfig(
                font_name="Microsoft YaHei",
                font_size=24,
                font_color="#FFFFFF",
                background_color="#000000",
                background_opacity=0.7,
                border_color="#000000",
                border_width=2,
                shadow_color="#000000",
                shadow_offset=2
            ),
            SubtitleStyle.MODERN: SubtitleStyleConfig(
                font_name="Arial",
                font_size=28,
                font_color="#00FFFF",
                background_color="#000033",
                background_opacity=0.8,
                border_color="#00FFFF",
                border_width=3,
                shadow_color="#000000",
                shadow_offset=3
            ),
            SubtitleStyle.ELEGANT: SubtitleStyleConfig(
                font_name="Times New Roman",
                font_size=22,
                font_color="#FFD700",
                background_color="#000000",
                background_opacity=0.6,
                border_color="#FFD700",
                border_width=1,
                shadow_color="#000000",
                shadow_offset=1
            ),
            SubtitleStyle.PLAYFUL: SubtitleStyleConfig(
                font_name="Comic Sans MS",
                font_size=26,
                font_color="#FF69B4",
                background_color="#FF1493",
                background_opacity=0.75,
                border_color="#FFFFFF",
                border_width=2,
                shadow_color="#000000",
                shadow_offset=2
            )
        }
    
    def apply_style(self, segments: List[SubtitleSegment],
                  style: SubtitleStyle) -> List[SubtitleSegment]:
        """应用样式到字幕"""
        style_config = self._styles.get(style)
        if not style_config:
            style_config = self._styles[SubtitleStyle.CLASSIC]
        
        with self._lock:
            styled_segments = []
            for segment in segments:
                styled_segment = SubtitleSegment(
                    id=segment.id,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    text=segment.text,
                    confidence=segment.confidence,
                    speaker=segment.speaker,
                    language=segment.language,
                    style=style,
                    position=segment.position
                )
                styled_segments.append(styled_segment)
            
            return styled_segments
    
    def get_style_config(self, style: SubtitleStyle) -> Optional[SubtitleStyleConfig]:
        """获取样式配置"""
        return self._styles.get(style)
    
    def set_style_config(self, style: SubtitleStyle, config: SubtitleStyleConfig):
        """设置样式配置"""
        with self._lock:
            self._styles[style] = config
    
    def get_available_styles(self) -> List[SubtitleStyle]:
        """获取可用样式"""
        return list(self._styles.keys())


class SubtitleGenerator:
    """字幕生成器（整合所有字幕功能）"""
    
    def __init__(self, model_size: str = "base"):
        self._transcriber = WhisperTranscriber(model_size)
        self._typo_corrector = TypoCorrector()
        self._styler = SubtitleStyler()
        self._segments: List[SubtitleSegment] = []
        self._lock = RLock()
    
    def generate_subtitles(self, audio_path: str,
                        language: str = "zh",
                        correct_typos: bool = False,
                        apply_style: Optional[SubtitleStyle] = None,
                        progress_callback: Optional[callable] = None) -> List[SubtitleSegment]:
        """生成字幕"""
        if progress_callback:
            progress_callback(0, "开始生成字幕...")
        
        with self._lock:
            try:
                # 步骤1: 语音转写
                if progress_callback:
                    progress_callback(10, "语音转写中...")
                
                segments = self._transcriber.transcribe_audio(audio_path, language, progress_callback)
                
                if not segments:
                    return []
                
                # 步骤2: 错别字纠错
                if correct_typos:
                    if progress_callback:
                        progress_callback(70, "纠错中...")
                    
                    corrected_segments = []
                    for segment in segments:
                        correction = self._typo_corrector.correct_text(segment.text, segment.confidence)
                        if correction.corrected_text != correction.original_text:
                            segment.text = correction.corrected_text
                        corrected_segments.append(segment)
                    
                    segments = corrected_segments
                
                # 步骤3: 应用样式
                if apply_style:
                    if progress_callback:
                        progress_callback(85, "应用样式...")
                    
                    segments = self._styler.apply_style(segments, apply_style)
                
                self._segments = segments
                
                if progress_callback:
                    progress_callback(100, "字幕生成完成")
                
                return segments
                
            except Exception as e:
                print(f"生成字幕失败: {e}")
                return []
    
    def export_subtitles(self, segments: List[SubtitleSegment],
                       format: SubtitleFormat = SubtitleFormat.SRT,
                       file_path: Optional[str] = None) -> str:
        """导出字幕"""
        content = ""
        
        if format == SubtitleFormat.SRT:
            content = self._export_srt(segments)
        elif format == SubtitleFormat.ASS:
            content = self._export_ass(segments)
        elif format == SubtitleFormat.VTT:
            content = self._export_vtt(segments)
        elif format == SubtitleFormat.TXT:
            content = self._export_txt(segments)
        
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return file_path
        
        return content
    
    def _export_srt(self, segments: List[SubtitleSegment]) -> str:
        """导出SRT格式"""
        srt_content = ""
        
        for i, segment in enumerate(segments, 1):
            start_time = self._format_srt_time(segment.start_time)
            end_time = self._format_srt_time(segment.end_time)
            
            srt_content += f"{i}\n"
            srt_content += f"{start_time} --> {end_time}\n"
            srt_content += f"{segment.text}\n\n"
        
        return srt_content
    
    def _export_ass(self, segments: List[SubtitleSegment]) -> str:
        """导出ASS格式"""
        ass_content = "[Script Info]\n"
        ass_content += "ScriptType: v4.00+\n"
        ass_content += "PlayResX: 1920\n"
        ass_content += "PlayResY: 1080\n\n"
        
        ass_content += "[V4+ Styles]\n"
        ass_content += "Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, OutlineColour, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, BorderStyle\n"
        ass_content += "Style: Default,Arial,24,&H00FFFFFF,&H000000,&H000000,2,2,2,10,10,10,1\n\n"
        
        ass_content += "[Events]\n"
        ass_content += "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        
        for segment in segments:
            start_time = self._format_ass_time(segment.start_time)
            end_time = self._format_ass_time(segment.end_time)
            
            ass_content += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{segment.text}\n"
        
        return ass_content
    
    def _export_vtt(self, segments: List[SubtitleSegment]) -> str:
        """导出VTT格式"""
        vtt_content = "WEBVTT\n\n"
        
        for segment in segments:
            start_time = self._format_vtt_time(segment.start_time)
            end_time = self._format_vtt_time(segment.end_time)
            
            vtt_content += f"{start_time} --> {end_time}\n"
            vtt_content += f"{segment.text}\n\n"
        
        return vtt_content
    
    def _export_txt(self, segments: List[SubtitleSegment]) -> str:
        """导出TXT格式"""
        txt_content = ""
        
        for segment in segments:
            txt_content += f"[{segment.start_time:.2f} - {segment.end_time:.2f}]\n"
            txt_content += f"{segment.text}\n\n"
        
        return txt_content
    
    def _format_srt_time(self, seconds: float) -> str:
        """格式化SRT时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"
    
    def _format_ass_time(self, seconds: float) -> str:
        """格式化ASS时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        
        return f"{hours}:{minutes}:{secs}.{centisecs:02d}"
    
    def _format_vtt_time(self, seconds: float) -> str:
        """格式化VTT时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millisecs:03d}"
    
    def get_segments(self) -> List[SubtitleSegment]:
        """获取字幕片段"""
        return self._segments.copy()
    
    def clear_subtitles(self):
        """清除字幕"""
        with self._lock:
            self._segments.clear()
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        if not self._segments:
            return {}
        
        total_duration = sum(s.duration for s in self._segments)
        avg_confidence = np.mean([s.confidence for s in self._segments])
        
        return {
            "total_segments": len(self._segments),
            "total_duration": total_duration,
            "average_duration": total_duration / len(self._segments),
            "average_confidence": float(avg_confidence),
            "languages": list(set(s.language for s in self._segments)),
            "speakers": list(set(s.speaker for s in self._segments if s.speaker))
        }
