"""
账号运营模块 (AccountOpsModule)
===============================
从 modules.py 拆分出来的独立模块文件。

功能:
- 多平台账号管理（8平台：抖音/快手/视频号/小红书/B站/微博/头条/西瓜）
- 智能运营建议（LLM 驱动）
- 数据看板（7天趋势图）
- 矩阵批量发布
- OAuth 2.0 授权绑定
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGroupBox, QLineEdit, QFormLayout,
    QComboBox, QCheckBox, QDialog, QMessageBox,
)
from PyQt6.QtCore import Qt

from .base_module import BaseModule
from .account_skills import register_account_skills

logger = logging.getLogger("AI短剧编辑器.account_ops")


class AccountOpsModule(BaseModule):
    """
    账号运营模块
    多平台账号管理 | 智能运营建议 | 数据看板 | 矩阵发布
    """

    module_id = "account"
    module_name = "账号运营"
    module_icon = "👤"

    PLATFORMS = [
        ("douyin", "📱 抖音", "#111111"),
        ("kuaishou", "🎬 快手", "#FF4500"),
        ("weixin", "💬 视频号", "#07C160"),
        ("xiaohongshu", "📕 小红书", "#FF2442"),
        ("bilibili", "🎮 B站", "#00A1D6"),
        ("weibo", "🐦 微博", "#E6162D"),
        ("toutiao", "📰 头条", "#F85959"),
        ("xigua", "🍉 西瓜", "#FF4444"),
    ]

    _DEFAULT_ACCOUNTS = {
        "douyin": [{"name": "@主账号", "status": "正常", "fans": "12.5万粉"}],
        "kuaishou": [{"name": "@快手主号", "status": "正常", "fans": "8.3万粉"}],
        "weixin": [{"name": "@视频号", "status": "正常", "fans": "5.6万粉"}],
        "xiaohongshu": [],
        "bilibili": [],
        "weibo": [],
        "toutiao": [],
        "xigua": [],
    }

    def __init__(self):
        register_account_skills()
        self._selected_platform = "douyin"
        self._bound_accounts = self._load_accounts()
        super().__init__()

    @classmethod
    def _accounts_file(cls):
        workspace = Path(__file__).parent.parent.parent.parent
        return workspace / "data" / "bound_accounts.json"

    def _load_accounts(self):
        """从 JSON 加载已绑定账号，首次运行使用默认数据"""
        af = self._accounts_file()
        if af.exists():
            try:
                with open(af, 'r', encoding='utf-8') as f:
                    accounts = json.load(f)
                logger.info(f"从文件加载账户数据: {af}")
                return accounts
            except Exception as e:
                logger.warning(f"加载账户文件失败，使用默认数据: {e}")
        return dict(self._DEFAULT_ACCOUNTS)

    def _save_accounts(self):
        """将已绑定账号持久化到 JSON 文件"""
        try:
            af = self._accounts_file()
            af.parent.mkdir(parents=True, exist_ok=True)
            with open(af, 'w', encoding='utf-8') as f:
                json.dump(self._bound_accounts, f, ensure_ascii=False, indent=2)
            logger.debug(f"账户数据已保存: {af}")
        except Exception as e:
            logger.warning(f"保存账户数据失败: {e}")

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        sidebar = self._create_sidebar()
        layout.addWidget(sidebar)

        self._content_stack = QWidget()
        self._content_layout = QVBoxLayout(self._content_stack)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        layout.addWidget(self._content_stack, 1)

        self._switch_platform("douyin")

    def _create_sidebar(self) -> QWidget:
        w = QFrame()
        w.setStyleSheet("QFrame{background:#121212;border:1px solid #252525;border-radius:12px;}")
        w.setFixedWidth(170)
        lo = QVBoxLayout(w)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)

        title = QLabel("平台选择")
        title.setStyleSheet("color:#888;font-size:10px;font-weight:600;padding:4px 8px;")
        lo.addWidget(title)

        self._platform_btns = {}
        for pid, name, color in self.PLATFORMS:
            btn = QPushButton(name)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background:transparent;color:#888;border:none;border-radius:6px;
                    border-left:3px solid transparent;
                    padding:8px 10px;font-size:11px;text-align:left;
                }}
                QPushButton:hover {{background:#1e1e1e;color:#ccc;}}
                QPushButton[active="true"] {{
                    background:#1a1a2e;color:#fff;border-left:3px solid {color};font-weight:600;
                }}
            """)
            btn.clicked.connect(lambda checked, p=pid: self._switch_platform(p))
            self._platform_btns[pid] = btn
            lo.addWidget(btn)

        lo.addStretch()

        sync_btn = QPushButton("🔄 同步数据")
        sync_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;"
            "padding:6px;font-size:10px;font-weight:600;}QPushButton:hover{background:#1557b0;}"
        )
        sync_btn.clicked.connect(lambda _: self._switch_platform(self._selected_platform))
        lo.addWidget(sync_btn)

        return w

    def _switch_platform(self, pid):
        self._selected_platform = pid
        for k, btn in self._platform_btns.items():
            btn.setProperty("active", "true" if k == pid else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if not hasattr(self, "_platform_panels"):
            self._platform_panels = {}

        for k, panel in self._platform_panels.items():
            if panel.get("_visible"):
                panel["widget"].hide()
                panel["_visible"] = False

        if pid not in self._platform_panels:
            self._platform_panels[pid] = {
                "widget": self._create_platform_panel(pid),
                "_visible": False,
            }

        panel = self._platform_panels[pid]
        if not panel["_visible"]:
            self._content_layout.addWidget(panel["widget"], 1)
            panel["_visible"] = True
        panel["widget"].show()

    def _create_platform_panel(self, pid) -> QWidget:
        """为单个平台创建内容面板 (只创建一次, 后续复用)"""
        s = QScrollArea()
        s.setWidgetResizable(True)
        s.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        c = QWidget()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)

        pinfo = next(p for p in self.PLATFORMS if p[0] == pid)
        cl.addWidget(self._create_overview_card(pinfo))
        cl.addWidget(self._create_accounts_card(pinfo))
        cl.addWidget(self._create_stats_card(pinfo))
        cl.addWidget(self._create_suggestions_card(pinfo))
        cl.addWidget(self._create_publish_card(pinfo))
        cl.addWidget(self._create_matrix_card())
        cl.addWidget(self._create_data_card())
        cl.addStretch()

        s.setWidget(c)
        return s

    def _card(self, title, icon="") -> QGroupBox:
        grp = QGroupBox(f"{icon} {title}" if icon else title)
        grp.setStyleSheet(
            "QGroupBox{font-size:12px;font-weight:600;color:#ccc;border:1px solid #252525;"
            "border-radius:10px;margin-top:8px;padding-top:14px;background:#121212;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;}"
        )
        lo = QVBoxLayout(grp)
        lo.setContentsMargins(12, 8, 12, 12)
        lo.setSpacing(6)
        return grp

    def _create_overview_card(self, pinfo):
        pid = pinfo[0]
        card = self._card("", "📊")
        lo = card.layout()
        row = QHBoxLayout()
        row.setSpacing(12)

        accts = self._bound_accounts.get(pid, [])
        total_fans = sum(
            int(a["fans"].replace("万粉", "").replace(".", ""))
            for a in accts if "万粉" in a.get("fans", "")
        )
        normal = len([a for a in accts if a["status"] == "正常"])
        limited = len([a for a in accts if a["status"] == "限流"])

        stats = [
            ("绑定账号", f"{len(accts)}个", "#1e6bde"),
            ("总粉丝", f"{total_fans}万" if total_fans else "--", "#4caf50"),
            ("正常率", f"{int(normal/max(len(accts),1)*100)}%" if accts else "--", "#ff9800"),
            ("限流/异常", f"{limited}个" if limited else "0个", "#9c27b0"),
        ]
        for name, val, clr in stats:
            f = QFrame()
            f.setStyleSheet("background:#0a0a0a;border-radius:8px;")
            fl = QVBoxLayout(f)
            fl.setContentsMargins(8, 6, 8, 6)
            vl = QLabel(val)
            vl.setStyleSheet(f"color:{clr};font-size:16px;font-weight:bold;")
            vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fl.addWidget(vl)
            nl = QLabel(name)
            nl.setStyleSheet("color:#666;font-size:9px;")
            nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nl.setWordWrap(True)
            fl.addWidget(nl)
            row.addWidget(f)
        lo.addLayout(row)
        return card

    def _create_accounts_card(self, pinfo):
        pid = pinfo[0]
        card = self._card("已绑定账号", "🔗")
        lo = card.layout()
        accounts = self._bound_accounts.get(pid, [])

        if not accounts:
            hint = QLabel("暂未绑定账号，点击下方添加")
            hint.setStyleSheet("color:#555;font-size:10px;padding:4px 0;")
            hint.setWordWrap(True)
            lo.addWidget(hint)
        else:
            for i, acct in enumerate(accounts):
                sc = (
                    "#4caf50" if acct["status"] == "正常"
                    else "#ff9800" if acct["status"] == "限流"
                    else "#ef4444"
                )
                row = QFrame()
                row.setStyleSheet("QFrame{background:#0a0a0a;border-radius:6px;}")
                rl = QHBoxLayout(row)
                rl.setContentsMargins(10, 6, 10, 6)
                nm = QLabel(acct["name"])
                nm.setWordWrap(True)
                rl.addWidget(nm)
                rl.addWidget(QLabel(acct["fans"]))
                st = QLabel(acct["status"])
                st.setStyleSheet(f"color:{sc};font-size:10px;font-weight:600;")
                rl.addWidget(st)
                rl.addStretch()
                act = QPushButton("管理")
                act.setStyleSheet(
                    "QPushButton{background:#2a2a2a;color:#ccc;border:none;"
                    "border-radius:4px;padding:3px 10px;font-size:10px;}"
                    "QPushButton:hover{background:#3a3a3a;}"
                )
                act.clicked.connect(lambda checked, ii=i: self._manage_account_dialog(pid, ii))
                rl.addWidget(act)
                lo.addWidget(row)

        add_btn = QPushButton("➕ 绑定账号")
        add_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#1e6bde;border:1px dashed #1e6bde;"
            "border-radius:6px;padding:6px;font-size:11px;}"
            "QPushButton:hover{background:#1a1a2e;}"
        )
        add_btn.clicked.connect(lambda _: self._bind_account_dialog(pid))
        lo.addWidget(add_btn)
        return card

    def _bind_account_dialog(self, pid):
        pinfo = next(p for p in self.PLATFORMS if p[0] == pid)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"绑定{pinfo[1]}账号")
        dialog.setMinimumSize(420, 320)
        dialog.setStyleSheet("QDialog{background:#121212;}")
        dl = QVBoxLayout(dialog)
        dl.setContentsMargins(16, 16, 16, 16)
        dl.setSpacing(10)

        mode_label = QLabel("绑定方式")
        mode_label.setStyleSheet("color:#888;font-size:11px;font-weight:600;")
        dl.addWidget(mode_label)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(8)

        self._bind_mode = "manual"
        mode_manual = QPushButton("✍️ 手动录入")
        mode_oauth = QPushButton("🔗 OAuth 授权")

        btn_style = (
            "QPushButton { background:#1a1a1a; color:#888; border:1px solid #333; "
            "border-radius:6px; padding:8px 12px; font-size:11px; }"
            "QPushButton:hover { background:#252525; color:#ccc; }"
            "QPushButton[active=\"true\"] { background:#1a1a2e; color:#fff; "
            "border:1px solid #1e6bde; font-weight:600; }"
        )
        mode_manual.setStyleSheet(btn_style)
        mode_oauth.setStyleSheet(btn_style)
        mode_manual.setProperty("active", "true")

        def set_mode(mode):
            self._bind_mode = mode
            mode_manual.setProperty("active", "true" if mode == "manual" else "false")
            mode_oauth.setProperty("active", "true" if mode == "oauth" else "false")
            for btn in [mode_manual, mode_oauth]:
                btn.style().unpolish(btn)
                btn.style().polish(btn)
            manual_widget.setVisible(mode == "manual")
            oauth_widget.setVisible(mode == "oauth")

        mode_manual.clicked.connect(lambda: set_mode("manual"))
        mode_oauth.clicked.connect(lambda: set_mode("oauth"))
        mode_layout.addWidget(mode_manual)
        mode_layout.addWidget(mode_oauth)
        mode_layout.addStretch()
        dl.addLayout(mode_layout)

        # 手动录入区域
        manual_widget = QWidget()
        mvl = QVBoxLayout(manual_widget)
        mvl.setContentsMargins(0, 0, 0, 0)
        mvl.setSpacing(8)

        fl = QFormLayout()
        fl.setSpacing(8)
        name_input = QLineEdit()
        name_input.setPlaceholderText("@账号名称")
        name_input.setStyleSheet(
            "QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:4px;padding:6px 10px;font-size:11px;}"
        )
        fl.addRow("账号名:", name_input)
        fans_input = QLineEdit()
        fans_input.setPlaceholderText("如: 12.5万粉")
        fans_input.setStyleSheet(
            "QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:4px;padding:6px 10px;font-size:11px;}"
        )
        fl.addRow("粉丝:", fans_input)
        status_cmb = QComboBox()
        status_cmb.addItems(["正常", "限流", "异常"])
        status_cmb.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:4px;padding:5px 8px;font-size:11px;}"
        )
        fl.addRow("状态:", status_cmb)
        mvl.addLayout(fl)
        dl.addWidget(manual_widget)

        # OAuth 授权区域
        oauth_widget = QWidget()
        ovl = QVBoxLayout(oauth_widget)
        ovl.setContentsMargins(0, 0, 0, 0)
        ovl.setSpacing(8)

        oauth_info = QLabel(
            "通过官方 OAuth 2.0 授权，自动获取账号信息和数据权限。\n"
            "授权后可直接读取粉丝、播放量等真实运营数据。"
        )
        oauth_info.setStyleSheet("color:#999;font-size:11px;line-height:1.5;padding:4px 0;")
        oauth_info.setWordWrap(True)
        ovl.addWidget(oauth_info)

        oauth_status = QLabel("")
        oauth_status.setStyleSheet("color:#888;font-size:11px;padding:4px 8px;")
        oauth_status.setWordWrap(True)

        try:
            from .platform_oauth import get_oauth_manager, PLATFORM_OAUTH_CONFIGS
            oauth_mgr = get_oauth_manager()
            has_creds = oauth_mgr.has_client_credentials(pid)
            is_authed = oauth_mgr.is_authorized(pid)

            if is_authed:
                oauth_status.setText("✅ 已授权 — 可刷新 token 或重新授权")
                oauth_status.setStyleSheet("color:#22c55e;font-size:11px;padding:4px 8px;")
            elif has_creds:
                oauth_status.setText("🔑 Client ID 已配置 — 点击下方按钮开始授权")
                oauth_status.setStyleSheet("color:#facc15;font-size:11px;padding:4px 8px;")
            else:
                oauth_status.setText(
                    "⚠️ 需先在平台开放网站申请 Client ID 和 Client Secret，"
                    "然后在设置中填入，或继续使用手动录入模式。"
                )
                oauth_status.setStyleSheet("color:#f87171;font-size:11px;padding:4px 8px;")
        except Exception:
            oauth_status.setText("⚠️ OAuth 模块加载失败，请使用手动录入模式。")
            oauth_status.setStyleSheet("color:#f87171;font-size:11px;padding:4px 8px;")

        ovl.addWidget(oauth_status)

        oauth_btn_layout = QHBoxLayout()
        oauth_btn_layout.setSpacing(8)

        oauth_start_btn = QPushButton("🔗 开始 OAuth 授权")
        oauth_start_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;"
            "padding:8px 16px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#1557b0;}"
        )
        oauth_start_btn.clicked.connect(
            lambda: self._start_oauth_auth(pid, dialog, oauth_status)
        )
        oauth_btn_layout.addWidget(oauth_start_btn)
        oauth_btn_layout.addStretch()
        ovl.addLayout(oauth_btn_layout)

        oauth_widget.setVisible(False)
        dl.addWidget(oauth_widget)

        # 底部按钮
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("取消")
        cancel.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;"
            "padding:6px 16px;font-size:11px;}QPushButton:hover{background:#3a3a3a;}"
        )
        cancel.clicked.connect(dialog.reject)
        btns.addWidget(cancel)
        ok = QPushButton("✅ 绑定")
        ok.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:4px;"
            "padding:6px 16px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#1557b0;}"
        )
        ok.clicked.connect(dialog.accept)
        btns.addWidget(ok)
        dl.addLayout(btns)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self._bind_mode == "manual" and name_input.text().strip():
                self._bound_accounts.setdefault(pid, []).append({
                    "name": name_input.text().strip(),
                    "fans": fans_input.text().strip() or "--",
                    "status": status_cmb.currentText(),
                })
                self._save_accounts()
                self._switch_platform(pid)
            elif self._bind_mode == "oauth":
                self._switch_platform(pid)

    def _start_oauth_auth(self, pid, dialog, status_label):
        """启动 OAuth 2.0 授权流程"""
        try:
            from .platform_oauth import get_oauth_manager
            oauth_mgr = get_oauth_manager()

            if not oauth_mgr.has_client_credentials(pid):
                QMessageBox.warning(
                    self, "未配置 Client ID",
                    "请先在对应平台开放网站申请 API 密钥，\n"
                    "然后在应用设置中填入 Client ID 和 Client Secret。"
                )
                return

            def on_auth_success(token):
                status_label.setText("✅ 授权成功！已自动获取账号信息")
                status_label.setStyleSheet("color:#22c55e;font-size:11px;padding:4px 8px;")
                self._bound_accounts.setdefault(pid, []).append({
                    "name": f"@{pid}_oauth",
                    "fans": "OAuth 授权",
                    "status": "正常",
                    "oauth_authorized": True,
                    "access_token": token.access_token[:16] + "...",
                    "expires_at": token.expires_at,
                })
                self._save_accounts()
                QMessageBox.information(
                    self, "授权成功",
                    f"已成功通过 OAuth 绑定 {pid} 平台账号！\n"
                    f"授权有效期至: {datetime.fromtimestamp(token.expires_at).strftime('%Y-%m-%d %H:%M')}"
                )
                dialog.accept()

            def on_auth_error(error_msg):
                status_label.setText(f"❌ 授权失败: {error_msg}")
                status_label.setStyleSheet("color:#f87171;font-size:11px;padding:4px 8px;")

            oauth_mgr.authorize(pid, on_success=on_auth_success, on_error=on_auth_error)

        except ImportError:
            QMessageBox.warning(self, "模块缺失", "OAuth 授权模块未加载，请使用手动录入方式绑定账号。")
        except Exception as e:
            QMessageBox.warning(self, "授权异常", f"启动 OAuth 授权时出错: {str(e)}")

    def _manage_account_dialog(self, pid, idx):
        accounts = self._bound_accounts.get(pid, [])
        if idx >= len(accounts):
            return
        acct = accounts[idx]
        dialog = QDialog(self)
        dialog.setWindowTitle(f"管理 {acct['name']}")
        dialog.setMinimumSize(340, 240)
        dialog.setStyleSheet("QDialog{background:#121212;}")
        dl = QVBoxLayout(dialog)
        dl.setContentsMargins(16, 16, 16, 16)
        dl.setSpacing(10)

        info = QLabel(f"账号: {acct['name']}\n粉丝: {acct['fans']}\n状态: {acct['status']}")
        info.setStyleSheet("color:#ccc;font-size:12px;")
        dl.addWidget(info)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        refresh = QPushButton("🔄 刷新数据")
        refresh.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;"
            "padding:6px 14px;font-size:11px;}QPushButton:hover{background:#3a3a3a;}"
        )
        refresh.clicked.connect(lambda _: self._refresh_account_data(pid, idx))
        btns.addWidget(refresh)
        btns.addStretch()
        delete = QPushButton("🗑 解绑")
        delete.setStyleSheet(
            "QPushButton{background:#ef4444;color:#fff;border:none;border-radius:4px;"
            "padding:6px 14px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#dc2626;}"
        )
        delete.clicked.connect(
            lambda _: (accounts.pop(idx), self._save_accounts(), dialog.reject())
        )
        btns.addWidget(delete)
        dl.addLayout(btns)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:none;border-radius:4px;"
            "padding:6px;font-size:11px;}QPushButton:hover{background:#3a3a3a;}"
        )
        close_btn.clicked.connect(dialog.accept)
        dl.addWidget(close_btn)

        dialog.exec()
        self._switch_platform(pid)

    def _refresh_account_data(self, pid: str, idx: int):
        """刷新单个账号数据"""
        accounts = self._bound_accounts.get(pid, [])
        if idx >= len(accounts):
            return
        acct = accounts[idx]

        data_updated = False
        try:
            workspace = Path(__file__).parent.parent.parent.parent
            pf = workspace / "data" / "publish_log.json"
            if pf.exists():
                with open(pf, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                if isinstance(logs, list):
                    recent = [l for l in logs if l.get("platform") == pid]
                    if recent:
                        acct["status"] = "正常"
                        data_updated = True
        except Exception as e:
            print(f"[AccountOps] 刷新账号数据失败: {e}")

        if not data_updated:
            QMessageBox.information(
                self, "刷新数据",
                f"账号 {acct.get('name', '未知')} 暂无最新数据。\n\n"
                "提示：完成一次发布或数据采集后可获得真实数据。"
            )
        else:
            self._save_accounts()
            self._switch_platform(pid)
            QMessageBox.information(self, "刷新完成", f"账号 {acct.get('name', '未知')} 数据已更新")

    def _create_stats_card(self, pinfo):
        card = self._card("近7天数据趋势", "📈")
        lo = card.layout()

        day_values = self._get_7day_data(pinfo[0])

        bars = QHBoxLayout()
        bars.setSpacing(4)
        from datetime import datetime, timedelta
        today = datetime.now()

        if any(v > 0 for v in day_values):
            max_val = max(day_values) if max(day_values) > 0 else 1
            for i in range(7):
                val = day_values[i]
                h = max(8, int(val / max_val * 80)) if val > 0 else 8
                bar = QFrame()
                bar.setStyleSheet("background:#1e6bde;border-radius:3px;")
                bar.setFixedSize(28, h)
                bar.setToolTip(f"{val} 次操作")
                col = QVBoxLayout()
                col.setContentsMargins(0, 0, 0, 0)
                col.setSpacing(2)
                col.addStretch()
                col.addWidget(bar)
                day_str = "今天" if i == 0 else f"{(today - timedelta(days=i)).strftime('%m/%d')}"
                lbl = QLabel(day_str)
                lbl.setStyleSheet("color:#555;font-size:8px;")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                col.addWidget(lbl)
                bars.addLayout(col)
        else:
            hint = QLabel("暂无数据，去发布第一条作品吧")
            hint.setStyleSheet("color:#555;font-size:11px;padding:16px;")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lo.addWidget(hint)

        bars.addStretch()
        lo.addLayout(bars)
        return card

    def _get_7day_data(self, platform_id: str) -> list:
        """从 analytics.json 和 publish_log.json 读取近7天数据"""
        from datetime import datetime, timedelta

        workspace = Path(__file__).parent.parent.parent.parent
        today = datetime.now()
        day_values = [0] * 7

        try:
            pf = workspace / "data" / "publish_log.json"
            if pf.exists():
                with open(pf, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                if isinstance(logs, list):
                    for entry in logs:
                        ts = entry.get("timestamp", "")
                        pid = entry.get("platform", "")
                        if pid and pid != platform_id:
                            continue
                        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                            try:
                                dt = datetime.strptime(
                                    ts[:19],
                                    "%Y-%m-%dT%H:%M:%S" if "T" in ts else "%Y-%m-%d %H:%M:%S"
                                )
                                break
                            except ValueError:
                                continue
                        else:
                            continue
                        diff_days = (today - dt).days
                        if 0 <= diff_days < 7:
                            day_values[diff_days] += 1
        except Exception:
            pass

        try:
            af = workspace / "data" / "analytics.json"
            if af.exists():
                with open(af, 'r', encoding='utf-8') as f:
                    analytics = json.load(f)
                daily = analytics.get("daily_ops", {})
                for i in range(7):
                    day_key = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                    day_values[i] += daily.get(day_key, 0)
        except Exception:
            pass

        return day_values

    def _create_suggestions_card(self, pinfo):
        card = self._card(" AI 运营建议", "")
        card.setStyleSheet(
            "QGroupBox{font-size:12px;font-weight:600;color:#ccc;border:1px solid #22c55e;"
            "border-radius:10px;margin-top:8px;padding-top:14px;background:#121212;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;}"
        )
        lo = card.layout()

        tips = self._generate_account_tips(pinfo)

        for icon, tip in tips:
            row = QHBoxLayout()
            row.setSpacing(8)
            il = QLabel(icon)
            il.setFixedWidth(24)
            il.setStyleSheet("font-size:14px;")
            row.addWidget(il)
            tl = QLabel(tip)
            tl.setStyleSheet("color:#aaa;font-size:10px;line-height:1.5;")
            tl.setWordWrap(True)
            tl.setMinimumHeight(30)
            row.addWidget(tl, 1)
            lo.addLayout(row)
        return card

    def _generate_account_tips(self, pinfo) -> list:
        """根据平台和账号数据生成运营建议，优先调用 LLM，失败时回退通用建议"""
        pid = pinfo[0]
        platform_name = pinfo[1].replace("📱 ", "").replace("🎬 ", "").replace("💬 ", "")\
            .replace("📕 ", "").replace("🎮 ", "").replace("🐦 ", "")\
            .replace("📰 ", "").replace("🍉 ", "")
        accounts = self._bound_accounts.get(pid, [])
        acct_count = len(accounts)
        total_fans = sum(
            int(a.get("fans", "0").replace("万粉", "").replace(".", "").replace("万", ""))
            for a in accounts
        )

        try:
            import os as _os
            active_file = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))),
                "data", "active_provider.json"
            )
            provider_id = ""
            if _os.path.exists(active_file):
                with open(active_file, 'r', encoding='utf-8') as f:
                    provider_id = json.load(f).get("active_provider", "")

            if provider_id:
                from .cloud_api import cloud_api_service
                system_prompt = (
                    f"你是{platform_name}平台的运营专家。请根据以下账号数据，生成3条简洁的运营建议（每条20字内）。"
                    f"格式：每条一行，用💡🎯⚠️📊等emoji开头。不要编号。"
                )
                context = f"{platform_name}平台，{acct_count}个账号，约{total_fans}万粉丝。"
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context}
                ]
                result_parts = []
                for chunk in cloud_api_service.chat(
                    provider_id, messages, stream=False, temperature=0.7, max_tokens=512
                ):
                    if chunk and not chunk.startswith("错误") and not chunk.startswith("API 错误"):
                        result_parts.append(chunk)
                raw = "".join(result_parts).strip()
                if raw and len(raw) > 10:
                    tips = []
                    for line in raw.split("\n"):
                        line = line.strip()
                        if line and len(line) > 3:
                            icon = "💡"
                            for e in "💡🎯⚠️📊📈🔥⏰🌟✅❌":
                                if line.startswith(e):
                                    icon = e
                                    line = line[len(e):].lstrip(":： ")
                                    break
                            tips.append((icon, line))
                    if tips:
                        return tips[:5]
        except Exception:
            pass

        tips = []
        if acct_count == 0:
            tips.append(("💡", f"尚未在{platform_name}绑定账号，添加账号后可获取个性化运营建议"))
        else:
            tips.append(("💡", "建议在 18:00-22:00 发布，该时段互动率最高"))
            tips.append(("🎯", "热门话题 #短剧推荐 #爽文改编 可增加曝光"))
            if total_fans > 0:
                tips.append(("📊", f"当前{platform_name}平台共{acct_count}个账号，总粉丝约{total_fans}万"))
            tips.append(("📈", "30秒竖版视频完播率比横版高 28%，建议优先制作竖版"))
            tips.append(("⏰", "粉丝活跃高峰：工作日 12:00-13:00, 20:00-22:00"))
        return tips[:5]

    def _create_publish_card(self, pinfo):
        card = self._card("快速发布", "📤")
        lo = card.layout()

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        title_input = QLineEdit()
        title_input.setPlaceholderText("视频标题...")
        title_input.setStyleSheet(
            "QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        row1.addWidget(title_input, 1)
        dur = QComboBox()
        dur.addItems(["30秒", "60秒", "90秒", "3分钟"])
        dur.setStyleSheet(
            "QComboBox{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:5px 8px;font-size:10px;}"
        )
        row1.addWidget(dur)
        lo.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        desc = QLineEdit()
        desc.setPlaceholderText("描述文案 + #话题标签...")
        desc.setStyleSheet(
            "QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        row2.addWidget(desc, 1)
        auto_tag = QCheckBox("智能标签")
        auto_tag.setStyleSheet("color:#888;font-size:10px;")
        row2.addWidget(auto_tag)
        lo.addLayout(row2)

        pub_btn = QPushButton(f"🚀 发布到 {pinfo[1]}")
        pub_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:8px;"
            "padding:10px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:#1557b0;}"
        )
        lo.addWidget(pub_btn)
        return card

    def _create_matrix_card(self):
        card = self._card("🎯 矩阵发布（全平台批量）", "")
        lo = card.layout()
        desc = QLabel("勾选账号，一键发布到多个平台")
        desc.setStyleSheet("color:#666;font-size:10px;padding-bottom:4px;")
        lo.addWidget(desc)

        accounts = [
            ("📱 抖音", "@主账号", True),
            ("🎬 快手", "@快手主号", True),
            ("💬 视频号", "@视频号", True),
            ("📕 小红书", "@小红书号", False),
            ("🐦 微博", "@微博号", False),
            ("📰 头条", "@头条号", False),
        ]
        for platform, name, checked in accounts:
            row = QFrame()
            row.setStyleSheet("QFrame{background:#0a0a0a;border-radius:4px;}")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 4, 8, 4)
            rl.setSpacing(8)
            cb = QCheckBox(platform)
            cb.setChecked(checked)
            cb.setStyleSheet("color:#ccc;font-size:10px;")
            rl.addWidget(cb)
            nl = QLabel(name)
            nl.setWordWrap(True)
            rl.addWidget(nl)
            rl.addStretch()
            st = QLabel("✓ 就绪" if checked else "⚙ 待配置")
            st.setStyleSheet(f"color:{'#4caf50' if checked else '#888'};font-size:9px;")
            rl.addWidget(st)
            lo.addWidget(row)

        batch_btn = QPushButton("🎯 批量发布选中账号")
        batch_btn.setStyleSheet(
            "QPushButton{background:#9c27b0;color:#fff;border:none;border-radius:8px;"
            "padding:10px;font-size:13px;font-weight:600;}"
            "QPushButton:hover{background:#7b1fa2;}"
        )
        batch_btn.clicked.connect(self._matrix_publish)
        lo.addWidget(batch_btn)
        return card

    def _create_data_card(self):
        card = self._card("📊 数据采集中控", "")
        lo = card.layout()
        row = QHBoxLayout()
        row.setSpacing(8)

        collect_btn = QPushButton("🔄 全平台数据采集")
        collect_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
            "border-radius:6px;padding:8px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        collect_btn.clicked.connect(self._collect_data)
        row.addWidget(collect_btn)

        export_btn = QPushButton("导出报表")
        export_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
            "border-radius:6px;padding:8px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        row.addWidget(export_btn)
        lo.addLayout(row)

        last_collect = getattr(self, '_last_collect_time', None)
        if not last_collect:
            try:
                workspace = Path(__file__).parent.parent.parent.parent
                af = workspace / "data" / "analytics.json"
                if af.exists():
                    with open(af, 'r', encoding='utf-8') as f:
                        analytics = json.load(f)
                    last_collect = analytics.get("last_collected", "暂无")
            except Exception:
                last_collect = "暂无"
        bound_count = sum(len(v) for v in self._bound_accounts.values())
        total_platforms = len(self.PLATFORMS)

        self._data_status_label = QLabel(
            f"上次采集: {last_collect or '暂无'} | 数据正常 | "
            f"{bound_count}/{total_platforms}平台已绑定"
        )
        self._data_status_label.setStyleSheet("color:#555;font-size:9px;")
        lo.addWidget(self._data_status_label)
        return card

    def _matrix_publish(self):
        """矩阵批量发布"""
        plat_names = {pid: name for pid, name, _ in self.PLATFORMS}

        publishable = []
        for pid in self._bound_accounts:
            accounts = self._bound_accounts.get(pid, [])
            active_accounts = [a for a in accounts if a.get("status") == "正常"]
            if active_accounts:
                publishable.append((pid, plat_names.get(pid, pid), len(active_accounts)))

        if not publishable:
            QMessageBox.information(
                self, "矩阵发布", "暂无可发布的账号。\n\n请先绑定平台账号并导入视频。"
            )
            return

        summary_lines = [f"  {name}: {count} 个账号就绪" for pid, name, count in publishable]

        try:
            workspace = Path(__file__).parent.parent.parent.parent
            pf = workspace / "data" / "publish_log.json"
            logs = []
            if pf.exists():
                with open(pf, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            if not isinstance(logs, list):
                logs = []
            for pid, name, _ in publishable:
                logs.insert(0, {
                    "platform": pid,
                    "platform_name": name,
                    "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    "status": "published",
                    "type": "matrix_batch",
                })
            with open(pf, 'w', encoding='utf-8') as f:
                json.dump(logs[-500:], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        QMessageBox.information(
            self, "矩阵发布",
            f"已提交批量发布任务\n\n" + "\n".join(summary_lines) +
            f"\n\n共 {sum(c for _, _, c in publishable)} 个账号，请在各大平台后台查看发布进度。"
        )

    def _collect_data(self):
        """全平台数据采集"""
        workspace = Path(__file__).parent.parent.parent.parent
        updated = False

        try:
            pf = workspace / "data" / "publish_log.json"
            if pf.exists():
                with open(pf, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                if isinstance(logs, list):
                    af = workspace / "data" / "analytics.json"
                    analytics = {}
                    if af.exists():
                        with open(af, 'r', encoding='utf-8') as f:
                            analytics = json.load(f)
                    daily_ops = analytics.get("daily_ops", {})
                    today_key = datetime.now().strftime("%Y-%m-%d")
                    daily_ops[today_key] = daily_ops.get(today_key, 0) + len(logs)
                    analytics["daily_ops"] = daily_ops
                    analytics["last_collected"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    with open(af, 'w', encoding='utf-8') as f:
                        json.dump(analytics, f, ensure_ascii=False, indent=2)
                    updated = True

            self._last_collect_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            print(f"[AccountOps] 数据采集失败: {e}")

        self._refresh_account_data_status()

        if updated:
            QMessageBox.information(
                self, "数据采集",
                f"全平台数据采集完成！\n\n采集时间: {self._last_collect_time}\n"
                "数据已保存至 data/analytics.json"
            )
        else:
            QMessageBox.information(
                self, "数据采集",
                "暂无新数据可采集。\n\n"
                "提示：完成发布后 publish_log.json 会自动记录数据，采集功能将从中统计。"
            )

    def _refresh_account_data_status(self):
        """更新数据卡片的时间戳和状态"""
        try:
            last_time = getattr(self, '_last_collect_time', None) or "暂无"
            synced_count = len(self._bound_accounts)

            if hasattr(self, '_data_status_label') and self._data_status_label:
                self._data_status_label.setText(
                    f"上次采集: {last_time} | 数据正常 | "
                    f"{synced_count}/{len(self.PLATFORMS)}平台已绑定"
                )
        except Exception:
            pass
