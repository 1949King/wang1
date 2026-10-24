/**
 * 画布「AI 增强意图目录」桥（Wave 0 #13 孤儿端点接线第 3 条，2026-10-15）
 * ======================================================
 * 缺口证据：`app/core/canvas_routes_get.py:729` `@_route_get("/host/enhance-intents")`
 * 返回 `canvas_enhance.available_intents()`（**不加载任何模型**的纯目录）+ 质量档。
 * 前端零调用 ⇒ 后果：`NoviceInspector.tsx` 的 AI 增强区把意图**硬编码成两个按钮**
 * （doEnhance 的参数类型是字面量 `"sharpen" | "cutout"`），
 * 后端 `ENHANCE_INTENTS`（app/core/canvas_enhance.py:54）里的 `face` **前端完全够不着**，
 * 后端加意图前端也不自动长出来 ⇒ 又一处「后端齐全、前端没有」的漂移点。
 *
 * ⚠️⚠️ **语义红线：绝不把本端点的 quality_tiers 塞进前端 `QUALITY_TIERS`**
 *   - 本端点 `quality_tiers` = `canvas_enhance.QUALITY_TIERS` = **fast / standard / high**
 *     （超分实现档位，high 才触发 RealESRGAN 下载，见 canvas_enhance.py:80）
 *   - 前端 `novice/types.ts:80` 的 `QUALITY_TIERS` = **draft / standard / fine / cinema**
 *     （**生成画质档**，喂给 generate-image/video 的 quality 参数）
 *   两者名字撞车、语义完全不同。混用会把「超分档」当成「生成画质档」传出去，
 *   导致 quality 参数错传 ⇒ 静默的降级/失败。**本文件只取 `intents`，不碰 quality_tiers。**
 *
 * 单一通道纪律：只做 fetch + 纯函数筛选，判定仍在后端（`apply_intents`），
 * 前端**不复制任何一条意图语义**，也不自己判断引擎可用性。
 */
import { BRIDGE, bridgeToken, authHeaders } from "./bridge";

/** 一条意图（镜像后端 available_intents() 的行） */
export type EnhanceIntent = {
  id: string;
  label: string;
  hint: string;
};

export type EnhanceIntentCatalog = {
  ok: boolean;
  intents?: EnhanceIntent[];
  message?: string;
};

/**
 * 拉意图目录。**永不抛**：拿不到就返回空目录，
 * 由调用方决定回落到哪套 UI（不能因为一个只读目录接口挂了就白屏）。
 */
export async function fetchEnhanceIntents(): Promise<EnhanceIntentCatalog> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/enhance-intents?token=${encodeURIComponent(token)}`,
      { headers: authHeaders(false) },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, intents: [], message: `意图目录拉取失败: ${e}` };
  }
}

// ── 纯函数筛选（vitest 无 jsdom，逻辑抽出来才可测）────────────────────

/**
 * **可一键执行的意图**白名单。
 *
 * 判据（不是「后端支持就都渲染」）：**前端当前能否提供该意图所需的必填参数**。
 * 逐条依据 app/core/canvas_enhance.py 的 `_step_*` 实现：
 *
 *| 意图    | 必填 params      | 前端能否提供 | 收录 |
 *  |---------|------------------|--------------|------|
 *  | face    | 无（无脸则原样返回）| ✅ 纯按钮即可  | 是 |
 *  | cutout  | 无（bg_color 缺省=透明底）| ✅        | 是 |
 *  | sharpen | 无（quality 是选档不是必填）| ✅          | 是 |
 *  | heal    | **`params.mask` 遮罩必填**（canvas_enhance.py:216-219，缺则 skipped「缺少遮罩」）| ❌ 画布无遮罩涂抹入口 | 否 |
 *  | style   | `style` / `strength`（有默认值 cyberpunk/0.8）| ⚠️ 能跑但默认「cyberpunk」对竖屏短剧是无意义的默认审美 | 否 |
 *
 * ⚠️ 收录 heal 会造出「点了必然报缺少遮罩」的死按钮 —— 违反诚实纪律。
 * ⚠️ 收录 style 会在用户没选风格时静默套用 cyberpunk —— 属于「随机效果」，本项目明令禁止。
 * 二者等有对应输入控件后再放开（放开时改这两个判据即可，目录仍从后端取，不改前端常量表）。
 */
export const DIRECT_INTENTS: readonly string[] = ["face", "cutout", "sharpen"];

/**
 * 从后端目录里挑出**前端能直接一键执行**的意图。
 * - 保持**后端目录顺序**（后端 ENHANCE_INTENTS 的声明顺序即推荐序），前端不重排。
 * - 目录里出现未知 id（如后端新增了前端没适配的意图）→ 排除，避免点了走不通。
 * - 目录里少了白名单里的某项 → 不补齐（后端删了就是不支持了，前端不自己加回去）。
 * - `catalog.intents` 缺失/空 → 返回空数组，调用方回落到既有硬编码 UI。
 */
export function selectDirectIntents(
  catalog: EnhanceIntentCatalog | null | undefined,
): EnhanceIntent[] {
  const list = catalog?.intents;
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.filter((it) => it && DIRECT_INTENTS.includes(String(it.id)));
}

/** 目录里被排除的意图（用于 UI 如实说明「为什么不给你这个按钮」，不静默隐藏）。 */
export function excludedIntents(
  catalog: EnhanceIntentCatalog | null | undefined,
): EnhanceIntent[] {
  const list = catalog?.intents;
  if (!Array.isArray(list) || list.length === 0) return [];
  return list.filter((it) => it && !DIRECT_INTENTS.includes(String(it.id)));
}

/** 一行执行文案：优先用后端 label（单一真源），**trim 后为空也要回落 id**
 *  —— 否则按钮渲染成空白（`{"  " || id}` 在 JS 里是 `"  "`，不是 falsy）。 */
export function intentButtonLabel(intent: EnhanceIntent): string {
  const label = String(intent?.label || "").trim();
  if (label) return label;
  return String(intent?.id || "").trim();
}