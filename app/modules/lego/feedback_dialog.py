"""
意见反馈对话框 (FeedbackDialog)
=============================

P1 主应用个人中心面板第 4 段「意见反馈」入口。用户点 UserCenterPanel 底部或
NotificationCenterPanel 底部的「意见反馈」按钮后会弹这个对话框。

提交路径（V4.42.1）：
- 必走：本地持久化（NotificationStore.feedback 类型 + 通知中心可见）
- 选走：Webhook POST（若 QSettings 配置了 feedback/webhook_url）
- 兜底：System 通道留本地记录（即使 webhook 失败也告诉 UI 已记录）

不做：
- 不上传文件/截图（V4.42.x 内不开放）
- 不做富文本/HTML
- 不重写 alert_system 的现有行为
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Optional

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QComboBox, QLineEdit, QTextEdit, QDialogButtonBox,
)

from app.core.notification_store import (
    notification_store, TYPE_FEEDBACK, LEVEL_SUCCESS, LEVEL_WARNING,
)

logger = logging.getLogger("AI短剧编辑器.feedback")


# QSettings 键（V4.42.1 起；将来若挪到 settings_module 的设置项里，键保持兼容）
WEBHOOK_KEY = "feedback/webhook_url"
WEBHOOK_TIMEOUT = 10  # 秒

# UI 选项
CATEGORY_OPTIONS = [
    ("问题反馈", "遇到使用上不理解的地方"),
    ("功能建议", "希望未来加入某个能力"),
    ("Bug 报告", "程序崩溃 / 异常行为"),
    ("内容合规", "发现不合适的内容"),
    ("其他",       "不属于上面任何一类"),
]

SEVERITY_OPTIONS = [
    ("普通", "普通",   LEVEL_SUCCESS),
    ("重要", "重要",   LEVEL_WARNING),
    ("紧急", "紧急",   LEVEL_WARNING),  # 同时标 warning
]

MIN_BODY_LENGTH = 5
MAX_BODY_LENGTH = 2000


def _read_webhook_url() -> Optional[str]:
    """从 QSettings 读 webhook URL，未配置返回 None"""
    try:
        s = QSettings()
        url = s.value(WEBHOOK_KEY, "", type=str)
        url = (url or "").strip()
        return url if url else None
    except Exception as e:
        logger.debug("读取 feedback webhook_url 失败: %s", e)
        return None


class FeedbackDialog(QDialog):
    """意见反馈对话框（模态）"""

    submitted = Signal(dict)  # {"category":..., "severity":..., "body":..., "email":...}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("feedbackDialog")
        self.setWindowTitle("意见反馈")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setMinimumHeight(420)

        self._build_ui()
        self._wire_signals()

    # ─────────── UI ───────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        # 标题
        title = QLabel("提交反馈", self)
        title.setObjectName("feedbackTitle")
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        outer.addWidget(title)

        subtitle = QLabel(
            "反馈会先写到本地的通知中心，配置了 Webhook URL 也会同步上传。",
            self,
        )
        subtitle.setObjectName("feedbackSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        # ── 表单区 ──
        form_box = QFrame(self)
        form_box.setObjectName("feedbackForm")
        form_layout = QVBoxLayout(form_box)
        form_layout.setContentsMargins(12, 12, 12, 12)
        form_layout.setSpacing(10)

        # 类别
        cat_row = QHBoxLayout()
        cat_label = QLabel("类别", self)
        cat_label.setFixedWidth(80)
        cat_row.addWidget(cat_label)
        self._category_combo = QComboBox(self)
        for label_text, _hint in CATEGORY_OPTIONS:
            self._category_combo.addItem(label_text)
        cat_row.addWidget(self._category_combo, 1)
        form_layout.addLayout(cat_row)

        # 严重程度
        sev_row = QHBoxLayout()
        sev_label = QLabel("严重程度", self)
        sev_label.setFixedWidth(80)
        sev_row.addWidget(sev_label)
        self._severity_combo = QComboBox(self)
        for label_text, _hint, _level in SEVERITY_OPTIONS:
            self._severity_combo.addItem(label_text)
        self._severity_combo.setCurrentIndex(0)
        sev_row.addWidget(self._severity_combo, 1)
        form_layout.addLayout(sev_row)

        # 邮箱（选填）
        email_row = QHBoxLayout()
        email_label = QLabel("联系邮箱", self)
        email_label.setFixedWidth(80)
        email_row.addWidget(email_label)
        self._email_edit = QLineEdit(self)
        self._email_edit.setPlaceholderText("选填，留空则匿名")
        email_row.addWidget(self._email_edit, 1)
        form_layout.addLayout(email_row)

        # 描述（必填）
        body_label = QLabel("详细描述 *", self)
        form_layout.addWidget(body_label)
        self._body_edit = QTextEdit(self)
        self._body_edit.setPlaceholderText(
            "请尽量描述清楚：场景、操作步骤、期望结果、实际结果。\n"
            "不少于 5 个字符。"
        )
        self._body_edit.setMinimumHeight(140)
        form_layout.addWidget(self._body_edit, 1)

        outer.addWidget(form_box, 1)

        # ── 底部按钮 ──
        self._button_box = QDialogButtonBox(self)
        self._button_box.setStandardButtons(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.button(QDialogButtonBox.StandardButton.Ok).setText("提交")
        self._button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        outer.addWidget(self._button_box)

        # 状态条（提交时显示）
        self._status_label = QLabel("", self)
        self._status_label.setObjectName("feedbackStatus")
        self._status_label.setWordWrap(True)
        self._status_label.hide()
        outer.addWidget(self._status_label)

    def _wire_signals(self):
        self._button_box.accepted.connect(self._on_submit)
        self._button_box.rejected.connect(self.reject)
        self._body_edit.textChanged.connect(self._update_status)

    def _update_status(self):
        text = self._body_edit.toPlainText().strip()
        ok_enabled = len(text) >= MIN_BODY_LENGTH
        self._button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok_enabled)

    # ─────────── 提交 ───────────
    def _on_submit(self):
        body = self._body_edit.toPlainText().strip()
        if len(body) < MIN_BODY_LENGTH:
            self._show_status(f"描述至少 {MIN_BODY_LENGTH} 个字符", LEVEL_WARNING)
            return

        category = self._category_combo.currentText()
        severity_label = self._severity_combo.currentText()
        # 找 severity 对应的 LEVEL_* 键
        severity_level = LEVEL_SUCCESS
        for label_text, _hint, level in SEVERITY_OPTIONS:
            if label_text == severity_label:
                severity_level = level
                break
        email = self._email_edit.text().strip()

        payload = {
            "category": category,
            "severity": severity_label,
            "body": body,
            "email": email,
            "submitted_at": time.time(),
        }

        # 1) 永远先写本地通知中心
        ns = notification_store()
        title = f"{category} · {severity_label}"
        if email:
            title += f" ({email})"
        ns.notify(
            title=title,
            body=body[:MAX_BODY_LENGTH],
            type=TYPE_FEEDBACK,
            level=severity_level,
            metadata={"email": email, "severity": severity_label},
        )

        # 2) 选走 Webhook（如有配置）
        webhook_url = _read_webhook_url()
        webhook_ok = None
        if webhook_url:
            webhook_ok = self._post_webhook(webhook_url, payload)
            # 把 webhook 状态写到通知 metadata 里
            all_notifs = ns.list(type=TYPE_FEEDBACK, only_unread=False, limit=1)
            if all_notifs:
                all_notifs[0].metadata["webhook_url"] = webhook_url[:80]
                all_notifs[0].metadata["webhook_ok"] = bool(webhook_ok)

        # 3) UI 反馈 + 关弹窗
        if webhook_url and webhook_ok is False:
            self._show_status(
                f"已记录到本地通知，但 Webhook 上传失败（{webhook_url[:60]}）",
                LEVEL_WARNING,
            )
            # 不关闭弹窗，让用户看到状态
            return

        self.submitted.emit(payload)
        self.accept()

    def _post_webhook(self, url: str, payload: dict) -> Optional[bool]:
        """POST 到 webhook。返回 True/False/None（None=网络异常）"""
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
                ok = 200 <= resp.status < 300
                logger.info("feedback webhook 上传 %s status=%s", url, resp.status)
                return ok
        except urllib.error.HTTPError as e:
            logger.warning("feedback webhook HTTP 错误: %s", e)
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning("feedback webhook 网络异常: %s", e)
            return None
        except Exception as e:
            logger.exception("feedback webhook 未知异常: %s", e)
            return False

    def _show_status(self, text: str, _level: str):
        self._status_label.setText(text)
        self._status_label.show()


__all__ = ["FeedbackDialog", "WEBHOOK_KEY"]