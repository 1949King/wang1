import { create } from "zustand";
import {
  type Edge,
  type Node,
  type OnEdgesChange,
  type OnNodesChange,
  type OnConnect,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
} from "@xyflow/react";
import { getNodeDefinition } from "./plugins/node-registry";
import { defaultDataForRegistryType } from "./plugins/infinite-compat";
import {
  migrateBundle,
  isProjectBundleLike,
  migrateEdgesForCanvas,
  CURRENT_SCHEMA_VERSION,
} from "./stores/schema-migrations";
import {
  PROJECT_KEY,
  PROJECT_KEY_OLD,
  TEMPLATES_KEY,
  PROJECTS_KEY,
  PROJECT_BUNDLE_PREFIX,
  uid,
  readProjectsIndex,
  writeProjectsIndex,
  readProjectBundle,
  writeProjectBundle,
  deleteProjectBundle,
  filterFlowNodes,
  ensureProjectCanvases,
  pickActiveCanvas,
  patchActiveCanvas,
  readBundleWithActiveCanvas,
  snapshotToBundle,
} from "./stores/project-storage";
import {
  cloneGraph,
  pushGraphHistory,
  popGraphPast,
  popGraphFuture,
  getGraphPast,
  getGraphFuture,
  getClipboard,
  setClipboard,
} from "./stores/history-store";
import type { GraphSnap, ClipboardPayload } from "./stores/history-store";
import {
  type EdgeType,
  type NodeStatus,
  type MovementType,
  type CameraPreset,
  type GenParams,
  type StatusBlock,
  type StackVideo,
  type StackImage,
  type ShotData,
  type ScriptData,
  type ImageData,
  type VideoData,
  type PromptData,
  type TextData,
  type ConfigData,
  type GeneratorData,
  type GroupData,
  type AudioData,
  type MusicData,
  type MarkdownData,
  type ShotlistData,
  type ShotlistRow,
  type StoryboardData,
  type StoryboardCell,
  type DirectorData,
  type AnimationData,
  type AnimationAction,
  type PanoramaData,
  type NoteData,
  type SourceData,
  type NodeData,
  inferEdgeType,
  buildEdgeOptions,
  defaultEdgeOptions,
  makeNode,
  BUILTIN_NODE_KINDS,
  pushStackImage,
  pushStackVideo,
  createShotlistRow,
  defaultStoryboardCells,
  ANIMATION_ACTION_LABELS,
  animationGrid,
  CharacterEntry,
} from "./stores/node-factory";

/** re-export 给外部模块用（保持 import 路径不变） */
export type {
  GraphSnap, ClipboardPayload,
  EdgeType, NodeStatus, MovementType, CameraPreset, GenParams, StatusBlock,
  StackVideo, StackImage,
  ShotData, ScriptData, ImageData, VideoData, PromptData, TextData,
  ConfigData, GeneratorData, GroupData, AudioData, MusicData, NodeData,
  MarkdownData, ShotlistData, ShotlistRow, StoryboardData, StoryboardCell,
  DirectorData, AnimationData, AnimationAction, PanoramaData, NoteData, SourceData,
  CharacterEntry,
};
export {
  cloneGraph, pushGraphHistory, uid, readProjectBundle, writeProjectBundle, deleteProjectBundle,
  inferEdgeType, buildEdgeOptions, makeNode, pushStackImage, pushStackVideo,
  createShotlistRow, defaultStoryboardCells, ANIMATION_ACTION_LABELS, animationGrid,
};

export type StoryboardShot = {
  id?: number;
  duration?: number;
  shot?: string;
  description?: string;
  dialogue?: string;
};

export type ViewMode =
  | "home"
  | "projects"
  | "canvas"
  | "stage3d"
  | "image"
  | "video"
  | "prompts"
  | "assets"
  | "settings";

export type CanvasLayoutMode = "flow" | "simple" | "storyboard";

const VIEW_MODES: ReadonlySet<string> = new Set([
  "home",
  "projects",
  "canvas",
  "stage3d",
  "image",
  "video",
  "prompts",
  "assets",
  "settings",
]);

function normalizeViewMode(m: string): ViewMode {
  return VIEW_MODES.has(m) ? (m as ViewMode) : "home";
}

/** 项目元数据（列表视图用，轻量） */
export type ProjectMeta = {
  id: string;
  name: string;
  savedAt: string;
  /** 节点数，快速预览 */
  nodeCount: number;
  /** 画布项目关联的 3D 导演台快照版本 */
  stage3dSnapshotId?: string;
};

/** 单工作区内的画布快照 */
export type CanvasSnapshot = {
  id: string;
  name: string;
  nodes: Node[];
  edges: Edge[];
  savedAt: string;
};

export type CanvasMeta = {
  id: string;
  name: string;
  nodeCount: number;
  savedAt: string;
};

/** 项目完整 bundle（存 PROJECT_BUNDLE_PREFIX + id） */
export type ProjectBundle = {
  /** 当前 schema 版本号（主字段，由 schema-migrations.ts 维护） */
  schemaVersion?: number;
  /** 向后兼容字段（与 schemaVersion 同值，待存量迁移后逐步废弃） */
  version?: number;
  id: string;
  name: string;
  dramaTitle: string;
  episode: string;
  nodes: Node[];
  edges: Edge[];
  savedAt: string;
  stage3d?: unknown;
  /** 同一工作区多画布（缺省时用顶层 nodes/edges 当作「画布 1」） */
  canvases?: CanvasSnapshot[];
  activeCanvasId?: string;
  /** S6: 项目内用过的 AI provider/model 版本快照（打开时对比系统当前版本弹提醒） */
  aiVersions?: {
    /** provider → model 映射，收集自 config / generator / shot 节点的 data.model 字段 */
    providers: Record<string, string>;
    /** 项目保存时的前端版本号，留空不影响主流程 */
    canvasVersion?: string;
  };
};

/**
 * 旧工程（v1/v2）升级到 v3 连线 schema：
 * — 内部委托 schema-migrations.ts 的 migrateEdgesForCanvas，保持幂等
 * — 所有调用方（openProject / switchCanvas / duplicateCanvas / loadProject / loadProjectBundle）的
 *   签名不变，仅内部实现统一走迁移层
 */
function upgradeSchemaV2toV3(nodes: Node[], edges: Edge[]): Edge[] {
  return migrateEdgesForCanvas(nodes as any, edges as any) as Edge[];
}

// ════════════════════════════════════════════════════════════════════════
// 预装场景模板（BUILTIN_TEMPLATES）— 零学习成本起点
// 节点 id 固定（edges source/target 要引用），不用 makeNode 的随机 uid
// ════════════════════════════════════════════════════════════════════════

type BuiltinTemplate = {
  id: string;                     // "builtin:xxx" 前缀区分
  name: string;
  description: string;            // 一句话说明用途（降学习成本）
  nodes: Node[];
  edges: Edge[];
};

function _edge(src: string, tgt: string, type?: string): Edge {
  return {
    id: `e_${src}_${tgt}`,
    source: src,
    target: tgt,
    type: type || "default",
    animated: false,
    style: { stroke: "#64748b" },
  };
}

