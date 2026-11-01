# -*- coding: utf-8 -*-
"""人物卡预览 + 角色库路由（2026-11-01）。

为什么单独成文件：canvas_routes_post.py 已贴 2000 行规模门禁（SIZE），
按 canvas_routes_team.py 的既有做法抽成 mixin —— 主文件只留 import + 一个基类。

覆盖：
  POST /host/person-card/preview   人物卡 → 英文提示词 + 负向 + 题材分档
  POST /host/characters/list       角色库列表（复用 CharacterStore）
  POST /host/characters/save       新建/更新角色（含 person_card）
  POST /host/characters/delete     删除角色
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs() -> Any:
    """取 canvas_server 单例（沿用主文件的惰性导入约定，避免循环导入）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasDrawPlanRoutesMixin:
    """人物卡/角色库路由。宿主类需提供 _json / _check_host_token。"""

    # ── POST /host/person-card/preview：人物卡 → 英文提示词（2026-11-01 · C 项）──
    # 为什么放后端：词典与排序规则只有一份（prompt_template），前端自己抄一遍必然漂移。
    # 面板据此显示「真正送进模型的那句话」，用户就不会觉得是黑盒。
    @_route_post("/host/person-card/preview")
    def _p_host_person_card_preview(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            from app.core.ai import negative_presets as NP
            from app.core.ai import prompt_template as PT

            card = body.get("person_card") if isinstance(body.get("person_card"), dict) else None
            genre = str(body.get("genre") or "")
            free = str(body.get("free_text") or "").strip()
            prompt = PT.render_prompt(card, extra=free)
            # 分档必须看**中文原值**：渲染后是英文（hanfu/ancient architecture），
            # 关键词表是中文，拿英文去猜永远落到默认档（实测 bug）。
            _zh = " ".join(str(v) for v in (card or {}).values()) + " " + free
            self._json(200, {
                "ok": True,
                "prompt": prompt,
                "genre": genre or NP.guess_genre(_zh),
                "negative": NP.build_negatives(prompt=free or prompt, genre=genre),
                "fields": PT.normalize_card(card),
            })
        except Exception:
            logger.exception("[/host/person-card/preview] 失败")
            self._json(500, {"ok": False, "message": "人物卡预览失败"})


    # ── 角色库（2026-11-01）：复用既有 CharacterStore，画布人物卡面板读写 ──
    @_route_post("/host/characters/list")
    def _p_host_characters_list(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            from app.core.ai import character_library as CL

            self._json(200, {
                "ok": True,
                "characters": CL.list_characters(),
                "store_path": CL.store_path(),
                "writable": CL.writable(),
            })
        except Exception:
            logger.exception("[/host/characters/list] 失败")
            self._json(500, {"ok": False, "message": "角色库读取失败"})

    @_route_post("/host/characters/save")
    def _p_host_characters_save(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            from app.core.ai import character_library as CL

            res = CL.save_character(
                name=str(body.get("name") or ""),
                card=body.get("person_card") or body.get("card"),
                char_id=str(body.get("id") or ""),
            )
            self._json(200 if res.get("ok") else 400, res)
        except Exception:
            logger.exception("[/host/characters/save] 失败")
            self._json(500, {"ok": False, "message": "角色保存失败"})

    @_route_post("/host/characters/delete")
    def _p_host_characters_delete(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        try:
            from app.core.ai import character_library as CL

            res = CL.delete_character(str(body.get("id") or ""))
            self._json(200 if res.get("ok") else 400, res)
        except Exception:
            logger.exception("[/host/characters/delete] 失败")
            self._json(500, {"ok": False, "message": "角色删除失败"})


