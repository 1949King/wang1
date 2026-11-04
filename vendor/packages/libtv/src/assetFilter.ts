/**
 * 素材列表的筛与搜（2026-11-04 · 画布 0.3.49）
 *
 * 为什么需要：⑤ 段原来是一条平铺列表，项目跑到三十几条素材时「找那条成片」只能靠
 * 眼睛从头扫。这里只做两件事 —— **按类型筛**、**按文字搜**，都是用户已经在做的动作
 * （脑子里想的就是「找镜 03 那个视频」），没有引入任何新概念。
 *
 * 搜的范围特意包含 `owner`（出处「镜 03」「剧本」）：用户记得住的往往是**哪一镜**，
 * 而不是文件名叫 `team_a1b2c3_成片.mp4`。
 */
import type { TeamAsset } from "./teamClient";

export type AssetKindFilter = "all" | "video" | "image" | "audio" | "other";

const KIND_LABEL: Record<AssetKindFilter, string> = {
  all: "全部",
  video: "🎬 视频",
  image: "🖼 图片",
  audio: "🎵 音频",
  other: "📦 其他",
};

export function kindLabel(kind: AssetKindFilter): string {
  return KIND_LABEL[kind] || KIND_LABEL.all;
}

/** 后端的 kind 是 image/video/audio/text/file；筛选项把它们收成四类 + 全部。 */
export function bucketOf(kind: string): Exclude<AssetKindFilter, "all"> {
  const k = String(kind || "").toLowerCase();
  if (k === "video" || k === "image" || k === "audio") return k;
  return "other";
}

export function filterAssets(
  list: TeamAsset[],
  kind: AssetKindFilter = "all",
  query = "",
): TeamAsset[] {
  const q = query.trim().toLowerCase();
  return (list || []).filter((a) => {
    if (kind !== "all" && bucketOf(a.kind) !== kind) return false;
    if (!q) return true;
    const hay = `${a.name || ""} ${a.owner || ""} ${a.author || ""}`.toLowerCase();
    return hay.includes(q);
  });
}

/** 每个筛选项上的数字（用于 chip 上的角标，避免点进去才发现是空的）。 */
export function assetCounts(list: TeamAsset[]): Record<AssetKindFilter, number> {
  const out: Record<AssetKindFilter, number> = { all: 0, video: 0, image: 0, audio: 0, other: 0 };
  (list || []).forEach((a) => {
    out.all += 1;
    out[bucketOf(a.kind)] += 1;
  });
  return out;
}

/**
 * 空结果时该说什么。三种空法原因完全不同，糊成一句「没有素材」会让人以为传丢了：
 *   · 项目本来就没有素材
 *   · 有素材，但筛/搜把它藏了（最容易被误判成「丢了」）
 */
export function emptyAssetHint(total: number, kind: AssetKindFilter, query: string): string {
  if (!total) return "这个项目还没有素材。成片视频、生成的图都可以从这里传。";
  const byKind = kind === "all" ? "" : `「${kindLabel(kind)}」`;
  const byQuery = query.trim() ? `含「${query.trim()}」的` : "";
  return `当前 ${byKind}${byQuery}素材一条都没匹配到 —— 共 ${total} 条素材还在，清空筛选/搜索就能看到。`;
}
