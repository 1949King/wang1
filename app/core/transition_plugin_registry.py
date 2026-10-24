"""
自研 / 插件转场注册表（ITransitionPlugin + 简易 apply()）
========================================================
扫描 `app/plugins/transition_*.py`，供调色页转场下拉与预览双帧混合使用。
不做剪映素材商店格式兼容。
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AI短剧编辑器.transition_plugins")

# 中文 UI 标签 → 插件 id（兼容旧下拉文案）
LEGACY_LABEL_TO_PLUGIN: Dict[str, str] = {
    "淡入淡出": "transition_fade",
    "滑动": "transition_slide",
    "缩放": "transition_zoom",
    "模糊": "transition_dissolve",
    "翻转": "transition_flip",
    "溶解": "transition_dissolve",
    "擦除": "transition_wipe",
    "推入": "transition_slide",
    "旋转": "transition_spin",
    "故障": "transition_glitch",
    "黑场": "transition_fadeblack",
    "黑场过渡": "transition_fadeblack",
    "白场": "transition_fadewhite",
    "白场过渡": "transition_fadewhite",
    "径向": "transition_radial",
    "径向擦除": "transition_radial",
    "时钟擦除": "transition_radial",
    "对角": "transition_diag",
    "对角擦除": "transition_diag",
    "翻页": "transition_page",
    "翻页转场": "transition_page",
}

_CURVE_TO_EASING: Dict[str, str] = {
    "线性": "linear",
    "缓入": "ease-in",
    "缓出": "ease-out",
    "缓入缓出": "ease-in-out",
    "弹性": "ease-in-out",
    "回弹": "ease-out",
}

_registry: Dict[str, Any] = {}
_infos: List[Dict[str, str]] = []
_loaded = False


def _plugins_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "plugins"))


def ensure_loaded() -> None:
    """惰性扫描并实例化 transition_*.py。"""
    global _loaded
    if _loaded:
        return
    _loaded = True
    root = _plugins_dir()
    if not os.path.isdir(root):
        return
    # 保证 app/ 与项目根可 import
    app_dir = os.path.dirname(root)
    proj = os.path.dirname(app_dir)
    for p in (proj, app_dir):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    for fname in sorted(os.listdir(root)):
        if not (fname.startswith("transition_") and fname.endswith(".py")):
            continue
        mod_name = fname[:-3]
        plugin_id = mod_name
        try:
            try:
                mod = importlib.import_module(f"app.plugins.{mod_name}")
            except ImportError:
                mod = importlib.import_module(f"plugins.{mod_name}")
            cls = getattr(mod, "Plugin", None)
            if cls is None:
                continue
            inst = cls()
            if hasattr(inst, "initialize"):
                try:
                    inst.initialize({})
                except Exception:
                    logger.debug("转场插件 %s initialize 失败", plugin_id, exc_info=True)
            name = plugin_id
            try:
                info = getattr(inst, "plugin_info", None)
                if info is not None and getattr(info, "name", None):
                    name = str(info.name)
                    plugin_id = str(getattr(info, "id", None) or plugin_id)
                elif getattr(inst, "name", None):
                    name = str(inst.name)
            except Exception:
                logger.debug("读取转场插件 %s 信息失败", plugin_id, exc_info=True)
            _registry[plugin_id] = inst
            _infos.append({"id": plugin_id, "name": name, "module": mod_name})
        except Exception as e:
            logger.debug("加载转场插件失败 %s: %s", fname, e)


def list_transitions() -> List[Dict[str, str]]:
    ensure_loaded()
    return list(_infos)


def resolve_plugin_id(label_or_id: str) -> Optional[str]:
    """UI 文案 / plugin_id / 英文短名 → 注册表 id。"""
    ensure_loaded()
    raw = str(label_or_id or "").strip()
    if not raw:
        return None
    if raw in _registry:
        return raw
    mapped = LEGACY_LABEL_TO_PLUGIN.get(raw)
    if mapped and mapped in _registry:
        return mapped
    # 短名 fade / slide
    cand = raw if raw.startswith("transition_") else f"transition_{raw}"
    if cand in _registry:
        return cand
    for info in _infos:
        if info["name"] == raw or info["module"] == raw:
            return info["id"]
    return mapped  # 即使未加载也返回约定 id，便于写元数据


def get_plugin(plugin_id: str) -> Optional[Any]:
    ensure_loaded()
    pid = resolve_plugin_id(plugin_id) or plugin_id
    return _registry.get(pid)


def easing_from_curve(curve: str) -> str:
    return _CURVE_TO_EASING.get(str(curve or ""), "ease-in-out")


def apply_frames(
    plugin_id: str,
    from_frame: Any,
    to_frame: Any,
    progress: float,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """调用插件混合两帧；失败返回 None。"""
    plugin = get_plugin(plugin_id)
    if plugin is None or from_frame is None or to_frame is None:
        return None
    progress = max(0.0, min(1.0, float(progress)))
    params = dict(params or {})
    try:
        a = from_frame
        b = to_frame
        if hasattr(a, "shape") and hasattr(b, "shape") and a.shape[:2] != b.shape[:2]:
            # 简易对齐到 from 尺寸
            try:
                import cv2

                b = cv2.resize(b, (a.shape[1], a.shape[0]))
            except Exception:
                return None
        if hasattr(plugin, "apply_transition"):
            return plugin.apply_transition(a, b, progress, params)
        if hasattr(plugin, "apply"):
            # 简易插件：仅传已知 kwargs
            import inspect

            sig = inspect.signature(plugin.apply)
            kwargs = {}
            for k, v in params.items():
                if k in sig.parameters:
                    kwargs[k] = v
            return plugin.apply(a, b, progress, **kwargs)
    except Exception as e:
        logger.debug("转场混合失败 %s: %s", plugin_id, e)
    return None


def display_entries() -> List[Tuple[str, str]]:
    """(显示名, plugin_id) 列表，供 QComboBox。"""
    ensure_loaded()
    if _infos:
        return [(i["name"], i["id"]) for i in _infos]
    # 扫描失败时回退中文内置
    return list(LEGACY_LABEL_TO_PLUGIN.items())


# plugin_id / UI 文案 → ffmpeg xfade 名（导出与预览语义对齐）
# 能盖住的尽量盖；盖不住的见 _EXPORT_FIDELITY + bake 路径
_PLUGIN_TO_XFADE: Dict[str, str] = {
    "transition_fade": "fade",
    "transition_dissolve": "dissolve",  # ffmpeg dissolve ≈ 像素噪点溶解
    "transition_zoom": "zoomin",
    "transition_flip": "squeezeh",  # bake 失败回退
    "transition_spin": "radial",  # bake 失败回退
    "transition_glitch": "pixelize",
    "transition_fadeblack": "fadeblack",
    "transition_fadewhite": "fadewhite",
    "transition_radial": "radial",
}

_SLIDE_XFADE = {
    "left": "slideleft",
    "right": "slideright",
    "up": "slideup",
    "down": "slidedown",
}
_WIPE_XFADE = {
    "left": "wipeleft",
    "right": "wiperight",
    "up": "wipeup",
    "down": "wipedown",
}
# 新增转场（2026-09-16 撑开）：open/close 或四向方向 → ffmpeg xfade 短名（全部 exact）
_CIRCLE_XFADE = {"open": "circleopen", "close": "circleclose"}
_VERT_XFADE = {"open": "vertopen", "close": "vertclose"}
_HORZ_XFADE = {"open": "horzopen", "close": "horzclose"}
_COVER_XFADE = {"left": "coverleft", "right": "coverright", "up": "coverup", "down": "coverdown"}
_REVEAL_XFADE = {"left": "revealleft", "right": "revealright", "up": "revealup", "down": "revealdown"}
_SMOOTH_XFADE = {"left": "smoothleft", "right": "smoothright", "up": "smoothup", "down": "smoothdown"}
# 新增真转场（2026-09-26 优秀三件事③）：对角起始角 / 翻页方向 → ffmpeg xfade 短名
# 注意：ffmpeg diag* 命名与「B 揭示起始角」相反（diagtl 的 B 来自右下）——
# 已用本机 ffmpeg 金标准渲染验证（≤4 LSB），勿按字面改回 tl→diagtl。
_DIAG_XFADE = {"tl": "diagbr", "tr": "diagbl", "bl": "diagtr", "br": "diagtl"}
_PAGE_XFADE = {"left": "coverleft", "right": "coverright"}  # bake 失败回退近似

# 兼容旧中文短名 / 插件显示名
_LABEL_TO_XFADE: Dict[str, str] = {
    "淡入淡出": "fade",
    "滑动": "slideright",
    "滑动转场": "slideright",
    "缩放": "zoomin",
    "缩放转场": "zoomin",
    "模糊": "hblur",
    "翻转": "squeezeh",
    "翻转转场": "squeezeh",
    "溶解": "dissolve",
    "溶解转场": "dissolve",
    "擦除": "wipeleft",
    "擦除转场": "wipeleft",
    "推入": "slideleft",
    "旋转": "radial",
    "旋转转场": "radial",
    "故障": "pixelize",
    "故障转场": "pixelize",
    "黑场": "fadeblack",
    "黑场过渡": "fadeblack",
    "白场": "fadewhite",
    "白场过渡": "fadewhite",
    "径向": "radial",
    "径向擦除": "radial",
    "时钟擦除": "radial",
    "对角": "diagtl",
    "对角擦除": "diagtl",
    "翻页": "coverleft",
    "翻页转场": "coverleft",
}

# mode: exact | approx | bake
# exact = 预览≈导出；approx = xfade 近似（须提示）；bake = 插件帧烘焙（失败回退 xfade）
_EXPORT_FIDELITY: Dict[str, Dict[str, str]] = {
    "transition_fade": {
        "mode": "exact",
        "xfade": "fade",
        "note": "",
    },
    "transition_slide": {
        "mode": "exact",
        "xfade": "",  # 方向在 xfade_name_for_transition 解析
        "note": "",
    },
    "transition_wipe": {
        "mode": "exact",
        "xfade": "",
        "note": "",
    },
    "transition_dissolve": {
        "mode": "exact",
        "xfade": "dissolve",
        "note": "",
    },
    "transition_zoom": {
        "mode": "approx",
        "xfade": "zoomin",
        "note": "导出将近似为 zoomin（非预览中心缩放叠层）",
    },
    "transition_flip": {
        "mode": "bake",
        "xfade": "squeezeh",
        "note": "导出将烘焙翻转效果（失败则近似为 squeezeh）",
    },
    "transition_spin": {
        "mode": "bake",
        "xfade": "radial",
        "note": "导出将烘焙旋转效果（失败则近似为 radial）",
    },
    "transition_glitch": {
        "mode": "approx",
        "xfade": "pixelize",
        "note": "导出将近似为 pixelize（非预览 RGB 错位/块位移）",
    },
    "transition_circle": {
        "mode": "exact",
        "xfade": "",  # open/close 在 xfade_name_for_transition 解析
        "note": "",
    },
    "transition_vert": {
        "mode": "exact",
        "xfade": "",
        "note": "",
    },
    "transition_horz": {
        "mode": "exact",
        "xfade": "",
        "note": "",
    },
    "transition_cover": {
        "mode": "exact",
        "xfade": "",
        "note": "",
    },
    "transition_reveal": {
        "mode": "exact",
        "xfade": "",
        "note": "",
    },
    "transition_smooth": {
        "mode": "exact",
        "xfade": "",
        "note": "",
    },
    "transition_fadeblack": {
        "mode": "bake",
        "xfade": "fadeblack",  # bake 失败回退（本机 xfade 曲线与插件有版本漂移，属近似）
        "note": "导出将烘焙黑场效果（失败则近似为 xfade fadeblack）",
    },
    "transition_fadewhite": {
        "mode": "bake",
        "xfade": "fadewhite",
        "note": "导出将烘焙白场效果（失败则近似为 xfade fadewhite）",
    },
    "transition_radial": {
        "mode": "exact",
        "xfade": "radial",  # 金标准验证：预览 vs 本机 xfade ≤4 LSB
        "note": "",
    },
    "transition_diag": {
        "mode": "exact",
        "xfade": "",  # 起始角在 xfade_name_for_transition 解析（金标准验证 ≤4 LSB）
        "note": "",
    },
    "transition_page": {
        "mode": "bake",
        "xfade": "coverleft",  # bake 失败回退（方向在 xfade_name_for_transition 解析）
        "note": "导出将烘焙翻页效果（失败则近似为 cover 覆盖）",
    },
}

_KNOWN_XFADE = frozenset({
    "fade", "dissolve", "slideright", "slideleft", "slideup", "slidedown",
    "wipeleft", "wiperight", "wipeup", "wipedown", "smoothleft", "smoothright",
    "smoothup", "smoothdown", "hblur", "zoomin", "pixelize", "radial",
    "squeezeh", "squeezev", "horzopen", "horzclose", "vertopen", "vertclose",
    "circleopen", "circleclose", "fadeblack", "fadewhite",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
    "diagtl", "diagtr", "diagbl", "diagbr",
})


def xfade_name_for_transition(trans: Optional[Dict[str, Any]]) -> str:
    """片段转场元数据 → ffmpeg xfade transition= 名（读 plugin_id）。"""
    if not isinstance(trans, dict):
        return "fade"
    direction = str(trans.get("direction") or "right").lower().strip()
    raw = str(trans.get("plugin_id") or trans.get("type") or trans.get("name") or "")
    pid = _canonical_plugin_id(raw)
    if pid == "transition_slide":
        return _SLIDE_XFADE.get(direction, "slideright")
    if pid == "transition_wipe":
        return _WIPE_XFADE.get(direction, "wipeleft")
    if pid == "transition_circle":
        return _CIRCLE_XFADE.get(direction, "circleopen")
    if pid == "transition_vert":
        return _VERT_XFADE.get(direction, "vertopen")
    if pid == "transition_horz":
        return _HORZ_XFADE.get(direction, "horzopen")
    if pid == "transition_cover":
        return _COVER_XFADE.get(direction, "coverleft")
    if pid == "transition_reveal":
        return _REVEAL_XFADE.get(direction, "revealleft")
    if pid == "transition_smooth":
        return _SMOOTH_XFADE.get(direction, "smoothleft")
    if pid == "transition_diag":
        return _DIAG_XFADE.get(direction, "diagtl")
    if pid == "transition_page":
        return _PAGE_XFADE.get(direction, "coverleft")
    if pid and pid in _PLUGIN_TO_XFADE:
        return _PLUGIN_TO_XFADE[pid]
    label = str(trans.get("type") or trans.get("name") or "").strip()
    if label in _LABEL_TO_XFADE:
        return _LABEL_TO_XFADE[label]
    # 已是合法 xfade 短名
    if label in _KNOWN_XFADE:
        return label
    return "fade"


def _canonical_plugin_id(raw: str) -> str:
    """解析 plugin_id；未加载进注册表时仍认约定 id / 中文标签。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    pid = resolve_plugin_id(s)
    if pid:
        return pid
    known = set(_EXPORT_FIDELITY) | set(_PLUGIN_TO_XFADE) | {
        "transition_slide", "transition_wipe",
    }
    if s in known:
        return s
    mapped = LEGACY_LABEL_TO_PLUGIN.get(s)
    if mapped:
        return mapped
    cand = s if s.startswith("transition_") else f"transition_{s}"
    if cand in known:
        return cand
    return ""


