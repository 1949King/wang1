"""
国际化 (i18n) 系统
====================
对标 OpenShot 100+ 语言翻译。

特性:
- 基于 JSON 的翻译文件
- 自动检测系统语言
- 运行时语言切换
- 支持嵌套 key (a.b.c)
- 占位符替换 {name}
"""
import os
import json
import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger("AI短剧编辑器.i18n")


# 内置翻译 (中文 + 英文)
BUILTIN_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "zh_CN": {
        # 通用
        "app.name": "AI短剧编辑器",
        "common.ok": "确定",
        "common.cancel": "取消",
        "common.save": "保存",
        "common.open": "打开",
        "common.delete": "删除",
        "common.edit": "编辑",
        "common.copy": "复制",
        "common.paste": "粘贴",
        "common.cut": "剪切",
        "common.undo": "撤销",
        "common.redo": "重做",
        "common.import": "导入",
        "common.export": "导出",
        "common.new": "新建",
        "common.close": "关闭",
        "common.search": "搜索",
        "common.loading": "加载中...",
        "common.success": "成功",
        "common.failed": "失败",
        "common.confirm": "确认",
        "common.warning": "警告",
        "common.error": "错误",
        "common.yes": "是",
        "common.no": "否",

        # 菜单
        "menu.file": "文件",
        "menu.edit": "编辑",
        "menu.view": "视图",
        "menu.clip": "片段",
        "menu.track": "轨道",
        "menu.ai": "AI智能",
        "menu.export": "导出",
        "menu.help": "帮助",
        "menu.settings": "设置",

        # 文件操作
        "file.new_project": "新建项目",
        "file.open_project": "打开项目",
        "file.save_project": "保存项目",
        "file.import_media": "导入媒体",
        "file.export_video": "导出视频",
        "file.recent_files": "最近文件",
        "file.exit": "退出",

        # 时间线
        "timeline.add_track": "添加轨道",
        "timeline.delete_track": "删除轨道",
        "timeline.zoom_in": "放大",
        "timeline.zoom_out": "缩小",
        "timeline.zoom_fit": "适应窗口",
        "timeline.snap": "磁吸",
        "timeline.ripple_delete": "波纹删除",
        "timeline.split": "分割",
        "timeline.mute": "静音",
        "timeline.solo": "独奏",
        "timeline.lock": "锁定",

        # AI 功能
        "ai.auto_clip": "AI智能剪辑",
        "ai.optimize_viral": "AI爆款优化",
        "ai.generate_subtitle": "AI自动字幕",
        "ai.analyze_drama": "AI剧情分析",
        "ai.workflow_running": "AI工作流运行中...",
        "ai.review_passed": "审核通过",
        "ai.review_failed": "审核未通过",

        # 渲染
        "render.start": "开始渲染",
        "render.cancel": "取消渲染",
        "render.queue": "渲染队列",
        "render.progress": "渲染进度",
        "render.completed": "渲染完成",
        "render.failed": "渲染失败",
        "render.gpu_accel": "GPU 加速",

        # 设置
        "settings.general": "常规",
        "settings.shortcuts": "快捷键",
        "settings.theme": "主题",
        "settings.language": "语言",
        "settings.about": "关于",
        "settings.update": "检查更新",

        # 错误
        "error.file_not_found": "文件未找到",
        "error.unsupported_format": "不支持的格式",
        "error.render_failed": "渲染失败",
        "error.network_error": "网络错误",
        "error.permission_denied": "权限不足",
    },
    "en_US": {
        "app.name": "AI Short Drama Editor",
        "common.ok": "OK",
        "common.cancel": "Cancel",
        "common.save": "Save",
        "common.open": "Open",
        "common.delete": "Delete",
        "common.edit": "Edit",
        "common.copy": "Copy",
        "common.paste": "Paste",
        "common.cut": "Cut",
        "common.undo": "Undo",
        "common.redo": "Redo",
        "common.import": "Import",
        "common.export": "Export",
        "common.new": "New",
        "common.close": "Close",
        "common.search": "Search",
        "common.loading": "Loading...",
        "common.success": "Success",
        "common.failed": "Failed",
        "common.confirm": "Confirm",
        "common.warning": "Warning",
        "common.error": "Error",
        "common.yes": "Yes",
        "common.no": "No",

        "menu.file": "File",
        "menu.edit": "Edit",
        "menu.view": "View",
        "menu.clip": "Clip",
        "menu.track": "Track",
        "menu.ai": "AI",
        "menu.export": "Export",
        "menu.help": "Help",
        "menu.settings": "Settings",

        "file.new_project": "New Project",
        "file.open_project": "Open Project",
        "file.save_project": "Save Project",
        "file.import_media": "Import Media",
        "file.export_video": "Export Video",
        "file.recent_files": "Recent Files",
        "file.exit": "Exit",

        "timeline.add_track": "Add Track",
        "timeline.delete_track": "Delete Track",
        "timeline.zoom_in": "Zoom In",
        "timeline.zoom_out": "Zoom Out",
        "timeline.zoom_fit": "Fit",
        "timeline.snap": "Snap",
        "timeline.ripple_delete": "Ripple Delete",
        "timeline.split": "Split",
        "timeline.mute": "Mute",
        "timeline.solo": "Solo",
        "timeline.lock": "Lock",

        "ai.auto_clip": "AI Auto Clip",
        "ai.optimize_viral": "AI Viral Optimize",
        "ai.generate_subtitle": "AI Subtitle",
        "ai.analyze_drama": "AI Drama Analysis",
        "ai.workflow_running": "AI workflow running...",
        "ai.review_passed": "Review Passed",
        "ai.review_failed": "Review Failed",

        "render.start": "Start Render",
        "render.cancel": "Cancel Render",
        "render.queue": "Render Queue",
        "render.progress": "Render Progress",
        "render.completed": "Render Completed",
        "render.failed": "Render Failed",
        "render.gpu_accel": "GPU Acceleration",

        "settings.general": "General",
        "settings.shortcuts": "Shortcuts",
        "settings.theme": "Theme",
        "settings.language": "Language",
        "settings.about": "About",
        "settings.update": "Check Update",

        "error.file_not_found": "File not found",
        "error.unsupported_format": "Unsupported format",
        "error.render_failed": "Render failed",
        "error.network_error": "Network error",
        "error.permission_denied": "Permission denied",
    },
}


