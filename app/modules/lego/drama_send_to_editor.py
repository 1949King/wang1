# -*- coding: utf-8 -*-
"""M6：短剧选题 → 剪辑时间线（最小回流）。

不改冻结区 drama_ui.py：由拓展中心对话框外挂「发送到剪辑」。
不自动精剪、不走 DRAMA_SELECTED / workflow。
无本地成片则诚实失败（可选手选文件）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_PATH_KEYS = ("local_path", "video_path", "path", "file_path", "media_path")


def resolve_local_media_path(item: Optional[Dict[str, Any]]) -> Tuple[Optional[str], str]:
    """
    从选题 dict 解析本地成片路径（纯数据，无 UI）。

    返回 (path, error)。成功时 error 为空串。
    """
    if not item or not isinstance(item, dict):
        return None, "未选中短剧条目"
    title = (item.get("title") or "").strip() or "未命名选题"
    for key in _PATH_KEYS:
        raw = item.get(key)
        if not raw:
            continue
        path = os.path.abspath(str(raw).strip())
        if os.path.isfile(path):
            return path, ""
        return None, f"选题「{title}」的 {key} 无效或文件不存在：\n{path}"
    return None, (
        f"选题「{title}」没有本地成片路径（仅有标题/平台等元数据）。\n"
        "请选择本机视频文件发送到剪辑，或取消。"
    )


def emit_send_to_editor(file_path: str, *, title: str = "", source: str = "drama_finder") -> Dict[str, Any]:
    """切换到剪辑模块并推送素材到时间线（EventBus）。"""
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        return {
            "success": False,
            "message": f"视频文件不存在：\n{path}",
            "file_path": path,
        }
    try:
        from app.modules.lego.core import EventBus, EventType
    except ImportError:
        from modules.lego.core import EventBus, EventType  # type: ignore

    bus = EventBus.get_instance()
    bus.emit(
        EventType.MODULE_ACTIVATED,
        {
            "target": "editor",
            "hint": f"选题已发送到剪辑：{title or os.path.basename(path)}",
            "source": source,
        },
        source=source,
    )
    bus.emit(
        EventType.MATERIAL_TO_TIMELINE,
        {"file_path": path, "title": title, "source": source},
        source=source,
    )
    return {
        "success": True,
        "message": f"已发送到剪辑：{os.path.basename(path)}",
        "file_path": path,
        "title": title,
    }


def send_drama_item_to_editor(
    item: Optional[Dict[str, Any]],
    parent=None,
    *,
    pick_file_if_missing: bool = True,
) -> Dict[str, Any]:
    """
    UI 入口：解析路径 → 可选文件对话框 → EventBus 写入剪辑时间线。

    不下载、不精剪。取消选文件视为 cancelled，非假成功。
    """
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    path, err = resolve_local_media_path(item)
    title = ""
    if isinstance(item, dict):
        title = (item.get("title") or "").strip()

    if not path and pick_file_if_missing:
        # 诚实：元数据无成片，请用户指定本地文件
        if err:
            QMessageBox.information(
                parent,
                "发送到剪辑",
                err + "\n\n下一步将打开文件选择对话框。",
            )
        picked, _ = QFileDialog.getOpenFileName(
            parent,
            f"为选题选择本地视频 — {title or '未命名'}",
            "",
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*.*)",
        )
        if not picked:
            return {
                "success": False,
                "cancelled": True,
                "message": "用户取消选择文件，未发送到剪辑",
            }
        path = os.path.abspath(picked)
        if not os.path.isfile(path):
            QMessageBox.warning(parent, "发送到剪辑", f"所选文件不存在：\n{path}")
            return {"success": False, "message": "所选文件不存在", "file_path": path}

    if not path:
        QMessageBox.warning(parent, "发送到剪辑", err or "无法解析本地成片路径")
        return {"success": False, "cancelled": False, "message": err or "无路径"}

    result = emit_send_to_editor(path, title=title, source="drama_finder")
    if result.get("success"):
        QMessageBox.information(
            parent,
            "已发送到剪辑",
            f"选题「{title or os.path.basename(path)}」已加入时间线。\n\n"
            f"{path}\n\n（未自动精剪；可在剪辑模块继续编辑。）",
        )
    else:
        QMessageBox.warning(parent, "发送失败", result.get("message") or "未知错误")
    return result


def send_selected_drama_to_editor(drama_widget, parent=None) -> Dict[str, Any]:
    """从 DramaFinderWidget._selected 发送；未选中则诚实失败。"""
    from PyQt6.QtWidgets import QMessageBox

    selected = getattr(drama_widget, "_selected", None) if drama_widget is not None else None
    if not selected:
        QMessageBox.information(
            parent,
            "发送到剪辑",
            "请先在左侧点选一部短剧，再点「发送到剪辑」。",
        )
        return {"success": False, "message": "未选中短剧条目"}
    return send_drama_item_to_editor(selected, parent=parent or drama_widget)
