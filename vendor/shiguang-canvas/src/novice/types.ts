/**
 * 小白模式（磁吸意图画布）类型与规格常量
 *
 * 与《磁吸意图画布》开发规格说明书对齐：
 * - 卡片尺寸 240×200，圆角 4（2026-09-16 用户裁定：贴合四角缺口减半，
 *   对齐 Windows 磁贴观感；规格原值 8），标题栏 40，状态栏 32，内容区最小 120
 * - 参数三层：L1 导演参数（始终可见）/ L2 进阶（折叠）/ L3 专业（L2 底部折叠展开，
 *   2026-09-16 用户裁定：L3 不再完全隐藏，按字段存在性渲染）
 * - 意图胶囊三层：表面层 / 语义层 / 实现层
 * - 交互分级（2026-09-16 用户裁定）：单击选中 = 卡片内直接输入主文本；
 *   双击 = 右侧面板展开 L2 进阶设置（精细编辑）
 *
 * 数据模型与专业模式完全共用（同一份 nodes/edges），
 * 本模块只负责「换一张脸」——把节点渲染成矩形磁吸卡片，并对参数做降维呈现。
 */

/** 画布档位 */
export type CanvasTier = "novice" | "pro";

/** 档位持久化 key */
export const TIER_STORAGE_KEY = "shiguang-canvas:tier:v1";

/** 卡片几何规格（对齐 spec 4.1；圆角 2026-09-18 由 4 改 16——用户裁定「1+4 结合」大圆角色块，对齐商用磁贴观感） */
export const CARD_GEOMETRY = {
  width: 240,
  /**
   * 固定高度（2026-09-23 用户裁定「卡片大小不统一」修复）：
   * 原为 `minHeight: 200` —— 内容（缩略图 + 提示 + 正文 + 元信息）会把卡片撑到
   * 300px 上下，导致画布上卡片高矮不一，且**违反冻结不变量「卡片实尺寸必须
   * 240×200（磁吸落位基准）」**。改为 fixed height：DOM 实尺寸恒 240×200。
   * 内容超出由 `.nv-card-body` 的 overflow:hidden + 缩略图弹性收缩承担。
   */
  height: 200,
  radius: 16,
  headerHeight: 40,
  minBodyHeight: 120,
  footerHeight: 32,
} as const;

/** 意图胶囊三层（对齐 spec 1.2 / 2 术语表） */
export type IntentLayer = "surface" | "semantic" | "implementation";

export const INTENT_LAYERS: { id: IntentLayer; label: string; hint: string }[] = [
  { id: "surface", label: "表面层", hint: "你看到的：标题、缩略图、状态" },
  { id: "semantic", label: "语义层", hint: "你的意图：提示词、时长、画质、运动幅度" },
  { id: "implementation", label: "实现层", hint: "系统的事：模型、采样器、步数、ControlNet" },
];

/**
 * 特定节点的意图胶囊语义层文案（覆盖 INTENT_LAYERS 的通用 hint）。
 * 让「这张卡片的里面」对不同节点说不同的话，胶囊生态更贴节点本质。
 */
const INTENT_HINT_OVERRIDE: Record<string, Partial<Record<IntentLayer, string>>> = {
  director: {
    surface: "你看到的：导演台主图、最近机位、历史截图缩略图",
    semantic: "你的意图：摆好角色姿势、定机位，截图回写成一张可用的镜头卡",
    implementation: "系统的事：Stage3D 场景、控制网、截图回写链路",
  },
  directorCard: {
    semantic: "你的意图：写一段剧情，自动拆成角色 / 场景 / 分镜序列",
    implementation: "系统的事：宿主 LLM 拉片，产出下游分镜卡片",
  },
};

/** 取节点在某意图层的提示文案（有覆盖用覆盖，否则用通用） */
export function intentHintFor(kind: string, layer: IntentLayer): string {
  const over = INTENT_HINT_OVERRIDE[kind]?.[layer];
  if (over) return over;
  return INTENT_LAYERS.find((l) => l.id === layer)?.hint || "";
}

/** 画质档位（对齐 spec 7.5，与节点已有 qualityTier 字段取值一致） */
export type QualityTier = "draft" | "standard" | "fine" | "cinema";

export const QUALITY_TIERS: { id: QualityTier; label: string; desc: string }[] = [
  { id: "draft", label: "草稿", desc: "5-10 秒出效果" },
  { id: "standard", label: "标准", desc: "720p-1080p" },
  { id: "fine", label: "精修", desc: "细节优先" },
  { id: "cinema", label: "电影级", desc: "1080p-4K" },
];

