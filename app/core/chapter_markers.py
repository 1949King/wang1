"""
章节标记系统 (ChapterMarkers)
================================
对标 Shotcut 的章节标记 (Chapter Markers) 功能。

特性:
- 添加/编辑/删除章节
- 章节树形结构 (子章节)
- 导出 YouTube 章节格式
- 导出 EDL 章节格式
- 缩略图自动抓取
"""
import os
import json
import logging
import subprocess
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("AI短剧编辑器.chapter_markers")


@dataclass
class ChapterMarker:
    """章节标记"""
    id: str
    time: float           # 章节开始时间(秒)
    title: str            # 章节标题
    description: str = "" # 章节描述
    color: str = "#1e6bde"
    # 缩略图
    thumbnail_path: str = ""
    # 层级
    parent_id: str = ""   # 父章节 ID
    order: int = 0
    # 元数据
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "time": self.time,
            "title": self.title,
            "description": self.description,
            "color": self.color,
            "thumbnail_path": self.thumbnail_path,
            "parent_id": self.parent_id,
            "order": self.order,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChapterMarker":
        return cls(**{k: d.get(k, v) for k, v in {
            "id": "", "time": 0.0, "title": "", "description": "",
            "color": "#1e6bde", "thumbnail_path": "", "parent_id": "",
            "order": 0, "created_at": "",
        }.items() if k in d})


class ChapterMarkerManager:
    """
    章节标记管理器
    """

    _instance: Optional["ChapterMarkerManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self._chapters: Dict[str, ChapterMarker] = {}
        self._order_counter = 0

    # ---- CRUD ----

    def add_chapter(self, time: float, title: str, description: str = "",
                    parent_id: str = "") -> ChapterMarker:
        """添加章节"""
        self._order_counter += 1
        chapter = ChapterMarker(
            id=f"chapter_{self._order_counter}_{int(datetime.now().timestamp() * 1000)}",
            time=time,
            title=title,
            description=description,
            parent_id=parent_id,
            order=self._order_counter,
            created_at=datetime.now().isoformat(),
        )
        self._chapters[chapter.id] = chapter
        return chapter

    def update_chapter(self, chapter_id: str, **kwargs) -> bool:
        """更新章节"""
        chapter = self._chapters.get(chapter_id)
        if not chapter:
            return False
        for key, value in kwargs.items():
            if hasattr(chapter, key):
                setattr(chapter, key, value)
        return True

    def delete_chapter(self, chapter_id: str, recursive: bool = True) -> bool:
        """删除章节 (recursive 决定是否删除子章节)"""
        if chapter_id not in self._chapters:
            return False
        del self._chapters[chapter_id]
        if recursive:
            # 删除子章节
            children = [c for c in self._chapters.values() if c.parent_id == chapter_id]
            for child in children:
                self.delete_chapter(child.id, recursive=True)
        return True

    def get_chapter(self, chapter_id: str) -> Optional[ChapterMarker]:
        return self._chapters.get(chapter_id)

    def list_chapters(self, parent_id: str = "") -> List[ChapterMarker]:
        """列出章节 (默认顶层)"""
        chapters = [c for c in self._chapters.values() if c.parent_id == parent_id]
        return sorted(chapters, key=lambda c: c.time)

    def list_all(self) -> List[ChapterMarker]:
        """列出所有章节 (按时间排序)"""
        return sorted(self._chapters.values(), key=lambda c: c.time)

    def clear(self):
        self._chapters.clear()
        self._order_counter = 0

    # ---- 导出 ----

    def export_youtube_chapters(self) -> str:
        """
        导出 YouTube 章节格式

        格式:
            00:00 章节1
            01:23 章节2
            05:00 章节3
        """
        lines = []
        for c in self.list_all():
            ts = self._format_youtube_time(c.time)
            lines.append(f"{ts} {c.title}")
        return "\n".join(lines)

    def _format_youtube_time(self, seconds: float) -> str:
        """格式化为 YouTube 时间码"""
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def export_json(self) -> str:
        """导出为 JSON"""
        return json.dumps(
            [c.to_dict() for c in self.list_all()],
            ensure_ascii=False, indent=2
        )

    def import_json(self, json_str: str) -> int:
        """从 JSON 导入"""
        try:
            data = json.loads(json_str)
            count = 0
            for d in data:
                c = ChapterMarker.from_dict(d)
                self._chapters[c.id] = c
                count += 1
            return count
        except Exception as e:
            logger.error(f"导入章节失败: {e}")
            return 0

    def export_edl(self) -> str:
        """
        导出为 EDL (CMX3600) 章节格式
        """
        lines = ["TITLE: Chapter Markers", "FCM: NON-DROP FRAME"]
        for i, c in enumerate(self.list_all(), 1):
            edit_num = f"{i:03d}"
            tc = self._format_smpte_timecode(c.time)
            lines.append(f"{edit_num}  001 V     C        {tc} {tc}")
            lines.append(f"* {c.title}")
            if c.description:
                lines.append(f"* {c.description}")
        return "\n".join(lines)

    def _format_smpte_timecode(self, seconds: float, fps: int = 30) -> str:
        """SMPTE 时间码 HH:MM:SS:FF"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        f = int((seconds - int(seconds)) * fps)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    # ---- 缩略图 ----

    def auto_thumbnail(self, video_path: str, chapter_id: str,
                        output_dir: str = "") -> bool:
        """从视频中抓取章节时间点的缩略图"""
        chapter = self.get_chapter(chapter_id)
        if not chapter or not os.path.exists(video_path):
            return False
        try:
            from app.core.render_manager import FFmpegTool
            if not output_dir:
                output_dir = os.path.join(os.path.dirname(video_path), ".chapters")
            os.makedirs(output_dir, exist_ok=True)
            thumb_path = os.path.join(output_dir, f"{chapter.id}.jpg")
            cmd = [
                FFmpegTool.find_ffmpeg(),
                "-y", "-ss", str(chapter.time),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                thumb_path
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and os.path.exists(thumb_path):
                chapter.thumbnail_path = thumb_path
                return True
        except Exception as e:
            logger.error(f"抓取缩略图失败: {e}")
        return False


# 全局实例
chapter_marker_manager = ChapterMarkerManager()
