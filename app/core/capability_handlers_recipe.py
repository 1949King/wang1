"""配方（Recipe）能力处理器 —— 2026-10-19

为什么独立成文件：`capability_handlers.py` 已 1,985/2,000 行（体积守卫上限只剩 15 行），
按既有惯例（`capability_handlers_media.py` / `capability_handlers_editor_skills.py`）拆出。

★ 架构红线：**Python 侧不直接操作画布**。
画布 store 活在 WebView 里，唯一触达方式是 SSE 事件 ⇒ 这里只做
「构造事件 + 广播」，真正建节点由前端 `recipeBridge.ts` 收到 `recipe.apply` 后执行。

为什么不做 `canvas.list_recipes`：配方库在前端 localStorage，
后端读不到；也不需要读 —— Agent 只转述用户原话（intent），
由前端用 LCS 打分匹配。匹配不到时**前端诚实提示**，不硬编凑数。
"""
from typing import Any, Dict

try:
    from app.core.capability_dispatcher import CapabilityRequest, CapabilityResult
    from app.core.canvas_bridge import broadcast_agent_event, make_agent_event
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.capability_dispatcher import CapabilityRequest, CapabilityResult  # type: ignore
    from core.canvas_bridge import broadcast_agent_event, make_agent_event  # type: ignore


class RecipeCapabilityHandlers:
    """Agent 侧的配方入口：一句话 → 事件 → 前端铺卡。"""

    def apply_recipe(self, req: CapabilityRequest) -> CapabilityResult:
        p: Dict[str, Any] = req.params or {}
        intent = str(p.get("intent") or "").strip()
        recipe_id = str(p.get("recipe_id") or "").strip()

        # 两个都没给 = 调用方没说清要铺哪套配方 ⇒ 诚实失败，不猜
        if not intent and not recipe_id:
            return CapabilityResult(
                req.request_id, False, error="需要提供 intent（一句话）或 recipe_id"
            )

        evt = make_agent_event(
            "recipe.apply",
            {"intent": intent, "recipe_id": recipe_id},
            from_agent="canvas.apply_recipe",
            to_agent="canvas",
        )
        broadcast_agent_event(evt)
        return CapabilityResult(
            req.request_id,
            True,
            output={
                "event_id": evt["id"],
                "intent": intent,
                "recipe_id": recipe_id,
                "note": "事件已广播；实际铺卡在前端执行，结果以状态条提示为准",
            },
            error=None,
        )
