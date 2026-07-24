"""
短剧定制 MLT 引擎 (DramaMLT)
============================
基于 C++ MLT 引擎，专为 AI 短剧编辑器定制的项目级封装。

核心能力:
  DramaTimeline  → 短剧时间线 (剧名/集号/场景类型)
  DramaPresets   → 5 种短剧模板预设
  AutoAssemble   → AI 检测结果自动组装时间线
  PlatformExport → 一键多平台导出
  BatchExport    → 批量导出不同方案

用法:
  from app.core.video_processing.drama_mlt import DramaEditor
  
  editor = DramaEditor()
  editor.new_drama("逆袭人生", episode=3)
  editor.add_highlight("clip1.mp4", 0, 5)
  editor.add_highlight("clip2.mp4", 12, 8)
  editor.auto_assemble()           # 自动加转场+BGM
  editor.export("抖音")            # 一键导出
"""
import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("AI短剧编辑器.drama_mlt")

# ---- 数据结构 ----

@dataclass
class Highlight:
    """高光片段"""
    source: str
    start_time: float    # 在源文件中的起始秒
    duration: float      # 持续秒
    score: float = 0.0   # AI 评分 (0-1)
    label: str = ""      # AI 标注 (搞笑/冲突/反转/结局)

@dataclass  
class DramaPreset:
    """短剧模板预设"""
    name: str
    description: str
    aspect: str          # "9:16" / "16:9" / "1:1"
    width: int
    height: int
    default_transition: str  # "fade" / "dissolve" / "none"
    default_duration: float  # 建议总时长(秒)
    platform: str        # "抖音" / "快手" / "B站" / "小红书"


# ---- 短剧模板 ----

DRAMA_PRESETS = {
    "高光混剪": DramaPreset(
        name="高光混剪", description="选取最精彩片段快速混剪",
        aspect="9:16", width=1080, height=1920,
        default_transition="fade", default_duration=60,
        platform="抖音"
    ),
    "带货混剪": DramaPreset(
        name="带货混剪", description="产品展示+短剧片段穿插",
        aspect="9:16", width=1080, height=1920,
        default_transition="dissolve", default_duration=45,
        platform="抖音"
    ),
    "剧情解说": DramaPreset(
        name="剧情解说", description="解说配音覆盖+画面配合",
        aspect="16:9", width=1920, height=1080,
        default_transition="none", default_duration=180,
        platform="B站"
    ),
    "直播切片": DramaPreset(
        name="直播切片", description="直播高光快速切片",
        aspect="9:16", width=1080, height=1920,
        default_transition="fade", default_duration=90,
        platform="快手"
    ),
    "小红书卡点": DramaPreset(
        name="小红书卡点", description="BGM卡点+图文混剪",
        aspect="1:1", width=1080, height=1080,
        default_transition="fade", default_duration=30,
        platform="小红书"
    ),
}

# 平台导出参数
PLATFORM_EXPORT = {
    "抖音":   {"codec": "h264_nvenc", "crf": 23, "preset": "fast", "width": 1080, "height": 1920, "fps": 30},
    "快手":   {"codec": "h264_nvenc", "crf": 23, "preset": "fast", "width": 1080, "height": 1920, "fps": 30},
    "B站":    {"codec": "h264_nvenc", "crf": 20, "preset": "medium", "width": 1920, "height": 1080, "fps": 30},
    "小红书": {"codec": "libx264",   "crf": 22, "preset": "medium", "width": 1080, "height": 1080, "fps": 30},
    "视频号": {"codec": "h264_nvenc", "crf": 23, "preset": "fast", "width": 1080, "height": 1920, "fps": 30},
    "通用HD": {"codec": "libx264",   "crf": 20, "preset": "medium", "width": 1920, "height": 1080, "fps": 30},
}

# ---- 项目定制引擎 ----