/** 运动幅度（对齐 spec 7.2，落 motionStrength 0-100） */
export type MotionLevel = "low" | "medium" | "high";

export const MOTION_LEVELS: { id: MotionLevel; label: string; value: number }[] = [
  { id: "low", label: "小", value: 20 },
  { id: "medium", label: "中", value: 55 },
  { id: "high", label: "大", value: 90 },
];

/** 镜头运动（L2，对齐 spec 7.3 七选一，复用节点已有 movement 字段） */
export const CAMERA_MOTIONS: { id: string; label: string }[] = [
  { id: "static", label: "固定" },
  { id: "push", label: "推" },
  { id: "pull", label: "拉" },
  { id: "follow", label: "跟随" },
  { id: "pan", label: "摇移" },
  { id: "handheld", label: "手持" },
  { id: "crane", label: "升降" },
];

/** 画质档位 → 后台参数联动（对齐 spec 7.5 表格） */
export const QUALITY_PRESET: Record<
  QualityTier,
  { steps: number; upscale: boolean; faceRestore: boolean; frameInterpolate: boolean }
> = {
  draft: { steps: 12, upscale: false, faceRestore: false, frameInterpolate: false },
  standard: { steps: 22, upscale: false, faceRestore: true, frameInterpolate: false },
  fine: { steps: 30, upscale: true, faceRestore: true, frameInterpolate: true },
  cinema: { steps: 45, upscale: true, faceRestore: true, frameInterpolate: true },
};

/** 节点类型 → 卡片主色 + 图标（对齐 spec 4.5「颜色代表类型」） */
export const KIND_STYLE: Record<string, { color: string; icon: string; label: string }> = {
  script: { color: "#fbbf24", icon: "📖", label: "剧本" },
  directorCard: { color: "#c084fc", icon: "🎬", label: "导演卡" },
  director: { color: "#c084fc", icon: "🎬", label: "导演台" },
  shot: { color: "#4ade80", icon: "🎥", label: "镜头" },
  image: { color: "#38bdf8", icon: "🖼", label: "图片" },
  video: { color: "#f472b6", icon: "▶", label: "视频" },
  audio: { color: "#22d3ee", icon: "♪", label: "音频" },
  music: { color: "#22d3ee", icon: "♫", label: "音乐" },
  prompt: { color: "#a3a3a3", icon: "☰", label: "提示词" },
  text: { color: "#a3a3a3", icon: "≡", label: "文本" },
  digitalHuman: { color: "#fb923c", icon: "🧑", label: "数字人" },
  storyboard: { color: "#818cf8", icon: "▦", label: "分镜板" },
  shotlist: { color: "#818cf8", icon: "☰", label: "镜头表" },
  group: { color: "#64748b", icon: "▢", label: "分组" },
  note: { color: "#94a3b8", icon: "✎", label: "便签" },
  config: { color: "#94a3b8", icon: "⚙", label: "配置" },
  source: { color: "#94a3b8", icon: "⬇", label: "素材" },
  generator: { color: "#f59e0b", icon: "⚡", label: "生成器" },
  markdown: { color: "#a3a3a3", icon: "M↓", label: "文档" },
  animation: { color: "#fb7185", icon: "🎞", label: "动画" },
  panorama: { color: "#34d399", icon: "🌐", label: "全景" },
};

/** 取节点对应的卡面样式（未知类型给中性灰） */
export function kindStyle(kind: string): { color: string; icon: string; label: string } {
  return KIND_STYLE[kind] || { color: "#64748b", icon: "▢", label: kind || "节点" };
}

/**
 * 各类型卡片的主文本字段（2026-09-16 交互升级）。
 *
 * 单击选中卡片后，内容区原位变成输入框，直接编辑该类型的「主文本」：
 * 字段全部来自 stores/node-factory.ts 的真实数据模型（共用同一份 node.data，
 * 切到专业模式原样可见），不引入小白专属字段。
 */
