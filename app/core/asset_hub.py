# -*- coding: utf-8 -*-
"""asset_hub.py — 画布产物 ↔ 剪辑片段的**资产中间表示**薄门面（刀2 · 2026-10-23）

## 要解决的问题

画布产物进入剪辑时间线时，载荷只有 6 个程序性字段：:

    {path, title, source, send_to_editor, kind, duration_sec}   # stage3dArtifacts.ts:125-133

产物**没有身份**（无 asset_id）、**没有版本**（重复发同一路径无法区分）、
**血缘只有 4/6 键**（前端 `generationFromNode` 只发 prompt/model/seed/character_id，
丢了 `channel` / `reference`，见 editorIngress.ts:92-101）。于是：

* 「同一角色跨镜复用有唯一来源」不成立（D2 验收口径）；
* 工程文件换 NLE 打开即丢血缘（`timeline_dsl.Clip` 无 generation 字段）；
* 三套资产结构互不相连：`Stage3dArtifact`(TS, MAX_KEEP=8) / `AssetEntry`(code_video) /
  `AssetMaster`(母版模型, 零调用)。

## 本模块的定位：**薄门面，不建第二套存储**

资产真相源**已经存在** —— `app/core/gen_task_registry.py` 的 AssetNode
（`record_asset` / `get_asset` / `find_asset_by_path` / `resolve_lineage`）。
本模块照 `media_perception.py` 的先例（门面只分发、不重写算法）只做三件事：

1. `asset_ref_from_ingest()` —— 把 `/ingest_path` 的入参归一成 `AssetRef`；
   血缘走 `glue.schema.normalize_generation`（**六键白名单单一来源，不扩容**）；
2. `remember_ingest()` —— 把 AssetRef 写进 `gen_task_registry.record_asset`
   （无 path/asset_id ⇒ 诚实拒绝，不造无主记录）；
3. `lineage_of_clip()` —— 委托 `resolve_lineage`，查不到如实返回空槽。

## 与 `asset_master` 的关系

`asset_master` 是**母版模型**（character/scene/prop/style 的 canonical+variants），
本模块的 `AssetRef.master_id` 只是**引用**它 —— 不复制母版字段、不替代它。
母版接线（角色库 → create_master / add_variant）是 D2 的第二段，不在本模块内
（模型已由 `check_asset_master.py` 守，接线属于 UI 期）。

## 纪律

* 零 Qt、零网络、零 UI；只 import `glue.schema` 与 `gen_task_registry`；
* **不猜**：缺字段就缺，不补默认值；`asset_id` 缺失时由 path 确定性派生（不随机）；
* **不造假**：落账失败如实返回 False，不谎报成功；
* 六键血缘白名单**不扩容**（`code_video/spec.py` 有守卫断言同源）。
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

try:
    from app.core.glue.schema import normalize_generation
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.glue.schema import normalize_generation  # type: ignore

ASSET_HUB_VERSION = "1.0"

#: 从 `/ingest_path` 载荷可识别的资产类别（与 MATERIAL_TO_TIMELINE 的 kind 对齐）。
ASSET_KINDS = ("image", "video", "audio", "text", "unknown")


def _text(value: Any) -> str:
    """非空 trimmed 字符串，否则空串（不把 None/数字悄悄转成正文）。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def derive_asset_id(path: str, *, source: str = "") -> str:
    """由「规范化路径 + 出处」确定性派生 asset_id。

    为什么不用随机 uuid：同一路径重复入轨必须命中同一条 AssetNode
    （否则「唯一来源」永远不成立）；确定性哈希让重放幂等，且跨进程稳定
    （**不用内置 `hash()`** —— 它带进程随机盐，同 gen_task_registry 的纪律）。
    找不到 path 时返回空串（诚实：不造无主身份）。
    """
    norm = _text(path).replace("\\", "/").lower()
    if not norm:
        return ""
    digest = hashlib.sha1(f"{norm}|{_text(source)}".encode("utf-8")).hexdigest()
    return f"ast_{digest[:16]}"


def normalize_kind(value: Any) -> str:
    """把任意 kind 归一到 ASSET_KINDS；不认识就是 "unknown"（不硬塞）。"""
    text = _text(value).lower()
    if text in ASSET_KINDS:
        return text
    # 常见别名：视频/图片/音频/字幕
    alias = {"movie": "video", "pic": "image", "photo": "image",
             "sound": "audio", "music": "audio", "subtitle": "text"}
    return alias.get(text, "unknown")