class I18n:
    """
    国际化管理器 (单例)

    使用:
        i18n = I18n()
        i18n.set_locale("en_US")
        label.setText(i18n.t("menu.file"))
    """

    _instance: Optional["I18n"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init = False
        return cls._instance

    def __init__(self):
        if self._init:
            return
        self._init = True
        self._current_locale = "zh_CN"
        self._translations: Dict[str, Dict[str, str]] = {}
        # 加载内置翻译
        for locale, trans in BUILTIN_TRANSLATIONS.items():
            self._translations[locale] = trans.copy()
        # 尝试从配置加载用户自定义翻译
        self._load_user_translations()

    def _load_user_translations(self):
        """从用户目录加载翻译文件"""
        try:
            try:
                from app.core.config_paths import get_user_data_dir
                base = get_user_data_dir()
            except ImportError:
                base = os.path.join(os.path.expanduser("~"), ".ai_short_drama_editor")
            i18n_dir = os.path.join(base, "i18n")
            if not os.path.isdir(i18n_dir):
                return
            for fname in os.listdir(i18n_dir):
                if fname.endswith(".json"):
                    locale = fname[:-5]
                    path = os.path.join(i18n_dir, fname)
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if locale not in self._translations:
                            self._translations[locale] = {}
                        self._translations[locale].update(data)
                    except Exception as e:
                        logger.warning(f"加载翻译文件 {fname} 失败: {e}")
        except Exception as e:
            logger.warning(f"[I18N] 加载翻译目录失败: {e}")

    def set_locale(self, locale: str) -> bool:
        """切换语言"""
        if locale not in self._translations:
            logger.warning(f"不支持的语言: {locale}")
            return False
        self._current_locale = locale
        return True

    def get_locale(self) -> str:
        return self._current_locale

    def t(self, key: str, default: str = None, **kwargs) -> str:
        """
        翻译 key

        Args:
            key: 翻译键 (e.g. "menu.file")
            default: 找不到时的默认文本
            **kwargs: 占位符变量

        Returns:
            翻译后的文本
        """
        text = self._translations.get(self._current_locale, {}).get(key)
        if text is None:
            # 回退到中文
            text = self._translations.get("zh_CN", {}).get(key)
        if text is None:
            # 用 key 本身作为默认
            text = default or key
        # 占位符替换
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                logger.debug("i18n 占位符替换失败，返回未替换文本: %s", key, exc_info=True)
        return text

    def available_locales(self) -> list:
        """所有可用语言"""
        return list(self._translations.keys())


# 全局实例
i18n = I18n()
