# -*- coding: utf-8 -*-
"""设置 · 团队协作页（2026-11-02 · V4.49.2）

## 为什么单独成文件（不是顺手塞进 settings_module.py）

`settings_module.py` 已被单文件规模守卫盯住：基线 **2823 行 / 容差 30**，
实测 2850 —— 只剩 3 行余量。本页要讲「怎么用」，正文本身就长，塞进去必红。
按项目既有先例（`teamPanel.css` / `canvasTierSeg.tsx`）单独成文件，
settings 里只留一行导航项 + 一个三行转发方法。

## 内容纪律

· 只写「点哪里、填什么、看到什么」，不写原理；
· 报错一律给「下一步该做什么」，不给错误码当答案；
· 安全边界必须写清（这是唯一会被同事连的端口）。
"""
from __future__ import annotations

import html
import logging
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_TITLE_QSS = "font-size: 18px; font-weight: 600; color: #ffffff;"
_DESC_QSS = "color: #999999; font-size: 13px;"
_STEP_QSS = "color: #cccccc; font-size: 13px;"
_KEY_QSS = "color: #6ea8ff; font-size: 13px; font-weight: 600;"
_DIM_QSS = "color: #8a8a8a; font-size: 12px;"
#: 分组框标题默认继承调色板，在深底上偏暗（实机截图确认过）⇒ 显式给色。
_GROUP_QSS = (
    "QGroupBox { color: #e6e9ef; font-size: 13px; font-weight: 600;"
    " border: 1px solid #2a2f3a; border-radius: 8px; margin-top: 10px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #9fb4d8; }"
)


def _label(text: str, qss: str = _STEP_QSS, wrap: bool = True) -> QLabel:
    """`**粗体**` → 真加粗。

    🔴 2026-11-02 实机截图发现：直接塞 PlainText 会把 `**挑一台电脑**` 原样画到界面上。
    """
    body = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", html.escape(text))
    lb = QLabel(body)
    lb.setStyleSheet(qss)
    lb.setWordWrap(wrap)
    lb.setTextFormat(Qt.TextFormat.RichText)
    return lb


def _group(title: str, rows: list) -> QGroupBox:
    """每个小节 = 一个 QGroupBox，行内容自动换行、间距统一。"""
    box = QGroupBox(title)
    box.setStyleSheet(_GROUP_QSS)
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 16, 14, 12)
    v.setSpacing(7)
    for item in rows:
        if isinstance(item, str):
            v.addWidget(_label(item))
        else:
            v.addWidget(item)
    return box


def _action_grid() -> QWidget:
    """「四个按钮到底差在哪」—— 这张表是整页最该被记住的东西。"""
    holder = QWidget()
    grid = QGridLayout(holder)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(8)
    head = ["按钮", "做了什么", "什么时候点"]
    for col, text in enumerate(head):
        grid.addWidget(_label(text, _KEY_QSS, False), 0, col)
    rows = [
        ("上传当前画布", "把手上这个画布**新建**成一个共享项目（不动别人已有的）", "第一次把项目给大家看"),
        ("上传到此", "把当前画布**提交成这个项目的新版本**；版本号对不上会报冲突", "改完了要交回去"),
        ("拉取", "把服务器上的版本**覆盖**到本地（会二次确认）", "接手别人改过的版本"),
        ("认领 / 释放", "认领后 10 分钟内别人改不了（有锁图标）", "防止两人同时改顺手"),
        ("交接", "把项目指给某个同事，他会在「④ 交接给我的」里看到", "换班 / 换人接着做"),
    ]
    for r, (btn, what, when) in enumerate(rows, start=1):
        grid.addWidget(_label(btn, _KEY_QSS, False), r, 0)
        grid.addWidget(_label(what), r, 1)
        grid.addWidget(_label(when, _DIM_QSS), r, 2)
    grid.setColumnStretch(1, 3)
    grid.setColumnStretch(2, 2)
    return holder


def _open_panel(host: QWidget) -> None:
    """「打开团队面板」—— 复用主窗口那颗按钮的既有流程，不另造第二条通道。"""
    win = host.window()
    fn = getattr(win, "_on_team_btn_clicked", None)
    if callable(fn):
        fn()
        return
    # 拿不到主窗口时不静默：告诉用户唯一可靠的手工入口
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.information(
        host,
        "团队协作",
        "请点画布左侧导航栏的 👥 图标，或主程序右上角的「👥 团队」按钮。",
    )


