/**
 * 画质档 → 出图尺寸（单一真源，2026-10-27）。
 *
 * 为什么单独成模块：画布节点、意图卡片、生成请求三处都要显示/使用同一个尺寸，
 * 各写一套必然漂移。数值与后端 app/core/ai/local_image_plan.py 同口径：
 *   SDXL 长边上限 draft 768 / standard 832 / fine·cinema 1024
 *   （2026-10-27 实测：1024²=30.7s · 832²=16.4s · 768²=14.3s）
 * 后端仍会按**真实模型族**再收口一次（SD1.5 上限更小），这里只做展示与请求初值。
 */

/** 画质档 → 长边上限（SDXL 口径）。 */
export const QUALITY_MAX_SIDE: Record<string, number> = {
  draft: 768,
  standard: 832,
  fine: 1024,
  cinema: 1024,
};

/** 画质档中文名（节点/卡片共用，避免各处再写一份 map）。 */
export const QUALITY_LABEL: Record<string, string> = {
  draft: "草稿",
  standard: "标准",
  fine: "精修",
  cinema: "电影级",
};

/** 按画幅与画质档估算出图尺寸：等比缩放 + 对齐 64，长边不超过档位上限。 */
export function estimateImageSize(
  aspect: string,
  quality = "standard",
): { width: number; height: number } {
  const maxSide = QUALITY_MAX_SIDE[String(quality || "standard").toLowerCase()] ?? 832;
  const a = String(aspect || "").toLowerCase();
  let w = 1024;
  let h = 1024;
  if (a.includes("9:16") || a.includes("portrait")) {
    w = 720;
    h = 1280;
  } else if (a.includes("16:9") || a.includes("landscape")) {
    w = 1280;
    h = 720;
  } else if (a.includes("4:5")) {
    w = 1024;
    h = 1280;
  }
  const scale = Math.min(1, maxSide / Math.max(w, h));
  const align = (v: number) =>
    Math.max(256, Math.min(maxSide, Math.round((v * scale) / 64) * 64));
  return { width: align(w), height: align(h) };
}

/** 人类可读：832×832。 */
export function describeImageSize(aspect: string, quality = "standard"): string {
  const { width, height } = estimateImageSize(aspect, quality);
  return width + "×" + height;
}