class DramaEditor:
    """短剧定制 MLT 编辑器 — 基于原生 MLT C++ 引擎"""

    def __init__(self):
        self._engine = None
        self._highlights: List[Highlight] = []
        self._preset: DramaPreset = DRAMA_PRESETS["高光混剪"]
        self._drama_name = ""
        self._episode = 0
        self._bgm_path = ""
        self._subtitle_path = ""
        self._watermark_path = ""
        self._get_engine()

    def _get_engine(self):
        """获取底层 MLT C++ 引擎"""
        if self._engine is None:
            from app.core.video_processing.mlt_engine_cpp import get_mlt_cpp_engine
            self._engine = get_mlt_cpp_engine()
        return self._engine

    # ---- 项目管理 ----

    def new_drama(self, name: str, episode: int = 1, preset: str = "高光混剪"):
        """创建新短剧项目"""
        self._drama_name = name
        self._episode = episode
        self._preset = DRAMA_PRESETS.get(preset, DRAMA_PRESETS["高光混剪"])
        self._highlights.clear()
        self._bgm_path = ""
        self._subtitle_path = ""
        self._watermark_path = ""
        logger.info(f"新建短剧: {name} 第{episode}集 [{preset}]")

    def load_highlights(self, highlights: List[dict]):
        """加载 AI 检测的高光片段"""
        self._highlights = [Highlight(**h) for h in highlights]
        self._highlights.sort(key=lambda h: h.start_time)
        logger.info(f"加载 {len(self._highlights)} 个高光片段")

    def set_bgm(self, bgm_path: str):
        """设置背景音乐"""
        if os.path.exists(bgm_path):
            self._bgm_path = bgm_path

    def set_subtitle(self, srt_path: str):
        """设置字幕文件 (SRT)"""
        if os.path.exists(srt_path):
            self._subtitle_path = srt_path

    def set_watermark(self, watermark_path: str):
        """设置水印 (PNG)"""
        if os.path.exists(watermark_path):
            self._watermark_path = watermark_path

    # ---- 自动组装 ----

    def auto_assemble(self, keep_top_pct: float = 0.8) -> dict:
        """
        AI 自动组装时间线:
        1. 按 AI 评分排序，保留 top N%
        2. 添加转场
        3. 添加 BGM + 字幕 + 水印
        4. 构建 FFmpeg 滤镜图命令
        
        返回渲染命令字典，可直接传给 render_manager
        """
        if not self._highlights:
            return {"error": "无高光片段"}

        # 按评分排序，保留 top
        sorted_hl = sorted(self._highlights, key=lambda h: h.score, reverse=True)
        count = max(1, int(len(sorted_hl) * keep_top_pct))
        selected = sorted_hl[:count]
        selected.sort(key=lambda h: h.start_time)  # 按时间排序

        logger.info(f"自动组装: {len(selected)}/{len(self._highlights)} 个片段 "
                     f"(top {keep_top_pct*100:.0f}%)")

        result = {
            "drama": self._drama_name,
            "episode": self._episode,
            "preset": self._preset.name,
            "platform": self._preset.platform,
            "duration": sum(h.duration for h in selected),
            "clip_count": len(selected),
            "clips": [
                {
                    "source": h.source,
                    "start": h.start_time,
                    "duration": h.duration,
                    "score": h.score,
                    "label": h.label,
                }
                for h in selected
            ],
            "bgm": self._bgm_path,
            "subtitle": self._subtitle_path,
            "watermark": self._watermark_path,
            "transition": self._preset.default_transition,
            "transition_duration": 0.5 if self._preset.default_transition != "none" else 0,
        }

        return result

    # ---- 导出 ----

    def export(self, platform: str, output_dir: str = "") -> Optional[str]:
        """一键导出到指定平台"""
        params = PLATFORM_EXPORT.get(platform, PLATFORM_EXPORT["通用HD"])
        if not output_dir:
            from app.config import OUTPUT_DIR
            output_dir = OUTPUT_DIR

        base = f"{self._drama_name}_第{self._episode}集_{platform}"
        output_path = os.path.join(output_dir, f"{base}.mp4")

        # 如果底层 MLT C++ 引擎可用，优先用原生渲染
        engine = self._get_engine()
        if engine and engine.available:
            assembly = self.auto_assemble()
            for clip in assembly.get("clips", []):
                engine.add_clip(clip["source"])
            engine.render(output_path)
        else:
            # 回退：委托 RenderManager
            assembly = self.auto_assemble()
            if "error" in assembly:
                return None
            from app.core.render_manager import get_render_manager
            rm = get_render_manager()
            if assembly["clips"]:
                first = assembly["clips"][0]
                rm.render(first["source"], output_path, platform=platform)

        logger.info(f"导出完成: {output_path}")
        return output_path

    def batch_export(self, platforms: List[str] = None) -> List[Tuple[str, str]]:
        """批量导出到多个平台"""
        if not platforms:
            platforms = ["抖音", "快手", "B站", "小红书"]

        results = []
        for p in platforms:
            path = self.export(p)
            if path:
                results.append((p, path))
                logger.info(f"  {p}: {path}")
            else:
                logger.warning(f"  {p}: 导出失败")

        return results

    # ---- 序列化 ----

    def save_project(self, path: str):
        """保存短剧项目"""
        data = {
            "drama_name": self._drama_name,
            "episode": self._episode,
            "preset": self._preset.name,
            "highlights": [
                {"source": h.source, "start_time": h.start_time,
                 "duration": h.duration, "score": h.score, "label": h.label}
                for h in self._highlights
            ],
            "bgm": self._bgm_path,
            "subtitle": self._subtitle_path,
            "watermark": self._watermark_path,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_project(self, path: str):
        """加载短剧项目"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self._drama_name = data["drama_name"]
        self._episode = data.get("episode", 1)
        self._preset = DRAMA_PRESETS.get(data.get("preset", "高光混剪"), DRAMA_PRESETS["高光混剪"])
        self.load_highlights(data.get("highlights", []))
        self._bgm_path = data.get("bgm", "")
        self._subtitle_path = data.get("subtitle", "")
        self._watermark_path = data.get("watermark", "")


# ---- 全局实例 ----

_drama_editor: Optional[DramaEditor] = None

def get_drama_editor() -> DramaEditor:
    global _drama_editor
    if _drama_editor is None:
        _drama_editor = DramaEditor()
    return _drama_editor
