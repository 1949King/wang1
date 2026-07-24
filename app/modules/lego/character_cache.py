"""
视频级分析缓存（Video-level Analysis Cache）
===========================================

目标：让同一视频的剧情理解结果可复用，避免每次都跑 Whisper + LLM。

缓存键：
    视频路径的 MD5 + 文件大小 + 修改时间 = 稳定哈希键

缓存内容：
    1. DramaStructure 全量数据（角色、情节点、场景、主题等）
    2. 用户角色偏好（"优先保留" / "忽略"）
    3. 元信息（缓存时间、源文件路径、视频时长）

使用方式：
    from .character_cache import AnalysisCache
    cache = AnalysisCache()

    # 读取
    drama = cache.get_drama(video_path)  # 命中返回 DramaStructure，否则 None

    # 写入
    cache.put_drama(video_path, drama)

    # 角色偏好（用户勾选后写回）
    cache.set_character_pref(video_path, "林总", keep=True, weight=1.3)
    prefs = cache.get_character_prefs(video_path)

缓存目录：
    Windows: C:\\Users\\<user>\\.video_editor_cache\\analysis\\
    macOS/Linux: ~/.video_editor_cache/analysis/
"""

import os
import json
import hashlib
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
import numpy as np

# DramaStructure 和相关类型（延迟导入以避免循环）


def _cache_root_dir() -> str:
    """返回缓存根目录"""
    home = os.path.expanduser("~")
    return os.path.join(home, ".video_editor_cache", "analysis")


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _file_fingerprint(path: str) -> Tuple[str, int, float]:
    """
    生成视频文件的稳定指纹：(文件大小, 修改时间)
    用于判断文件是否被修改过。
    """
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime)


def _cache_key(video_path: str) -> str:
    """
    根据视频路径生成缓存键（相对路径的 hash，便于不同机器/路径迁移）。
    缓存文件内还会记录文件指纹做二次校验。
    """
    normalized = os.path.normpath(os.path.abspath(video_path))
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _cache_file_path(video_path: str) -> str:
    root = _cache_root_dir()
    _ensure_dir(root)
    return os.path.join(root, f"{_cache_key(video_path)}.json")


@dataclass
class CharacterPreference:
    """用户对单个角色的剪辑偏好"""
    name: str
    keep: bool = True       # True = 优先保留，False = 忽略
    weight: float = 1.0     # 权重乘数（1.0 = 不调整，>1 = 提升，<1 = 降低）
    note: str = ""           # 用户可备注，比如"男主高光"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "keep": self.keep,
            "weight": self.weight,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CharacterPreference":
        return cls(
            name=str(d.get("name", "")),
            keep=bool(d.get("keep", True)),
            weight=float(d.get("weight", 1.0)),
            note=str(d.get("note", "")),
        )


