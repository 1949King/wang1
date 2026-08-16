/**
 * 节点工厂 + 连线工具层。
 * — 纯函数/常量，不依赖 Zustand store
 * — store.ts 通过 import 引入，并 re-export 给外部保持路径兼容
 */
import type { Edge, Node } from "@xyflow/react";
import { MarkerType } from "@xyflow/react";
import { uid } from "./project-storage";

/** 节点类型数据定义（从 store.ts 迁入，保持原 export 不变） */

export type StackVideo = { id: string; url: string; posterUrl?: string; label?: string; createdAt?: string };
export type StackImage = { id: string; url: string; createdAt?: string; label?: string };

/** 连线类型 — 由 source/target 节点 kind 自动推断 */
export type EdgeType = "prompt" | "image" | "video" | "audio" | "data";

/** 节点执行状态 — DAG 执行器运行时填充 */
export type NodeStatus = "idle" | "generating" | "success" | "failed";

/**
 * 角色库条目（对接 Python CharacterStore）
 * — 字段与 Python CHARACTER_FIELD_SCHEMA 对齐
 * — 前端只缓存一份列表，增删改通过 /host/characters 端点同步
 */
export type CharacterEntry = {
  id: string;
  name: string;
  gender?: "男" | "女" | "其他" | string;
  age_range?: string;
  role_type?: "主角" | "配角" | "反派" | "路人" | string;
  tags?: string[];
  appearance?: string;
  personality?: string;
  representative_line?: string;
  background?: string;
  notes?: string;
  media_dir?: string;            // 角色参考图目录（Python 端填充）
  avatar_url?: string;           // 画布侧可显示的头像 URL
  created_at?: string;
  updated_at?: string;
};

/** 运镜类型枚举 */
export type MovementType =
  | "push-in"
  | "pull-out"
  | "pan-left"
  | "pan-right"
  | "tilt-up"
  | "tilt-down"
  | "dolly"
  | "crane"
  | "static";

/** 机型预设 */
export type CameraPreset = "arri-alexa" | "red-komodo" | "sony-cinealta" | "iphone";

/** 通用生成参数块（shot/image/video/audio 共用） */
export type GenParams = {
  seed?: number;
  cfg?: number;
  steps?: number;
};