export const KIND_TEXT_FIELD: Record<string, { field: string; placeholder: string; rows: number }> = {
  script: { field: "content", placeholder: "写剧本大纲，会自动拆成分镜镜头…", rows: 6 },
  directorCard: { field: "script", placeholder: "输入一段剧情，自动拆解角色/场景/分镜…", rows: 6 },
  shot: { field: "prompt", placeholder: "用大白话描述这一镜的画面…", rows: 4 },
  image: { field: "prompt", placeholder: "描述想要的画面…", rows: 4 },
  video: { field: "prompt", placeholder: "描述想要的视频画面…", rows: 4 },
  audio: { field: "prompt", placeholder: "写台词或声音风格…", rows: 4 },
  music: { field: "prompt", placeholder: "描述音乐的风格和情绪…", rows: 4 },
  generator: { field: "prompt", placeholder: "写要生成的内容，会同时产出多张候选…", rows: 4 },
  animation: { field: "prompt", placeholder: "写角色和动作，生成逐帧动画…", rows: 4 },
  panorama: { field: "prompt", placeholder: "描述 360° 全景场景…", rows: 4 },
  digitalHuman: { field: "line", placeholder: "写角色要说的台词…", rows: 4 },
  markdown: { field: "content", placeholder: "写策划案、分镜说明、台词本…", rows: 6 },
  text: { field: "content", placeholder: "随手记录…", rows: 5 },
  prompt: { field: "text", placeholder: "写提示词…", rows: 5 },
  note: { field: "content", placeholder: "写便签内容…", rows: 4 },
};

/** 取卡片主文本字段定义（没有可输入主文本的类型返回 null） */
export function textFieldFor(kind: string): { field: string; placeholder: string; rows: number } | null {
  return KIND_TEXT_FIELD[kind] || null;
}

// ════════════════════════════════════════════════════════════════════════
//  L2 进阶 / L3 专业 参数选项（字段全部来自 node-factory.ts 类型定义，
//  不存在 aspectRatio / styleStrength / negativePrompt —— 那三个字段
//  前后端生成链路均无消费，属假设置，已于 2026-09-16 移除）
// ════════════════════════════════════════════════════════════════════════

/** 景别（ShotData.shotSize；与镜头表默认值「中景」同一体系） */
export const SHOT_SIZES = ["特写", "近景", "中景", "全景", "远景"];

/** 焦段 mm（ShotData.focalLength 注释枚举：18/35/50/85/200） */
export const FOCAL_LENGTHS = [18, 35, 50, 85, 200];

/** 光圈 f/（ShotData.aperture 注释枚举：1.4/2.8/4/8） */
export const APERTURES = [1.4, 2.8, 4, 8];

/** 补帧目标帧率（interpolationTargetFps 枚举） */
export const INTERP_FPS_CHOICES = [24, 30, 60];

/** 小白模式下的操作提示（对齐卡片内的黄色提示条） */
export function noviceHint(kind: string): string {
  switch (kind) {
    case "script":
      return "剧本节点：写剧本大纲 → 按 Enter 自动拆成分镜镜头节点";
    case "directorCard":
      return "导演卡：输入剧本 → 自动拆解角色 / 场景 / 分镜并排好序列";
    case "director":
      return "3D 导演台：点「打开舞台」摆好角色和机位 → 截图自动回写这张卡片";
    case "shot":
    case "image":
    case "video":
      return "镜头节点：填写 Prompt → 点底部「生成选中」开始生图/生视频";
    case "audio":
    case "music":
      return "声音节点：写台词或风格 → 点底部「生成选中」开始配音/配乐";
    case "generator":
      return "生成器：写下要生成的内容 → 会同时产出多张候选，选一张入轨";
    case "markdown":
      return "文档节点：写策划案、分镜说明、台词本，随手记下的东西";
    case "animation":
      return "动画节点：写角色和动作 → 生成逐帧精灵图，可预览循环播放";
    case "panorama":
      return "全景节点：生成 360° 全景图，点中可旋转查看";
    default:
      return "拖到别的卡片旁边就会自动吸附成关系，拉开即解除";
  }
}

/** 卡片在小白模式下的状态灯（对齐 spec CardStatus） */
export type NoviceLamp = "idle" | "running" | "done" | "failed" | "review";

export const LAMP_STYLE: Record<NoviceLamp, { color: string; label: string }> = {
  idle: { color: "#64748b", label: "待执行" },
  running: { color: "#38bdf8", label: "生成中" },
  done: { color: "#4ade80", label: "已完成" },
  failed: { color: "#f87171", label: "失败" },
  review: { color: "#fbbf24", label: "待审阅" },
};

/** 由节点 data.status 推导状态灯 */
export function lampOf(status?: string): NoviceLamp {
  switch (status) {
    case "running":
    case "generating":
    case "queued":
      return "running";
    case "done":
    case "success":
      return "done";
    case "failed":
    case "error":
      return "failed";
    case "pending_review":
    case "review_issues":
      return "review";
    default:
      return "idle";
  }
}
