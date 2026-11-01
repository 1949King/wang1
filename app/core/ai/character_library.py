# -*- coding: utf-8 -*-
"""角色库桥接（2026-11-01）：把**既有** CharacterStore 暴露给画布人物卡面板。

## 为什么不新建一套角色存储

仓库里已经有 app/modules/lego/character_management_module.py::CharacterStore
（JSON 持久化在 ~/.video_editor_cache/characters/library.json，字段表 CHARACTER_FIELD_SCHEMA），
还有 canvas_bridge.build_character_prompt 负责把角色压成提示词片段。
再建一套 = 两份真相源，必然漂移（仓库"代码收敛"铁律明令禁止）。

## 本模块只做三件事

1. **归一化**：把角色记录转成画布人物卡能用的形状（card）；
2. **映射**：角色字段（性别/年龄段/外貌）↔ 人物卡字段（gender/age/hair…）；
3. **持久化人物卡**：在角色记录里加一个 person_card 键（额外键，兼容旧数据）。

## 映射规则（可解释、可回退）

| 角色字段 | 人物卡 | 说明 |
|---|---|---|
| gender 女/男 | gender 女生/男生 | 枚举直译 |
| age_range | age | 如「青年」；人物卡 VALUES 有对应英文 |
| appearance | **不硬拆** | 自由文本可能写"黑色长直发，米白衬衫"，硬拆会错；作为 free_text 一起翻译 |
| person_card（本模块写入） | 整卡 | 面板编辑过的结构化字段，优先级最高 |
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 角色性别 → 人物卡性别
_GENDER_MAP = {"女": "女生", "男": "男生", "其他": ""}

#: 人物卡字段白名单（与 prompt_template.FIELD_ORDER 对齐；只存这些，避免把垃圾塞进角色库）
_CARD_KEYS = (
    "ethnicity", "gender", "age", "hair", "face", "outfit", "pose", "prop",
    "setting", "lighting", "mood", "style",
)


def _store():
    """惰性取 CharacterStore（导入这个模块不该有副作用；Qt 模块导入较重）。

    SHIGUANG_CHARACTER_STORE_PATH 可覆盖存储路径：测试用临时文件，
    或在「主库目录不可写」的环境里指向可写位置（见 store_path 的回报）。
    """
    import os

    from app.modules.lego.character_management_module import CharacterStore

    override = str(os.environ.get("SHIGUANG_CHARACTER_STORE_PATH") or "").strip()
    return CharacterStore(store_path=override or None)


def store_path() -> str:
    """当前角色库文件路径（面板据此显示"存在哪"，排障时不用猜）。"""
    try:
        return str(_store()._path)
    except Exception:  # stability-gate: allow-swallow（拿不到路径不影响功能）
        return ""


def writable() -> bool:
    """主库目录是否可写（不可写时面板必须提示，否则用户以为保存成功了）。"""
    import os

    path = store_path()
    if not path:
        return False
    d = os.path.dirname(path) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:  # stability-gate: allow-swallow（目录建不了就是不可写）
        return False
    # 真写一次再删：os.access 会误报（实测 ACL 显示 FullControl，实际写入仍 PermissionError）
    probe = os.path.join(d, ".write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:  # stability-gate: allow-swallow（探针失败 = 不可写，如实返回）
        return False


def _clean_card(card: Any) -> Dict[str, str]:
    if not isinstance(card, dict):
        return {}
    return {k: str(card.get(k)).strip() for k in _CARD_KEYS if str(card.get(k) or "").strip()}


def derive_card(char: Dict[str, Any]) -> Dict[str, str]:
    """角色记录 → 人物卡。

    优先用面板存下来的 person_card（结构化真源）；
    没有就从 gender / age_range 推基础两项（appearance 不硬拆，走 free_text）。
    """
    saved = _clean_card(char.get("person_card"))
    if saved:
        return saved
    card: Dict[str, str] = {}
    g = _GENDER_MAP.get(str(char.get("gender") or "").strip(), "")
    if g:
        card["gender"] = g
    age = str(char.get("age_range") or "").strip()
    if age:
        card["age"] = age
    return card


def prompt_hint(char: Dict[str, Any]) -> str:
    """角色 → 中文提示片段（复用既有 build_character_prompt；后续会被翻成英文）。"""
    try:
        from app.core.canvas_bridge import build_character_prompt

        return str(build_character_prompt(char) or "")
    except Exception:  # stability-gate: allow-swallow（提示片段缺失不影响出图，卡仍可用）
        logger.debug("[character_library] build_character_prompt 失败", exc_info=True)
        return ""


def normalize(char: Dict[str, Any]) -> Dict[str, Any]:
    """对外形状：画布面板只认这几个键。"""
    return {
        "id": str(char.get("id") or ""),
        "name": str(char.get("name") or "未命名角色"),
        "gender": str(char.get("gender") or ""),
        "age_range": str(char.get("age_range") or ""),
        "role_type": str(char.get("role_type") or ""),
        "card": derive_card(char),
        "hint": prompt_hint(char),
        "has_card": bool(_clean_card(char.get("person_card"))),
    }


def list_characters() -> List[Dict[str, Any]]:
    try:
        return [normalize(c) for c in _store().all() if isinstance(c, dict)]
    except Exception:
        logger.exception("[character_library] 读取角色库失败")
        return []


def get_character(char_id: str) -> Optional[Dict[str, Any]]:
    try:
        char = _store().get(str(char_id or ""))
        return normalize(char) if char else None
    except Exception:
        logger.exception("[character_library] 读取角色失败")
        return None


def save_character(*, name: str, card: Any = None, char_id: str = "") -> Dict[str, Any]:
    """新增/更新角色（char_id 存在则更新）。

    返回 {ok, id, name, card, message}；失败给明确原因（不假报成功）。
    """
    nm = str(name or "").strip()
    cleaned = _clean_card(card)
    if not nm:
        return {"ok": False, "id": "", "name": "", "card": {}, "message": "角色名不能为空"}
    try:
        st = _store()
        payload: Dict[str, Any] = {"name": nm}
        if cleaned:
            payload["person_card"] = cleaned
        if char_id:
            if not st.get(str(char_id)):
                return {"ok": False, "id": "", "name": nm, "card": cleaned,
                        "message": "角色不存在（可能已被删除）"}
            if not st.update(str(char_id), payload):
                return {"ok": False, "id": "", "name": nm, "card": cleaned,
                        "message": "保存失败（磁盘写入被拒）"}
            return {"ok": True, "id": str(char_id), "name": nm, "card": cleaned, "message": "角色已更新"}
        new_id = st.add(payload)
        if not new_id:
            return {"ok": False, "id": "", "name": nm, "card": cleaned,
                    "message": "保存失败（磁盘写入被拒）"}
        return {"ok": True, "id": str(new_id), "name": nm, "card": cleaned, "message": "角色已创建"}
    except Exception as e:
        logger.exception("[character_library] 保存角色失败")
        return {"ok": False, "id": "", "name": nm, "card": cleaned,
                "message": f"保存异常：{type(e).__name__}"}


def delete_character(char_id: str) -> Dict[str, Any]:
    cid = str(char_id or "").strip()
    if not cid:
        return {"ok": False, "message": "缺少角色 id"}
    try:
        st = _store()
        if not st.get(cid):
            return {"ok": False, "message": "角色不存在"}
        if not st.remove(cid):
            return {"ok": False, "message": "删除失败（磁盘写入被拒）"}
        return {"ok": True, "message": "角色已删除"}
    except Exception:
        logger.exception("[character_library] 删除角色失败")
        return {"ok": False, "message": "删除异常"}