/** 通用状态块（各节点 kind 共用） */
export type StatusBlock = {
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

export type ShotData = {
  kind: "shot";
  title: string;
  shotSize: string;
  duration: number;
  dialogue: string;
  prompt: string;
  imageUrl?: string;
  images?: StackImage[];
  primaryImageId?: string;
  /** 即梦式首尾帧 */
  firstFrameUrl?: string;
  lastFrameUrl?: string;
  /** 参考视频片段（构图/运镜/节奏） */
  refVideoUrl?: string;
  refVideoName?: string;
  // === 镜头语言（子项目1 新增）===
  movement?: MovementType;
  focalLength?: number;          // 焦段 mm：18/35/50/85/200
  aperture?: number;             // 光圈 f/：1.4/2.8/4/8
  cameraPreset?: CameraPreset;
  /** 水平环绕角度（度）：-180~180，0=正面 */
  cameraYaw?: number;
  /** 俯仰角度（度）：负=俯拍，正=仰拍 */
  cameraPitch?: number;
  // === 生成控制 ===
  seed?: number;
  cfg?: number;
  steps?: number;
  // === 执行状态 ===
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
  // === 角色绑定（对接 CharacterStore）===
  characterId?: string;           // 绑定的角色库 ID（空=未绑定）
  characterName?: string;         // 角色名（绑定后自动同步）
  characterAppearance?: string;    // 外貌特征（绑定后自动同步到 prompt 前缀）
  // === 剪辑 & 补帧（对接 EventBus 双向同步）===
  editorStatus?: "not_sent" | "sent" | "in_timeline" | "trimmed" | "deleted";
  editorRange?: string;           // 入轨时间范围 "00:12-00:15"
  // 补帧参数（用户在 Inspector 里配置）
  interpolationEnabled?: boolean;    // 是否在"发送到剪辑"时自动补帧
  interpolationMode?: "disabled" | "auto" | "always" | "smart";
  interpolationTargetFps?: 24 | 30 | 60;
  interpolationPreviewRange?: string; // 预览时的帧范围 "start-end"（可选）
  // 补帧执行状态（后端回写）
  interpolationStatus?: "none" | "queued" | "running" | "done" | "failed";
  interpolationFrames?: number;    // 补帧完成后新增帧数
};

export type ScriptData = {
  kind: "script";
  title: string;
  content: string;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

export type ImageData = {
  kind: "image";
  title: string;
  prompt: string;
  imageUrl?: string;
  images?: StackImage[];
  primaryImageId?: string;
  refVideoUrl?: string;
  refVideoName?: string;
  // === 生成控制 ===
  seed?: number;
  cfg?: number;
  steps?: number;
  // === 执行状态 ===
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
  // === 剪辑 & 补帧（与 ShotData 对齐）===
  editorStatus?: "not_sent" | "sent" | "in_timeline" | "trimmed" | "deleted";
  editorRange?: string;
  interpolationEnabled?: boolean;
  interpolationMode?: "disabled" | "auto" | "always" | "smart";
  interpolationTargetFps?: 24 | 30 | 60;
  interpolationPreviewRange?: string;
  interpolationStatus?: "none" | "queued" | "running" | "done" | "failed";
  interpolationFrames?: number;
};

export type VideoData = {
  kind: "video";
  title: string;
  prompt: string;
  posterUrl?: string;
  videoUrl?: string;
  videos?: StackVideo[];
  primaryVideoId?: string;
  duration?: number;
  firstFrameUrl?: string;
  lastFrameUrl?: string;
  /** true = 本地上传的参考片段，非云端生成结果 */
  isReference?: boolean;
  refVideoUrl?: string;
  refVideoName?: string;
  // === 视频生成控制 ===
  motionStrength?: number;      // 运动幅度 0-100
  consistency?: number;         // 风格一致性 0-100
  firstFrameWeight?: number;   // 首帧权重 0-1
  lastFrameWeight?: number;    // 尾帧权重 0-1
  seed?: number;
  // === 执行状态 ===
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
  // === 剪辑 & 补帧 ===
  editorStatus?: "not_sent" | "sent" | "in_timeline" | "trimmed" | "deleted";
  editorRange?: string;
  interpolationEnabled?: boolean;
  interpolationMode?: "disabled" | "auto" | "always" | "smart";
  interpolationTargetFps?: 24 | 30 | 60;
  interpolationPreviewRange?: string;
  interpolationStatus?: "none" | "queued" | "running" | "done" | "failed";
  interpolationFrames?: number;
};

export type AudioData = {
  kind: "audio";
  title: string;
  prompt: string;
  audioUrl?: string;
  duration?: number;
  seed?: number;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

export type MusicData = {
  kind: "music";
  title: string;
  prompt: string;
  style?: string;
  lyrics?: string;
  trackTitle?: string;
  instrumental?: boolean;
  audioUrl?: string;
  duration?: number;
  model?: string;
  channel_id?: string;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

export type PromptData = {
  kind: "prompt";
  title: string;
  text: string;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

/** infinite-canvas 对齐：Text 节点（content 字段） */
export type TextData = {
  kind: "text";
  title: string;
  content: string;
  fontSize?: number;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

/** infinite-canvas 对齐：Config 生成配置节点 */
export type ConfigData = {
  kind: "config";
  title: string;
  content?: string;
  generationMode: "image" | "video" | "audio" | "text";
  model?: string;
  size?: string;
  count?: number;
  prompt?: string;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

export type GeneratorData = {
  kind: "generator";
  title: string;
  mode: "image" | "video" | "audio" | "text";
  prompt: string;
  count: number;
  // === DAG 汇聚控制（子项目1 新增）===
  autoCollectUpstream?: boolean;   // 被生成时自动拉取上游 prompt/image/video
  outputKind?: "image" | "video";  // 决定汇聚后产出节点类型
  seed?: number;
  cfg?: number;
  // === 执行状态 ===
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
};

export type GroupData = {
  kind: "group";
  title: string;
};

/** AI-Canvas-tauri 对齐：Markdown 文档节点 */
export type MarkdownData = {
  kind: "markdown";
  title: string;
  content: string;
  preview?: boolean;
};

/** 分镜表一行（画面绑定画布上的 image/video 节点） */
export type ShotlistRow = {
  id: string;
  shotNo: string;
  shotSize: string;
  camera: string;
  content: string;
  dialogue: string;
  duration: number;
  note: string;
  frameNodeId?: string;
  frameKind?: "image" | "video";
  frameUrl?: string;
};

/** AI-Canvas-tauri 对齐：可编辑分镜表 */
export type ShotlistData = {
  kind: "shotlist";
  title: string;
  rows: ShotlistRow[];
};

/** 宫格分镜单格覆盖 */
export type StoryboardCell = {
  overrideUrl?: string;
  label?: string;
};

/** AI-Canvas-tauri 对齐：交互宫格分镜（非一次性拆镜） */
export type StoryboardData = {
  kind: "storyboard";
  title: string;
  cols: 2 | 3 | 4 | 5;
  rows: 2 | 3 | 4 | 5;
  sourceUrl?: string;
  cells: StoryboardCell[];
  prompt?: string;
};

/** 3D 导演台节点：打开内嵌 Stage3D，截图回写本节点 */
export type DirectorData = {
  kind: "director";
  title: string;
  imageUrl?: string;
  captureUrls?: string[];
  status?: NodeStatus;
  lastCameraName?: string;
  prompt?: string;
};

export type AnimationAction = "idle" | "walk" | "run" | "jump" | "attack" | "hit";

/** 逐帧 / Sprite Sheet 动画节点 */
export type AnimationData = {
  kind: "animation";
  title: string;
  prompt: string;
  action: AnimationAction;
  frames: 6 | 8 | 12 | 16;
  sheetUrl?: string;
  previewMode: "sheet" | "playing";
  fps: number;
  status?: NodeStatus;
  errorMessage?: string;
};

/** 360° 全景（等距柱状图） */
export type PanoramaData = {
  kind: "panorama";
  title: string;
  imageUrl?: string;
  yaw: number;
  pitch: number;
  prompt?: string;
  status?: NodeStatus;
};

/** 画布笔记（形状 / 文字 / 箭头） */
export type NoteData = {
  kind: "note";
  title: string;
  noteType: "text" | "rect" | "ellipse" | "arrow";
  content: string;
  color: string;
  strokeWidth?: number;
};

/** 源文件节点：本地素材进流水线 */
export type SourceData = {
  kind: "source";
  title: string;
  mediaType: "image" | "video" | "audio" | "text";
  fileName?: string;
  imageUrl?: string;
  videoUrl?: string;
  audioUrl?: string;
  content?: string;
  prompt?: string;
};

export type NodeData =
  | ShotData
  | ScriptData
  | ImageData
  | VideoData
  | PromptData
  | TextData
  | ConfigData
  | GeneratorData
  | GroupData
  | AudioData
  | MusicData
  | MarkdownData
  | ShotlistData
  | StoryboardData
  | DirectorData
  | AnimationData
  | PanoramaData
  | NoteData
  | SourceData;

export const ANIMATION_ACTION_LABELS: Record<AnimationAction, string> = {
  idle: "待机",
  walk: "行走",
  run: "奔跑",
  jump: "跳跃",
  attack: "攻击",
  hit: "受击",
};

export function animationGrid(frames: number): { cols: number; rows: number } {
  if (frames <= 6) return { cols: 3, rows: 2 };
  if (frames <= 8) return { cols: 4, rows: 2 };
  if (frames <= 12) return { cols: 4, rows: 3 };
  return { cols: 4, rows: 4 };
}

export function createShotlistRow(index = 1): ShotlistRow {
  return {
    id: `row_${Math.random().toString(36).slice(2, 9)}`,
    shotNo: String(index).padStart(2, "0"),
    shotSize: "中景",
    camera: "固定",
    content: "",
    dialogue: "",
    duration: 3,
    note: "",
  };
}

export function defaultStoryboardCells(cols: number, rows: number): StoryboardCell[] {
  return Array.from({ length: cols * rows }, () => ({}));
}

/** ========== 连线推断 ========== */

/**
 * 根据 source/target 节点 kind 推断连线类型
 * - script/prompt → shot/image → prompt 流
 * - shot/image → shot/generator → image 流
 * - video → shot/generator → video 流
 * - audio → generator → audio 流
 * - 其他 → data 流
 */
export function inferEdgeType(
  sourceKind: NodeData["kind"],
  targetKind: NodeData["kind"],
): EdgeType {
  const PROMPT_KINDS = new Set<NodeData["kind"]>(["script", "prompt", "text", "config", "markdown", "note"]);
  const IMAGE_PRODUCERS = new Set<NodeData["kind"]>(["shot", "image", "director", "animation", "panorama", "source"]);
  const VIDEO_PRODUCERS = new Set<NodeData["kind"]>(["video"]);
  const AUDIO_PRODUCERS = new Set<NodeData["kind"]>(["audio"]);

  if (PROMPT_KINDS.has(sourceKind)) return "prompt";
  if (IMAGE_PRODUCERS.has(sourceKind)) return "image";
  if (VIDEO_PRODUCERS.has(sourceKind)) return "video";
  if (AUDIO_PRODUCERS.has(sourceKind)) return "audio";

  // target 是 generator 时，也可以反向推断上游类型
  if (targetKind === "generator") {
    if (IMAGE_PRODUCERS.has(sourceKind)) return "image";
    if (VIDEO_PRODUCERS.has(sourceKind)) return "video";
    if (PROMPT_KINDS.has(sourceKind)) return "prompt";
  }
  return "data";
}

/** 连线类型 → 视觉样式映射 */
const EDGE_STYLE_BY_TYPE: Record<EdgeType, { stroke: string; dash?: string }> = {
  prompt: { stroke: "#a78bfa", dash: "6 4" },          // 紫色虚线 — 提示词流
  image: { stroke: "#64748b" },                        // 灰色实线 — 图片流
  video: { stroke: "#22d3ee" },                        // 青色实线 — 视频流
  audio: { stroke: "#a855f7" },                        // 紫色实线 — 音频流
  data: { stroke: "#94a3b8", dash: "4 3" },           // 浅灰虚线 — 数据流
};

/**
 * 根据 source/target 节点 kind 构建带类型的连线默认选项。
 * type 字段会写入 edge.data.type，供前端渲染（styles.css）区分样式。
 */
export function buildEdgeOptions(
  sourceKind: NodeData["kind"],
  targetKind: NodeData["kind"],
) {
  const type = inferEdgeType(sourceKind, targetKind);
  const style = EDGE_STYLE_BY_TYPE[type];
  return {
    animated: type === "prompt",
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    style: {
      stroke: style.stroke,
      strokeWidth: type === "video" ? 2.2 : 1.6,
      strokeDasharray: style.dash,
    } as Record<string, unknown>,
    data: { type } as Record<string, unknown>,
  };
}

/** 旧默认值保留作 fallback（无 source/target kind 信息时） */
export const defaultEdgeOptions = {
  animated: true,
  markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
  style: { stroke: "#64748b" },
};

/** ========== 节点工厂 ========== */

export function makeNode(
  type: NodeData["kind"],
  position: { x: number; y: number },
  extra?: Partial<NodeData>,
): Node {
  const id = uid(type);
  const base: Record<string, NodeData> = {
    shot: {
      kind: "shot",
      title: "镜头",
      shotSize: "中景",
      duration: 3,
      dialogue: "",
      prompt: "电影感，竖屏漫剧分镜",
      ...extra,
    } as ShotData,
    script: {
      kind: "script",
      title: "剧本",
      content: "第一场：主角登场……",
      ...extra,
    } as ScriptData,
    image: {
      kind: "image",
      title: "图片",
      prompt: "",
      ...extra,
    } as ImageData,
    video: {
      kind: "video",
      title: "视频",
      prompt: "",
      duration: 5,
      ...extra,
    } as VideoData,
    prompt: {
      kind: "prompt",
      title: "提示词",
      text: "风格：赛博朋克，高对比",
      ...extra,
    } as PromptData,
    text: {
      kind: "text",
      title: "文本",
      content: "可复用提示词 / 说明",
      fontSize: 14,
      ...extra,
    } as TextData,
    config: {
      kind: "config",
      title: "生成配置",
      content: "",
      generationMode: "image",
      count: 1,
      prompt: "",
      ...extra,
    } as ConfigData,
    generator: {
      kind: "generator",
      title: "生成器",
      mode: "image",
      prompt: "",
      count: 1,
      ...extra,
    } as GeneratorData,
    group: {
      kind: "group",
      title: "编组",
      ...extra,
    } as GroupData,
    audio: {
      kind: "audio",
      title: "音频",
      prompt: "",
      ...extra,
    } as AudioData,
    music: {
      kind: "music",
      title: "音乐",
      prompt: "",
      ...extra,
    } as MusicData,
    markdown: {
      kind: "markdown",
      title: "Markdown",
      content: "# 分镜说明\n\n- 开场\n- 冲突\n- 收束\n",
      preview: false,
      ...extra,
    } as MarkdownData,
    shotlist: {
      kind: "shotlist",
      title: "分镜表",
      rows: [createShotlistRow(1), createShotlistRow(2), createShotlistRow(3)],
      ...extra,
    } as ShotlistData,
    storyboard: {
      kind: "storyboard",
      title: "宫格分镜",
      cols: 3,
      rows: 3,
      cells: defaultStoryboardCells(3, 3),
      prompt: "",
      ...extra,
    } as StoryboardData,
    director: {
      kind: "director",
      title: "3D 导演台",
      captureUrls: [],
      prompt: "",
      ...extra,
    } as DirectorData,
    animation: {
      kind: "animation",
      title: "逐帧动画",
      prompt: "角色侧视图，白色背景，清晰轮廓",
      action: "walk",
      frames: 8,
      previewMode: "sheet",
      fps: 8,
      ...extra,
    } as AnimationData,
    panorama: {
      kind: "panorama",
      title: "全景",
      yaw: 0,
      pitch: 0,
      prompt: "",
      ...extra,
    } as PanoramaData,
    note: {
      kind: "note",
      title: "画布笔记",
      noteType: "text",
      content: "在此标注镜头意图…",
      color: "#fbbf24",
      strokeWidth: 2,
      ...extra,
    } as NoteData,
    source: {
      kind: "source",
      title: "源文件",
      mediaType: "image",
      prompt: "",
      ...extra,
    } as SourceData,
  };
  const node: Node = {
    id,
    type,
    position,
    data: base[type],
  };
  if (type === "group") {
    node.style = { width: 420, height: 280, zIndex: -1 };
  }
  if (type === "shotlist") {
    node.style = { width: 720, height: 360 };
  }
  if (type === "storyboard") {
    node.style = { width: 420, height: 360 };
  }
  if (type === "markdown") {
    node.style = { width: 360, height: 280 };
  }
  if (type === "director") {
    node.style = { width: 320, height: 280 };
  }
  if (type === "animation") {
    node.style = { width: 340, height: 300 };
  }
  if (type === "panorama") {
    node.style = { width: 360, height: 260 };
  }
  if (type === "note") {
    node.style = { width: 240, height: 160 };
  }
  if (type === "source") {
    node.style = { width: 300, height: 220 };
  }
  return node;
}

export const BUILTIN_NODE_KINDS = new Set<NodeData["kind"]>([
  "shot",
  "script",
  "image",
  "video",
  "prompt",
  "text",
  "config",
  "generator",
  "group",
  "audio",
  "music",
  "markdown",
  "shotlist",
  "storyboard",
  "director",
  "animation",
  "panorama",
  "note",
  "source",
]);

/** ========== Stack 工具 ========== */

export function pushStackImage(
  data: ShotData | ImageData,
  imageUrl: string,
  label?: string,
): ShotData | ImageData {
  const id = `img_${Math.random().toString(36).slice(2, 9)}`;
  const images = [...(data.images || [])];
  if (data.imageUrl && !images.some((x) => x.url === data.imageUrl)) {
    images.push({
      id: data.primaryImageId || `img_prev_${Math.random().toString(36).slice(2, 6)}`,
      url: data.imageUrl,
    });
  }
  images.push({ id, url: imageUrl, createdAt: new Date().toISOString(), label });
  return { ...data, imageUrl, images, primaryImageId: id };
}

export function pushStackVideo(
  data: VideoData,
  videoUrl: string,
  label?: string,
  posterUrl?: string,
): VideoData {
  const id = `vid_${Math.random().toString(36).slice(2, 9)}`;
  const videos = [...(data.videos || [])];
  if (data.videoUrl && !videos.some((x) => x.url === data.videoUrl)) {
    videos.push({
      id: data.primaryVideoId || `vid_prev_${Math.random().toString(36).slice(2, 6)}`,
      url: data.videoUrl,
      posterUrl: data.posterUrl,
    });
  }
  videos.push({
    id,
    url: videoUrl,
    posterUrl,
    label,
    createdAt: new Date().toISOString(),
  });
  return {
    ...data,
    videoUrl,
    videos,
    primaryVideoId: id,
    ...(posterUrl ? { posterUrl } : {}),
  };
}
