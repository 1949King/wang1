/**
 * outputHistory.ts — 「输出历史」的**纯逻辑**（2026-10-06，对标参考产品的输出历史面板）。
 *
 * 为什么单独成模块：面板（`OutputHistoryPanel.tsx`）只负责画，**分类/收集/过滤**这些判据
 * 抽出来才能被单测直接覆盖 —— 判据错的话，用户会"搜不到自己的东西"（比没有面板更糟）。
 *
 * 数据从哪来（**不新造账本**）
 * ==========================
 * 全部取自**画布节点**已有的字段（生成收尾会回写）：
 *   · 产物  ：`imageUrl` / `videoUrl` / `audioUrl`（视频另有 `posterUrl` / `firstFrameUrl`）
 *   · 文本  ：`content` / `text`
 *   · 提示词：`prompt`（文本类另看 `text` / `content`）
 *   · 元信息：`lastSeed` / `lastSeedSent` / `proxyScore` / `recommendation`
 * ⚠️ 本模块**只读**，不写任何状态；也不统计"没产物的节点"（那会把历史列表塞满空条目）。
 */
export type HistoryCategory = "text" | "image" | "video" | "audio";

export const CATEGORY_LABEL: Record<HistoryCategory, string> = {
  text: "文本",
  image: "图像",
  video: "视频",
  audio: "音频",
};

export interface HistoryEntry {
  /** 节点 id（用于「定位到该节点」） */
  id: string;
  kind: string;
  category: HistoryCategory;
  title: string;
  prompt: string;
  model: string;
  /** 产物 URL（文本类为空） */
  assetUrl: string;
  /** 文本类的内容（用于搜索与展示） */
  textBody: string;
  seed: number | null;
  seedSent: boolean;
  score: number | null;
  /** 是否有可用产物（无产物的节点不进历史） */
  hasOutput: boolean;
}

/** 节点 kind → 历史分类；不参与历史的 kind 返回 null。 */
export function categoryOf(kind: string): HistoryCategory | null {
  switch (kind) {
    case "video":
      return "video";
    case "audio":
    case "music":
      return "audio";
    case "image":
    case "shot":
    case "digitalHuman":
    case "panorama":
    case "director":
    case "animation":
    case "source":
      return "image";
    case "script":
    case "text":
    case "prompt":
    case "markdown":
    case "storyboard":
    case "shotlist":
    case "note":
    case "config":
      return "text";
    default:
      // group / generator / directorCard 等：不是"产物"，不进历史
      return null;
  }
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function numOrNull(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** 取产物 URL（视频节点优先成片本体，退化到首帧/封面）。 */
function assetOf(kind: string, d: Record<string, unknown>): string {
  if (kind === "video") return str(d.videoUrl) || str(d.firstFrameUrl) || str(d.posterUrl);
  if (kind === "audio" || kind === "music") return str(d.audioUrl);
  if (kind === "animation") return str(d.sheetUrl) || str(d.imageUrl);
  return str(d.imageUrl);
}

/** 取"输出内容"文本（文本类节点用 content/text）。 */
function bodyOf(d: Record<string, unknown>): string {
  return str(d.content) || str(d.text) || "";
}

export function collectHistory(
  nodes: Array<{ id: string; data?: Record<string, unknown> }>,
): HistoryEntry[] {
  const out: HistoryEntry[] = [];
  for (const n of nodes || []) {
    const d = (n?.data || {}) as Record<string, unknown>;
    const kind = str(d.kind) || str((d as { type?: unknown }).type);
    const category = categoryOf(kind);
    if (!category) continue;
    const assetUrl = assetOf(kind, d);
    const textBody = bodyOf(d);
    const hasOutput = Boolean(assetUrl) || Boolean(textBody);
    if (!hasOutput) continue; // 没产物的不进历史
    const title =
      str(d.title) ||
      (str(d.prompt) ? str(d.prompt).slice(0, 24) : "") ||
      (textBody ? textBody.slice(0, 24) : "") ||
      String(n.id);
    out.push({
      id: String(n.id),
      kind,
      category,
      title,
      prompt: str(d.prompt),
      model: str(d.model),
      assetUrl,
      textBody,
      seed: numOrNull(d.lastSeed),
      seedSent: d.lastSeedSent === true,
      score: numOrNull(d.proxyScore),
      hasOutput,
    });
  }
  return out;
}

/** 命中判据：提示词 / 输出内容 / 标题 / 模型 / 种子（对标参考产品的搜索范围并多给一个种子）。 */
export function matchesQuery(e: HistoryEntry, query: string): boolean {
  const q = (query || "").trim().toLowerCase();
  if (!q) return true;
  const hay = [e.prompt, e.textBody, e.title, e.model,
    e.seed != null ? String(e.seed) : ""].join(" ").toLowerCase();
  return hay.includes(q);
}

export function filterHistory(
  entries: HistoryEntry[],
  opts: { category?: HistoryCategory | "all"; query?: string } = {},
): HistoryEntry[] {
  const cat = opts.category ?? "all";
  const q = opts.query ?? "";
  return (entries || []).filter(
    (e) => (cat === "all" || e.category === cat) && matchesQuery(e, q),
  );
}

/** 分类计数（tab 上显示数量；"全部"= 总数）。 */
export function countByCategory(entries: HistoryEntry[]): Record<string, number> {
  const c: Record<string, number> = { all: (entries || []).length, text: 0, image: 0, video: 0, audio: 0 };
  for (const e of entries || []) c[e.category] += 1;
  return c;
}

/**
 * 生成「可复用的配方」一行文本：提示词 + 种子（+ 模型）。
 *
 * 这是抽卡闭环的**兑现口**：账本里存了 `best_seed`，用户终于能一键把"那次出好图的配方"抄走。
 * 没有种子时如实只给提示词（**不编造种子**）。
 */
export function recipeOf(e: HistoryEntry): string {
  const parts: string[] = [];
  if (e.prompt) parts.push(e.prompt.trim());
  if (e.seed != null) parts.push(e.seedSent ? `seed=${e.seed}` : `seed=${e.seed}(渠道未透传)`);
  if (e.model) parts.push(`model=${e.model}`);
  return parts.join("  ");
}