export const BUILTIN_TEMPLATES: BuiltinTemplate[] = [
  // ── 模板 1：竖屏短剧 3 场分镜 ──
  {
    id: "builtin:shorts-drama",
    name: "竖屏短剧 · 3 场分镜",
    description: "剧本 → 3 个镜头，一键填写 prompt 开始生图/生视频",
    nodes: [
      {
        id: "s1", type: "script", position: { x: 60, y: 160 },
        data: { kind: "script", title: "剧本 · 第一场", content: "主角推门进入空荡的房间……" } as any,
      },
      {
        id: "sh1", type: "shot", position: { x: 320, y: 60 },
        data: { kind: "shot", title: "镜 01 · 推门", shotSize: "中景", duration: 3, prompt: "竖屏 9:16，电影感推镜，冷色调" } as any,
      },
      {
        id: "sh2", type: "shot", position: { x: 320, y: 200 },
        data: { kind: "shot", title: "镜 02 · 环顾", shotSize: "全景", duration: 4, prompt: "竖屏 9:16，缓慢环视运镜" } as any,
      },
      {
        id: "sh3", type: "shot", position: { x: 320, y: 340 },
        data: { kind: "shot", title: "镜 03 · 特写", shotSize: "特写", duration: 2, prompt: "竖屏 9:16，人物面部特写，暖光" } as any,
      },
      {
        id: "cfg1", type: "config", position: { x: 620, y: 160 },
        data: { kind: "config", title: "生成配置", generationMode: "image", count: 4, prompt: "" } as any,
      },
    ],
    edges: [_edge("s1", "sh1"), _edge("s1", "sh2"), _edge("s1", "sh3"), _edge("sh1", "cfg1"), _edge("sh2", "cfg1"), _edge("sh3", "cfg1")],
  },

  // ── 模板 2：产品展示分镜 ──
  {
    id: "builtin:product-showcase",
    name: "产品展示 · 卖点 3 镜",
    description: "Prompt → 3 个产品角度镜头，突出卖点/质感/使用场景",
    nodes: [
      {
        id: "p1", type: "prompt", position: { x: 60, y: 180 },
        data: { kind: "prompt", title: "风格提示", text: "高端质感，浅景深，棚拍，4K" } as any,
      },
      {
        id: "ps1", type: "shot", position: { x: 320, y: 40 },
        data: { kind: "shot", title: "产品 · 正面特写", shotSize: "特写", duration: 3, prompt: "产品正面，微距，水滴细节" } as any,
      },
      {
        id: "ps2", type: "shot", position: { x: 320, y: 200 },
        data: { kind: "shot", title: "产品 · 侧面", shotSize: "中景", duration: 3, prompt: "产品 45° 侧面，阴影光" } as any,
      },
      {
        id: "ps3", type: "shot", position: { x: 320, y: 360 },
        data: { kind: "shot", title: "产品 · 使用场景", shotSize: "全景", duration: 5, prompt: "模特使用场景，生活化" } as any,
      },
      {
        id: "g1", type: "generator", position: { x: 620, y: 180 },
        data: { kind: "generator", title: "批量生成器", mode: "image", count: 6, prompt: "" } as any,
      },
    ],
    edges: [_edge("p1", "ps1"), _edge("p1", "ps2"), _edge("p1", "ps3"), _edge("ps1", "g1"), _edge("ps2", "g1"), _edge("ps3", "g1")],
  },

  // ── 模板 3：情绪板 / Moodboard ──
  {
    id: "builtin:moodboard",
    name: "情绪板 · 视觉预演",
    description: "4 张参考图 + 说明文字，快速对齐团队视觉调性",
    nodes: [
      {
        id: "gp", type: "group", position: { x: 40, y: 40 },
        data: { kind: "group", title: "情绪板 · 都市夜景" } as any,
        style: { width: 520, height: 380, zIndex: -1 },
      },
      {
        id: "m1", type: "image", position: { x: 70, y: 80 },
        data: { kind: "image", title: "参考 · 霓虹 1", prompt: "赛博朋克霓虹灯" } as any,
      },
      {
        id: "m2", type: "image", position: { x: 270, y: 80 },
        data: { kind: "image", title: "参考 · 霓虹 2", prompt: "雨夜城市街道" } as any,
      },
      {
        id: "m3", type: "image", position: { x: 70, y: 240 },
        data: { kind: "image", title: "参考 · 光影", prompt: "窗格光影投射" } as any,
      },
      {
        id: "m4", type: "image", position: { x: 270, y: 240 },
        data: { kind: "image", title: "参考 · 氛围", prompt: "烟雾 + 蓝光" } as any,
      },
      {
        id: "mt", type: "text", position: { x: 580, y: 160 },
        data: { kind: "text", title: "调性说明", content: "整体冷蓝调 + 霓虹粉点缀，雨夜氛围……", fontSize: 14 } as any,
      },
    ],
    edges: [],
  },

  // ── 模板 4：MV 节奏分镜 ──
  {
    id: "builtin:mv-beatboard",
    name: "MV · 7 拍节奏板",
    description: "7 个紧凑镜头（2-4s），贴合 BGM 节拍的情绪流",
    nodes: [
      {
        id: "mv1", type: "shot", position: { x: 40, y: 80 },
        data: { kind: "shot", title: "Beat 1 · 开场", shotSize: "特写", duration: 2, prompt: "歌手近景特写，聚光" } as any,
      },
      {
        id: "mv2", type: "shot", position: { x: 190, y: 80 },
        data: { kind: "shot", title: "Beat 2 · 转身", shotSize: "中景", duration: 3, prompt: "转身甩头，动感" } as any,
      },
      {
        id: "mv3", type: "shot", position: { x: 340, y: 80 },
        data: { kind: "shot", title: "Beat 3 · 全景", shotSize: "全景", duration: 4, prompt: "舞台全景，观众欢呼" } as any,
      },
      {
        id: "mv4", type: "shot", position: { x: 490, y: 80 },
        data: { kind: "shot", title: "Beat 4 · 乐器", shotSize: "特写", duration: 2, prompt: "吉他手手指特写" } as any,
      },
      {
        id: "mv5", type: "shot", position: { x: 640, y: 80 },
        data: { kind: "shot", title: "Beat 5 · 仰拍", shotSize: "仰拍", duration: 3, prompt: "从舞台向上仰拍歌手" } as any,
      },
      {
        id: "mv6", type: "shot", position: { x: 790, y: 80 },
        data: { kind: "shot", title: "Beat 6 · 甩镜", shotSize: "中景", duration: 3, prompt: "快速甩镜到主唱" } as any,
      },
      {
        id: "mv7", type: "shot", position: { x: 940, y: 80 },
        data: { kind: "shot", title: "Beat 7 · 高潮", shotSize: "特写", duration: 2, prompt: "副歌最高潮表情" } as any,
      },
      {
        id: "mva", type: "audio", position: { x: 490, y: 220 },
        data: { kind: "audio", title: "BGM · 导入音频文件" } as any,
      },
    ],
    edges: [_edge("mv1", "mv2"), _edge("mv2", "mv3"), _edge("mv3", "mv4"), _edge("mv4", "mv5"), _edge("mv5", "mv6"), _edge("mv6", "mv7")],
  },

  // ── 模板 5：AI 生图快速卡 ──
  {
    id: "builtin:quick-image-card",
    name: "快速生图卡",
    description: "配置 → Prompt → Image → Generator，最短路径跑通生图",
    nodes: [
      {
        id: "qc", type: "config", position: { x: 60, y: 180 },
        data: { kind: "config", title: "配置", generationMode: "image", count: 4, prompt: "" } as any,
      },
      {
        id: "qp", type: "prompt", position: { x: 300, y: 180 },
        data: { kind: "prompt", title: "Prompt", text: "一个戴帽子的女孩，站在秋天的枫叶树下" } as any,
      },
      {
        id: "qi", type: "image", position: { x: 540, y: 180 },
        data: { kind: "image", title: "预览图", prompt: "" } as any,
      },
      {
        id: "qg", type: "generator", position: { x: 780, y: 180 },
        data: { kind: "generator", title: "生成器", mode: "image", count: 4, prompt: "" } as any,
      },
    ],
    edges: [_edge("qc", "qp"), _edge("qp", "qi"), _edge("qi", "qg")],
  },
];

// ════════════════════════════════════════════════════════════════════════
// S6 版本锁定：收集项目内用到的 provider/model 快照
// ════════════════════════════════════════════════════════════════════════

/** 从节点列表中收集出现过的 AI model → provider 映射 */
function collectAiVersions(nodes: Node[]): ProjectBundle["aiVersions"] {
  const providers: Record<string, string> = {};
  for (const n of nodes) {
    const d = (n.data || {}) as Record<string, any>;
    const model = d.model as string | undefined;
    const provider = (d.provider || "") as string;
    if (model) {
      providers[provider || "default"] = model;
    }
  }
  if (Object.keys(providers).length === 0) return undefined;
  return { providers };
}

