# -*- coding: utf-8 -*-
"""关于页「代表形象 · 拾岚」卡片（2026-10-20）。

为什么要单独一个文件
====================
`settings_module.py` 已 2800+ 行，受单文件规模守卫（2000 行阈值、存量只减不增）
约束。把这张卡拆出来，`settings_module` 只留「import + 一行调用」，
不推高上帝类债务。规范见 `docs/design/拾岚形象规范.md`。

设计约束
========
1. 主形象卡**只做展示、不做交互**（品牌位，不是按钮）；
2. 素材缺失时返回 None，调用方整卡不渲染 —— **诚实失败，不占位假图**；
3. 配色沿用关于页既有的深色卡片体系（#171b2b → #1d1526 渐变 + #2a2f3a 描边）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

#: 主形象卡母版（assets/mascot/ 只增不改）。
MASCOT_CARD_PATH = (
    Path(__file__).resolve().parents[3]
    / "assets"
    / "mascot"
    / "shilan-主形象卡-v3-成年比例.png"
)


def build_about_mascot_card() -> QFrame | None:
    """构建关于页的代表形象卡；素材缺失或读图失败时返回 None。"""
    if not MASCOT_CARD_PATH.is_file():
        return None

    card = QFrame()
    card.setObjectName("aboutMascot")
    # 定高：关于页的根 QVBoxLayout 会把多余高度分给未定高的子项，
    # 不定高会让这张卡被拉成一整块空白（2026-10-20 截图实测）。
    card.setFixedHeight(172)
    card.setStyleSheet(
        "QFrame#aboutMascot {"
        "  background: qlineargradient(x1:0 y1:0, x2:1 y2:1,"
        "    stop:0 #171b2b, stop:1 #1d1526);"
        "  border: 1px solid #2a2f3a; border-radius: 14px;"
        "}"
    )
    layout = QHBoxLayout(card)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(18)

    portrait = QLabel()
    portrait.setFixedSize(96, 144)
    portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
    portrait.setStyleSheet("background: transparent; border: none;")
    pixmap = QPixmap(str(MASCOT_CARD_PATH))
    if pixmap.isNull():
        return None
    portrait.setPixmap(
        pixmap.scaled(
            96,
            144,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    layout.addWidget(portrait)

    info = QVBoxLayout()
    info.setSpacing(5)

    name = QLabel("拾岚 · Shilan")
    name.setStyleSheet(
        "font-size: 17px; font-weight: bold; color: #e6d3c2;"
        "background: transparent; border: none;"
    )
    info.addWidget(name)

    role = QLabel("拾光剪影 · 代表形象 / 导演台常驻小狐狸")
    role.setStyleSheet(
        "font-size: 11px; color: #8a8fa0; background: transparent; border: none;"
    )
    info.addWidget(role)

    desc = QLabel(
        "狐耳与蓝挑染是她的记号。画布右下角的小拾岚会随生成状态呼吸、眨眼、点头；"
        "她安静下来时，就是在等你回来。"
    )
    desc.setWordWrap(True)
    desc.setStyleSheet(
        "font-size: 11px; color: #a9b0c2; background: transparent; border: none;"
    )
    info.addWidget(desc)
    info.addStretch()
    layout.addLayout(info, 1)

    return card
