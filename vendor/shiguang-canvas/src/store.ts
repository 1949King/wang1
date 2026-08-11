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
  MarkerType,
} from "@xyflow/react";

export type ShotData = {
  kind: "shot";
  title: string;
  shotSize: string;
  duration: number;
  dialogue: string;
  prompt: string;
  imageUrl?: string;
  /** 即梦式首尾帧 */
  firstFrameUrl?: string;
  lastFrameUrl?: string;
};

export type ScriptData = {
  kind: "script";
  title: string;
  content: string;
};

export type ImageData = {
  kind: "image";
  title: string;
  prompt: string;
  imageUrl?: string;
};

export type VideoData = {
  kind: "video";
  title: string;
  prompt: string;
  posterUrl?: string;
  firstFrameUrl?: string;
  lastFrameUrl?: string;
};

export type PromptData = {
  kind: "prompt";
  title: string;
  text: string;
};

export type NodeData =
  | ShotData
  | ScriptData
  | ImageData
  | VideoData
  | PromptData;

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

const PROJECT_KEY = "shiguang-canvas:project:v1";
const TEMPLATES_KEY = "shiguang-canvas:templates:v1";

function uid(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

type Store = {
  nodes: Node[];
  edges: Edge[];
  selectedId: string | null;
  status: string;
  dramaTitle: string;
  episode: string;
  viewMode: ViewMode;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setStatus: (s: string) => void;
  setMeta: (dramaTitle: string, episode: string) => void;
  setViewMode: (m: ViewMode) => void;
  setSelected: (id: string | null) => void;
  updateSelectedData: (patch: Record<string, unknown>) => void;
  updateNodeData: (id: string, patch: Record<string, unknown>) => void;
  addNode: (type: NodeData["kind"], pos?: { x: number; y: number }) => void;
  addStoryboardGrid: (count?: 9 | 25) => void;
  applyStoryboard: (shots: StoryboardShot[], scriptTitle?: string) => void;
  addThreeView: () => void;
  addVariants: (axis?: "表情" | "服装" | "背景", count?: number) => void;
  removeSelected: () => void;
  saveProject: () => void;
  loadProject: () => void;
  listTemplates: () => { id: string; name: string; savedAt: string }[];
  saveTemplate: (name: string) => void;
  loadTemplate: (id: string) => void;
  deleteTemplate: (id: string) => void;
  setNodeImage: (id: string, imageUrl: string) => void;
  addCaptureToCanvas: (imageUrl: string, title: string) => void;
};

const defaultEdgeOptions = {
  animated: true,
  markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
  style: { stroke: "#64748b" },
};

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
      ...extra,
    } as VideoData,
    prompt: {
      kind: "prompt",
      title: "提示词",
      text: "风格：赛博朋克，高对比",
      ...extra,
    } as PromptData,
  };
  return {
    id,
    type,
    position,
    data: base[type],
  };
}

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
  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),
  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),
  onConnect: (connection) =>
    set({
      edges: addEdge({ ...connection, ...defaultEdgeOptions }, get().edges),
    }),
  setStatus: (status) => set({ status }),
  setMeta: (dramaTitle, episode) => set({ dramaTitle, episode }),
  setViewMode: (viewMode) => set({ viewMode: normalizeViewMode(viewMode) }),
  setSelected: (selectedId) => set({ selectedId }),
  updateSelectedData: (patch) => {
    const id = get().selectedId;
    if (!id) return;
    get().updateNodeData(id, patch);
  },
  updateNodeData: (id, patch) => {
    set({
      nodes: get().nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, ...patch } } : n,
      ),
    });
  },
  addNode: (type, pos) => {
    const position = pos || {
      x: 120 + Math.random() * 320,
      y: 80 + Math.random() * 240,
    };
    const node = makeNode(type, position);
    set({ nodes: [...get().nodes, node], selectedId: node.id });
  },
  addStoryboardGrid: (count = 9) => {
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
    set({
      nodes: [...get().nodes, ...nodes],
      status: `已添加${n}宫格分镜`,
    });
  },
  applyStoryboard: (shots, scriptTitle) => {
    const list = Array.isArray(shots) ? shots : [];
    if (!list.length) {
      set({ status: "拉片结果为空" });
      return;
    }
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
    set({
      nodes: [scriptNode, ...shotNodes],
      edges,
      selectedId: shotNodes[0]?.id || scriptNode.id,
      status: `拉片完成：${shotNodes.length} 个分镜节点`,
    });
  },
  addThreeView: () => {
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
    set({
      nodes: [...get().nodes, ...nodes],
      edges: [...get().edges, ...edges],
      selectedId: nodes[0]?.id || null,
      status: "已添加角色三视图节点（正/侧/背）",
    });
  },
  addVariants: (axis = "表情", count = 3) => {
    const id = get().selectedId;
    const src = get().nodes.find((n) => n.id === id);
    if (!src || (src.data as NodeData).kind !== "shot") {
      set({ status: "请先选中一个镜头节点再生成变体" });
      return;
    }
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
    set({
      nodes: [...get().nodes, ...nodes],
      edges: [...get().edges, ...edges],
      selectedId: nodes[0]?.id || id,
      status: `已生成 ${nodes.length} 个「${axis}」变体（可批量生成）`,
    });
  },
  removeSelected: () => {
    const id = get().selectedId;
    if (!id) return;
    set({
      nodes: get().nodes.filter((n) => n.id !== id),
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      selectedId: null,
    });
  },
  saveProject: () => {
    const payload = {
      version: 2,
      dramaTitle: get().dramaTitle,
      episode: get().episode,
      nodes: get().nodes,
      edges: get().edges,
      savedAt: new Date().toISOString(),
    };
    localStorage.setItem(PROJECT_KEY, JSON.stringify(payload));
    set({ status: "工程已保存到浏览器本地" });
  },
  loadProject: () => {
    const raw = localStorage.getItem(PROJECT_KEY);
    if (!raw) {
      set({ status: "没有本地工程" });
      return;
    }
    try {
      const data = JSON.parse(raw);
      set({
        nodes: data.nodes || [],
        edges: data.edges || [],
        dramaTitle: data.dramaTitle || "",
        episode: data.episode || "",
        status: `已加载工程（${data.savedAt || "未知时间"}）`,
      });
    } catch {
      set({ status: "工程文件损坏" });
    }
  },
  listTemplates: () => {
    try {
      const raw = localStorage.getItem(TEMPLATES_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr)
        ? arr.map((t: any) => ({
            id: String(t.id),
            name: String(t.name || "未命名"),
            savedAt: String(t.savedAt || ""),
          }))
        : [];
    } catch {
      return [];
    }
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
  setNodeImage: (id, imageUrl) => {
    set({
      nodes: get().nodes.map((n) => {
        if (n.id !== id) return n;
        const data = n.data as NodeData;
        if (data.kind === "shot" || data.kind === "image") {
          return { ...n, data: { ...data, imageUrl } };
        }
        if (data.kind === "video") {
          return { ...n, data: { ...data, posterUrl: imageUrl } };
        }
        return n;
      }),
    });
  },
  addCaptureToCanvas: (imageUrl, title) => {
    const node = makeNode(
      "shot",
      { x: 80 + Math.random() * 120, y: 60 + Math.random() * 80 },
      {
        title: title || "机位截图",
        shotSize: "中景",
        duration: 3,
        prompt: `3D导演台机位参考「${title || "截图"}」，保持人物站位、朝向与镜头构图`,
        imageUrl,
        firstFrameUrl: imageUrl,
      } as Partial<ShotData>,
    );
    set({
      nodes: [...get().nodes, node],
      selectedId: node.id,
      viewMode: "canvas",
      status: `3D 截图已入画布：${title || node.id}`,
    });
  },
}));
