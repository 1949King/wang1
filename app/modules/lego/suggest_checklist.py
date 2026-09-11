# -*- coding: utf-8 -*-
"""通用「建议清单 → 勾选写入」对话框（Agent / FunClip / AutoClip 共用）。

纯函数可在无 Qt 的单测里跑；对话框只在活路径 UI 调用。
不新增 MCP 工具，不默认全链路成片。
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

_READ_ACTIONS = frozenset({"answer", "info"})

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPushButton,
        QVBoxLayout,
    )
except Exception:  # pragma: no cover
    Qt = None  # type: ignore
    QDialog = None  # type: ignore


def is_read_action(action: str) -> bool:
    return str(action or "") in _READ_ACTIONS


def partition_agent_commands(commands: Sequence[Any]) -> tuple[List[Any], List[Any]]:
    """拆成 (只读, 写时间线)。只读不进勾选清单，写操作默认待确认。"""
    reads: List[Any] = []
    writes: List[Any] = []
    for cmd in commands:
        action = getattr(cmd, "action", "") if not isinstance(cmd, dict) else cmd.get("action", "")
        if is_read_action(str(action)):
            reads.append(cmd)
        else:
            writes.append(cmd)
    return reads, writes


def merge_checked_commands(
    reads: Sequence[Any],
    writes: Sequence[Any],
    checked_indices: Sequence[int],
) -> List[Any]:
    """只读全保留 + 勾选的写指令。越界 index 忽略。"""
    picked: List[Any] = []
    n = len(writes)
    seen = set()
    for i in checked_indices:
        if not isinstance(i, int) or i < 0 or i >= n or i in seen:
            continue
        seen.add(i)
        picked.append(writes[i])
    return list(reads) + picked


def format_agent_command_label(cmd: Any, index: int) -> str:
    if isinstance(cmd, dict):
        action = str(cmd.get("action") or "unknown")
        desc = str(cmd.get("description") or "")
        params = cmd.get("params") or {}
    else:
        action = str(getattr(cmd, "action", "unknown") or "unknown")
        desc = str(getattr(cmd, "description", "") or "")
        params = getattr(cmd, "params", None) or {}
    extra = ""
    if isinstance(params, dict):
        if params.get("clip_index") == "all":
            extra = " · 全部片段"
        elif params.get("t_in") is not None or params.get("start_time") is not None:
            t_in = params.get("t_in", params.get("start_time"))
            t_out = params.get("t_out", params.get("end_time"))
            extra = f" · {t_in}–{t_out}"
    body = desc.strip() or action
    return f"{index}. {action} — {body}{extra}"


def pick_checked_indices(
    parent,
    *,
    title: str,
    hint: str,
    labels: Sequence[str],
    default_checked: bool = True,
    ok_text: str = "执行选中",
) -> Optional[List[int]]:
    """弹出勾选清单。None=取消；[]=确认但一项都没勾。"""
    if QDialog is None or Qt is None:
        raise RuntimeError("PyQt6 不可用")
    dlg = _SuggestChecklistDialog(
        parent,
        title=title,
        hint=hint,
        labels=labels,
        default_checked=default_checked,
        ok_text=ok_text,
    )
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.checked_indices()


class _SuggestChecklistDialog(QDialog):  # type: ignore[misc]
    def __init__(
        self,
        parent,
        *,
        title: str,
        hint: str,
        labels: Sequence[str],
        default_checked: bool,
        ok_text: str,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self.setMinimumHeight(320)
        root = QVBoxLayout(self)
        head = QLabel(hint)
        head.setWordWrap(True)
        root.addWidget(head)
        self._list = QListWidget()
        state = Qt.CheckState.Checked if default_checked else Qt.CheckState.Unchecked
        for i, label in enumerate(labels):
            item = QListWidgetItem(label)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(state)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)
        root.addWidget(self._list)
        tools = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("全不选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        tools.addWidget(btn_all)
        tools.addWidget(btn_none)
        tools.addStretch(1)
        root.addLayout(tools)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(ok_text)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(state)

    def checked_indices(self) -> List[int]:
        out: List[int] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return out
