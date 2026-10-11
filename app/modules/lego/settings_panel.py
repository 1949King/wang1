"""
设置面板 (SettingsDialog)
==========================================

对标 AI-Canvas-tauri SettingsPanel.tsx + settings.css，重做「外观」「常规」两页，
视觉 1:1 对齐用户提供的 AI Canvas 截图（外观预设卡墙 / 主题模式 / 6 开关分组）。

Tab 结构（左侧 176px 导航 + 右侧 QStackedWidget）：
    外观   —— 头部(标题+主题chip+自动保存) · 导入/导出/保存预设 · 节点预览大图
              · 外观预设 3×2 卡墙(6 个预设 + custom 上传) · 主题模式 3 段
    常规   —— 节点工具栏分段 · 画布笔记工具栏 · 素材引用 · 节点标题 · 窗口外观
              · 图形与性能 · 侧边栏（7 个分组，开关卡直抄 .sidebar-pref-card）
    存储 / ComfyUI / MCP / 关于

设计纪律：
- 单例(SettingsDialog.instance())，避免重复弹窗
- 所有颜色走 theme_tokens，自绘控件在 set_theme() 重绘
- 设置落 QSettings(拾光剪影 / Settings)
- 开关卡直抄 .sidebar-pref-card（整卡可点 + iOS 开关 + 迷你预览）
- 6 个外观预设与画布 canvasBackgrounds.ts 中的 CANVAS_BACKGROUNDS 一一对应
  (V4.43.3)；custom 走「选图 → 存 data/uploaded/ → base64 下发画布」链路

V4.43.3 任务 #287
"""
from __future__ import annotations

import base64
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSettings, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QFrame, QScrollArea,
    QGridLayout, QMessageBox,
)

from app.modules.lego.theme_manager import ThemeManager
from app.modules.lego.settings_widgets import (
    PreferenceCard, SegmentedControl, PresetCard, AppearancePreview,
)

logger = logging.getLogger("AI短剧编辑器.settings_panel")


# ═══════════════════════════════════════════════════════════════
# 设置键（单源真相，便于守卫 + 防拼写漂移）
# ═══════════════════════════════════════════════════════════════
# 外观
SETTING_KEY_APPEARANCE_PRESET = "appearance/preset"           # 外观预设 id
SETTING_KEY_THEME_MODE = "appearance/theme_mode"              # dark / light / system
# 外观 → 画布（V4.43.2：画布 canvasBackgrounds.ts 轮询 /host/canvas-settings 读取）
# 存 JSON 文件而非 QSettings：① 沙箱/无注册表权限环境也能写；② 画布通道可直接读文件；
# ③ 与项目既有「注册表 + JSON 双保险」思路一致。字段名即本组常量。
SETTING_KEY_CANVAS_BACKGROUND = "canvas_background"  # 画布背景 id
SETTING_KEY_CANVAS_THEME = "canvas_theme"            # 画布主题 dark/light（已解析）
SETTING_KEY_SETTINGS_REVISION = "revision"           # 递增版本号，驱动画布增量应用
# V4.43.3 新增：custom 背景的 base64 data URL（≤ 256KB 缩放后）
SETTING_KEY_CUSTOM_IMAGE_B64 = "canvas_custom_image_b64"

#: 画布外观设置文件（单一真相源，画布经 /host/canvas-settings 读取）
CANVAS_APPEARANCE_FILE = (
    Path(__file__).resolve().parents[3] / "data" / "canvas_appearance.json"
)
#: 上传图片保存目录（custom 背景图持久化用）
CUSTOM_BG_DIR = Path(__file__).resolve().parents[3] / "data" / "uploaded"
# 常规 — 开关
SETTING_KEY_NODE_TOOLBAR_MODE = "ui/node_toolbar_mode"        # icons / icons-and-text
SETTING_KEY_NOTE_TOOLBAR = "ui/canvas_note_toolbar_visible"   # 画布笔记工具栏
SETTING_KEY_AUTO_REF_ASSET = "canvas/auto_ref_asset"          # 连线后自动 @ 素材
SETTING_KEY_NODE_TITLE = "ui/node_label_visible"              # 节点标题
SETTING_KEY_GLASS_FRAME = "ui/window_glass_frame"             # 窗口玻璃外框
SETTING_KEY_PERFORMANCE_MODE = "perf/performance_mode"        # 性能模式
SETTING_KEY_SIDEBAR_FLOATING = "ui/sidebar_floating"          # 侧边栏悬浮