def export_fidelity_for_transition(trans: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """导出保真度计划：mode / xfade / note / plugin_id / display。

    mode:
      - exact: 预览≈导出（xfade 语义对齐）
      - approx: 映射到最近 xfade，须提示用户
      - bake: 优先插件帧烘焙，失败回退 xfade
    """
    if not isinstance(trans, dict):
        return {
            "plugin_id": "",
            "display": "淡入淡出",
            "mode": "exact",
            "xfade": "fade",
            "note": "",
        }
    raw = str(trans.get("plugin_id") or trans.get("type") or trans.get("name") or "")
    pid = _canonical_plugin_id(raw)
    display = str(trans.get("type") or trans.get("name") or pid or "转场").strip()
    xfade = xfade_name_for_transition(trans)
    meta = _EXPORT_FIDELITY.get(pid) if pid else None
    if meta:
        return {
            "plugin_id": pid,
            "display": display,
            "mode": meta["mode"],
            "xfade": xfade or meta.get("xfade") or "fade",
            "note": meta.get("note") or "",
        }
    # 未知插件：诚实降级
    note = f"「{display}」导出将近似为 {xfade or 'fade'}"
    return {
        "plugin_id": pid,
        "display": display,
        "mode": "approx",
        "xfade": xfade or "fade",
        "note": note,
    }


def is_bakeable_transition(trans: Optional[Dict[str, Any]]) -> bool:
    """是否走插件帧烘焙导出（flip / spin）。"""
    plan = export_fidelity_for_transition(trans)
    return plan.get("mode") == "bake"


def export_degradation_note(trans: Optional[Dict[str, Any]]) -> str:
    """单条转场的用户可见导出说明（exact 且无 note 时返回空串）。"""
    plan = export_fidelity_for_transition(trans)
    note = (plan.get("note") or "").strip()
    if note:
        return note
    if plan.get("mode") == "approx":
        disp = plan.get("display") or "转场"
        xf = plan.get("xfade") or "fade"
        return f"「{disp}」导出将近似为 {xf}"
    return ""


def collect_transition_export_notes(
    transitions: List[Optional[Dict[str, Any]]],
) -> List[str]:
    """去重后的导出提示列表（应用转场 / 导出前展示）。"""
    seen = set()
    out: List[str] = []
    for t in transitions or []:
        if not isinstance(t, dict):
            continue
        note = export_degradation_note(t)
        if not note or note in seen:
            continue
        seen.add(note)
        out.append(note)
    return out
