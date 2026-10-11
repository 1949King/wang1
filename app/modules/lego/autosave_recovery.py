"""自动保存 · 恢复提示策略（V4.43.13）
======================================

从 `editor_module` 抽出的**纯逻辑**（无 Qt 依赖、可单测）：只回答
「这次启动该不该提示恢复」，并维护两个标记文件。

## 为什么需要它（对标业界）

| 平台 | 何时弹 | 频率 | 机制 |
|---|---|---|---|
| Adobe Premiere | 仅 `quit unexpectedly` | **一次**（官方："won't appear again … next launch"） | — |
| Microsoft Office | 仅异常关闭 | 一次 | **正常保存 / 正常关闭 → 删除 AutoRecover 文件** |
| NightOS crashsave 规范 | 检测到非正常退出 | 每应用一次 | **启动写 `awake`，正常退出即删，残留即判崩溃** |
| 拾光剪影（改前） | **每次启动** | **无限次** | 什么都没做 ❌ |

**业界共识 = 正常关闭要清理恢复数据，只有崩溃残留才提示。**

## 改前的三处缺陷（用户：「每次一开程序就弹，弹的还是两个月前的文件」）

1. 关闭时**没有任何清理** ⇒ autosave 永远留着 ⇒ 每次都弹；
2. `_autosave_prompted` 只是**内存变量**，进程重启即归零；
3. 无「是否崩溃残留」判断 ⇒ 弹的是上次**正常保存**的副本。

## 标记文件协议

- `autosave/.running`   ── 启动时写（含本次 pid）；**正常退出时删**。
  残留即说明上次是崩溃/强杀 ⇒ 才提示恢复。
- `autosave/.prompted`  ── 记录「已经询问过哪个版本（latest.timeline 的 mtime）」；
  同一版本不再重复问（对齐 Premiere "won't appear again"）。
"""
import atexit
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger(__name__)

RUNNING_FLAG = ".running"
PROMPTED_FLAG = ".prompted"
LATEST_NAME = "latest.timeline"
#: 超过该天数的存档视为僵尸文件，静默忽略（顺手解决 2026-08-11 那种两个月前的残留）
MAX_AGE_DAYS = 7

_hook_registered = False


def autosave_dir() -> str:
    """自动保存目录（相对当前工作目录，与既有实现一致）"""
    return os.path.join(os.getcwd(), "autosave")


def latest_path() -> str:
    """自动保存工程文件路径"""
    return os.path.join(autosave_dir(), LATEST_NAME)


def mark_clean_exit() -> None:
    """正常退出：删除「运行中」标记 ⇒ 下次启动不会误判为崩溃。

    经 `atexit` 注册：进程正常结束时执行；被强杀 / 崩溃时**不执行** ⇒ 标记残留 ⇒
    下次启动正确识别为「上次异常退出」。这正是 Premiere / Office / NightOS 的做法。
    """
    try:
        flag = os.path.join(autosave_dir(), RUNNING_FLAG)
        if os.path.isfile(flag):
            os.remove(flag)
    except OSError as e:
        logger.debug("清理 autosave 运行标记失败: %s", e)


def _register_clean_exit_hook() -> None:
    """atexit 注册（幂等，避免重复挂载）"""
    global _hook_registered
    if _hook_registered:
        return
    atexit.register(mark_clean_exit)
    _hook_registered = True


def begin_session() -> bool:
    """启动时调用：判定「上次是否异常退出」并写下本次的运行标记。

    :return: True = 上次异常退出（`autosave/.running` 残留）；False = 上次正常关闭。
    """
    running = os.path.join(autosave_dir(), RUNNING_FLAG)
    crashed_last_time = os.path.isfile(running)  # 必须在写本次标记**之前**读
    try:
        os.makedirs(autosave_dir(), exist_ok=True)
        with open(running, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        _register_clean_exit_hook()
    except OSError as e:
        logger.debug("写 autosave 运行标记失败: %s", e)
    return crashed_last_time


def _read_prompted_mtime() -> float | None:
    try:
        with open(os.path.join(autosave_dir(), PROMPTED_FLAG), encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return None


def take_pending() -> float | None:
    """返回「值得提示恢复」的存档 mtime；None = 不该提示。

    过滤链：存档不存在 → 过期（> MAX_AGE_DAYS）→ 同一版本已问过。
    """
    latest = latest_path()
    if not os.path.isfile(latest):
        return None
    try:
        mtime = os.path.getmtime(latest)
    except OSError:
        return None
    if (time.time() - mtime) > MAX_AGE_DAYS * 86400:
        return None
    asked = _read_prompted_mtime()
    if asked is not None and abs(asked - mtime) < 1.0:
        return None  # 这个版本已经问过了
    return mtime


def remember_prompted(mtime: float) -> None:
    """记住「这个版本已询问」，无论用户选了是还是否都不再重复打扰。"""
    try:
        with open(os.path.join(autosave_dir(), PROMPTED_FLAG), "w", encoding="utf-8") as f:
            f.write(str(mtime))
    except OSError as e:
        logger.debug("写 autosave 询问标记失败: %s", e)


def describe_mtime(mtime: float) -> str:
    """把 mtime 格式化进提示文案"""
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
