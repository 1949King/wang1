# -*- coding: utf-8 -*-
"""首启免责提示的 Qt 弹窗（文本与状态逻辑见 `app/core/first_run_notice.py`）。

为什么用 QMessageBox 而不是自绘卡片
===================================
项目不变量 #8：**内联样式是主题盲区**（每新增一个 `setStyleSheet` 内联控件，
都得回头在 `set_theme()` 里补刷新）。这是启动期的一次性告知，不值得引入新的主题维护点；
QMessageBox 走系统/QSS 主题，深色浅色都正常。

行为约定
========
· 只有用户**明确点了「我已阅读并知晓」**才写入已确认状态；
  直接关窗（X）视为未确认 ⇒ 下次启动**会再提示**（这是免责告知，宁可重复一次）。
· 任何异常都不阻断启动（返回 False，交由调用方继续）。
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _to_html(text: str) -> str:
    """把极简 markdown（``**粗体**``）转成 QMessageBox 能渲染的 HTML。

    先转义 HTML 特殊字符，避免正文里的 ``<`` 之类被当成标签。
    """
    safe = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return "<div style='white-space:pre-wrap'>" + safe + "</div>"


def show_first_run_notice(parent=None, *, force: bool = False) -> bool:
    """需要时弹出首启免责提示（``force=True`` 用于「帮助」里再次查看）。

    返回**是否弹出过**。异常一律吞掉并返回 False（绝不阻断启动）。
    """
    try:
        from app.core import first_run_notice as frm

        if not force and not frm.should_show():
            return False

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QMessageBox

        box = QMessageBox(parent)
        box.setWindowTitle(frm.NOTICE_TITLE)
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)   # 正文里有 **粗体** 转换出的 HTML
        box.setText(_to_html(frm.full_text()))
        ack_btn = box.addButton("我已阅读并知晓", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(ack_btn)
        box.exec()
        if box.clickedButton() is ack_btn:
            frm.mark_acknowledged()
            logger.info("[first_run_notice] 用户已确认首启免责提示（v%d）", frm.NOTICE_VERSION)
        else:
            logger.info("[first_run_notice] 未确认（关闭窗口）⇒ 下次启动会再提示")
        return True
    except Exception as e:
        logger.warning("[first_run_notice] 提示弹窗异常（不阻断启动）: %s", e)
        return False


def notice_text() -> str:
    """供「帮助」等入口再次查看时取正文（无 Qt 依赖）。"""
    from app.core import first_run_notice as frm

    return frm.full_text()
