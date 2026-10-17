"""
工具栏 / 快捷键统一指令入口
==========================
一次动作 → 同一套 EditorModule 方法，避免按钮与快捷键分叉。

不负责 UI 刷新细节；调用方仍走 editor 既有副作用（写 _clips / undo / 时间线同步）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("AI短剧编辑器.editor_ux_commands")

# 允许的动作名（工具栏 + 快捷键共用）
KNOWN_ACTIONS = (
    "import",
    "import_timeline",   # 时间线互操作导入（OTIO/EDL/FCPXML，2026-10-18）
    "open_project",
    "save_project",
    "export",
    "cut",          # 播放头切割
    "copy",
    "paste",
    "delete",
    "undo",
    "redo",
    "play_pause",
    "toggle_snap",
    "close_gap",    # 空隙收拢 / 波纹消隙
    "toggle_razor",
    "toggle_ripple",
    "set_preview_quality",
    "toggle_proxy",
)


def dispatch_editor_action(editor: Any, action: str, **kwargs) -> Dict[str, Any]:
    """
    统一调度。返回 {"ok": bool, "action": str, "message": str}。
    """
    name = str(action or "").strip().lower()
    if name not in KNOWN_ACTIONS:
        return {"ok": False, "action": name, "message": f"未知动作: {name}"}

    try:
        if name == "import":
            editor._import_video()
        elif name == "import_timeline":
            editor._import_timeline_document()
        elif name == "open_project":
            editor._open_project()
        elif name == "save_project":
            editor._save_project()
        elif name == "export":
            editor._export_video()
        elif name == "cut":
            editor._cut_clip()
        elif name == "copy":
            editor._copy_clip()
        elif name == "paste":
            editor._paste_clip()
        elif name == "delete":
            editor._delete_clip()
        elif name == "undo":
            editor._undo()
        elif name == "redo":
            editor._redo()
        elif name == "play_pause":
            editor._play_pause()
        elif name == "toggle_snap":
            enabled = kwargs.get("enabled")
            if enabled is None:
                cur = bool(getattr(editor, "_snap_enabled", True))
                enabled = not cur
            if hasattr(editor, "_on_snap_toggled"):
                editor._on_snap_toggled(bool(enabled))
            btn = getattr(editor, "_snap_btn", None)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(bool(enabled))
                btn.blockSignals(False)
        elif name == "close_gap":
            editor._ripple_delete_gaps()
        elif name == "toggle_razor":
            if hasattr(editor, "_toggle_razor_tool"):
                editor._toggle_razor_tool()
        elif name == "toggle_ripple":
            cur = bool(getattr(editor, "_ripple_delete_enabled", True))
            enabled = kwargs.get("enabled")
            if enabled is None:
                enabled = not cur
            if hasattr(editor, "_on_ripple_delete_toggled"):
                editor._on_ripple_delete_toggled(bool(enabled))
            btn = getattr(editor, "_ripple_btn", None)
            if btn is not None:
                btn.blockSignals(True)
                btn.setChecked(bool(enabled))
                btn.blockSignals(False)
        elif name == "set_preview_quality":
            q = kwargs.get("quality") or kwargs.get("value")
            if hasattr(editor, "set_user_preview_quality"):
                editor.set_user_preview_quality(q)
            else:
                return {"ok": False, "action": name, "message": "无 set_user_preview_quality"}
        elif name == "toggle_proxy":
            if hasattr(editor, "set_proxy_preview_enabled"):
                cur = bool(getattr(editor, "_proxy_preview_enabled", True))
                editor.set_proxy_preview_enabled(not cur)
            else:
                return {"ok": False, "action": name, "message": "无代理开关"}
        return {"ok": True, "action": name, "message": "ok"}
    except Exception as e:
        logger.warning("dispatch_editor_action(%s) 失败: %s", name, e)
        return {"ok": False, "action": name, "message": str(e)}


def bind_action(editor: Any, action: str, **fixed_kwargs) -> Callable[[], None]:
    """生成无参回调，供 QPushButton / QShortcut 绑定。"""

    def _cb(*_args, **_kw):
        dispatch_editor_action(editor, action, **fixed_kwargs)

    return _cb