def build_team_tab(host: QWidget) -> QWidget:
    """构建设置页「👥 团队协作」整页（内容较长 ⇒ 自带滚动）。"""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)

    body = QWidget()
    v = QVBoxLayout(body)
    v.setContentsMargins(20, 20, 20, 20)
    v.setSpacing(16)

    v.addWidget(_label("👥 团队协作", _TITLE_QSS))
    v.addWidget(_label(
        "一台电脑当「服务器」，其他人的电脑连它 —— 大家一起改同一个画布，"
        "谁在改、改到第几版、有没有人覆盖都会写清楚。全部在局域网内，不上传云端。",
        _DESC_QSS,
    ))

    v.addWidget(_group("① 第一次用：先决定谁当服务器", [
        "在同一间办公室 / 同一个 Wi-Fi 下，**挑一台电脑**当服务器（通常是配置最好的那台）。",
        "在那台机器上打开画布 → 点左侧导航栏的 👥 → 在「① 我当服务器」里点「启动团队服务」。",
        "启动后那一栏会显示一个地址，形如 http://192.168.1.4:18770 —— 把它发给同事，这就是他们要填的地址。",
        "只用一台机器自己试：先启动服务，再在「② 我连别人的团队」里把同一个地址填回去点「加入」，效果和两人协作一样。",
    ]))

    v.addWidget(_group("② 同事怎么加入", [
        "1. 打开画布 → 左侧导航栏点 👥（主程序右上角也有一个「👥 团队」按钮，点它会直接切到画布并弹出面板）。",
        "2. 在「② 我连别人的团队」里填两样东西：服务器地址（http://IP:18770）+ 自己的名字。",
        "3. 点「加入」。成功后标题会变成「已连接 · 你的名字 @ 地址」，下面多出「③ 共享项目」和「④ 交接给我的」。",
        "4. 不想手抄 IP 就点「扫描局域网」，扫到会自动填上地址；扫到多台会给你一个下拉框挑。",
    ]))

    v.addWidget(_group("③ 五个动作到底差在哪（最容易点错的地方）", [_action_grid()]))

    v.addWidget(_group("④ 一次完整协作长什么样", [
        "A：启动服务 → 加入 → 在 ③ 里点「上传当前画布」，项目就叫 A 的画布名字。",
        "B：加入 A 的地址 → 在 ③ 里选中那个项目 → 点「拉取」，本地就能看到 A 的画布。",
        "B 改完 → 点「上传到此」，服务器上变成第 2 版（rev 2）。",
        "A 想接着改 → 先「拉取」再改，否则上传时会提示冲突（并告诉你 B 改到了第几版）。",
        "要换人做：A 在 ③ 里选中项目 → 选「交接给…」挑 B → 点「交接」；B 在「④ 交接给我的」点「接手」，画布自动换成最新版。",
    ]))

    v.addWidget(_group("⑤ 报错对照表：看到什么 → 该做什么", [
        "「没扫到服务器」→ 对方没点「启动团队服务」；或两台机器不在同一个 Wi-Fi/网段；或公司网络禁止广播 —— 直接让对把手上的地址复制给你手填。",
        "「拒绝连接」/ 10061 → 地址或端口不对，或对方服务已经停了。确认地址末尾是 **:18770**，让对方重新启动一次。",
        "「端口已占用」/ 10048 → 这台机器上已经有一个团队服务在跑。要么直接用它，要么换台机器当服务器。",
        "「连接超时」/ 10060 → 两台机器不在同一个网段（比如一台连 Wi-Fi 一台连网线走的不同网络），或防火墙拦住了 18770。",
        "「冲突：xx 改到第 N 版」→ 你手上的版本旧了。先「拉取」，再重新改、重新「上传到此」。",
        "「锁在 xx 手上」→ 对方认领了还没释放。让他点「释放」，或者等 10 分钟自动过期。",
        "「连不上本机画布桥」→ 主程序刚重启或画布崩了。关掉画布重新打开，再点一次 👥。",
    ]))

    v.addWidget(_group("⑥ 安全边界（必须知道）", [
        "团队服务只给**同一个局域网**用。不要把 18770 端口映射到公网、也不要在外面咖啡馆的公共 Wi-Fi 上随便开会话。",
        "拿到地址 + 加入成功的人，就能看、能改所有共享项目 —— 「名字」只是显示用的标签，不是账号密码。",
        "项目数据存在**服务器那台机器**的 data/team 目录里。那台机器关掉或目录被删，共享项目就没了（本地画布不受影响）。",
        "不用了就「停止团队服务」，端口随即关闭。",
    ]))

    btn_row = QWidget()
    row = QVBoxLayout(btn_row)
    row.setContentsMargins(0, 4, 0, 0)
    open_btn = QPushButton("打开团队面板（切到画布）")
    open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    open_btn.setFixedHeight(34)
    open_btn.setStyleSheet(
        "QPushButton { background: #1e6bde; color: #ffffff; border: none;"
        " border-radius: 8px; padding: 6px 18px; font-size: 13px; }"
        "QPushButton:hover { background: #2b7bef; }"
    )
    open_btn.clicked.connect(lambda: _open_panel(host))
    row.addWidget(open_btn)
    v.addWidget(btn_row)

    v.addStretch(1)
    scroll.setWidget(body)
    outer.addWidget(scroll)
    return page
