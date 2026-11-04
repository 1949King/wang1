/**
 * 局部重绘桥（抽卡闭环 P4）—— 从 bridge.ts 拆出。
 *
 * 2026-09-27 V4.40.11 拆分理由：bridge.ts 已顶到规模守卫容差（存量文件只许减不许增），
 * 而局部重绘是内聚的独立功能（自动找坏区 → inpaint → 合成），适合独立成模块。
 *
 * 与 bridge.ts 的 `inpaintViaHost` 分工：后者要调用方自带蒙版（"我知道哪坏了"）；
 * 本模块自己找坏区（"帮我看看哪坏了并修掉"），且**坏区外像素逐字节保持原图**。
 * ⚠️ 坏区检测免费，但重绘会真花一次云端额度 ⇒ 必须由用户/Agen 显式触发。
 */

import { BRIDGE, authHeaders, bridgeToken } from "./bridge";

export async function repairImageViaHost(opts: {
  image: string; prompt?: string; model?: string; channel_id?: string;
  size?: string; grid?: number; threshold?: number;
}): Promise<{
  ok: boolean; message?: string; repaired?: boolean; image_data_url?: string;
  boxes?: number[][]; before_score?: number; after_score?: number; used?: number;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/repair-image?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        image: opts.image,
        prompt: opts.prompt || "",
        model: opts.model || "",
        channel_id: opts.channel_id || "",
        size: opts.size || "768x1344",
        ...(opts.grid ? { grid: opts.grid } : {}),
        ...(opts.threshold ? { threshold: opts.threshold } : {}),
      }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `局部重绘异常: ${e}` };
  }
}
