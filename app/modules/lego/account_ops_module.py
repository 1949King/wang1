"""
账号运营模块 (AccountOpsModule)
===============================
从 modules.py 拆分出来的独立模块文件。

功能:
- 多平台账号管理（8平台：抖音/快手/视频号/小红书/B站/微博/头条/西瓜）
- 智能运营建议（LLM 驱动）
- 爆款优化建议（account_analyzer → viral_optimization_engine）
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
    QComboBox, QCheckBox, QDialog, QMessageBox, QFileDialog,
    QInputDialog,
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

    # 修复：此前抖音/快手/视频号预置了虚构的"@主账号 12.5万粉"等账号，
    # 首次启动时会让用户误以为自己已经绑定了真实账号、且已有真实粉丝数据。
    # 改为和其余平台一致的空列表，真实状态应通过账号绑定流程获得。
    _DEFAULT_ACCOUNTS = {
        "douyin": [],
        "kuaishou": [],
        "weixin": [],
        "xiaohongshu": [],
        "bilibili": [],
        "weibo": [],
        "toutiao": [],
        "xigua": [],
    }

    _INTEGRATOR_PLATFORM_MAP = {
        "weixin": "shipinhao",
    }

    _REAL_UPLOADER_TYPES = frozenset({"DouyinUploader", "BilibiliUploader"})

    _VIRAL_PLATFORM_MAP = {
        "douyin": "DOUYIN",
        "kuaishou": "KUAISHOU",
        "xiaohongshu": "XIAOHONGSHU",
        "bilibili": "BILIBILI",
        "weixin": "WECHAT",
    }

    def __init__(self):
        register_account_skills()
        self._selected_platform = "douyin"
        self._bound_accounts = self._load_accounts()
        self._viral_engine = None
        self._viral_nav_context: dict[str, dict] = {}
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
        viral_card, drama_nav_btn, editor_nav_btn = self._create_viral_optimization_card(pinfo)
        cl.addWidget(viral_card)
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
        except Exception as e:
            logger.debug(f"[AccountOps] 计算周数据失败: {e}")

        try:
            af = workspace / "data" / "analytics.json"
            if af.exists():
                with open(af, 'r', encoding='utf-8') as f:
                    analytics = json.load(f)
                daily = analytics.get("daily_ops", {})
                for i in range(7):
                    day_key = (today - timedelta(days=i)).strftime("%Y-%m-%d")
                    day_values[i] += daily.get(day_key, 0)
        except Exception as e:
            logger.debug(f"[AccountOps] 加载分析数据失败: {e}")

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
        except Exception as e:
            logger.debug(f"[AccountOps] 解析建议失败: {e}")

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

    def _analyzer_data_dir(self) -> Path:
        return self._workspace_root() / "app" / "运营数据"

    def _get_viral_engine(self):
        if self._viral_engine is not None:
            return self._viral_engine
        try:
            from .viral_optimization_engine import ViralOptimizationEngine
            self._viral_engine = ViralOptimizationEngine()
            return self._viral_engine
        except Exception as e:
            logger.warning(f"[AccountOps] ViralOptimizationEngine 不可用: {e}")
            return None

    def _map_platform_to_viral(self, pid: str, pinfo):
        from .viral_optimization_engine import Platform
        enum_name = self._VIRAL_PLATFORM_MAP.get(pid)
        if enum_name and hasattr(Platform, enum_name):
            return getattr(Platform, enum_name)
        return Platform.DOUYIN

    @staticmethod
    def _sample_video_features():
        from .viral_optimization_engine import VideoFeatures
        return VideoFeatures(
            duration=45.0,
            scene_count=12,
            avg_scene_duration=3.75,
            dialogue_density=0.7,
            emotion_variance=0.6,
            conflict_intensity=0.8,
            hook_quality=65,
            climax_position=0.75,
            has_cliffhanger=True,
            visual_attractiveness=75,
            audio_quality=80,
            subtitle_quality=70,
        )

    @staticmethod
    def _build_video_features_from_analysis(analysis: dict):
        from .viral_optimization_engine import VideoFeatures

        avg_like = float(analysis.get("average_like_rate", 0) or 0)
        avg_comment = float(analysis.get("average_comment_rate", 0) or 0)
        avg_share = float(analysis.get("average_share_rate", 0) or 0)
        avg_views = float(analysis.get("average_views", 0) or 0)

        duration = 45.0
        scene_count = max(3, int(duration / 4))
        hook_quality = min(100.0, max(15.0, avg_like * 1200))
        emotion_variance = min(1.0, max(0.2, (avg_comment + avg_share) * 12))
        conflict_intensity = min(1.0, max(0.3, avg_like * 6))
        visual_score = min(100.0, max(35.0, 40.0 + avg_views / 2000.0))

        return VideoFeatures(
            duration=duration,
            scene_count=scene_count,
            avg_scene_duration=duration / scene_count,
            dialogue_density=0.65,
            emotion_variance=emotion_variance,
            conflict_intensity=conflict_intensity,
            hook_quality=hook_quality,
            climax_position=0.7,
            has_cliffhanger=avg_comment >= 0.012,
            visual_attractiveness=visual_score,
            audio_quality=75.0,
            subtitle_quality=70.0,
        )

    def _create_viral_optimization_card(self, pinfo):
        card = self._card("爆款优化建议", "🔥")
        card.setStyleSheet(
            "QGroupBox{font-size:12px;font-weight:600;color:#ccc;border:1px solid #f97316;"
            "border-radius:10px;margin-top:8px;padding-top:14px;background:#121212;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 6px;}"
        )
        lo = card.layout()

        intro = QLabel(
            "读取 account_analyzer 本地运营数据，经 viral_optimization_engine "
            "生成完播/互动预测与具体优化项（非 LLM 话术）。"
        )
        intro.setStyleSheet("color:#777;font-size:9px;line-height:1.4;")
        intro.setWordWrap(True)
        lo.addWidget(intro)

        status_label = QLabel("尚未分析。点击下方按钮生成建议。")
        status_label.setStyleSheet("color:#888;font-size:10px;")
        status_label.setWordWrap(True)
        lo.addWidget(status_label)

        results_label = QLabel("")
        results_label.setStyleSheet(
            "color:#ccc;font-size:10px;line-height:1.5;"
            "background:#0a0a0a;border-radius:6px;padding:8px;"
        )
        results_label.setWordWrap(True)
        results_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        lo.addWidget(results_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        drama_nav_btn = QPushButton("🎭 去短剧筛选选题")
        drama_nav_btn.setEnabled(False)
        drama_nav_btn.setToolTip("基于爆款分析，跳转插件中心「短剧筛选」挑下一批题材")
        drama_nav_btn.setStyleSheet(
            "QPushButton{background:#7c3aed;color:#fff;border:none;border-radius:6px;"
            "padding:8px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#6d28d9;}"
            "QPushButton:disabled{background:#2a2a2a;color:#555;}"
        )
        drama_nav_btn.clicked.connect(
            lambda _, p=pinfo[0]: self._navigate_to_drama_finder(p)
        )

        editor_nav_btn = QPushButton("✂️ 去剪辑（下一轮粗剪）")
        editor_nav_btn.setEnabled(False)
        editor_nav_btn.setToolTip("带着优化建议进入剪辑，按建议做下一轮粗剪")
        editor_nav_btn.setStyleSheet(
            "QPushButton{background:#1e6bde;color:#fff;border:none;border-radius:6px;"
            "padding:8px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#1557b0;}"
            "QPushButton:disabled{background:#2a2a2a;color:#555;}"
        )
        editor_nav_btn.clicked.connect(
            lambda _, p=pinfo[0]: self._navigate_to_editor_rough_cut(p)
        )

        gen_btn = QPushButton("📊 从运营数据生成")
        gen_btn.setStyleSheet(
            "QPushButton{background:#ea580c;color:#fff;border:none;border-radius:6px;"
            "padding:8px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#c2410c;}"
        )
        gen_btn.clicked.connect(
            lambda _: self._refresh_viral_suggestions(
                pinfo, status_label, results_label, drama_nav_btn, editor_nav_btn,
                use_sample=False,
            )
        )
        btn_row.addWidget(gen_btn)

        sample_btn = QPushButton("🧪 样例分析")
        sample_btn.setToolTip("无本地运营数据时，用内置样例特征演示引擎输出（会明确标注非真实数据）")
        sample_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #444;"
            "border-radius:6px;padding:8px;font-size:11px;font-weight:600;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        sample_btn.clicked.connect(
            lambda _: self._refresh_viral_suggestions(
                pinfo, status_label, results_label, drama_nav_btn, editor_nav_btn,
                use_sample=True,
            )
        )
        btn_row.addWidget(sample_btn)
        lo.addLayout(btn_row)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        nav_row.addWidget(drama_nav_btn)
        nav_row.addWidget(editor_nav_btn)
        lo.addLayout(nav_row)

        return card, drama_nav_btn, editor_nav_btn

    def _refresh_viral_suggestions(
        self, pinfo, status_label, results_label, drama_nav_btn, editor_nav_btn,
        use_sample=False,
    ):
        pid = pinfo[0]
        platform_name = pinfo[1]

        def _set_nav_enabled(enabled: bool):
            drama_nav_btn.setEnabled(enabled)
            editor_nav_btn.setEnabled(enabled)

        engine = self._get_viral_engine()
        if engine is None:
            status_label.setText("❌ 爆款优化引擎加载失败，请检查 viral_optimization_engine 依赖（numpy 等）。")
            results_label.setText("")
            _set_nav_enabled(False)
            return

        try:
            platform = self._map_platform_to_viral(pid, pinfo)
            unsupported = pid not in self._VIRAL_PLATFORM_MAP

            if use_sample:
                features = self._sample_video_features()
                data_source = "内置样例特征（非真实账号数据，仅演示引擎输出格式）"
            else:
                from .account_analyzer import get_account_analyzer

                analyzer = get_account_analyzer(str(self._analyzer_data_dir()))
                analysis = analyzer.analyze_data()
                if "error" in analysis:
                    status_label.setText(
                        f"⚠️ 暂无运营数据（{analysis['error']}）。"
                        f"数据目录：{self._analyzer_data_dir()}。"
                        "可先「全平台数据采集」或点「样例分析」查看引擎输出。"
                    )
                    results_label.setText("")
                    _set_nav_enabled(False)
                    return
                features = self._build_video_features_from_analysis(analysis)
                data_source = (
                    f"本地运营数据（{analysis.get('total_videos', 0)} 条视频，"
                    f"均赞率 {analysis.get('average_like_rate', 0):.2%}）"
                )

            prediction = engine.predict_performance(features, platform)
            suggestions = engine.generate_optimization_suggestions(features, platform)

            platform_note = platform.value
            if unsupported:
                platform_note += "（当前平台暂无专属权重，暂按抖音算法估算）"

            status_label.setText(
                f"✅ 已调用 viral_optimization_engine | 平台：{platform_name} → {platform_note}\n"
                f"数据来源：{data_source}"
            )

            lines = ["【表现预测】"]
            for key, value in prediction.to_dict().items():
                lines.append(f"  · {key}：{value}")

            rough_cut_lines = []
            if suggestions:
                lines.append("")
                lines.append("【优化建议】")
                for i, item in enumerate(suggestions[:5], 1):
                    lines.append(
                        f"{i}. {item.factor.value}（优先级 {item.priority}，"
                        f"{item.current_score:.0f}→{item.target_score:.0f}）"
                    )
                    first_line = item.suggestion.split("\n", 1)[0].strip()
                    lines.append(f"   {first_line}")
                    lines.append(f"   预期改善：{item.expected_improvement}")
                    rough_cut_lines.append(f"{i}. {item.factor.value}：{first_line}")
            else:
                lines.append("")
                lines.append("当前特征已达标，引擎未给出额外优化项。")
                rough_cut_lines.append("当前特征已达标，可按数据趋势挑选新题材做粗剪。")

            results_label.setText("\n".join(lines))

            self._viral_nav_context[pid] = {
                "platform_name": platform_name,
                "platform_id": pid,
                "drama_hint": (
                    f"基于{platform_name}爆款分析，优先筛选完播/互动潜力高的短剧题材。"
                ),
                "rough_cut_hint": "\n".join([
                    f"平台：{platform_name}",
                    "来源：账号运营 · 爆款优化建议",
                    "",
                    "【下一轮粗剪可优先】",
                    *rough_cut_lines,
                    "",
                    "提示：导入素材后可结合 AI 字幕/去水词做第一轮粗剪。",
                ]),
            }
            _set_nav_enabled(True)

        except Exception as e:
            logger.exception("[AccountOps] 爆款优化分析失败")
            status_label.setText(f"❌ 分析失败：{e}")
            results_label.setText("")
            _set_nav_enabled(False)

    def _ensure_module_enabled(self, module_id: str, display_name: str) -> bool:
        from .module_registry import get_registry

        if get_registry().is_enabled(module_id):
            return True
        QMessageBox.warning(
            self,
            "模块未启用",
            f"请先在「设置 → 功能开关」中启用「{display_name}」模块后再跳转。",
        )
        return False

    def _navigate_to_drama_finder(self, platform_id: str):
        ctx = self._viral_nav_context.get(platform_id)
        if not ctx:
            QMessageBox.information(self, "提示", "请先生成爆款优化建议。")
            return
        # M1：注册表已迁 plugins → extensions（拓展中心）
        if not self._ensure_module_enabled("extensions", "拓展中心"):
            return
        from .core import EventType

        self._event_bus.emit(
            EventType.MODULE_ACTIVATED,
            {
                "target": "extensions",
                "action": "drama_finder",
                "hint": ctx.get("drama_hint", ""),
            },
        )

    def _navigate_to_editor_rough_cut(self, platform_id: str):
        ctx = self._viral_nav_context.get(platform_id)
        if not ctx:
            QMessageBox.information(self, "提示", "请先生成爆款优化建议。")
            return
        from .core import EventType

        self._event_bus.emit(
            EventType.MODULE_ACTIVATED,
            {
                "target": "editor",
                "workflow_hint": {
                    "source": "viral_optimization",
                    "title": "下一轮粗剪建议",
                    "platform": ctx.get("platform_name", ""),
                    "body": ctx.get("rough_cut_hint", ""),
                },
            },
        )

    def _workspace_root(self) -> Path:
        return Path(__file__).parent.parent.parent.parent

    def _publish_log_path(self) -> Path:
        return self._workspace_root() / "data" / "publish_log.json"

    def _integrator_platform_id(self, pid: str) -> str:
        return self._INTEGRATOR_PLATFORM_MAP.get(pid, pid)

    def _get_platform_integrator(self):
        try:
            from app.integrations.platforms import PlatformIntegrator
            return PlatformIntegrator()
        except Exception as e:
            logger.warning(f"[AccountOps] PlatformIntegrator 不可用: {e}")
            return None

    def _real_upload_capable(self, integrator, platform_id: str) -> bool:
        if not integrator:
            return False
        iid = self._integrator_platform_id(platform_id)
        client = integrator.get_platform_client(iid)
        if client.get("uploader_type") not in self._REAL_UPLOADER_TYPES:
            return False
        return bool(client.get("uploader_available"))

    def _append_publish_log(self, entry: dict) -> tuple:
        try:
            pf = self._publish_log_path()
            pf.parent.mkdir(parents=True, exist_ok=True)
            logs = []
            if pf.exists():
                with open(pf, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            if not isinstance(logs, list):
                logs = []
            logs.insert(0, entry)
            with open(pf, "w", encoding="utf-8") as f:
                json.dump(logs[-500:], f, ensure_ascii=False, indent=2)
            return True, ""
        except Exception as e:
            logger.warning(f"[AccountOps] 写入 publish_log 失败: {e}")
            return False, str(e)

    def _pick_video_file(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择要发布的视频",
            "",
            "视频文件 (*.mp4 *.mov *.mkv *.avi);;所有文件 (*.*)",
        )
        return path or ""

    def _browse_video_into(self, video_input: QLineEdit):
        path = self._pick_video_file()
        if path:
            video_input.setText(path)

    def _execute_publish(
        self,
        *,
        platform_id: str,
        platform_name: str,
        video_path: str,
        title: str,
        description: str = "",
        tags=None,
        publish_type: str = "quick",
        account_name: str = "",
        duration_label: str = "",
    ) -> dict:
        tags = tags or []
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        receipt = {
            "platform": platform_id,
            "platform_name": platform_name,
            "timestamp": ts,
            "type": publish_type,
            "title": title,
            "description": description,
            "video_path": video_path,
            "account": account_name,
            "duration_label": duration_label,
        }

        if not title.strip():
            receipt.update(status="failed", message="请填写视频标题")
            return receipt

        if not video_path or not os.path.isfile(video_path):
            receipt.update(status="failed", message="请选择有效的视频文件")
            return receipt

        integrator = self._get_platform_integrator()
        iid = self._integrator_platform_id(platform_id)
        real_upload = self._real_upload_capable(integrator, platform_id)

        if not integrator:
            receipt.update(
                status="local_queue",
                receipt_kind="local_queue",
                message="已写入本地发布队列（未连接平台上传接口，不会自动发到平台）",
            )
            ok, err = self._append_publish_log(receipt)
            if not ok:
                receipt.update(status="failed", message=f"本地队列写入失败：{err}")
            return receipt

        try:
            success = integrator.publish_to_platform(
                iid,
                video_path,
                title.strip(),
                description.strip(),
                tags,
            )
        except Exception as e:
            receipt.update(status="failed", message=f"发布异常：{e}")
            self._append_publish_log(receipt)
            return receipt

        if not success:
            receipt.update(
                status="failed",
                message="视频转码/导出失败，未提交到平台",
            )
            self._append_publish_log(receipt)
            return receipt

        base_name = os.path.basename(video_path).rsplit(".", 1)[0]
        export_hint = os.path.join("短剧AI剪辑输出", f"{base_name}_{iid}.mp4")

        if real_upload:
            receipt.update(
                status="upload_attempted",
                receipt_kind="platform_upload",
                message=(
                    f"已尝试通过自动化上传到{platform_name}，"
                    "请在平台创作者后台核对是否出现该作品"
                ),
            )
        else:
            receipt.update(
                status="local_export",
                receipt_kind="local_export",
                export_path=export_hint,
                message=(
                    f"已导出为{platform_name}规格（{export_hint}），"
                    "需手动上传到平台，并未自动发布"
                ),
            )

        ok, err = self._append_publish_log(receipt)
        if not ok:
            receipt["status"] = "failed"
            receipt["message"] = (
                f"发布已完成但记录失败：{err} · {receipt.get('message', '')}"
            )
        return receipt

    def _show_publish_receipt_dialog(self, dialog_title: str, receipts: list):
        lines = []
        for receipt in receipts:
            st = receipt.get("status", "")
            prefix = "❌" if st == "failed" else "ℹ️"
            name = receipt.get("platform_name") or receipt.get("platform", "")
            lines.append(f"{prefix} {name}: {receipt.get('message', '')}")
            if receipt.get("export_path"):
                lines.append(f"   导出路径: {receipt['export_path']}")

        body = "\n".join(lines)
        failed = [r for r in receipts if r.get("status") == "failed"]
        okish = [r for r in receipts if r.get("status") != "failed"]
        if failed and not okish:
            QMessageBox.warning(self, dialog_title, body)
        elif failed:
            QMessageBox.warning(
                self, dialog_title, body + "\n\n部分任务失败，请查看上方明细。"
            )
        else:
            QMessageBox.information(self, dialog_title, body)

    def _quick_publish(
        self,
        pid,
        pinfo,
        title_input,
        desc_input,
        auto_tag,
        video_input,
        duration_combo=None,
    ):
        platform_name = pinfo[1]
        title = title_input.text().strip()
        description = desc_input.text().strip()
        video_path = video_input.text().strip()
        # 修复：此前 dur（发布时长下拉）创建后从未被任何调用方读取，
        # 用户选择"90秒"/"3分钟"完全不生效——现在真正传给 _execute_publish
        # 并写入发布日志，供后续统计/回顾使用。
        duration_label = duration_combo.currentText() if duration_combo is not None else ""

        if not video_path:
            video_path = self._pick_video_file()
            if video_path:
                video_input.setText(video_path)

        tags = []
        if auto_tag.isChecked() and description:
            tags = [t for t in description.split() if t.startswith("#")]

        accounts = self._bound_accounts.get(pid, [])
        active = [a for a in accounts if a.get("status") == "正常"]
        if not active:
            QMessageBox.warning(
                self,
                "快速发布",
                f"暂无可用的{platform_name}绑定账号。\n\n请先在「账号管理」中绑定账号。",
            )
            return

        account_name = active[0].get("name", "")
        receipt = self._execute_publish(
            platform_id=pid,
            platform_name=platform_name,
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            publish_type="quick",
            account_name=account_name,
            duration_label=duration_label,
        )
        self._show_publish_receipt_dialog("快速发布", [receipt])

    def _create_publish_card(self, pinfo):
        card = self._card("快速发布", "📤")
        lo = card.layout()

        video_row = QHBoxLayout()
        video_row.setSpacing(8)
        video_input = QLineEdit()
        video_input.setPlaceholderText("选择视频文件…")
        video_input.setReadOnly(True)
        video_input.setStyleSheet(
            "QLineEdit{background:#0a0a0a;color:#fff;border:1px solid #222;"
            "border-radius:6px;padding:6px 10px;font-size:11px;}"
        )
        video_row.addWidget(video_input, 1)
        browse_btn = QPushButton("浏览…")
        browse_btn.setStyleSheet(
            "QPushButton{background:#2a2a2a;color:#ccc;border:1px solid #333;"
            "border-radius:6px;padding:6px 10px;font-size:10px;}"
            "QPushButton:hover{background:#3a3a3a;color:#fff;}"
        )
        browse_btn.clicked.connect(lambda _: self._browse_video_into(video_input))
        video_row.addWidget(browse_btn)
        lo.addLayout(video_row)

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
        pub_btn.clicked.connect(
            lambda _: self._quick_publish(
                pinfo[0], pinfo, title_input, desc, auto_tag, video_input, dur
            )
        )
        lo.addWidget(pub_btn)

        hint = QLabel("说明：未接平台 API 时为本地导出/队列，不会假装已发到平台。")
        hint.setStyleSheet("color:#666;font-size:9px;")
        hint.setWordWrap(True)
        lo.addWidget(hint)
        return card

    def _create_matrix_card(self):
        card = self._card("🎯 矩阵发布（全平台批量）", "")
        lo = card.layout()
        desc = QLabel(
            "将向左侧各平台已绑定的正常账号提交任务；需选择视频。"
            "未接平台 API 时为本地导出/队列，下方勾选仅为示意尚未接线。"
        )
        desc.setWordWrap(True)
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

        collect_btn = QPushButton("🔄 汇总本地发布日志")
        collect_btn.setToolTip("将本地 publish_log.json 的发布记录汇总进 analytics.json；不会联网拉取各平台真实播放/互动数据")
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
        # 修复：此前创建了按钮但从未 connect，点击「导出报表」完全无响应（死按钮）
        export_btn.clicked.connect(self._export_report)
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
        """矩阵批量发布 — 诚实回执，禁止假成功"""
        plat_names = {pid: name for pid, name, _ in self.PLATFORMS}

        publishable = []
        for pid in self._bound_accounts:
            accounts = self._bound_accounts.get(pid, [])
            active_accounts = [a for a in accounts if a.get("status") == "正常"]
            if active_accounts:
                publishable.append(
                    (pid, plat_names.get(pid, pid), active_accounts)
                )

        if not publishable:
            QMessageBox.information(
                self,
                "矩阵发布",
                "暂无可发布的账号。\n\n请先在各平台绑定账号（状态为「正常」）。",
            )
            return

        video_path = self._pick_video_file()
        if not video_path:
            return

        title, ok = QInputDialog.getText(
            self, "矩阵发布", "视频标题（所有平台共用）："
        )
        if not ok or not title.strip():
            QMessageBox.warning(self, "矩阵发布", "请填写视频标题。")
            return

        receipts = []
        for pid, name, active_accounts in publishable:
            account_name = ", ".join(a.get("name", "") for a in active_accounts)
            receipts.append(
                self._execute_publish(
                    platform_id=pid,
                    platform_name=name,
                    video_path=video_path,
                    title=title.strip(),
                    description="",
                    publish_type="matrix_batch",
                    account_name=account_name,
                )
            )

        self._show_publish_receipt_dialog("矩阵发布", receipts)

    def _collect_data(self):
        """汇总本地发布日志到 analytics.json

        如实说明：这里不会联网调用任何平台 API 拉取真实播放量/互动数据，
        只是把本地 publish_log.json 里已有的发布记录条数汇总进
        analytics.json。此前按钮叫"全平台数据采集"、完成后弹"全平台数据
        采集完成"，容易让人误以为真的从抖音/快手等平台拉取了最新数据。
        """
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
                self, "数据汇总",
                f"本地发布日志汇总完成！\n\n汇总时间: {self._last_collect_time}\n"
                "数据已保存至 data/analytics.json\n\n"
                "⚠️ 仅统计本地 publish_log.json 记录数，不联网拉取各平台真实播放/互动数据"
            )
        else:
            QMessageBox.information(
                self, "数据汇总",
                "暂无新数据可汇总。\n\n"
                "提示：完成发布后 publish_log.json 会自动记录数据，汇总功能将从中统计。"
            )

    def _export_report(self):
        """导出运营报表（账号绑定状态 + 本地汇总统计）为 JSON 文件

        修复：此前按钮从未 connect，点击完全没反应（死按钮）。
        导出内容如实标注数据来源，不虚构未采集到的指标。
        """
        workspace = Path(__file__).parent.parent.parent.parent
        analytics = {}
        try:
            af = workspace / "data" / "analytics.json"
            if af.exists():
                with open(af, 'r', encoding='utf-8') as f:
                    analytics = json.load(f)
        except Exception as e:
            logger.warning(f"读取 analytics.json 失败: {e}")

        plat_names = {pid: name for pid, name, _ in self.PLATFORMS}
        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": "accounts 为本地绑定记录，daily_ops 来自本地 publish_log.json 汇总；均非各平台实时官方数据",
            "accounts": {
                plat_names.get(pid, pid): accounts
                for pid, accounts in self._bound_accounts.items() if accounts
            },
            "daily_ops": analytics.get("daily_ops", {}),
            "last_collected": analytics.get("last_collected", "暂无"),
        }

        default_name = f"运营报表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "导出报表", default_name, "JSON 文件 (*.json)")
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "导出成功", f"报表已保存至：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"写入文件失败：{e}")

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
        except Exception as e:
            logger.debug(f"[AccountOps] 更新状态标签失败: {e}")