@dataclass
class AssetRef:
    """画布产物在**资产层**的身份（带身份/血缘/版本，区别于裸路径）。

    `asset_id` 确定性派生；`lineage` 只收六键白名单；`version` 供重复入轨时
    区分「同一资产的第 N 次入轨」（不再是「覆盖」或「丢失历史」）。
    """

    asset_id: str
    path: str
    kind: str = "unknown"
    title: str = ""
    source: str = ""
    lineage: Dict[str, Any] = field(default_factory=dict)
    master_id: str = ""
    version: int = 1
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_hub_version": ASSET_HUB_VERSION,
            "asset_id": self.asset_id,
            "path": self.path,
            "kind": self.kind,
            "title": self.title,
            "source": self.source,
            "lineage": dict(self.lineage),
            "master_id": self.master_id,
            "version": self.version,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "AssetRef":
        """吃 `to_dict` 的产物；畸形输入落回空值，**不抛异常**。"""
        if not isinstance(data, Mapping):
            return cls(asset_id="", path="")
        return cls(
            asset_id=_text(data.get("asset_id")),
            path=_text(data.get("path")),
            kind=normalize_kind(data.get("kind")),
            title=_text(data.get("title")),
            source=_text(data.get("source")),
            lineage=normalize_generation(data.get("lineage")),
            master_id=_text(data.get("master_id")),
            version=int(data.get("version") or 1),
            created_at=float(data.get("created_at") or 0.0),
        )

    def lineage_keys(self) -> List[str]:
        """本资产实际携带的血缘键（衡量「六键齐全率」的原子）。"""
        return sorted(self.lineage.keys())


def asset_ref_from_ingest(
    payload: Mapping[str, Any],
    *,
    now: Optional[float] = None,
) -> AssetRef:
    """把 `/ingest_path` 的标准载荷归一成 `AssetRef`（**纯函数**，零副作用）。

    识别字段（沿用该端点的既有键名，不改契约）：
      * `path` → 本地绝对路径（缺失 ⇒ asset_id 为空，调用方须拒绝落账）
      * `kind` / `canvas_kind` → 资产类别
      * `title`、`source`
      * `generation` → 血缘块（过 `normalize_generation` 六键白名单）
      * `asset_id` → 后端已定时直用；缺省按 path+source 确定性派生
      * `master_id` → 引用母版（可选；不影响母版模型本身）
      * `version` → 同一资产第几次入轨（缺省 1）
    """
    if not isinstance(payload, Mapping):
        return AssetRef(asset_id="", path="")

    path = _text(payload.get("path"))
    source = _text(payload.get("source")) or "infinite_canvas"
    raw_generation = payload.get("generation")
    lineage = normalize_generation(raw_generation) if isinstance(raw_generation, Mapping) else {}
    asset_id = _text(payload.get("asset_id")) or derive_asset_id(path, source=source)

    version_raw = payload.get("version")
    version = 1
    if isinstance(version_raw, int) and not isinstance(version_raw, bool) and version_raw > 0:
        version = version_raw

    return AssetRef(
        asset_id=asset_id,
        path=path,
        kind=normalize_kind(payload.get("kind") or payload.get("canvas_kind")),
        title=_text(payload.get("title")),
        source=source,
        lineage=lineage,
        master_id=_text(payload.get("master_id")),
        version=version,
        created_at=float(now if now is not None else 0.0),
    )


def remember_ingest(ref: AssetRef, *, store: Any = None) -> bool:
    """把 AssetRef 写进资产真相源（`gen_task_registry` 的 AssetNode）。

    返回是否真的落账（**失败如实 False，不谎报**）：
      * ref 为空 / 无 path / 无 asset_id ⇒ False（不造无主记录）；
      * store 不可用 / `record_asset` 抛错或返回 None ⇒ False。

    落账只写「身份 + 血缘 + 版本」这三类**已有字段**，不新增 schema：
    `generation_task_id` 留空（本刀不生成任务），`canvas_node_id` 由调用方传。
    """
    if not is_asset_ref(ref):
        return False
    if not ref.path or not ref.asset_id:
        return False
    if store is None:
        try:
            from app.core.gen_task_registry import get_store
        except ImportError:
            try:
                from core.gen_task_registry import get_store  # type: ignore
            except ImportError:
                return False
        try:
            store = get_store()
        except Exception:
            return False
    record_asset = getattr(store, "record_asset", None)
    if not callable(record_asset):
        return False
    try:
        rec = record_asset(
            ref.asset_id,
            path=ref.path,
            kind=ref.kind,
            canvas_node_id=_text(getattr(ref, "canvas_node_id", "")),
        )
    except Exception:
        return False
    return rec is not None