type Store = {
  nodes: Node[];
  edges: Edge[];
  selectedId: string | null;
  status: string;
  dramaTitle: string;
  episode: string;
  viewMode: ViewMode;
  canvasLayoutMode: CanvasLayoutMode;
  /** 脏版本号：任何节点/连线变动 +1，用于触发 auto-save 的 useEffect 依赖 */
  dirtyVersion: number;
  /** 3D 导演台场景快照（saveProject 时打包，loadProject 时恢复） */
  stage3dSnapshot?: unknown;
  /** 从导演台节点打开 Stage3D 时，截图回写到该节点 */
  directorTargetNodeId: string | null;

  // ===== Graph: React Flow 事件 + 基础状态 =====
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setStatus: (s: string) => void;
  setMeta: (dramaTitle: string, episode: string) => void;
  setViewMode: (m: ViewMode) => void;
  setCanvasLayoutMode: (m: CanvasLayoutMode) => void;
  openDirectorForNode: (nodeId: string) => void;
  clearDirectorTarget: () => void;

  // ===== Selection =====
  setSelected: (id: string | null) => void;
  updateSelectedData: (patch: Record<string, unknown>) => void;
  updateNodeData: (id: string, patch: Record<string, unknown>) => void;

  // ===== Node CRUD + Workflow Generators =====
  addNode: (type: NodeData["kind"], pos?: { x: number; y: number }) => void;
  addRegistryNode: (type: string, pos?: { x: number; y: number }) => void;
  addVideoReference: (
    url: string,
    opts?: { title?: string; name?: string; pos?: { x: number; y: number } },
  ) => void;
  addStoryboardGrid: (count?: 9 | 25) => void;
  applyStoryboard: (shots: StoryboardShot[], scriptTitle?: string) => void;
  addThreeView: () => void;
  addVariants: (axis?: "表情" | "服装" | "背景", count?: number) => void;
  addCaptureToCanvas: (
    imageUrl: string,
    title: string,
    shotMeta?: {
      focalLength?: number;
      shotSize?: string;
      aspect?: string;
      aperture?: number;
      cameraPreset?: CameraPreset;
      movement?: MovementType;
    },
  ) => void;
  addStudioNode: (
    kind: "image" | "video" | "prompt",
    data: Record<string, unknown>,
  ) => void;

  // ===== Selection Operations =====
  removeSelected: () => void;
  deleteEdge: (edgeId: string) => void;
  duplicateSelected: () => void;
  copySelected: () => void;
  pasteClipboard: (pos?: { x: number; y: number }) => void;
  selectAll: () => void;
  clearSelection: () => void;
  alignSelected: (mode: "left" | "center" | "top" | "middle" | "distribute-h") => void;
  groupSelected: () => void;

  // ===== History (Undo/Redo) =====
  undoGraph: () => void;
  redoGraph: () => void;
  beginGraphEdit: () => void;

  // ===== Media Stack (setNode 系列) =====
  setNodeImage: (id: string, imageUrl: string, opts?: { replaceStack?: boolean; label?: string }) => void;
  setPrimaryImage: (id: string, imageId: string) => void;
  setNodeVideo: (id: string, videoUrl: string, posterUrl?: string, opts?: { label?: string }) => void;
  setPrimaryVideo: (id: string, videoId: string) => void;
  setNodeAudio: (id: string, audioUrl: string) => void;

  // ===== Project Persistence =====
  saveProject: (opts?: { silent?: boolean }) => void;
  loadProject: () => void;
  loadProjectBundle: (bundle: {
    nodes: Node[];
    edges: Edge[];
    dramaTitle?: string;
    episode?: string;
    stage3d?: unknown;
  }) => void;
  getProjectBundle: () => {
    nodes: Node[];
    edges: Edge[];
    dramaTitle: string;
    episode: string;
    stage3d?: unknown;
  };

  // ===== Multi-Project State =====
  activeProjectId: string | null;
  activeProjectName: string;
  activeCanvasId: string | null;
  activeCanvasName: string;

  // ===== Multi-Project CRUD =====
  listProjects: () => ProjectMeta[];
  ensureWorkspace: () => string;
  createProject: (name: string) => string;
  openProject: (id: string) => void;
  renameProject: (id: string, newName: string) => void;
  deleteProject: (id: string) => void;
  bulkDeleteProjects: (ids: string[]) => void;

  // ===== Multi-Canvas Within Workspace =====
  listCanvases: () => CanvasMeta[];
  createCanvas: (name?: string) => string;
  switchCanvas: (id: string) => void;
  renameCanvas: (id: string, newName: string) => void;
  deleteCanvas: (id: string) => void;
  duplicateCanvas: (id: string) => void;

  // ===== JSON Import / Export =====
  exportProjectJSON: (id?: string) => string | null;
  importProjectJSON: (json: string, opts?: { name?: string; open?: boolean }) => string | null;

  // ===== Template (workflow preset) =====
  listTemplates: () => { id: string; name: string; savedAt: string; builtin?: boolean; description?: string }[];
  saveTemplate: (name: string) => void;
  loadTemplate: (id: string) => void;
  deleteTemplate: (id: string) => void;

  // ===== Character Library（对接 Python CharacterStore）=====
  characters: CharacterEntry[];
  refreshCharacters: () => Promise<void>;                         // GET /host/characters
  bindCharacterToShot: (nodeId: string, characterId: string) => void;
  unbindCharacterFromShot: (nodeId: string) => void;
  syncCharacterToShot: (nodeId: string) => void;                // 手动刷 appearance → prompt 前缀

  // ===== 3D Stage Snapshot Sync =====
  setStage3dSnapshot: (snapshot: unknown) => void;
  getStage3dSnapshot: () => unknown | undefined;
};

