# -*- coding: utf-8 -*-
"""AssetMaster：角色/场景/道具/风格的母版模型（2026-10-20 · 上游第一刀）

设计文档 §0.3 的准确说法：**「有零件，缺抽象」**——角色锚定、道具守护、角色库都在，
但没有「母版 + 变体 + 继承」的统一模型，于是每次重抽都从零开始。

本模块只做**纯数据结构与纯函数**（零 I/O、零 UI、零 store）：
    Master（稳定设定） 1 ── * Variant（一次具体产出：seed/model/媒体/覆盖）
    变体继承母版字段，只存 overrides；母版改字段 ⇒ 变体可标记 stale。

纪律：
* 不猜：缺字段进 errors；未知 kind 不硬塞；
* 不静默覆盖：stale 变体仍可读，但 `stale_reason` 必须如实带出；
* 不接 UI/存储：接入角色库/场景库是下一刀（任务清单 D2），避免「先接线后改模型」。
"""
from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

MASTER_KINDS = ("character", "scene", "prop", "style")
MODEL_VERSION = "1.0"


def _now() -> float:
    return round(time.time(), 3)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深合并：override 覆盖 base；dict 递归，其余类型直接替换。不修改入参。"""
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class AssetVariant:
    """一次具体产出（图/视频/配音）：只存差异，继承母版。"""
    variant_id: str
    master_id: str
    overrides: Dict[str, Any] = field(default_factory=dict)
    media: List[str] = field(default_factory=list)
    seed: Optional[int] = None
    model: str = ""
    lineage: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    stale_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "master_id": self.master_id,
            "overrides": copy.deepcopy(self.overrides),
            "media": list(self.media),
            "seed": self.seed,
            "model": self.model,
            "lineage": copy.deepcopy(self.lineage),
            "created_at": self.created_at,
            "stale_reason": self.stale_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetVariant":
        # 契约是「吃 to_dict 的产物」：非 dict 落回空变体，不抛异常。
        if not isinstance(data, dict):
            return cls(variant_id="", master_id="")
        return cls(
            variant_id=str(data.get("variant_id") or ""),
            master_id=str(data.get("master_id") or ""),
            overrides=copy.deepcopy(data.get("overrides") or {}),
            media=list(data.get("media") or []),
            seed=data.get("seed") if isinstance(data.get("seed"), int) else None,
            model=str(data.get("model") or ""),
            lineage=copy.deepcopy(data.get("lineage") or {}),
            created_at=float(data.get("created_at") or _now()),
            stale_reason=str(data.get("stale_reason") or ""),
        )


@dataclass
class AssetMaster:
    """母版：一个角色/场景/道具/风格的稳定设定。"""
    master_id: str
    kind: str
    name: str
    canonical: Dict[str, Any] = field(default_factory=dict)
    variants: List[AssetVariant] = field(default_factory=list)
    version: int = 1
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    stale_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_version": MODEL_VERSION,
            "master_id": self.master_id,
            "kind": self.kind,
            "name": self.name,
            "canonical": copy.deepcopy(self.canonical),
            "variants": [v.to_dict() for v in self.variants],
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stale_reason": self.stale_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetMaster":
        # 契约是「吃 to_dict 的产物」：非 dict / 畸形 variants 一律落回空，
        # 不抛异常（此前 variants 传字符串会 AttributeError 炸穿调用方）。
        if not isinstance(data, dict):
            return cls(master_id="", kind="", name="")
        raw_variants = data.get("variants")
        variants = ([AssetVariant.from_dict(v) for v in raw_variants if isinstance(v, dict)]
                    if isinstance(raw_variants, list) else [])
        return cls(
            master_id=str(data.get("master_id") or ""),
            kind=str(data.get("kind") or ""),
            name=str(data.get("name") or ""),
            canonical=copy.deepcopy(data.get("canonical") if isinstance(data.get("canonical"), dict) else {}),
            variants=variants,
            version=int(data.get("version") or 1),
            created_at=float(data.get("created_at") or _now()),
            updated_at=float(data.get("updated_at") or _now()),
            stale_reason=str(data.get("stale_reason") or ""),
        )


def validate_master(master: AssetMaster) -> List[str]:
    errors: List[str] = []
    if not master.master_id:
        errors.append("master_id 不能为空")
    if master.kind not in MASTER_KINDS:
        errors.append(f"kind={master.kind!r} 不在 {MASTER_KINDS}")
    if not master.name:
        errors.append("name 不能为空")
    ids = [v.variant_id for v in master.variants]
    if any(not x for x in ids):
        errors.append("variant_id 不能为空")
    if len(ids) != len(set(ids)):
        errors.append("variant_id 重复")
    for v in master.variants:
        if v.master_id and v.master_id != master.master_id:
            errors.append(f"variant {v.variant_id} 的 master_id 不匹配")
    return errors


def create_master(kind: str, name: str, canonical: Optional[Dict[str, Any]] = None,
                  *, master_id: str = "") -> AssetMaster:
    return AssetMaster(
        master_id=master_id or f"master_{uuid.uuid4().hex[:12]}",
        kind=kind,
        name=name,
        canonical=copy.deepcopy(canonical or {}),
    )


def add_variant(master: AssetMaster, *, overrides: Optional[Dict[str, Any]] = None,
                media: Optional[List[str]] = None, seed: Optional[int] = None,
                model: str = "", lineage: Optional[Dict[str, Any]] = None,
                variant_id: str = "") -> AssetVariant:
    variant = AssetVariant(
        variant_id=variant_id or f"var_{uuid.uuid4().hex[:12]}",
        master_id=master.master_id,
        overrides=copy.deepcopy(overrides or {}),
        media=list(media or []),
        seed=seed,
        model=model,
        lineage=copy.deepcopy(lineage or {}),
    )
    master.variants.append(variant)
    return variant


def resolve_variant(master: AssetMaster, variant_id: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """解析变体的有效设定（母版 canonical + 变体 overrides 深合并）。

    返回 (resolved, errors)。找不到变体 ⇒ resolved=None + 明确 error（不猜）。
    """
    errors = validate_master(master)
    variant = next((v for v in master.variants if v.variant_id == variant_id), None)
    if variant is None:
        return None, errors + [f"未找到变体 {variant_id}（master={master.master_id}）"]
    resolved = deep_merge(master.canonical, variant.overrides)
    resolved["_master_id"] = master.master_id
    resolved["_variant_id"] = variant.variant_id
    resolved["_kind"] = master.kind
    if variant.stale_reason or master.stale_reason:
        resolved["_stale_reason"] = variant.stale_reason or master.stale_reason
    return resolved, errors


def update_canonical(master: AssetMaster, patch: Dict[str, Any], *,
                     mark_variants_stale: bool = True) -> List[AssetVariant]:
    """更新母版设定；默认把已有变体标 stale（旧产出不再代表新母版）。

    返回被标记 stale 的变体列表（调用方应如实提示，不静默丢弃）。
    """
    master.canonical = deep_merge(master.canonical, patch or {})
    master.version += 1
    master.updated_at = _now()
    marked: List[AssetVariant] = []
    if mark_variants_stale:
        reason = f"母版 v{master.version} 更新"
        for variant in master.variants:
            variant.stale_reason = reason
            marked.append(variant)
    return marked


def clear_stale(master: AssetMaster, variant_id: str) -> bool:
    variant = next((v for v in master.variants if v.variant_id == variant_id), None)
    if variant is None:
        return False
    variant.stale_reason = ""
    return True