class AnalysisCache:
    """
    视频级分析缓存。

    设计原则：
    1. 仅做"命中即返回，未命中则返回 None"——上层决定是否重新分析
    2. 所有写入都原子化（先写 .tmp 文件再 rename），避免中途退出产生损坏的缓存
    3. 提供角色偏好的独立读写，用户可以在未重新分析的情况下调整偏好
    """

    SCHEMA_VERSION = 1

    def __init__(self):
        _ensure_dir(_cache_root_dir())

    # ─── 基础：读取/写入 DramaStructure ────────────────

    def has(self, video_path: str) -> bool:
        """是否存在此视频的有效缓存"""
        return self._read_cache(video_path, validate_fingerprint=True) is not None

    def get_drama(self, video_path: str):
        """
        读取缓存中的 DramaStructure。如果文件不存在或指纹不符，返回 None。
        """
        entry = self._read_cache(video_path, validate_fingerprint=True)
        if entry is None:
            return None
        return self._drama_from_dict(entry["drama"])

    def put_drama(self, video_path: str, drama) -> str:
        """
        写入 DramaStructure 到缓存。返回缓存文件路径。
        """
        fingerprint = _file_fingerprint(video_path)
        entry = {
            "schema_version": self.SCHEMA_VERSION,
            "video_path": os.path.abspath(video_path),
            "file_size": fingerprint[0],
            "file_mtime": fingerprint[1],
            "cached_at": datetime.now().isoformat(),
            "drama": self._drama_to_dict(drama),
            "character_prefs": {},  # 独立更新，见 set_character_pref
        }
        path = _cache_file_path(video_path)
        self._atomic_write(path, entry)
        return path

    # ─── 角色偏好 ────────────────────────────

    def get_character_prefs(self, video_path: str) -> Dict[str, CharacterPreference]:
        """
        读取该视频的角色偏好。如果该视频无缓存，返回空 dict。
        """
        entry = self._read_cache(video_path, validate_fingerprint=False)
        if entry is None:
            return {}
        prefs_raw = entry.get("character_prefs", {})
        return {name: CharacterPreference.from_dict(p) for name, p in prefs_raw.items()}

    def set_character_pref(self, video_path: str,
                           character_name: str,
                           keep: bool = True,
                           weight: float = 1.0,
                           note: str = "") -> bool:
        """
        设置某角色的偏好。写入成功返回 True。
        若该视频尚无分析缓存，则先创建一个"空缓存壳"，仅保存偏好。
        """
        entry = self._read_cache(video_path, validate_fingerprint=False)
        if entry is None:
            # 空壳缓存：没有 drama，但有 preferences
            fingerprint = _file_fingerprint(video_path)
            entry = {
                "schema_version": self.SCHEMA_VERSION,
                "video_path": os.path.abspath(video_path),
                "file_size": fingerprint[0],
                "file_mtime": fingerprint[1],
                "cached_at": datetime.now().isoformat(),
                "drama": None,
                "character_prefs": {},
            }

        prefs = entry.get("character_prefs", {})
        prefs[character_name] = CharacterPreference(
            name=character_name, keep=keep, weight=weight, note=note,
        ).to_dict()
        entry["character_prefs"] = prefs
        entry["updated_at"] = datetime.now().isoformat()

        path = _cache_file_path(video_path)
        self._atomic_write(path, entry)
        return True

    def update_character_prefs(self, video_path: str,
                               prefs: Dict[str, CharacterPreference]) -> bool:
        """批量更新角色偏好"""
        entry = self._read_cache(video_path, validate_fingerprint=False)
        if entry is None:
            fingerprint = _file_fingerprint(video_path)
            entry = {
                "schema_version": self.SCHEMA_VERSION,
                "video_path": os.path.abspath(video_path),
                "file_size": fingerprint[0],
                "file_mtime": fingerprint[1],
                "cached_at": datetime.now().isoformat(),
                "drama": None,
                "character_prefs": {},
            }

        entry["character_prefs"] = {
            name: p.to_dict() for name, p in prefs.items()
        }
        entry["updated_at"] = datetime.now().isoformat()

        path = _cache_file_path(video_path)
        self._atomic_write(path, entry)
        return True

    # ─── 工具：清理 / 信息 ──────────────────────

    def info(self, video_path: str) -> Optional[Dict[str, Any]]:
        """返回缓存元信息（用于 UI 展示"已缓存 X 小时"等）"""
        entry = self._read_cache(video_path, validate_fingerprint=True)
        if entry is None:
            return None
        return {
            "cached_at": entry.get("cached_at"),
            "updated_at": entry.get("updated_at", entry.get("cached_at")),
            "num_characters": (
                len(entry["drama"].get("characters", []))
                if entry.get("drama") else 0
            ),
            "num_prefs": len(entry.get("character_prefs", {})),
            "source": entry.get("video_path"),
        }

    def clear(self, video_path: str) -> bool:
        """删除某视频的缓存"""
        path = _cache_file_path(video_path)
        if os.path.exists(path):
            try:
                os.remove(path)
                return True
            except OSError:
                return False
        return False

    def clear_all(self) -> int:
        """清空全部缓存，返回删除数"""
        root = _cache_root_dir()
        count = 0
        for name in os.listdir(root):
            if name.endswith(".json"):
                try:
                    os.remove(os.path.join(root, name))
                    count += 1
                except OSError:
                    pass
        return count

    # ─── 内部实现 ─────────────────────────

    def _read_cache(self, video_path: str, validate_fingerprint: bool) -> Optional[Dict[str, Any]]:
        path = _cache_file_path(video_path)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        if entry.get("schema_version") != self.SCHEMA_VERSION:
            return None

        if validate_fingerprint:
            try:
                cur_size, cur_mtime = _file_fingerprint(video_path)
            except OSError:
                return None
            if entry.get("file_size") != cur_size or abs(entry.get("file_mtime", 0) - cur_mtime) > 1.0:
                # 文件已被修改，缓存失效
                return None
        return entry

    def _atomic_write(self, path: str, entry: Dict[str, Any]):
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    # ─── DramaStructure 序列化 ─────────────────
    # DramaStructure 是 dataclass，我们做显式 to_dict / from_dict
    # 避免依赖 dataclasses_json（当前项目没装）

    def _drama_to_dict(self, drama) -> Dict[str, Any]:
        if drama is None:
            return None
        # 字符列表
        characters_list = []
        for c in getattr(drama, "characters", []):
            characters_list.append({
                "name": c.name,
                "role_type": c.role_type,
                "personality_traits": list(getattr(c, "personality_traits", []) or []),
                "relationships": dict(getattr(c, "relationships", {}) or {}),
                "appearance_times": [list(t) if isinstance(t, (list, tuple)) else t
                                      for t in getattr(c, "appearance_times", []) or []],
                "key_lines": list(getattr(c, "key_lines", []) or []),
            })

        # 情节点
        plot_points_list = []
        for p in getattr(drama, "plot_points", []):
            plot_points_list.append({
                "timestamp": float(getattr(p, "timestamp", 0)),
                "plot_type": str(getattr(p, "plot_type", "SETUP")),
                "description": str(getattr(p, "description", "")),
                "importance": float(getattr(p, "importance", 0.5)),
                "characters_involved": list(getattr(p, "characters_involved", []) or []),
                "emotional_impact": float(getattr(p, "emotional_impact", 0.5)),
            })

        # 场景
        scenes_list = []
        for s in getattr(drama, "scenes", []):
            scenes_list.append({
                "start_time": float(getattr(s, "start_time", 0)),
                "end_time": float(getattr(s, "end_time", 0)),
                "scene_type": str(getattr(s, "scene_type", "DIALOGUE")),
                "characters": list(getattr(s, "characters", []) or []),
                "location": str(getattr(s, "location", "")),
                "emotional_tone": str(getattr(s, "emotional_tone", "HAPPY")),
                "key_moments": list(getattr(s, "key_moments", []) or []),
            })

        return {
            "title": str(getattr(drama, "title", "")),
            "genre": str(getattr(drama, "genre", "")),
            "total_duration": float(getattr(drama, "total_duration", 0.0)),
            "characters": characters_list,
            "plot_points": plot_points_list,
            "scenes": scenes_list,
            "dialogues": [
                {
                    "start_time": float(getattr(d, "start_time", 0)),
                    "end_time": float(getattr(d, "end_time", 0)),
                    "speaker": str(getattr(d, "speaker", "")),
                    "text": str(getattr(d, "text", "")),
                    "emotion": str(getattr(d, "emotion", "HAPPY")),
                }
                for d in getattr(drama, "dialogues", [])
            ],
            "themes": list(getattr(drama, "themes", []) or []),
            "emotional_curve": [
                list(t) if isinstance(t, (list, tuple)) else t
                for t in getattr(drama, "emotional_curve", [])
            ],
            "pacing_analysis": dict(getattr(drama, "pacing_analysis", {}) or {}),
            # v3.0 新增字段
            "emotion_vectors": [
                list(map(float, v)) for v in getattr(drama, "_emotion_vectors", [])
            ],
            "emotion_journey": list(getattr(drama, "emotion_journey", []) or []),
        }

    def _drama_from_dict(self, d: Optional[Dict[str, Any]]):
        if not d:
            return None

        # 延迟导入，避免循环
        from .drama_understanding_engine import (
            DramaStructure, Character, PlotPoint, PlotPointType,
            SceneSegment, SceneType, EmotionalTone,
        )

        characters = []
        for c in d.get("characters", []):
            characters.append(Character(
                name=c.get("name", ""),
                role_type=c.get("role_type", "supporting"),
                personality_traits=list(c.get("personality_traits", [])),
                relationships=dict(c.get("relationships", {})),
                appearance_times=[tuple(t) if isinstance(t, list) else t
                                  for t in c.get("appearance_times", [])],
                key_lines=list(c.get("key_lines", [])),
            ))

        plot_points = []
        for p in d.get("plot_points", []):
            try:
                ptype = PlotPointType(p.get("plot_type", "SETUP"))
            except Exception:
                ptype = PlotPointType.SETUP
            plot_points.append(PlotPoint(
                timestamp=float(p.get("timestamp", 0)),
                plot_type=ptype,
                description=p.get("description", ""),
                importance=float(p.get("importance", 0.5)),
                characters_involved=list(p.get("characters_involved", [])),
                emotional_impact=float(p.get("emotional_impact", 0.5)),
            ))

        scenes = []
        for s in d.get("scenes", []):
            try:
                stype = SceneType(s.get("scene_type", "DIALOGUE"))
            except Exception:
                stype = SceneType.DIALOGUE
            try:
                etone = EmotionalTone(s.get("emotional_tone", "HAPPY"))
            except Exception:
                etone = EmotionalTone.HAPPY
            scenes.append(SceneSegment(
                start_time=float(s.get("start_time", 0)),
                end_time=float(s.get("end_time", 0)),
                scene_type=stype,
                characters=list(s.get("characters", [])),
                location=s.get("location", ""),
                emotional_tone=etone,
                key_moments=list(s.get("key_moments", [])),
            ))

        # dialogues（可选字段；若无则给空列表）
        dialogues = []
        try:
            from .drama_understanding_engine import DialogueSegment
            for dlg in d.get("dialogues", []):
                dialogues.append(DialogueSegment(
                    start_time=float(dlg.get("start_time", 0)),
                    end_time=float(dlg.get("end_time", 0)),
                    speaker=str(dlg.get("speaker", "")),
                    text=str(dlg.get("text", "")),
                    emotion=str(dlg.get("emotion", "HAPPY")),
                    volume=float(dlg.get("volume", 0.0)),
                    speed=float(dlg.get("speed", 0.0)),
                ))
        except Exception:
            dialogues = []

        return DramaStructure(
            title=d.get("title", ""),
            genre=d.get("genre", ""),
            total_duration=float(d.get("total_duration", 0.0)),
            characters=characters,
            plot_points=plot_points,
            scenes=scenes,
            dialogues=dialogues,
            themes=list(d.get("themes", [])),
            emotional_curve=[
                tuple(t) if isinstance(t, list) else t
                for t in d.get("emotional_curve", [])
            ],
            pacing_analysis=dict(d.get("pacing_analysis", {})),
            _emotion_vectors=[
                np.array(v, dtype=np.float32)
                for v in d.get("emotion_vectors", [])
            ],
            emotion_journey=list(d.get("emotion_journey", [])),
        )
