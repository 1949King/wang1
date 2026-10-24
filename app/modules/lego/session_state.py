"""会话状态 · 工程落盘路径（V4.43.14）
======================================

本模块服务两件事：

**② 修「新建项目后回首页看不到」**
   首页的「最近项目」靠**扫描 `data/projects/` 目录**渲染（`modules._refresh_recent_projects`），
   而首页 CTA 的「+ 新建项目」此前只 emit `MODULE_ACTIVATED(action=create_project)`，
   `main_window._flush_pending_module_action` **没有该 action 的分支** ⇒ 项目既没创建也没落盘
   ⇒ 回首页扫不到。本模块提供 `new_project_path()`，让「新建」**立刻写出工程文件**。

**① 「下次打开接着上次继续」**
   `save_last_session()` / `load_last_session()` 记录「上次在哪个模块 / 哪个项目 / 何时退出」，
   由主窗口在关闭时写入、启动时按设置开关读取。开关项见 `SETTING_KEY_RESUME_SESSION`。
"""
import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

#: 会话状态文件（相对当前工作目录）
STATE_REL = os.path.join("data", "session_state.json")
#: 设置项：启动时是否自动恢复到上次的模块 / 项目
SETTING_KEY_RESUME_SESSION = "resume_session_on_start"

_UNSAFE = re.compile(r'[\\/:*?"<>|]+')


def projects_dir() -> str:
    """首页「最近项目」扫描的目录（与 `modules.py` 保持一致）"""
    return os.path.join(os.getcwd(), "data", "projects")


def safe_name(name: str) -> str:
    """把用户输入的项目名转成安全的文件名（去非法字符；空则兜底）"""
    cleaned = _UNSAFE.sub("_", name or "").strip().strip(".")
    return cleaned or "未命名项目"


def new_project_path(name: str) -> str:
    """新建工程的目标路径，并确保目录存在"""
    d = projects_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{safe_name(name)}.timeline")


def project_exists(path: str) -> bool:
    """工程文件是否仍在（恢复前校验，避免加载已被删除的工程）"""
    return bool(path) and os.path.isfile(path)


def _state_path() -> str:
    return os.path.join(os.getcwd(), STATE_REL)


def save_last_session(module_id: str, project_path: str = "", project_name: str = "") -> None:
    """记住「本次退出时在哪」，供下次启动恢复。写失败不影响主流程。"""
    payload = {
        "module": str(module_id or ""),
        "project": str(project_path or ""),
        "project_name": str(project_name or ""),
        "closed_at": time.time(),
    }
    try:
        p = _state_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.debug("写会话状态失败: %s", e)


def load_last_session() -> dict:
    """读取上次会话。无记录 / 损坏时返回空 dict（调用方按「无会话」处理）。"""
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        logger.debug("读会话状态失败（按无会话处理）: %s", e)
        return {}


def clear_last_session() -> None:
    """清除会话记录（用户在设置里关掉恢复时调用）"""
    try:
        p = _state_path()
        if os.path.isfile(p):
            os.remove(p)
    except OSError as e:
        logger.debug("清除会话状态失败: %s", e)


def describe(data: dict) -> str:
    """把会话记录转成一句人话，用于设置页展示 / 状态栏提示"""
    if not data:
        return "无上次会话记录"
    mod = data.get("module") or "?"
    name = data.get("project_name") or ""
    ts = data.get("closed_at")
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "未知时间"
    tail = f" · 项目「{name}」" if name else ""
    return f"上次于 {when} 停留在「{mod}」{tail}"
