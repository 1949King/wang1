/**
 * LibTV 向 Agent-IM 侧栏（借鉴 libtv-skills 会话 UX + assistant-ui sidebar 布局思路）。
 * 不引入 assistant-ui 重依赖，保持 Qt WebEngine 可加载；对话走项目 Agent。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BRIDGE,
  bridgeToken,
  refreshBridgeTokenFromInject,
  getAgentStatus,
  startCanvasAgent,
  listChatModels,
  projectAgentChatViaHost,
  listProjectTools,
  runProjectToolViaHost,
  syncModelPool,
  resolveMediaUrl,
  subscribeAgentEvents,
  sendAgentReply,
  controlAgentSession,
  breakdownStoryboard,
  planStoryboardCameras,
  fetchTimelineSnapshot,
  type AgentEventEnvelope,
  type ChatModelProvider,
  type ImageModelOption,
  type ProjectTool,
} from "./bridge";
import { useCanvasStore, type NodeData } from "./store";
import { nextFreeSlot } from "./canvasSlot";
import { applyBlueprint } from "./applyBlueprint";
import ConfirmDialog from "./ConfirmDialog";
import ExecutionBiasChip from "./ExecutionBiasChip";
import SgSelect from "./SgSelect";
import { refreshGenerationModels, useGenerationModelStore } from "./generationModels";
import "./agentPanel.css";
import {
  decideCanvasTool,
  loadAgentMode,
  saveAgentMode,
  type AgentMode,
} from "./agentPolicy";
import {
  dubPlan,
  dubExecute,
  dubToTimeline,
  collectShotRefs,
  buildShotDurationPatches,
  formatDubPlanForConfirm,
  summarizeDubExecute,
} from "./dubOrchestration";

type Attach = {
  id: string;
  kind: "image" | "video";
  url: string;
  name: string;
};

type Msg = {
  role: "user" | "assistant" | "system";
  text: string;
  attaches?: Attach[];
  streamId?: string;
  streaming?: boolean;
};

type Tab = "chat" | "models" | "tools" | "budget";

type Props = {
  open: boolean;
  docked?: boolean;
  onClose: () => void;
  onRequestGenerate: () => void;
  onRequestBreakdown?: () => void;
  onRequestBatchGenerate?: () => void;
};

const QUICK = [
  { id: "gen", label: "生成选中", text: "/generate" },
  { id: "batch", label: "批量生成", text: "/batch" },
  { id: "shot", label: "+镜头", text: "/add shot" },
  { id: "sync", label: "同步模型", text: "/sync" },
  { id: "status", label: "状态", text: "/status" },
  { id: "tools", label: "工具", text: "/tools" },
] as const;

/** 生图/生视频模型行：本地与云端共用同一份 generationModels store。 */
function GenerationModelRows({
  title,
  models,
  selectedKey,
  onSelect,
  empty,
}: {
  title: string;
  models: ImageModelOption[];
  selectedKey: string;
  onSelect: (key: string) => void;
  empty: string;
}) {
  return (
    <>
      <div className="section-title" style={{ marginTop: 10 }}>
        {title}（{models.length}）
      </div>
      {models.length === 0 ? (
        <p className="muted" style={{ fontSize: 11 }}>{empty}</p>
      ) : (
        models.map((m) => {
          const key = `${m.channel_id}::${m.model}`;
          return (
            <div className="sg-tool-row" key={key}>
              <div style={{ minWidth: 0 }}>
                <strong style={{ fontSize: 11 }}>{m.label}</strong>
              </div>
              <button
                type="button"
                className={`btn${selectedKey === key ? " primary" : ""}`}
                onClick={() => onSelect(key)}
              >
                {selectedKey === key ? "已选" : "选用"}
              </button>
            </div>
          );
        })
      )}
    </>
  );
}

