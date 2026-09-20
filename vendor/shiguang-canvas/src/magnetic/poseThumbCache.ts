/**
 * 数字人节点 · 姿势元数据 + 轻量缩略图缓存
 *
 * 背景：riggedHumanoid.ts 锁了 30 个 PosePresetId 姿势表（每个含 JointPose），
 * mediaExtraNodes.tsx 锁了 DigitalHumanData 节点渲染。本模块做"壳"：
 *   - 姿势 id → 中文名 / 类别 / 适用场景（从源 PosePresetId + label 派生）
 *   - 缩略图 URL 缓存（按 poseId + characterId 维度 LRU）
 *
 * 锁了的部分碰不到，**只能在它们外面做桥**。这正是补强而非重写的位置。
 */

export type PoseCategory = "static" | "action" | "weapon" | "extreme" | "emotion";

// @source: riggedHumanoid.ts: POSE_PRESETS (硬绑，源改了请同步)
const POSE_META: Record<string, { label: string; category: PoseCategory; hint: string }> = {
  idle:         { label: "站立",   category: "static",   hint: "默认站姿 · 适用于多数对话场景" },
  wave:         { label: "挥手",   category: "static",   hint: "打招呼 / 致意" },
  think:        { label: "思考",   category: "emotion",  hint: "托腮或侧头，适合内心独白" },
  point:        { label: "指向",   category: "static",   hint: "指引目标 · 镜头感强" },
  hands_hips:   { label: "叉腰",   category: "static",   hint: "自信 / 准备开打" },
  cross_arms:   { label: "抱臂",   category: "static",   hint: "旁观 / 不耐烦" },
  sit:          { label: "坐姿",   category: "static",   hint: "采访 / 室内" },
  fight:        { label: "戒备",   category: "action",   hint: "战斗起手式" },
  bow:          { label: "鞠躬",   category: "emotion",  hint: "致谢 / 道歉" },
  jump_kick:    { label: "飞踢",   category: "extreme",  hint: "武打高潮" },
  sword_up:     { label: "举剑",   category: "weapon",   hint: "古装持剑 / 蓄力" },
  aim:          { label: "瞄准",   category: "weapon",   hint: "射击 / 持枪" },
  staff:        { label: "持棍",   category: "weapon",   hint: "棍棒 / 杖" },
  phone:        { label: "打电话", category: "static",   hint: "现代都市场景" },
  lean_wall:    { label: "靠墙",   category: "static",   hint: "街头 / 等待" },
  hands_pockets: { label: "插兜",   category: "static",   hint: "轻松休闲" },
  stretch:      { label: "舒展",   category: "action",   hint: "运动 / 起床" },
  yawn:         { label: "打呵欠", category: "emotion",  hint: "困倦 / 过渡" },
  cheer:        { label: "欢呼",   category: "emotion",  hint: "胜利 / 庆祝" },
  sad:          { label: "沮丧",   category: "emotion",  hint: "低头 / 坐地" },
  surprised:    { label: "惊讶",   category: "emotion",  hint: "突然发现" },
  punch:        { label: "出拳",   category: "action",   hint: "打斗动作" },
  block:        { label: "格挡",   category: "action",   hint: "防御姿态" },
  throw:        { label: "投掷",   category: "action",   hint: "扔出 / 抛投" },
  crouch:       { label: "下蹲",   category: "action",   hint: "躲藏 / 蓄力" },
  step_turn:    { label: "转身",   category: "action",   hint: "换向 / 走位" },
  tpose:        { label: "T 字",   category: "static",   hint: "开发期 / 校准用" },
  walk:         { label: "行走",   category: "action",   hint: "动态行走" },
  kneel:        { label: "跪地",   category: "emotion",  hint: "投降 / 哀求" },
};

// ── 元数据查询 ──────────────────────────────────────────────

export function getPoseMeta(poseId: string): { label: string; category: PoseCategory; hint: string } | null {
  return POSE_META[poseId] || null;
}

export function listAllPoseIds(): string[] {
  return Object.keys(POSE_META);
}

export function listPosesByCategory(category: PoseCategory): string[] {
  return Object.entries(POSE_META)
    .filter(([, m]) => m.category === category)
    .map(([id]) => id);
}

export function getAllCategories(): PoseCategory[] {
  return ["static", "action", "weapon", "extreme", "emotion"];
}

// ── 缩略图缓存（按 poseId + character 维度 LRU） ─────────────

export type ThumbnailEntry = {
  url: string;
  generatedAt: number;
  hits: number;
};

const _DEFAULT_MAX = 64;

export class PoseThumbnailCache {
  private map: Map<string, ThumbnailEntry> = new Map();
  private maxEntries: number;

  constructor(maxEntries: number = _DEFAULT_MAX) {
    this.maxEntries = Math.max(1, maxEntries);
  }

  private _key(poseId: string, characterId?: string): string {
    return `${poseId}@${characterId || "_default"}`;
  }

  /** 取缩略图（命中 + 1，未命中返回 null） */
  get(poseId: string, characterId?: string): ThumbnailEntry | null {
    const key = this._key(poseId, characterId);
    const e = this.map.get(key);
    if (!e) return null;
    e.hits += 1;
    // LRU: 移到末尾（最近访问）
    this.map.delete(key);
    this.map.set(key, e);
    return e;
  }

  /** 写入缩略图（超出容量裁旧） */
  set(poseId: string, url: string, characterId?: string): ThumbnailEntry {
    const entry: ThumbnailEntry = { url, generatedAt: Date.now(), hits: 0 };
    const key = this._key(poseId, characterId);
    if (this.map.has(key)) this.map.delete(key);
    this.map.set(key, entry);
    while (this.map.size > this.maxEntries) {
      const firstKey = this.map.keys().next().value;
      if (firstKey === undefined) break;
      this.map.delete(firstKey);
    }
    return entry;
  }

  /** 清空 */
  clear(): void {
    this.map.clear();
  }

  size(): number {
    return this.map.size;
  }

  stats(): { size: number; maxEntries: number; topHits: Array<{ key: string; hits: number }> } {
    const entries = Array.from(this.map.entries());
    const topHits = entries
      .map(([k, e]) => ({ key: k, hits: e.hits }))
      .sort((a, b) => b.hits - a.hits)
      .slice(0, 5);
    return { size: this.size(), maxEntries: this.maxEntries, topHits };
  }
}

// 模块级单例（默认容量 64，可被实例替换以做测试）
let _singleton: PoseThumbnailCache = new PoseThumbnailCache();
export function getPoseThumbnailCache(): PoseThumbnailCache {
  return _singleton;
}
export function setPoseThumbnailCache(cache: PoseThumbnailCache): void {
  _singleton = cache;
}