export const useCanvasStore = create<Store>((set, get) => ({
  nodes: [
    makeNode("script", { x: 80, y: 120 }),
    makeNode("shot", { x: 400, y: 80 }, { title: "镜 01" } as Partial<ShotData>),
    makeNode("shot", { x: 400, y: 280 }, { title: "镜 02" } as Partial<ShotData>),
  ],
  edges: [],
  selectedId: null,
  status: "拾光导演台就绪 — 可添加分镜节点",
  dramaTitle: "",
  episode: "",
  viewMode: "home",
  canvasLayoutMode: "flow",
  directorTargetNodeId: null,
  activeProjectId: null,
  activeProjectName: "未命名工作区",
  activeCanvasId: null,
  activeCanvasName: "画布 1",
  dirtyVersion: 0,
  onNodesChange: (changes) =>
    set((state) => ({
      nodes: applyNodeChanges(changes, state.nodes),
      dirtyVersion: state.dirtyVersion + 1,
    })),
  onEdgesChange: (changes) =>
    set((state) => ({
      edges: applyEdgeChanges(changes, state.edges),
      dirtyVersion: state.dirtyVersion + 1,
    })),
  onConnect: (connection) => {
    pushGraphHistory(get);
    // 预先建 id→node Map，避免 O(N*M) 查找
    const nodeMap = new Map(get().nodes.map((n) => [n.id, n]));
    const src = nodeMap.get(connection.source);
    const tgt = nodeMap.get(connection.target);
    const srcKind = (src?.data as NodeData | undefined)?.kind;
    const tgtKind = (tgt?.data as NodeData | undefined)?.kind;
    const edgeOpts =
      srcKind && tgtKind
        ? buildEdgeOptions(srcKind, tgtKind)
        : defaultEdgeOptions;
    set((state) => ({
      edges: addEdge({ ...connection, ...edgeOpts }, state.edges),
      status: srcKind && tgtKind
        ? `已连接（${inferEdgeType(srcKind, tgtKind)} 流）`
        : "已连接节点",
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  setStatus: (status) => set({ status }),
  setMeta: (dramaTitle, episode) => set({ dramaTitle, episode }),
  setViewMode: (viewMode) => set({ viewMode: normalizeViewMode(viewMode) }),
  openDirectorForNode: (nodeId) => {
    const n = get().nodes.find((x) => x.id === nodeId);
    const kind = (n?.data as NodeData | undefined)?.kind;
    if (!n || kind !== "director") {
      set({ status: "请从「3D 导演台」节点打开舞台" });
      return;
    }
    set({
      directorTargetNodeId: nodeId,
      selectedId: nodeId,
      viewMode: "stage3d",
      status: `导演台已绑定节点「${(n.data as DirectorData).title || nodeId}」· 截图将回写`,
    });
  },
  clearDirectorTarget: () => set({ directorTargetNodeId: null }),
  setCanvasLayoutMode: (canvasLayoutMode) => set({ canvasLayoutMode }),
  setSelected: (selectedId) => set({ selectedId }),
  updateSelectedData: (patch) => {
    const id = get().selectedId;
    if (!id) return;
    get().updateNodeData(id, patch);
  },
  updateNodeData: (id, patch) => {
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...patch } } : n,
      ),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addNode: (type, pos) => {
    pushGraphHistory(get);
    const position = pos || {
      x: 120 + Math.random() * 320,
      y: 80 + Math.random() * 240,
    };
    const node = makeNode(type, position);
    set((state) => ({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), { ...node, selected: true }],
      selectedId: node.id,
      status: `已添加「${type}」节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addRegistryNode: (type, pos) => {
    pushGraphHistory(get);
    const position = pos || {
      x: 120 + Math.random() * 320,
      y: 80 + Math.random() * 240,
    };
    const def = getNodeDefinition(type);
    if (!def) {
      set({ status: `未知节点类型：${type}` });
      return;
    }
    const id = uid(type.replace(/:/g, "_"));
    const node: Node = {
      id,
      type,
      position,
      data: defaultDataForRegistryType(type),
      selected: true,
      style: def.defaultSize
        ? { width: def.defaultSize.width, height: def.defaultSize.height }
        : undefined,
    };
    if (type === "group") {
      node.style = { ...(node.style || {}), width: 760, height: 480, zIndex: -1 };
    }
    set((state) => ({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), node],
      selectedId: id,
      status: `已添加插件节点「${def.title}」`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addVideoReference: (url, opts) => {
    pushGraphHistory(get);
    const position = opts?.pos || {
      x: 120 + Math.random() * 320,
      y: 80 + Math.random() * 240,
    };
    const title = opts?.title || "参考视频";
    const node = makeNode("video", position, {
      title,
      prompt: "【参考片段】用于运镜/节奏/构图参考，可挂到镜头节点或发给 Agent",
      videoUrl: url,
      isReference: true,
      refVideoUrl: url,
      refVideoName: opts?.name || title,
      duration: 5,
    } as Partial<VideoData>);
    set((state) => ({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), { ...node, selected: true }],
      selectedId: node.id,
      status: `已添加参考视频「${title}」`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addStoryboardGrid: (count = 9) => {
    pushGraphHistory(get);
    const n = count === 25 ? 25 : 9;
    const cols = count === 25 ? 5 : 3;
    const startX = 100;
    const startY = 80;
    const gapX = 220;
    const gapY = 190;
    const nodes: Node[] = [];
    for (let i = 0; i < n; i++) {
      const col = i % cols;
      const row = Math.floor(i / cols);
      nodes.push(
        makeNode(
          "shot",
          { x: startX + col * gapX, y: startY + row * gapY },
          {
            title: `镜 ${String(i + 1).padStart(2, "0")}`,
            prompt: `${n}宫格分镜 ${i + 1}/${n}，竖屏漫剧`,
          } as Partial<ShotData>,
        ),
      );
    }
    set((state) => ({
      nodes: [...state.nodes, ...nodes],
      status: `已添加${n}宫格分镜`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  applyStoryboard: (shots, scriptTitle) => {
    const list = Array.isArray(shots) ? shots : [];
    if (!list.length) {
      set({ status: "拉片结果为空" });
      return;
    }
    pushGraphHistory(get);
    const scriptNode = makeNode(
      "script",
      { x: 40, y: 40 },
      {
        title: scriptTitle || "拉片剧本",
        content: list
          .map(
            (s, i) =>
              `${i + 1}. [${s.shot || "中景"}] ${s.description || ""} ${s.dialogue ? `「${s.dialogue}」` : ""}`,
          )
          .join("\n"),
      } as Partial<ScriptData>,
    );
    const shotNodes: Node[] = [];
    const edges: Edge[] = [];
    const cols = list.length > 12 ? 5 : 3;
    list.forEach((s, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const node = makeNode(
        "shot",
        { x: 320 + col * 230, y: 40 + row * 200 },
        {
          title: `镜 ${String(i + 1).padStart(2, "0")}`,
          shotSize: s.shot || "中景",
          duration: Number(s.duration) || 3,
          dialogue: s.dialogue || "",
          prompt: s.description || `分镜 ${i + 1}`,
        } as Partial<ShotData>,
      );
      shotNodes.push(node);
      edges.push({
        id: uid("e"),
        source: scriptNode.id,
        target: node.id,
        ...defaultEdgeOptions,
      });
    });
    set((state) => ({
      nodes: [scriptNode, ...shotNodes],
      edges,
      selectedId: shotNodes[0]?.id || scriptNode.id,
      status: `拉片完成：${shotNodes.length} 个分镜节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addThreeView: () => {
    pushGraphHistory(get);
    const views = [
      { title: "三视图·正面", prompt: "角色设定三视图正面，全身立绘，干净白底，竖屏漫剧角色设计" },
      { title: "三视图·侧面", prompt: "角色设定三视图侧面，全身立绘，干净白底，竖屏漫剧角色设计" },
      { title: "三视图·背面", prompt: "角色设定三视图背面，全身立绘，干净白底，竖屏漫剧角色设计" },
    ];
    const startX = 120;
    const startY = 100;
    const nodes = views.map((v, i) =>
      makeNode(
        "shot",
        { x: startX + i * 240, y: startY },
        {
          title: v.title,
          shotSize: "全景",
          duration: 1,
          prompt: v.prompt,
        } as Partial<ShotData>,
      ),
    );
    const edges: Edge[] = [];
    for (let i = 0; i < nodes.length - 1; i++) {
      edges.push({
        id: uid("e"),
        source: nodes[i].id,
        target: nodes[i + 1].id,
        ...defaultEdgeOptions,
      });
    }
    set((state) => ({
      nodes: [...state.nodes, ...nodes],
      edges: [...state.edges, ...edges],
      selectedId: nodes[0]?.id || null,
      status: "已添加角色三视图节点（正/侧/背）",
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addVariants: (axis = "表情", count = 3) => {
    const id = get().selectedId;
    const src = get().nodes.find((n) => n.id === id);
    if (!src || (src.data as NodeData).kind !== "shot") {
      set({ status: "请先选中一个镜头节点再生成变体" });
      return;
    }
    pushGraphHistory(get);
    const d = src.data as ShotData;
    const catalog: Record<string, string[]> = {
      表情: ["微笑", "严肃", "惊讶", "悲伤", "愤怒"],
      服装: ["便装", "正装", "校服", "古装", "战甲"],
      背景: ["雨夜街道", "教室窗边", "霓虹天台", "咖啡馆", "海边"],
    };
    const labels = (catalog[axis] || catalog["表情"]).slice(0, Math.max(1, Math.min(count, 5)));
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    labels.forEach((label, i) => {
      const node = makeNode(
        "shot",
        { x: src.position.x + 240, y: src.position.y + i * 180 },
        {
          title: `${d.title || "镜头"}·${label}`,
          shotSize: d.shotSize,
          duration: d.duration,
          dialogue: d.dialogue,
          prompt: `${d.prompt || ""}；变体维度:${axis}=${label}`,
          firstFrameUrl: d.firstFrameUrl || d.imageUrl,
        } as Partial<ShotData>,
      );
      nodes.push(node);
      edges.push({
        id: uid("e"),
        source: src.id,
        target: node.id,
        ...defaultEdgeOptions,
      });
    });
    set((state) => ({
      nodes: [...state.nodes, ...nodes],
      edges: [...state.edges, ...edges],
      selectedId: nodes[0]?.id || id,
      status: `已生成 ${nodes.length} 个「${axis}」变体（可批量生成）`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  removeSelected: () => {
    const sid = get().selectedId;
    const nodeIds = new Set(
      get()
        .nodes.filter((n) => n.selected || n.id === sid)
        .map((n) => n.id),
    );
    const edgeIds = new Set(get().edges.filter((e) => e.selected).map((e) => e.id));
    if (!nodeIds.size && !edgeIds.size) {
      set({ status: "请先点选要删除的节点或连线（Shift 可多选）" });
      return;
    }
    pushGraphHistory(get);
    set((state) => ({
      nodes: state.nodes.filter((n) => !nodeIds.has(n.id)),
      edges: state.edges.filter(
        (e) => !edgeIds.has(e.id) && !nodeIds.has(e.source) && !nodeIds.has(e.target),
      ),
      selectedId: null,
      status:
        nodeIds.size && edgeIds.size
          ? `已删除 ${nodeIds.size} 节点 + ${edgeIds.size} 连线`
          : nodeIds.size
            ? `已删除 ${nodeIds.size} 个节点`
            : `已删除 ${edgeIds.size} 条连线`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  deleteEdge: (edgeId) => {
    if (!get().edges.some((e) => e.id === edgeId)) return;
    pushGraphHistory(get);
    set((state) => ({
      edges: state.edges.filter((e) => e.id !== edgeId),
      status: "已删除连线",
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  duplicateSelected: () => {
    const sid = get().selectedId;
    const selected = get().nodes.filter((n) => n.selected || n.id === sid);
    if (!selected.length) {
      set({ status: "请先选中要复制的节点" });
      return;
    }
    pushGraphHistory(get);
    const idMap = new Map<string, string>();
    const created = selected.map((n) => {
      const data = n.data as NodeData;
      const kind = data.kind as NodeData["kind"];
      let node: Node;
      if (BUILTIN_NODE_KINDS.has(kind)) {
        node = makeNode(kind, { x: n.position.x + 40, y: n.position.y + 40 }, {
          ...data,
          title: "title" in data ? `${data.title || data.kind} 副本` : undefined,
        } as Partial<NodeData>);
      } else {
        const id = uid(String(n.type || kind).replace(/:/g, "_"));
        node = {
          id,
          type: n.type || String(kind),
          position: { x: n.position.x + 40, y: n.position.y + 40 },
          data: {
            ...data,
            title: "title" in data ? `${(data as { title?: string }).title || kind} 副本` : undefined,
          },
          selected: true,
          style: n.style ? { ...n.style } : undefined,
        };
      }
      idMap.set(n.id, node.id);
      return { ...node, selected: true };
    });
    const selSet = new Set(selected.map((n) => n.id));
    const state = get();
    const newEdges = state.edges
      .filter((e) => selSet.has(e.source) && selSet.has(e.target))
      .map((e) => ({
        ...e,
        id: uid("e"),
        source: idMap.get(e.source) || e.source,
        target: idMap.get(e.target) || e.target,
        selected: false,
      }));
    set(() => ({
      nodes: [
        ...state.nodes.map((n) => ({ ...n, selected: false })),
        ...created,
      ],
      edges: [...state.edges, ...newEdges],
      selectedId: created[0]?.id || null,
      status: `已复制 ${created.length} 个节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  copySelected: () => {
    const sid = get().selectedId;
    const selected = get().nodes.filter((n) => n.selected || n.id === sid);
    if (!selected.length) {
      set({ status: "请先选中要复制的节点" });
      return;
    }
    const ids = new Set(selected.map((n) => n.id));
    setClipboard({
      nodes: JSON.parse(JSON.stringify(selected)) as Node[],
      edges: JSON.parse(
        JSON.stringify(get().edges.filter((e) => ids.has(e.source) && ids.has(e.target))),
      ) as Edge[],
    });
    set({ status: `已复制 ${selected.length} 个节点到剪贴板` });
  },
  pasteClipboard: (pos) => {
    const cb = getClipboard();
    if (!cb?.nodes.length) {
      set({ status: "剪贴板为空，请先 Ctrl+C" });
      return;
    }
    pushGraphHistory(get);
    const xs = cb.nodes.map((n) => n.position.x);
    const ys = cb.nodes.map((n) => n.position.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const anchor = pos || { x: minX + 48, y: minY + 48 };
    const idMap = new Map<string, string>();
    const created = cb.nodes.map((n) => {
      const data = n.data as NodeData;
      const node = makeNode(
        data.kind,
        {
          x: anchor.x + (n.position.x - minX),
          y: anchor.y + (n.position.y - minY),
        },
        { ...data } as Partial<NodeData>,
      );
      idMap.set(n.id, node.id);
      return { ...node, selected: true };
    });
    const newEdges = cb.edges.map((e) => ({
      ...e,
      id: uid("e"),
      source: idMap.get(e.source) || e.source,
      target: idMap.get(e.target) || e.target,
      selected: false,
    }));
    const state = get();
    set(() => ({
      nodes: [
        ...state.nodes.map((n) => ({ ...n, selected: false })),
        ...created,
      ],
      edges: [...state.edges, ...newEdges],
      selectedId: created[0]?.id || null,
      status: `已粘贴 ${created.length} 个节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  selectAll: () => {
    const nodes = get().nodes.map((n) => ({ ...n, selected: true }));
    set({
      nodes,
      selectedId: nodes[0]?.id || null,
      status: `已全选 ${nodes.length} 个节点`,
    });
  },
  undoGraph: () => {
    const prev = popGraphPast(() => cloneGraph(get().nodes, get().edges, get().selectedId));
    if (!prev) {
      set({ status: "没有可撤销的操作" });
      return;
    }
    set((state) => ({
      nodes: prev.nodes,
      edges: prev.edges,
      selectedId: prev.selectedId,
      status: "已撤销",
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  redoGraph: () => {
    const next = popGraphFuture(() => cloneGraph(get().nodes, get().edges, get().selectedId));
    if (!next) {
      set({ status: "没有可重做的操作" });
      return;
    }
    set((state) => ({
      nodes: next.nodes,
      edges: next.edges,
      selectedId: next.selectedId,
      status: "已重做",
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  clearSelection: () => {
    set({
      nodes: get().nodes.map((n) => ({ ...n, selected: false })),
      edges: get().edges.map((e) => ({ ...e, selected: false })),
      selectedId: null,
    });
  },
  alignSelected: (mode) => {
    const sid = get().selectedId;
    const selected = get().nodes.filter((n) => n.selected || n.id === sid);
    if (selected.length < 2) {
      set({ status: "对齐至少需要 2 个选中节点" });
      return;
    }
    pushGraphHistory(get);
    let next = [...selected];
    if (mode === "left") {
      const x = Math.min(...next.map((n) => n.position.x));
      next = next.map((n) => ({ ...n, position: { ...n.position, x } }));
    } else if (mode === "center") {
      const cx =
        next.reduce((s, n) => s + n.position.x + (n.measured?.width || 180) / 2, 0) / next.length;
      next = next.map((n) => ({
        ...n,
        position: { ...n.position, x: cx - (n.measured?.width || 180) / 2 },
      }));
    } else if (mode === "top") {
      const y = Math.min(...next.map((n) => n.position.y));
      next = next.map((n) => ({ ...n, position: { ...n.position, y } }));
    } else if (mode === "middle") {
      const cy =
        next.reduce((s, n) => s + n.position.y + (n.measured?.height || 120) / 2, 0) / next.length;
      next = next.map((n) => ({
        ...n,
        position: { ...n.position, y: cy - (n.measured?.height || 120) / 2 },
      }));
    } else if (mode === "distribute-h") {
      const sorted = [...next].sort((a, b) => a.position.x - b.position.x);
      const first = sorted[0].position.x;
      const last = sorted[sorted.length - 1].position.x;
      const step = (last - first) / Math.max(sorted.length - 1, 1);
      next = sorted.map((n, i) => ({
        ...n,
        position: { ...n.position, x: first + step * i },
      }));
    }
    const map = new Map(next.map((n) => [n.id, n]));
    set((state) => ({
      nodes: state.nodes.map((n) => map.get(n.id) || n),
      status: `已对齐 ${next.length} 个节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  beginGraphEdit: () => {
    pushGraphHistory(get);
  },
  saveProject: (opts) => {
    const s = get();
    const nowISO = new Date().toISOString();
    // 多项目路径：有 activeProjectId 就写入 bundle 并更新索引
    if (s.activeProjectId) {
      const existing = readProjectBundle(s.activeProjectId);
      const canvasId = s.activeCanvasId || existing?.activeCanvasId || uid("canvas");
      const canvasName = s.activeCanvasName || "画布 1";
      const snapshot: CanvasSnapshot = {
        id: canvasId,
        name: canvasName,
        nodes: s.nodes,
        edges: s.edges,
        savedAt: nowISO,
      };
      const base: ProjectBundle = existing || {
        version: CURRENT_SCHEMA_VERSION,
        schemaVersion: CURRENT_SCHEMA_VERSION,
        id: s.activeProjectId,
        name: s.activeProjectName || "未命名工作区",
        dramaTitle: s.dramaTitle,
        episode: s.episode,
        nodes: s.nodes,
        edges: s.edges,
        savedAt: nowISO,
        stage3d: get().getStage3dSnapshot?.(),
        aiVersions: collectAiVersions(s.nodes),
      };
      const bundle = patchActiveCanvas(
        {
          ...base,
          dramaTitle: s.dramaTitle,
          episode: s.episode,
          stage3d: get().getStage3dSnapshot?.(),
          aiVersions: collectAiVersions(s.nodes) || base.aiVersions,
        },
        snapshot,
      );
      bundle.name = s.activeProjectName || bundle.name || "未命名工作区";
      try {
        writeProjectBundle(bundle);
        const idx = readProjectsIndex();
        const others = idx.filter((m) => m.id !== s.activeProjectId);
        const meta: ProjectMeta = {
          id: s.activeProjectId,
          name: bundle.name,
          savedAt: nowISO,
          nodeCount: s.nodes.length,
        };
        writeProjectsIndex([meta, ...others]);
        if (!s.activeCanvasId) {
          set({ activeCanvasId: canvasId, activeCanvasName: canvasName });
        }
        if (!opts?.silent) set({ status: `已保存「${bundle.name}」· ${canvasName}` });
      } catch (e) {
        const msg = e instanceof Error ? e.message : `保存失败: ${e}`;
        set({ status: msg });
      }
      return;
    }
    // 旧版单项目路径（兜底）
    const payload = {
      version: CURRENT_SCHEMA_VERSION,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      dramaTitle: s.dramaTitle,
      episode: s.episode,
      nodes: s.nodes,
      edges: s.edges,
      savedAt: nowISO,
    };
    try {
      localStorage.setItem(PROJECT_KEY, JSON.stringify(payload));
      if (!opts?.silent) set({ status: "工程已保存（v3 schema）" });
    } catch (e) {
      const msg =
        e instanceof DOMException && e.name === "QuotaExceededError"
          ? "本地配额不足，请用「导出JSON」备份后清理叠卡大图"
          : `保存失败: ${e}`;
      set({ status: msg });
    }
  },
  loadProject: () => {
    // 多项目路径：有 activeProjectId 直接读 bundle
    const activeId = get().activeProjectId;
    if (activeId) {
      const bundle = readProjectBundle(activeId);
      if (!bundle) {
        set({ status: `工程丢失（${activeId}），已切换到未命名` });
        set({ activeProjectId: null, activeProjectName: "未命名工作区" });
        return;
      }
      // 通过 loadProjectBundle 统一加载，同时更新 activeProjectId/activeProjectName
      get().loadProjectBundle(bundle);
      return;
    }
    // 旧版单项目路径（兜底）
    let raw = localStorage.getItem(PROJECT_KEY);
    let migratedFromOld = false;
    if (!raw) {
      raw = localStorage.getItem(PROJECT_KEY_OLD);
      if (raw) migratedFromOld = true;
    }
    if (!raw) {
      set({ status: "没有本地工程" });
      return;
    }
    try {
      const rawData = JSON.parse(raw);
      const migrated = migrateBundle(rawData);
      const nodes = Array.isArray(migrated?.nodes) ? migrated.nodes : [];
      const known = FLOW_NODE_TYPES;
      const safeNodes = nodes.filter((n: Node) => {
        if (!n) return false;
        const t = String(n.type || "");
        if (t.includes(":")) return true;
        return known.has(t);
      });
      const upgradedEdges = Array.isArray(migrated?.edges) ? migrated.edges : [];
      if (migratedFromOld && migrated) {
        localStorage.setItem(PROJECT_KEY, JSON.stringify(migrated));
        localStorage.removeItem(PROJECT_KEY_OLD);
      }
      set({
        nodes: safeNodes,
        edges: upgradedEdges,
        dramaTitle: migrated?.dramaTitle || "",
        episode: migrated?.episode || "",
        status:
          safeNodes.length < nodes.length
            ? `已加载工程（跳过 ${nodes.length - safeNodes.length} 个未知节点）`
            : migratedFromOld
              ? `已加载旧工程并升级到 v3（${migrated?.savedAt || "未知时间"}）`
              : `已加载工程（${migrated?.savedAt || "未知时间"}）`,
      });
    } catch {
      set({ status: "工程文件损坏" });
    }
  },
  // —— 多项目 CRUD ——
  listProjects: () => {
    return readProjectsIndex().sort((a, b) => (b.savedAt > a.savedAt ? 1 : -1));
  },
  ensureWorkspace: () => {
    const s = get();
    if (s.activeProjectId) return s.activeProjectId;
    const existing = readProjectsIndex();
    if (existing.length) {
      get().openProject(existing[0].id);
      return existing[0].id;
    }
    const legacyRaw = localStorage.getItem(PROJECT_KEY) || localStorage.getItem(PROJECT_KEY_OLD);
    if (legacyRaw) {
      try {
        const data = JSON.parse(legacyRaw);
        const id = get().createProject("未命名工作区");
        const bundle = readProjectBundle(id);
        if (bundle) {
          const canvasId = uid("canvas");
          const canvases: CanvasSnapshot[] = [
            {
              id: canvasId,
              name: "画布 1",
              nodes: Array.isArray(data.nodes) ? data.nodes : s.nodes,
              edges: Array.isArray(data.edges) ? data.edges : s.edges,
              savedAt: data.savedAt || new Date().toISOString(),
            },
          ];
          writeProjectBundle({
            ...bundle,
            dramaTitle: data.dramaTitle || "",
            episode: data.episode || "",
            canvases,
            activeCanvasId: canvasId,
            nodes: canvases[0].nodes,
            edges: canvases[0].edges,
          });
          get().openProject(id);
          return id;
        }
      } catch {
        /* fall through */
      }
    }
    const id = get().createProject("未命名工作区");
    const snap = { nodes: s.nodes, edges: s.edges, dramaTitle: s.dramaTitle, episode: s.episode };
    if (snap.nodes.length || snap.edges.length) {
      const bundle = readProjectBundle(id);
      if (bundle) {
        const canvasId = uid("canvas");
        const now = new Date().toISOString();
        const canvases: CanvasSnapshot[] = [
          { id: canvasId, name: "画布 1", nodes: snap.nodes, edges: snap.edges, savedAt: now },
        ];
        writeProjectBundle({
          ...bundle,
          dramaTitle: snap.dramaTitle,
          episode: snap.episode,
          canvases,
          activeCanvasId: canvasId,
          nodes: snap.nodes,
          edges: snap.edges,
          savedAt: now,
        });
        get().openProject(id);
      }
    }
    return id;
  },
  createProject: (name) => {
    const id = uid("proj");
    const now = new Date().toISOString();
    const canvasId = uid("canvas");
    const meta: ProjectMeta = { id, name, savedAt: now, nodeCount: 0 };
    writeProjectsIndex([meta, ...readProjectsIndex()]);
    const canvases: CanvasSnapshot[] = [
      { id: canvasId, name: "画布 1", nodes: [], edges: [], savedAt: now },
    ];
    const bundle: ProjectBundle = {
      version: CURRENT_SCHEMA_VERSION,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      id,
      name,
      dramaTitle: "",
      episode: "",
      nodes: [],
      edges: [],
      savedAt: now,
      canvases,
      activeCanvasId: canvasId,
    };
    writeProjectBundle(bundle);
    pushGraphHistory(get);
    set({
      activeProjectId: id,
      activeProjectName: name,
      activeCanvasId: canvasId,
      activeCanvasName: "画布 1",
      nodes: [],
      edges: [],
      dramaTitle: "",
      episode: "",
      selectedId: null,
      status: `已创建工作区「${name}」`,
      dirtyVersion: 0,
    });
    return id;
  },
  openProject: (id) => {
    const current = get().activeProjectId;
    if (current && current !== id) {
      get().saveProject({ silent: true });
    }
    const loaded = readBundleWithActiveCanvas(id);
    if (!loaded) {
      set({ status: "工作区文件丢失（请检查本地存储）" });
      return;
    }
    const { bundle, canvas, canvases } = loaded;
    pushGraphHistory(get);
    const safeNodes = filterFlowNodes(canvas.nodes);
    const edges = upgradeSchemaV2toV3(safeNodes, canvas.edges || []);
    if (bundle.stage3d) {
      try {
        localStorage.setItem("shiguang-canvas:stage3d:v5", JSON.stringify(bundle.stage3d));
      } catch {
        /* ignore */
      }
    }
    const skipped = canvas.nodes.length - safeNodes.length;
    const base = `已打开「${bundle.name}」· ${canvas.name}（${safeNodes.length} 节点）`;
    set({
      nodes: safeNodes,
      edges,
      dramaTitle: bundle.dramaTitle || "",
      episode: bundle.episode || "",
      stage3dSnapshot: bundle.stage3d,
      activeProjectId: id,
      activeProjectName: bundle.name,
      activeCanvasId: canvas.id,
      activeCanvasName: canvas.name,
      selectedId: null,
      status: skipped > 0 ? `${base}（跳过 ${skipped} 个未知节点）` : base,
      viewMode: "canvas",
      dirtyVersion: 0,
    });
    if (!bundle.canvases?.length && canvases.length) {
      writeProjectBundle({ ...bundle, canvases, activeCanvasId: canvas.id });
    }
  },
  renameProject: (id, newName) => {
    const trimmed = newName.trim();
    if (!trimmed) return;
    const idx = readProjectsIndex();
    const next = idx.map((m) => (m.id === id ? { ...m, name: trimmed } : m));
    writeProjectsIndex(next);
    const bundle = readProjectBundle(id);
    if (bundle) {
      writeProjectBundle({ ...bundle, name: trimmed });
    }
    if (get().activeProjectId === id) {
      set({ activeProjectName: trimmed, status: `已重命名为「${trimmed}」` });
    }
  },
  deleteProject: (id) => {
    const idx = readProjectsIndex().filter((m) => m.id !== id);
    writeProjectsIndex(idx);
    deleteProjectBundle(id);
    if (get().activeProjectId === id) {
      set({ activeProjectId: null, activeProjectName: "未命名工作区", activeCanvasId: null, activeCanvasName: "画布 1" });
    }
  },
  bulkDeleteProjects: (ids) => {
    const s = new Set(ids);
    const idx = readProjectsIndex().filter((m) => !s.has(m.id));
    writeProjectsIndex(idx);
    ids.forEach((id) => deleteProjectBundle(id));
    if (ids.includes(get().activeProjectId || "")) {
      set({ activeProjectId: null, activeProjectName: "未命名工作区", activeCanvasId: null, activeCanvasName: "画布 1" });
    }
  },
  listCanvases: () => {
    const s = get();
    if (!s.activeProjectId) {
      return [
        {
          id: s.activeCanvasId || "memory",
          name: s.activeCanvasName,
          nodeCount: s.nodes.length,
          savedAt: "",
        },
      ];
    }
    const loaded = readBundleWithActiveCanvas(s.activeProjectId);
    if (!loaded) return [];
    return loaded.canvases.map((c) => ({
      id: c.id,
      name: c.name,
      nodeCount: c.nodes.length,
      savedAt: c.savedAt,
    }));
  },
  createCanvas: (name) => {
    if (!get().activeProjectId) get().ensureWorkspace();
    const projectId = get().activeProjectId;
    if (!projectId) return "";
    get().saveProject({ silent: true });
    const bundle = readProjectBundle(projectId);
    if (!bundle) return "";
    const canvases = ensureProjectCanvases(bundle);
    const id = uid("canvas");
    const canvasName = (name || "").trim() || `画布 ${canvases.length + 1}`;
    const now = new Date().toISOString();
    const nextCanvas: CanvasSnapshot = { id, name: canvasName, nodes: [], edges: [], savedAt: now };
    writeProjectBundle({
      ...bundle,
      canvases: [...canvases, nextCanvas],
      activeCanvasId: id,
      nodes: [],
      edges: [],
      savedAt: now,
    });
    pushGraphHistory(get);
    set({
      activeCanvasId: id,
      activeCanvasName: canvasName,
      nodes: [],
      edges: [],
      selectedId: null,
      status: `已新建「${canvasName}」`,
    });
    return id;
  },
  switchCanvas: (id) => {
    const s = get();
    if (!s.activeProjectId || s.activeCanvasId === id) return;
    get().saveProject({ silent: true });
    const loaded = readBundleWithActiveCanvas(s.activeProjectId);
    if (!loaded) return;
    const target = loaded.canvases.find((c) => c.id === id);
    if (!target) return;
    pushGraphHistory(get);
    const safeNodes = filterFlowNodes(target.nodes);
    const edges = upgradeSchemaV2toV3(safeNodes, target.edges || []);
    writeProjectBundle({ ...loaded.bundle, activeCanvasId: id, nodes: safeNodes, edges });
    set({
      nodes: safeNodes,
      edges,
      activeCanvasId: id,
      activeCanvasName: target.name,
      selectedId: null,
      status: `已切换到「${target.name}」`,
      dirtyVersion: 0,
    });
  },
  renameCanvas: (id, newName) => {
    const trimmed = newName.trim();
    if (!trimmed) return;
    const s = get();
    if (!s.activeProjectId) {
      if (!s.activeCanvasId || s.activeCanvasId === id) {
        set({ activeCanvasName: trimmed, status: `画布已重命名为「${trimmed}」` });
      }
      return;
    }
    const bundle = readProjectBundle(s.activeProjectId);
    if (!bundle) return;
    const canvases = ensureProjectCanvases(bundle).map((c) =>
      c.id === id ? { ...c, name: trimmed } : c,
    );
    writeProjectBundle({ ...bundle, canvases });
    if (s.activeCanvasId === id) {
      set({ activeCanvasName: trimmed, status: `画布已重命名为「${trimmed}」` });
    }
  },
  deleteCanvas: (id) => {
    const s = get();
    if (!s.activeProjectId) return;
    const bundle = readProjectBundle(s.activeProjectId);
    if (!bundle) return;
    const canvases = ensureProjectCanvases(bundle);
    if (canvases.length <= 1) {
      set({ status: "至少保留一个画布" });
      return;
    }
    get().saveProject({ silent: true });
    const next = canvases.filter((c) => c.id !== id);
    const fallback = next[0];
    writeProjectBundle({
      ...bundle,
      canvases: next,
      activeCanvasId: fallback.id,
      nodes: fallback.nodes,
      edges: fallback.edges,
    });
    if (s.activeCanvasId === id) {
      const safeNodes = filterFlowNodes(fallback.nodes);
      set({
        nodes: safeNodes,
        edges: upgradeSchemaV2toV3(safeNodes, fallback.edges || []),
        activeCanvasId: fallback.id,
        activeCanvasName: fallback.name,
        selectedId: null,
        status: `已删除画布，当前「${fallback.name}」`,
        dirtyVersion: 0,
      });
    }
  },
  duplicateCanvas: (id) => {
    const s = get();
    if (!s.activeProjectId) return;
    const bundle = readProjectBundle(s.activeProjectId);
    if (!bundle) return;
    const canvases = ensureProjectCanvases(bundle);
    const src = canvases.find((c) => c.id === id);
    if (!src) return;
    const newId = uid("canvas");
    const copy: CanvasSnapshot = {
      id: newId,
      name: `${src.name} 副本`,
      nodes: JSON.parse(JSON.stringify(src.nodes)) as Node[],
      edges: JSON.parse(JSON.stringify(src.edges)) as Edge[],
      savedAt: new Date().toISOString(),
    };
    writeProjectBundle({ ...bundle, canvases: [...canvases, copy] });
    set({ status: `已复制「${src.name}」` });
  },
  exportProjectJSON: (id) => {
    const targetId = id ?? get().activeProjectId;
    let bundle: ProjectBundle | null = null;
    if (targetId) bundle = readProjectBundle(targetId);
    if (!bundle) {
      // 兜底：导出当前内存里的画布
      const s = get();
      bundle = {
        version: CURRENT_SCHEMA_VERSION,
        schemaVersion: CURRENT_SCHEMA_VERSION,
        id: targetId || uid("proj"),
        name: get().activeProjectName || "未命名工作区",
        dramaTitle: s.dramaTitle,
        episode: s.episode,
        nodes: s.nodes,
        edges: s.edges,
        savedAt: new Date().toISOString(),
        stage3d: s.getStage3dSnapshot?.(),
      };
    }
    try {
      return JSON.stringify(bundle, null, 2);
    } catch (e) {
      set({ status: `导出失败: ${e}` });
      return null;
    }
  },
  importProjectJSON: (json, opts) => {
    try {
      const raw = JSON.parse(json);
      const isBundle = isProjectBundleLike(raw);
      if (isBundle) {
        // 走完整 schema 迁移链（幂等），覆盖 V1/V2/V3 所有老版本
        const migrated = migrateBundle(raw);
        const nodes = Array.isArray(migrated?.nodes) ? migrated.nodes : [];
        const id = uid("proj");
        const now = new Date().toISOString();
        const bundle: ProjectBundle = {
          version: CURRENT_SCHEMA_VERSION,
          schemaVersion: CURRENT_SCHEMA_VERSION,
          id,
          name: opts?.name || String(migrated?.name || "导入的工程"),
          dramaTitle: migrated?.dramaTitle || "",
          episode: migrated?.episode || "",
          nodes,
          edges: Array.isArray(migrated?.edges) ? migrated.edges : [],
          savedAt: now,
          stage3d: migrated?.stage3d,
        };
        writeProjectBundle(bundle);
        const idx = readProjectsIndex();
        writeProjectsIndex([{ id, name: bundle.name, savedAt: now, nodeCount: nodes.length }, ...idx]);
        if (opts?.open !== false) {
          get().loadProjectBundle(bundle);
        }
        return id;
      }
      set({ status: "无效的工程 JSON（缺少 nodes 字段）" });
      return null;
    } catch (e) {
      set({ status: `导入失败: ${e instanceof Error ? e.message : e}` });
      return null;
    }
  },
  listTemplates: () => {
    const builtin = BUILTIN_TEMPLATES.map((t) => ({
      id: t.id,
      name: t.name,
      savedAt: "",
      builtin: true as const,
      description: t.description,
    }));
    let custom: { id: string; name: string; savedAt: string; builtin?: boolean; description?: string }[] = [];
    try {
      const raw = localStorage.getItem(TEMPLATES_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      custom = Array.isArray(arr)
        ? arr.map((t: any) => ({
            id: String(t.id),
            name: String(t.name || "未命名"),
            savedAt: String(t.savedAt || ""),
            builtin: false as const,
          }))
        : [];
    } catch {
      custom = [];
    }
    return [...builtin, ...custom];
  },
  saveTemplate: (name) => {
    const id = uid("tpl");
    const entry = {
      id,
      name: (name || "工作流模板").trim(),
      savedAt: new Date().toISOString(),
      dramaTitle: get().dramaTitle,
      episode: get().episode,
      nodes: get().nodes,
      edges: get().edges,
    };
    let arr: any[] = [];
    try {
      arr = JSON.parse(localStorage.getItem(TEMPLATES_KEY) || "[]");
      if (!Array.isArray(arr)) arr = [];
    } catch {
      arr = [];
    }
    arr.unshift(entry);
    arr = arr.slice(0, 20);
    localStorage.setItem(TEMPLATES_KEY, JSON.stringify(arr));
    set({ status: `模板已保存：${entry.name}` });
  },
  loadTemplate: (id) => {
    // 预装模板：builtin:xxx 前缀
    if (id.startsWith("builtin:")) {
      const bt = BUILTIN_TEMPLATES.find((t) => t.id === id);
      if (bt) {
        set({
          nodes: bt.nodes,
          edges: bt.edges,
          dramaTitle: "",
          episode: "",
          status: `已加载预装模板：${bt.name}`,
        });
        return;
      }
      set({ status: "找不到预装模板" });
      return;
    }
    // 用户自定义模板：走 localStorage
    try {
      const arr = JSON.parse(localStorage.getItem(TEMPLATES_KEY) || "[]");
      const t = Array.isArray(arr) ? arr.find((x: any) => x.id === id) : null;
      if (!t) {
        set({ status: "找不到模板" });
        return;
      }
      set({
        nodes: t.nodes || [],
        edges: t.edges || [],
        dramaTitle: t.dramaTitle || "",
        episode: t.episode || "",
        status: `已加载模板：${t.name}`,
      });
    } catch {
      set({ status: "模板损坏" });
    }
  },
  deleteTemplate: (id) => {
    try {
      let arr = JSON.parse(localStorage.getItem(TEMPLATES_KEY) || "[]");
      if (!Array.isArray(arr)) arr = [];
      arr = arr.filter((x: any) => x.id !== id);
      localStorage.setItem(TEMPLATES_KEY, JSON.stringify(arr));
      set({ status: "模板已删除" });
    } catch {
      set({ status: "删除失败" });
    }
  },
  setNodeImage: (id, imageUrl, opts) => {
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== id) return n;
        const data = n.data as NodeData;
        if (data.kind === "shot" || data.kind === "image") {
          if (opts?.replaceStack) {
            const sid = `img_${Math.random().toString(36).slice(2, 9)}`;
            return {
              ...n,
              data: {
                ...data,
                imageUrl,
                images: [{ id: sid, url: imageUrl }],
                primaryImageId: sid,
              },
            };
          }
          return { ...n, data: pushStackImage(data, imageUrl, opts?.label) };
        }
        if (data.kind === "video") {
          return { ...n, data: { ...data, posterUrl: imageUrl } };
        }
        if (data.kind === "director" || data.kind === "panorama") {
          return { ...n, data: { ...data, imageUrl, status: "success" } };
        }
        if (data.kind === "source" && data.mediaType === "image") {
          return { ...n, data: { ...data, imageUrl } };
        }
        if (data.kind === "animation") {
          return { ...n, data: { ...data, sheetUrl: imageUrl, status: "success" } };
        }
        return n;
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  setPrimaryImage: (id, imageId) => {
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== id) return n;
        const data = n.data as NodeData;
        if (data.kind !== "shot" && data.kind !== "image") return n;
        const hit = (data.images || []).find((x) => x.id === imageId);
        if (!hit) return n;
        return {
          ...n,
          data: { ...data, primaryImageId: imageId, imageUrl: hit.url },
        };
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  setNodeVideo: (id, videoUrl, posterUrl, opts) => {
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== id) return n;
        const data = n.data as NodeData;
        if (data.kind !== "video") return n;
        return {
          ...n,
          data: pushStackVideo(data, videoUrl, opts?.label, posterUrl),
        };
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  setPrimaryVideo: (id, videoId) => {
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== id) return n;
        const data = n.data as NodeData;
        if (data.kind !== "video") return n;
        const hit = (data.videos || []).find((x) => x.id === videoId);
        if (!hit) return n;
        return {
          ...n,
          data: {
            ...data,
            primaryVideoId: videoId,
            videoUrl: hit.url,
            ...(hit.posterUrl ? { posterUrl: hit.posterUrl } : {}),
          },
        };
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  setNodeAudio: (id, audioUrl) => {
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== id) return n;
        const data = n.data as NodeData;
        if (data.kind !== "audio") return n;
        return { ...n, data: { ...data, audioUrl } };
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  groupSelected: () => {
    const selected = get().nodes.filter((n) => n.selected && (n.data as NodeData).kind !== "group");
    if (selected.length < 2) {
      set({ status: "请至少选中 2 个非编组节点再编组" });
      return;
    }
    pushGraphHistory(get);
    const xs = selected.map((n) => n.position.x);
    const ys = selected.map((n) => n.position.y);
    const minX = Math.min(...xs) - 24;
    const minY = Math.min(...ys) - 40;
    const maxX = Math.max(...selected.map((n) => n.position.x + 220));
    const maxY = Math.max(...selected.map((n) => n.position.y + 160));
    const g = makeNode("group", { x: minX, y: minY }, { title: `编组 ${selected.length}` });
    g.style = {
      width: Math.max(280, maxX - minX + 40),
      height: Math.max(180, maxY - minY + 60),
      zIndex: -1,
    };
    const ids = new Set(selected.map((n) => n.id));
    set((state) => ({
      nodes: [
        ...state.nodes.map((n) => {
          if (!ids.has(n.id)) return n;
          return {
            ...n,
            parentId: g.id,
            extent: "parent" as const,
            position: {
              x: n.position.x - minX,
              y: n.position.y - minY,
            },
          };
        }),
        g,
      ],
      selectedId: g.id,
      status: `已编组 ${selected.length} 个节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  getProjectBundle: () => {
    const s = get();
    let stage3d = s.stage3dSnapshot;
    if (!stage3d) {
      try {
        stage3d = JSON.parse(localStorage.getItem("shiguang-canvas:stage3d:v5") || localStorage.getItem("shiguang-canvas:stage3d:v4") || "null");
      } catch {
        stage3d = undefined;
      }
    }
    return {
      nodes: s.nodes,
      edges: s.edges,
      dramaTitle: s.dramaTitle,
      episode: s.episode,
      stage3d,
    };
  },
  loadProjectBundle: (bundle) => {
    pushGraphHistory(get);
    if (bundle.stage3d) {
      try {
        localStorage.setItem("shiguang-canvas:stage3d:v5", JSON.stringify(bundle.stage3d));
      } catch {
        /* ignore quota */
      }
    }
    // schema 安全处理：过滤未知节点类型 + 自动补齐连线 data.type
    const known = FLOW_NODE_TYPES;
    const rawNodes = Array.isArray(bundle.nodes) ? bundle.nodes : [];
    const safeNodes = filterFlowNodes(rawNodes);
    const rawEdges = Array.isArray(bundle.edges) ? bundle.edges : [];
    const edges = upgradeSchemaV2toV3(safeNodes, rawEdges);
    // 多项目路径自动更新 activeProjectId/activeProjectName
    const activeProjectId = (bundle as ProjectBundle).id ?? null;
    const activeProjectName = (bundle as ProjectBundle).name || "未命名工作区";
    const canvases = ensureProjectCanvases(bundle as ProjectBundle);
    const activeCanvas = pickActiveCanvas(bundle as ProjectBundle, canvases);
    const skipped = rawNodes.length - safeNodes.length;
    const base = activeProjectId
      ? `已加载工程「${activeProjectName}」（${safeNodes.length} 节点）`
      : `已导入工程（${safeNodes.length} 节点）`;
    // S6: 版本锁定提醒 — 如果项目保存时的 AI model 快照与当前节点配置不一致，
    // 说明用户换过模型，生成结果可能与旧项目预期不同
    const aiSnapshot = (bundle as ProjectBundle).aiVersions;
    let aiVersionNote = "";
    if (aiSnapshot && Object.keys(aiSnapshot.providers).length > 0) {
      const currentSnapshot = collectAiVersions(safeNodes);
      const prev = aiSnapshot.providers;
      const curr = currentSnapshot?.providers || {};
      const allKeys = new Set([...Object.keys(prev), ...Object.keys(curr)]);
      const diff: string[] = [];
      for (const k of allKeys) {
        if (prev[k] !== curr[k]) {
          diff.push(`${k}: ${prev[k] ?? "—"} → ${curr[k] ?? "—"}`);
        }
      }
      if (diff.length > 0) {
        aiVersionNote = ` ⚠️ 模型版本变更（${diff.join("; ")}），生成结果可能与项目保存时不同`;
      }
    }
    set({
      nodes: safeNodes,
      edges,
      dramaTitle: bundle.dramaTitle || "",
      episode: bundle.episode || "",
      stage3dSnapshot: bundle.stage3d,
      activeProjectId,
      activeProjectName,
      activeCanvasId: activeCanvas.id,
      activeCanvasName: activeCanvas.name,
      selectedId: null,
      status: (skipped > 0 ? `${base}（跳过 ${skipped} 个未知节点）` : base) + aiVersionNote,
      viewMode: "canvas",
      dirtyVersion: 0,
    });
  },
  setStage3dSnapshot: (snapshot) => {
    set({ stage3dSnapshot: snapshot });
  },
  getStage3dSnapshot: () => get().stage3dSnapshot,

  // ===== Character Library（对接 Python CharacterStore）=====
  characters: [] as CharacterEntry[],
  refreshCharacters: async () => {
    const BRIDGE = (window as any).__BRIDGE__ || "http://127.0.0.1:18765";
    try {
      const res = await fetch(`${BRIDGE}/host/characters`);
      if (!res.ok) { set({ characters: [] as CharacterEntry[] }); return; }
      const data = await res.json();
      const list: CharacterEntry[] = Array.isArray(data) ? data : (data?.characters ?? []);
      set({ characters: list });
      set({ status: `角色库已同步 (${list.length} 个角色)` });
    } catch {
      set({ characters: [] as CharacterEntry[] });
    }
  },
  bindCharacterToShot: (nodeId, characterId) => {
    const chars = get().characters;
    const target = chars.find((c) => c.id === characterId);
    if (!target) return;
    pushGraphHistory(get);
    set((s) => ({
      nodes: s.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const d = n.data as ShotData;
        const appearance = target.appearance ? `[角色外貌: ${target.appearance}] ` : "";
        return {
          ...n,
          data: {
            ...d,
            characterId: target.id,
            characterName: target.name,
            characterAppearance: target.appearance || "",
            prompt: (d.prompt || "").replace(/^\[角色外貌:[^\]]*\]\s*/, "") + (appearance ? "\n" + appearance : ""),
          } as ShotData,
        };
      }),
      dirtyVersion: s.dirtyVersion + 1,
      status: `已绑定角色「${target.name}」到节点`,
    }));
  },
  unbindCharacterFromShot: (nodeId) => {
    pushGraphHistory(get);
    set((s) => ({
      nodes: s.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const d = n.data as ShotData;
        return {
          ...n,
          data: {
            ...d,
            characterId: undefined,
            characterName: undefined,
            characterAppearance: undefined,
            prompt: (d.prompt || "").replace(/^\[角色外貌:[^\]]*\]\s*/, "").trim(),
          } as ShotData,
        };
      }),
      dirtyVersion: s.dirtyVersion + 1,
      status: "已解除角色绑定",
    }));
  },
  syncCharacterToShot: (nodeId) => {
    const node = get().nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const d = node.data as ShotData;
    if (!d.characterId) { set({ status: "该节点未绑定角色" }); return; }
    const target = get().characters.find((c) => c.id === d.characterId);
    if (!target) { set({ status: `角色 ${d.characterId} 不在角色库（可能已删除）` }); return; }
    pushGraphHistory(get);
    set((s) => ({
      nodes: s.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const nd = n.data as ShotData;
        const appearance = target.appearance ? `[角色外貌: ${target.appearance}] ` : "";
        return {
          ...n,
          data: {
            ...nd,
            characterName: target.name,
            characterAppearance: target.appearance || "",
            prompt: (nd.prompt || "").replace(/^\[角色外貌:[^\]]*\]\s*/, "") + (appearance ? "\n" + appearance : ""),
          } as ShotData,
        };
      }),
      dirtyVersion: s.dirtyVersion + 1,
      status: `已从角色库同步「${target.name}」的最新外貌描述`,
    }));
  },

  addCaptureToCanvas: (imageUrl, title, shotMeta) => {
    pushGraphHistory(get);
    const baseTitle = title || "机位截图";
    const targetId = get().directorTargetNodeId;
    const target = targetId
      ? get().nodes.find((n) => n.id === targetId && (n.data as NodeData).kind === "director")
      : undefined;

    if (target) {
      const prev = target.data as DirectorData;
      const captureUrls = [...(prev.captureUrls || []), imageUrl].slice(-24);
      set((state) => ({
        nodes: state.nodes.map((n) =>
          n.id === target.id
            ? {
                ...n,
                data: {
                  ...prev,
                  imageUrl,
                  captureUrls,
                  lastCameraName: baseTitle,
                  status: "success",
                } as DirectorData,
              }
            : n,
        ),
        dirtyVersion: state.dirtyVersion + 1,
      }));
    }

    const node = makeNode(
      "shot",
      { x: 80 + Math.random() * 120, y: 60 + Math.random() * 80 },
      {
        title: baseTitle,
        shotSize: shotMeta?.shotSize || "中景",
        duration: 3,
        prompt: `3D导演台机位参考「${baseTitle}」，保持人物站位、朝向与镜头构图`,
        imageUrl,
        firstFrameUrl: imageUrl,
        focalLength: shotMeta?.focalLength,
        aperture: shotMeta?.aperture,
        cameraPreset: shotMeta?.cameraPreset,
        movement: shotMeta?.movement,
      } as Partial<ShotData>,
    );
    set((state) => ({
      nodes: [...state.nodes, node],
      selectedId: target?.id || node.id,
      viewMode: "canvas",
      status: target
        ? `截图已回写导演台「${(target.data as DirectorData).title || target.id}」并入镜头：${baseTitle}`
        : `3D 截图已入画布：${baseTitle}${shotMeta?.focalLength ? ` @ ${shotMeta.focalLength}mm` : ""}`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  addStudioNode: (kind, data) => {
    pushGraphHistory(get);
    const node = makeNode(
      kind,
      { x: 100 + Math.random() * 200, y: 80 + Math.random() * 160 },
      data as Partial<NodeData>,
    );
    set((state) => ({
      nodes: [...state.nodes, node],
      selectedId: node.id,
      viewMode: "canvas",
      status: `已从工作台加入画布：${(data.title as string) || node.id}`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
}));
