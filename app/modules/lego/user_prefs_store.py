"""
短剧用户偏好持久化模块
========================
把 DramaCrawler 的 _user_preferences / _favorites / _view_history 从内存
持久化到 JSON 文件,程序关闭/重启数据不丢。

不破坏 DramaCrawler 现有 API,只提供 3 个函数:
  - load_user_prefs()    -> Dict
  - save_user_prefs(prefs: Dict) -> None
  - prefs_storage_path() -> str  (供 UI 显示)
"""
import os
import json
import logging
import threading
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

# 存储路径: app/data/store/drama_prefs.json
_HERE = os.path.dirname(os.path.abspath(__file__))
_STORE_DIR = os.path.normpath(os.path.join(_HERE, "..", "data", "store"))
_DEFAULT_PATH = os.path.join(_STORE_DIR, "drama_prefs.json")

_lock = threading.RLock()


def prefs_storage_path() -> str:
    """返回当前持久化文件路径 (供 UI 显示)"""
    return _DEFAULT_PATH


def load_user_prefs() -> Dict[str, Any]:
    """
    从磁盘加载用户偏好。

    Returns:
        {
            "user_preferences": {...},   # 用户偏好
            "favorites": [drama_id, ...], # 收藏列表
            "view_history": [drama_id, ...] # 观看历史(最新在前)
        }
    """
    if not os.path.isfile(_DEFAULT_PATH):
        return {"user_preferences": {}, "favorites": [], "view_history": []}
    try:
        with _lock:
            with open(_DEFAULT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        # 兜底: 字段缺失不报错
        data.setdefault("user_preferences", {})
        data.setdefault("favorites", [])
        data.setdefault("view_history", [])
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"加载 drama_prefs.json 失败, 使用默认值: {e}")
        return {"user_preferences": {}, "favorites": [], "view_history": []}


def save_user_prefs(prefs: Dict[str, Any]) -> bool:
    """
    把用户偏好写入磁盘(原子写入,防止半路崩溃损坏文件)。

    Args:
        prefs: 至少含 user_preferences/favorites/view_history 三个键

    Returns:
        True=成功, False=失败
    """
    try:
        os.makedirs(_STORE_DIR, exist_ok=True)
        data = {
            "user_preferences": prefs.get("user_preferences", {}),
            "favorites":        list(prefs.get("favorites", [])),
            "view_history":     list(prefs.get("view_history", [])),
        }
        with _lock:
            tmp = _DEFAULT_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 原子替换
            if os.path.isfile(_DEFAULT_PATH):
                os.replace(tmp, _DEFAULT_PATH)
            else:
                os.rename(tmp, _DEFAULT_PATH)
        return True
    except OSError as e:
        logger.error(f"保存 drama_prefs.json 失败: {e}")
        return False


def add_to_favorites(drama_id: str) -> List[str]:
    """便捷: 追加收藏, 写盘, 返回最新列表"""
    prefs = load_user_prefs()
    if drama_id not in prefs["favorites"]:
        prefs["favorites"].append(drama_id)
    save_user_prefs(prefs)
    return prefs["favorites"]


def remove_from_favorites(drama_id: str) -> List[str]:
    """便捷: 移除收藏, 写盘, 返回最新列表"""
    prefs = load_user_prefs()
    if drama_id in prefs["favorites"]:
        prefs["favorites"].remove(drama_id)
    save_user_prefs(prefs)
    return prefs["favorites"]


def add_to_history(drama_id: str, max_len: int = 100) -> List[str]:
    """便捷: 追加观看历史(最新在前), 写盘"""
    prefs = load_user_prefs()
    if drama_id in prefs["view_history"]:
        prefs["view_history"].remove(drama_id)
    prefs["view_history"].insert(0, drama_id)
    prefs["view_history"] = prefs["view_history"][:max_len]
    save_user_prefs(prefs)
    return prefs["view_history"]


def set_user_preferences(prefs_dict: Dict[str, Any]) -> bool:
    """便捷: 写入用户偏好"""
    prefs = load_user_prefs()
    prefs["user_preferences"].update(prefs_dict)
    return save_user_prefs(prefs)
