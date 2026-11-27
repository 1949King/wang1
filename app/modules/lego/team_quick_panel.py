# -*- coding: utf-8 -*-
"""团队连接小窗 —— 任意模块都能开，不抢你的画布（2026-11-04）

它解决的那一件事
================
以前顶栏「👥 团队」只有一个行为：**切到画布模块**，再让画布里的 `TeamPanel` 弹出来
（`main_window.py::_on_team_btn_clicked`）。于是用户在剪辑器里想看一眼「同事连上没有」，
也会被连人带椅子搬到画布 —— 手上的上下文丢了。

但 `TeamPanel` 跟画布状态是硬绑的（`selectedId` 批注锚点、`getProjectBundle()` 上传、
`loadProjectBundle()` 拉取、`setSelected()` 定位），搬到独立窗口 = 窗口里再跑一个画布，
既慢又会和主画布抢同一份数据。**所以不是整体搬，是把面板拆成两半：**

    · **连接层**（本文件）—— 起服务 / 出码 / 加入 / 扫描 / 看谁在线。
      这些**根本不需要画布**，凭什么非得进画布才能做？
    · **内容层**（画布里的 `TeamPanel`）—— 上传、拉取、版本、批注、评审。
      这些真的要画布上下文，留在原处。

「不制造第二套状态机」这条纪律仍然成立：本文件**不存任何团队状态**，每一个数字都是
现问本机桥（`127.0.0.1:<canvas_bridge>` 的 `/host/team/*`）或现问对端 hub（`/team/*`）
拿回来的。唯一留在内存里的是 `owner` 令牌 —— 那是**本机主人**打自己服务用的凭据，
和画布里那份是同一个（都来自 `team_hub.ensure_owner`），不是第二份真相。

纪律（踩过的坑，别重犯）
========================
· **网络一律不阻塞 UI**：全部走 `_Req(QThread)`，结果用 signal 回主线程。
  `urllib` 在主线程里 4 秒超时 = 界面假死 4 秒。
· **错误必须翻人话**：`friendly_socket_error` 是本项目既有的翻译层（`team_discovery.py:58`），
  别在这里另写一套；连不上就说「对方没在跑团队服务」，不要「网络错误，请稍后重试」。
· **线程对象要留引用**：`QThread` 被 GC 掉会让进程直接崩（Qt 的经典坑），所以存 `_threads`。
· **不写内联颜色**：主题真相源是 `theme_tokens`；这里只 setProperty("theme") +
  unpolish/polish，和 `user_center_panel.py::_apply_theme` 保持一致。
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 4.0

# 🔴 必须禁用代理：团队请求全部打向 127.0.0.1（画布桥）或局域网对端（192.168.x.x），
# 但 `urllib.request.urlopen` 默认会读环境变量/注册表里的系统代理，把这些**本该直连**的
# 地址也丢给代理 —— 代理不认识 127.0.0.1:18765，回一个 502，界面上就变成「对方返回了 502」。
# 2026-11-04 实机复现：环境里有 http_proxy=http://127.0.0.1:60630 时，小窗每一次请求都 502。
# 用 ProxyHandler({}) 显式清空代理表，只影响本模块的请求，不动全局 urllib 状态。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ═══════════════════════════════════════════════════════════════════
# 错误翻人话
# ═══════════════════════════════════════════════════════════════════

def friendly_error(exc: BaseException) -> str:
    """把请求失败翻成一句用户能照做的话。

    套接字层复用 `team_discovery.friendly_socket_error`（全库唯一碰 UDP/socket 的地方），
    这里只补 HTTP 语义 —— 同一件事不要有第二种说法。
    """
    if isinstance(exc, urllib.error.HTTPError):
        msg = ""
        try:
            msg = str(json.loads(exc.read().decode("utf-8")).get("message") or "")
        except Exception:
            logger.debug("读错误响应体失败", exc_info=True)
        if exc.code in (502, 503, 504):
            return ("对方返回了 %d —— 本机地址出现这个码，通常是系统代理把请求截走了；"
                    "关掉代理再试" % exc.code)
        return msg or "对方返回了 %d，没说原因" % exc.code

    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return "对方 %d 秒没回应 —— 确认在同一网络，且对方防火墙放行了这个端口" % int(_TIMEOUT)
        if isinstance(reason, ConnectionRefusedError):
            return "对方没有在跑团队服务 —— 让对方先点「启动团队服务」"
        try:
            from app.core.team_discovery import friendly_socket_error

            if isinstance(reason, OSError):
                return friendly_socket_error(reason)
        except Exception:
            logger.debug("翻套接字错误失败", exc_info=True)
        return "连不上：%s" % (reason or exc)

    if isinstance(exc, TimeoutError):
        return "对方 %d 秒没回应 —— 确认在同一网络，且对方防火墙放行了这个端口" % int(_TIMEOUT)
    return "%s: %s" % (type(exc).__name__, exc)


# ═══════════════════════════════════════════════════════════════════
# 请求线程
# ═══════════════════════════════════════════════════════════════════

class _Req(QThread):
    """一次 HTTP 往返，结果经 `done` 回主线程。"""

    done = Signal(dict)

    def __init__(
        self,
        method: str,
        url: str,
        body: Optional[Dict[str, Any]] = None,
        token: str = "",
        bearer: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._method = method
        self._url = url
        self._body = body
        self._token = token
        self._bearer = bearer

    def run(self) -> None:
        headers = {"Accept": "application/json"}
        data = None
        if self._body is not None:
            data = json.dumps(self._body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["X-Shiguang-Token"] = self._token
        if self._bearer:
            headers["Authorization"] = "Bearer " + self._bearer
        req = urllib.request.Request(self._url, data=data, headers=headers, method=self._method)
        try:
            with _OPENER.open(req, timeout=_TIMEOUT) as r:
                payload = json.loads(r.read().decode("utf-8") or "{}")
            self.done.emit({"ok": True, "data": payload})
        except Exception as e:
            self.done.emit({"ok": False, "message": friendly_error(e)})


# ═══════════════════════════════════════════════════════════════════
# 地址 / 码的解析
# ═══════════════════════════════════════════════════════════════════

_HOST_OK = re.compile(
    r"^(?:"
    r"(?:\d{1,3}\.){3}\d{1,3}"
    r"|\[[0-9A-Fa-f:]+\]"
    r"|[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9\-]+)+"
    r")(?::\d{1,5})?$"
)


def parse_invite(raw: str) -> Dict[str, str]:
    """把用户粘进来的东西认成「码 / 地址」—— 认不出就给一句为什么。

    与前端 `teamInvite.ts::parseInvite` 同一套判断顺序（码 → 带 ?code= 的链接 → 光地址），
    但这里只服务本小窗，不重复前端的完整校验逻辑。
    """
    s = (raw or "").strip().strip("\"'`<>")
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        s = s.replace(ch, "")
    s = s.rstrip("。.,，、;；")
    if not s:
        return {"kind": "none", "why": "还没填东西"}

    if re.fullmatch(r"\d{4,10}", s):
        return {"kind": "code", "code": s, "host": ""}

    # 全数字点分但段数不对 ⇒ 明确说「缺了一段」，别当域名去连。
    # 否则用户少打一段（192.168.1）会得到「连不上」，而真正的原因是地址本身不完整 ——
    # 报错要是能照做的，不能让人往防火墙方向查半天。
    probe = s.split("/")[0]
    if probe.count(":") == 1 and not probe.startswith("["):
        probe = probe.split(":")[0]
    if re.fullmatch(r"[\d.]+", probe) and probe.count(".") != 3:
        return {"kind": "none",
                "why": "地址像是少了一段 —— IPv4 要四段，比如 192.168.1.4:18770"}

    host, code = "", ""
    if "://" in s or "?" in s or "/" in s:
        try:
            u = urllib.parse.urlparse(s if "://" in s else "http://" + s)
            host = u.netloc or ""
            code = (urllib.parse.parse_qs(u.query).get("code") or [""])[0]
        except Exception:
            logger.debug("解析邀请链接失败", exc_info=True)
    if not host and _HOST_OK.match(s):
        return {"kind": "host", "host": s, "code": ""}
    if host and not _HOST_OK.match(host):
        return {"kind": "none", "why": "地址长这样认不出来（要 host:port，比如 192.168.1.4:18770）"}
    if host and code:
        return {"kind": "code", "host": host, "code": code}
    if host:
        return {"kind": "host", "host": host, "code": ""}
    if _HOST_OK.match(s):
        return {"kind": "host", "host": s, "code": ""}
    return {"kind": "none", "why": "认不出这是码还是地址（码是 4~10 位数字）"}


# ═══════════════════════════════════════════════════════════════════
# 小窗
# ═══════════════════════════════════════════════════════════════════

def _bridge_msg(raw: str) -> str:
    """本机桥的错误翻人话。

    `unauthorized` 是**一定会遇到**的一种：如果用户之前手动跑过 `canvas_server`
    独立进程（或上一次退出没清干净），现在盘在 18765 上的是**别的进程**，
    它的会话令牌和主程序这次生成的对不上 —— 表现就是这个 401。
    这时唯一有效的动作是「关掉它，从软件里重新打开画布」，不是「检查网络」。
    """
    low = (raw or "").lower()
    if "unauthorized" in low:
        return ("这个端口被别的进程占着（不是本次启动的画布服务，令牌对不上）。"
                "把那个进程关掉，再从软件里重新打开画布")
    return raw or "原因未知"


class TeamQuickPanel(QFrame):
    """团队连接小窗。任意模块都能弹，不切模块。"""

    # 用户点了「在画布中打开完整面板」—— 由 main_window 接住去做真正的跳转
    open_full_requested = Signal()

    PANEL_WIDTH = 392

    def __init__(self, theme_manager: Any = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tm = theme_manager
        self._threads: List[_Req] = []
        self._owner: Dict[str, Any] = {}
        self._address = ""
        self._members: List[Dict[str, Any]] = []
        # 加入成功后待注入画布的凭据（画布还没加载时先存这儿）
        self._pending_cred: Optional[Dict[str, str]] = None
        # 用户是否自己动过「服务器与加入」折叠 —— 动过之后一切听用户的，
        # 不再让 5 秒一次的 refresh 把它自己收起来/摊开。
        self._io_user = False
        # 上一次拉「等我做 / 项目」的时刻（秒）。refresh 是 5 秒一次，
        # 而这两块是给人看的、不是实时数据 ⇒ 节流到 12 秒，省两次往返。
        self._hub_at = 0.0
        # 加入别人的团队后**长期**留着的那份凭据。
        # 和 `_pending_cred` 分开：后者是「一次性交给画布」的过路货（`take_cred()` 会清空），
        # 而「等我做 / 项目」这两块每次刷新都要用它去问对端 hub。
        self._member_cred: Dict[str, str] = {}

        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setObjectName("teamQuickPanel")
        self.setFixedWidth(self.PANEL_WIDTH)
        self._build_ui()

        # 这三个按钮在行内是「按内容宽」，不是「撑满」——
        # 旁边的提示标签一隐藏，默认策略会让按钮撑满整行，看起来像个输入框。
        for _b in (self._code_btn, self._scan_btn, self._full_btn):
            _b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self._apply_theme()
        self.refresh()

        # 每 5 秒问一次状态：这里不缓存任何东西，全靠现问
        self._tick = QTimer(self)
        self._tick.setInterval(5000)
        self._tick.timeout.connect(self.refresh)

        # 盯两处：全局点击（点外面就关）+ 主人自己（主人收摊跟着收）
        if parent is not None:
            parent.installEventFilter(self)
        if QApplication.instance() is not None:
            QApplication.instance().installEventFilter(self)

    # ── 主题 ──────────────────────────────────────────
    def _apply_theme(self) -> None:
        """按主题令牌生成本面板样式。

        为什么必须在这里自己写：本面板是 `parent=None` 的独立 Popup 窗口，
        **不在主窗口 `setStyleSheet` 的作用域里** —— 全局 `QWidget[theme="dark"]`
        选择器够不到它，于是它会退回 Qt 原生浅灰底 + 方角灰按钮，在深色主界面上
        像一块贴上去的白纸（2026-11-04 实拍确认）。

        纪律：颜色一律取自 `theme_tokens`（主窗口用的是同一份），**不写死 hex**；
        `on_theme_changed` 会重调这里，所以切主题能跟着走。
        """
        theme = "dark"
        try:
            if self._tm and hasattr(self._tm, "get_current_theme"):
                theme = self._tm.get_current_theme() or "dark"
        except Exception as e:
            logger.debug("读取当前主题失败，默认 dark: %s", e)
        self.setProperty("theme", theme)

        colors: Dict[str, Any] = {}
        try:
            if self._tm and hasattr(self._tm, "get_colors"):
                colors = self._tm.get_colors() or {}
        except Exception:
            logger.debug("取主题颜色表失败", exc_info=True)
        if not colors:
            try:
                from app.core.theme_tokens import DARK_TOKENS, LIGHT_TOKENS

                colors = LIGHT_TOKENS if theme == "light" else DARK_TOKENS
            except Exception:
                logger.debug("回退读取 theme_tokens 失败", exc_info=True)

        def c(key: str, fallback: str) -> str:
            return str(colors.get(key) or fallback)

        self.setStyleSheet(
            """
            QFrame#teamQuickPanel {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QFrame#teamQuickPanel QLabel {{
                background: transparent;
                color: {tx};
            }}
            QLabel#teamQuickTitle {{ font-size: 13px; font-weight: 600; }}
            QLabel#teamQuickStatus {{ color: {tx2}; font-size: 11px; }}
            QLabel#teamQuickSec {{ color: {tx2}; font-size: 11px; }}
            QLabel#teamQuickMono {{
                color: {acc}; font-family: Consolas,"Courier New",monospace; font-size: 12px;
            }}
            QLabel#teamQuickHint {{ color: {mut}; font-size: 11px; }}
            QLabel#teamQuickCode {{ color: {acc}; font-size: 12px; font-weight: 600; }}
            QLabel#teamQuickMembers {{ color: {tx2}; font-size: 11px; }}
            QLabel#teamQuickLink {{ color: {tx}; font-size: 11px; }}
            /* 「等我做」用一条强调色竖线拉出来：它是首屏唯一要**动手**的块。
               「项目」用分隔色，同一条竖线但退到背景里。 */
            QLabel#teamQuickInbox {{
                color: {tx}; font-size: 11px;
                border-left: 2px solid {acc}; padding-left: 8px;
            }}
            QLabel#teamQuickProj {{
                color: {tx2}; font-size: 11px;
                border-left: 2px solid {sep}; padding-left: 8px;
            }}
            QPushButton#teamQuickFold {{
                background: transparent; border: none; text-align: left;
                padding: 2px 0; color: {tx2}; font-size: 11px;
            }}
            QPushButton#teamQuickFold:hover {{ color: {tx}; }}
            QLabel#teamQuickMsg {{ color: {tx2}; font-size: 11px; }}
            QLabel#teamQuickMsg[bad="true"] {{ color: {bad}; }}
            QFrame#teamQuickHr {{
                background-color: {sep}; border: none; max-height: 1px;
            }}
            QLineEdit {{
                background-color: {field};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px 9px;
                color: {tx};
                selection-background-color: {acc};
                selection-color: {onacc};
            }}
            QLineEdit:focus {{ border-color: {focus}; }}
            QPushButton {{
                background-color: {field};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 6px 12px;
                color: {tx};
            }}
            QPushButton:hover {{ background-color: {hover}; border-color: {acc}; }}
            QPushButton:pressed {{ background-color: {accsoft}; }}
            QPushButton[on="true"] {{
                background-color: {accsoft}; border-color: {acc}; color: {acc};
            }}
            QPushButton:disabled {{ color: {dis}; }}
            """.format(
                bg=c("bg_secondary", "#14141c"),
                border=c("card_border", "#2a2a3a"),
                tx=c("text_primary", "#dddde4"),
                tx2=c("text_secondary", "#8888a0"),
                mut=c("text_muted", "#7d7d91"),
                acc=c("accent", "#2f7bff"),
                onacc=c("text_on_accent", "#f8fbff"),
                sep=c("separator_color", "rgba(232,232,237,0.10)"),
                field=c("bg_tertiary", "#1a1a26"),
                hover=c("bg_hover", "#252535"),
                accsoft=c("accent_soft", "#102a4d"),
                focus=c("focus", "#6ba4ff"),
                bad=c("danger", "#ef4444"),
                dis=c("text_disabled", "#444455"),
            )
        )
        self.style().unpolish(self)
        self.style().polish(self)

    def on_theme_changed(self, _name: str = "") -> None:
        self._apply_theme()

    # ── 弹出 / 关闭 ────────────────────────────────────
    def popup_below(self, anchor: Optional[QWidget]) -> None:
        """挂在顶栏按钮正下方，右对齐；屏幕放不下就往上翻。"""
        if anchor is not None:
            g = anchor.mapToGlobal(QPoint(0, 0))
            x = g.x() + anchor.width() - self.PANEL_WIDTH
            y = g.y() + anchor.height() + 6
            screen = anchor.screen()
            if screen is not None:
                geo = screen.availableGeometry()
                x = max(geo.left() + 8, min(x, geo.right() - self.PANEL_WIDTH - 8))
                if y + self.sizeHint().height() > geo.bottom() - 8:
                    y = max(geo.top() + 8, g.y() - self.sizeHint().height() - 6)
            self.move(x, y)
        self.show()
        self.raise_()
        self.refresh()
        self._tick.start()

    def hide_panel(self) -> None:
        self._tick.stop()
        self.hide()

    def eventFilter(self, obj, ev):
        """两条来源、两件事：主人收摊就跟着收摊；点外面就关掉。

        方法名是 Qt 约定，不改 —— 改了就不被调用了。

        ⚠️ 为什么非要在这里监听父窗口：`Qt.WindowType.Popup` **不是**真正的 transient
        子窗口 —— 实测（2026-11-04）主窗口 `close()` 之后它 `isVisible()` 仍然是 True，
        用户看到的就是「软件都关了，团队窗口还挂在桌面上」。给 `Qt.Popup` 传 parent
        只解决了归属，不解决收摊，所以必须自己盯住主人的 Close/Hide/最小化。
        不去改主窗口的 `closeEvent`：那里第一句是冻结区不变量（退出先停媒体），
        为一个浮窗去动它不值当。
        """
        owner = self.parent()
        if owner is not None and obj is owner:
            if ev.type() in (ev.Type.Close, ev.Type.Hide):
                self.hide_panel()
            elif ev.type() == ev.Type.WindowStateChange:
                try:
                    if owner.windowState() & Qt.WindowState.WindowMinimized:
                        self.hide_panel()
                except Exception:
                    logger.debug("读主窗口状态失败", exc_info=True)
            return False

        if self.isVisible() and ev.type() == ev.Type.MouseButtonPress:
            try:
                if not self.geometry().contains(ev.globalPosition().toPoint()):
                    self.hide_panel()
            except Exception:
                logger.debug("点击外部关闭判断失败", exc_info=True)
        return False

    # ── 界面 ──────────────────────────────────────────
    def _build_ui(self) -> None:
        """按「动作」排：状态 → 谁在 → 等我做 → 项目 → （折叠）装机器。

        2026-11-05 重排的原因：旧版小窗只有 ① 起服务 / ② 填地址两段 ——
        那正好是从画布 `TeamPanel` 里抄来的**最没用的两段**（一辈子点一两次），
        用户点开「团队」看到的还是「原来那个样子」。真正每天要看的是
        「谁把活交给我了」和「项目改到第几版了」，而这两样**根本不需要画布**
        （纯 `/team/inbox` 与 `/team/projects` 查询）。
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("👥 团队协作")
        title.setObjectName("teamQuickTitle")
        self._status = QLabel("正在查…")
        self._status.setObjectName("teamQuickStatus")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self._status)
        root.addLayout(head)

        # ── 状态条：连接 + 几个人在线，一行看完 ──
        self._link_lbl = QLabel("")
        self._link_lbl.setObjectName("teamQuickLink")
        self._link_lbl.setWordWrap(True)
        self._link_lbl.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._link_lbl)

        self._members_lbl = QLabel("")
        self._members_lbl.setObjectName("teamQuickMembers")
        self._members_lbl.setWordWrap(True)
        self._members_lbl.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._members_lbl)

        # ── 等我做（原画布面板 ④ 段）：别人交接给我的 ──
        self._inbox_lbl = QLabel("")
        self._inbox_lbl.setObjectName("teamQuickInbox")
        self._inbox_lbl.setWordWrap(True)
        self._inbox_lbl.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._inbox_lbl)

        # ── 一起做的项目（原 ③ 段）──
        self._proj_lbl = QLabel("")
        self._proj_lbl.setObjectName("teamQuickProj")
        self._proj_lbl.setWordWrap(True)
        self._proj_lbl.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._proj_lbl)

        # ── 折叠：服务器与加入（原 ①②）──
        # 收起是默认：已加入的人不该每次都被「启动服务 / 填地址」挡在最前面。
        # 没加入时 `refresh()` 会自动展开（收起来等于把唯一入口藏了）。
        self._io_toggle = QPushButton("▸ 服务器与加入")
        self._io_toggle.setObjectName("teamQuickFold")
        self._io_toggle.setToolTip("启动服务、出配对码、填地址加入 —— 一辈子点一两次，所以收起来")
        self._io_toggle.clicked.connect(self._toggle_io)
        io_row = QHBoxLayout()
        io_row.addWidget(self._io_toggle)
        io_row.addStretch(1)
        root.addLayout(io_row)

        self._io_box = QWidget(self)
        box = QVBoxLayout(self._io_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)

        # ① 我当服务器
        l1 = QLabel("① 我当服务器（同事连我）")
        l1.setObjectName("teamQuickSec")
        box.addWidget(l1)

        row1 = QHBoxLayout()
        self._start_btn = QPushButton("启动团队服务")
        self._start_btn.clicked.connect(self._start_server)
        self._addr = QLabel("还没启动")
        self._addr.setObjectName("teamQuickMono")
        self._addr.setTextFormat(Qt.TextFormat.PlainText)
        self._addr.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row1.addWidget(self._start_btn)
        row1.addWidget(self._addr, 1)
        box.addLayout(row1)

        self._hint = QLabel("")
        self._hint.setObjectName("teamQuickHint")
        self._hint.setWordWrap(True)
        self._hint.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self._hint)

        code_row = QHBoxLayout()
        self._code_btn = QPushButton("出配对码")
        self._code_btn.setToolTip("念给同事 6 位数字；码 2 分钟内有效")
        self._code_btn.clicked.connect(self._make_code)
        self._code_show = QLabel("")
        self._code_show.setObjectName("teamQuickCode")
        self._code_show.setTextFormat(Qt.TextFormat.PlainText)
        self._code_show.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        code_row.addWidget(self._code_btn)
        code_row.addWidget(self._code_show)
        code_row.addStretch(1)   # 提示标签隐藏时按钮要留在左边，别被布局居中
        box.addLayout(code_row)

        # ② 我连别人的团队
        l2 = QLabel("② 我连别人的团队")
        l2.setObjectName("teamQuickSec")
        box.addWidget(l2)

        self._input = QLineEdit()
        self._input.setPlaceholderText("6 位配对码，或粘贴邀请链接，或对方地址")
        self._input.returnPressed.connect(self._join)
        box.addWidget(self._input)

        name_row = QHBoxLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("我的名字（同事要知道谁加进来了）")
        self._join_btn = QPushButton("加入")
        self._join_btn.clicked.connect(self._join)
        name_row.addWidget(self._name, 1)
        name_row.addWidget(self._join_btn)
        box.addLayout(name_row)

        scan_row = QHBoxLayout()
        self._scan_btn = QPushButton("扫描局域网")
        self._scan_btn.clicked.connect(self._scan)
        self._scan_hint = QLabel("")
        self._scan_hint.setObjectName("teamQuickHint")
        self._scan_hint.setTextFormat(Qt.TextFormat.PlainText)
        scan_row.addWidget(self._scan_btn)
        scan_row.addWidget(self._scan_hint)
        scan_row.addStretch(1)
        box.addLayout(scan_row)

        root.addWidget(self._io_box)
        self._io_box.setVisible(False)

        root.addWidget(self._hr())

        # 底部：完整面板
        # 提示语单独一行、按钮单独一行：
        # 两者挤在同一个 QHBoxLayout 里时，错误提示一长（比如「对方返回了 502…」）
        # 就把右下角那颗按钮顶出面板边缘（2026-11-04 用户截图为证）。
        self._msg = QLabel("")
        self._msg.setObjectName("teamQuickMsg")
        self._msg.setWordWrap(True)
        self._msg.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self._msg)

        self._full_btn = QPushButton("在画布中打开完整面板")
        self._full_btn.setToolTip("上传当前画布 / 拉取 / 版本历史 / 批注评审 —— 这些要看画布，只能在那边做")
        self._full_btn.clicked.connect(self._open_full)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(self._full_btn)
        root.addLayout(foot)

        # 初始全是空提示：先藏起来，否则每个空 QLabel 都占一整行高度，版面散成一截一截
        for lbl in (self._hint, self._code_show, self._scan_hint, self._members_lbl,
                    self._msg, self._link_lbl, self._inbox_lbl, self._proj_lbl):
            lbl.setVisible(False)

    def _toggle_io(self) -> None:
        self._io_user = True          # 用户动过了，之后不再自动收起/摊开
        show = not self._io_box.isVisible()
        self._io_box.setVisible(show)
        self._io_toggle.setText(("▾ " if show else "▸ ") + "服务器与加入")

    def _hr(self) -> QFrame:
        line = QFrame()
        line.setObjectName("teamQuickHr")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

    # ── 请求小工具 ────────────────────────────────────
    def _bridge(self, path: str) -> str:
        from app.core.canvas_bridge import DEFAULT_PORT

        return "http://127.0.0.1:%d%s" % (DEFAULT_PORT, path)

    def _token(self) -> str:
        try:
            from app.core.canvas_bridge import session_token

            return session_token()
        except Exception:
            logger.debug("拿不到画布桥令牌", exc_info=True)
            return ""

    def _call(
        self,
        method: str,
        url: str,
        cb: Callable[[Dict[str, Any]], None],
        body: Optional[Dict[str, Any]] = None,
        token: str = "",
        bearer: str = "",
    ) -> None:
        req = _Req(method, url, body=body, token=token, bearer=bearer, parent=self)
        self._threads.append(req)
        req.done.connect(lambda r, c=cb, q=req: self._on_done(r, c, q))
        req.start()

    def _on_done(self, res: Dict[str, Any], cb: Callable[[Dict[str, Any]], None], req: _Req) -> None:
        try:
            if req in self._threads:
                self._threads.remove(req)
        except ValueError:
            logger.debug("请求线程已不在列表里")
        try:
            cb(res)
        except Exception:
            logger.exception("团队小窗回调出错")
        finally:
            try:
                req.wait(10)
            except Exception:
                logger.debug("等待请求线程退出失败", exc_info=True)
            req.deleteLater()

    @staticmethod
    def _put(label: QLabel, text: str) -> None:
        """空文本就藏起来 —— 空的 QLabel 仍占一整行高度，版面会散成一截一截。"""
        label.setText(text)
        label.setVisible(bool(text))

    def _say(self, text: str, bad: bool = False) -> None:
        self._put(self._msg, text)
        self._msg.setProperty("bad", "true" if bad else "false")
        self._msg.style().unpolish(self._msg)
        self._msg.style().polish(self._msg)

    # ── 状态 ──────────────────────────────────────────
    def refresh(self) -> None:
        self._call("GET", self._bridge("/host/team/status"), self._on_status, token=self._token())

    # ── hub 凭据 / 内容层 ──────────────────────────────
    def _hub_cred(self) -> tuple:
        """(地址, 令牌) —— 问 hub 该用哪张票。

        两种身份都要能用：**本机当服务器**时用 `ensure_owner` 发的主人票；
        **加入了别人的团队**时用 `/team/pair` 换回来的成员票。
        原来只认主人票，于是「加入别人的团队」的人在这台机器上永远看不到
        成员和项目 —— 那不是权限问题，是取票路径少了一条。
        """
        addr = (self._address or "").rstrip("/")
        tok = str(self._owner.get("token") or "")
        if addr and tok:
            return addr, tok
        c = self._member_cred or {}
        a = str(c.get("address") or "").rstrip("/")
        t = str(c.get("token") or "")
        if a and t:
            return a, t
        return "", ""

    def _load_hub(self) -> None:
        """拉「等我做」与「一起做的项目」。

        🔴 这两块**根本不需要画布**：`/team/inbox` 与 `/team/projects` 都是纯服务端
        查询。旧版小窗只有连接层，等于把「今天有没有人把活交给我」锁死在画布里，
        用户在剪辑器 / 生图台里完全看不到。
        """
        addr, tok = self._hub_cred()
        if not addr or not tok:
            self._put(self._inbox_lbl, "")
            self._put(self._proj_lbl, "")
            return
        # 节流：`refresh()` 是 5 秒一次的心跳，而「谁交给我什么了」不是实时数据。
        # 不节流的话面板开着时每分钟白跑 24 次往返。
        if time.time() - self._hub_at < 12:
            return
        self._hub_at = time.time()
        self._call("GET", addr + "/team/inbox", self._on_inbox, bearer=tok)
        self._call("GET", addr + "/team/projects", self._on_projects, bearer=tok)

    def _on_inbox(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._put(self._inbox_lbl, "「等我做」拉不到：" + str(res.get("message") or ""))
            return
        items = (res.get("data") or {}).get("items") or []
        if not items:
            self._put(self._inbox_lbl, "等我做：暂时没有 —— 同事把项目交给你时会出现在这里")
            return
        # 只列 3 条：小窗是「瞄一眼」，不是工作台。多出来的用一句话带过，
        # 免得两段文本把面板撑到屏幕外（面板是 Popup，没有滚动条）。
        lines = ["等我做（%d）：" % len(items)]
        for it in items[:3]:
            name = str(it.get("project_name") or it.get("project_id") or "未命名")
            who = str(it.get("from") or "同事")
            msg = str(it.get("message") or "").strip()
            tail = ("，留言：%s" % msg[:40]) if msg else ""
            lines.append("· %s 把「%s」交给你%s" % (who, name, tail))
        if len(items) > 3:
            lines.append("· 还有 %d 条" % (len(items) - 3))
        lines.append("接手要在画布里做（右下角「打开完整面板」）")
        self._put(self._inbox_lbl, "\n".join(lines))

    def _on_projects(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._put(self._proj_lbl, "项目列表拉不到：" + str(res.get("message") or ""))
            return
        projects = (res.get("data") or {}).get("projects") or []
        if not projects:
            self._put(self._proj_lbl, "一起做的项目：还没有共享项目（在画布里「上传当前画布」就有了）")
            return
        now = time.time()
        lines = ["一起做的项目（%d）：" % len(projects)]
        for p in projects[:4]:
            name = str(p.get("name") or "未命名")
            rev = p.get("rev")
            owner = str(p.get("owner") or "")
            bit = "· %s · 第 %s 版" % (name, rev if isinstance(rev, int) else "?")
            if owner:
                bit += " · %s" % owner
            exp = p.get("claim_expires_at")
            holder = str(p.get("claimed_by") or "")
            if holder and isinstance(exp, (int, float)) and float(exp) > now:
                bit += " · 🔒 %s 在改" % holder
            lines.append(bit)
        if len(projects) > 4:
            lines.append("· 还有 %d 个" % (len(projects) - 4))
        self._put(self._proj_lbl, "\n".join(lines))

    def _on_status(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._status.setText("本机服务未知")
            self._put(self._hint, "查不到本机状态：" + _bridge_msg(str(res.get("message") or "")))
            return
        d = res.get("data") or {}
        owner = d.get("owner") or {}
        if isinstance(owner, dict) and owner.get("token"):
            self._owner = owner
        if d.get("running"):
            self._address = str(d.get("address") or "")
            self._status.setText("服务已启动")
            self._addr.setText(self._address or "地址未知")
            self._start_btn.setText("停止服务")
            self._start_btn.setProperty("on", "true")
            st = d.get("stats") or {}
            tip = ""
            if isinstance(st, dict) and st:
                parts = []
                for k, label in (("members", "人"), ("projects", "个项目"),
                                 ("versions", "个版本"), ("open_comments", "条待处理意见")):
                    if isinstance(st.get(k), int):
                        parts.append("%d %s" % (st[k], label))
                tip = " · ".join(parts)
            self._put(self._hint, ("同事填这个地址，或念配对码给他们。" + tip) if tip
                               else "同事填这个地址，或念配对码给他们。")
        else:
            self._address = ""
            self._status.setText("未启动")
            self._addr.setText("还没启动")
            self._start_btn.setText("启动团队服务")
            self._start_btn.setProperty("on", "false")
            self._put(self._hint, str(d.get("hint") or "点「启动团队服务」后，同事才能连这台机器"))
        self._start_btn.style().unpolish(self._start_btn)
        self._start_btn.style().polish(self._start_btn)

        # 接没接上团队，决定「装机器那段」是收还是摊开：
        #   接上了 → 收起（每天要看的「等我做 / 项目」才有地方站）
        #   没接上 → 强制摊开（收起来等于把唯一入口藏了，新同事只会看到空面板）
        # `_io_user` 记「用户自己动过折叠」，动过之后一切听用户的，不再自动改。
        addr, tok = self._hub_cred()
        if addr and tok:
            self._put(self._link_lbl, "● 已接上团队 · %s" % addr)
            if not self._io_user:
                self._io_box.setVisible(False)
                self._io_toggle.setText("▸ 服务器与加入")
            self._load_members()
            self._load_hub()
        else:
            self._put(self._link_lbl, "○ 还没接上团队 —— 展开下面「服务器与加入」")
            if not self._io_user:
                self._io_box.setVisible(True)
                self._io_toggle.setText("▾ 服务器与加入")
            self._put(self._members_lbl, "")
            self._put(self._inbox_lbl, "")
            self._put(self._proj_lbl, "")

    # ── 启动 / 停止 ───────────────────────────────────
    def _start_server(self) -> None:
        running = self._start_btn.text().startswith("停止")
        path = "/host/team/stop" if running else "/host/team/start"
        self._say("正在停止…" if running else "正在启动…")
        self._call("POST", self._bridge(path), self._on_started,
                   body={}, token=self._token())

    def _on_started(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._say(str(res.get("message") or "操作失败，原因未知"), bad=True)
            return
        d = res.get("data") or {}
        owner = d.get("owner") or {}
        if isinstance(owner, dict) and owner.get("token"):
            self._owner = owner
        self._say("服务已启动，把地址发给同事就行" if d.get("running") else "服务已停止")
        self.refresh()

    # ── 出码 ──────────────────────────────────────────
    def _make_code(self) -> None:
        token = str(self._owner.get("token") or "")
        if not self._address or not token:
            self._say("先启动团队服务，才能出码", bad=True)
            return
        self._say("正在出码…")
        self._call("POST", self._address.rstrip("/") + "/team/pairing",
                   self._on_code, body={"max_uses": 1, "role": "editor"}, bearer=token)

    def _on_code(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._say(str(res.get("message") or "出码失败"), bad=True)
            return
        d = res.get("data") or {}
        code = str(d.get("code") or "")
        if not code:
            self._say("对方没给码，原因未知", bad=True)
            return
        self._put(self._code_show, "配对码 %s（2 分钟内、只能用一次）" % code)
        self._say("把 %s 念给同事" % code)

    # ── 扫描 ──────────────────────────────────────────
    def _scan(self) -> None:
        self._put(self._scan_hint, "正在扫描…")
        self._call("GET", self._bridge("/host/team/discover"), self._on_scan, token=self._token())

    def _on_scan(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._put(self._scan_hint, str(res.get("message") or "扫描失败"))
            return
        servers = (res.get("data") or {}).get("servers") or []
        if not servers:
            self._put(self._scan_hint, "没扫到。让对方先启动服务，或直接念配对码")
            return
        first = servers[0] or {}
        self._input.setText(str(first.get("address") or ""))
        self._put(self._scan_hint, "扫到 %d 台，已填第一台" % len(servers))

    # ── 加入 ──────────────────────────────────────────
    def _join(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._say("先填你的名字，同事才知道谁加进来了", bad=True)
            self._name.setFocus()
            return
        inv = parse_invite(self._input.text())
        if inv["kind"] == "none":
            self._say(inv.get("why") or "认不出这是码还是地址", bad=True)
            self._input.setFocus()
            return
        if inv["kind"] == "code" and not inv.get("host"):
            # 只有码：先让本机桥用 UDP 广播问出地址（浏览器没有 raw socket，这件事只能它做）
            self._say("正在用配对码找主机…")
            self._call("POST", self._bridge("/host/team/find-code"),
                       lambda r: self._on_found(r, name), body={"code": inv["code"]},
                       token=self._token())
            return
        if inv["kind"] == "code":
            self._pair(inv["code"], inv["host"], name)
            return
        self._join_direct(inv["host"], name)

    def _on_found(self, res: Dict[str, Any], name: str) -> None:
        if not res.get("ok"):
            self._say(str(res.get("message") or "找主机失败"), bad=True)
            return
        d = res.get("data") or {}
        srv = d.get("server") or {}
        addr = str(srv.get("address") or srv.get("host") or "")
        if not addr:
            self._say(str(d.get("message") or "这个码当前没人应答 —— 核对一下，或让对方重新出码"), bad=True)
            return
        self._pair(parse_invite(self._input.text())["code"], addr, name)

    def _pair(self, code: str, addr: str, name: str) -> None:
        self._say("正在用码加入…")
        base = addr if "://" in addr else "http://" + addr
        self._call("POST", base.rstrip("/") + "/team/pair", self._on_joined,
                   body={"name": name, "code": code})

    def _join_direct(self, addr: str, name: str) -> None:
        self._say("正在加入…（这条路径不凭码，进去是「只看」身份）")
        base = addr if "://" in addr else "http://" + addr
        self._call("POST", base.rstrip("/") + "/team/join", self._on_joined,
                   body={"name": name})

    def _on_joined(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._say(str(res.get("message") or "加入失败"), bad=True)
            return
        d = res.get("data") or {}
        token = str(d.get("token") or "")
        if not token:
            self._say("加入了但对方没给令牌，原因未知", bad=True)
            return
        addr = str(d.get("address") or "")
        cred = {
            "token": token,
            "address": addr,
            "member_id": str(d.get("member_id") or d.get("id") or ""),
            "name": str(d.get("name") or self._name.text().strip()),
            "role": str(d.get("role") or ""),
        }
        self._pending_cred = cred
        self._member_cred = dict(cred)   # 长期留一份：「等我做 / 项目」每次刷新都要用它
        self._address = addr
        role = cred["role"] or "成员"
        self._hub_at = 0.0               # 刚加入，立刻拉一次，别等节流窗口过
        self._say("已加入（%s）。下面就能看到「等我做」和项目；动手要在画布里" % role)
        self.refresh()

    def take_cred(self) -> Optional[Dict[str, str]]:
        """取走待注入画布的凭据（注入后清空，避免反复写）。"""
        c = self._pending_cred
        self._pending_cred = None
        return c

    # ── 成员 ──────────────────────────────────────────
    def _load_members(self) -> None:
        addr, token = self._hub_cred()
        if not addr or not token:
            self._put(self._members_lbl, "")
            return
        self._call("GET", addr + "/team/members", self._on_members, bearer=token)

    def _on_members(self, res: Dict[str, Any]) -> None:
        if not res.get("ok"):
            self._put(self._members_lbl, "成员列表拿不到：" + str(res.get("message") or ""))
            return
        members = (res.get("data") or {}).get("members") or []
        addr, _tok = self._hub_cred()
        self._put(self._link_lbl, "● 已接上团队 · %d 人在册 · %s" % (len(members), addr))
        if not members:
            self._put(self._members_lbl, "还没有成员")
            return
        bits = []
        for m in members[:8]:
            nm = str(m.get("name") or "未命名")
            role = {"owner": "主人", "editor": "能改", "viewer": "只看"}.get(
                str(m.get("role") or ""), str(m.get("role") or ""))
            bits.append("%s（%s）" % (nm, role))
        more = "" if len(members) <= 8 else " 等 %d 人" % len(members)
        self._put(self._members_lbl, "成员： " + "、".join(bits) + more)

    # ── 完整面板 ──────────────────────────────────────
    def _open_full(self) -> None:
        self.hide_panel()
        self.open_full_requested.emit()