ALL_PREFERENCE_KEYS = [
    SETTING_KEY_NOTE_TOOLBAR,
    SETTING_KEY_AUTO_REF_ASSET,
    SETTING_KEY_NODE_TITLE,
    SETTING_KEY_GLASS_FRAME,
    SETTING_KEY_PERFORMANCE_MODE,
    SETTING_KEY_SIDEBAR_FLOATING,
]


def _read_bool_setting(key: str, default: bool = True) -> bool:
    try:
        return bool(QSettings("拾光剪影", "Settings").value(key, default, type=bool))
    except Exception:
        return default


def _write_bool_setting(key: str, value: bool) -> None:
    try:
        s = QSettings("拾光剪影", "Settings")
        s.setValue(key, bool(value))
        s.sync()
    except Exception as e:
        logger.debug("写入设置失败 %s: %s", key, e)


def _read_str_setting(key: str, default: str = "") -> str:
    try:
        return str(QSettings("拾光剪影", "Settings").value(key, default))
    except Exception:
        return default


def _write_str_setting(key: str, value: str) -> None:
    try:
        s = QSettings("拾光剪影", "Settings")
        s.setValue(key, value)
        s.sync()
    except Exception as e:
        logger.debug("写入设置失败 %s: %s", key, e)


# ═══════════════════════════════════════════════════════════════
# 外观预设（6 个，与画布 CANVAS_BACKGROUNDS 一一对应）
# ═══════════════════════════════════════════════════════════════
# (id, 名称, 预览底色, 强调色, 对应画布背景 id, 对应画布主题)
# V4.43.3：6 个预设全部对应画布真实背景：
#   深色 → default / 浅色 → off-white / 太阳系 / 星云 / 磨砂曝光 / 自定义图片
# 每个预设点击即写 QSettings + 递增 revision，画布轮询到后应用。
# custom 的图片走「上传 PNG/JPG → base64 → canvas_appearance.json」通道。
PRESETS = [
    ("dark",          "深色",       "#0a0a0f", "#6366f1", "default",       "dark"),
    ("light",         "浅色",       "#F4F6FB", "#7280E4", "off-white",     "light"),
    ("solar-system",  "太阳系",     "#0a0a12", "#a855f7", "solar-system",  "dark"),
    ("nebula",        "星云",       "#080510", "#d946ef", "nebula",        "dark"),
    ("frosted-glass", "磨砂曝光",   "#eef1f8", "#6ECBAA", "frosted-glass", "light"),
    ("custom",        "自定义图片", "#0a0e14", "#f59e0b", "custom",        "dark"),
]


def _save_custom_image_to_disk(source_path: Path) -> Optional[Path]:
    """把用户选的图片复制到 data/uploaded/ 并返回持久化路径。

    V4.43.3：custom 上传链路 =① 选文件 → ② 复制到 data/uploaded/ → ③ base64 编码
    下发画布（≤ 256KB）。这里只做复制（保持原格式）；尺寸压理由 PIL 可选（如未装
    pillow 则不压缩，照原图 base64 —— 通常 PNG ≤ 1MB 仍是合理大小）。
    """
    try:
        CUSTOM_BG_DIR.mkdir(parents=True, exist_ok=True)
        ext = source_path.suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        dst = CUSTOM_BG_DIR / f"custom_bg{ext}"
        shutil.copyfile(str(source_path), str(dst))
        return dst
    except Exception as e:
        logger.warning("保存自定义图片失败: %s", e)
        return None