function sessionId(): string {
  const k = "shiguang-canvas:agent-session-id";
  try {
    const ex = localStorage.getItem(k);
    if (ex) return ex;
    const id = `sg_${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(k, id);
    return id;
  } catch {
    return "local";
  }
}

export default function AgentPanel({
  open,
  docked = true,
  onClose,
  onRequestGenerate,
  onRequestBreakdown,
  onRequestBatchGenerate,
}: Props) {
  const [tab, setTab] = useState<Tab>("chat");
  const [mcpOn, setMcpOn] = useState(false);
  const [mcpUrl, setMcpUrl] = useState("");
  const [busy, setBusy] = useState(false);
  // 2026-10-19（用户反馈「Agent UI 过于繁杂」）：只有「暂停过」才显示「继续」。
  // 旧实现空闲时就常驻一个「继续」按钮，用户点它没有任何效果，纯噪音。
  const [paused, setPaused] = useState(false);
  const [thinkSec, setThinkSec] = useState(0);
  // V4.40.52：快捷提示词默认收起（对话区当主角，省 ≈50px）
  const [chipsOpen, setChipsOpen] = useState(false);
  // V4.40.53：画布引用卡默认收起成一行摘要（点标题行展开缩略图）
  const [refOpen, setRefOpen] = useState(false);
  const streamBufRef = useRef<Record<string, string>>({});
  const activeStreamRef = useRef<string>("");
  const [input, setInput] = useState("");
  const [providers, setProviders] = useState<ChatModelProvider[]>([]);
  const [modelKey, setModelKey] = useState<string>(() => {
    try { return localStorage.getItem("shiguang-canvas:agent-model") || ""; } catch { return ""; }
  });
  // 生图/生视频模型与算力偏好共用 App 的 generationModels store（面板不再只列对话模型）
  const genImageModels = useGenerationModelStore((s) => s.imageModels);
  const genVideoModels = useGenerationModelStore((s) => s.videoModels);
  const genSelectedImageKey = useGenerationModelStore((s) => s.selectedModelKey);
  const genSelectedVideoKey = useGenerationModelStore((s) => s.selectedVideoModelKey);
  const setGenImageKey = useGenerationModelStore((s) => s.setSelectedModelKey);
  const setGenVideoKey = useGenerationModelStore((s) => s.setSelectedVideoModelKey);
  const localImageModels = genImageModels.filter((m) => m.channel_id === "local");
  const cloudImageModels = genImageModels.filter((m) => m.channel_id !== "local");
  const localVideoModels = genVideoModels.filter((m) => m.channel_id === "local");
  const cloudVideoModels = genVideoModels.filter((m) => m.channel_id !== "local");
  const [tools, setTools] = useState<ProjectTool[]>([]);
  const [toolFilter, setToolFilter] = useState("");
  const [attaches, setAttaches] = useState<Attach[]>([]);
  const [budgetData, setBudgetData] = useState<any>(null);
  const [budgetLoading, setBudgetLoading] = useState(false);
  const [recentCalls, setRecentCalls] = useState<any[]>([]);
  const [sid] = useState(() => sessionId());
  const [agentMode, setAgentMode] = useState<AgentMode>(() => loadAgentMode());
  const agentModeRef = useRef<AgentMode>(agentMode);
  agentModeRef.current = agentMode;
  const [confirmBox, setConfirmBox] = useState<{
    title: string;
    message: string;
    danger: boolean;
    resolve: (ok: boolean) => void;
  } | null>(null);
  const msgsEndRef = useRef<HTMLDivElement>(null);
  // V4.40.53：欢迎语精简 —— 完整版只给第一次用的人看；之后一行就绪提示（LibTV 简洁）
  const [msgs, setMsgs] = useState<Msg[]>(() => {
    let seen = false;
    try {
      seen = localStorage.getItem("shiguang-canvas:agent-im:welcomed") === "1";
      localStorage.setItem("shiguang-canvas:agent-im:welcomed", "1");
    } catch {
      /* localStorage 不可用时按首次处理 */
    }
    return [
      {
        role: "system",
        text: seen
          ? "已就绪 · 选模型 → 输入 → 发送（/ 指令 · 📎 附件）"
          : "画布 Agent（快路径，无需先开剪辑）：① 选好对话模型 → ② 输入 → ③ 发送。" +
            "回复会边生成边显示。快捷芯片=/指令；可 📎 附图视频。" +
            "3D 姿势/机位请在导演台左侧栏手动调。",
      },
    ];
  });

  const addNode = useCanvasStore((s) => s.addNode);
  const addVideoReference = useCanvasStore((s) => s.addVideoReference);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const nodes = useCanvasStore((s) => s.nodes);
  const edges = useCanvasStore((s) => s.edges);
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const setSelected = useCanvasStore((s) => s.setSelected);
  const onConnect = useCanvasStore((s) => s.onConnect);
  const onNodesChange = useCanvasStore((s) => s.onNodesChange);
  const setNodeImage = useCanvasStore((s) => s.setNodeImage);
  const setNodeVideo = useCanvasStore((s) => s.setNodeVideo);
  const duplicateSelected = useCanvasStore((s) => s.duplicateSelected);
  const groupSelected = useCanvasStore((s) => s.groupSelected);
  const undoGraph = useCanvasStore((s) => s.undoGraph);
  const redoGraph = useCanvasStore((s) => s.redoGraph);
  const applyStoryboard = useCanvasStore((s) => s.applyStoryboard);

  const push = (role: Msg["role"], text: string, atts?: Attach[]) =>
    setMsgs((m) => [...m, { role, text, attaches: atts }]);

  useEffect(() => {
    if (!busy) {
      setThinkSec(0);
      return;
    }
    setThinkSec(0);
    const t = window.setInterval(() => setThinkSec((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [busy]);

  useEffect(() => {
    if (modelKey) {
      try { localStorage.setItem("shiguang-canvas:agent-model", modelKey); } catch {}
    }
  }, [modelKey]);

  const upsertStreamMsg = (streamId: string, text: string, streaming: boolean) => {
    setMsgs((m) => {
      const idx = m.findIndex((x) => x.streamId === streamId);
      if (idx >= 0) {
        const next = m.slice();
        next[idx] = { ...next[idx], text, streaming, role: "assistant" };
        return next;
      }
      return [...m, { role: "assistant", text, streamId, streaming }];
    });
  };

  useEffect(() => {
    msgsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy, thinkSec]);

  // budget tab 自动刷新
  useEffect(() => {
    if (tab === "budget") void refreshBudget();
  }, [tab]);

  // ── SSE: 订阅剪辑 Agent 主动推过来的事件 ──────────────────────

  const handleEditorEvent = (evt: AgentEventEnvelope) => {
    // 心跳忽略
    if (evt.type === "ping" || evt.type === "pong") return;

    // 流式对话增量
    if (evt.type === "chat.delta") {
      const p = evt.payload || {};
      const streamId = String(p.stream_id || "");
      if (!streamId) return;
      if (activeStreamRef.current && streamId !== activeStreamRef.current) return;
      if (p.status === "start") {
        streamBufRef.current[streamId] = "";
        upsertStreamMsg(streamId, "…", true);
        return;
      }
      const delta = String(p.delta || "");
      if (!delta) return;
      streamBufRef.current[streamId] = (streamBufRef.current[streamId] || "") + delta;
      upsertStreamMsg(streamId, streamBufRef.current[streamId], true);
      return;
    }
    if (evt.type === "chat.done") {
      const p = evt.payload || {};
      const streamId = String(p.stream_id || "");
      if (!streamId) return;
      if (activeStreamRef.current && streamId !== activeStreamRef.current) return;
      const text = String(p.text || streamBufRef.current[streamId] || "");
      if (p.ok === false) {
        upsertStreamMsg(streamId, String(p.error || "生成失败"), false);
      } else if (text) {
        upsertStreamMsg(streamId, text, false);
      }
      return;
    }

    // chat.message：剪辑 Agent 主动发一句话（推到聊天区）
    if (evt.type === "chat.message") {
      const p = evt.payload || {};
      const text = String(p.text || p || "");
      const role: Msg["role"] =
        p.role === "system" ? "system" : p.role === "error" ? "system" : "assistant";
      push(role, text);
      return;
    }

    // task / progress / done / fail：任务状态推送（展示为 system 消息）
    if (evt.type === "task.progress") {
      const p = evt.payload || {};
      const pct = p.percent != null ? `${p.percent}%` : "";
      const msg = String(p.message || pct || "任务进行中...");
      push("system", `🔄 任务 ${evt.payload?.task_id || ""} ${msg}`);
      return;
    }
    if (evt.type === "task.done") {
      push("system", `✅ 任务 ${evt.payload?.task_id || ""} 完成`);
      return;
    }
    if (evt.type === "task.fail") {
      push("system", `❌ 任务 ${evt.payload?.task_id || ""} 失败: ${evt.payload?.error || ""}`);
      return;
    }

    // task.create：给画布派任务（加节点 / 更新 / 连边 / 删除 / 生图 / 导入）
    if (evt.type === "task.create") {
      executeRemoteTask(evt);
      return;
    }

    // compliance.report：剧本合规守护推送（AI 审查建议）
    if (evt.type === "compliance.report") {
      const p = evt.payload || {};
      const items: any[] = p.suggestions || [];
      if (items.length === 0) {
        push("system", `✅ 剧本合规守护通过（${p.total_shots || 0} 分镜 / ${p.total_characters || 0} 角色）`);
      } else {
        const header = `🛡️ 剧本合规守护：${p.summary || `${items.length} 条建议`}`;
        push("system", header);
        items.forEach((it, i) => {
          const lvl = it.level === "warning" ? "⚠️" : it.level === "error" ? "❌" : "💡";
          push("system", `${lvl} [${it.category || "建议"}] ${it.message || ""}`);
        });
      }
      return;
    }

    // 未知类型：推 system 展示原文，方便调试
    push("system", `📨 收到事件 ${evt.type}: ${JSON.stringify(evt.payload).slice(0, 200)}`);
  };

  const askConfirm = (title: string, message: string, danger = false) =>
    new Promise<boolean>((resolve) => {
      setConfirmBox({
        title,
        message,
        danger,
        resolve: (v: boolean) => {
          resolve(v);
        },
      });
    });

  const executeRemoteTask = async (evt: AgentEventEnvelope) => {
    const p = evt.payload || {};
    const taskId: string = String(p.task_id || evt.id || "");
    const action: string = String(p.action || "");
    const params: Record<string, any> = p.params || {};

    const policy = decideCanvasTool(action, agentModeRef.current);
    if (policy.action === "deny") {
      push("system", `⛔ Plan 已拦截「${action}」：${policy.reason}`);
      if (evt.ack_required || evt.correlation_id) {
        await sendAgentReply({
          correlation_id: evt.correlation_id || evt.id,
          type: "canvas.reply",
          payload: { task_id: taskId, ok: false, action, error: policy.reason },
        });
      }
      return;
    }
    if (policy.action === "require_approval") {
      const ok = await askConfirm(
        "确认画布操作",
        `Agent 请求执行「${action}」。协作模式下改画布/生成需你确认。`,
        action === "deleteNode" || action === "runGenerate",
      );
      if (!ok) {
        push("system", `已取消「${action}」`);
        if (evt.ack_required || evt.correlation_id) {
          await sendAgentReply({
            correlation_id: evt.correlation_id || evt.id,
            type: "canvas.reply",
            payload: { task_id: taskId, ok: false, action, error: "user_cancelled" },
          });
        }
        return;
      }
    }

    const reply = async (ok: boolean, extra: Record<string, any> = {}) => {
      if (!evt.ack_required && !evt.correlation_id) return;
      const res = await sendAgentReply({
        correlation_id: evt.correlation_id || evt.id,
        type: "canvas.reply",
        payload: { task_id: taskId, ok, action, ...extra },
      });
      if (!res.ok) {
        // 回执失败不阻塞执行，但要让用户知道
        push("system", `⚠️ 回执失败（桥可能未连通）: ${res.message}`);
      }
    };

    try {
      let canvasNodeId = "";
      switch (action) {
        case "addNode": {
          const kind = String(params.kind || params.type || "shot");
          // Agent 没给坐标 ⇒ 用确定性网格槽位（canvasSlot），不再走 store 的
          // Math.random() 撒点（一批卡全挤同一小盒子 = 用户看到的「画布很乱」）。
          const pos =
            params.x != null && params.y != null
              ? { x: Number(params.x), y: Number(params.y) }
              : nextFreeSlot(useCanvasStore.getState().nodes);
          addNode(kind as any, pos);
          // addNode 内部设 selectedId，立即读
          const sid = useCanvasStore.getState().selectedId;
          canvasNodeId = sid || "";
          // 如果有额外数据要写（prompt / camera 等），用 updateNodeData
          const extra: Record<string, any> = {};
          for (const k of Object.keys(params)) {
            if (k !== "kind" && k !== "type" && k !== "x" && k !== "y") {
              extra[k] = params[k];
            }
          }
          if (canvasNodeId && Object.keys(extra).length > 0) {
            updateNodeData(canvasNodeId, extra);
          }
          break;
        }
        case "updateNode": {
          const id = String(params.id || params.node_id || "");
          if (!id) throw new Error("updateNode 缺少 id");
          const patch = params.patch || params.data || {};
          updateNodeData(id, patch);
          break;
        }
        case "connectNodes": {
          const src = String(params.source || "");
          const tgt = String(params.target || "");
          if (!src || !tgt) throw new Error("connectNodes 缺少 source/target");
          onConnect({
            source: src,
            target: tgt,
            sourceHandle: params.sourceHandle,
            targetHandle: params.targetHandle,
          } as any);
          break;
        }
        case "applyBlueprint": {
          // ★ 2026-10-31：工作流蓝图（LLM 出图结构，本地算坐标 ⇒ 一次铺出完整 DAG）。
          //   只走 store 已公开的 addNode/updateNodeData/onConnect 三件套，
          //   与上面 addNode/connectNodes 两个 case 同一套语义（不造第二条链路）。
          const spec = (params.blueprint || params.spec || params) as any;
          const before = useCanvasStore.getState().nodes.length;
          const res = applyBlueprint(spec, {
            addNode: (kind: string, pos: { x: number; y: number }) =>
              addNode(kind as any, pos),
            updateNodeData: (id: string, patch: Record<string, unknown>) =>
              updateNodeData(id, patch),
            onConnect: (c: { source: string; target: string }) => onConnect(c as any),
            existingNodes: useCanvasStore.getState().nodes,
          });
          if (!res.ok) {
            throw new Error(`蓝图应用失败：${res.problems.join("；") || "没有有效节点"}`);
          }
          canvasNodeId = res.nodeIds[res.nodeIds.length - 1] || "";
          const added = useCanvasStore.getState().nodes.length - before;
          const warn = res.problems.length ? `（${res.problems.length} 条提示）` : "";
          push(
            "system",
            `✅ 工作流已铺开：${added} 个节点 / ${res.edgesApplied} 条连线${warn}`,
          );
          break;
        }
        case "deleteNode": {
          const id = String(params.id || "");
          if (!id) throw new Error("deleteNode 缺少 id");
          onNodesChange([{ type: "remove", id }] as any);
          break;
        }
        case "runGenerate": {
          onRequestGenerate();
          break;
        }
        case "batchGenerate":
        case "runBatchGenerate":
        case "canvas_batch_generate": {
          if (!onRequestBatchGenerate) throw new Error("当前画布未接线批量生成");
          onRequestBatchGenerate();
          break;
        }
        case "setNodeImage": {
          const id = String(params.id || "");
          const url = String(params.url || "");
          if (!id || !url) throw new Error("setNodeImage 缺少 id/url");
          setNodeImage(id, url);
          break;
        }
        case "setNodeVideo": {
          const id = String(params.id || "");
          const url = String(params.url || "");
          if (!id || !url) throw new Error("setNodeVideo 缺少 id/url");
          setNodeVideo(id, url, params.posterUrl);
          break;
        }
        case "importImage": {
          const url = String(params.url || "");
          if (!url) throw new Error("importImage 缺少 url");
          addVideoReference(url, { title: String(params.title || ""), name: String(params.name || "") });
          const sid = useCanvasStore.getState().selectedId;
          canvasNodeId = sid || "";
          break;
        }
        case "queryTimeline": {
          const snap = await fetchTimelineSnapshot();
          await reply(true, {
            clip_count: snap.clip_count || (snap.clips || []).length,
            clips: snap.clips || [],
            gaps: snap.gaps || [],
            suggestions: snap.suggestions || [],
            message: snap.message || "",
          });
          push("system", `✅ queryTimeline → ${snap.clip_count || 0} 个片段`);
          return;
        }
        case "queryNodes":
        case "canvas_query": {
          const kind = String(params.kind || params.type || "").trim();
          const keyword = String(params.keyword || params.q || "").trim().toLowerCase();
          const list = useCanvasStore.getState().nodes
            .filter((n) => {
              const d = n.data as any;
              if (kind && d?.kind !== kind && n.type !== kind) return false;
              if (!keyword) return true;
              const blob = `${d?.title || ""} ${d?.prompt || ""} ${d?.content || ""} ${d?.text || ""}`.toLowerCase();
              return blob.includes(keyword);
            })
            .map((n) => ({
              id: n.id,
              type: n.type,
              kind: (n.data as any)?.kind,
              title: (n.data as any)?.title,
              selected: n.selected,
            }));
          await reply(true, { nodes: list, total: list.length, edges: edges.length });
          push("system", `✅ queryNodes → ${list.length} 个节点`);
          return;
        }
        case "selectNode":
        case "canvas_select": {
          const id = String(params.id || params.node_id || "");
          if (!id) throw new Error("selectNode 缺少 id");
          setSelected(id);
          useCanvasStore.setState((s) => ({
            nodes: s.nodes.map((n) => ({ ...n, selected: n.id === id })),
          }));
          canvasNodeId = id;
          break;
        }
        case "duplicateNode":
        case "canvas_duplicate_node": {
          const id = String(params.id || params.node_id || selectedId || "");
          if (id) setSelected(id);
          duplicateSelected();
          canvasNodeId = useCanvasStore.getState().selectedId || "";
          break;
        }
        case "groupNodes":
        case "canvas_group": {
          groupSelected();
          canvasNodeId = useCanvasStore.getState().selectedId || "";
          break;
        }
        case "undo":
        case "canvas_undo": {
          undoGraph();
          break;
        }
        case "redo":
        case "canvas_redo": {
          redoGraph();
          break;
        }
        case "bindShotlistFrame":
        case "canvas_bind_shotlist_frame": {
          const shotlistId = String(params.shotlist_id || params.id || "");
          const rowId = String(params.row_id || "");
          const frameId = String(params.frame_node_id || params.image_id || "");
          if (!shotlistId || !rowId || !frameId) throw new Error("bindShotlistFrame 缺少参数");
          const st = useCanvasStore.getState();
          const sl = st.nodes.find((n) => n.id === shotlistId);
          const fr = st.nodes.find((n) => n.id === frameId);
          if (!sl || (sl.data as any).kind !== "shotlist") throw new Error("不是分镜表节点");
          if (!fr) throw new Error("画面节点不存在");
          const fd = fr.data as any;
          const rows = ((sl.data as any).rows || []).map((r: any) =>
            r.id === rowId
              ? {
                  ...r,
                  frameNodeId: frameId,
                  frameKind: fd.kind === "video" ? "video" : "image",
                  frameUrl: fd.imageUrl || fd.posterUrl || fd.videoUrl || "",
                }
              : r,
          );
          updateNodeData(shotlistId, { rows });
          canvasNodeId = shotlistId;
          break;
        }
        case "fillStoryboardCell":
        case "canvas_fill_storyboard_cell": {
          const sbId = String(params.storyboard_id || params.id || "");
          const index = Number(params.index ?? params.cell ?? 0);
          const url = String(params.url || "");
          if (!sbId) throw new Error("fillStoryboardCell 缺少 id");
          const st = useCanvasStore.getState();
          const sb = st.nodes.find((n) => n.id === sbId);
          if (!sb || (sb.data as any).kind !== "storyboard") throw new Error("不是宫格分镜节点");
          const d = sb.data as any;
          const cols = d.cols || 3;
          const rowsN = d.rows || 3;
          const cells = [...(d.cells || Array.from({ length: cols * rowsN }, () => ({})))];
          while (cells.length < cols * rowsN) cells.push({});
          if (url) {
            cells[index] = { ...(cells[index] || {}), overrideUrl: url };
            updateNodeData(sbId, { cells });
          } else if (d.sourceUrl) {
            const { cropGridCell } = await import("./imageTools");
            const cut = await cropGridCell(d.sourceUrl, cols, rowsN, index);
            cells[index] = { ...(cells[index] || {}), overrideUrl: cut };
            updateNodeData(sbId, { cells });
            st.addNode("image", {
              x: (sb.position.x || 0) + 460,
              y: (sb.position.y || 0) + index * 40,
            });
            const sid = useCanvasStore.getState().selectedId;
            if (sid) updateNodeData(sid, { title: `格 ${index + 1}`, imageUrl: cut });
            canvasNodeId = sid || sbId;
          } else {
            throw new Error("宫格无源图且未提供 url");
          }
          if (!canvasNodeId) canvasNodeId = sbId;
          break;
        }
        case "breakdown":
        case "applyStoryboard":
        case "storyboardBreakdown":
        case "canvas_breakdown": {
          let script = String(params.script || params.content || params.storyboard || "").trim();
          if (!script) {
            const firstScript = nodes.find((n) => (n.data as NodeData).kind === "script");
            if (firstScript) {
              script = String((firstScript.data as Extract<NodeData, { kind: "script" }>).content || "").trim();
            }
          }
          if (!script) throw new Error("breakdown 缺少剧本内容（params.script / script 节点均为空）");
          push("system", `🧩 收到剧本拆解请求（${script.length} 字），正在调用后端 LLM…`);
          const res = await breakdownStoryboard(script);
          if (!res.ok && !(res.shots && res.shots.length)) {
            throw new Error(res.message || "剧本拆解失败");
          }
          applyStoryboard(res.shots || [], "Agent拆解剧本");
          if (res.fallback) {
            push("system", `⚠️ 启发式兜底，共生成 ${res.shots?.length || 0} 镜`);
          } else {
            push("system", `✅ LLM 拆解完成，共 ${res.shots?.length || 0} 镜`);
          }
          break;
        }
        case "stage3dTextPlan": {
          // 文本 → 3D 粗模（仅机位档）：复用后端既有「文本/剧本 → 分镜 → 机位」通道，
          // 再走现成 applyStage3dCameraPlan 把机位投到 3D 导演台。不新增任何 3D 通道、不动冻结区。
          let text = String(params.text || params.script || params.content || "").trim();
          if (!text) {
            const firstScript = nodes.find((n) => (n.data as NodeData).kind === "script");
            if (firstScript) {
              text = String((firstScript.data as Extract<NodeData, { kind: "script" }>).content || "").trim();
            }
          }
          if (!text) throw new Error("stage3dTextPlan 缺少文本（params.text / script 节点均为空）");
          push("system", `🎥 收到文本→3D 机位请求（${text.length} 字），正在解析…`);
          const plan = await planStoryboardCameras({ script: text, use_llm: true });
          if (!plan.ok || !(plan.cameras && plan.cameras.length)) {
            throw new Error(plan.message || "机位规划失败（未产出可用机位）");
          }
          useCanvasStore.getState().applyStage3dCameraPlan(plan.cameras);
          push("system", `✅ 已生成 ${plan.cameras.length} 个机位并应用到 3D 导演台（可在 3D 台内微调/录制白模参考视频）`);
          break;
        }
        case "dubOrchestrate": {
          // 剧本 → 多角色配音（逐句路由角色音色）→ 配音时长反推镜头时长 → 配音轨落时间线。
          // 这是"写效果"，协作模式下 decideCanvasTool 已在上方弹过确认，这里不重复确认。
          let script = String(params.script || params.content || "").trim();
          if (!script) {
            const firstScript = nodes.find((n) => (n.data as NodeData).kind === "script");
            if (firstScript) {
              script = String((firstScript.data as Extract<NodeData, { kind: "script" }>).content || "").trim();
            }
          }
          if (!script) throw new Error("dubOrchestrate 缺少剧本（params.script / script 节点均为空）");
          const characters = Array.isArray(params.characters) ? params.characters : undefined;
          const shotRefs = collectShotRefs(nodes as any);

          push("system", `🔊 收到配音编排请求（${script.length} 字 · ${shotRefs.length} 个镜头），先出计划…`);
          const plan = await dubPlan(script, characters);
          if (!plan.ok) throw new Error(plan.message || "配音计划生成失败");
          push("system", formatDubPlanForConfirm(plan));

          push("system", "🎙️ 正在逐句合成配音（本地 TTS）…");
          const exec = await dubExecute(script, {
            characters,
            shots: shotRefs.length ? shotRefs : undefined,
            // 听写校验 / 音→字字幕为可选（会加载 Whisper，较慢）：用户显式要求时才开
            verify: params.verify === true,
            subtitles: params.subtitles === true,
          });
          push("system", summarizeDubExecute(exec));
          if (exec.red_flags && exec.red_flags > 0) {
            push("system", `⚠️ ${exec.red_flags} 句发音相似度偏低（红标），建议复核后再用`);
          }

          // 用配音真实时长反推镜头时长（只有拿到音频的镜头才改；无证据保持估算）
          for (const { id, patch } of buildShotDurationPatches(exec.shots, shotRefs)) {
            updateNodeData(id, patch);
          }

          const segments = exec.track?.segments || [];
          if (segments.length) {
            const tl = await dubToTimeline(segments);
            if (tl.ok) {
              push("system", `✅ 配音轨已落时间线音轨（${tl.pushed || 0} 段）`);
            } else {
              push("system", `⚠️ 配音已生成，但落轨失败：${tl.message || `${tl.failed || 0} 段未入轨`}`);
            }
          }
          break;
        }
        default:
          throw new Error(`未知 action: ${action}`);
      }

      push("system", `✅ 执行 ${action}${canvasNodeId ? ` → 节点 ${canvasNodeId}` : ""}`);
      await reply(true, canvasNodeId ? { canvas_node_id: canvasNodeId } : {});
    } catch (err: any) {
      const msg = err?.message || String(err);
      push("system", `❌ 执行 ${action} 失败: ${msg}`);
      await reply(false, { error: msg });
    }
  };

  // ── SSE 断线治理（2026-10-14）──────────────────────────────
  // 后端 session token 每次启动重建，旧 token 会让 /host/*（含 SSE）全 401；
  // 而 EventSource 自带无限自动重连 ⇒ 旧实现把每条失败都 push 成一条消息，
  // 刷满整屏「SSE 连接异常」。现改为：每轮断线最多 2 条提示；连续失败到第 3 次
  // 触发一次凭据自愈（重拉 inject.js）；自愈后凭据确有变化才重订阅（bridgeEpoch），
  // 连接恢复（onOpen）时重置计数并给一条恢复提示。
  const [bridgeEpoch, setBridgeEpoch] = useState(0);
  const sseFailRef = useRef(0);
  const sseHealedRef = useRef(false);

  useEffect(() => {
    if (!open) return undefined;
    const unsub = subscribeAgentEvents({
      onOpen: () => {
        const hadErr = sseFailRef.current > 0;
        sseFailRef.current = 0;
        sseHealedRef.current = false;
        if (hadErr) push("system", "✅ 已恢复与画布后端的连接");
      },
      onEvent: handleEditorEvent,
      onError: (err) => {
        sseFailRef.current += 1;
        const n = sseFailRef.current;
        if (n === 1) {
          push("system", `ℹ️ ${err}`);
        } else if (n === 3 && !sseHealedRef.current) {
          // 退避到第 3 次失败再自愈一次，避免无谓抖动；其余失败不再逐条刷屏。
          sseHealedRef.current = true;
          const before = bridgeToken();
          void refreshBridgeTokenFromInject().then((token) => {
            if (token && token !== before) {
              push("system", "🔑 连接凭据已失效，已刷新凭据，正在重新连接…");
              setBridgeEpoch((e) => e + 1);
            }
          });
        }
      },
    });
    return () => {
      try {
        unsub();
      } catch {
        /* ignore */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bridgeEpoch]);

  const refreshMcp = async () => {
    const ag = await getAgentStatus();
    setMcpOn(Boolean(ag.listening || (ag.ok && ag.token)));
    setMcpUrl(String(ag.url || ""));
  };

  const refreshModels = async () => {
    const [res] = await Promise.all([listChatModels(), refreshGenerationModels()]);
    const list = res.providers || [];
    setProviders(list);
    const stored = modelKey;
    if (stored) {
      // 校验：localStorage 里存的 provider 现在是否还 configured
      const [pid] = stored.split("::");
      const stillValid = list.some((p) => p.id === pid && p.configured);
      if (stillValid) return; // 用户选的还能用，尊重它
    }
    // 没存或存的已失效 → 用后端 active / 第一个 configured
    const active = list.find((p) => p.active && p.configured);
    const any = list.find((p) => p.configured);
    const pick = active || any;
    if (pick) {
      const m = pick.models[0] || "";
      setModelKey(m ? `${pick.id}::${m}` : `${pick.id}::`);
    }
  };

  const refreshTools = async () => {
    const res = await listProjectTools(agentMode);
    setTools(res.tools || []);
    if (res.message) setStatus(res.message);
  };

  const refreshBudget = async () => {
    setBudgetLoading(true);
    const BRIDGE = (window as any).__BRIDGE__ || "http://127.0.0.1:18765";
    try {
      const [budgetRes, callsRes] = await Promise.all([
        fetch(`${BRIDGE}/host/budget`),
        fetch(`${BRIDGE}/host/calls?limit=10`),
      ]);
      if (budgetRes.ok) {
        const j = await budgetRes.json();
        if (j.ok) setBudgetData(j.data);
      }
      if (callsRes.ok) {
        const j = await callsRes.json();
        if (j.ok) setRecentCalls(j.data || []);
      }
    } catch {
      setBudgetData(null);
    } finally {
      setBudgetLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void refreshMcp();
    void refreshModels();
    void refreshTools();
    const t = window.setInterval(() => void refreshMcp(), 10000);
    return () => window.clearInterval(t);
  }, [open]);

  const filteredTools = useMemo(() => {
    const q = toolFilter.trim().toLowerCase();
    if (!q) return tools.slice(0, 80);
    return tools
      .filter(
        (t) =>
          t.tool_name.toLowerCase().includes(q) ||
          t.extension_name.toLowerCase().includes(q) ||
          t.extension_id.toLowerCase().includes(q) ||
          (t.description || "").toLowerCase().includes(q),
      )
      .slice(0, 80);
  }, [tools, toolFilter]);

  /**
   * V4.41.19 AI 画布重组：80 行工具按 extension_type 自动分组 + 可折叠块。
   * 每组一个 <details>，默认前 2 组展开、其余折叠；搜索时自动全展开。
   */
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const groupedTools = useMemo(() => {
    const byType = new Map<string, ProjectTool[]>();
    filteredTools.forEach((t) => {
      const key = t.extension_type || "other";
      if (!byType.has(key)) byType.set(key, []);
      byType.get(key)!.push(t);
    });
    // 按类型名稳定排序，数量多的类型放前面
    return Array.from(byType.entries())
      .map(([type, items]) => ({ type, items }))
      .sort((a, b) => b.items.length - a.items.length || a.type.localeCompare(b.type));
  }, [filteredTools]);
  const toolFilterActive = toolFilter.trim().length > 0;

  const resolveModel = () => {
    if (!modelKey.includes("::")) return { provider: modelKey, model: "" };
    const [p, ...rest] = modelKey.split("::");
    return { provider: p, model: rest.join("::") };
  };

  const canvasContext = (extraAttaches?: Attach[]) => {
    const sel = nodes.find((n) => n.id === selectedId);
    const d = sel?.data as NodeData | undefined;
    const atts = extraAttaches || attaches;
    return {
      session_id: sid,
      agent_mode: agentMode,
      selected_id: selectedId,
      selected_kind: d?.kind,
      selected_title: d && "title" in d ? d.title : undefined,
      selected_prompt:
        d && "prompt" in d ? d.prompt : d && "text" in d ? d.text : undefined,
      selected_ref_video:
        d && "refVideoUrl" in d && d.refVideoUrl
          ? { url: d.refVideoUrl, name: (d as { refVideoName?: string }).refVideoName }
          : undefined,
      node_count: nodes.length,
      attachments: atts.map((a) => ({
        kind: a.kind,
        name: a.name,
        url: a.url.slice(0, 200),
      })),
    };
  };

  const runLocalOp = async (line: string): Promise<boolean> => {
    const t = line.trim();
    if (!t.startsWith("/")) return false;
    const [cmd, ...rest] = t.slice(1).split(/\s+/);
    const arg = rest.join(" ");
    if (cmd === "add") {
      const kind = (arg || "shot") as NodeData["kind"];
      const allowed = ["shot", "image", "video", "audio", "generator", "prompt", "script", "group"];
      if (!allowed.includes(kind)) {
        push("assistant", `未知节点类型：${kind}`);
        return true;
      }
      addNode(kind, nextFreeSlot(useCanvasStore.getState().nodes));
      push("assistant", `已添加节点：${kind}`);
      return true;
    }
    if (cmd === "sync") {
      const msg = await syncModelPool();
      push("assistant", msg);
      setStatus(msg);
      await refreshModels();
      return true;
    }
    if (cmd === "generate") {
      const sel = useCanvasStore.getState().selectedId;
      const ok = await askConfirm(
        "确认生成",
        sel
          ? "将调用 AIGC 生成当前选中节点（消耗模型额度）。确认后才执行。"
          : "当前没有选中节点，将自动挑选一个镜头/图片/视频节点生成（消耗模型额度）。确认后才执行。",
      );
      if (!ok) {
        push("assistant", "已取消生成，未改画布");
        return true;
      }
      onRequestGenerate();
      // 不再无条件说「已触发生成选中节点」：未选中时会自动挑节点，
      // 真实结果由 App 的状态栏/节点状态给出，这里只说已请求（2026-10-31）。
      push("assistant", sel ? "已触发生成选中节点" : "已触发生成（自动选择可生成节点）");
      return true;
    }
    if (cmd === "breakdown") {
      const ok = await askConfirm("确认拉片", "将按当前剧本拆镜并写入画布节点。确认后才执行。");
      if (!ok) {
        push("assistant", "已取消拉片，未改画布");
        return true;
      }
      onRequestBreakdown?.();
      push("assistant", "已触发一键拉片");
      return true;
    }
    if (cmd === "batch") {
      const ok = await askConfirm("确认批量生成", "将串行生成全部镜头/图/视频节点（消耗模型额度）。确认后才执行。");
      if (!ok) {
        push("assistant", "已取消批量生成");
        return true;
      }
      if (!onRequestBatchGenerate) {
        push("assistant", "当前画布未接线批量生成");
        return true;
      }
      onRequestBatchGenerate();
      push("assistant", "已触发批量生成");
      return true;
    }
    if (cmd === "tools") {
      await refreshTools();
      push("assistant", `已刷新工具列表：${tools.length}（见「工具」页）`);
      setTab("tools");
      return true;
    }
    if (cmd === "status") {
      const { provider, model } = resolveModel();
      push(
        "assistant",
        `会话=${sid}；项目模型=${provider || "自动"}${model ? "/" + model : ""}；画布MCP=${mcpOn ? mcpUrl : "未连"}；选中=${selectedId || "无"}；附件=${attaches.length}`,
      );
      return true;
    }
    if (cmd === "prompt" && selectedId) {
      updateNodeData(selectedId, { prompt: arg });
      push("assistant", "已更新选中节点提示词");
      return true;
    }
    push("assistant", `未知指令：/${cmd}`);
    return true;
  };

  const pickAttach = async (file: File) => {
    const isVid = file.type.startsWith("video/");
    const isImg = file.type.startsWith("image/");
    if (!isVid && !isImg) {
      push("system", "仅支持图片或视频附件");
      return;
    }
    setBusy(true);
    const res = await resolveMediaUrl(file);
    setBusy(false);
    if (!res.ok || !res.url) {
      push("system", res.message || "附件失败");
      return;
    }
    const att: Attach = {
      id: `att_${Math.random().toString(36).slice(2, 8)}`,
      kind: isVid ? "video" : "image",
      url: res.url,
      name: file.name,
    };
    setAttaches((a) => [...a, att].slice(-4));
    if (isVid) {
      push("system", `已附参考视频「${file.name}」。可点「挂到选中」或「落画布」。`);
    }
  };

  const attachToSelected = () => {
    const vid = [...attaches].reverse().find((a) => a.kind === "video");
    if (!vid) {
      push("system", "请先附上视频");
      return;
    }
    if (!selectedId) {
      push("system", "请先选中镜头/图片/视频节点");
      return;
    }
    const sel = nodes.find((n) => n.id === selectedId);
    const kind = (sel?.data as NodeData | undefined)?.kind;
    if (kind !== "shot" && kind !== "image" && kind !== "video") {
      push("system", "选中节点不支持参考视频槽");
      return;
    }
    updateNodeData(selectedId, { refVideoUrl: vid.url, refVideoName: vid.name });
    push("assistant", `已将「${vid.name}」挂到选中节点作参考视频`);
    setStatus(`参考视频 → ${vid.name}`);
  };

  const dropAttachToCanvas = () => {
    const vid = [...attaches].reverse().find((a) => a.kind === "video");
    if (!vid) {
      push("system", "请先附上视频");
      return;
    }
    addVideoReference(vid.url, { title: `参考·${vid.name}`, name: vid.name });
    push("assistant", `已在画布添加参考视频节点「${vid.name}」`);
  };

  const busyRef = useRef(false);
  const inboxRef = useRef<string[]>([]);

  const send = async (preset?: string) => {
    const text = (preset ?? input).trim();
    if (!text && !attaches.length) return;
    const payload =
      text ||
      (attaches.length
        ? `请结合附件（${attaches.map((a) => a.name).join("、")}）给当前分镜提建议`
        : "");
    if (busyRef.current) {
      inboxRef.current.push(payload);
      setInput("");
      push("system", `已排队（串行）：${payload.slice(0, 80)}`);
      return;
    }
    setInput("");
    const used = attaches.slice();
    push("user", payload, used);
    setAttaches([]);
    if (await runLocalOp(payload)) return;
    const streamId = `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
    activeStreamRef.current = streamId;
    streamBufRef.current[streamId] = "";
    upsertStreamMsg(streamId, "…", true);
    busyRef.current = true;
    setBusy(true);
    const { provider, model } = resolveModel();
    const res = await projectAgentChatViaHost({
      message: payload,
      provider,
      model,
      apply: false,
      mode: "canvas_fast",
      stream_id: streamId,
      agent_mode: agentMode,
      session_id: sid,
      canvas_context: canvasContext(used),
    });
    const finalText =
      res.reply ||
      streamBufRef.current[streamId] ||
      res.message ||
      "（空回复）";
    upsertStreamMsg(streamId, finalText, false);
    if (!res.ok) setStatus(res.message || "画布 Agent 失败");
    else if (res.path) setStatus(`Agent 快路径 · ${res.path}`);
    activeStreamRef.current = "";
    busyRef.current = false;
    setBusy(false);
    const nxt = inboxRef.current.shift();
    if (nxt) void send(nxt);
  };

  if (!open) return null;

  // 停靠规格（V4.40.50）：gridColumn 让它占最右两列。
  // V4.40.51 用户裁定「太大、占空间过多」⇒ 宽度不再钉死，回 CSS 弹性 minmax(280px,320px)
  // （比 LibTV 原档 300~360 收窄一档；剪辑 Agent 保持 360 —— 画布 Agent 是辅助，该小）。
  return (
    <aside
      className={`sg-agent-panel sg-agent-panel-wide${docked ? " sg-agent-dock" : ""}`}
      data-sg-no-autoclick="1"
      style={docked ? { gridColumn: "3 / -1" } : undefined}
    >
      <div className="sg-agent-head">
        <div className="sg-agent-brand">
          <strong>Agent-IM</strong>
          <span className="muted tiny">会话 {sid.slice(0, 10)}</span>
          {/* 2026-11-21：原生 select 弹层在 QtWebEngine 现白块 ⇒ 换前端渲染下拉 */}
          <SgSelect
            width={88}
            value={agentMode}
            title="Plan 只规划；协作 B 改画布需确认；自主 C 自动执行（生成不重试）"
            options={[
              { value: "collaborative", label: "协作 B" },
              { value: "plan", label: "Plan" },
              { value: "autonomous", label: "自主 C" },
            ]}
            onChange={(v) => {
              const m = v as AgentMode;
              setAgentMode(m);
              saveAgentMode(m);
              void controlAgentSession({ session_id: sid, action: "mode", mode: m });
              push(
                "system",
                m === "plan"
                  ? "已切 Plan：只分析/只读。"
                  : m === "autonomous"
                    ? "已切自主 C：画布写与生成将自动执行。"
                    : "已切协作 B：改画布/生成前会确认。",
              );
            }}
          />
        </div>
        <span className={providers.some((p) => p.configured) ? "chip-ok" : "chip-warn"}>
          {providers.find((p) => p.active)?.name || "模型管理"}
        </span>
        {/*
          头部瘦身（V4.34.0 · 第一步）：控制按钮**按状态显示**，不再常驻 3 个。
          忙碌 → 「暂停 / 停止」；空闲 → 「继续」（用于暂停后恢复）。任意时刻最多 2 个，头部更清爽。
        */}
        {busy ? (
          <>
            <button
              type="button"
              className="btn"
              title="暂停当前任务（点「继续」后才会再跑）"
              onClick={() => {
                void controlAgentSession({ session_id: sid, action: "pause" });
                busyRef.current = false;
                setBusy(false);
                setPaused(true);
                push("system", "已暂停。点「继续」后再发送。");
              }}
            >
              暂停
            </button>
            <button
              type="button"
              className="btn"
              title="停止当前 Agent 任务"
              onClick={() => {
                void controlAgentSession({ session_id: sid, action: "stop" });
                inboxRef.current = [];
                busyRef.current = false;
                setBusy(false);
                setPaused(false);
                push("system", "已停止跟踪（供应商若不支持远端取消，生成可能仍在跑）。");
              }}
            >
              停止
            </button>
          </>
        ) : paused ? (
          <button
            type="button"
            className="btn"
            title="继续任务 / 处理排队中的消息"
            onClick={() => {
              void controlAgentSession({ session_id: sid, action: "resume" });
              setPaused(false);
              push("system", "已继续。");
            }}
          >
            继续
          </button>
        ) : null}
        <button type="button" className="btn" onClick={onClose} title="收起侧栏">
          收起
        </button>
      </div>

      <div className="sg-agent-tabs">
        {/*
          2026-10-19（用户反馈「Agent UI 过于繁杂」）：页签去掉彩色 emoji，只留
          两字标签 —— 四个 emoji 颜色各异，在窄侧栏里比文字本身更抢眼。
          功能一个没删（对话/模型/工具/预算四页签全在）。
        */}
        {(
          [
            ["chat", "对话"],
            ["models", "模型"],
            ["tools", "工具"],
            ["budget", "预算"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`btn${tab === id ? " primary" : ""}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "chat" ? (
        <div className="sg-agent-chat">
          {/* V4.41.19 AI 画布重组：模型选择包进可折叠块。
              2026-10-19：默认**收起** —— 模型是一次性配置，每次打开都展开等于
              把「设置项」当主界面内容（用户反馈「过于繁杂」）。 */}
          <details className="sg-chat-section">
            <summary>⚙️ 对话模型</summary>
            <div className="sg-chat-section-body">
              <select value={modelKey} onChange={(e) => setModelKey(e.target.value)}>
                <option value="">自动 / 激活 Provider</option>
                {providers.map((p) =>
                  (p.models.length ? p.models : [""]).map((m) => (
                    <option
                      key={`${p.id}::${m}`}
                      value={`${p.id}::${m}`}
                      disabled={!p.configured}
                    >
                      {p.active ? "★ " : ""}
                      {p.name}
                      {m ? ` / ${m}` : ""}
                      {p.configured ? "" : "（未配置）"}
                    </option>
                  )),
                )}
              </select>
            </div>
          </details>

          <button
            type="button"
            className="chip"
            title="快捷提示词（点击展开/收起）"
            onClick={() => setChipsOpen((v) => !v)}
          >
            💡 快捷 {chipsOpen ? "▾" : "▸"}
          </button>
          {chipsOpen ? (
            <div className="sg-agent-chips">
              {QUICK.map((q) => (
                <button
                  key={q.id}
                  type="button"
                  className="chip"
                  disabled={busy}
                  onClick={() => void send(q.text)}
                >
                  {q.label}
                </button>
              ))}
              {onRequestBreakdown ? (
                <button
                  type="button"
                  className="chip"
                  disabled={busy}
                  onClick={() => void send("/breakdown")}
                >
                  拉片
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="sg-agent-msgs">
            {msgs.map((m, i) => (
              <div key={i} className={`sg-agent-msg ${m.role}${m.streaming ? " streaming" : ""}`}>
                {m.text}
                {m.streaming ? <span className="sg-agent-cursor">▍</span> : null}
                {m.attaches?.length ? (
                  <div className="sg-agent-msg-atts">
                    {m.attaches.map((a) =>
                      a.kind === "video" ? (
                        <video key={a.id} src={a.url} muted playsInline controls />
                      ) : (
                        <img key={a.id} src={a.url} alt={a.name} />
                      ),
                    )}
                  </div>
                ) : null}
              </div>
            ))}
            {busy ? (
              <div className="sg-agent-msg system">
                {thinkSec < 1 ? "连接模型…" : `生成中 ${thinkSec}s`}
              </div>
            ) : null}
            <div ref={msgsEndRef} />
          </div>

          {/* ── 画布引用可视化：让用户一眼看到 Agent 正在看什么 ── */}
          {(() => {
            const selNodes = nodes.filter((n) => n.selected);
            const primarySel = nodes.find((n) => n.id === selectedId);
            const showNodes = selNodes.length > 0 ? selNodes : primarySel ? [primarySel] : [];
            const totalNodes = nodes.length;
            const withImg = nodes.filter((n) => {
              const d = n.data as NodeData;
              const hasImg =
                ("imageUrl" in d && Boolean(d.imageUrl)) ||
                ("videoUrl" in d && Boolean(d.videoUrl)) ||
                ("posterUrl" in d && Boolean(d.posterUrl));
              return Boolean(d.kind) && hasImg;
            }).length;
            const kindCount: Record<string, number> = {};
            nodes.forEach((n) => {
              const k = (n.data as NodeData).kind || "?";
              kindCount[k] = (kindCount[k] || 0) + 1;
            });
            const kindBadges = Object.entries(kindCount).slice(0, 5);
            if (showNodes.length === 0 && totalNodes === 0) return null;
            const kindText = kindBadges.map(([k, c]) => `${k}×${c}`).join(" ");
            return (
              <div className="sg-agent-canvas-ref" title="Agent 即将把这些画布上下文发给模型">
                {/* V4.40.53：默认收起成一行摘要（点标题行展开详情），底部不再挤一大张卡 */}
                <div
                  className="sg-agent-ref-header"
                  style={{ cursor: "pointer", userSelect: "none" }}
                  onClick={() => setRefOpen((v) => !v)}
                >
                  <span className="sg-agent-ref-title">
                    📋 画布引用
                    <span className="muted tiny">
                      {showNodes.length > 0
                        ? `选中 ${showNodes.length} 节点`
                        : `全画布 ${totalNodes} 节点`}
                    </span>
                  </span>
                  <span className="sg-agent-ref-summary muted tiny">
                    {kindText || `节点 ${totalNodes} · 带图/视频 ${withImg} · 连线 ${edges.length}`} {refOpen ? "▾" : "▸"}
                  </span>
                </div>
                {!refOpen ? null : showNodes.length > 0 ? (
                  <div className="sg-agent-ref-grid">
                    {showNodes.slice(0, 6).map((n) => {
                      const d = n.data as NodeData;
                      const thumb =
                        ("imageUrl" in d && d.imageUrl) ||
                        ("posterUrl" in d && d.posterUrl) ||
                        ("firstFrameUrl" in d && d.firstFrameUrl) ||
                        "";
                      const kindEmoji: Record<string, string> = {
                        shot: "🎬", image: "🖼", video: "🎥", script: "📜",
                        prompt: "✨", text: "📄", config: "⚙️", generator: "⚙",
                        group: "📦", audio: "🔊", music: "🎵",
                      };
                      return (
                        <div key={n.id} className="sg-agent-ref-card" title={`${d.kind} · ${("title" in d && d.title) || n.id}`}>
                          {thumb ? (
                            <img src={thumb} alt="" />
                          ) : (
                            <div className="sg-agent-ref-placeholder">
                              {kindEmoji[d.kind] || "•"}
                            </div>
                          )}
                          <span className="sg-agent-ref-kind">{d.kind}</span>
                        </div>
                      );
                    })}
                    {showNodes.length > 6 ? (
                      <div className="sg-agent-ref-more">+{showNodes.length - 6}</div>
                    ) : null}
                  </div>
                ) : (
                  <div className="sg-agent-ref-overview">
                    {kindBadges.map(([k, c]) => (
                      <span key={k} className="sg-agent-ref-badge">{k}×{c}</span>
                    ))}
                  </div>
                )}
              </div>
            );
          })()}

          {attaches.length ? (
            <div className="sg-agent-pending">
              {attaches.map((a) => (
                <span key={a.id} className="sg-agent-pending-item">
                  {a.kind === "video" ? "🎬" : "🖼"} {a.name}
                  <button
                    type="button"
                    className="linkish"
                    onClick={() => setAttaches((xs) => xs.filter((x) => x.id !== a.id))}
                  >
                    ×
                  </button>
                </span>
              ))}
              <button type="button" className="btn" onClick={attachToSelected}>
                挂到选中
              </button>
              <button type="button" className="btn" onClick={dropAttachToCanvas}>
                落画布
              </button>
            </div>
          ) : null}

          <div className="sg-agent-input">
            <label className="sg-agent-attach" title="附参考图/视频">
              📎
              <input
                type="file"
                accept="image/*,video/*"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) void pickAttach(f);
                }}
              />
            </label>
            <textarea
              value={input}
              placeholder="输入消息，Enter 发送，Shift+Enter 换行…"
              disabled={busy}
              rows={2}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <button
              type="button"
              className="sg-agent-send"
              disabled={busy}
              onClick={() => void send()}
            >
              {busy ? "…" : "发送"}
            </button>
          </div>
        </div>
      ) : null}

      {tab === "models" ? (
        <div className="sg-agent-scroll">
          <p className="muted" style={{ fontSize: 11 }}>
            本地与云端模型已合并在这里：先选生成模型，再用下方算力滑块决定本地／云端优先级。
          </p>
          <div className="btn-row" style={{ marginBottom: 4 }}>
            <button
              type="button"
              className="btn teal"
              onClick={async () => {
                setBusy(true);
                const msg = await syncModelPool();
                push("system", msg);
                await refreshModels();
                setBusy(false);
                setStatus(msg);
              }}
            >
              同步模型池
            </button>
            <button type="button" className="btn" onClick={() => void refreshModels()}>
              刷新
            </button>
          </div>

          <GenerationModelRows
            title="本地生图"
            models={localImageModels}
            selectedKey={genSelectedImageKey}
            onSelect={setGenImageKey}
            empty="未发现本地生图模型；请看启动日志中的 torch / 模型目录提示"
          />
          <GenerationModelRows
            title="本地生视频"
            models={localVideoModels}
            selectedKey={genSelectedVideoKey}
            onSelect={setGenVideoKey}
            empty="未发现本地视频模型"
          />

          <div className="section-title" style={{ marginTop: 12 }}>
            本地 / 云端算力
          </div>
          <ExecutionBiasChip embedded />

          <details className="sg-tool-group">
            <summary>
              <span className="sg-tool-group-title">云端 / 自动生成模型</span>
              <span className="sg-tool-group-count">
                {cloudImageModels.length} 图 · {cloudVideoModels.length} 视频
              </span>
            </summary>
            <div className="sg-tool-group-body">
              <GenerationModelRows
                title="云端生图"
                models={cloudImageModels}
                selectedKey={genSelectedImageKey}
                onSelect={setGenImageKey}
                empty="云端图像渠道未配置"
              />
              <GenerationModelRows
                title="云端 / 自动生视频"
                models={cloudVideoModels}
                selectedKey={genSelectedVideoKey}
                onSelect={setGenVideoKey}
                empty="云端视频渠道未配置"
              />
            </div>
          </details>

          <div className="section-title" style={{ marginTop: 12 }}>
            对话 Agent 模型
          </div>
          {providers.map((p) => (
            <div key={p.id} className="sg-tool-row">
              <div>
                <strong>
                  {p.active ? "★ " : ""}
                  {p.name}
                </strong>
                <div className="muted" style={{ fontSize: 11 }}>
                  {p.configured ? "已配置 Key" : "未配置"}
                  {p.is_local ? " · 本地" : ""} · 模型 {p.models.length}
                </div>
              </div>
              <button
                type="button"
                className="btn"
                disabled={!p.configured}
                onClick={() => setModelKey(`${p.id}::${p.models[0] || ""}`)}
              >
                选用
              </button>
            </div>
          ))}
          <div className="section-title" style={{ marginTop: 12 }}>
            画布 MCP（Codex :17371）
          </div>
          <p className="muted" style={{ fontSize: 11 }}>
            与项目对话分离。仅外部 MCP/Codex 需要时连接。
          </p>
          <div className="btn-row">
            <button
              type="button"
              className="btn"
              data-sg-no-autoclick="1"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                const r = await startCanvasAgent();
                push("system", r.message || (r.ok ? "画布 MCP 已连接" : "连接失败"));
                await refreshMcp();
                setBusy(false);
              }}
            >
              {mcpOn ? "MCP 已连接" : "连接画布MCP"}
            </button>
            <span className="muted" style={{ fontSize: 11 }}>
              {mcpUrl || ":17371"}
            </span>
          </div>
        </div>
      ) : null}

      {tab === "tools" ? (
        <div className="sg-agent-scroll">
          <p className="muted" style={{ fontSize: 11 }}>
            拓展中心 Skill / 插件（与剪辑 Agent 同源）。
          </p>
          <div className="btn-row" style={{ marginBottom: 6 }}>
            <input
              style={{ flex: 1 }}
              placeholder="搜索工具…"
              value={toolFilter}
              onChange={(e) => setToolFilter(e.target.value)}
            />
            <button type="button" className="btn" onClick={() => void refreshTools()}>
              刷新
            </button>
          </div>
          {filteredTools.length === 0 ? (
            <p className="muted">暂无工具。请打开一次「拓展中心」或「剪辑」页。</p>
          ) : (
            /* V4.41.19 AI 画布重组：按 extension_type 分组折叠，替代 80 行平铺 */
            groupedTools.map((g) => {
              const gOpen = toolFilterActive
                ? true
                : collapsedGroups[g.type] === undefined
                  ? groupedTools.findIndex((x) => x.type === g.type) < 2
                  : !collapsedGroups[g.type];
              return (
                <details
                  key={g.type}
                  className="sg-tool-group"
                  open={gOpen}
                  onToggle={(e) => {
                    const el = e.target as HTMLDetailsElement;
                    if (!toolFilterActive && collapsedGroups[g.type] === undefined && el.open) return;
                    setCollapsedGroups((m) => ({ ...m, [g.type]: !el.open }));
                  }}
                >
                  <summary>
                    <span className="sg-tool-group-title">{g.type}</span>
                    <span className="sg-tool-group-count">{g.items.length} 项</span>
                  </summary>
                  <div className="sg-tool-group-body">
                    {g.items.map((t) => (
                      <div key={`${t.extension_id}:${t.tool_id}`} className="sg-tool-row">
                        <div>
                          <strong>{t.tool_name || t.tool_id}</strong>
                          <div className="muted" style={{ fontSize: 11 }}>
                            {t.extension_name}
                            {t.description ? ` — ${t.description.slice(0, 60)}` : ""}
                          </div>
                        </div>
                        <button
                          type="button"
                          className="btn"
                          disabled={busy}
                          onClick={async () => {
                            setBusy(true);
                            const res = await runProjectToolViaHost({
                              extension_id: t.extension_id,
                              tool_id: t.tool_id,
                              skill_id: t.extension_type === "skill" ? t.extension_id : "",
                              agent_mode: agentMode,
                              session_id: sid,
                              approved: true,
                            });
                            push(
                              "assistant",
                              `运行 ${t.tool_name}: ${res.message || (res.ok ? "完成" : "失败")}`,
                            );
                            setTab("chat");
                            setBusy(false);
                          }}
                        >
                          运行
                        </button>
                      </div>
                    ))}
                  </div>
                </details>
              );
            })
          )}
        </div>
      ) : null}
      {tab === "budget" ? (
        <div className="sg-agent-scroll">
          <div className="btn-row" style={{ marginBottom: 10, gap: 6 }}>
            <button type="button" className="btn" onClick={() => void refreshBudget()}>
              {budgetLoading ? "加载中…" : "刷新数据"}
            </button>
            <button
              type="button"
              className="btn"
              onClick={async () => {
                const v = window.prompt("设置预算上限（元，0 = 不限制）", String(budgetData?.budget_limit || 0));
                if (v == null) return;
                const limit = parseFloat(v) || 0;
                try {
                  await fetch(`${BRIDGE}/host/budget/set`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-Shiguang-Token": sessionStorage.getItem("sg_token") || "" },
                    body: JSON.stringify({ budget_limit: limit, project_budget: 0 }),
                  });
                  push("system", `预算上限已设置为 ¥${limit.toFixed(2)}`);
                  await refreshBudget();
                } catch {
                  push("system", "设置失败，请确认桥已连通");
                }
              }}
              disabled={!budgetData}
            >
              设置预算
            </button>
            {budgetData?.over_budget ? (
              <span style={{ color: "#ef4444", fontSize: 11, alignSelf: "center" }}>⚠️ 已超支</span>
            ) : null}
          </div>
          {!budgetData ? (
            <p className="muted" style={{ fontSize: 12 }}>
              {budgetLoading ? "连接 budget 端点中…" : "预算数据不可用。请确认剪辑服务已启动。"}
            </p>
          ) : (
            <>
              {/* 总览卡（画布为单一深色主题，沿用既有 inline 配色，不动冻结区 styles.css） */}
              <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
                <div className="sg-budget-card" style={{ background: "#1e293b" }}>
                  <div className="sg-budget-label">累计成本</div>
                  <div className="sg-budget-value" style={{ color: budgetData.over_budget ? "#ef4444" : "#22d3ee" }}>
                    ¥ {budgetData.total_cost.toFixed(4)}
                  </div>
                </div>
                <div className="sg-budget-card" style={{ background: "#1e293b" }}>
                  <div className="sg-budget-label">NG 次数</div>
                  <div className="sg-budget-value" style={{ color: "#f59e0b" }}>{budgetData.ng_count}</div>
                </div>
                {budgetData.budget_limit > 0 ? (
                  <div className="sg-budget-card" style={{ background: "#1e293b" }}>
                    <div className="sg-budget-label">预算上限</div>
                    <div className="sg-budget-value">¥ {budgetData.budget_limit.toFixed(2)}</div>
                  </div>
                ) : null}
              </div>
              {/* Provider 详情 */}
              {Object.keys(budgetData.providers || {}).length > 0 ? (
                <div>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>按 Provider 聚合</div>
                  {Object.entries(budgetData.providers).map(([p, v]: [string, any]) => (
                    <div key={p} className="sg-budget-row">
                      <strong>{p}</strong>
                      <span className="muted">
                        {v.calls} 次 · {v.tokens?.toLocaleString?.() || v.tokens} tokens · 成功率 {(v.success_rate * 100).toFixed(0)}%
                      </span>
                      <span className="sg-budget-cost">¥ {v.cost.toFixed(4)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted" style={{ fontSize: 12 }}>暂无 AI 调用记录。</p>
              )}
              {/* 最近调用 */}
              {recentCalls.length > 0 ? (
                <div style={{ marginTop: 12 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>最近 {recentCalls.length} 次调用</div>
                  {recentCalls.map((c, i) => (
                    <div key={i} className="sg-budget-row">
                      <strong>{c.provider}</strong>
                      <span className="muted">
                        {c.model} · {c.prompt_tokens}+{c.completion_tokens} tokens · {c.duration_ms?.toFixed?.(0) || c.duration_ms}ms
                      </span>
                      <span className="sg-budget-cost">¥ {c.cost?.toFixed?.(4) || c.cost}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}
      <ConfirmDialog
        open={!!confirmBox}
        title={confirmBox?.title}
        message={confirmBox?.message || ""}
        danger={confirmBox?.danger}
        confirmLabel="执行"
        cancelLabel="取消"
        onConfirm={() => {
          confirmBox?.resolve(true);
          setConfirmBox(null);
        }}
        onCancel={() => {
          confirmBox?.resolve(false);
          setConfirmBox(null);
        }}
      />
    </aside>
  );
}
