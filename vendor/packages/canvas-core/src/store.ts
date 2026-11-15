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
  CURRENT_SCHEMA_VERSION,
} from "./stores/schema-migrations";
import {
  PROJECT_KEY,
  PROJECT_KEY_OLD,
  TEMPLATES_KEY,
  FLOW_NODE_TYPES,
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
} from "./stores/project-storage";
import { persistMediaUrl, reviewCanvasNodeViaHost } from "./bridge";
import { comfyToCanvasNodes, type ComfyCanvasNode } from "./comfyToCanvas";
import { persistNodesCopy, applyUrlMapToNodes } from "./stores/persist-media";
import { BUILTIN_TEMPLATES } from "./stores/templates";
import { upgradeSchemaV2toV3, collectAiVersions } from "./stores/migrations";
import {
  cloneGraph,
  pushGraphHistory,
  popGraphPast,
  popGraphFuture,
  getClipboard,
  setClipboard,
} from "./stores/history-store";
import type { GraphSnap, ClipboardPayload } from "./stores/history-store";
import { stackReducer, ensureStack } from "./magnetic/CardStack";
import type { CardStackData, CardStatus } from "./magnetic/types";
// 幂等守卫的判定逻辑独立成文件（store.ts 是冻结区，只引不入，见 storeIdempotent.ts 头注）
import { bondedSidesEqual, nodeDataPatchIsNoop } from "./storeIdempotent";
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
  type DirectorCardData,
  type DigitalHumanData,
  type AnimationData,
  type AnimationAction,
  type PanoramaData,
  type NoteData,
  type SourceData,
  type CharacterData,
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
  type CharacterEntry,
} from "./stores/node-factory";
// 灯位→3D 灯光快照类型。**type-only**：stage3dLighting.ts 反向 import 本 store，值级会成环
import type { Stage3dLightState } from "./stage3dLighting";