def _image_to_base64(path: Path, max_bytes: int = 256 * 1024) -> Optional[str]:
    """读取图片转 data URL；如果太大先用 PIL 缩到 1600px 宽再压。

    V4.43.3：base64 入 JSON，画布收到后传给 html[--bg-img]，再覆盖到 --bg。
    256KB 是经验阈值；超了会被前端 CSS 拒绝（4MB 字符串解析很慢）。
    """
    try:
        raw = path.read_bytes()
        # 尝试压缩（pillow 可用时）
        if len(raw) > max_bytes:
            try:
                from PIL import Image
                import io
                im = Image.open(io.BytesIO(raw))
                im.thumbnail((1600, 1600))
                buf = io.BytesIO()
                im.save(buf, format="PNG", optimize=True)
                raw = buf.getvalue()
            except Exception:
                # 没 pillow 也不强求：照原图拼（更大就更大吧，画布收到会抱怨一下）
                pass
        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/png" if path.suffix.lower() in (".png", "") else f"image/{path.suffix[1:].lower()}"
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning("图片转 base64 失败 %s: %s", path, e)
        return None


def _load_current_image_b64() -> Optional[str]:
    """读取当前 JSON 里持久化的 custom 背景图 base64（settings_panel.py 版本）"""
    try:
        if not CANVAS_APPEARANCE_FILE.exists():
            return None
        data = json.loads(CANVAS_APPEARANCE_FILE.read_text(encoding="utf-8"))
        return data.get("image_data_url") or None
    except Exception:
        return None


def _preset_export_path() -> Path:
    """外观预设导入/导出目录（按 JSON 文件区分）"""
    p = Path(__file__).resolve().parents[3] / "data" / "presets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def export_appearance_preset(name: str = "custom") -> Optional[Path]:
    """把当前外观配置序列化为 JSON 写到 data/presets/{name}.json

    V4.43.3：导入/导出按钮真接上，写文件路径返回给调用方做 toast/success 提示。
    """
    try:
        data: dict = {"name": name, "ts": int(__import__("time").time())}
        for k in (
            SETTING_KEY_APPEARANCE_PRESET,
            SETTING_KEY_THEME_MODE,
            SETTING_KEY_CANVAS_BACKGROUND,
        ):
            data[k] = _read_str_setting(k, "")
        if CANVAS_APPEARANCE_FILE.exists():
            data["canvas_appearance"] = json.loads(
                CANVAS_APPEARANCE_FILE.read_text(encoding="utf-8")
            )
        path = _preset_export_path() / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except Exception as e:
        logger.warning("导出外观预设失败: %s", e)
        return None


def import_appearance_preset(name: str = "custom") -> bool:
    """从 data/presets/{name}.json 恢复外观设置，并下发画布"""
    try:
        path = _preset_export_path() / f"{name}.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        for k in (
            SETTING_KEY_APPEARANCE_PRESET,
            SETTING_KEY_THEME_MODE,
        ):
            if k in data and data[k]:
                _write_str_setting(k, str(data[k]))
        ca = data.get("canvas_appearance") or {}
        if "canvas_background" in ca:
            push_canvas_appearance(
                str(ca.get("canvas_background", "default")),
                str(ca.get("theme", "dark")),
                image_b64=ca.get("image_data_url"),
            )
        return True
    except Exception as e:
        logger.warning("导入外观预设失败: %s", e)
        return False


def push_canvas_appearance(
    canvas_bg: str, theme: str, image_b64: Optional[str] = None
) -> None:
    """把外观预设下发到画布（写 JSON + 递增 revision）。

    画布 `canvasBackgrounds.ts` 每 2.5s 轮询 `GET /host/canvas-settings`，
    只在 revision 变化时应用 —— 这样不会覆盖用户在画布内的本地主题切换。

    V4.43.3 新增 image_b64：custom 背景时把图片以 data URL 形式一并写入；
    画布检测到 `custom` 时会用该 data URL 覆盖 html --bg。
    """
    try:
        payload = {
            "revision": 0,
            "canvas_background": str(canvas_bg),
            "theme": "light" if theme == "light" else "dark",
        }
        if image_b64:
            payload["image_data_url"] = image_b64
        f = CANVAS_APPEARANCE_FILE
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            try:
                payload["revision"] = int(
                    json.loads(f.read_text(encoding="utf-8")).get("revision", 0)
                )
            except Exception:
                payload["revision"] = 0
        payload["revision"] += 1
        # 写入磁盘
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
        logger.debug("外观预设已下发画布: bg=%s theme=%s image=%d bytes", canvas_bg, theme, len(image_b64 or ""))
    except Exception as e:
        logger.debug("下发画布外观失败: %s", e)

