# -*- coding: utf-8 -*-
"""预设管理器：5 类基础预设 + 美学预设包（组合）。

历史（2026-09-16 之前）：``import_preset`` / ``export_preset`` / ``apply_preset``
三方法全是空壳，纯内存 dict 不落盘，且没有「预设包」（组合）概念。
本轮补齐：
  1. JSON 落盘（项目根/data/presets.json），仅持久化「用户自定义」数据，
     代码内嵌默认预设/默认包每次启动重建，互不污染。
  2. ``import_preset`` / ``export_preset`` 真正读写 JSON。
  3. 美学预设包（aesthetic pack）：多个 clip 级 step 的组合，一键套用。
     ``apply_pack`` 只做数据解析，真正写真相源 ``_clips`` 由
     ``EditorModule.apply_aesthetic_pack`` 负责（走可撤销 compound action）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

# 存储路径基于本文件定位（项目根/data），与启动时工作目录无关。
# 与 app/core/memory_store.py 的 _STORAGE_PATH 同约定。
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))          # app/core
_STORAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(_MODULE_DIR)), "data", "presets.json"
)

# 美学预设包支持的 clip 级 step 种类（写真相源 _clips 的能力面）
PACK_STEP_KINDS = ("color", "lut", "filter", "transition", "blend_mode", "opacity")


class PresetManager:
    def __init__(self):
        self.presets = {
            "effect": [],
            "transition": [],
            "export": [],
            "audio": [],
            "subtitle": []
        }
        self.packs: List[Dict[str, Any]] = []
        # 代码内嵌默认数据 id 集合（落盘时排除，避免磁盘重复/覆盖默认）
        self._default_preset_ids: set = set()
        self._default_pack_ids: set = set()
        self._initialize_default_presets()
        self._initialize_default_packs()
        self._load_from_disk()

    # ─────────────────────────────────────────────────────────
    # 默认数据（代码内嵌）
    # ─────────────────────────────────────────────────────────

    def _initialize_default_presets(self):
        """初始化默认预设"""
        # 特效预设
        self.presets["effect"].extend([
            {
                "id": "effect_preset_1",
                "name": "电影风格",
                "type": "effect",
                "category": "color",
                "parameters": {
                    "brightness": 0.9,
                    "contrast": 1.2,
                    "saturation": 1.1,
                    "hue": 0.0,
                    "gamma": 1.0
                },
                "effects": ["brightness", "contrast", "saturation"]
            },
            {
                "id": "effect_preset_2",
                "name": "复古风格",
                "type": "effect",
                "category": "color",
                "parameters": {
                    "brightness": 0.8,
                    "contrast": 1.0,
                    "saturation": 0.7,
                    "sepia": 0.6
                },
                "effects": ["brightness", "contrast", "saturation", "sepia"]
            },
            {
                "id": "effect_preset_3",
                "name": "黑白风格",
                "type": "effect",
                "category": "color",
                "parameters": {
                    "saturation": 0.0,
                    "contrast": 1.3
                },
                "effects": ["saturation", "contrast"]
            }
        ])

        # 转场预设
        self.presets["transition"].extend([
            {
                "id": "transition_preset_1",
                "name": "平滑淡入淡出",
                "type": "transition",
                "category": "fade",
                "parameters": {
                    "duration": 1.0,
                    "ease_in": 0.5,
                    "ease_out": 0.5
                },
                "transition_type": "fade"
            },
            {
                "id": "transition_preset_2",
                "name": "快速滑动",
                "type": "transition",
                "category": "slide",
                "parameters": {
                    "duration": 0.5,
                    "direction": "left",
                    "ease": "ease_out"
                },
                "transition_type": "slide"
            }
        ])

        # 导出预设
        self.presets["export"].extend([
            {
                "id": "export_preset_1",
                "name": "HD 1080p",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "1920x1080",
                    "frame_rate": 30,
                    "bitrate": "10M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "128k"
                }
            },
            {
                "id": "export_preset_2",
                "name": "4K Ultra HD",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "3840x2160",
                    "frame_rate": 60,
                    "bitrate": "30M",
                    "codec": "h265",
                    "audio_codec": "aac",
                    "audio_bitrate": "256k"
                }
            },
            {
                "id": "export_preset_3",
                "name": "Instagram 方形",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "1080x1080",
                    "frame_rate": 30,
                    "bitrate": "5M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "128k"
                }
            },
            {
                "id": "export_preset_vertical_1080",
                "name": "抖音/TikTok 竖屏 1080×1920",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "1080x1920",
                    "frame_rate": 30,
                    "bitrate": "8M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "128k"
                }
            },
            {
                "id": "export_preset_vertical_4k",
                "name": "竖屏 4K 2160×3840",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "2160x3840",
                    "frame_rate": 30,
                    "bitrate": "20M",
                    "codec": "h265",
                    "audio_codec": "aac",
                    "audio_bitrate": "192k"
                }
            },
            {
                "id": "export_preset_instagram_45",
                "name": "Instagram 竖方 1080×1350",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "1080x1350",
                    "frame_rate": 30,
                    "bitrate": "6M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "128k"
                }
            },
            {
                "id": "export_preset_widescreen_2560",
                "name": "电影超宽 2560×1080",
                "type": "export",
                "category": "video",
                "parameters": {
                    "resolution": "2560x1080",
                    "frame_rate": 24,
                    "bitrate": "12M",
                    "codec": "h264",
                    "audio_codec": "aac",
                    "audio_bitrate": "192k"
                }
            }
        ])

        # 音频预设
        self.presets["audio"].extend([
            {
                "id": "audio_preset_1",
                "name": "电影音频",
                "type": "audio",
                "category": "mix",
                "parameters": {
                    "volume": 1.0,
                    "bass": 1.2,
                    "mid": 1.0,
                    "treble": 1.1,
                    "compression": 0.5
                }
            },
            {
                "id": "audio_preset_2",
                "name": "语音优化",
                "type": "audio",
                "category": "voice",
                "parameters": {
                    "volume": 1.2,
                    "bass": 0.8,
                    "mid": 1.3,
                    "treble": 1.1,
                    "noise_reduction": 0.6
                }
            }
        ])

        # 字幕预设
        self.presets["subtitle"].extend([
            {
                "id": "subtitle_preset_1",
                "name": "电影字幕",
                "type": "subtitle",
                "category": "display",
                "parameters": {
                    "font": "Arial",
                    "font_size": 24,
                    "color": "#FFFFFF",
                    "background": "#000000",
                    "opacity": 0.8,
                    "alignment": "bottom",
                    "margin": 30
                }
            },
            {
                "id": "subtitle_preset_2",
                "name": "标题字幕",
                "type": "subtitle",
                "category": "display",
                "parameters": {
                    "font": "Arial Bold",
                    "font_size": 36,
                    "color": "#FFFFFF",
                    "background": "transparent",
                    "opacity": 1.0,
                    "alignment": "center",
                    "margin": 50
                }
            }
        ])

        for ptype in self.presets:
            for p in self.presets[ptype]:
                self._default_preset_ids.add(p["id"])

    def _initialize_default_packs(self):
        """初始化默认美学预设包（clip 级组合）。"""
        self.packs.extend([
            {
                "id": "aesthetic_pack_cinema",
                "name": "电影感",
                "description": "电影胶片 LUT + 轻对比提饱和 + 淡入淡出转场",
                "applies_to": "clip",
                "steps": [
                    {"kind": "lut", "lut": "cinema_warm", "lut_intensity": 0.7},
                    {"kind": "color", "contrast": 1.08, "saturation": 1.05},
                    {"kind": "transition", "transition_type": "fade", "duration": 0.8},
                ],
            },
            {
                "id": "aesthetic_pack_retro",
                "name": "复古暖调",
                "description": "复古暖调 LUT + 暖色温 + 慢速滑动转场",
                "applies_to": "clip",
                "steps": [
                    {"kind": "lut", "lut": "vintage", "lut_intensity": 0.8},
                    {"kind": "color", "temperature": 8.0, "saturation": 0.95},
                    {"kind": "transition", "transition_type": "slide", "duration": 0.6},
                ],
            },
            {
                "id": "aesthetic_pack_fresh",
                "name": "日系清新",
                "description": "日系清新 LUT + 轻微提亮 + 快速滑动转场",
                "applies_to": "clip",
                "steps": [
                    {"kind": "lut", "lut": "jp_fresh", "lut_intensity": 0.6},
                    {"kind": "color", "brightness": 0.05, "saturation": 1.02},
                    {"kind": "transition", "transition_type": "slide", "duration": 0.4},
                ],
            },
            {
                "id": "aesthetic_pack_bw",
                "name": "黑白经典",
                "description": "黑白 LUT + 高对比去饱和 + 淡入淡出转场",
                "applies_to": "clip",
                "steps": [
                    {"kind": "lut", "lut": "bw", "lut_intensity": 0.9},
                    {"kind": "color", "contrast": 1.2, "saturation": 0.0},
                    {"kind": "transition", "transition_type": "fade", "duration": 0.7},
                ],
            },
        ])
        for p in self.packs:
            self._default_pack_ids.add(p["id"])

    # ─────────────────────────────────────────────────────────
    # 持久化（只存用户自定义数据，默认数据代码内嵌）
    # ─────────────────────────────────────────────────────────

    def _is_user_preset(self, preset: Dict[str, Any]) -> bool:
        return bool(preset.get("id")) and preset["id"] not in self._default_preset_ids

    def _is_user_pack(self, pack: Dict[str, Any]) -> bool:
        return bool(pack.get("id")) and pack["id"] not in self._default_pack_ids

    def _save(self) -> bool:
        """把「用户自定义」预设/包落盘为 JSON。"""
        data = {
            "schema_version": 1,
            "presets": {
                ptype: [p for p in self.presets[ptype] if self._is_user_preset(p)]
                for ptype in self.presets
            },
            "packs": [p for p in self.packs if self._is_user_pack(p)],
        }
        try:
            os.makedirs(os.path.dirname(_STORAGE_PATH), exist_ok=True)
            with open(_STORAGE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    def _load_from_disk(self) -> None:
        """启动时把磁盘上的用户自定义数据追加到默认数据之上（按 id 去重）。"""
        try:
            with open(_STORAGE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        disk_presets = (data or {}).get("presets", {}) or {}
        for ptype, plist in disk_presets.items():
            if ptype not in self.presets:
                continue
            existing = {p["id"] for p in self.presets[ptype]}
            for p in (plist or []):
                if isinstance(p, dict) and p.get("id") and p["id"] not in existing:
                    self.presets[ptype].append(p)
        disk_packs = (data or {}).get("packs", []) or []
        existing_packs = {p["id"] for p in self.packs}
        for p in disk_packs:
            if isinstance(p, dict) and p.get("id") and p["id"] not in existing_packs:
                self.packs.append(p)

    # ─────────────────────────────────────────────────────────
    # 基础预设 CRUD
    # ─────────────────────────────────────────────────────────

    def create_preset(self, name, preset_type, parameters, category="default"):
        """创建预设"""
        if preset_type not in self.presets:
            return None

        preset = {
            "id": f"{preset_type}_preset_{len(self.presets[preset_type]) + 1}",
            "name": name,
            "type": preset_type,
            "category": category,
            "parameters": parameters,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        self.presets[preset_type].append(preset)
        self._save()
        return preset

    def get_preset(self, preset_id):
        """获取预设"""
        for preset_type, presets in self.presets.items():
            for preset in presets:
                if preset["id"] == preset_id:
                    return preset
        return None

    def list_presets(self, preset_type=None, category=None):
        """列出预设"""
        if preset_type:
            if preset_type not in self.presets:
                return []
            presets = self.presets[preset_type]
        else:
            presets = [p for ps in self.presets.values() for p in ps]

        if category:
            presets = [p for p in presets if p.get("category") == category]

        return presets

    def update_preset(self, preset_id, **kwargs):
        """更新预设"""
        preset = self.get_preset(preset_id)
        if preset:
            preset.update(kwargs)
            self._save()
            return True
        return False

    def delete_preset(self, preset_id):
        """删除预设（默认预设也可删，删除后即视为用户态不复现，除非 reset_to_defaults）"""
        for preset_type, presets in self.presets.items():
            for i, preset in enumerate(presets):
                if preset["id"] == preset_id:
                    self.presets[preset_type].pop(i)
                    self._save()
                    return True
        return False

    def search_presets(self, query, preset_type=None):
        """搜索预设"""
        if preset_type:
            if preset_type not in self.presets:
                return []
            presets = self.presets[preset_type]
        else:
            presets = [p for ps in self.presets.values() for p in ps]

        return [p for p in presets if query.lower() in p["name"].lower() or
                query.lower() in p.get("category", "").lower()]

    def import_preset(self, file_path):
        """导入预设：读 JSON 文件，支持单个预设 dict 或 {presets: {...}} 包结构。

        返回导入的预设列表（空 = 文件格式不合法）。
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

        candidates: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            # 可能是 {presets: {effect: [...], ...}} 或单个预设
            if "presets" in data:
                for plist in (data.get("presets") or {}).values():
                    if isinstance(plist, list):
                        candidates.extend(p for p in plist if isinstance(p, dict))
            elif data.get("id") and data.get("type") in self.presets:
                candidates.append(data)
        imported: List[Dict[str, Any]] = []
        for p in candidates:
            ptype = p.get("type")
            if ptype not in self.presets or not p.get("id"):
                continue
            existing = {x["id"] for x in self.presets[ptype]}
            if p["id"] in existing:
                # 覆盖同名（保持导入幂等）
                for i, x in enumerate(self.presets[ptype]):
                    if x["id"] == p["id"]:
                        self.presets[ptype][i] = p
                        break
            else:
                self.presets[ptype].append(p)
            imported.append(p)
        if imported:
            self._save()
        return imported

    def export_preset(self, preset_id, file_path):
        """导出单个预设到 JSON 文件。"""
        preset = self.get_preset(preset_id)
        if not preset:
            return False
        try:
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(preset, f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    def apply_preset(self, preset_id, target=None):
        """把单个预设解析为「执行指令」（kind + 参数），供 EditorModule 写真相源。

        注意：本方法只做数据解析，不直接写片段；真正写 ``_clips`` 由
        ``EditorModule.apply_aesthetic_pack`` / 未来的单预设执行入口负责。
        返回 None 表示预设不存在。
        """
        preset = self.get_preset(preset_id)
        if not preset:
            return None
        ptype = preset.get("type")
        params = dict(preset.get("parameters") or {})
        if ptype == "effect":
            return {"kind": "color", "name": preset.get("name", ""), **params}
        if ptype == "transition":
            return {
                "kind": "transition",
                "transition_type": params.get("transition_type") or preset.get("transition_type") or "fade",
                "duration": float(params.get("duration", 0.5)),
            }
        if ptype in ("subtitle", "audio", "export"):
            # 工程级预设不属 clip 级 step，原样返回供上层按类型处理
            return {"kind": ptype, "name": preset.get("name", ""), **params}
        return {"kind": ptype, "name": preset.get("name", ""), **params}

    def duplicate_preset(self, preset_id, new_name):
        """复制预设"""
        preset = self.get_preset(preset_id)
        if preset:
            new_preset = dict(preset)
            new_preset["id"] = f"{preset['type']}_preset_{len(self.presets[preset['type']]) + 1}"
            new_preset["name"] = new_name
            new_preset["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            self.presets[preset['type']].append(new_preset)
            self._save()
            return new_preset
        return None

    def get_preset_categories(self, preset_type=None):
        """获取预设分类"""
        categories = set()
        if preset_type:
            if preset_type in self.presets:
                for preset in self.presets[preset_type]:
                    categories.add(preset.get("category", "default"))
        else:
            for presets in self.presets.values():
                for preset in presets:
                    categories.add(preset.get("category", "default"))

        return list(categories)

    def reset_to_defaults(self, preset_type=None):
        """重置为默认预设"""
        if preset_type:
            if preset_type in self.presets:
                self.presets[preset_type] = []
        else:
            self.presets = {
                "effect": [],
                "transition": [],
                "export": [],
                "audio": [],
                "subtitle": []
            }
            self.packs = []
        self._default_preset_ids = set()
        self._default_pack_ids = set()
        self._initialize_default_presets()
        self._initialize_default_packs()
        self._save()
        return True

    # ─────────────────────────────────────────────────────────
    # 美学预设包（组合预设）
    # ─────────────────────────────────────────────────────────

    def list_packs(self) -> List[Dict[str, Any]]:
        """列出所有美学预设包。"""
        return list(self.packs)

    def get_pack(self, pack_id: str) -> Optional[Dict[str, Any]]:
        """按 id 取美学预设包。"""
        for p in self.packs:
            if p.get("id") == pack_id:
                return p
        return None

    def create_pack(self, name: str, steps: List[Dict[str, Any]],
                    description: str = "", applies_to: str = "clip",
                    pack_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """新建美学预设包。steps 仅接受 PACK_STEP_KINDS 里的 kind。"""
        cleaned = [s for s in (steps or []) if isinstance(s, dict) and s.get("kind") in PACK_STEP_KINDS]
        if not cleaned:
            return None
        pack = {
            "id": pack_id or f"aesthetic_pack_{len(self.packs) + 1}",
            "name": name,
            "description": description or "",
            "applies_to": applies_to or "clip",
            "steps": cleaned,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.packs.append(pack)
        self._save()
        return pack

    def delete_pack(self, pack_id: str) -> bool:
        """删除美学预设包。"""
        for i, p in enumerate(self.packs):
            if p.get("id") == pack_id:
                self.packs.pop(i)
                self._save()
                return True
        return False

    def import_pack(self, file_path: str) -> List[Dict[str, Any]]:
        """导入美学预设包：读 JSON，支持单包 dict 或 {packs: [...]} 结构。"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        candidates: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            if "packs" in data and isinstance(data["packs"], list):
                candidates.extend(p for p in data["packs"] if isinstance(p, dict))
            elif data.get("id") and isinstance(data.get("steps"), list):
                candidates.append(data)
        imported: List[Dict[str, Any]] = []
        for p in candidates:
            if not p.get("id") or not isinstance(p.get("steps"), list):
                continue
            cleaned = [s for s in p["steps"] if isinstance(s, dict) and s.get("kind") in PACK_STEP_KINDS]
            if not cleaned:
                continue
            p = dict(p)
            p["steps"] = cleaned
            existing = {x["id"] for x in self.packs}
            if p["id"] in existing:
                for i, x in enumerate(self.packs):
                    if x["id"] == p["id"]:
                        self.packs[i] = p
                        break
            else:
                self.packs.append(p)
            imported.append(p)
        if imported:
            self._save()
        return imported

    def export_pack(self, pack_id: str, file_path: str) -> bool:
        """导出美学预设包到 JSON 文件。"""
        pack = self.get_pack(pack_id)
        if not pack:
            return False
        try:
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(pack, f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

    def apply_pack(self, pack_id: str, target=None) -> Optional[List[Dict[str, Any]]]:
        """解析美学预设包为有序 step 列表（供 EditorModule 写真相源）。

        只做数据解析，不直接写片段；返回 None 表示包不存在。
        """
        pack = self.get_pack(pack_id)
        if not pack:
            return None
        return [dict(s) for s in (pack.get("steps") or [])
                if isinstance(s, dict) and s.get("kind") in PACK_STEP_KINDS]
