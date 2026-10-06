import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Node,
  type NodeTypes,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  resolveMediaUrl,
  type BridgePrefs,
  type ImageModelOption,
  type VideoModelOption,
  type AudioModelOption,
  type MusicModelOption,
  getAgentStatus,
  startCanvasAgent,
  isComfyWorkflowText,
  importComfyWorkflowText,
  getComfyEngineStatus,
  type ComfyEngineStatus,
} from "./bridge";
import AppNav, { type AppRoute } from "./AppNav";
import { CANVAS_VERSION_LABEL, CANVAS_VERSION_TITLE } from "./canvasVersion";
import { MusicYueFields } from "./musicYueFields";
import type { PromptItem } from "./promptLibrary";
import HomeLanding from "./HomeLanding";
import NodePalette, { buildAddNodeItems, isBuiltinNodeKind } from "./NodePalette";
import CommandPalette, { type CommandItem } from "./CommandPalette";
import WorkspaceCanvasMenus from "./WorkspaceCanvasMenus";
import { showcaseFromLibrary, type LocalAsset, type LocalPrompt } from "./localLibrary";
import { LibTvBottomDock } from "./LibTvChrome";
import { type NodeData, type ViewMode, type CanvasLayoutMode, type ShotData, useCanvasStore } from "./store";
import { useMagneticDrag } from "./magnetic/useMagneticDrag";
import { MagneticLines } from "./magnetic/MagneticLines";
import { SlotGhost } from "./magnetic/SlotGhost";
import { SnapSeam } from "./magnetic/SnapSeam";
import { SoftConnectionLines } from "./magnetic/SoftConnectionLines";
import { removeSoftConnection } from "./magnetic/SoftConnection";
import { computeBonds, bondedSidesMap } from "./magnetic/bonds";
import type { SoftConnection } from "./magnetic/types";
import { StackBadge } from "./magnetic/StackBadge";
import { StatusBadge } from "./magnetic/StatusBadge";
import { FloatingToolbar } from "./magnetic/FloatingToolbar";
import {
  ANGLE_PRESETS,
  FOCAL_PRESETS,
  MOVEMENT_OPTIONS,
  buildCameraPromptBlock,
} from "./shotCamera";
// nodeTypes 改为从 registry 动态读（内置节点 + 插件节点统一入口）
import { buildNodeTypes, useNodeRegistryVersion } from "./plugins/node-registry";
import CanvasContextMenu from "./components/canvas/CanvasContextMenu";
import CanvasToolbar from "./components/canvas/CanvasToolbar";
import CanvasEmptyState from "./components/canvas/CanvasEmptyState";
import MultiSelectToolbar from "./components/canvas/MultiSelectToolbar";
import ModelSelector from "./components/canvas/ModelSelector";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { getGraphPast, getGraphFuture } from "./stores/history-store";
import { buildNoviceNodeTypes, NoviceInspector } from "./novice";
import type { CanvasTier } from "./store";

/** 重面板按需分包：缩短首屏 JS，打开对应模式/侧栏再拉 chunk */
const PromptLibraryPanel = lazy(() => import("./PromptLibraryPanel"));
const StudioPage = lazy(() => import("./StudioPages"));
const ImageStudio = lazy(() => import("./ImageStudio"));
const VideoStudio = lazy(() => import("./VideoStudio"));
const PluginManagerPanel = lazy(() => import("./PluginManagerPanel"));
const MaskEditDialog = lazy(() => import("./MaskEditDialog"));
const AgentPanel = lazy(() => import("./AgentPanel"));

function PanelFallback({ label }: { label: string }) {
  return (
    <div className="sg-panel-fallback" style={{ color: "#8b9bb0", padding: "12px 8px", fontSize: 12 }}>
      正在加载{label}…
    </div>
  );
}

type CtxMenu =
  | { mode: "pane"; clientX: number; clientY: number; flow: { x: number; y: number } }
  | { mode: "node"; clientX: number; clientY: number; nodeId: string }
  | { mode: "edge"; clientX: number; clientY: number; edgeId: string }
  | {
      mode: "connect";
      clientX: number;
      clientY: number;
      flow: { x: number; y: number };
      sourceId: string;
      sourceHandle?: string;
    };

type PaletteState = {
  open: boolean;
  clientX: number;
  clientY: number;
  flow: { x: number; y: number };
};

export function FrameSlot({
  label,
  url,
  onPick,
  onClear,
}: {
  label: string;
  url?: string;
  onPick: (dataUrl: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {url ? (
        <div className="frame-row">
          <img className="frame-thumb" src={url} alt={label} />
          <button type="button" className="btn" onClick={onClear}>
            清除
          </button>
        </div>
      ) : null}
      <label className="file-btn">
        选择图片…
        <input
          type="file"
          accept="image/*"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            const res = await resolveMediaUrl(f);
            if (!res.ok || !res.url) {
              window.alert(res.message || "上传参考图失败");
              return;
            }
            onPick(res.url);
          }}
        />
      </label>
    </div>
  );
}

export function VideoRefSlot({
  label,
  url,
  name,
  onPick,
  onClear,
}: {
  label: string;
  url?: string;
  name?: string;
  onPick: (url: string, fileName: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {url ? (
        <div className="video-ref-box">
          <video src={url} muted playsInline controls />
          <div className="muted tiny">{name || "参考视频"}</div>
          <button type="button" className="btn" onClick={onClear}>
            清除
          </button>
        </div>
      ) : null}
      <label className="file-btn">
        选择视频片段…
        <input
          type="file"
          accept="video/*"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            const res = await resolveMediaUrl(f);
            if (!res.ok || !res.url) {
              window.alert(res.message || "上传参考视频失败");
              return;
            }
            onPick(res.url, f.name);
          }}
        />
      </label>
    </div>
  );
}

export type CanvasShellProps = {
  viewMode: ViewMode;
  setViewMode: (m: ViewMode) => void;
  status: string;
  prefs: BridgePrefs;
  generating: boolean;
  breaking: boolean;
  imageModels: ImageModelOption[];
  selectedModelKey: string;
  setSelectedModelKey: (k: string) => void;
  compareModelKey: string;
  setCompareModelKey: (k: string) => void;
  videoModels: VideoModelOption[];
  selectedVideoModelKey: string;
  setSelectedVideoModelKey: (k: string) => void;
  compareVideoModelKey: string;
  setCompareVideoModelKey: (k: string) => void;
  audioModels: AudioModelOption[];
  selectedAudioModelKey: string;
  setSelectedAudioModelKey: (k: string) => void;
  musicModels: MusicModelOption[];
  selectedMusicModelKey: string;
  setSelectedMusicModelKey: (k: string) => void;
  breakdownDraft: string;
  setBreakdownDraft: (v: string) => void;
  templates: { id: string; name: string; savedAt: string }[];
  dramaTitle: string;
  episode: string;
  setMeta: (dramaTitle: string, episode: string) => void;
  selectedData: NodeData | null;
  /** nodes/edges/onNodesChange/onEdgesChange/onConnect 改从 store 直取，避免 App.tsx 重渲染链 */
  onSelectionChange: (params: { nodes: Node[] }) => void;
  updateSelectedData: (patch: Record<string, unknown>) => void;
  addNode: (type: NodeData["kind"], pos?: { x: number; y: number }) => string;
  addRegistryNode: (type: string, pos?: { x: number; y: number }) => void;
  addStoryboardGrid: (count?: 9 | 25) => void;
  addThreeView: () => void;
  addVariants: (axis?: "表情" | "服装" | "背景", count?: number) => void;
  removeSelected: () => void;
  deleteEdge: (edgeId: string) => void;
  duplicateSelected: () => void;
  copySelected: () => void;
  pasteClipboard: (pos?: { x: number; y: number }) => void;
  selectAll: () => void;
  undoGraph: () => void;
  redoGraph: () => void;
  clearSelection: () => void;
  alignSelected: (mode: "left" | "center" | "top" | "middle" | "distribute-h") => void;
  beginGraphEdit: () => void;
  saveProject: (opts?: { silent?: boolean }) => void;
  loadProject: () => void;
  saveTemplate: (name: string) => void;
  loadTemplate: (id: string) => void;
  deleteTemplate: (id: string) => void;
  refreshTemplates: () => void;
  onGenerate: () => void;
  onCompareGenerate: () => void;
  onMultiAngleGenerate: () => void;
  onExportSkill: () => void;
  onImportSkill: (file: File) => void;
  onSetPrimaryVideo: (nodeId: string, videoId: string) => void;
  onBatchGenerate: () => void;
  onAbortBatch: () => void;
  /** 「运行到此处」（刀 A4-3）：后端出计划(dry_run) → 确认 → 执行整图 */
  onRunToHere: () => void;
  onSendToEditor: () => void;
  onSendAllToEditor: () => void;
  editorClipCount?: number;
  onSyncModels: () => void;
  onApplyPromptLibrary: (item: PromptItem) => void;
  onBreakdown: () => void;
  onExportStoryboard: () => void;
  onInpaint: (mask: string, prompt: string) => void;
  onSetPrimaryImage: (nodeId: string, imageId: string) => void;
  onGroupSelected: () => void;
  onExportZip: () => void;
  onImportZip: (file: File) => void;
  onApplyImageTool: (tool: "crop916" | "split2" | "split3" | "upscale" | "rotate90") => void;
  onSetNodeAudio: (dataUrl: string) => void;
  stage3dContent?: React.ReactNode;
  onSendStudioToCanvas: (payload: {
    kind: "image" | "video" | "prompt";
    title: string;
    prompt?: string;
    text?: string;
    imageUrl?: string;
    videoUrl?: string;
    posterUrl?: string;
  }) => void;
};

