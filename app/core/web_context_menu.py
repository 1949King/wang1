# -*- coding: utf-8 -*-
"""把 QtWebEngine 的英文右键菜单换成中文（2026-11-12）。

## 为什么用「应用级事件过滤器」而不是改画布模块

创建 `QWebEngineView` 的 `character_management_module.py` 与画布 `nodes.tsx`/`CanvasShell.tsx`
都在冻结区（未授权解冻不可改）。所以这里不改它们，而是在 QApplication 上装一个事件过滤器：
右键事件先到过滤器，我们弹自己的中文 QMenu 并 `return True`，默认英文菜单就不会出现。

## 保留哪些项（跟浏览器习惯对齐）

返回 / 前进 / 刷新 / 保存网页 · 图片：保存图片 / 复制图片 / 复制图片地址 ·
媒体：复制媒体地址 / 播放或暂停 · 链接：打开链接 / 复制链接地址 · 编辑：剪切/复制/粘贴/全选。

全部映射到 Qt 自带的 WebAction，不自己造下载逻辑（避免权限/路径/编码问题）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("AI短剧编辑器.web_context_menu")  # 与项目其他模块一致，日志才进文件

#: 纯函数产出的菜单项（便于单测）：(action_key, 中文标签)
LABELS = {
    "back": "返回",
    "forward": "前进",
    "reload": "刷新",
    "save_page": "保存网页…",
    "open_link": "打开链接",
    "copy_link": "复制链接地址",
    "save_image": "保存图片…",
    "copy_image": "复制图片",
    "copy_image_url": "复制图片地址",
    "copy_media_url": "复制媒体地址",
    "toggle_play": "播放 / 暂停",
    "cut": "剪切",
    "copy": "复制",
    "paste": "粘贴",
    "select_all": "全选",
}

#: 菜单分组（空行分隔）
GROUPS: List[List[str]] = [
    ["back", "forward", "reload", "save_page"],
    ["open_link", "copy_link"],
    ["save_image", "copy_image", "copy_image_url"],
    ["copy_media_url", "toggle_play"],
    ["cut", "copy", "paste", "select_all"],
]


def build_menu_items(info: Dict[str, Any]) -> List[List[Tuple[str, str]]]:
    """根据上下文决定显示哪些项。

    参数 info：
      - `has_link`: bool        右键点在链接上
      - `media`: str|None        "image" / "video" / "audio"
      - `editable`: bool         可编辑区域
      - `has_selection`: bool    有选中文本
    返回分组列表，每组是 (key, label)；空组会被剔除。
    """
    allow = {"back", "forward", "reload", "save_page"}
    if info.get("has_link"):
        allow |= {"open_link", "copy_link"}
    media = str(info.get("media") or "")
    if media == "image":
        allow |= {"save_image", "copy_image", "copy_image_url"}
    elif media in ("video", "audio"):
        allow |= {"copy_media_url", "toggle_play"}
    if info.get("editable"):
        allow |= {"cut", "paste", "select_all"}
    if info.get("has_selection") or info.get("editable"):
        allow.add("copy")
    if info.get("editable") or info.get("has_selection"):
        allow.add("select_all")

    out: List[List[Tuple[str, str]]] = []
    for group in GROUPS:
        rows = [(k, LABELS[k]) for k in group if k in allow]
        if rows:
            out.append(rows)
    return out


# ── Qt 侧 ────────────────────────────────────────────────────


def _find_web_view(obj: Any):
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    node = obj
    for _ in range(8):
        if node is None:
            return None
        if isinstance(node, QWebEngineView):
            return node
        node = node.parent()
    return None


def _request_info(request: Any) -> Dict[str, Any]:
    if request is None:
        return {"has_link": False, "media": None, "editable": False, "has_selection": False}
    try:
        from PyQt6.QtWebEngineCore import QWebEngineContextMenuRequest
    except Exception:  # stability-gate: allow-swallow（旧版本没有该枚举时按无媒体处理）
        QWebEngineContextMenuRequest = None  # type: ignore
    media = None
    try:
        mt = request.mediaType()
        if QWebEngineContextMenuRequest is not None:
            MT = QWebEngineContextMenuRequest.MediaType
            if mt == MT.MediaTypeImage:
                media = "image"
            elif mt == MT.MediaTypeVideo:
                media = "video"
            elif mt == MT.MediaTypeAudio:
                media = "audio"
    except Exception:  # stability-gate: allow-swallow（拿不到媒体类型就只给通用项）
        logger.debug("[web-menu] mediaType 读取失败", exc_info=True)
    try:
        has_link = bool(request.linkUrl().isValid())
    except Exception:  # stability-gate: allow-swallow（链接判定失败按无链接处理）
        has_link = False
    try:
        editable = bool(request.isContentEditable())
    except Exception:  # stability-gate: allow-swallow（编辑态判定失败按只读处理）
        editable = False
    try:
        has_sel = bool(str(request.selectedText() or "").strip())
    except Exception:  # stability-gate: allow-swallow（选区读取失败按无选区处理）
        has_sel = False
    return {"has_link": has_link, "media": media, "editable": editable, "has_selection": has_sel}


def _trigger(view: Any, key: str) -> None:
    from PyQt6.QtWebEngineCore import QWebEnginePage

    WA = QWebEnginePage.WebAction
    mapping = {
        "back": WA.Back,
        "forward": WA.Forward,
        "reload": WA.Reload,
        "save_page": WA.SavePage,
        "copy_link": WA.CopyLinkToClipboard,
        "save_image": WA.DownloadImageToDisk,
        "copy_image": WA.CopyImageToClipboard,
        "copy_image_url": WA.CopyImageUrlToClipboard,
        "copy_media_url": WA.CopyMediaUrlToClipboard,
        "toggle_play": WA.ToggleMediaPlayPause,
        "cut": WA.Cut,
        "copy": WA.Copy,
        "paste": WA.Paste,
        "select_all": WA.SelectAll,
    }
    page = view.page()
    if key == "open_link":
        try:
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices

            req = page.lastContextMenuRequest()
            QDesktopServices.openUrl(QUrl(req.linkUrl()))
            return
        except Exception:  # stability-gate: allow-swallow（打开链接失败不弹错，菜单已关）
            logger.debug("[web-menu] 打开链接失败", exc_info=True)
            return
    act = mapping.get(key)
    if act is not None:
        page.triggerAction(act)


class ChineseContextMenuFilter:
    """QApplication 事件过滤器（鸭子类型，避免 import Qt 时崩在无 GUI 环境）。"""

    def __new__(cls, *args: Any, **kwargs: Any):
        raise TypeError("use install_chinese_context_menu() / _make_filter()")


def _make_filter(): 
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QApplication, QMenu

    class _Filter(QObject):
        def eventFilter(self, obj, event):  # noqa: N802（Qt 命名）
            try:
                if event.type() != QEvent.Type.ContextMenu:
                    return False
                view = _find_web_view(obj)
                if view is None:
                    return False
                req = view.page().lastContextMenuRequest()
                groups = build_menu_items(_request_info(req))
                if not groups:
                    return True
                menu = QMenu(view)
                for gi, group in enumerate(groups):
                    if gi > 0:
                        menu.addSeparator()
                    for key, label in group:
                        act = menu.addAction(label)
                        act.triggered.connect(lambda _=False, k=key, v=view: _trigger(v, k))
                # 2026-11-12 稳定性：**不能在事件过滤器里 exec()**（嵌套事件循环），
                # 实测会让 Qt6WebEngineCore 抛 0xc0000005 崩溃。改成非阻塞 popup。
                menu.popup(event.globalPos())
                view._sg_ctx_menu = menu  # type: ignore[attr-defined]  持引用防 GC
                try:
                    menu.aboutToHide.connect(menu.deleteLater)
                except Exception:  # stability-gate: allow-swallow（连接失败不影响菜单可用）
                    logger.debug("[web-menu] aboutToHide 连接失败", exc_info=True)
                return True
            except Exception:  # stability-gate: allow-swallow（菜单异常不得影响画布渲染）
                logger.debug("[web-menu] 右键菜单构建失败", exc_info=True)
                return False

    return _Filter(QApplication.instance())


def install_chinese_context_menu(app: Any) -> bool:
    """在 QApplication 上安装过滤器；失败返回 False（不阻断启动）。"""
    try:
        import os

        # 2026-11-13：**默认关闭**。QtWebEngine 里 popup() 的 QMenu 在部分场景不消失，
        # 多个菜单会以"黑色方块"堆在画面上、并抓住输入导致 AppHangTransient。
        # 右键菜单统一改由前端（React）接管，需要 Qt 菜单时显式设 SHIGUANG_QT_CTX_MENU=1。
        if str(os.environ.get("SHIGUANG_QT_CTX_MENU", "0")).strip() != "1":
            logger.info("[web-menu] Qt 右键菜单默认关闭（改用前端中文菜单）；需要时设 SHIGUANG_QT_CTX_MENU=1")
            return False
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  依赖探测

        filt = _make_filter()
        app.installEventFilter(filt)
        # 保持引用，防止被 GC（PyQt 不持有 Python 侧强引用）
        app._shiguang_ctx_menu_filter = filt  # type: ignore[attr-defined]
        logger.info("[web-menu] 已启用中文右键菜单（%s）", type(filt).__name__)
        return True
    except Exception:  # stability-gate: allow-swallow（WebEngine 不可用时静默跳过）
        logger.warning("[web-menu] 安装失败（右键仍是英文）", exc_info=True)
        return False