/** re-export 给外部模块用（保持 import 路径不变） */
export type {
  GraphSnap, ClipboardPayload,
  EdgeType, NodeStatus, MovementType, CameraPreset, GenParams, StatusBlock,
  StackVideo, StackImage,
  ShotData, ScriptData, ImageData, VideoData, PromptData, TextData,
  ConfigData, GeneratorData, GroupData, AudioData, MusicData, NodeData,
  MarkdownData, ShotlistData, ShotlistRow, StoryboardData, StoryboardCell,
  DirectorData, DigitalHumanData, AnimationData, AnimationAction, PanoramaData, NoteData, SourceData,
  DirectorCardData, CharacterData,
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

/** 画布档位：小白模式（磁吸意图画布）/ 专业模式（节点画布） */
export type CanvasTier = "novice" | "pro";

/** 档位持久化 key */
export const TIER_STORAGE_KEY = "shiguang-canvas:tier:v1";

/** 主题持久化 key（V4.41.22 引入） */
export const THEME_STORAGE_KEY = "shiguang-canvas:theme:v1";

/** 主题：暗色（默认）/ 浅色。沿用项目品牌色（深藏蓝 + 主蓝 + 强调橙） */
export type CanvasTheme = "dark" | "light";

/** 读取已保存的档位，默认专业模式（存量用户行为不变） */
export function readStoredTier(): CanvasTier {
  try {
    return localStorage.getItem(TIER_STORAGE_KEY) === "novice" ? "novice" : "pro";
  } catch {
    return "pro";
  }
}

/** 读取已保存的主题，默认暗色（存量用户行为不变） */
export function readStoredTheme(): CanvasTheme {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

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
  /** 该工程所属画布档位；缺失视为专业模式（存量工程） */
  tier?: CanvasTier;
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
  /** 保存在哪个档位创建；缺失视为专业模式 */
  tier?: CanvasTier;
  /** S6: 项目内用过的 AI provider/model 版本快照（打开时对比系统当前版本弹提醒） */
  aiVersions?: {
    /** provider → model 映射，收集自 config / generator / shot 节点的 data.model 字段 */
    providers: Record<string, string>;
    /** 项目保存时的前端版本号，留空不影响主流程 */
    canvasVersion?: string;
  };
};


/** WS4#2 相机路径规划：后端 /host/storyboard-camera-plan 返回的机位计划（结构对齐 Stage3D.StageCamera） */
export type StageCameraPlanShot = {
  id: string;
  name: string;
  position: [number, number, number];
  lookAt: [number, number, number];
  fov: number;
  shotSize?: string;
  movement?: string;
  pathPoints?: { pos: [number, number, number]; look: [number, number, number] }[];
  pathDuration?: number;
};

type Store = {
  nodes: Node[];
  edges: Edge[];
  selectedId: string | null;
  status: string;
  dramaTitle: string;
  episode: string;
  viewMode: ViewMode;
  canvasLayoutMode: CanvasLayoutMode;
  /** 磁吸模式开关：开启后拖拽节点时产生磁吸效果 */
  magneticMode: boolean;
  /** 画布档位：小白模式 = 磁吸意图画布；专业模式 = 节点画布 */
  editorTier: CanvasTier;
  /** 当前主题（V4.41.22 引入）：暗色 / 浅色 */
  theme: CanvasTheme;
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
  /** 切换主题（V4.41.22 引入）：持久化 + 同步 document.documentElement[data-theme] */
  setTheme: (t: CanvasTheme) => void;
  setCanvasLayoutMode: (m: CanvasLayoutMode) => void;
  setMagneticMode: (on: boolean) => void;
  /** 切换画布档位（会持久化；小白模式强制开启磁吸） */
  setEditorTier: (t: CanvasTier) => void;
  openDirectorForNode: (nodeId: string) => void;
  clearDirectorTarget: () => void;

  // ===== Selection =====
  setSelected: (id: string | null) => void;
  updateSelectedData: (patch: Record<string, unknown>) => void;
  updateNodeData: (id: string, patch: Record<string, unknown>) => void;
  /** 小白模式：双击卡片请求打开精细编辑（Inspector 自动展开进阶设置） */
  requestProEdit: () => void;
  /** 双击信号计数器：Inspector 订阅它变化后展开进阶设置 */
  proEditNonce: number;
  /** 咬合侧隐形表（瞬态 UI 态，不落盘）：nodeId → 需透明的贴合边方向。
   *  由 CanvasShell 依据 bonds 几何推导写入，NoviceCard 订阅后给贴合边加透明描边+直角，
   *  两卡贴合处融为一块（对齐 Windows 磁贴观感，2026-09-16 用户裁定）。 */
  bondedSides: Record<string, import("./magnetic/types").SpatialDirection[]>;
  setBondedSides: (map: Record<string, import("./magnetic/types").SpatialDirection[]>) => void;
  // 层叠系统（磁吸层 CardStack 状态入口）
  pushLayer: (nodeId: string, params: Record<string, unknown>) => void;
  removeLayer: (nodeId: string, layerId: string) => void;
  activateLayer: (nodeId: string, layerId: string) => void;
  hybridLayers: (nodeId: string, layerIdA: string, layerIdB: string, weightA: number) => void;
  setLayerStatus: (
    nodeId: string,
    layerId: string,
    patch: { status: CardStatus; issues?: string[]; qualityScore?: number },
  ) => void;
  /** 生成完成后触发 AI 审阅（走 /host/canvas-ai-review），回写层叠状态与质检分 */
  reviewNode: (nodeId: string) => void;

  // ===== Node CRUD + Workflow Generators =====
  addNode: (type: NodeData["kind"], pos?: { x: number; y: number }) => string;
  addRegistryNode: (type: string, pos?: { x: number; y: number }) => void;
  addVideoReference: (
    url: string,
    opts?: { title?: string; name?: string; pos?: { x: number; y: number } },
  ) => void;
  addStoryboardGrid: (count?: 9 | 25) => void;
  applyStoryboard: (shots: StoryboardShot[], scriptTitle?: string) => void;
  /** 导演卡拆解：把分镜结果追加为导演卡的下游镜头节点（非破坏，保留画布既有内容） */
  breakdownDirectorCard: (directorId: string, shots: StoryboardShot[], cameras?: StageCameraPlanShot[]) => void;
  /** ComfyUI workflow 粘贴落地：把 comfyToCanvasNodes 的映射结果铺成画布节点 + 连线 */
  applyComfyWorkflow: (json: unknown, origin?: { x: number; y: number }) => number;
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
    kind: "image" | "video" | "prompt" | "audio" | "source",
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
  alignSelected: (mode: "left" | "center" | "right" | "top" | "middle" | "bottom" | "distribute-h" | "distribute-v") => void;
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
  listProjects: (tier?: CanvasTier) => ProjectMeta[];
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
  /** 选择性存模板：只存「选中的一组卡片」及其内部连线（卡片生态 · 积木沉淀） */
  saveSelectionTemplate: (name: string) => number;
  loadTemplate: (id: string) => void;
  deleteTemplate: (id: string) => void;

  // ===== Character Library（对接 Python CharacterStore）=====
  characters: CharacterEntry[];
  refreshCharacters: () => Promise<void>;                         // GET /host/characters
  bindCharacterToShot: (nodeId: string, characterId: string) => void;
  unbindCharacterFromShot: (nodeId: string) => void;
  syncCharacterToShot: (nodeId: string) => void;                // 手动从角色库重刷 prompt 里的角色设定块

  // ===== 3D Stage Snapshot Sync =====
  setStage3dSnapshot: (snapshot: unknown) => void;
  getStage3dSnapshot: () => unknown | undefined;

  // ===== WS4#2 相机路径规划：AI 分镜机位 → Stage3D 实时视口 =====
  /** 递增序号：触发 Stage3D 消费 pendingStage3dCameras（仅序号变化才应用，避免重复） */
  stage3dApplySeq: number;
  /** 待 Stage3D 应用的机位计划（消费后置空，防止切回导演台时覆盖手动机位） */
  pendingStage3dCameras: StageCameraPlanShot[] | null;
  applyStage3dCameraPlan: (cameras: StageCameraPlanShot[]) => void;
  consumeStage3dCameraPlan: () => void;

  // ===== 缺口① 角色库 → 3D 导演台：把一个角色投成导演台人偶 =====
  /** 递增序号：触发 Stage3D 消费 pendingStage3dCast（仅序号变化才应用，避免重复投递） */
  stage3dCastSeq: number;
  /** 待投递的角色（消费后置空，防止切回导演台时重复添加同一个角色） */
  pendingStage3dCast: CharacterEntry | null;
  requestStage3dCast: (character: CharacterEntry) => void;
  consumeStage3dCast: () => void;

  // ===== 24 位灯位 → 3D 灯光（2026-10-12）。同族第三通道，照 stage3dCastSeq 正统模式 =====
  stage3dLightingSeq: number; pendingStage3dLighting: Stage3dLightState | null;
  requestStage3dLighting: (state: Stage3dLightState | null) => void; consumeStage3dLighting: () => void;
  // ===== Canvas View Preferences =====
  showGrid: boolean;
  smoothLine: boolean;
  setShowGrid: (v: boolean) => void;
  setSmoothLine: (v: boolean) => void;
};

type ProjectSaveSnap = {
  activeProjectId: string | null;
  activeProjectName: string;
  activeCanvasId: string | null;
  activeCanvasName: string;
  dramaTitle: string;
  episode: string;
  nodes: Node[];
  edges: Edge[];
  stage3d: unknown;
  silent?: boolean;
};

let saveChain: Promise<void> = Promise.resolve();

function scheduleReplaceMediaUrl(
  set: (fn: (state: Store) => Partial<Store>) => void,
  url?: string,
) {
  if (!url || !url.startsWith("data:") || url.length < 4096) return;
  void persistMediaUrl(url).then((next) => {
    if (next === url) return;
    set((state) => {
      const nodes = applyUrlMapToNodes(state.nodes, new Map([[url, next]]));
      return nodes === state.nodes ? {} : { nodes };
    });
  });
}

async function persistAndWriteSnapshot(
  snap: ProjectSaveSnap,
  get: () => Store,
  set: (partial: Partial<Store>) => void,
) {
  const { nodes: persisted, map } = await persistNodesCopy(snap.nodes);
  const nowISO = new Date().toISOString();
  const stillHere = () =>
    snap.activeProjectId
      ? get().activeProjectId === snap.activeProjectId
      : !get().activeProjectId;

  const applyLiveUrls = (extra?: Partial<Store>) => {
    if (!stillHere()) return;
    const mapped = applyUrlMapToNodes(get().nodes, map);
    const patch: Partial<Store> = { ...(extra || {}) };
    if (mapped !== get().nodes) patch.nodes = mapped;
    if (Object.keys(patch).length) set(patch);
  };

  if (snap.activeProjectId) {
    const existing = readProjectBundle(snap.activeProjectId);
    const canvasId = snap.activeCanvasId || existing?.activeCanvasId || uid("canvas");
    const canvasName = snap.activeCanvasName || "画布 1";
    const snapshot: CanvasSnapshot = {
      id: canvasId,
      name: canvasName,
      nodes: persisted,
      edges: snap.edges,
      savedAt: nowISO,
    };
    const base: ProjectBundle = existing || {
      version: CURRENT_SCHEMA_VERSION,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      id: snap.activeProjectId,
      name: snap.activeProjectName || "未命名工作区",
      dramaTitle: snap.dramaTitle,
      episode: snap.episode,
      nodes: persisted,
      edges: snap.edges,
      savedAt: nowISO,
      stage3d: snap.stage3d,
      aiVersions: collectAiVersions(persisted),
    };
    const bundle = patchActiveCanvas(
      {
        ...base,
        dramaTitle: snap.dramaTitle,
        episode: snap.episode,
        stage3d: snap.stage3d,
        aiVersions: collectAiVersions(persisted) || base.aiVersions,
      },
      snapshot,
    );
    bundle.name = snap.activeProjectName || bundle.name || "未命名工作区";
    try {
      const idx = readProjectsIndex();
      const prev = idx.find((m) => m.id === snap.activeProjectId);
      // 工程所属档位：沿用原档位，新建时按当前档位写入
      const tier = prev?.tier || bundle.tier || readStoredTier();
      bundle.tier = tier;
      writeProjectBundle(bundle);
      const others = idx.filter((m) => m.id !== snap.activeProjectId);
      writeProjectsIndex([
        {
          id: snap.activeProjectId,
          name: bundle.name,
          savedAt: nowISO,
          nodeCount: persisted.length,
          tier,
        },
        ...others,
      ]);
      const extra: Partial<Store> = {};
      if (stillHere() && !get().activeCanvasId) {
        extra.activeCanvasId = canvasId;
        extra.activeCanvasName = canvasName;
      }
      if (!snap.silent) extra.status = `已保存「${bundle.name}」· ${canvasName}`;
      applyLiveUrls(extra);
    } catch (e) {
      const msg = e instanceof Error ? e.message : `保存失败: ${e}`;
      if (stillHere()) set({ status: msg });
    }
    return;
  }

  const payload = {
    version: CURRENT_SCHEMA_VERSION,
    schemaVersion: CURRENT_SCHEMA_VERSION,
    dramaTitle: snap.dramaTitle,
    episode: snap.episode,
    nodes: persisted,
    edges: snap.edges,
    savedAt: nowISO,
  };
  try {
    localStorage.setItem(PROJECT_KEY, JSON.stringify(payload));
    applyLiveUrls(snap.silent ? undefined : { status: "工程已保存（v3 schema）" });
  } catch (e) {
    const msg =
      e instanceof DOMException && e.name === "QuotaExceededError"
        ? "本地配额不足，请用「导出 JSON」备份后清理叠卡大图"
        : `保存失败: ${e}`;
    if (stillHere()) set({ status: msg });
  }
}

// ── 角色设定块 → 生图提示词 ──────────────────────────────────────────
// 旧实现只拼 target.appearance：用户在角色库填的「气质倾向 / 标志性符号 / 性格特征」
// 三个 visual 字段全被丢掉，绑定角色后一个字都进不了提示词。
// 现在直接用服务端 /host/characters 下发的 prompt（Python build_character_prompt 拼的，
// 含 visual 组全部字段）—— 前端不再自己拼，避免两份拼装逻辑漂移。
//
// 顺带修掉两个幂等性 bug：旧代码的删除正则锚在开头 ^，但新块是 append 到末尾，
// 于是「重复绑定越绑越长」「解绑删不掉」。

/** 角色设定块必须占一行：行内换行压平，否则下面的行级幂等替换会漏。 */
function charPromptBlock(text: string | undefined): string {
  const t = String(text || "").replace(/\s*\n\s*/g, " ").trim();
  return t ? `[角色设定: ${t}]` : "";
}

/** 命中 `[角色设定: ...]` / 旧版 `[角色外貌: ...]` 整行（贪婪到行内最后一个 ]）。 */
const CHAR_BLOCK_RE = /^[ \t]*\[角色(?:设定|外貌):[^\n]*\][ \t]*\r?\n?/gm;

/** 幂等替换 prompt 里的角色设定块；block 传空串即删除。 */
function applyCharBlock(prompt: string | undefined, block: string): string {
  const out = String(prompt || "")
    .replace(CHAR_BLOCK_RE, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return block ? (out ? out + "\n" + block : block) : out;
}

export const useCanvasStore = create<Store>((set, get) => ({
  // 2026-10-14：初始画布改为空白 —— 进入 AI 画布模块先显示「拾光导演台」空状态
  // 引导卡（CanvasEmptyState 仅在 nodes.length===0 时渲染），由用户从引导卡 /
  // 双击空白处 / 「/」自行添加节点，不再预置演示用 script×1 + shot×2。
  // 解冻记录：canvas-magnetic-intent（用户授权解冻 2026-10-14）。
  nodes: [],
  edges: [],
  selectedId: null,
  status: "拾光导演台就绪 — 可添加分镜节点",
  dramaTitle: "",
  episode: "",
  viewMode: "home",
  canvasLayoutMode: "flow",
  magneticMode: true,
  editorTier: readStoredTier(),
  theme: readStoredTheme(),
  directorTargetNodeId: null,
  stage3dApplySeq: 0,
  pendingStage3dCameras: null,
  stage3dCastSeq: 0,
  pendingStage3dCast: null,
  stage3dLightingSeq: 0,
  pendingStage3dLighting: null,
  activeProjectId: null,
  activeProjectName: "未命名工作区",
  activeCanvasId: null,
  activeCanvasName: "画布 1",
  dirtyVersion: 0,
  proEditNonce: 0,
  bondedSides: {},
  // 幂等守卫（React #185 根因）：内容与当前表相同则整体不 set，bondedSides 引用不变，
  // 订阅它的 NoviceCard 不再全量重渲染 → 不再抛 dimensions change → 不断链。
  setBondedSides: (map) => {
    if (bondedSidesEqual(get().bondedSides, map)) return;
    set({ bondedSides: map });
  },
  showGrid: true,
  smoothLine: true,
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
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      /* localStorage 写入失败（沙箱/隐私模式）不影响内存切换 */
    }
    if (typeof document !== "undefined") {
      document.documentElement.setAttribute("data-theme", theme);
    }
    set({ theme });
  },
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
  setMagneticMode: (magneticMode) => set({ magneticMode }),
  setEditorTier: (editorTier) => {
    try {
      localStorage.setItem(TIER_STORAGE_KEY, editorTier);
    } catch {
      /* 隐私模式下写入失败不影响本次切换 */
    }
    // 小白模式强制开启磁吸 + 回到卡片视图：卡片靠磁吸建立关系，这是它的核心交互
    set(
      editorTier === "novice"
        ? { editorTier, magneticMode: true, canvasLayoutMode: "flow" as CanvasLayoutMode }
        : { editorTier },
    );
  },
  setShowGrid: (showGrid) => set({ showGrid }),
  setSmoothLine: (smoothLine) => set({ smoothLine }),
  setSelected: (selectedId) => set({ selectedId }),
  updateSelectedData: (patch) => {
    const id = get().selectedId;
    if (!id) return;
    get().updateNodeData(id, patch);
  },
  /** 小白模式双击信号：双击卡片 = 打开右侧精细编辑（Inspector 展开进阶设置）。自增 nonce 触发订阅 */
  requestProEdit: () => set((s) => ({ proEditNonce: s.proEditNonce + 1 })),
  updateNodeData: (id, patch) => {
    // 幂等守卫（React #185 放大器）：patch 逐键与现值相同 ⇒ 空转，
    // 整个 set 都不执行（nodes 引用不变、dirtyVersion 不自增）。
    // 已核查全部调用方，无一依赖「空转也 +1 dirtyVersion」。
    const target = get().nodes.find((n) => n.id === id);
    if (target && nodeDataPatchIsNoop(target.data as Record<string, unknown>, patch)) return;
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...patch } } : n,
      ),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  // ===== 层叠系统 =====
  pushLayer: (nodeId, params) => {
    set((state) => {
      const nodes = state.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const current = (n.data.stack as CardStackData) || { layers: [], activeLayerId: "" };
        const newStack = stackReducer(current, { type: "push", params });
        return { ...n, data: { ...n.data, stack: newStack } };
      });
      return { nodes, dirtyVersion: state.dirtyVersion + 1 };
    });
  },
  removeLayer: (nodeId, layerId) => {
    set((state) => {
      const nodes = state.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const current = (n.data.stack as CardStackData) || { layers: [], activeLayerId: "" };
        const newStack = stackReducer(current, { type: "remove", layerId });
        return { ...n, data: { ...n.data, stack: newStack } };
      });
      return { nodes, dirtyVersion: state.dirtyVersion + 1 };
    });
  },
  activateLayer: (nodeId, layerId) => {
    set((state) => {
      const nodes = state.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const current = (n.data.stack as CardStackData) || { layers: [], activeLayerId: "" };
        const newStack = stackReducer(current, { type: "activate", layerId });
        const activeLayer = newStack.layers.find((l) => l.id === layerId);
        const newData = activeLayer ? { ...n.data, ...activeLayer.params, stack: newStack } : { ...n.data, stack: newStack };
        return { ...n, data: newData };
      });
      return { nodes, dirtyVersion: state.dirtyVersion + 1 };
    });
  },
  hybridLayers: (nodeId, layerIdA, layerIdB, weightA) => {
    set((state) => {
      const nodes = state.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const current = (n.data.stack as CardStackData) || { layers: [], activeLayerId: "" };
        const newStack = stackReducer(current, { type: "hybrid", layerIdA, layerIdB, weightA });
        return { ...n, data: { ...n.data, stack: newStack } };
      });
      return { nodes, dirtyVersion: state.dirtyVersion + 1 };
    });
  },
  setLayerStatus: (nodeId, layerId, patch) => {
    set((state) => ({
      nodes: state.nodes.map((n) => {
        if (n.id !== nodeId) return n;
        const current = (n.data.stack as CardStackData) || { layers: [], activeLayerId: "" };
        const newStack = stackReducer(current, {
          type: "set_status",
          layerId,
          status: patch.status,
          issues: patch.issues,
          qualityScore: patch.qualityScore,
        });
        return { ...n, data: { ...n.data, stack: newStack } };
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
  },
  reviewNode: (nodeId) => {
    const node = get().nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const data = node.data as NodeData;
    // 仅对能产出成片的节点做质检（shot/image/video），其余类型不触发
    if (data.kind !== "shot" && data.kind !== "image" && data.kind !== "video") return;
    const loose = node.data as Record<string, unknown>;
    // 无层叠时先用当前节点数据补一层（承载审阅状态），保证旧节点无 stack 也能显示徽标
    const existing = (loose.stack as CardStackData | undefined);
    if (!existing || existing.layers.length === 0) {
      get().updateNodeData(nodeId, { stack: ensureStack(loose) });
    }
    const fresh = get().nodes.find((n) => n.id === nodeId);
    const stack =
      ((fresh?.data as Record<string, unknown>).stack as CardStackData | undefined) ||
      ensureStack(loose);
    const activeLayer = stack.layers.find((l) => l.id === stack.activeLayerId) || stack.layers[0];
    if (!activeLayer) return;
    const layerId = activeLayer.id;
    // 先置为「审阅中」
    get().setLayerStatus(nodeId, layerId, { status: "pending_review" });
    // 组装审阅载荷（quality_scores 当前为空，后端按 70 基线打分并标注为估算）
    const imageUrl = typeof loose.imageUrl === "string" ? loose.imageUrl : "";
    const videoUrl = typeof loose.videoUrl === "string" ? loose.videoUrl : "";
    const posterUrl = typeof loose.posterUrl === "string" ? loose.posterUrl : "";
    const path = imageUrl || videoUrl || posterUrl;
    const duration = typeof loose.duration === "number" ? loose.duration : 0;
    const qualityScores = loose.qualityScores as Record<string, number | null> | undefined;
    reviewCanvasNodeViaHost({
      clip_id: nodeId,
      node_id: nodeId,
      path,
      duration,
      quality_scores: qualityScores || {},
    })
      .then((res) => {
        // 后端失败或非预期返回：回退到「已完成」，不阻塞成片
        if (!res.ok || !res.review) {
          get().setLayerStatus(nodeId, layerId, { status: "success" });
          return;
        }
        // 后端 0-100 分 → 前端 0~1 评分；D 级(<60) 视为有问题，其余视为通过
        get().setLayerStatus(nodeId, layerId, {
          status: res.status === "issues-found" ? "review_issues" : "review_passed",
          qualityScore:
            typeof res.quality_score === "number" ? res.quality_score / 100 : undefined,
          issues: res.status === "issues-found" ? res.review.suggestions || [] : [],
        });
      })
      .catch(() => {
        get().setLayerStatus(nodeId, layerId, { status: "success" });
      });
  },
  addNode: (type, pos) => {
    pushGraphHistory(get);
    const position = pos || {
      x: 120 + Math.random() * 320,
      y: 80 + Math.random() * 240,
    };
    /*
     * 镜头卡自动编号（2026-11-15 加）
     *
     * 序列信息写在**数据**里，不写在画布位置上 —— 用户明确拒绝「为顺序牺牲
     * 摆放自由度」。新建镜头自动拿「当前最大镜号 + 1」，用户可在右侧面板手改
     * （插镜、调序）。其它卡片类型不带此字段。
     */
    let extra: Partial<NodeData> | undefined;
    if (type === "shot") {
      const maxNo = get().nodes.reduce((m, n) => {
        const d = n.data as { kind?: string; shotNumber?: number };
        return d.kind === "shot" && typeof d.shotNumber === "number"
          ? Math.max(m, d.shotNumber)
          : m;
      }, 0);
      extra = { shotNumber: maxNo + 1 } as Partial<NodeData>;
    }
    const node = makeNode(type, position, extra);
    set((state) => ({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), { ...node, selected: true }],
      selectedId: node.id,
      status: `已添加「${type}」节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
    return node.id;
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
      // 网格步进 = CARD_SIZE(240×200) - 贴合落位 gap=-2（invariant：相邻边框融合）→ 238/198
      // 旧值 230 会让相邻卡重叠 10px：超出 bondTolerance(2px) 不构成咬合，视觉却近乎贴死（V4.23.2 修正）
      const node = makeNode(
        "shot",
        { x: 320 + col * 238, y: 40 + row * 198 },
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
  breakdownDirectorCard: (directorId, shots, cameras) => {
    const list = Array.isArray(shots) ? shots : [];
    const camList = Array.isArray(cameras) ? cameras : [];
    const directorNode = get().nodes.find((n) => n.id === directorId);
    if (!directorNode) return;
    if (!list.length) {
      set({ status: "拆解结果为空" });
      get().updateNodeData(directorId, { status: "failed", errorMessage: "拆解结果为空" });
      return;
    }
    pushGraphHistory(get);
    const baseX = directorNode.position.x;
    const baseY = directorNode.position.y;
    const cols = list.length > 12 ? 5 : 3;
    const shotNodes: Node[] = [];
    const edges: Edge[] = [];
    list.forEach((s, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const cam = camList[i];
      // 网格步进 = CARD_SIZE(240×200) - 贴合落位 gap=-2 → 238/198（V4.23.2，与拉片布局一致）
      const child = makeNode(
        "shot",
        { x: baseX + 360 + col * 238, y: baseY + row * 198 },
        {
          title: `镜 ${String(i + 1).padStart(2, "0")}`,
          shotSize: s.shot || "中景",
          duration: Number(s.duration) || 3,
          dialogue: s.dialogue || "",
          prompt: s.description || `分镜 ${i + 1}`,
          // 导演卡拆解顺带把 AI 相机计划（机位 + 运镜）写进分镜卡，供 Stage3D 摆机位
          camera3d: cam
            ? {
                position: cam.position,
                lookAt: cam.lookAt,
                fov: cam.fov,
                movement: cam.movement,
                pathPoints: cam.pathPoints,
                pathDuration: cam.pathDuration,
              }
            : undefined,
        } as Partial<ShotData>,
      );
      shotNodes.push(child);
      edges.push({
        id: uid("e"),
        source: directorId,
        target: child.id,
        ...defaultEdgeOptions,
      });
    });
    set((state) => ({
      nodes: [...state.nodes, ...shotNodes],
      edges: [...state.edges, ...edges],
      selectedId: shotNodes[0]?.id || directorId,
      status: `导演卡拆解完成：${shotNodes.length} 个分镜节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
    get().updateNodeData(directorId, {
      status: "success",
      errorMessage: "",
      lastBreakdown: { shots: shotNodes.length },
    });
  },
  applyComfyWorkflow: (json, origin) => {
    const mapped = comfyToCanvasNodes(json);
    if (!mapped.nodes.length) {
      set({ status: "无法识别的 ComfyUI 工作流" });
      return 0;
    }
    pushGraphHistory(get);
    const baseX = origin?.x ?? 120;
    const baseY = origin?.y ?? 80;
    // 按「config/prompt/source/text 左列，image 右列」布局，避免全堆成一团
    const col = 260;
    const row = 180;
    const comfyToNodeId = new Map<string, string>();
    const nodes: Node[] = mapped.nodes.map((cn: ComfyCanvasNode, i) => {
      const onRight = cn.kind === "image";
      const x = baseX + (onRight ? col * 2 : 0);
      const y = baseY + i * row;
      const node = makeNode(cn.kind, { x, y }, {
        title: cn.title,
        ...(cn.kind === "prompt" || cn.kind === "text"
          ? { text: (cn.data.prompt as string) || cn.title }
          : {}),
        ...(cn.kind === "image" || cn.kind === "source"
          ? { prompt: (cn.data.prompt as string) || "" }
          : {}),
        ...(cn.kind === "config"
          ? { content: `ComfyUI 节点：${cn.data.comfyClassType || cn.title}` }
          : {}),
      } as Partial<NodeData>);
      comfyToNodeId.set(cn.comfyId, node.id);
      return node;
    });
    const edges: Edge[] = mapped.edges.flatMap((e) => {
      const src = comfyToNodeId.get(e.source);
      const dst = comfyToNodeId.get(e.target);
      if (!src || !dst) return [];
      return [{ id: uid("e"), source: src, target: dst, ...defaultEdgeOptions } as Edge];
    });
    set((state) => ({
      nodes: [...state.nodes, ...nodes],
      edges: [...state.edges, ...edges],
      selectedId: nodes[0]?.id || null,
      status: `已导入 ComfyUI 工作流：${nodes.length} 个节点`,
      dirtyVersion: state.dirtyVersion + 1,
    }));
    return nodes.length;
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
    } else if (mode === "right") {
      const x = Math.max(...next.map((n) => n.position.x + (n.measured?.width || 180)));
      next = next.map((n) => ({
        ...n,
        position: { ...n.position, x: x - (n.measured?.width || 180) },
      }));
    } else if (mode === "bottom") {
      const y = Math.max(...next.map((n) => n.position.y + (n.measured?.height || 120)));
      next = next.map((n) => ({
        ...n,
        position: { ...n.position, y: y - (n.measured?.height || 120) },
      }));
    } else if (mode === "distribute-v") {
      const sorted = [...next].sort((a, b) => a.position.y - b.position.y);
      const first = sorted[0].position.y;
      const last = sorted[sorted.length - 1].position.y;
      const step = (last - first) / Math.max(sorted.length - 1, 1);
      next = sorted.map((n, i) => ({
        ...n,
        position: { ...n.position, y: first + step * i },
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
    const snap: ProjectSaveSnap = {
      activeProjectId: s.activeProjectId,
      activeProjectName: s.activeProjectName,
      activeCanvasId: s.activeCanvasId,
      activeCanvasName: s.activeCanvasName,
      dramaTitle: s.dramaTitle,
      episode: s.episode,
      nodes: s.nodes,
      edges: s.edges,
      stage3d: s.getStage3dSnapshot?.(),
      silent: opts?.silent,
    };
    saveChain = saveChain
      .then(() => persistAndWriteSnapshot(snap, get, set))
      .catch((e) => {
        set({ status: e instanceof Error ? e.message : `保存失败: ${e}` });
      });
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
      const nodes: Node[] = Array.isArray(migrated?.nodes) ? (migrated.nodes as Node[]) : [];
      const known = FLOW_NODE_TYPES;
      const safeNodes = nodes.filter((n: Node) => {
        if (!n) return false;
        const t = String(n.type || "");
        if (t.includes(":")) return true;
        return known.has(t);
      });
      const upgradedEdges: Edge[] = Array.isArray(migrated?.edges) ? (migrated.edges as Edge[]) : [];
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
  listProjects: (tier) => {
    const all = readProjectsIndex().sort((a, b) => (b.savedAt > a.savedAt ? 1 : -1));
    if (!tier) return all;
    // 小白模式与专业模式各自只看自己的工程（同一份数据模型，独立工程文件）
    return all.filter((m) => (m.tier || "pro") === tier);
  },
  ensureWorkspace: () => {
    const s = get();
    if (s.activeProjectId) return s.activeProjectId;
    const tier = s.editorTier;
    const all = readProjectsIndex();
    const existing = all.filter((m) => (m.tier || "pro") === tier);
    if (existing.length) {
      get().openProject(existing[0].id);
      return existing[0].id;
    }
    // 该档位下还没有工程：有存量专业工程时不去抢占，直接新建当前档位工程
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
    const meta: ProjectMeta = {
      id,
      name,
      savedAt: now,
      nodeCount: 0,
      tier: get().editorTier,
    };
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
      tier: get().editorTier,
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
        const nodes: Node[] = Array.isArray(migrated?.nodes) ? (migrated.nodes as Node[]) : [];
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
          edges: Array.isArray(migrated?.edges) ? (migrated.edges as Edge[]) : [],
          savedAt: now,
          stage3d: migrated?.stage3d,
          tier: readStoredTier(),
        };
        writeProjectBundle(bundle);
        const idx = readProjectsIndex();
        writeProjectsIndex([
          { id, name: bundle.name, savedAt: now, nodeCount: nodes.length, tier: bundle.tier },
          ...idx,
        ]);
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
  saveSelectionTemplate: (name) => {
    const sid = get().selectedId;
    const selected = get().nodes.filter((n) => n.selected || n.id === sid);
    if (selected.length === 0) {
      set({ status: "没有选中的卡片，先点选要沉淀成模板的一组卡片" });
      return 0;
    }
    const idSet = new Set(selected.map((n) => n.id));
    // 只保留两端都在选中集内的连线（卡片内部关系，不含连向外部的线）
    const edges = get().edges.filter(
      (e) => idSet.has(e.source) && idSet.has(e.target),
    );
    const entry = {
      id: uid("tpl"),
      name: (name || "卡片组合").trim(),
      savedAt: new Date().toISOString(),
      dramaTitle: "",
      episode: "",
      nodes: selected,
      edges,
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
    set({ status: `已把 ${selected.length} 张卡片存为模板「${entry.name}」` });
    return selected.length;
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
        if (data.kind === "director" || data.kind === "panorama" || data.kind === "digitalHuman") {
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
    scheduleReplaceMediaUrl(set, imageUrl);
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
    scheduleReplaceMediaUrl(set, videoUrl);
    if (posterUrl) scheduleReplaceMediaUrl(set, posterUrl);
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
        if (data.kind !== "audio" && data.kind !== "music" && data.kind !== "digitalHuman") return n;
        return { ...n, data: { ...data, audioUrl } };
      }),
      dirtyVersion: state.dirtyVersion + 1,
    }));
    scheduleReplaceMediaUrl(set, audioUrl);
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
  applyStage3dCameraPlan: (cameras) => {
    set((state) => ({
      pendingStage3dCameras: cameras,
      stage3dApplySeq: state.stage3dApplySeq + 1,
      viewMode: "stage3d",
      status: `已生成 ${cameras.length} 个机位，正在应用到 3D 导演台`,
    }));
  },
  consumeStage3dCameraPlan: () => set({ pendingStage3dCameras: null }),
  requestStage3dCast: (character) => {
    set((state) => ({
      pendingStage3dCast: character,
      stage3dCastSeq: state.stage3dCastSeq + 1,
      viewMode: "stage3d",
      status: `已把「${character.name || "角色"}」投递到 3D 导演台`,
    }));
  },
  consumeStage3dCast: () => set({ pendingStage3dCast: null }),
  requestStage3dLighting: (lightState) => set((s) => ({ pendingStage3dLighting: lightState,
    stage3dLightingSeq: s.stage3dLightingSeq + 1, viewMode: "stage3d",
    status: lightState ? "已应用灯位为 3D 打光示意" : "已恢复灯光预设" })),
  consumeStage3dLighting: () => set({ pendingStage3dLighting: null }),

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
        const charBlock = charPromptBlock(target.prompt);
        return {
          ...n,
          data: {
            ...d,
            characterId: target.id,
            characterName: target.name,
            characterAppearance: target.appearance || "",
            prompt: applyCharBlock(d.prompt, charBlock),
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
            prompt: applyCharBlock(d.prompt, ""),
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
        const charBlock = charPromptBlock(target.prompt);
        return {
          ...n,
          data: {
            ...nd,
            characterName: target.name,
            characterAppearance: target.appearance || "",
            prompt: applyCharBlock(nd.prompt, charBlock),
          } as ShotData,
        };
      }),
      dirtyVersion: s.dirtyVersion + 1,
      status: `已从角色库同步「${target.name}」的最新角色设定`,
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
    scheduleReplaceMediaUrl(set, imageUrl);
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
