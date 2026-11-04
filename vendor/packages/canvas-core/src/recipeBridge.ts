/**
 * 配方 · Agent 事件桥（2026-10-19）
 * ==================================
 * 链路：Agent 能力 `canvas.apply_recipe` → 后端 SSE `/host/agent/events`
 *      → 本文件 `subscribeAgentEvents` 收到 `type === "recipe.apply"`
 *      → 匹配配方 → `applyRecipe()` 铺到画布。
 *
 * 为什么不在 `bridge.ts` 里做：那是 HTTP 桥（fetch 封装），而这里是**事件订阅**，
 * 语义不同；独立文件也让「Agent 只能建议」这件事有了第一个真正的执行端。
 *
 * 诚实失败：配方匹配不到就报「没有找到对应配方」，**绝不硬编一张凑数的卡**。
 */
import { subscribeAgentEvents } from "./agentEvents";
import { applyRecipe, listRecipes, matchRecipeByIntent } from "./recipe";

export type RecipeEventPayload = {
  /** 直接指定配方 id（Agent 从列表里选的） */
  recipe_id?: string;
  /** 或用一句话让前端匹配（Agent 只转述用户原话时） */
  intent?: string;
};

/** 事件类型：与后端 `canvas.apply_recipe` 的推送保持一致 */
export const RECIPE_APPLY_EVENT = "recipe.apply";

/**
 * 挂上配方事件桥，返回取消订阅函数。
 * 调用方应在组件卸载时调用返回值，避免重复订阅（EventSource 多开会重复消费）。
 */
export function installRecipeAgentBridge(
  onStatus: (msg: string) => void,
): () => void {
  return subscribeAgentEvents({
    onEvent(env) {
      if (env.type !== RECIPE_APPLY_EVENT) return;
      const p = (env.payload || {}) as RecipeEventPayload;
      const list = listRecipes();
      const recipe = p.recipe_id
        ? list.find((r) => r.id === p.recipe_id) || null
        : matchRecipeByIntent(p.intent || "");

      if (!recipe) {
        const tip = p.intent
          ? `没有找到和「${p.intent}」对应的配方，可以先选中几张卡片存一个`
          : "没有找到对应配方，可先选中几张卡片存一个";
        onStatus(tip);
        return;
      }

      const ids = applyRecipe(recipe);
      onStatus(
        ids.length > 0
          ? `已按配方「${recipe.name}」铺开 ${ids.length} 张卡片`
          : `配方「${recipe.name}」没有卡片可铺`,
      );
    },
    onError() {
      /* SSE 自带重连，这里不刷屏 */
    },
  });
}
