"""
素材库 · 提示词库面板
====================
细分类 / 尺度 / 收藏夹 / 同步源 / 复制与应用。
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QComboBox, QListWidget, QListWidgetItem, QTextEdit, QMessageBox,
    QCheckBox, QSplitter, QFrame, QScrollArea, QButtonGroup, QSizePolicy,
)

from .prompt_library_store import (
    PromptLibraryStore,
    PromptItem,
    categories_grouped,
    maturity_label,
)

logger = logging.getLogger("AI短剧编辑器.prompt_library_panel")


class _SyncWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_ok = pyqtSignal(int, int, int)

    def __init__(self, store: PromptLibraryStore, parent=None):
        super().__init__(parent)
        self._store = store

    def run(self):
        def prog(i, n, name):
            self.progress.emit(i, n, name)

        ok, fail, total = self._store.refresh_enabled(progress=prog)
        self.finished_ok.emit(ok, fail, total)


class PromptLibraryPanel(QWidget):
    """提示词库分区 UI。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = PromptLibraryStore()
        self._favorites_only = False
        self._worker: Optional[_SyncWorker] = None
        self._current: Optional[PromptItem] = None
        self._cat_btns: dict = {}
        self._setup_ui()
        # 先加载本地包，远程可点同步
        self._bootstrap_local()
        self._reload_list()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        tip = QLabel(
            "提示词库分区：GitHub JSON 源 + 本地短剧/成人包。可收藏、按细分类浏览。"
            "成人源默认关闭；内容仅面向成年人。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#808080;font-size:12px;")
        root.addWidget(tip)

        # 工具栏
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索标题 / 提示词 / 标签…")
        self._search.setStyleSheet(self._input_ss())
        self._search.textChanged.connect(lambda _: self._reload_list())
        bar.addWidget(self._search, 1)

        self._maturity = QComboBox()
        self._maturity.addItem("全部尺度", "all")
        self._maturity.addItem("全年龄", "sfw")
        self._maturity.addItem("成熟向", "mature")
        self._maturity.addItem("成人向 18+", "nsfw")
        self._maturity.setStyleSheet(self._combo_ss())
        self._maturity.currentIndexChanged.connect(lambda _: self._reload_list())
        bar.addWidget(self._maturity)

        self._fav_btn = QPushButton("★ 我的收藏")
        self._fav_btn.setCheckable(True)
        self._fav_btn.setStyleSheet(self._chip_ss())
        self._fav_btn.clicked.connect(self._toggle_favorites_view)
        bar.addWidget(self._fav_btn)

        self._sync_btn = QPushButton("同步源")
        self._sync_btn.setStyleSheet(self._primary_ss())
        self._sync_btn.clicked.connect(self._on_sync)
        bar.addWidget(self._sync_btn)
        root.addLayout(bar)

        # 主体：左分类 + 中列表 + 右详情
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setStyleSheet("QSplitter::handle{background:#2a2a2a;width:2px;}")

        # 左：分类
        left = QFrame()
        left.setStyleSheet("QFrame{background:#141414;border:1px solid #252525;border-radius:8px;}")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(8, 8, 8, 8)
        left_l.addWidget(QLabel("细分类"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        cat_host = QWidget()
        self._cat_layout = QVBoxLayout(cat_host)
        self._cat_layout.setSpacing(4)
        self._cat_layout.setContentsMargins(0, 0, 0, 0)
        self._cat_group = QButtonGroup(self)
        self._cat_group.setExclusive(True)
        all_btn = QPushButton("全部")
        all_btn.setCheckable(True)
        all_btn.setChecked(True)
        all_btn.setProperty("cat_id", "all")
        all_btn.setStyleSheet(self._cat_btn_ss())
        self._cat_group.addButton(all_btn)
        self._cat_layout.addWidget(all_btn)
        self._cat_btns["all"] = all_btn
        for group, items in categories_grouped():
            gl = QLabel(group)
            gl.setStyleSheet("color:#6b7280;font-size:11px;margin-top:8px;")
            self._cat_layout.addWidget(gl)
            for cid, label, mat in items:
                b = QPushButton(label + (f" ·{maturity_label(mat)}" if mat != "sfw" else ""))
                b.setCheckable(True)
                b.setProperty("cat_id", cid)
                b.setStyleSheet(self._cat_btn_ss())
                self._cat_group.addButton(b)
                self._cat_layout.addWidget(b)
                self._cat_btns[cid] = b
        self._cat_layout.addStretch()
        self._cat_group.buttonClicked.connect(lambda _: self._reload_list())
        scroll.setWidget(cat_host)
        left_l.addWidget(scroll, 1)

        # 源开关（折叠感：下方小块）
        src_title = QLabel("数据源")
        src_title.setStyleSheet("color:#6b7280;font-size:11px;margin-top:6px;")
        left_l.addWidget(src_title)
        self._src_box = QVBoxLayout()
        self._src_checks: dict = {}
        for s in self._store.sources:
            cb = QCheckBox(s.name + (" 🔞" if s.adult else ""))
            cb.setChecked(s.enabled)
            cb.setStyleSheet("color:#ccc;font-size:11px;")
            cb.stateChanged.connect(lambda st, sid=s.id, adult=s.adult: self._on_source_toggle(sid, st, adult))
            self._src_checks[s.id] = cb
            self._src_box.addWidget(cb)
        left_l.addLayout(self._src_box)

        split.addWidget(left)

        # 中：列表
        mid = QFrame()
        mid.setStyleSheet("QFrame{background:#111;border:1px solid #252525;border-radius:8px;}")
        mid_l = QVBoxLayout(mid)
        mid_l.setContentsMargins(6, 6, 6, 6)
        self._status = QLabel("共 0 条")
        self._status.setStyleSheet("color:#808080;font-size:11px;")
        mid_l.addWidget(self._status)
        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background:#0d0d0d; color:#ddd; border:none; font-size:12px;
            }
            QListWidget::item { padding:10px 8px; border-bottom:1px solid #1a1a1a; }
            QListWidget::item:hover { background:#1a2530; }
            QListWidget::item:selected { background:#112244; color:#fff; }
        """)
        self._list.currentItemChanged.connect(self._on_select)
        mid_l.addWidget(self._list, 1)
        split.addWidget(mid)

        # 右：详情
        right = QFrame()
        right.setStyleSheet("QFrame{background:#141414;border:1px solid #252525;border-radius:8px;}")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(10, 10, 10, 10)
        self._detail_title = QLabel("选择一条提示词")
        self._detail_title.setWordWrap(True)
        self._detail_title.setStyleSheet("font-size:15px;font-weight:bold;color:#fff;")
        right_l.addWidget(self._detail_title)
        self._detail_meta = QLabel("")
        self._detail_meta.setWordWrap(True)
        self._detail_meta.setStyleSheet("color:#808080;font-size:11px;")
        right_l.addWidget(self._detail_meta)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        self._detail_text.setStyleSheet(
            "QTextEdit{background:#0d0d0d;color:#ddd;border:1px solid #222;border-radius:6px;padding:8px;font-size:12px;}"
        )
        right_l.addWidget(self._detail_text, 1)

        act = QHBoxLayout()
        self._star_btn = QPushButton("☆ 收藏")
        self._star_btn.setStyleSheet(self._chip_ss())
        self._star_btn.clicked.connect(self._on_toggle_fav)
        act.addWidget(self._star_btn)
        copy_btn = QPushButton("复制提示词")
        copy_btn.setStyleSheet(self._primary_ss())
        copy_btn.clicked.connect(self._on_copy)
        act.addWidget(copy_btn)
        canvas_btn = QPushButton("发送到画布")
        canvas_btn.setStyleSheet(self._chip_ss())
        canvas_btn.clicked.connect(self._on_send_canvas)
        act.addWidget(canvas_btn)
        act.addStretch()
        right_l.addLayout(act)
        split.addWidget(right)

        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 3)
        split.setSizes([220, 360, 360])
        root.addWidget(split, 1)

    def _bootstrap_local(self):
        for s in self._store.sources:
            if s.enabled and s.local:
                self._store.load_source(s)

    def _selected_category_id(self) -> str:
        btn = self._cat_group.checkedButton()
        if not btn:
            return "all"
        return str(btn.property("cat_id") or "all")

    def _reload_list(self):
        maturity = self._maturity.currentData() or "all"
        items = self._store.query(
            keyword=self._search.text(),
            category_id=self._selected_category_id(),
            maturity=maturity,
            favorites_only=self._favorites_only,
        )
        self._list.clear()
        for it in items[:500]:
            star = "★ " if it.favorite else ""
            badge = maturity_label(it.maturity)
            text = f"{star}{it.title}\n[{it.category_group} · {it.category} · {badge}]  {it.source_name}"
            lw = QListWidgetItem(text)
            lw.setData(Qt.ItemDataRole.UserRole, (it.source_id, it.id))
            lw.setToolTip(it.prompt[:300])
            self._list.addItem(lw)
        mode = "收藏" if self._favorites_only else "全部匹配"
        self._status.setText(f"{mode} · 共 {len(items)} 条" + ("（仅显示前 500）" if len(items) > 500 else ""))
        if not items:
            self._detail_title.setText("暂无内容" if not self._favorites_only else "收藏夹为空")
            self._detail_meta.setText("点「同步源」拉取 GitHub；或勾选成人源后同步。启用收藏后可在此查看。")
            self._detail_text.clear()
            self._current = None

    def _on_select(self, cur: Optional[QListWidgetItem], _prev=None):
        if not cur:
            return
        data = cur.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        sid, iid = data
        it = self._store.get_item(sid, iid)
        if not it:
            return
        self._current = it
        self._detail_title.setText(it.title)
        self._detail_meta.setText(
            f"{it.category_group} · {it.category} · {maturity_label(it.maturity)}"
            f"  |  源：{it.source_name}"
            f"  |  标签：{', '.join(it.tags[:8]) or '—'}"
        )
        self._detail_text.setPlainText(it.prompt)
        self._star_btn.setText("★ 已收藏" if it.favorite else "☆ 收藏")

    def _toggle_favorites_view(self):
        self._favorites_only = self._fav_btn.isChecked()
        self._fav_btn.setText("★ 查看全部" if self._favorites_only else "★ 我的收藏")
        self._reload_list()

    def _on_toggle_fav(self):
        it = self._current
        if not it:
            QMessageBox.information(self, "提示", "请先选择一条提示词")
            return
        now = self._store.toggle_favorite(it.source_id, it.id)
        it.favorite = now
        self._star_btn.setText("★ 已收藏" if now else "☆ 收藏")
        self._reload_list()
        # 重新选中
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data == (it.source_id, it.id):
                self._list.setCurrentItem(item)
                break

    def _on_copy(self):
        it = self._current
        if not it:
            return
        QGuiApplication.clipboard().setText(it.prompt)
        QMessageBox.information(self, "已复制", "提示词已复制到剪贴板")

    def _on_send_canvas(self):
        it = self._current
        if not it:
            return
        try:
            from .core import EventBus, EventType
            EventBus.get_instance().emit(
                EventType.MODULE_ACTIVATED,
                {
                    "target": "characters",
                    "action": "apply_prompt",
                    "prompt": it.prompt,
                    "title": it.title,
                },
                source="materials_prompt_lib",
            )
            QMessageBox.information(self, "已发送", "已请求打开 AI 画布并携带提示词（若画布已接线 apply_prompt）。")
        except Exception as e:
            # 至少复制
            QGuiApplication.clipboard().setText(it.prompt)
            QMessageBox.information(self, "已复制", f"画布跳转未接通（{e}），提示词已复制到剪贴板。")

    def _on_source_toggle(self, source_id: str, state: int, adult: bool):
        enabled = state == Qt.CheckState.Checked.value or state is True or state == 2
        if adult and enabled:
            r = QMessageBox.question(
                self,
                "启用成人向源",
                "即将启用「成人向 18+」提示词源。\n内容仅面向成年人，禁止未成年人相关描述。\n确认启用？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                cb = self._src_checks.get(source_id)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                return
        self._store.set_source_enabled(source_id, bool(enabled))
        if enabled:
            src = next((s for s in self._store.sources if s.id == source_id), None)
            if src:
                self._store.load_source(src)
        self._reload_list()

    def _on_sync(self):
        if self._worker and self._worker.isRunning():
            return
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("同步中…")
        self._status.setText("正在同步 GitHub 提示词源…")
        self._worker = _SyncWorker(self._store, self)
        self._worker.progress.connect(
            lambda i, n, name: self._status.setText(f"同步 {i}/{n}：{name}")
        )
        self._worker.finished_ok.connect(self._on_sync_done)
        self._worker.start()

    def _on_sync_done(self, ok: int, fail: int, total: int):
        self._sync_btn.setEnabled(True)
        self._sync_btn.setText("同步源")
        self._status.setText(f"同步完成：{total} 条（{ok} 源成功" + (f"，{fail} 源失败）" if fail else "）"))
        self._reload_list()

    # —— styles ——
    @staticmethod
    def _input_ss() -> str:
        return (
            "QLineEdit{background:#1a1a1a;color:#eee;border:1px solid #333;border-radius:6px;"
            "padding:6px 10px;font-size:12px;}"
        )

    @staticmethod
    def _combo_ss() -> str:
        return (
            "QComboBox{background:#1a1a1a;color:#eee;border:1px solid #333;border-radius:6px;"
            "padding:5px 8px;font-size:12px;min-width:110px;}"
            "QComboBox QAbstractItemView{background:#1a1a1a;color:#eee;selection-background-color:#1e6bde;}"
        )

    @staticmethod
    def _chip_ss() -> str:
        return """
            QPushButton {
                background:#2a2a2a;color:#ccc;border:1px solid #333;border-radius:6px;
                padding:6px 12px;font-size:12px;
            }
            QPushButton:hover { background:#3a3a3a;color:#fff; }
            QPushButton:checked { background:#854d0e;color:#fff;border-color:#a16207; }
        """

    @staticmethod
    def _primary_ss() -> str:
        return """
            QPushButton {
                background:#1e6bde;color:#fff;border:none;border-radius:6px;
                padding:6px 14px;font-size:12px;
            }
            QPushButton:hover { background:#1557b0; }
            QPushButton:disabled { background:#333;color:#777; }
        """

    @staticmethod
    def _cat_btn_ss() -> str:
        return """
            QPushButton {
                text-align:left; background:transparent; color:#aaa;
                border:none; border-radius:4px; padding:5px 8px; font-size:11px;
            }
            QPushButton:hover { background:#1f1f1f; color:#fff; }
            QPushButton:checked { background:#1e6bde33; color:#93c5fd; }
        """
