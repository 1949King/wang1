/**
 * assetFromOutputs.ts — 「把生成结果收进我的资产」的映射层（纯函数 · 可单测）。
 *
 * ## 为什么单独抽出来
 *
 * 右键菜单本体是 UI（vitest 无 jsdom，测不到），但**真正的判断**只有三件：
 * 有没有可存的产物 URL / 该归到哪个 kind / 标题怎么裁。这三件都是纯逻辑，
 * 抽到这里就能用单测锁住，将来加新分类（音频、3D）也只改这一处。
 *
 * ## 纪律：宁可返回 null，不造空资产
 *
 * `LocalAsset` 的 kind 只有 image / video / text。文本类历史条目没有 URL，
 * 音频类也不在集合里 —— 这些一律 **返回 null**（菜单项置灰并说明原因），
 * 而不是塞一条 url 为空、点开是破图的资产。项目口径：不假装成功。
 */

/** 与 `localLibrary.LocalAsset` 对齐的写入载荷（不含 id / createdAt）。 */
export type AssetDraft = {
  title: string;
  kind: "image" | "video" | "text";
  url: string;
  prompt?: string;
};

/** 资产标题上限：卡片一行放得下，也避免长提示词把名字撑爆。 */
export const ASSET_TITLE_MAX = 40;

function tidyTitle(raw: string, fallback: string): string {
  const s = String(raw || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!s) return fallback;
  return s.length > ASSET_TITLE_MAX ? `${s.slice(0, ASSET_TITLE_MAX)}…` : s;
}

/**
 * 输出历史条目 → 资产载荷。没有产物 URL（文本类）或音频类返回 null。
 *
 * @param e 历史条目里本函数真正用到的字段（不依赖 HistoryEntry 全量形状）
 */
export function assetFromHistory(e: {
  category: string;
  title?: string;
  prompt?: string;
  assetUrl?: string;
}): AssetDraft | null {
  const url = String(e.assetUrl || "").trim();
  if (!url) return null;
  if (e.category === "image") {
    return { title: tidyTitle(e.title || "", "图片"), kind: "image", url, prompt: e.prompt || undefined };
  }
  if (e.category === "video") {
    return { title: tidyTitle(e.title || "", "视频"), kind: "video", url, prompt: e.prompt || undefined };
  }
  // audio / text 不在 LocalAsset 的 kind 里，收进来会变成点不开的卡片
  return null;
}

/**
 * 图库缩略图 → 资产载荷。
 *
 * 注意：视频项传进来的通常是**首帧封面**（posterUrl），存的是封面而不是视频本体 ——
 * 这是有意的：图库本来就只保证有缩略图，存封面至少能在资产页看到是哪一条。
 */
export function assetFromGallery(it: {
  kind: "image" | "video";
  title?: string;
  thumb?: string;
  prompt?: string;
}): AssetDraft | null {
  const url = String(it.thumb || "").trim();
  if (!url) return null;
  const isVideo = it.kind === "video";
  return {
    title: tidyTitle(it.title || "", isVideo ? "视频" : "图片"),
    kind: isVideo ? "video" : "image",
    url,
    prompt: it.prompt || undefined,
  };
}

/** 菜单项置灰的理由（给 UI 用；能存则返回空串）。 */
export function whyNotSaveable(category: string, url: string): string {
  if (String(url || "").trim()) return "";
  if (category === "text") return "文本结果没有图片文件，存进资产会是一张破图";
  if (category === "audio") return "音频暂不支持存入我的资产";
  return "这一条还没有生成结果";
}