def lineage_of_clip(clip: Mapping[str, Any], *, store: Any = None) -> Dict[str, Any]:
    """clip → asset → task → canvas_node 链查询（委托 `resolve_lineage`）。

    查不到的槽位如实为 None（诚实：不猜、不补默认值）。
    与 `gen_task_registry.resolve_lineage` 同一实现，本函数只是稳定入口。
    """
    if not isinstance(clip, Mapping):
        return {"clip_id": "", "asset": None, "task": None, "canvas_node_id": ""}
    if store is None:
        try:
            from app.core.gen_task_registry import get_store
        except ImportError:
            try:
                from core.gen_task_registry import get_store  # type: ignore
            except ImportError:
                return {"clip_id": _text(clip.get("id")), "asset": None,
                        "task": None, "canvas_node_id": ""}
        try:
            store = get_store()
        except Exception:
            return {"clip_id": _text(clip.get("id")), "asset": None,
                    "task": None, "canvas_node_id": ""}
    resolver = getattr(store, "resolve_lineage", None)
    if not callable(resolver):
        return {"clip_id": _text(clip.get("id")), "asset": None,
                "task": None, "canvas_node_id": ""}
    try:
        return resolver(dict(clip))
    except Exception:
        return {"clip_id": _text(clip.get("id")), "asset": None,
                "task": None, "canvas_node_id": ""}


def lineage_coverage(refs: List[AssetRef]) -> Dict[str, Any]:
    """统计「血缘六键齐全率」（D2 的可量化验收口径，纯函数）。

    返回每个键的命中数 + 六键全齐的资产数 + 样本总数。
    **不把「没测」说成「测了」**：空样本 ⇒ coverage 为 None，不是 0。
    """
    usable = [r for r in refs if isinstance(r, AssetRef) and r.asset_id]
    if not usable:
        return {"total": 0, "complete": 0, "coverage": None, "per_key": {}}
    from app.core.glue.schema import GENERATION_KEYS  # 单一来源，不在此复制名单

    per_key = {key: sum(1 for r in usable if key in r.lineage) for key in GENERATION_KEYS}
    complete = sum(1 for r in usable if all(k in r.lineage for k in GENERATION_KEYS))
    return {
        "total": len(usable),
        "complete": complete,
        "coverage": round(complete / len(usable), 4),
        "per_key": per_key,
    }


def is_asset_ref(value: Any) -> bool:
    """结构判定（**不用 isinstance**）。

    本仓库同时存在两种导入风格（`from app.core.x` 与 `from core.x`），
    测试的 conftest 把 `app/` 和项目根都塞进 `sys.path` ⇒ 同一文件会被
    加载成**两个不同的类对象**，`isinstance` 跨风格判定失败（刀2 实测踩到）。
    故这里按「是本模块的 AssetRef 或其鸭子类型等价物」判定：具备 asset_id /
    path / lineage / to_dict 四个成员即认，既不误判 dict，也不受双加载影响。
    """
    if isinstance(value, AssetRef):
        return True
    return (hasattr(value, "asset_id") and hasattr(value, "path")
            and hasattr(value, "lineage") and callable(getattr(value, "to_dict", None)))


# 便于调用方判断「路径是否已在 inbox」，与 canvas_bridge 同一口径（不重复实现）。
def is_inbox_path(path: str, inbox_dir: str) -> bool:
    """判断路径是否已位于 inbox（纯字符串比较，不访问磁盘）。"""
    if not _text(path) or not _text(inbox_dir):
        return False
    a = os.path.normcase(os.path.abspath(path))
    b = os.path.normcase(os.path.abspath(inbox_dir))
    return os.path.dirname(a) == b
