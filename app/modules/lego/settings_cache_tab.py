# -*- coding: utf-8 -*-
"""缓存管理标签页（2026-11-13 重做）。

## 为什么重做

原来是"一行一类 + 一个清理按钮"：

- 点「清理」= **整类全删**，用户不知道会删什么（AI 模型缓存 44.6 GB 一下全没）；
- 想只删"自己不用了的那个模型"根本做不到；
- 也看不到里面到底有哪些东西。

现在改成**可展开的分类**：每类可展开成条目列表（文件夹/文件），每条可单独删除；
"清理"按钮也改成明确提示"将删除 N 项 / 共 X GB"，并保留"全部分类"的显式确认。
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("AI短剧编辑器.cache_tab")

#: (key, 图标, 显示名, 说明)
CATEGORIES: List[Tuple[str, str, str, str]] = [
    ("render_cache", "📁", "渲染缓存", "FFmpeg 渲染中间文件"),
    ("preview_cache", "🎬", "预览缓存", "视频预览缩略图 / 代理"),
    ("model_cache", "🤖", "AI 模型缓存", "Whisper / Coqui TTS 等模型文件"),
    ("temp_cache", "📝", "临时项目文件", "项目自动备份和临时文件"),
]

#: key → 相对路径列表（"~" 开头表示用户目录）
DIRS = {
    "render_cache": ["render_cache", "temp_ai_editor", "短剧AI剪辑输出"],
    "preview_cache": ["preview_cache", ".thumb_cache", "cache/proxies"],
    "model_cache": ["models", "~/.cache/whisper", "~/.cache/coqui"],
    "temp_cache": ["temp", ".backup", "temp_ai_editor"],
}


def _app_root() -> Path:
    # app/modules/lego/settings_cache_tab.py → 上溯到 app/
    return Path(__file__).resolve().parent.parent.parent


def resolve_dir(raw: str) -> Path:
    if raw.startswith("~"):
        return Path.home() / raw[2:]
    return _app_root() / raw


def fmt_size(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def path_size(p: Path) -> int:
    """文件/目录占用（目录递归求和；读不到的项按 0 处理）。"""
    try:
        if p.is_file():
            return p.stat().st_size
        total = 0
        for root, _dirs, files in os.walk(p):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
        return total
    except OSError:
        return 0


def _entry_dirs(key: str) -> List[Path]:
    """某类缓存的"条目根"。

    AI 模型缓存有个统一容器 `models/cache/`（模型都在它里面），
    如果只列 `models/` 一级，用户只能看到唯一一项 `cache`（45 GB），
    没法删"某一个模型"。所以有容器时直接列出容器里的模型。
    """
    roots: List[Path] = []
    for raw in DIRS.get(key, []):
        p = resolve_dir(raw)
        if not p.is_dir():
            continue
        target = p
        if key == "model_cache":
            cache = p / "cache"
            if cache.is_dir():
                try:
                    if any(cache.iterdir()):
                        target = cache
                except OSError:  # stability-gate: allow-swallow（读不到目录就按原目录列，不影响清理）
                    logger.debug("模型缓存容器不可读: %s", cache)
        roots.append(target)
    return roots


def list_entries(key: str) -> List[Tuple[Path, int, bool]]:
    """展开某类缓存：返回其下**一级条目**（目录或文件）及占用。"""
    out: List[Tuple[Path, int, bool]] = []
    seen = set()
    for root in _entry_dirs(key):
        try:
            children = sorted(root.iterdir(), key=lambda x: x.name.lower())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):  # 锁文件之类的噪音不展示
                continue
            k = str(child)
            if k in seen:
                continue
            seen.add(k)
            try:
                is_dir = child.is_dir()
            except OSError:
                is_dir = False
            out.append((child, path_size(child), is_dir))
    return out


def category_size(key: str) -> int:
    return sum(size for _p, size, _d in list_entries(key))


def delete_entry(p: Path) -> bool:
    """删除单个条目（目录递归）。失败返回 False，不抛异常。"""
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return True
    except OSError as e:
        logger.warning("删除缓存条目失败 %s: %s", p, e)
        return False


def clear_category(key: str) -> Tuple[int, int]:
    """清理整类：删除目录内容但保留目录本身。返回 (删除项数, 释放字节)。"""
    removed = 0
    freed = 0
    for p in _entry_dirs(key):
        try:
            children = [c for c in p.iterdir() if not c.name.startswith(".")]
        except OSError:
            continue
        for child in children:
            size = path_size(child)
            if delete_entry(child):
                removed += 1
                freed += size
    return removed, freed


def build_cache_tab(owner: QWidget) -> QWidget:
    """构建缓存管理页（owner 用于 QMessageBox 的父窗口）。"""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    title = QLabel("🗑️ 缓存管理")
    layout.addWidget(title)
    desc = QLabel("点「展开」查看具体文件后**逐项清理**；「清理全部」会先告诉你将删除多少项、多少空间。")
    desc.setStyleSheet("color:#999;font-size:13px;")
    desc.setWordWrap(True)
    layout.addWidget(desc)

    def _ask(text: str) -> bool:
        return QMessageBox.question(
            owner, "确认清理", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    cards = {}

    def _make_item_row(p: Path, size: int, is_dir: bool, refresh) -> QWidget:
        row = QFrame()
        row.setStyleSheet("QFrame{background:#141414;border-radius:6px;}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 6, 10, 6)
        icon = QLabel("📁" if is_dir else "📄")
        icon.setFixedWidth(22)
        rl.addWidget(icon)
        name = QLabel(p.name if p.name else str(p))
        name.setStyleSheet("color:#ddd;font-size:12px;")
        name.setToolTip(str(p))
        rl.addWidget(name, 1)
        sz = QLabel(fmt_size(size))
        sz.setStyleSheet("color:#666;font-size:11px;")
        sz.setFixedWidth(80)
        rl.addWidget(sz)

        open_btn = QPushButton("打开目录")
        open_btn.setStyleSheet("QPushButton{background:#232323;color:#aaa;border:none;border-radius:4px;padding:4px 10px;font-size:11px;}QPushButton:hover{background:#2e2e2e;}")
        open_btn.clicked.connect(lambda _=False, path=p: _open_dir(path))
        rl.addWidget(open_btn)

        del_btn = QPushButton("删除")
        del_btn.setStyleSheet("QPushButton{background:#7f1d1d;color:#fff;border:none;border-radius:4px;padding:4px 12px;font-size:11px;}QPushButton:hover{background:#991b1b;}")
        del_btn.clicked.connect(lambda _=False, path=p, s=size: _delete_single(path, s, refresh))
        rl.addWidget(del_btn)
        return row

    def _open_dir(p: Path) -> None:
        target = p if p.is_dir() else p.parent
        try:
            os.startfile(str(target))  # noqa: SIN104（Windows 打开资源管理器）
        except Exception:  # stability-gate: allow-swallow（打不开目录不影响清理）
            logger.debug("打开目录失败: %s", target, exc_info=True)

    def _delete_single(p: Path, size: int, refresh) -> None:
        if not _ask(f"确定删除？\n\n{p}\n\n约释放 {fmt_size(size)}，删除后不可恢复。"):
            return
        ok = delete_entry(p)
        if ok:
            QMessageBox.information(owner, "已删除", f"已删除：{p.name}\n释放约 {fmt_size(size)}")
        else:
            QMessageBox.warning(owner, "删除失败", f"删不掉（可能被占用）：\n{p}")
        refresh()

    def _card(key: str, icon: str, name: str, desc: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet("QFrame{background:#1a1a1a;border-radius:8px;}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(6)

        head = QHBoxLayout()
        ic = QLabel(icon)
        ic.setStyleSheet("font-size:20px;")
        head.addWidget(ic)

        info = QVBoxLayout()
        nm = QLabel(name)
        nm.setStyleSheet("color:#ccc;font-size:13px;font-weight:600;")
        info.addWidget(nm)
        sub = QLabel(desc)
        sub.setStyleSheet("color:#666;font-size:11px;")
        info.addWidget(sub)
        head.addLayout(info, 1)

        size_lbl = QLabel("计算中…")
        size_lbl.setStyleSheet("color:#888;font-size:11px;")
        head.addWidget(size_lbl)

        expand_btn = QPushButton("展开 ▾")
        expand_btn.setCheckable(True)
        expand_btn.setStyleSheet(
            "QPushButton{background:#232323;color:#ccc;border:none;border-radius:4px;padding:6px 12px;font-size:11px;}"
            "QPushButton:checked{background:#2f3b52;color:#cfe0ff;}"
            "QPushButton:hover{background:#2e2e2e;}"
        )
        head.addWidget(expand_btn)

        clear_btn = QPushButton("清理")
        clear_btn.setStyleSheet("QPushButton{background:#c62828;color:#fff;border:none;border-radius:4px;padding:6px 16px;font-size:11px;}QPushButton:hover{background:#b71c1c;}")
        head.addWidget(clear_btn)
        cl.addLayout(head)

        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 4, 0, 0)
        holder_layout.setSpacing(4)
        holder.setVisible(False)
        cl.addWidget(holder)

        def refresh_sizes() -> None:
            entries = list_entries(key)
            total = sum(s for _p, s, _d in entries)
            size_lbl.setText(f"{fmt_size(total)}（{len(entries)} 项）" if entries else "无需清理")
            # 重建条目列表
            while holder_layout.count():
                item = holder_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            if not entries:
                empty = QLabel("这里现在是空的。")
                empty.setStyleSheet("color:#555;font-size:11px;")
                holder_layout.addWidget(empty)
                return
            for p, size, is_dir in entries:
                holder_layout.addWidget(_make_item_row(p, size, is_dir, refresh_sizes))

        def on_expand(checked: bool) -> None:
            expand_btn.setText("收起 ▴" if checked else "展开 ▾")
            holder.setVisible(checked)
            if checked:
                refresh_sizes()

        expand_btn.toggled.connect(on_expand)

        def on_clear() -> None:
            entries = list_entries(key)
            if not entries:
                QMessageBox.information(owner, "无需清理", f"{name} 已经是空的。")
                return
            total = sum(s for _p, s, _d in entries)
            if not _ask(f"清理【{name}】全部内容？\n\n将删除 {len(entries)} 项，释放约 {fmt_size(total)}。\n"
                        f"（想只删其中几个，请先「展开」逐项删除）"):
                return
            removed, freed = clear_category(key)
            QMessageBox.information(owner, "完成", f"已删除 {removed} 项，释放约 {fmt_size(freed)}")
            refresh_sizes()

        clear_btn.clicked.connect(lambda _=False: on_clear())
        refresh_sizes()
        cards[key] = (card, refresh_sizes)
        return card

    for key, icon, name, desc in CATEGORIES:
        layout.addWidget(_card(key, icon, name, desc))

    # 全部清理（显式列出总量）
    all_card = QFrame()
    all_card.setStyleSheet("QFrame{background:#2a1a1a;border:1px solid #5a2020;border-radius:8px;}")
    al = QHBoxLayout(all_card)
    al.setContentsMargins(12, 10, 12, 10)
    aic = QLabel("🧹")
    aic.setStyleSheet("font-size:20px;")
    al.addWidget(aic)
    ainfo = QVBoxLayout()
    anm = QLabel("全部缓存")
    anm.setStyleSheet("color:#f0b0b0;font-size:13px;font-weight:600;")
    ainfo.addWidget(anm)
    asub = QLabel("清理以上所有分类（同样会先确认将删除多少）")
    asub.setStyleSheet("color:#a07070;font-size:11px;")
    ainfo.addWidget(asub)
    al.addLayout(ainfo, 1)
    all_size = QLabel("")
    all_size.setStyleSheet("color:#c08080;font-size:11px;")
    al.addWidget(all_size)

    def refresh_all() -> None:
        entries = []
        for key, _i, _n, _d in CATEGORIES:
            entries.extend(list_entries(key))
        total = sum(s for _p, s, _d in entries)
        all_size.setText(f"{fmt_size(total)}（{len(entries)} 项）" if entries else "无需清理")

    def on_clear_all() -> None:
        entries = []
        for key, _i, _n, _d in CATEGORIES:
            entries.extend(list_entries(key))
        if not entries:
            QMessageBox.information(owner, "无需清理", "所有缓存都是空的。")
            return
        total = sum(s for _p, s, _d in entries)
        if not _ask(f"清理全部缓存？\n\n将删除 {len(entries)} 项，释放约 {fmt_size(total)}。"):
            return
        removed = freed = 0
        for key, _i, _n, _d in CATEGORIES:
            r, f = clear_category(key)
            removed += r
            freed += f
        QMessageBox.information(owner, "完成", f"已删除 {removed} 项，释放约 {fmt_size(freed)}")
        for _k, (_c, refresh) in cards.items():
            refresh()
        refresh_all()

    all_btn = QPushButton("清理全部")
    all_btn.setStyleSheet("QPushButton{background:#c62828;color:#fff;border:none;border-radius:4px;padding:6px 16px;font-size:11px;}QPushButton:hover{background:#b71c1c;}")
    all_btn.clicked.connect(lambda _=False: on_clear_all())
    al.addWidget(all_btn)
    layout.addWidget(all_card)
    refresh_all()

    layout.addStretch()
    scroll.setWidget(host)
    outer.addWidget(scroll)
    return page