export default function CanvasShell(props: CanvasShellProps) {
  const {
    viewMode,
    setViewMode,
    status,
    prefs,
    generating,
    breaking,
    imageModels,
    selectedModelKey,
    setSelectedModelKey,
    compareModelKey,
    setCompareModelKey,
    videoModels,
    selectedVideoModelKey,
    setSelectedVideoModelKey,
    compareVideoModelKey,
    setCompareVideoModelKey,
    audioModels,
    selectedAudioModelKey,
    setSelectedAudioModelKey,
    musicModels,
    selectedMusicModelKey,
    setSelectedMusicModelKey,
    breakdownDraft,
    setBreakdownDraft,
    templates,
    dramaTitle,
    episode,
    setMeta,
    selectedData,
    onSelectionChange,
    updateSelectedData,
    addNode,
    addRegistryNode,
    addStoryboardGrid,
    addThreeView,
    addVariants,
    removeSelected,
    deleteEdge,
    duplicateSelected,
    copySelected,
    pasteClipboard,
    selectAll,
    undoGraph,
    redoGraph,
    clearSelection,
    // 角色库（Step A）— 从 store 读取，父组件不传 props
    // (characters/refreshCharacters/bind/unbind/sync 均在 store 内实现，见下方 selector)
    alignSelected,
    beginGraphEdit,
    saveProject,
    loadProject,
    saveTemplate,
    loadTemplate,
    deleteTemplate,
    refreshTemplates,
    onGenerate,
    onCompareGenerate,
    onMultiAngleGenerate,
    onExportSkill,
    onImportSkill,
    onSetPrimaryVideo,
    onBatchGenerate,
    onAbortBatch,
    onRunToHere,
    onSendToEditor,
    onSendAllToEditor,
    editorClipCount = 0,
    onSyncModels,
    onApplyPromptLibrary,
    onBreakdown,
    onExportStoryboard,
    onInpaint,
    onSetPrimaryImage,
    onGroupSelected,
    onExportZip,
    onImportZip,
    onApplyImageTool,
    onSetNodeAudio,
    stage3dContent,
    onSendStudioToCanvas,
  } = props;

  const rfRef = useRef<ReactFlowInstance | null>(null);
  /** 画布档位：小白模式（磁吸意图画布）/ 专业模式（节点画布） */
  const editorTier = useCanvasStore((s) => s.editorTier);
  const setEditorTier = useCanvasStore((s) => s.setEditorTier);
  /** 小白模式：卡片靠磁吸建立关系，不暴露连线与专业参数 */
  const isNovice = editorTier === "novice";
  // 从 registry 动态读 nodeTypes：内置节点 + 插件节点统一入口
  const registryVersion = useNodeRegistryVersion((s) => s.version);
  const registryNodeTypes = useMemo<NodeTypes>(() => {
    const built = buildNodeTypes();
    const out: NodeTypes = {};
    for (const [k, v] of Object.entries(built)) {
      if (v) out[k] = v as NodeTypes[string];
    }
    return out;
  }, [registryVersion]);
  /** 小白模式卡面：内置节点统一换成矩形磁吸卡片，插件节点保留原渲染器 */
  const shellNodeTypes = useMemo<NodeTypes>(
    () => (isNovice ? buildNoviceNodeTypes(registryNodeTypes) : registryNodeTypes),
    [isNovice, registryNodeTypes],
  );
  const addNodeItems = useMemo(() => buildAddNodeItems(), [registryVersion]);
  const pickNodeByType = (type: string, pos?: { x: number; y: number }) => {
    if (isBuiltinNodeKind(type)) addNode(type, pos);
    else addRegistryNode(type, pos);
  };
  const [ctxMenu, setCtxMenu] = useState<CtxMenu | null>(null);
  const [palette, setPalette] = useState<PaletteState>({
    open: false,
    clientX: 120,
    clientY: 120,
    flow: { x: 160, y: 120 },
  });
  const [cmdOpen, setCmdOpen] = useState(false);
  const lastPointerRef = useRef({ clientX: 200, clientY: 200 });
  const [spacePan, setSpacePan] = useState(false);
  const [snapGrid, setSnapGrid] = useState(true);
  const [leftCollapsed, setLeftCollapsed] = useState(() => localStorage.getItem("shiguang-canvas:left-collapsed") === "1");
  const [rightCollapsed, setRightCollapsed] = useState(() => localStorage.getItem("shiguang-canvas:right-collapsed") === "1");
  // 持久化折叠偏好：用户手动折叠/展开后记住
  useEffect(() => { localStorage.setItem("shiguang-canvas:left-collapsed", leftCollapsed ? "1" : "0"); }, [leftCollapsed]);
  useEffect(() => { localStorage.setItem("shiguang-canvas:right-collapsed", rightCollapsed ? "1" : "0"); }, [rightCollapsed]);
  const [autoSavedAt, setAutoSavedAt] = useState<string>("");
  const [agentListening, setAgentListening] = useState(false);
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentUrl, setAgentUrl] = useState("");
  const [maskOpen, setMaskOpen] = useState(false);
  const [zoomPct, setZoomPct] = useState(100);
  const [moreOpen, setMoreOpen] = useState(false);
  const [comfyEngineStatus, setComfyEngineStatus] = useState<ComfyEngineStatus | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const skillImportRef = useRef<HTMLInputElement>(null);
  const [agentPanelOpen, setAgentPanelOpen] = useState(() => {
    try {
      const v = localStorage.getItem("shiguang-canvas:agent-dock:open");
      // LibTV 空画布默认收起 Agent，避免挡四卡
      return v === null ? false : v === "1";
    } catch {
      return false;
    }
  });
  const setStatus = useCanvasStore((s) => s.setStatus);
  const applyComfyWorkflow = useCanvasStore((s) => s.applyComfyWorkflow);
  const selectedId = useCanvasStore((s) => s.selectedId);
  // 角色库（Step A）— 从 store 读取
  const characters = useCanvasStore((s) => s.characters);
  const refreshCharacters = useCanvasStore((s) => s.refreshCharacters);
  const bindCharacterToShot = useCanvasStore((s) => s.bindCharacterToShot);
  const unbindCharacterFromShot = useCanvasStore((s) => s.unbindCharacterFromShot);
  const syncCharacterToShot = useCanvasStore((s) => s.syncCharacterToShot);
  const setNodeImage = useCanvasStore((s) => s.setNodeImage);
  const canvasLayoutMode = useCanvasStore((s) => s.canvasLayoutMode);
  const setCanvasLayoutMode = useCanvasStore((s) => s.setCanvasLayoutMode);
  const magneticMode = useCanvasStore((s) => s.magneticMode);
  const directorTargetNodeId = useCanvasStore((s) => s.directorTargetNodeId);
  const addVideoReference = useCanvasStore((s) => s.addVideoReference);
  /** 脏版本号：仅在节点/连线实际变更时 +1，替代订阅整个 nodes/edges 数组做 auto-save 触发源 */
  const dirtyVersion = useCanvasStore((s) => s.dirtyVersion);
  /** 高频变化项：从 store 直取，避免 App.tsx 每次 nodes/edges 变化都重渲染并向下传递 */
  const nodes = useCanvasStore((s) => s.nodes);
  const edges = useCanvasStore((s) => s.edges);
  const onNodesChange = useCanvasStore((s) => s.onNodesChange);
  const onEdgesChange = useCanvasStore((s) => s.onEdgesChange);
  const onConnect = useCanvasStore((s) => s.onConnect);
  const exportProjectJSON = useCanvasStore((s) => s.exportProjectJSON);
  const showGrid = useCanvasStore((s) => s.showGrid);

  // ===== 磁吸拖拽 =====
  /** 磁吸相关能力开关：小白模式强制开启磁吸，专业模式按用户开关 */
  const magneticActive = magneticMode || isNovice;
  const {
    onNodeDrag: magNodeDrag,
    onNodeDragStart: magNodeDragStart,
    onNodeDragStop: magNodeDragStop,
    magState,
    draggingId: magDraggingId,
    bondState,
    flash: bondFlash,
    reflowPlan,
  } = useMagneticDrag({
    enabled: magneticActive,
    nodes,
  });

  /** 全画布咬合关系（吸附成功的持久结果），用于渲染咬合缝 */
  const bonds = useMemo(
    () => (magneticActive ? computeBonds(nodes) : []),
    [magneticActive, nodes],
  );

  /** 咬合侧隐形表（磁贴式无缝，2026-09-16 用户裁定）：贴合边透明描边+直角。
   *  与 bonds 同源同周期计算，经 store 下发给 NoviceCard（卡片自身不重复推导）。 */
  const bondedSides = useMemo(
    () => (magneticActive ? bondedSidesMap(nodes) : {}),
    [magneticActive, nodes],
  );
  useEffect(() => {
    useCanvasStore.getState().setBondedSides(bondedSides);
  }, [bondedSides]);

  // ===== 软连接（潜在血缘虚线，不落盘）=====
  const [softConnections, setSoftConnections] = useState<SoftConnection[]>([]);

  /** 拖拽结束：吸附 strong = 咬合（bond）已经表达了连接关系，
   *  2026-09-17 用户裁定「贴合即连接」——不再自动生成软连接虚线/徽章，
   *  此前贴上还画「此节点输出」箭头属双重表达，无感化原则下废除。 */
  const onSoftDragStop = useCallback(
    // 注意：React Flow 的拖拽回调传的是原生 DOM 事件（MouseEvent | TouchEvent），
    // 不是 React.MouseEvent —— 写成 React.MouseEvent 会与 OnNodeDragStop 类型不兼容。
    (event: MouseEvent | TouchEvent, node: Node) => {
      magNodeDragStop(event, node);
    },
    [magNodeDragStop],
  );

  /** 一键固化：把软连接转为正式 edge */
  const onConfirmSoft = useCallback(
    (conn: SoftConnection) => {
      setSoftConnections((list) => removeSoftConnection(list, conn.id));
      // 避免重复连接：已有同向 edge 则仅去掉虚线
      const exists = edges.some(
        (e) => (e.source === conn.sourceId && e.target === conn.targetId),
      );
      if (!exists) {
        onConnect({ source: conn.sourceId, target: conn.targetId, sourceHandle: null, targetHandle: null });
      }
    },
    [edges, onConnect],
  );

  /** 丢弃软连接 */
  const onDismissSoft = useCallback(
    (connId: string) => setSoftConnections((list) => removeSoftConnection(list, connId)),
    [],
  );

  // ===== 画布 Tab bar（多画布快速切换）=====
  const activeProjectId = useCanvasStore((s) => s.activeProjectId);
  const activeCanvasId = useCanvasStore((s) => s.activeCanvasId);
  const listCanvases = useCanvasStore((s) => s.listCanvases);
  const switchCanvas = useCanvasStore((s) => s.switchCanvas);
  const createCanvas = useCanvasStore((s) => s.createCanvas);
  const renameCanvas = useCanvasStore((s) => s.renameCanvas);
  const deleteCanvas = useCanvasStore((s) => s.deleteCanvas);

  // 小白模式不暴露连线：关系由磁吸吸附 / 软连接虚线承载
  const flowEdges = canvasLayoutMode === "flow" && !isNovice ? edges : [];
  const storyboardShots = useMemo(
    () =>
      nodes
        .filter((n) => (n.data as NodeData).kind === "shot")
        .sort((a, b) => a.position.y - b.position.y || a.position.x - b.position.x),
    [nodes],
  );

  useEffect(() => {
    try {
      localStorage.setItem("shiguang-canvas:agent-dock:open", agentPanelOpen ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [agentPanelOpen]);

  const refreshAgentStatus = async () => {
    const ag = await getAgentStatus();
    const on = Boolean(ag.listening || (ag.ok && ag.token));
    setAgentListening(on);
    setAgentUrl(String(ag.url || ""));
    return ag;
  };

  useEffect(() => {
    void refreshAgentStatus();
    const t = window.setInterval(() => {
      void refreshAgentStatus();
    }, 8000);
    return () => window.clearInterval(t);
  }, []);

  // ComfyUI 引擎状态：低频轮询，供顶栏常驻指示点展示；引擎未安装时后端走零网络静态诊断，开销极小
  const refreshComfyEngineStatus = async () => {
    const st = await getComfyEngineStatus();
    setComfyEngineStatus(st);
  };

  useEffect(() => {
    void refreshComfyEngineStatus();
    const t = window.setInterval(() => {
      void refreshComfyEngineStatus();
    }, 10000);
    return () => window.clearInterval(t);
  }, []);

  const selectedCount = nodes.filter((n) => n.selected).length || (selectedData ? 1 : 0);

  const openPaletteAt = (clientX: number, clientY: number) => {
    const flow =
      rfRef.current?.screenToFlowPosition({ x: clientX, y: clientY }) || {
        x: 160,
        y: 120,
      };
    setCtxMenu(null);
    setPalette({ open: true, clientX, clientY, flow });
  };

  useEffect(() => {
    const down = (ev: KeyboardEvent) => {
      if (ev.code === "Space" && viewMode === "canvas") {
        const t = ev.target as HTMLElement | null;
        if (t?.closest?.("input, textarea, select, [contenteditable='true']")) return;
        if (!ev.repeat) setSpacePan(true);
        ev.preventDefault();
      }
    };
    const up = (ev: KeyboardEvent) => {
      if (ev.code === "Space") setSpacePan(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [viewMode]);

  // 使用抽离的键盘快捷键 hook
  useKeyboardShortcuts({
    viewMode,
    paletteOpen: palette.open,
    cmdOpen,
    rfRef,
    lastPointerRef,
    openPaletteAt,
    setCmdOpen,
    setCtxMenu: (v: unknown) => setCtxMenu(v as React.SetStateAction<CtxMenu | null>),
    setAutoSavedAt,
    closeAllPanels: () => {
      setPalette((p) => ({ ...p, open: false }));
      setCmdOpen(false);
    },
    onGroupSelected,
    onGenerate,
    onSendToEditor,
    onBreakdown,
  });

  // 小地图切换监听
  const [showMiniMap, setShowMiniMap] = useState(true);
  useEffect(() => {
    const handler = () => setShowMiniMap((v) => !v);
    window.addEventListener("shiguang:toggle-minimap", handler);
    return () => window.removeEventListener("shiguang:toggle-minimap", handler);
  }, []);

  // 空白粘贴 ComfyUI 工作流：识别剪贴板中的 workflow JSON → 解析 → 落成画布节点
  useEffect(() => {
    const onPaste = (ev: ClipboardEvent) => {
      const text = ev.clipboardData?.getData("text/plain") || "";
      if (!isComfyWorkflowText(text)) return; // 非 ComfyUI 工作流，不拦截
      ev.preventDefault();
      void importComfyWorkflowText(text).then((outcome) => {
        if (!outcome.ok) {
          setStatus(outcome.message);
          return;
        }
        let json: unknown;
        try {
          json = JSON.parse(text.trim());
        } catch {
          json = null;
        }
        const placed = json != null ? applyComfyWorkflow(json) : 0;
        setStatus(placed > 0 ? `已导入 ComfyUI 工作流：${placed} 个节点` : outcome.message);
        if (outcome.engineMissing && outcome.detail) {
          window.alert(`ComfyUI 引擎未安装（节点已铺到画布，生成需引擎）\n\n${outcome.detail}`);
        }
      });
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [setStatus, applyComfyWorkflow]);

  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("blur", close);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("blur", close);
    };
  }, [ctxMenu]);

  // 同步 CanvasToolbar 的 snapGrid 切换
  useEffect(() => {
    const handler = (e: CustomEvent<boolean>) => {
      setSnapGrid(e.detail);
    };
    window.addEventListener("shiguang:snap-grid-change", handler as EventListener);
    return () => window.removeEventListener("shiguang:snap-grid-change", handler as EventListener);
  }, [setSnapGrid]);

  // 自动保存工程（防抖）— 只依赖 dirtyVersion，避免订阅 nodes/edges 数组导致拖拽时频繁触发
  useEffect(() => {
    if (viewMode !== "canvas") return;
    const t = window.setTimeout(() => {
      saveProject({ silent: true });
      setAutoSavedAt(new Date().toLocaleTimeString());
    }, 2500);
    return () => window.clearTimeout(t);
  }, [dirtyVersion, dramaTitle, episode, viewMode, saveProject]);

  const libShowcase = showcaseFromLibrary(6);
  const showcaseItems = (() => {
    const fromNodes = nodes
      .map((n) => {
        const d = n.data as NodeData;
        const cover =
          ("imageUrl" in d && d.imageUrl) ||
          ("posterUrl" in d && d.posterUrl) ||
          ("firstFrameUrl" in d && d.firstFrameUrl) ||
          "";
        if (!cover) return null;
        return {
          id: n.id,
          title: ("title" in d && d.title) || n.id,
          prompt: ("prompt" in d && d.prompt) || ("text" in d && d.text) || "",
          coverUrl: cover,
          tags: [d.kind],
        };
      })
      .filter(Boolean) as {
      id: string;
      title: string;
      prompt: string;
      coverUrl?: string;
      tags?: string[];
    }[];
    if (libShowcase.length > 0) return libShowcase;
    return fromNodes;
  })();

  const assetCount = nodes.filter((n) => {
    const d = n.data as NodeData;
    return Boolean(
      ("imageUrl" in d && d.imageUrl) ||
        ("posterUrl" in d && d.posterUrl) ||
        ("firstFrameUrl" in d && d.firstFrameUrl),
    );
  }).length;

  const navActive: AppRoute =
    viewMode === "canvas" || viewMode === "stage3d"
      ? "projects"
      : (viewMode as AppRoute);

  const canvasCommands: CommandItem[] = useMemo(
    () => [
      { id: "add-node", label: "添加节点", hint: "搜索节点类型", shortcut: "/", keywords: "add node 添加", run: () => openPaletteAt(lastPointerRef.current.clientX, lastPointerRef.current.clientY) },
      { id: "save", label: "保存工程", shortcut: "Ctrl+S", keywords: "save 保存", run: () => { saveProject(); setAutoSavedAt(new Date().toLocaleTimeString()); } },
      { id: "undo", label: "撤销", shortcut: "Ctrl+Z", run: () => undoGraph() },
      { id: "redo", label: "重做", shortcut: "Ctrl+Y", run: () => redoGraph() },
      { id: "copy", label: "复制选中", shortcut: "Ctrl+C", run: () => copySelected() },
      { id: "paste", label: "粘贴", shortcut: "Ctrl+V", run: () => pasteClipboard() },
      { id: "dup", label: "原地复制", shortcut: "Ctrl+D", run: () => duplicateSelected() },
      { id: "select-all", label: "全选", shortcut: "Ctrl+A", run: () => selectAll() },
      { id: "delete", label: "删除选中", shortcut: "Delete", run: () => removeSelected() },
      { id: "group", label: "编组选中", shortcut: "Ctrl+G", keywords: "group 编组", run: () => onGroupSelected() },
      { id: "fit", label: "适配视野", shortcut: "F", keywords: "fit 聚焦", run: () => rfRef.current?.fitView({ padding: 0.18, duration: 220 }) },
      { id: "generate", label: "生成选中节点", shortcut: "Ctrl+Enter", keywords: "generate 生图", run: () => onGenerate() },
      { id: "send", label: "选中入轨", shortcut: "Ctrl+E", keywords: "editor 入轨 剪辑", run: () => onSendToEditor() },
      { id: "send-all", label: "全部入轨", keywords: "editor 入轨", run: () => onSendAllToEditor() },
      { id: "breakdown", label: "一键拉片", keywords: "breakdown 分镜", run: () => onBreakdown() },
      { id: "stage3d", label: "打开 3D 导演台", keywords: "3d stage", run: () => { useCanvasStore.getState().clearDirectorTarget(); setViewMode("stage3d"); } },
      { id: "add-digital-human", label: "添加数字人节点", keywords: "digital human 数字人 tts 配音", run: () => addNode("digitalHuman") },
      { id: "agent", label: "打开 Agent 面板", keywords: "agent 对话", run: () => setAgentPanelOpen(true) },
    ],
    [
      saveProject, undoGraph, redoGraph, copySelected, pasteClipboard, duplicateSelected,
      selectAll, removeSelected, onGroupSelected, onGenerate, onSendToEditor, onSendAllToEditor, onBreakdown, setViewMode,
      addNode,
    ],
  );

  const showWorkspace = viewMode === "canvas";
  const showStage = viewMode === "stage3d" && Boolean(stage3dContent);
  const showImageStudio = viewMode === "image";
  const showVideoStudio = viewMode === "video";
  const showStudio =
    viewMode === "projects" ||
    viewMode === "prompts" ||
    viewMode === "assets" ||
    viewMode === "settings";

  const insertPrompt = (p: LocalPrompt) => {
    onSendStudioToCanvas({ kind: "prompt", title: p.title, text: p.text, prompt: p.text });
  };
  const insertAsset = (a: LocalAsset) => {
    if (a.kind === "video") {
      onSendStudioToCanvas({
        kind: "video",
        title: a.title,
        videoUrl: a.url,
        prompt: a.prompt || "",
      });
    } else if (a.kind === "image") {
      onSendStudioToCanvas({
        kind: "image",
        title: a.title,
        imageUrl: a.url,
        prompt: a.prompt || "",
      });
    } else {
      onSendStudioToCanvas({ kind: "prompt", title: a.title, text: a.prompt || a.title });
    }
  };

  // 顶栏「引擎状态」指示点派生值：区分 在线/待拉起/未安装/检测中 四态
  const comfyEngineState: "ready" | "installed" | "missing" | "unknown" = (() => {
    if (!comfyEngineStatus) return "unknown";
    if (comfyEngineStatus.diagnose.available) return "ready";
    if (comfyEngineStatus.engine_valid) return "installed";
    return "missing";
  })();
  const comfyEngineLabel: Record<string, string> = {
    ready: "引擎在线",
    installed: "引擎待拉起",
    missing: "引擎未安装",
    unknown: "引擎检测中",
  };

  return (
    <div className="shell">
      <AppNav
        active={navActive}
        onNavigate={(id) => setViewMode(id as ViewMode)}
        version={CANVAS_VERSION_LABEL}
        versionTitle={CANVAS_VERSION_TITLE}
        tier={editorTier}
        onTierChange={(t: CanvasTier) => setEditorTier(t)}
      />

      {viewMode === "home" ? (
        <HomeLanding
          onStart={() => setViewMode("canvas")}
          onOpenCanvas={() => setViewMode("canvas")}
          onViewPrompts={() => setViewMode("prompts")}
          showcase={showcaseItems}
        />
      ) : null}

      {showImageStudio ? (
        <Suspense fallback={<PanelFallback label="图片工作室" />}>
          <ImageStudio
            onOpenCanvas={() => setViewMode("canvas")}
            onSyncModels={onSyncModels}
            onSendToCanvas={(p) => onSendStudioToCanvas(p)}
          />
        </Suspense>
      ) : null}

      {showVideoStudio ? (
        <Suspense fallback={<PanelFallback label="视频工作室" />}>
          <VideoStudio
            onOpenCanvas={() => setViewMode("canvas")}
            onSyncModels={onSyncModels}
            onSendToCanvas={(p) => onSendStudioToCanvas(p)}
          />
        </Suspense>
      ) : null}

      {showStudio ? (
        <Suspense fallback={<PanelFallback label="工作室页" />}>
          <StudioPage
            route={viewMode}
            onOpenCanvas={() => setViewMode("canvas")}
            onOpenStage3d={() => {
              useCanvasStore.getState().clearDirectorTarget();
              setViewMode("stage3d");
            }}
            onSyncModels={onSyncModels}
            templateCount={templates.length}
            assetCount={assetCount}
            status={status}
            onInsertPrompt={insertPrompt}
            onInsertAsset={insertAsset}
          />
        </Suspense>
      ) : null}

      {showStage ? (
        <>
          <header className="topbar subbar">
            <div className="seg">
              <button type="button" onClick={() => setViewMode("canvas")}>
                画布
              </button>
              <button type="button" className="on">
                3D 导演台
              </button>
            </div>
            <div className="spacer" />
            <div className="chip">
              {directorTargetNodeId
                ? "截图回写 · 已绑定导演台节点"
                : prefs.active_provider_label || prefs.active_provider || "未同步"}
              {prefs.character_name ? ` · ${prefs.character_name}` : ""}
            </div>
          </header>
          {stage3dContent}
        </>
      ) : null}

      {showWorkspace ? (
        <>
      <header className="topbar subbar libtv-topbar">
        <div className="libtv-top-left">
          <span className="libtv-logo" title="拾光导演台">
            ⟦⟧
          </span>
          <WorkspaceCanvasMenus />
          <button
            type="button"
            className="libtv-icon-btn"
            title="节点连线"
            onClick={() => openPaletteAt(lastPointerRef.current.clientX, lastPointerRef.current.clientY)}
          >
            ⚭
          </button>
          <button
            type="button"
            className="libtv-icon-btn"
            title="指令面板 Ctrl+K"
            onClick={() => setCmdOpen(true)}
          >
            ⌘
          </button>
          <button
            type="button"
            className="libtv-icon-btn"
            title="侧栏"
            onClick={() => {
              setLeftCollapsed((v) => !v);
              setRightCollapsed((v) => !v);
            }}
          >
            ▥
          </button>
        </div>
        <div className="seg">
          <button type="button" className="on" onClick={() => setViewMode("canvas")}>
            画布
          </button>
          <button type="button" onClick={() => {
            useCanvasStore.getState().clearDirectorTarget();
            setViewMode("stage3d");
          }}>
            3D 导演台
          </button>
        </div>
        {isNovice ? (
          <div className="chip" title="小白模式：拖卡片靠近就吸附成关系，拉开即解除">
            小白模式 · 磁吸意图画布
          </div>
        ) : (
          <div className="seg canvas-layout-seg" title="视图模式">
            {(["flow", "simple", "storyboard"] as CanvasLayoutMode[]).map((m) => (
              <button
                key={m}
                type="button"
                className={canvasLayoutMode === m ? "on" : ""}
                onClick={() => {
                  setCanvasLayoutMode(m);
                  if (m !== "flow") setRightCollapsed(false);
                }}
              >
                {m === "flow" ? "节点" : m === "simple" ? "表单" : "分镜条"}
              </button>
            ))}
          </div>
        )}
        <div className="spacer" />
        <div className="libtv-top-right">
          <span
            className="libtv-engine-dot"
            title={
              comfyEngineStatus
                ? comfyEngineStatus.diagnose.suggestion || comfyEngineStatus.diagnose.error || "内置 ComfyUI 引擎"
                : "正在检测内置 ComfyUI 引擎状态…"
            }
            role="button"
            onClick={() => void refreshComfyEngineStatus()}
          >
            <i className={`libtv-engine-dot-core ${comfyEngineState}`} />
            {comfyEngineLabel[comfyEngineState]}
          </span>
          <div className="chip" title="来自剪辑时间线快照">
            剪辑 {editorClipCount} 片 · {prefs.active_provider_label || prefs.active_provider || "未同步"}
          </div>
          <button
            type="button"
            className={`libtv-agent-btn${agentPanelOpen ? " on" : ""}`}
            onClick={() => setAgentPanelOpen((v) => !v)}
          >
            💬 Agent
          </button>
          <div className="libtv-more-wrap">
            <button type="button" className="libtv-icon-btn" onClick={() => setMoreOpen((v) => !v)}>
              ☰
            </button>
            {moreOpen ? (
              <div className="libtv-more-menu" onMouseLeave={() => setMoreOpen(false)}>
                <button type="button" onClick={() => { undoGraph(); setMoreOpen(false); }}>撤销</button>
                <button type="button" onClick={() => { onGenerate(); setMoreOpen(false); }} disabled={generating}>
                  {generating ? "生成中…" : "生成选中"}
                </button>
                <button type="button" onClick={() => { onSendToEditor(); setMoreOpen(false); }}>入轨</button>
                <button type="button" onClick={() => { onSyncModels(); setMoreOpen(false); }}>同步模型</button>
                <button type="button" onClick={() => { onExportZip(); setMoreOpen(false); }}>导出 ZIP</button>
                <button type="button" onClick={() => { setViewMode("settings"); setMoreOpen(false); }}>模型/Agent</button>
                <button type="button" onClick={() => {
                  (window as any).__shiguangShowBridgePanel?.();
                  setMoreOpen(false);
                }}>拾光面板</button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

        {activeProjectId ? (
          <div className="canvas-tab-bar">
            <div className="canvas-tabs">
              {listCanvases().map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`canvas-tab${c.id === activeCanvasId ? " on" : ""}`}
                  onClick={() => switchCanvas(c.id)}
                  onDoubleClick={() => {
                    const name = window.prompt("重命名画布", c.name);
                    if (name && name.trim()) renameCanvas(c.id, name.trim());
                  }}
                  title={`${c.name} · ${c.nodeCount} 节点`}
                >
                  <span className="canvas-tab-name">{c.name}</span>
                  <span className="canvas-tab-count">{c.nodeCount}</span>
                  <span
                    className="canvas-tab-close"
                    role="button"
                    aria-label="删除画布"
                    onClick={(e) => {
                      e.stopPropagation();
                      const canvases = listCanvases();
                      if (canvases.length <= 1) {
                        setStatus?.("至少保留一个画布");
                        return;
                      }
                      if (window.confirm(`删除画布「${c.name}」？`)) deleteCanvas(c.id);
                    }}
                  >
                    ×
                  </span>
                </button>
              ))}
              <button
                type="button"
                className="canvas-tab canvas-tab-add"
                title="新建画布"
                onClick={() => {
                  const canvases = listCanvases();
                  const name = window.prompt("新建画布名称", `画布 ${canvases.length + 1}`);
                  createCanvas(name || undefined);
                }}
              >
                +
              </button>
            </div>
          </div>
        ) : null}

        <div
          className={`workspace${leftCollapsed ? " left-collapsed" : ""}${rightCollapsed ? " right-collapsed" : ""}${agentPanelOpen ? " agent-open" : ""}${spacePan ? " space-pan" : ""}`}
        >
          <aside className={`sidebar${leftCollapsed ? " collapsed" : ""}`}>
            {leftCollapsed ? null : (
            <>
            <details className="panel" open>
              <summary>节点列表</summary>
              <div className="panel-body node-locator">
                {nodes.map((n) => {
                  const d = n.data as NodeData;
                  const title =
                    ("title" in d && d.title) ||
                    ("content" in d && String(d.content || "").slice(0, 12)) ||
                    ("text" in d && String(d.text || "").slice(0, 12)) ||
                    n.id;
                  return (
                    <button
                      key={n.id}
                      type="button"
                      className={`node-locator-item${selectedId === n.id ? " on" : ""}`}
                      onClick={() => {
                        useCanvasStore.getState().setSelected(n.id);
                        rfRef.current?.fitView({
                          nodes: [{ id: n.id }],
                          padding: 0.4,
                          duration: 200,
                        });
                      }}
                    >
                      <span className="muted">{d.kind}</span> {title}
                    </button>
                  );
                })}
              </div>
            </details>
            <details className="panel" open>
              <summary>添加节点</summary>
              <div className="panel-body">
                <p className="muted" style={{ margin: "0 0 8px", fontSize: 11 }}>
                  双击空白或按 <kbd>/</kbd> 搜索添加；也可把下方按钮<strong>拖到画布</strong>
                </p>
                <div className="btn-row">
                  {addNodeItems.map((it) => (
                    <button
                      key={it.type}
                      className="btn"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("application/shiguang-node", it.type);
                        e.dataTransfer.effectAllowed = "copy";
                      }}
                      onClick={() => pickNodeByType(it.type)}
                    >
                      {it.label}
                    </button>
                  ))}
                </div>
                <div className="btn-row">
                  <button className="btn" onClick={duplicateSelected} disabled={!selectedData}>
                    复制选中
                  </button>
                  <button className="btn danger" onClick={removeSelected} disabled={!selectedData}>
                    删除选中
                  </button>
                </div>
                <div className="btn-row">
                  <button className="btn" onClick={undoGraph}>
                    撤销
                  </button>
                  <button className="btn" onClick={redoGraph}>
                    重做
                  </button>
                </div>
                <button
                  className="btn"
                  onClick={() =>
                    openPaletteAt(lastPointerRef.current.clientX, lastPointerRef.current.clientY)
                  }
                >
                  搜索添加节点…
                </button>
                <label className="btn teal" style={{ cursor: "pointer" }} title="上传本地视频作参考片段">
                  + 参考视频
                  <input
                    type="file"
                    accept="video/*"
                    hidden
                    onChange={async (e) => {
                      const f = e.target.files?.[0];
                      e.target.value = "";
                      if (!f) return;
                      const res = await resolveMediaUrl(f);
                      if (!res.ok || !res.url) {
                        setStatus(res.message || "参考视频上传失败");
                        return;
                      }
                      addVideoReference(res.url, { title: `参考·${f.name}`, name: f.name });
                      setStatus(res.message || `已添加参考视频 ${f.name}`);
                    }}
                  />
                </label>
                <button className="btn primary" onClick={() => addStoryboardGrid(9)}>
                  九宫格
                </button>
                <button className="btn" onClick={() => addStoryboardGrid(25)}>
                  二十五宫格
                </button>
                <button className="btn teal" onClick={addThreeView}>
                  角色三视图
                </button>
                <button className="btn" onClick={() => {
                  useCanvasStore.getState().clearDirectorTarget();
                  setViewMode("stage3d");
                }}>
                  打开 3D 导演台
                </button>
              </div>
            </details>

            <details className="panel">
              <summary>插件管理</summary>
              <div className="panel-body">
                <Suspense fallback={<PanelFallback label="插件管理" />}>
                  <PluginManagerPanel onStatus={setStatus} />
                </Suspense>
              </div>
            </details>

            <details className="panel" open>
              <summary>提示词库</summary>
              <div className="panel-body">
                <Suspense fallback={<PanelFallback label="提示词库" />}>
                  <PromptLibraryPanel
                    onApply={onApplyPromptLibrary}
                    onStatus={(msg) => {
                      const el = document.getElementById("sg-status");
                      if (el) el.textContent = msg;
                    }}
                  />
                </Suspense>
              </div>
            </details>

            <details className="panel">
              <summary>变体 / 拉片</summary>
              <div className="panel-body">
                <div className="btn-row">
                  <button className="btn" onClick={() => addVariants("表情", 3)}>
                    表情×3
                  </button>
                  <button className="btn" onClick={() => addVariants("服装", 3)}>
                    服装×3
                  </button>
                </div>
                <button className="btn" onClick={() => addVariants("背景", 3)}>
                  背景×3
                </button>
                <div className="field">
                  <label>拉片文本</label>
                  <textarea
                    value={breakdownDraft}
                    onChange={(e) => setBreakdownDraft(e.target.value)}
                    placeholder="粘贴剧本，或用选中剧本节点"
                    rows={3}
                  />
                </div>
                <button className="btn primary" onClick={onBreakdown} disabled={breaking}>
                  {breaking ? "拉片中…" : "一键拉片"}
                </button>
              </div>
            </details>

            <details className="panel" open>
              <summary>生成 / 入轨</summary>
              <div className="panel-body">
                <div className="field">
                  <label>生图模型</label>
                  <ModelSelector
                    models={imageModels}
                    value={selectedModelKey}
                    onChange={setSelectedModelKey}
                    placeholder={imageModels.length === 0 ? "请先同步模型池" : "选择生图模型"}
                    disabled={imageModels.length === 0}
                    persistKey="shiguang-canvas:model:image"
                  />
                </div>
                <div className="field">
                  <label>生视频模型</label>
                  <ModelSelector
                    models={videoModels}
                    value={selectedVideoModelKey}
                    onChange={setSelectedVideoModelKey}
                    placeholder={videoModels.length === 0 ? "无视频模型" : "选择视频模型"}
                    disabled={videoModels.length === 0}
                    persistKey="shiguang-canvas:model:video"
                  />
                </div>
                <div className="field">
                  <label>TTS 模型</label>
                  <ModelSelector
                    models={audioModels}
                    value={selectedAudioModelKey}
                    onChange={setSelectedAudioModelKey}
                    placeholder={audioModels.length === 0 ? "无 TTS 模型（走本地 edge-tts 降级）" : "选择 TTS 模型"}
                    disabled={audioModels.length === 0}
                    persistKey="shiguang-canvas:model:audio"
                  />
                </div>
                <div className="field">
                  <label>对比模型（TapNow 式 A/B）</label>
                  <select
                    value={compareModelKey}
                    onChange={(e) => setCompareModelKey(e.target.value)}
                  >
                    {imageModels.length < 2 ? (
                      <option value="">需至少 2 个生图模型</option>
                    ) : (
                      imageModels.map((m) => (
                        <option
                          key={`cmp_${m.channel_id}::${m.model}`}
                          value={`${m.channel_id}::${m.model}`}
                        >
                          {m.label}
                        </option>
                      ))
                    )}
                  </select>
                </div>
                <div className="field">
                  <label>对比视频模型</label>
                  <select
                    value={compareVideoModelKey}
                    onChange={(e) => setCompareVideoModelKey(e.target.value)}
                  >
                    {videoModels.length < 2 ? (
                      <option value="">需至少 2 个视频模型</option>
                    ) : (
                      videoModels.map((m) => (
                        <option
                          key={`vcmp_${m.channel_id}::${m.model}`}
                          value={`${m.channel_id}::${m.model}`}
                        >
                          {m.label}
                        </option>
                      ))
                    )}
                  </select>
                </div>
                <button className="btn primary" onClick={onGenerate} disabled={generating}>
                  {generating
                    ? "生成中…"
                    : selectedData?.kind === "video"
                      ? "生成选中视频"
                      : selectedData?.kind === "digitalHuman"
                        ? "生成配音"
                        : "生成选中"}
                </button>
                <button
                  className="btn"
                  onClick={onCompareGenerate}
                  disabled={
                    generating ||
                    (selectedData?.kind === "video"
                      ? videoModels.length < 2 || !compareVideoModelKey
                      : selectedData?.kind === "shot" || selectedData?.kind === "image"
                        ? imageModels.length < 2 || !compareModelKey
                        : true)
                  }
                >
                  双模型对比
                </button>
                <button
                  className="btn"
                  onClick={onMultiAngleGenerate}
                  disabled={generating || selectedData?.kind !== "shot"}
                >
                  多角度预览
                </button>
                <button className="btn" onClick={onBatchGenerate} disabled={generating}>
                  批量生成
                </button>
                <button
                  className="btn"
                  onClick={onRunToHere}
                  disabled={generating}
                  title="先出执行计划（不消耗额度），确认后按依赖顺序整图执行；Ctrl+Shift+Enter"
                >
                  运行到此处
                </button>
                {generating ? (
                  <button className="btn" onClick={onAbortBatch}>
                    中断
                  </button>
                ) : null}
                <div className="btn-row">
                  <button className="btn" onClick={onSendToEditor}>
                    入轨
                  </button>
                  <button className="btn" onClick={onSendAllToEditor} disabled={generating}>
                    全部入轨
                  </button>
                </div>
                <button className="btn teal" onClick={onSyncModels}>
                  同步模型池
                </button>
              </div>
            </details>

            <details className="panel">
              <summary>工程</summary>
              <div className="panel-body">
                <div className="btn-row">
                  <button className="btn" onClick={() => saveProject()}>
                    保存
                  </button>
                  <button className="btn" onClick={() => loadProject()}>
                    加载
                  </button>
                </div>
                <button className="btn" onClick={onExportStoryboard}>
                  导出分镜
                </button>
                <button className="btn" onClick={onExportSkill}>
                  导出 Skill 包
                </button>
                <label className="btn" style={{ cursor: "pointer", textAlign: "center" }}>
                  导入 Skill…
                  <input
                    type="file"
                    accept="application/json,.json"
                    hidden
                    ref={skillImportRef}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = "";
                      if (f) void onImportSkill(f);
                    }}
                  />
                </label>
                <button
                  className="btn"
                  onClick={() => {
                    const name = window.prompt("模板名称", "漫剧分镜工作流");
                    if (!name) return;
                    saveTemplate(name);
                    refreshTemplates();
                  }}
                >
                  存为模板
                </button>
                {templates.map((t) => (
                  <div key={t.id} className="row" style={{ gap: 4, marginBottom: 4 }}>
                    <button className="btn" style={{ flex: 1 }} onClick={() => loadTemplate(t.id)}>
                      {t.name}
                    </button>
                    <button
                      className="btn"
                      onClick={() => {
                        deleteTemplate(t.id);
                        refreshTemplates();
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </details>
            </>
            )}
          </aside>

          <div
            className="canvas-wrap"
            onPointerMove={(e) => {
              lastPointerRef.current = { clientX: e.clientX, clientY: e.clientY };
            }}
            onDragOver={(e) => {
              if (e.dataTransfer.types.includes("application/shiguang-node")) {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
              }
            }}
            onDrop={(e) => {
              const nodeType = e.dataTransfer.getData("application/shiguang-node");
              if (!nodeType) return;
              e.preventDefault();
              const flow =
                rfRef.current?.screenToFlowPosition({ x: e.clientX, y: e.clientY }) || {
                  x: 160,
                  y: 120,
                };
              pickNodeByType(nodeType, flow);
            }}
          >
            <ReactFlow
              nodes={nodes}
              edges={flowEdges}
              className={[
                canvasLayoutMode !== "flow" && !isNovice ? "canvas-simple-edges-off" : "",
                zoomPct < 60 ? "zoomed-out" : "",
              ].filter(Boolean).join(" ") || undefined}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectEnd={(event, conn) => {
                if (conn.toNode || conn.toHandle) return;
                const from = conn.fromNode;
                if (!from) return;
                const point =
                  "changedTouches" in event
                    ? event.changedTouches[0]
                    : (event as MouseEvent);
                if (!point) return;
                const flow =
                  rfRef.current?.screenToFlowPosition({
                    x: point.clientX,
                    y: point.clientY,
                  }) || { x: 120, y: 80 };
                setPalette((p) => ({ ...p, open: false }));
                setCtxMenu({
                  mode: "connect",
                  clientX: point.clientX,
                  clientY: point.clientY,
                  flow,
                  sourceId: from.id,
                  sourceHandle: conn.fromHandle?.id || undefined,
                });
              }}
              onSelectionChange={onSelectionChange}
              onInit={(inst) => {
                rfRef.current = inst;
                inst.fitView({ padding: 0.2 });
                setZoomPct(Math.round(inst.getZoom() * 100));
              }}
              onMoveEnd={(_, vp) => setZoomPct(Math.round(vp.zoom * 100))}
              onNodeDragStart={(e, n) => {
                // 磁吸 Hook 需要拖拽开始时的咬合快照，之后再进入常规的图编辑事务
                magNodeDragStart(e, n);
                beginGraphEdit();
              }}
              onNodeDrag={magNodeDrag}
              onNodeDragStop={onSoftDragStop}
              onPaneClick={(e) => {
                setCtxMenu(null);
                setPalette((p) => ({ ...p, open: false }));
                if (e.detail === 2) {
                  openPaletteAt(e.clientX, e.clientY);
                }
              }}
              onPaneContextMenu={(e) => {
                e.preventDefault();
                const flow =
                  rfRef.current?.screenToFlowPosition({ x: e.clientX, y: e.clientY }) || {
                    x: 120,
                    y: 80,
                  };
                setPalette((p) => ({ ...p, open: false }));
                setCtxMenu({
                  mode: "pane",
                  clientX: e.clientX,
                  clientY: e.clientY,
                  flow,
                });
              }}
              onNodeContextMenu={(e, node) => {
                e.preventDefault();
                e.stopPropagation();
                onSelectionChange({ nodes: [node] });
                setPalette((p) => ({ ...p, open: false }));
                setCtxMenu({
                  mode: "node",
                  clientX: e.clientX,
                  clientY: e.clientY,
                  nodeId: node.id,
                });
              }}
              onEdgeContextMenu={(e, edge) => {
                e.preventDefault();
                e.stopPropagation();
                setPalette((p) => ({ ...p, open: false }));
                setCtxMenu({
                  mode: "edge",
                  clientX: e.clientX,
                  clientY: e.clientY,
                  edgeId: edge.id,
                });
              }}
              onlyRenderVisibleElements
              nodeTypes={shellNodeTypes}
              minZoom={0.15}
              maxZoom={2.5}
              deleteKeyCode={null}
              multiSelectionKeyCode="Shift"
              selectionOnDrag={!spacePan}
              panOnDrag={spacePan ? true : [1]}
              panOnScroll
              zoomOnScroll
              /* 小白模式关闭 16px 网格吸附：卡片位置会被量化成 16 的整数倍，
                 导致「分离拉力」变成台阶式跳变、失去阻力的细腻手感。
                 小白的对齐由磁吸贴合（gap=0）负责，不需要网格。 */
              snapToGrid={isNovice ? false : snapGrid}
              snapGrid={[16, 16]}
              proOptions={{ hideAttribution: true }}
              colorMode="dark"
            >
              {showGrid ? (
              <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1a2433" />
            ) : null}
              {showMiniMap ? <MiniMap pannable zoomable /> : null}
              <Controls />
              <CanvasToolbar />
              {/* 咬合缝：吸附成功的持久提示（已吸附 / 拉伸中 / 即将断开 + 落座闪光） */}
              {magneticActive ? (
                <SnapSeam bonds={bonds} bondState={bondState} flash={bondFlash} />
              ) : null}
              {magneticActive && magState.level !== "none" ? (
                <MagneticLines
                  nodes={nodes}
                  magState={magState}
                  draggingId={magDraggingId}
                />
              ) : null}
              {/* 整列让位坑位预览（2026-09-18 借鉴手机主屏手感 · 第 2 条机制）：
                  拖拽中被挡住的同行/列卡片会让开，这里预告拖拽卡将占住的坑位。
                  仅预览，真实位移在松手时统一执行。 */}
              {magneticActive ? <SlotGhost plan={reflowPlan} /> : null}
              {/* 软连接（潜在血缘虚线 + 一键固化） */}
              {magneticActive ? (
                <SoftConnectionLines
                  nodes={nodes}
                  connections={softConnections}
                  onConfirm={onConfirmSoft}
                  onDismiss={onDismissSoft}
                />
              ) : null}
              {/* 节点状态徽标 + 层叠徽章：所有卡片可见（spec 4.1 状态灯 / 4.5 层数） */}
              {nodes.map((node) => {
                const stack = node.data.stack as import("./magnetic/types").CardStackData | undefined;
                if (!stack || stack.layers.length === 0) return null;
                const activeLayer = stack.layers.find((l) => l.id === stack.activeLayerId);
                const showStack = stack.layers.length > 1;
                return (
                  <div key={`overlay_${node.id}`}>
                    {activeLayer ? (
                      <div
                        style={{
                          position: "absolute",
                          transform: `translate(${node.position.x}px, ${node.position.y}px)`,
                          pointerEvents: "none",
                        }}
                      >
                        <StatusBadge status={activeLayer.status} qualityScore={activeLayer.qualityScore} />
                      </div>
                    ) : null}
                    {showStack ? <StackBadge nodeId={node.id} stack={stack} /> : null}
                  </div>
                );
              })}
              {/* 浮动工具条 */}
              {selectedId ? (() => {
                const node = nodes.find((n) => n.id === selectedId);
                if (!node) return null;
                return (
                  <FloatingToolbar
                    nodeId={selectedId}
                    nodeX={node.position.x}
                    nodeY={node.position.y}
                    nodeWidth={(node.width || 280) as number}
                    onSendToEditor={onSendToEditor}
                  />
                );
              })() : null}
            </ReactFlow>
            {nodes.length === 0 ? (
              <CanvasEmptyState />
            ) : null}
            {canvasLayoutMode === "storyboard" && storyboardShots.length > 0 ? (
              <div className="storyboard-strip" aria-label="分镜时间条">
                {storyboardShots.map((n, i) => {
                  const d = n.data as Extract<NodeData, { kind: "shot" }>;
                  return (
                    <button
                      key={n.id}
                      type="button"
                      className={`storyboard-strip-item${selectedId === n.id ? " on" : ""}`}
                      onClick={() => {
                        useCanvasStore.getState().setSelected(n.id);
                        rfRef.current?.fitView({
                          nodes: [{ id: n.id }],
                          padding: 0.55,
                          duration: 220,
                        });
                      }}
                    >
                      <span className="idx">{String(i + 1).padStart(2, "0")}</span>
                      {d.imageUrl ? (
                        <img src={d.imageUrl} alt="" />
                      ) : (
                        <span className="ph">待生成</span>
                      )}
                      <span className="cap">{d.title || `镜 ${i + 1}`}</span>
                      <span className="meta">{d.shotSize} · {d.duration}s</span>
                    </button>
                  );
                })}
              </div>
            ) : null}
            <LibTvBottomDock
              zoomPct={zoomPct}
              onAdd={() =>
                openPaletteAt(lastPointerRef.current.clientX, lastPointerRef.current.clientY)
              }
              onAssets={() => setViewMode("assets")}
              onZoomFit={() => rfRef.current?.fitView({ padding: 0.2 })}
              onHelp={() => setCmdOpen(true)}
              onRole={() => {
                addThreeView();
                setStatus("已创建角色三视图（正面 / 侧面 / 背面）");
              }}
              onConnect={() => {
                // 自动连线：按 y 坐标分层，把同层无出边节点连到下一层无入边节点
                const ns = nodes;
                if (ns.length < 2) { setStatus("至少需要 2 个节点才能自动连线"); return; }
                const existing = new Set(edges.map((e) => `${e.source}→${e.target}`));
                // 按 y 坐标近似分层（差值 < 80 算同一层）
                const sorted = [...ns].sort((a, b) => (a.position.y + a.position.x * 0.1) - (b.position.y + b.position.x * 0.1));
                let connected = 0;
                // shot 节点优先按 x 顺序连（分镜序列）
                const shots = sorted.filter((n) => (n.data as NodeData).kind === "shot");
                if (shots.length >= 2) {
                  for (let i = 0; i < shots.length - 1; i++) {
                    const key = `${shots[i].id}→${shots[i + 1].id}`;
                    if (!existing.has(key)) {
                      onConnect({ source: shots[i].id, target: shots[i + 1].id, sourceHandle: null, targetHandle: null });
                      existing.add(key);
                      connected++;
                    }
                  }
                }
                // 剩余节点按位置顺序连
                const rest = sorted.filter((n) => (n.data as NodeData).kind !== "shot");
                for (let i = 0; i < rest.length - 1; i++) {
                  const key = `${rest[i].id}→${rest[i + 1].id}`;
                  if (!existing.has(key)) {
                    onConnect({ source: rest[i].id, target: rest[i + 1].id, sourceHandle: null, targetHandle: null });
                    existing.add(key);
                    connected++;
                  }
                }
                setStatus(connected > 0 ? `自动完成 ${connected} 条连线` : "所有节点已存在连线");
              }}
              onSend={() => {
                if (!selectedId && !selectedData) { setStatus("请先选中至少一个节点再发送"); return; }
                onSendToEditor();
              }}
              onShare={async () => {
                const json = exportProjectJSON();
                if (!json) { setStatus("导出失败：工程数据为空"); return; }
                try {
                  await navigator.clipboard.writeText(json);
                  setStatus("已复制工程 JSON 到剪贴板");
                } catch {
                  // fallback：用临时 textarea
                  const ta = document.createElement("textarea");
                  ta.value = json;
                  document.body.appendChild(ta);
                  ta.select();
                  document.execCommand("copy");
                  document.body.removeChild(ta);
                  setStatus("已复制工程 JSON 到剪贴板");
                }
              }}
              onBranch={() => {
                if (!selectedId) { setStatus("请先选中一个节点再分支"); return; }
                duplicateSelected();
                setStatus("已从选中节点复制分支（原地复制）");
              }}
              onPreview={() => {
                // 简单的预览：先 fitView 展示全貌，提示后续做真正的节点连线时序预览
                rfRef.current?.fitView({ padding: 0.2 });
                setStatus("预览模式：已聚焦全部节点 · 后续版本将支持节点连线时序播放");
              }}
              onHistory={() => {
                // 简单展示：用 window.alert 列出可用的撤销步数
                const past = getGraphPast().length;
                const future = getGraphFuture().length;
                setStatus(`历史栈：可撤销 ${past} 步，可重做 ${future} 步（Ctrl+Z / Ctrl+Y）`);
              }}
              onGallery={() => {
                // 图库预览：统计当前画布的图片数量
                const images = nodes.filter((n) => (n.data as NodeData).kind === "image");
                const videos = nodes.filter((n) => (n.data as NodeData).kind === "video");
                setStatus(`当前画布含 ${images.length} 张图片节点 · ${videos.length} 个视频节点 · 后续版本将支持缩略图网格浏览`);
              }}
            />
            <input
              ref={uploadRef}
              type="file"
              accept="image/*,video/*,audio/*"
              hidden
              onChange={async (e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (!f) return;
                const flow =
                  rfRef.current?.screenToFlowPosition({
                    x: lastPointerRef.current.clientX,
                    y: lastPointerRef.current.clientY,
                  }) || { x: 160, y: 120 };
                if (f.type.startsWith("image/")) {
                  const res = await resolveMediaUrl(f);
                  if (!res.ok || !res.url) {
                    setStatus(res.message || "上传图片失败");
                    return;
                  }
                  addNode("image", flow);
                  setNodeImage(useCanvasStore.getState().selectedId!, res.url);
                  setStatus(`已添加图片节点 · ${f.name}`);
                } else if (f.type.startsWith("video/")) {
                  const res = await resolveMediaUrl(f);
                  if (res.ok && res.url) {
                    addNode("video", flow);
                    const id = useCanvasStore.getState().selectedId;
                    if (id) useCanvasStore.getState().setNodeVideo(id, res.url);
                    setStatus(`已添加视频节点 · ${f.name}`);
                  } else {
                    setStatus(res.message || "上传视频失败");
                  }
                } else {
                  const res = await resolveMediaUrl(f);
                  if (!res.ok || !res.url) {
                    setStatus(res.message || "上传音频失败");
                    return;
                  }
                  addNode("audio", flow);
                  const id = useCanvasStore.getState().selectedId;
                  if (id) useCanvasStore.getState().setNodeAudio(id, res.url);
                  setStatus(`已添加音频节点 · ${f.name}`);
                }
              }}
            />
            {selectedCount > 0 ? (
              <MultiSelectToolbar onGenerate={onGenerate} />
            ) : null}
            {selectedCount > 0 && selectedCount < 2 ? (
              <div className="sel-toolbar">
                <span className="sel-toolbar-count">已选 {selectedCount}</span>
                <button type="button" className="btn primary" onClick={onGenerate} disabled={generating}>
                  生成
                </button>
                <button type="button" className="btn" onClick={onSendToEditor}>
                  入轨
                </button>
                <button type="button" className="btn danger" onClick={removeSelected}>
                  删除
                </button>
              </div>
            ) : null}
            <NodePalette
              open={palette.open}
              x={palette.clientX}
              y={palette.clientY}
              onClose={() => setPalette((p) => ({ ...p, open: false }))}
              onPick={(type) => pickNodeByType(type, palette.flow)}
            />
            <CommandPalette
              open={cmdOpen}
              title="导演台指令"
              items={canvasCommands}
              onClose={() => setCmdOpen(false)}
            />
            {ctxMenu ? (
              <CanvasContextMenu
                menu={ctxMenu}
                onClose={() => setCtxMenu(null)}
                onOpenStage3d={() => {
                  useCanvasStore.getState().clearDirectorTarget();
                  setViewMode("stage3d");
                }}
                onBreakdown={onBreakdown}
              />
            ) : null}
          </div>

          {!agentPanelOpen ? (
          <aside className={`inspector${rightCollapsed ? " collapsed" : ""}`}>
            {rightCollapsed ? null : isNovice ? (
              <NoviceInspector />
            ) : (
            <>
            <div className="section-title">项目</div>
            <div className="field">
              <label>剧名</label>
              <input
                value={dramaTitle}
                onChange={(e) => setMeta(e.target.value, episode)}
                placeholder="漫剧名"
              />
            </div>
            <div className="field">
              <label>集数</label>
              <input
                value={episode}
                onChange={(e) => setMeta(dramaTitle, e.target.value)}
                placeholder="01"
              />
            </div>
            <div className="section-title">选中节点</div>
            {!selectedData ? (
              <div className="muted">
                {canvasLayoutMode === "simple"
                  ? "简化表单：选镜头节点编辑提示词/机位，点「生成选中」"
                  : "点击画布节点编辑；空白处右键可添加"}
              </div>
            ) : (
              <>
                <div className="btn-row" style={{ marginBottom: 8 }}>
                  <button type="button" className="btn" onClick={duplicateSelected}>
                    复制
                  </button>
                  <button type="button" className="btn danger" onClick={removeSelected}>
                    删除
                  </button>
                </div>
                {"title" in selectedData && (
                  <div className="field">
                    <label>标题</label>
                    <input
                      value={(selectedData as { title?: string }).title || ""}
                      onChange={(e) => updateSelectedData({ title: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "shot" && (
                  <>
                    {/* ====== 导演级参数降维 ====== */}
                    <div className="field">
                      <label>🎬 质量档位</label>
                      <div style={{ display: "flex", gap: 4 }}>
                        {[
                          { key: "draft", label: "草稿", desc: "快出效果" },
                          { key: "standard", label: "标准", desc: "平衡" },
                          { key: "fine", label: "精修", desc: "细节优先" },
                          { key: "cinema", label: "电影级", desc: "最高质量" },
                        ].map((q) => {
                          const current = (selectedData as any).qualityTier || "standard";
                          const active = current === q.key;
                          return (
                            <button
                              key={q.key}
                              type="button"
                              onClick={() => updateSelectedData({ qualityTier: q.key })}
                              style={{
                                flex: 1,
                                padding: "8px 4px",
                                border: active ? "1px solid #c084fc" : "1px solid #2a2f42",
                                borderRadius: 8,
                                background: active
                                  ? "linear-gradient(135deg, rgba(192,132,252,0.2), rgba(168,85,247,0.15))"
                                  : "#161922",
                                color: active ? "#e9d5ff" : "#94a3b8",
                                cursor: "pointer",
                                fontSize: 11,
                                fontWeight: active ? 600 : 400,
                                transition: "all 0.15s",
                              }}
                              title={q.desc}
                            >
                              {q.label}
                            </button>
                          );
                        })}
                      </div>
                      <div style={{ fontSize: 10, color: "#64748b", marginTop: 4, textAlign: "center" }}>
                        导演只选档位，技术参数自动适配
                      </div>
                    </div>

                    <div className="field">
                      <label>
                        🎯 相似度
                        <span style={{ float: "right", color: "#c084fc", fontWeight: 600 }}>
                          {Math.round(((selectedData as any).similarity ?? 70) * 100) / 100}%
                        </span>
                      </label>
                      <input
                        type="range"
                        min={0}
                        max={100}
                        value={((selectedData as any).similarity ?? 70) as number}
                        onChange={(e) => updateSelectedData({ similarity: Number(e.target.value) })}
                        style={{ width: "100%", accentColor: "#c084fc" }}
                      />
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#64748b", marginTop: 2 }}>
                        <span>自由发挥</span>
                        <span>严格还原</span>
                      </div>
                    </div>

                    <div className="field">
                      <label>
                        🎨 风格强度
                        <span style={{ float: "right", color: "#5eead4", fontWeight: 600 }}>
                          {Math.round(((selectedData as any).styleStrength ?? 50) * 100) / 100}%
                        </span>
                      </label>
                      <input
                        type="range"
                        min={0}
                        max={100}
                        value={((selectedData as any).styleStrength ?? 50) as number}
                        onChange={(e) => updateSelectedData({ styleStrength: Number(e.target.value) })}
                        style={{ width: "100%", accentColor: "#5eead4" }}
                      />
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#64748b", marginTop: 2 }}>
                        <span>写实</span>
                        <span>艺术化</span>
                      </div>
                    </div>

                    {/* ====== 角色绑定（Step A 新增）====== */}
                    <div className="field">
                      <label>角色绑定</label>
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <select
                          value={selectedData.characterId || ""}
                          onChange={(e) => {
                            const id = e.target.value;
                            if (!id) {
                              if (selectedData.characterId) {
                                unbindCharacterFromShot(selectedId || "");
                              }
                            } else {
                              bindCharacterToShot(selectedId || "", id);
                            }
                          }}
                          style={{ flex: 1 }}
                        >
                          <option value="">— 未绑定角色 —</option>
                          {characters.map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name}
                              {c.role_type ? `（${c.role_type}）` : ""}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          className="btn"
                          style={{ padding: "4px 8px" }}
                          onClick={() => refreshCharacters()}
                          title="从角色库刷新"
                        >
                          ↻
                        </button>
                      </div>
                      {selectedData.characterId && (
                        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 4, lineHeight: 1.4 }}>
                          📋 外貌: {selectedData.characterAppearance || "(角色库无外貌描述)"}
                          <div style={{ marginTop: 2 }}>
                            🔄 <a
                              href="#"
                              onClick={(e) => {
                                e.preventDefault();
                                syncCharacterToShot(selectedId || "");
                              }}
                              style={{ color: "#5eead4" }}
                            >
                              从角色库同步最新外貌描述到提示词
                            </a>
                            {" · "}
                            <a
                              href="#"
                              onClick={(e) => {
                                e.preventDefault();
                                unbindCharacterFromShot(selectedId || "");
                              }}
                              style={{ color: "#f87171" }}
                            >
                              解除绑定
                            </a>
                          </div>
                        </div>
                      )}
                    </div>
                    {/* ====== AI 补帧面板（Step B 新增）====== */}
                    <div className="field">
                      <label>🎞️ AI 插补帧</label>
                      <div className="row" style={{ alignItems: "center", gap: 8 }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
                          <input
                            type="checkbox"
                            checked={!!selectedData.interpolationEnabled}
                            onChange={(e) =>
                              updateSelectedData({
                                interpolationEnabled: e.target.checked,
                                interpolationMode: e.target.checked
                                  ? (selectedData.interpolationMode || "smart")
                                  : "disabled",
                              })
                            }
                          />
                          发送到剪辑时自动补帧
                        </label>
                      </div>
                      {selectedData.interpolationEnabled && (
                        <>
                          <div className="row" style={{ gap: 8, marginTop: 6 }}>
                            <div style={{ flex: 1 }}>
                              <label style={{ fontSize: 11, color: "#94a3b8" }}>模式</label>
                              <select
                                value={selectedData.interpolationMode || "smart"}
                                onChange={(e) =>
                                  updateSelectedData({ interpolationMode: e.target.value })}
                                style={{ width: "100%" }}
                              >
                                <option value="smart">SMART（帧差自适应）</option>
                                <option value="auto">AUTO（始终补帧）</option>
                                <option value="always">ALWAYS（强制双倍）</option>
                                <option value="disabled">DISABLED（关闭）</option>
                              </select>
                            </div>
                            <div style={{ flex: 1 }}>
                              <label style={{ fontSize: 11, color: "#94a3b8" }}>目标帧率</label>
                              <select
                                value={selectedData.interpolationTargetFps || 24}
                                onChange={(e) =>
                                  updateSelectedData({
                                    interpolationTargetFps: Number(e.target.value) as 24 | 30 | 60,
                                  })}
                                style={{ width: "100%" }}
                              >
                                <option value={24}>24fps（电影）</option>
                                <option value={30}>30fps（视频）</option>
                                <option value={60}>60fps（顺滑）</option>
                              </select>
                            </div>
                          </div>
                          {/* 补帧执行状态（后端回写） */}
                          {(selectedData.interpolationStatus &&
                            selectedData.interpolationStatus !== "none") && (
                            <div
                              style={{
                                fontSize: 11,
                                marginTop: 6,
                                padding: "4px 8px",
                                borderRadius: 4,
                                background:
                                  selectedData.interpolationStatus === "done"
                                    ? "#064e3b"
                                    : selectedData.interpolationStatus === "failed"
                                    ? "#7f1d1d"
                                    : "#1e3a5f",
                                color:
                                  selectedData.interpolationStatus === "done"
                                    ? "#6ee7b7"
                                    : selectedData.interpolationStatus === "failed"
                                    ? "#fca5a5"
                                    : "#93c5fd",
                              }}
                            >
                              {selectedData.interpolationStatus === "queued" && "⏳ 补帧排队中..."}
                              {selectedData.interpolationStatus === "running" && "🎬 补帧执行中..."}
                              {selectedData.interpolationStatus === "done" &&
                                `✅ 补帧完成：新增 ${selectedData.interpolationFrames || "?"} 帧`}
                              {selectedData.interpolationStatus === "failed" && "❌ 补帧失败"}
                            </div>
                          )}
                          {/* 剪辑入轨状态（后端回写） */}
                          {selectedData.editorStatus &&
                            selectedData.editorStatus !== "not_sent" && (
                              <div style={{ fontSize: 11, marginTop: 4, color: "#a7f3d0" }}>
                                📌 入轨状态:{" "}
                                {{
                                  sent: "已发送到剪辑队列",
                                  in_timeline: `已在时间线 ${selectedData.editorRange || ""}`,
                                  trimmed: "已裁剪",
                                  deleted: "已从时间线删除",
                                }[selectedData.editorStatus] || selectedData.editorStatus}
                              </div>
                            )}
                          <div className="row" style={{ gap: 6, marginTop: 8 }}>
                            <button
                              type="button"
                              className="btn"
                              style={{ fontSize: 11, padding: "4px 8px" }}
                              onClick={() => {
                                const BRIDGE =
                                  (window as any).__BRIDGE__ || "http://127.0.0.1:18765";
                                const data = selectedData as ShotData;
                                fetch(`${BRIDGE}/host/interpolate`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({
                                    mode: data.interpolationMode || "smart",
                                    target_fps: data.interpolationTargetFps || 24,
                                    title: data.title,
                                  }),
                                })
                                  .then((r) => r.json().catch(() => ({ ok: true })))
                                  .then((res: any) => {
                                    setStatus(
                                      res?.ok
                                        ? "补帧预览请求已发送（需 canvas_bridge.py 后端）"
                                        : `补帧预览: ${res?.message || "无后端，已记录参数"}`,
                                    );
                                  })
                                  .catch(() => {
                                    setStatus("补帧预览：canvas_bridge.py 离线，参数已记录");
                                  });
                              }}
                              title="向 bridge 发送补帧预览请求"
                            >
                              ▶ 预览补帧
                            </button>
                            <button
                              type="button"
                              className="btn"
                              style={{ fontSize: 11, padding: "4px 8px" }}
                              onClick={() =>
                                updateSelectedData({
                                  interpolationStatus: undefined,
                                  interpolationFrames: undefined,
                                })
                              }
                              title="清除补帧执行状态"
                            >
                              清除状态
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                    <div className="field">
                      <label>景别</label>
                      <select
                        value={selectedData.shotSize}
                        onChange={(e) => updateSelectedData({ shotSize: e.target.value })}
                      >
                        {["远景", "全景", "中景", "近景", "特写"].map((x) => (
                          <option key={x} value={x}>
                            {x}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label>时长（秒）</label>
                      <input
                        type="number"
                        min={0.5}
                        step={0.5}
                        value={selectedData.duration}
                        onChange={(e) =>
                          updateSelectedData({ duration: Number(e.target.value) || 1 })
                        }
                      />
                    </div>
                    <div className="field">
                      <label>对白</label>
                      <textarea
                        value={selectedData.dialogue}
                        onChange={(e) => updateSelectedData({ dialogue: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>提示词（@角色 / @素材）</label>
                      <textarea
                        value={selectedData.prompt}
                        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                      />
                      <div className="row" style={{ marginTop: 4 }}>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => {
                            const tag = prefs.character_name
                              ? `@${prefs.character_name}`
                              : "@角色";
                            updateSelectedData({
                              prompt: `${selectedData.prompt || ""}${selectedData.prompt ? " " : ""}${tag}`,
                            });
                          }}
                        >
                          @角色
                        </button>
                        <button
                          type="button"
                          className="btn"
                          onClick={() =>
                            updateSelectedData({
                              prompt: `${selectedData.prompt || ""}${selectedData.prompt ? " " : ""}@素材`,
                            })
                          }
                        >
                          @素材
                        </button>
                      </div>
                    </div>
                    <div className="field">
                      <label>机位预览（LibTV 式）</label>
                      <div className="btn-row angle-preset-row">
                        {ANGLE_PRESETS.slice(0, 6).map((p) => (
                          <button
                            key={p.id}
                            type="button"
                            className={`btn tiny${
                              (selectedData.cameraYaw ?? 0) === p.yaw &&
                              (selectedData.cameraPitch ?? 0) === p.pitch
                                ? " on"
                                : ""
                            }`}
                            onClick={() =>
                              updateSelectedData({ cameraYaw: p.yaw, cameraPitch: p.pitch })
                            }
                          >
                            {p.label}
                          </button>
                        ))}
                      </div>
                      <div className="field compact">
                        <label>水平 {selectedData.cameraYaw ?? 0}°</label>
                        <input
                          type="range"
                          min={-180}
                          max={180}
                          step={5}
                          value={selectedData.cameraYaw ?? 0}
                          onChange={(e) =>
                            updateSelectedData({ cameraYaw: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="field compact">
                        <label>俯仰 {selectedData.cameraPitch ?? 0}°</label>
                        <input
                          type="range"
                          min={-60}
                          max={60}
                          step={5}
                          value={selectedData.cameraPitch ?? 0}
                          onChange={(e) =>
                            updateSelectedData({ cameraPitch: Number(e.target.value) })
                          }
                        />
                      </div>
                      <div className="field">
                        <label>焦段</label>
                        <select
                          value={selectedData.focalLength ?? ""}
                          onChange={(e) =>
                            updateSelectedData({
                              focalLength: e.target.value ? Number(e.target.value) : undefined,
                            })
                          }
                        >
                          <option value="">默认</option>
                          {FOCAL_PRESETS.map((f) => (
                            <option key={f} value={f}>
                              {f}mm
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="field">
                        <label>运镜</label>
                        <select
                          value={selectedData.movement ?? "static"}
                          onChange={(e) => updateSelectedData({ movement: e.target.value })}
                        >
                          {MOVEMENT_OPTIONS.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <p className="muted tiny">
                        {buildCameraPromptBlock({
                          shotSize: selectedData.shotSize,
                          cameraYaw: selectedData.cameraYaw,
                          cameraPitch: selectedData.cameraPitch,
                          focalLength: selectedData.focalLength,
                          movement: selectedData.movement,
                        }) || "默认机位"}
                      </p>
                      <button
                        type="button"
                        className="btn"
                        disabled={generating}
                        onClick={onMultiAngleGenerate}
                      >
                        生成 5 机位叠卡
                      </button>
                    </div>
                    <FrameSlot
                      label="首帧"
                      url={selectedData.firstFrameUrl}
                      onPick={(u) => updateSelectedData({ firstFrameUrl: u })}
                      onClear={() => updateSelectedData({ firstFrameUrl: "" })}
                    />
                    <FrameSlot
                      label="尾帧"
                      url={selectedData.lastFrameUrl}
                      onPick={(u) => updateSelectedData({ lastFrameUrl: u })}
                      onClear={() => updateSelectedData({ lastFrameUrl: "" })}
                    />
                    <VideoRefSlot
                      label="参考视频片段"
                      url={selectedData.refVideoUrl}
                      name={selectedData.refVideoName}
                      onPick={(u, n) =>
                        updateSelectedData({ refVideoUrl: u, refVideoName: n })
                      }
                      onClear={() =>
                        updateSelectedData({ refVideoUrl: "", refVideoName: "" })
                      }
                    />
                    {selectedData.imageUrl ? (
                      <>
                        <div className="section-title">图工具</div>
                        <div className="btn-row">
                          <button type="button" className="btn" onClick={() => setMaskOpen(true)}>
                            蒙版重绘
                          </button>
                          <button type="button" className="btn" onClick={() => onApplyImageTool("crop916")}>
                            裁9:16
                          </button>
                          <button type="button" className="btn" onClick={() => onApplyImageTool("split2")}>
                            拆2×2
                          </button>
                          <button type="button" className="btn" onClick={() => onApplyImageTool("upscale")}>
                            放大
                          </button>
                          <button type="button" className="btn" onClick={() => onApplyImageTool("rotate90")}>
                            旋转
                          </button>
                        </div>
                        {(selectedData.images?.length || 0) > 0 ? (
                          <div className="field">
                            <label>叠卡主图</label>
                            <div className="stack-row">
                              {selectedData.images?.map((im) => (
                                <button
                                  key={im.id}
                                  type="button"
                                  className={`stack-thumb${selectedData.primaryImageId === im.id ? " on" : ""}`}
                                  onClick={() => onSetPrimaryImage(selectedId || "", im.id)}
                                  title={im.label || undefined}
                                >
                                  <img src={im.url} alt="" />
                                  {im.label ? <span className="stack-label">{im.label}</span> : null}
                                </button>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </>
                )}
                {selectedData.kind === "script" && (
                  <div className="field">
                    <label>剧本</label>
                    <textarea
                      value={selectedData.content}
                      onChange={(e) => updateSelectedData({ content: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "markdown" && (
                  <div className="field">
                    <label>Markdown</label>
                    <textarea
                      value={selectedData.content}
                      onChange={(e) => updateSelectedData({ content: e.target.value })}
                    />
                    <label className="chk">
                      <input
                        type="checkbox"
                        checked={!!selectedData.preview}
                        onChange={(e) => updateSelectedData({ preview: e.target.checked })}
                      />
                      预览模式
                    </label>
                  </div>
                )}
                {selectedData.kind === "shotlist" && (
                  <div className="field">
                    <label>分镜表</label>
                    <p className="hint">在节点内编辑行；选中图片/镜头后点行内「绑定选中」；可「展开为镜头」。</p>
                    <div className="meta">共 {(selectedData.rows || []).length} 行</div>
                  </div>
                )}
                {selectedData.kind === "storyboard" && (
                  <div className="field">
                    <label>宫格分镜</label>
                    <p className="hint">先选中图片节点 → 节点内「绑源图」→ 点击格裁出。</p>
                    <label>提示词备注</label>
                    <textarea
                      value={selectedData.prompt || ""}
                      onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "director" && (
                  <div className="field">
                    <label>3D 导演台节点</label>
                    <p className="hint">点节点「打开舞台」摆姿截图；截图回写本节点并另存镜头卡。</p>
                    <button
                      type="button"
                      className="btn primary"
                      onClick={() => useCanvasStore.getState().openDirectorForNode(selectedId!)}
                    >
                      打开绑定舞台
                    </button>
                    <label>提示词备注</label>
                    <textarea
                      value={selectedData.prompt || ""}
                      onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                    />
                    <div className="meta">历史截图 {(selectedData.captureUrls || []).length} 张</div>
                  </div>
                )}
                {selectedData.kind === "digitalHuman" && (
                  <div className="field">
                    <label>数字人</label>
                    <p className="hint">
                      形象图 + 台词配音入轨。口型驱动成片未配置形象驱动模型时诚实失败，不写假视频。
                    </p>
                    <label>角色名</label>
                    <input
                      type="text"
                      value={selectedData.characterName || ""}
                      onChange={(e) => updateSelectedData({ characterName: e.target.value })}
                      placeholder="可选"
                    />
                    <label>台词</label>
                    <textarea
                      value={selectedData.line || ""}
                      onChange={(e) => updateSelectedData({ line: e.target.value })}
                      placeholder="生成配音时作为 TTS 文本"
                    />
                    <label className="file-btn">
                      上传形象图…
                      <input
                        type="file"
                        accept="image/*"
                        hidden
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          e.target.value = "";
                          if (!f) return;
                          const res = await resolveMediaUrl(f);
                          if (!res.ok || !res.url) {
                            setStatus(res.message || "上传形象失败");
                            return;
                          }
                          updateSelectedData({ imageUrl: res.url, status: "success", errorMessage: "" });
                          if (selectedId) setNodeImage(selectedId, res.url);
                        }}
                      />
                    </label>
                    {selectedData.imageUrl ? (
                      <img src={selectedData.imageUrl} alt="" style={{ width: "100%", marginTop: 8, borderRadius: 8 }} />
                    ) : null}
                    {selectedData.audioUrl ? (
                      <audio src={selectedData.audioUrl} controls style={{ width: "100%", marginTop: 8 }} />
                    ) : (
                      <p className="hint">选中后点「生成」或节点上「生成配音」走 TTS。</p>
                    )}
                    {selectedData.errorMessage ? (
                      <div className="sg-node-error" style={{ whiteSpace: "normal" }}>{selectedData.errorMessage}</div>
                    ) : null}
                  </div>
                )}
                {selectedData.kind === "animation" && (
                  <div className="field">
                    <label>逐帧动画</label>
                    <p className="hint">上传 Sheet / 占位表 / AI 生成；可切换播放预览。</p>
                    <label>提示词</label>
                    <textarea
                      value={selectedData.prompt || ""}
                      onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "panorama" && (
                  <div className="field">
                    <label>全景</label>
                    <p className="hint">等距柱状图；节点内拖拽环视。不接 XiaoLuo / 全景生成服务。</p>
                    <label>偏航 {Math.round(selectedData.yaw || 0)}°</label>
                    <input
                      type="range"
                      min={-180}
                      max={180}
                      value={selectedData.yaw || 0}
                      onChange={(e) => updateSelectedData({ yaw: Number(e.target.value) })}
                    />
                    <label>俯仰 {Math.round(selectedData.pitch || 0)}°</label>
                    <input
                      type="range"
                      min={-80}
                      max={80}
                      value={selectedData.pitch || 0}
                      onChange={(e) => updateSelectedData({ pitch: Number(e.target.value) })}
                    />
                  </div>
                )}
                {selectedData.kind === "note" && (
                  <div className="field">
                    <label>画布笔记</label>
                    <textarea
                      value={selectedData.content || ""}
                      onChange={(e) => updateSelectedData({ content: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "source" && (
                  <div className="field">
                    <label>源文件</label>
                    <p className="hint">本地素材入口，连到下游图片/视频/生成器。</p>
                    <div className="meta">{selectedData.fileName || selectedData.mediaType}</div>
                  </div>
                )}
                {(selectedData.kind === "image" || selectedData.kind === "video") && (
                  <div className="field">
                    <label>提示词</label>
                    <textarea
                      value={selectedData.prompt}
                      onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "image" ? (
                  <VideoRefSlot
                    label="参考视频片段"
                    url={selectedData.refVideoUrl}
                    name={selectedData.refVideoName}
                    onPick={(u, n) =>
                      updateSelectedData({ refVideoUrl: u, refVideoName: n })
                    }
                    onClear={() =>
                      updateSelectedData({ refVideoUrl: "", refVideoName: "" })
                    }
                  />
                ) : null}
                {selectedData.kind === "image" && selectedData.imageUrl ? (
                  <>
                    <div className="btn-row">
                      <button type="button" className="btn" onClick={() => setMaskOpen(true)}>
                        蒙版重绘
                      </button>
                      <button type="button" className="btn" onClick={() => onApplyImageTool("crop916")}>
                        裁9:16
                      </button>
                      <button type="button" className="btn" onClick={() => onApplyImageTool("split3")}>
                        拆3×3
                      </button>
                      <button type="button" className="btn" onClick={() => onApplyImageTool("upscale")}>
                        放大
                      </button>
                    </div>
                    {(selectedData.images?.length || 0) > 0 ? (
                      <div className="field">
                        <label>叠卡主图</label>
                        <div className="stack-row">
                          {selectedData.images?.map((im) => (
                            <button
                              key={im.id}
                              type="button"
                              className={`stack-thumb${selectedData.primaryImageId === im.id ? " on" : ""}`}
                              onClick={() => onSetPrimaryImage(selectedId || "", im.id)}
                              title={im.label || undefined}
                            >
                              <img src={im.url} alt="" />
                              {im.label ? <span className="stack-label">{im.label}</span> : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </>
                ) : null}
                {selectedData.kind === "generator" && (
                  <>
                    <div className="field">
                      <label>模式</label>
                      <select
                        value={selectedData.mode}
                        onChange={(e) =>
                          updateSelectedData({
                            mode: e.target.value as "image" | "video" | "audio" | "text",
                          })
                        }
                      >
                        <option value="image">生图</option>
                        <option value="video">生视频</option>
                        <option value="audio">生音频</option>
                        <option value="text">文本</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>数量（叠卡）</label>
                      <input
                        type="number"
                        min={1}
                        max={4}
                        value={selectedData.count}
                        onChange={(e) =>
                          updateSelectedData({ count: Math.max(1, Math.min(4, Number(e.target.value) || 1)) })
                        }
                      />
                    </div>
                    <div className="field">
                      <label>提示词</label>
                      <textarea
                        value={selectedData.prompt}
                        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                      />
                    </div>
                  </>
                )}
                {selectedData.kind === "audio" && (
                  <>
                    <div className="field">
                      <label>提示词（TTS 占位）</label>
                      <textarea
                        value={selectedData.prompt}
                        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                      />
                    </div>
                    <label className="file-btn">
                      上传音频…
                      <input
                        type="file"
                        accept="audio/*"
                        hidden
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          e.target.value = "";
                          if (!f) return;
                          const res = await resolveMediaUrl(f);
                          if (!res.ok || !res.url) {
                            setStatus(res.message || "上传音频失败");
                            return;
                          }
                          onSetNodeAudio(res.url);
                        }}
                      />
                    </label>
                    {selectedData.audioUrl ? (
                      <audio src={selectedData.audioUrl} controls style={{ width: "100%", marginTop: 8 }} />
                    ) : null}
                  </>
                )}
                {selectedData.kind === "music" && (
                  <>
                    <MusicYueFields data={selectedData as any} onUpdate={updateSelectedData as any} />
                    <div className="field">
                      <label>🎵 音乐提示词 / 风格描述</label>
                      <textarea
                        value={(selectedData as any).prompt || ""}
                        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                        rows={2}
                        placeholder="例：soft piano, relaxing, lo-fi beat with warm synth"
                      />
                    </div>
                    <div className="field">
                      <label>🎸 风格标签（Style）</label>
                      <input
                        type="text"
                        value={(selectedData as any).style || ""}
                        onChange={(e) => updateSelectedData({ style: e.target.value })}
                        placeholder="pop / electronic / classical / lofi / rock / ambient…"
                      />
                    </div>
                    <div className="field">
                      <label>📝 歌词（Lyrics，留空则生成纯音乐）</label>
                      <textarea
                        value={(selectedData as any).lyrics || ""}
                        onChange={(e) => updateSelectedData({ lyrics: e.target.value })}
                        rows={3}
                        placeholder="每行一句，留空 + 勾选「纯音乐」= 纯音乐生成"
                      />
                    </div>
                    <div className="field">
                      <label>📌 曲名（Title）</label>
                      <input
                        type="text"
                        value={(selectedData as any).trackTitle || ""}
                        onChange={(e) => updateSelectedData({ trackTitle: e.target.value })}
                        placeholder="留空自动生成"
                      />
                    </div>
                    <div className="field">
                      <label className="chk">
                        <input
                          type="checkbox"
                          checked={!!(selectedData as any).instrumental}
                          onChange={(e) => updateSelectedData({ instrumental: e.target.checked })}
                        />
                        🎹 纯音乐（Instrumental，无人声）
                      </label>
                    </div>
                    <div className="field" style={{ display: (selectedData as any).engine === "yue" ? "none" : undefined }}>
                      <label>🤖 Suno 音乐模型</label>
                      {musicModels.length === 0 ? (
                        <p className="muted tiny">
                          尚未配置音乐模型。请打开「AI 模型管理」→ 添加 Suno 渠道（capability = music，填 API Key），
                          然后点顶部 🔄 刷新模型池。
                        </p>
                      ) : (
                        <select
                          value={selectedMusicModelKey}
                          onChange={(e) => setSelectedMusicModelKey(e.target.value)}
                          style={{ width: "100%" }}
                        >
                          {musicModels.map((m) => (
                            <option
                              key={`m_${m.channel_id}::${m.model}`}
                              value={`${m.channel_id}::${m.model}`}
                            >
                              {m.label}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>
                    {(selectedData as any).model ? (
                      <div className="muted tiny" style={{ marginBottom: 6 }}>
                        上次模型：{(selectedData as any).model}
                      </div>
                    ) : null}
                    <label className="file-btn">
                      上传音频覆盖…
                      <input
                        type="file"
                        accept="audio/*"
                        hidden
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          e.target.value = "";
                          if (!f) return;
                          const res = await resolveMediaUrl(f);
                          if (!res.ok || !res.url) {
                            setStatus(res.message || "上传音频失败");
                            return;
                          }
                          onSetNodeAudio(res.url);
                        }}
                      />
                    </label>
                    {(selectedData as any).audioUrl ? (
                      <audio src={(selectedData as any).audioUrl} controls style={{ width: "100%", marginTop: 8 }} />
                    ) : (
                      <p className="muted tiny" style={{ marginTop: 6 }}>
                        点顶部「▶ 生成选中」开始调 Suno 生成音乐（通常需要 30–90 秒）
                      </p>
                    )}
                  </>
                )}
                {selectedData.kind === "group" && (
                  <p className="muted">拖拽子节点进出编组；拖动编组可整体移动。</p>
                )}
                {selectedData.kind === "video" && (
                  <>
                    {selectedData.videoUrl ? (
                      <div className="field">
                        <label>预览</label>
                        <video
                          src={selectedData.videoUrl}
                          controls
                          playsInline
                          style={{ width: "100%", borderRadius: 8, background: "#000" }}
                        />
                      </div>
                    ) : (
                      <p className="muted">尚未生成视频（生成选中会走视频渠道，不写假片）</p>
                    )}
                    {(selectedData.videos?.length || 0) > 1 ? (
                      <div className="field">
                        <label>视频叠卡（对比结果）</label>
                        <div className="stack-row video-stack-row">
                          {selectedData.videos?.map((v) => (
                            <button
                              key={v.id}
                              type="button"
                              className={`stack-thumb video-stack-thumb${selectedData.primaryVideoId === v.id ? " on" : ""}`}
                              onClick={() => onSetPrimaryVideo(selectedId || "", v.id)}
                              title={v.label || undefined}
                            >
                              {v.posterUrl ? (
                                <img src={v.posterUrl} alt="" />
                              ) : (
                                <span className="ph">▶</span>
                              )}
                              {v.label ? <span className="stack-label">{v.label}</span> : null}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="field">
                      <label>时长（秒）</label>
                      <input
                        type="number"
                        min={2}
                        max={10}
                        step={1}
                        value={selectedData.duration ?? 5}
                        onChange={(e) =>
                          updateSelectedData({ duration: Number(e.target.value) || 5 })
                        }
                      />
                    </div>
                    <FrameSlot
                      label="首帧"
                      url={selectedData.firstFrameUrl}
                      onPick={(u) => updateSelectedData({ firstFrameUrl: u })}
                      onClear={() => updateSelectedData({ firstFrameUrl: "" })}
                    />
                    <FrameSlot
                      label="尾帧"
                      url={selectedData.lastFrameUrl}
                      onPick={(u) => updateSelectedData({ lastFrameUrl: u })}
                      onClear={() => updateSelectedData({ lastFrameUrl: "" })}
                    />
                    <VideoRefSlot
                      label="参考视频片段"
                      url={selectedData.refVideoUrl}
                      name={selectedData.refVideoName}
                      onPick={(u, n) =>
                        updateSelectedData({ refVideoUrl: u, refVideoName: n })
                      }
                      onClear={() =>
                        updateSelectedData({ refVideoUrl: "", refVideoName: "" })
                      }
                    />
                    <label className="file-btn">
                      上传本地视频到本节点…
                      <input
                        type="file"
                        accept="video/*"
                        hidden
                        onChange={async (e) => {
                          const f = e.target.files?.[0];
                          e.target.value = "";
                          if (!f) return;
                          const res = await resolveMediaUrl(f);
                          if (!res.ok || !res.url) {
                            setStatus(res.message || "上传失败");
                            return;
                          }
                          updateSelectedData({
                            videoUrl: res.url,
                            isReference: true,
                            refVideoUrl: res.url,
                            refVideoName: f.name,
                            title: selectedData.title || `参考·${f.name}`,
                          });
                          setStatus(`已写入参考视频 ${f.name}`);
                        }}
                      />
                    </label>
                    {/* ====== AI 补帧面板（Step B3: video 节点）====== */}
                    <div className="field">
                      <label>🎞️ AI 插补帧</label>
                      <div className="row" style={{ alignItems: "center", gap: 8 }}>
                        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
                          <input
                            type="checkbox"
                            checked={!!selectedData.interpolationEnabled}
                            onChange={(e) =>
                              updateSelectedData({
                                interpolationEnabled: e.target.checked,
                                interpolationMode: e.target.checked
                                  ? (selectedData.interpolationMode || "smart")
                                  : "disabled",
                              })
                            }
                          />
                          发送到剪辑时自动补帧
                        </label>
                      </div>
                      {selectedData.interpolationEnabled && (
                        <>
                          <div className="row" style={{ gap: 8, marginTop: 6 }}>
                            <div style={{ flex: 1 }}>
                              <label style={{ fontSize: 11, color: "#94a3b8" }}>模式</label>
                              <select
                                value={selectedData.interpolationMode || "smart"}
                                onChange={(e) =>
                                  updateSelectedData({ interpolationMode: e.target.value })}
                                style={{ width: "100%" }}
                              >
                                <option value="smart">SMART（帧差自适应）</option>
                                <option value="auto">AUTO（始终补帧）</option>
                                <option value="always">ALWAYS（强制双倍）</option>
                                <option value="disabled">DISABLED（关闭）</option>
                              </select>
                            </div>
                            <div style={{ flex: 1 }}>
                              <label style={{ fontSize: 11, color: "#94a3b8" }}>目标帧率</label>
                              <select
                                value={selectedData.interpolationTargetFps || 24}
                                onChange={(e) =>
                                  updateSelectedData({
                                    interpolationTargetFps: Number(e.target.value) as 24 | 30 | 60,
                                  })}
                                style={{ width: "100%" }}
                              >
                                <option value={24}>24fps（电影）</option>
                                <option value={30}>30fps（视频）</option>
                                <option value={60}>60fps（顺滑）</option>
                              </select>
                            </div>
                          </div>
                          {(selectedData.interpolationStatus &&
                            selectedData.interpolationStatus !== "none") && (
                            <div
                              style={{
                                fontSize: 11,
                                marginTop: 6,
                                padding: "4px 8px",
                                borderRadius: 4,
                                background:
                                  selectedData.interpolationStatus === "done"
                                    ? "#064e3b"
                                    : selectedData.interpolationStatus === "failed"
                                    ? "#7f1d1d"
                                    : "#1e3a5f",
                                color:
                                  selectedData.interpolationStatus === "done"
                                    ? "#6ee7b7"
                                    : selectedData.interpolationStatus === "failed"
                                    ? "#fca5a5"
                                    : "#93c5fd",
                              }}
                            >
                              {selectedData.interpolationStatus === "queued" && "⏳ 补帧排队中..."}
                              {selectedData.interpolationStatus === "running" && "🎬 补帧执行中..."}
                              {selectedData.interpolationStatus === "done" &&
                                `✅ 补帧完成：新增 ${selectedData.interpolationFrames || "?"} 帧`}
                              {selectedData.interpolationStatus === "failed" && "❌ 补帧失败"}
                            </div>
                          )}
                          {selectedData.editorStatus &&
                            selectedData.editorStatus !== "not_sent" && (
                              <div style={{ fontSize: 11, marginTop: 4, color: "#a7f3d0" }}>
                                📌 入轨状态:{" "}
                                {{
                                  sent: "已发送到剪辑队列",
                                  in_timeline: `已在时间线 ${selectedData.editorRange || ""}`,
                                  trimmed: "已裁剪",
                                  deleted: "已从时间线删除",
                                }[selectedData.editorStatus] || selectedData.editorStatus}
                              </div>
                            )}
                          <div className="row" style={{ gap: 6, marginTop: 8 }}>
                            <button
                              type="button"
                              className="btn"
                              style={{ fontSize: 11, padding: "4px 8px" }}
                              onClick={() => {
                                const BRIDGE =
                                  (window as any).__BRIDGE__ || "http://127.0.0.1:18765";
                                fetch(`${BRIDGE}/host/interpolate`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({
                                    mode: selectedData.interpolationMode || "smart",
                                    target_fps: selectedData.interpolationTargetFps || 24,
                                    title: selectedData.title,
                                  }),
                                })
                                  .then((r) => r.json().catch(() => ({ ok: true })))
                                  .then((res: any) => {
                                    setStatus(
                                      res?.ok
                                        ? "补帧预览请求已发送（需 canvas_bridge.py 后端）"
                                        : `补帧预览: ${res?.message || "无后端，已记录参数"}`,
                                    );
                                  })
                                  .catch(() => {
                                    setStatus("补帧预览：canvas_bridge.py 离线，参数已记录");
                                  });
                              }}
                              title="向 bridge 发送补帧预览请求"
                            >
                              ▶ 预览补帧
                            </button>
                            <button
                              type="button"
                              className="btn"
                              style={{ fontSize: 11, padding: "4px 8px" }}
                              onClick={() =>
                                updateSelectedData({
                                  interpolationStatus: undefined,
                                  interpolationFrames: undefined,
                                })
                              }
                              title="清除补帧执行状态"
                            >
                              清除状态
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </>
                )}
                {selectedData.kind === "prompt" && (
                  <div className="field">
                    <label>提示词</label>
                    <textarea
                      value={selectedData.text}
                      onChange={(e) => updateSelectedData({ text: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "text" && (
                  <>
                    <div className="field">
                      <label>内容</label>
                      <textarea
                        value={selectedData.content}
                        onChange={(e) => updateSelectedData({ content: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>字号</label>
                      <input
                        type="number"
                        min={10}
                        max={32}
                        value={selectedData.fontSize ?? 14}
                        onChange={(e) =>
                          updateSelectedData({ fontSize: Number(e.target.value) || 14 })
                        }
                      />
                    </div>
                  </>
                )}
                {selectedData.kind === "config" && (
                  <>
                    <div className="field">
                      <label>生成模式</label>
                      <select
                        value={selectedData.generationMode}
                        onChange={(e) =>
                          updateSelectedData({
                            generationMode: e.target.value as "image" | "video" | "audio" | "text",
                          })
                        }
                      >
                        <option value="image">生图</option>
                        <option value="video">生视频</option>
                        <option value="audio">生音频</option>
                        <option value="text">生文本</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>数量</label>
                      <input
                        type="number"
                        min={1}
                        max={4}
                        value={selectedData.count ?? 1}
                        onChange={(e) =>
                          updateSelectedData({ count: Math.max(1, Math.min(4, Number(e.target.value) || 1)) })
                        }
                      />
                    </div>
                    <div className="field">
                      <label>提示词</label>
                      <textarea
                        value={selectedData.prompt || ""}
                        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                      />
                    </div>
                  </>
                )}
              </>
            )}
            </>
            )}
          </aside>
          ) : null}
          {agentPanelOpen ? (
            <Suspense fallback={<PanelFallback label="Agent" />}>
              <AgentPanel
                open={agentPanelOpen}
                docked
                onClose={() => setAgentPanelOpen(false)}
                onRequestGenerate={onGenerate}
                onRequestBreakdown={onBreakdown}
                onRequestBatchGenerate={onBatchGenerate}
              />
            </Suspense>
          ) : null}
        </div>
        </>
      ) : null}
      {!agentPanelOpen && showWorkspace ? (
        <button
          type="button"
          className="sg-agent-fab primary"
          data-sg-no-autoclick="1"
          onClick={() => setAgentPanelOpen(true)}
          title="打开 Agent-IM 侧栏"
        >
          Agent
        </button>
      ) : null}
      <Suspense fallback={null}>
        <MaskEditDialog
          open={maskOpen}
          busy={generating}
          imageUrl={
            selectedData && (selectedData.kind === "shot" || selectedData.kind === "image")
              ? selectedData.imageUrl || ""
              : ""
          }
          onClose={() => setMaskOpen(false)}
          onSubmit={(mask, prompt) => {
            setMaskOpen(false);
            onInpaint(mask, prompt);
          }}
        />
      </Suspense>
    </div>
  );
}