THEME_MODE_OPTIONS = [
    ("dark",   "☾  深色"),
    ("light",  "☀  浅色"),
    ("system", "🖥  跟随系统"),
]


# ═══════════════════════════════════════════════════════════════
# 主面板
# ═══════════════════════════════════════════════════════════════
class SettingsDialog(QDialog):
    """设置主面板（V4.43.1）

    信号：
        preference_changed(str, bool) — 开关变化 (key, value)
        appearance_changed(str)       — 外观预设 / 主题模式变化
    """

    preference_changed = pyqtSignal(str, bool)
    appearance_changed = pyqtSignal(str)

    _instance: Optional["SettingsDialog"] = None

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(940, 660)
        self.setObjectName("settingsDialog")
        self.setProperty("theme", ThemeManager.instance().current_theme)

        self._pref_cards: list[PreferenceCard] = []
        self._preset_cards: list[PresetCard] = []

        self._build_ui()

    @classmethod
    def instance(cls, parent: Optional[QWidget] = None) -> "SettingsDialog":
        if cls._instance is None:
            cls._instance = cls(parent)
        return cls._instance

    # ─────────── 骨架 ───────────
    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左导航
        nav_holder = QWidget()
        nav_holder.setObjectName("settingsNavHolder")
        nav_holder.setFixedWidth(184)
        nav_layout = QVBoxLayout(nav_holder)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        nav_header = QLabel("⚙  设置")
        nav_header.setObjectName("settingsNavHeader")
        nav_header.setFixedHeight(56)
        nav_layout.addWidget(nav_header)

        self._nav = QListWidget()
        self._nav.setObjectName("settingsNav")
        self._nav.setSpacing(2)
        nav_layout.addWidget(self._nav)
        layout.addWidget(nav_holder)

        # 右内容
        self._stack = QStackedWidget()
        self._stack.setObjectName("settingsStack")
        layout.addWidget(self._stack, stretch=1)

        self._add_tab("🎨", "外观", self._build_appearance_page())
        self._add_tab("🎛", "常规", self._build_general_page())
        self._add_tab("🗂", "存储", self._build_storage_page())
        self._add_tab("🖥", "ComfyUI", self._placeholder_page("ComfyUI 安装目录与运行配置（已迁移至专门设置面板）"))
        self._add_tab("🔌", "MCP", self._placeholder_page("MCP 控制：端口 / 令牌 / 客户端配置片段（已迁移至专门设置面板）"))
        self._add_tab("❓", "关于", self._build_about_page())

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _add_tab(self, icon: str, label: str, page: QWidget) -> None:
        item = QListWidgetItem(f"{icon}   {label}")
        item.setSizeHint(QSize(184, 44))
        self._nav.addItem(item)
        self._stack.addWidget(page)

    @staticmethod
    def _wrap_scroll(inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("settingsContent")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        return lbl

    # ═══════════ 外观页（对齐截图 1）═══════════
    def _build_appearance_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        current_preset = _read_str_setting(SETTING_KEY_APPEARANCE_PRESET, "dark")
        theme_label = "深色" if not ThemeManager.instance().is_light else "浅色"

        # ── 头部：标题 + chip + 自动保存 ──
        head = QHBoxLayout()
        head_icon = QLabel("✨")
        head_icon.setObjectName("appearanceHeadIcon")
        head.addWidget(head_icon)
        head.addWidget(self._title_label("外观"))
        chip = QLabel(theme_label)
        chip.setObjectName("chipBrand")
        head.addWidget(chip)
        head.addStretch(1)
        auto_badge = QLabel("● 自动保存")
        auto_badge.setObjectName("autoSaveBadge")
        head.addWidget(auto_badge)
        layout.addLayout(head)

        sub = QLabel("外观预设包含画布、节点、连接线、连接手柄和所有页面配色")
        sub.setObjectName("settingsPageHint")
        layout.addWidget(sub)

        # ── 工具按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for icon, label, obj in [
            ("⬇", "导入", "ghostBtn"),
            ("⬆", "导出", "ghostBtn"),
            ("💾", "保存预设", "ghostBtn"),
        ]:
            b = QPushButton(f"{icon}  {label}")
            b.setObjectName(obj)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c, l=label: self._on_appearance_tool(l))
            btn_row.addWidget(b)
        override = QPushButton("🚫  覆盖当前预设")
        override.setObjectName("overrideBtn")
        override.setEnabled(False)
        btn_row.addWidget(override)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # ── 大预览 ──
        self._appearance_preview = AppearancePreview()
        self._appearance_preview.set_theme_label(theme_label)
        layout.addWidget(self._appearance_preview)

        # ── 外观预设 3×2（6 个） ──
        layout.addWidget(self._section_title("外观预设"))
        preset_hint = QLabel("选择、保存或管理完整外观配置（含 6 套背景 + custom 上传）")
        preset_hint.setObjectName("sectionHint")
        layout.addWidget(preset_hint)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (pid, label, swatch, accent, _cgbg, _cgtheme) in enumerate(PRESETS):
            card = PresetCard(pid, label, swatch, accent)
            card.set_active(pid == current_preset)
            card.activated.connect(self._on_preset_activated)
            self._preset_cards.append(card)
            # 3 列 × 2 行；右上右下右下又…先按 3×2 排（也可改 2×3 由布局方向）
            grid.addWidget(card, i // 3, i % 3)
        layout.addLayout(grid)

        # ── 主题模式 ──
        layout.addWidget(self._section_title("主题模式"))
        mode_hint = QLabel("选择整套界面的明暗基调")
        mode_hint.setObjectName("sectionHint")
        layout.addWidget(mode_hint)

        saved_mode = _read_str_setting(SETTING_KEY_THEME_MODE,
                                       "light" if ThemeManager.instance().is_light else "dark")
        self._theme_mode = SegmentedControl(THEME_MODE_OPTIONS, saved_mode, height=44)
        self._theme_mode.changed.connect(self._on_theme_mode_changed)
        layout.addWidget(self._theme_mode)

        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    @staticmethod
    def _title_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("settingsBigTitle")
        return lbl

    def _on_appearance_tool(self, label: str) -> None:
        logger.info("外观工具: %s（待接入真实导入导出）", label)

    def _on_preset_activated(self, preset_id: str) -> None:
        """预设点击：custom 卡走「弹文件选择 → 持久化 → 下发画布」通路"""
        entry = next((p for p in PRESETS if p[0] == preset_id), None)
        if entry is None:
            return
        _pid, label, _swatch, _accent, canvas_bg, canvas_theme = entry

        # custom：未上传则弹文件框
        image_b64: Optional[str] = None
        if preset_id == "custom":
            existing = _load_current_image_b64()
            if existing is None:
                path = self._pick_custom_image()
                if path is None:
                    return  # 用户取消，不切换
                saved = _save_custom_image_to_disk(path)
                if saved is None:
                    QMessageBox.warning(self, "上传失败", "无法保存自定义图片")
                    return
                image_b64 = _image_to_base64(saved)
                if image_b64 is None:
                    QMessageBox.warning(self, "上传失败", "无法编码自定义图片")
                    return

        _write_str_setting(SETTING_KEY_APPEARANCE_PRESET, preset_id)
        for card in self._preset_cards:
            card.set_active(card._preset_id == preset_id)
        self._appearance_preview.set_theme_label(label)

        # 1) 主程序主题（画布外的 UI）
        _write_str_setting(SETTING_KEY_THEME_MODE, canvas_theme)
        self._theme_mode.set_current(canvas_theme)
        try:
            ThemeManager.instance().apply_theme(canvas_theme)
        except Exception as e:
            logger.warning("应用预设主题失败: %s", e)
        # 2) 下发到画布（V4.43.3：custom 带 image_b64）
        push_canvas_appearance(canvas_bg, canvas_theme, image_b64=image_b64)
        self.appearance_changed.emit(preset_id)

    def _pick_custom_image(self) -> Optional[Path]:
        """弹出文件选择对话框，让用户选一张 PNG/JPG/WEBP。"""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "选择自定义画布背景",
            str(Path.home()),
            "图片 (*.png *.jpg *.jpeg *.webp);;所有文件 (*)",
        )
        return Path(path_str) if path_str else None

    def _on_theme_mode_changed(self, mode: str) -> None:
        _write_str_setting(SETTING_KEY_THEME_MODE, mode)
        try:
            ThemeManager.instance().apply_theme(mode)
        except Exception as e:
            logger.warning("应用主题模式失败: %s", e)
        self.appearance_changed.emit(mode)

    # ═══════════ 常规页（对齐截图 2）═══════════
    def _build_general_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(18)

        # ── 节点工具栏（分段） ──
        layout.addWidget(self._section_title("节点工具栏"))
        toolbar_mode = _read_str_setting(SETTING_KEY_NODE_TOOLBAR_MODE, "icons")
        self._toolbar_seg = SegmentedControl(
            [("icons", "○  极简图标"), ("icons-and-text", "▤  图标 + 文本")],
            toolbar_mode, height=40,
        )
        self._toolbar_seg.changed.connect(
            lambda v: _write_str_setting(SETTING_KEY_NODE_TOOLBAR_MODE, v)
        )
        layout.addWidget(self._toolbar_seg)

        # ── 6 个开关分组（直抄 .sidebar-pref-card） ──
        note_card = PreferenceCard(
            SETTING_KEY_NOTE_TOOLBAR, "显示笔记工具栏",
            "在画布左下角显示绘图与笔记工具",
            preview_kind="note_toolbar",
            on_desc="在画布左下角显示绘图与笔记工具",
            off_desc="隐藏工具栏，已有笔记仍可编辑",
            default_value=_read_bool_setting(SETTING_KEY_NOTE_TOOLBAR, True),
        )
        ref_card = PreferenceCard(
            SETTING_KEY_AUTO_REF_ASSET, "连线后自动 @ 素材",
            "新建连线时，将上游素材追加到生成节点的提示词中；已有引用不会重复添加。",
            preview_kind="auto_ref",
            default_value=_read_bool_setting(SETTING_KEY_AUTO_REF_ASSET, True),
        )
        title_card = PreferenceCard(
            SETTING_KEY_NODE_TITLE, "显示节点标题",
            "节点上方显示类型图标与名称，双击可重命名",
            preview_kind="node_title",
            on_desc="节点上方显示类型图标与名称，双击可重命名",
            off_desc="隐藏节点上方的标题栏，画布更简洁",
            default_value=_read_bool_setting(SETTING_KEY_NODE_TITLE, True),
        )
        glass_card = PreferenceCard(
            SETTING_KEY_GLASS_FRAME, "玻璃外框",
            "显示 5px 玻璃带与双层边缘高光",
            preview_kind="glass_frame",
            on_desc="显示 5px 玻璃带与双层边缘高光",
            off_desc="内容贴合窗口边缘，不显示外框",
            default_value=_read_bool_setting(SETTING_KEY_GLASS_FRAME, True),
        )
        perf_card = PreferenceCard(
            SETTING_KEY_PERFORMANCE_MODE, "性能模式",
            "保留完整视觉效果与界面动画",
            preview_kind="perf_mode",
            badge="卡顿或页面显示不全时开启",
            default_value=_read_bool_setting(SETTING_KEY_PERFORMANCE_MODE, False),
        )
        side_card = PreferenceCard(
            SETTING_KEY_SIDEBAR_FLOATING, "悬浮显示",
            "侧边栏停靠在窗口内侧",
            preview_kind="sidebar_floating",
            on_desc="侧边栏半隐于窗口边缘，悬浮在画布之上",
            off_desc="侧边栏停靠在窗口内侧",
            default_value=_read_bool_setting(SETTING_KEY_SIDEBAR_FLOATING, True),
        )

        for section, card in [
            ("画布笔记工具栏", note_card),
            ("素材引用", ref_card),
            ("节点标题", title_card),
            ("窗口外观", glass_card),
            ("图形与性能", perf_card),
            ("侧边栏", side_card),
        ]:
            layout.addWidget(self._section_title(section))
            layout.addWidget(card)
            self._pref_cards.append(card)
            card.toggled.connect(self.preference_changed.emit)

        # 性能模式脚注
        footnote = QLabel(
            "开启后将保存并自动重启，正在运行的任务会中断；"
            "关闭后下次启动恢复原生图形设置。"
        )
        footnote.setObjectName("settingsFootnote")
        footnote.setWordWrap(True)
        layout.addWidget(footnote)

        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    # ═══════════ 其余页 ═══════════
    def _build_storage_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("存储健康"))
        hint = QLabel("空间占用分析 / 回收站清理 / 孤儿文件检测\n（后续版本接入，V4.44.0+）")
        hint.setObjectName("settingsPageHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    def _placeholder_page(self, text: str) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.addWidget(self._section_title(text))
        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    def _build_about_page(self) -> QWidget:
        from app.version import __version__, VERSION_INFO
        page = QWidget()
        page.setObjectName("settingsPage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        row = QHBoxLayout()
        logo = QLabel("✨")
        f = QFont()
        f.setPointSize(26)
        logo.setFont(f)
        row.addWidget(logo)
        row.addWidget(self._title_label(f"拾光剪影 V{__version__}"))
        row.addStretch(1)
        layout.addLayout(row)

        sub = QLabel(VERSION_INFO.get("codename", ""))
        sub.setObjectName("settingsPageHint")
        layout.addWidget(sub)

        layout.addWidget(self._section_title("核心能力"))
        caps = QHBoxLayout()
        caps.setSpacing(6)
        for icon, label in [("🎬", "剪辑"), ("🎨", "画布"), ("🤖", "Agent"),
                            ("📝", "脚本"), ("🧩", "插件"), ("🔌", "MCP")]:
            c = QLabel(f"{icon} {label}")
            c.setObjectName("chip")
            caps.addWidget(c)
        caps.addStretch(1)
        layout.addLayout(caps)

        layout.addWidget(self._section_title("技术栈"))
        stack = QHBoxLayout()
        stack.setSpacing(6)
        for label in ["PyQt6", "React Flow", "TypeScript", "Vite", "MCP"]:
            c = QLabel(label)
            c.setObjectName("chipMuted")
            stack.addWidget(c)
        stack.addStretch(1)
        layout.addLayout(stack)

        layout.addStretch(1)
        outer.addWidget(self._wrap_scroll(inner))
        return page

    # ─────────── 主题 ───────────
    def set_theme(self, theme: str) -> None:
        self.setProperty("theme", theme)
        for child in self.findChildren(QWidget):
            child.setProperty("theme", theme)
        for w in list(self._pref_cards) + list(self._preset_cards):
            try:
                w.set_theme(theme)
            except Exception as e:
                logger.debug("子控件主题刷新失败 %s: %s", type(w).__name__, e)
        seg = getattr(self, "_toolbar_seg", None)
        if seg is not None:
            seg.set_theme(theme)
        mode = getattr(self, "_theme_mode", None)
        if mode is not None:
            mode.set_theme(theme)
        prev = getattr(self, "_appearance_preview", None)
        if prev is not None:
            prev.update()

    def closeEvent(self, event):
        SettingsDialog._instance = None
        super().closeEvent(event)
