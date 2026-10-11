/**
 * 画布 AI 增强桥（LibTV 对标补强 刀3，2026-10-12）—— 从 bridge.ts 独立成模块。
 *
 * 拆分理由与 canvasRepair.ts 相同：bridge.ts 已顶到规模守卫容差（2043/2046，
 * 仅 3 行余量 = 禁改），新逻辑一律另开文件、bridge 只留薄入口。
 *
 * 承载三件（全部复用后端既有端点，与 Agent 能力同一实现，不造第二链路）：
 *  - enhanceImageViaHost → POST /host/canvas-enhance（AI 超分 sharpen / AI 抠像 cutout）
 *    （与 Agent 能力 canvas.ai_upscale / canvas.ai_matte 同一后端）
 *  - scriptWriteViaHost  → POST /host/script-write（文本生剧本）
 *    （与 Agent 能力 pipeline.script_write 同一后端 script_writer.py）
 *  - toEnhanceDataUrl    → imageUrl（data: 或 /inbox_file/…）→ data URL 归一化
 *    （canvas-enhance 后端只认 data URL；画布节点图可能是 inbox 路径）
 *
 * ⚠️ 诚实纪律：后端 apply_intents 会如实回报实际引擎与降级（degraded），
 * 前端必须原样展示给用户，不得把「双三次插值」说成「AI 超分」。
 */

import { BRIDGE, authHeaders, bridgeToken } from "./bridge";

/** 节点图 URL → data URL（canvas-enhance 后端仅认 data URL；失败返回空串）。 */
export async function toEnhanceDataUrl(url: string): Promise<string> {
  const u = (url || "").trim();
  if (!u) return "";
  if (u.startsWith("data:")) return u;
  try {
    const res = await fetch(u);
    if (!res.ok) return "";
    const blob = await res.blob();
    return await new Promise<string>((resolve) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result || ""));
      fr.onerror = () => resolve("");
      fr.readAsDataURL(blob);
    });
  } catch {
    return "";
  }
}

/** 意图级增强（超分/抠像共用）—— 返回后端的诚实报告（applied/skipped/engine/degraded）。 */
export async function enhanceImageViaHost(opts: {
  image: string;               // data URL
  intents: string[];           // ["sharpen"] 超分 | ["cutout"] 抠像
  quality?: string;            // fast/standard/high（high 档 RealESRGAN 首次需下载）
  params?: Record<string, unknown>;
}): Promise<{
  ok: boolean; message?: string; image_data_url?: string; changed?: boolean;
  applied?: { intent: string; label: string; engine?: string;
              degraded?: boolean; reason?: string }[];
  skipped?: { intent: string; label: string; reason?: string }[];
  quality?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/canvas-enhance?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        image: opts.image,
        intents: opts.intents,
        quality: opts.quality || "standard",
        params: opts.params || {},
      }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `AI 增强异常: ${e}` };
  }
}

/** 文本生剧本：主题 → LLM 完整剧本（云→Ollama→模板三级降级，fallback 如实标注）。 */
export async function scriptWriteViaHost(opts: {
  topic: string;
  duration_seconds?: number;
  scene_count?: number;
  style?: string;
}): Promise<{
  ok: boolean; script?: string; fallback?: boolean;
  source?: "llm" | "template" | "user"; message?: string; error?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/script-write?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        topic: opts.topic,
        duration_seconds: opts.duration_seconds || 30,
        ...(opts.scene_count ? { scene_count: opts.scene_count } : {}),
        style: opts.style || "",
      }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `剧本生成异常: ${e}` };
  }
}
