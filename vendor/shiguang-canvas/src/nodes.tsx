import React, { createContext, memo, useContext, useRef, useState, type ReactNode } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import type { NodeData, NodeStatus } from "./store";
import { useCanvasStore } from "./store";

/** 节点全局动作上下文 — 由 App.tsx 注入 retryNode 等方法，节点组件通过它触发生成/重试 */
export const NodeActionsContext = createContext<{
  /** 重试指定节点（内部会自动 select + 调 generateForNode） */
  retryNode?: (nodeId: string) => void;
}>({});
const useNodeActions = () => useContext(NodeActionsContext);

/**
 * 节点浅比较：仅比较影响视觉输出的 selected / data / dragging，
 * position 等由 ReactFlow 每帧传入新引用但不影响 JSX，忽略。
 */
function nodePropsEqual(prev: NodeProps, next: NodeProps): boolean {
  return (
    prev.selected === next.selected &&
    prev.dragging === next.dragging &&
    prev.data === next.data
  );
}

/** 状态标签（英文枚举 → 中文短标签） */
const MOVEMENT_LABELS: Record<string, string> = {
  "push-in": "推近",
  "pull-out": "拉远",
  "pan-left": "左摇",
  "pan-right": "右摇",
  "tilt-up": "上仰",
  "tilt-down": "下俯",
  "dolly": "跟移",
  "crane": "升降",
  "static": "固定",
};

const CAMERA_LABELS: Record<string, string> = {
  "arri-alexa": "ARRI",
  "red-komodo": "RED",
  "sony-cinealta": "CineAlta",
  "iphone": "iPhone",
};

const STATUS_LABELS: Record<NodeStatus, { dot: string; text: string; title: string }> = {
  idle: { dot: "○", text: "待执行", title: "尚未加入生成队列" },
  generating: { dot: "◉", text: "生成中", title: "正在生成，点击节点查看进度" },
  success: { dot: "✓", text: "成功", title: "生成成功" },
  failed: { dot: "✕", text: "失败", title: "生成失败，点击节点查看错误信息" },
};

/** 状态小圆点 — 渲染在节点标题右侧 */
function NodeStatusBadge({ status, progress, errorMessage }: {
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
}) {
  if (!status || status === "idle") return null;
  const meta = STATUS_LABELS[status];
  const titleTooltip = status === "failed" && errorMessage
    ? `${meta.title}：${errorMessage}`
    : status === "generating" && progress != null
      ? `${meta.title} · ${Math.round(progress)}%`
      : meta.title;
  return (
    <span className={`sg-status-badge sg-status-${status}`} title={titleTooltip}>
      {meta.dot}
      {status === "generating" && progress != null
        ? <span className="sg-status-progress">{Math.round(progress)}</span>
        : null}
    </span>
  );
}

/** Shot 节点镜头语言参数 tag 组 — 显示运镜/焦段/光圈/机型 */
function ShotParamsTag({ data }: { data: Extract<NodeData, { kind: "shot" }> }) {
  const tags: string[] = [];
  if (data.movement) tags.push(MOVEMENT_LABELS[data.movement] || data.movement);
  if (data.focalLength) tags.push(`${data.focalLength}mm`);
  if (data.cameraYaw != null && Math.abs(data.cameraYaw) >= 5) {
    tags.push(`环${data.cameraYaw > 0 ? "右" : "左"}${Math.abs(data.cameraYaw)}°`);
  }
  if (data.cameraPitch != null && Math.abs(data.cameraPitch) >= 5) {
    tags.push(data.cameraPitch < 0 ? "俯拍" : "仰拍");
  }
  if (data.aperture) tags.push(`f/${data.aperture}`);
  if (data.cameraPreset) tags.push(CAMERA_LABELS[data.cameraPreset] || data.cameraPreset);
  if (!tags.length) return null;
  return (
    <div className="sg-shot-tags">
      {tags.map((t) => <span key={t} className="sg-shot-tag">{t}</span>)}
    </div>
  );
}

// ── 节点首次使用提示（降学习成本）─────────────────────────────────────────

const NODE_HINT_KEY = "sg-canvas-hints-seen";

/** 每种节点类型的新手提示文案 */
const HINT_MAP: Record<string, string> = {
  shot: "💡 镜头节点：填写 Prompt → 点底部「生成选中」开始生图/生视频",
  script: "💡 剧本节点：写剧本大纲 → 按 Enter 自动拆成分镜镜头节点",
  prompt: "💡 提示词节点：写风格/氛围 → 连到镜头节点自动附加到 Prompt",
  image: "💡 图片节点：拖入参考图 / 点「生成选中」生成参考图",
  video: "💡 视频节点：拖入参考视频 → 或导入视频片段",
  text: "💡 文本节点：可存复用提示词、角色台词、说明文字",
  config: "💡 生成配置：设模型/张数/风格，连到多个镜头节点生效",
  generator: "💡 生成器：一键批量生成下游所有镜头节点",
  group: "💡 编组节点：圈选多个节点后 Ctrl+G 编组，Ctrl+Shift+G 解组",
  audio: "💡 音频节点：拖入 BGM/配音 → 或导入音频文件",
  music: "💡 音乐节点：填写风格/歌词 → 调 Suno 生成原创音乐",
};

/** 记忆"某节点类型提示已关闭"的 hook（首次渲染读 localStorage，关闭后立即持久化） */
function useNodeHintSeen(kind: string): { seen: boolean; markSeen: () => void } {
  const [seen, setSeen] = React.useState(() => {
    try {
      const raw = localStorage.getItem(NODE_HINT_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) && arr.includes(kind);
    } catch {
      return false;
    }
  });
  const markSeen = React.useCallback(() => {
    setSeen(true);
    try {
      const raw = localStorage.getItem(NODE_HINT_KEY);
      const arr = raw ? JSON.parse(raw) : [];
      const next = Array.isArray(arr) ? arr.filter((x: string) => x !== kind) : [];
      next.push(kind);
      localStorage.setItem(NODE_HINT_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }, [kind]);
  return { seen, markSeen };
}

/**
 * 可复用内联文本编辑器：双击 div 切换为 textarea 编辑，
 * 失焦 / Ctrl+Enter 提交到 store，Esc 取消。
 * textarea 内部 stopPropagation 防止 ReactFlow 把点击当成节点拖拽。
 */
function EditableText({
  nodeId,
  value,
  field,
  placeholder = "双击输入文字…",
  rows = 3,
  maxLength,
  fontSize,
}: {
  nodeId: string;
  value: string;
  field: string;
  placeholder?: string;
  rows?: number;
  maxLength?: number;
  fontSize?: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const commit = () => {
    const next = draft.trimEnd();
    if (next !== value) {
      useCanvasStore.getState().updateNodeData(nodeId, { [field]: next });
    }
    setEditing(false);
  };

  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDraft(value);
    setEditing(true);
    setTimeout(() => textareaRef.current?.focus(), 0);
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      cancel();
    } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      commit();
    }
    // 普通 Enter 允许换行，不拦截
  };

  if (editing) {
    return (
      <textarea
        ref={textareaRef}
        className="sg-editable-textarea"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={handleKeyDown}
        onPointerDown={handlePointerDown}
        onMouseDown={handleMouseDown}
        placeholder={placeholder}
        rows={rows}
        maxLength={maxLength}
        style={fontSize ? { fontSize } : undefined}
      />
    );
  }

  const displayText = value || placeholder;
  const isPlaceholder = !value;

  return (
    <div
      className={`sg-editable-display${isPlaceholder ? " sg-editable-placeholder" : ""}`}
      onDoubleClick={handleDoubleClick}
      title="双击编辑"
      style={fontSize ? { fontSize } : undefined}
    >
      {displayText}
    </div>
  );
}

/** 通用 Shell — 带状态 badge + 首次使用提示条 + 失败重试按钮 */
function Shell({
  nodeId,
  selected,
  kind,
  title,
  status,
  progress,
  errorMessage,
  children,
}: {
  nodeId: string;
  selected?: boolean;
  kind: string;
  title: string;
  status?: NodeStatus;
  progress?: number;
  errorMessage?: string;
  children: ReactNode;
}) {
  const hint = HINT_MAP[kind];
  const { seen, markSeen } = useNodeHintSeen(kind);
  const showHint = hint && !seen;
  const { retryNode } = useNodeActions();

  const canRetry = status === "failed" && !!retryNode;

  return (
    <div className={`sg-node ${kind}${selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>{title}</span>
        <div className="head-actions">
          <NodeStatusBadge status={status} progress={progress} errorMessage={errorMessage} />
          {canRetry ? (
            <button
              type="button"
              className="sg-retry-btn"
              title={`重试生成${errorMessage ? ` · ${errorMessage.slice(0, 40)}` : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                retryNode!(nodeId);
              }}
            >
              ↻
            </button>
          ) : null}
        </div>
      </div>
      {showHint ? (
        <div
          className="sg-node-hint"
          onClick={(e) => {
            e.stopPropagation();
            markSeen();
          }}
          title="点击关闭此提示"
        >
          {hint}
          <span className="sg-node-hint-close">✕</span>
        </div>
      ) : null}
      {canRetry ? (
        <div className="sg-node-error" title={errorMessage}>
          ✕ {errorMessage || "生成失败"}
        </div>
      ) : null}
      <div className="body">{children}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function StackBadge({ count }: { count?: number }) {
  if (!count || count < 2) return null;
  return <span className="stack-badge">{count}</span>;
}

export const ShotNode = memo(function ShotNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "shot" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="shot" title={`🎬 ${d.title || "镜头"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      {d.imageUrl ? (
        <div className="img-wrap">
          <img src={d.imageUrl} alt="" />
          <StackBadge count={d.images?.length} />
        </div>
      ) : null}
      <ShotParamsTag data={d} />
      <div className="frame-row">
        {d.firstFrameUrl ? <img className="frame-thumb" src={d.firstFrameUrl} alt="首帧" /> : null}
        {d.lastFrameUrl ? <img className="frame-thumb" src={d.lastFrameUrl} alt="尾帧" /> : null}
        {d.refVideoUrl ? <span className="ref-vid-badge">参考视频</span> : null}
      </div>
      <div>
        {d.shotSize} · {d.duration}s
        {d.seed != null ? <span className="sg-meta-tiny"> · seed:{d.seed}</span> : null}
      </div>
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入镜头提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const ScriptNode = memo(function ScriptNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "script" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="script" title={`📜 ${d.title || "剧本"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      <EditableText nodeId={id} value={d.content || ""} field="content" rows={5}
        placeholder="双击撰写剧本大纲…" />
    </Shell>
  );
}, nodePropsEqual);

export const ImageNode = memo(function ImageNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "image" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="image" title={`🖼️ ${d.title || "图片"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      {d.imageUrl ? (
        <div className="img-wrap">
          <img src={d.imageUrl} alt="" />
          <StackBadge count={d.images?.length} />
        </div>
      ) : (
        <div className="meta">未生成</div>
      )}
      {d.seed != null ? <div className="sg-meta-tiny">seed:{d.seed}</div> : null}
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入生图提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const VideoNode = memo(function VideoNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "video" }>;
  const stackCount = d.videos?.length || (d.videoUrl ? 1 : 0);
  return (
    <Shell
      nodeId={id}
      selected={selected}
      kind="video"
      title={`${d.isReference ? "📎" : "🎥"} ${d.title || (d.isReference ? "参考视频" : "视频")}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}
    >
      {d.videoUrl ? (
        <div className="img-wrap">
          <video src={d.videoUrl} muted playsInline controls />
          <StackBadge count={stackCount} />
        </div>
      ) : d.posterUrl ? (
        <img src={d.posterUrl} alt="" />
      ) : (
        <div className="meta">未生成</div>
      )}
      <div className="frame-row">
        {d.firstFrameUrl ? <img className="frame-thumb" src={d.firstFrameUrl} alt="首帧" /> : null}
        {d.lastFrameUrl ? <img className="frame-thumb" src={d.lastFrameUrl} alt="尾帧" /> : null}
        {d.isReference || d.refVideoUrl ? <span className="ref-vid-badge">参考</span> : null}
      </div>
      {(d.motionStrength != null || d.consistency != null) ? (
        <div className="sg-video-tags">
          {d.motionStrength != null && <span className="sg-shot-tag">动{d.motionStrength}</span>}
          {d.consistency != null && <span className="sg-shot-tag">稳{d.consistency}</span>}
          {d.firstFrameWeight != null && <span className="sg-shot-tag">首帧{d.firstFrameWeight}</span>}
          {d.lastFrameWeight != null && <span className="sg-shot-tag">尾帧{d.lastFrameWeight}</span>}
        </div>
      ) : null}
      {(d.duration || d.seed != null) ? (
        <div className="sg-meta-tiny">
          {d.duration ? `${d.duration}s` : ""}
          {d.duration && d.seed != null ? " · " : ""}
          {d.seed != null ? `seed:${d.seed}` : ""}
        </div>
      ) : null}
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入生视频提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const PromptNode = memo(function PromptNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "prompt" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="prompt" title={`✨ ${d.title || "提示词"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      <EditableText nodeId={id} value={d.text || ""} field="text" rows={3}
        placeholder="双击输入风格 / 氛围提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const TextNode = memo(function TextNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "text" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="text" title={`📄 ${d.title || "文本"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      <EditableText nodeId={id} value={d.content || ""} field="content" rows={3}
        placeholder="双击输入文字内容…" fontSize={d.fontSize || 14} />
    </Shell>
  );
}, nodePropsEqual);

export const ConfigNode = memo(function ConfigNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "config" }>;
  const modeLabel =
    d.generationMode === "video"
      ? "视频"
      : d.generationMode === "audio"
        ? "音频"
        : d.generationMode === "text"
          ? "文本"
          : "图片";
  return (
    <Shell nodeId={id} selected={selected} kind="config" title={`⚙️ ${d.title || "生成配置"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      <div>
        {modeLabel}
        {d.count != null && d.count > 1 ? ` · ×${d.count}` : ""}
        {d.model ? <span className="sg-shot-tag">{d.model}</span> : null}
      </div>
      <EditableText nodeId={id} value={d.prompt || d.content || ""} field={d.prompt != null ? "prompt" : "content"} rows={2}
        placeholder="双击输入配置提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const GeneratorNode = memo(function GeneratorNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "generator" }>;
  const outputKindLabel = d.outputKind ? (d.outputKind === "image" ? "图" : "视频") : null;
  return (
    <Shell nodeId={id} selected={selected} kind="generator" title={`⚙️ ${d.title || "生成器"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      <div>
        {d.mode} · ×{d.count || 1}
        {d.autoCollectUpstream && <span className="sg-shot-tag">汇聚</span>}
        {outputKindLabel && <span className="sg-shot-tag">{outputKindLabel}</span>}
      </div>
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入生成器统一提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const GroupNode = memo(function GroupNode({ data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "group" }>;
  return (
    <div className={`sg-node group${selected ? " selected" : ""}`}>
      <NodeResizer minWidth={200} minHeight={120} />
      <div className="head">📦 {d.title || "编组"}</div>
    </div>
  );
}, nodePropsEqual);

export const AudioNode = memo(function AudioNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "audio" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="audio" title={`🔊 ${d.title || "音频"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      {d.audioUrl ? (
        <audio src={d.audioUrl} controls preload="metadata" />
      ) : (
        <div className="meta">未上传 / 未生成</div>
      )}
      {d.seed != null ? <div className="sg-meta-tiny">seed:{d.seed}</div> : null}
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入音频生成提示词…" />
    </Shell>
  );
}, nodePropsEqual);

export const MusicNode = memo(function MusicNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "music" }>;
  return (
    <Shell nodeId={id} selected={selected} kind="music" title={`🎵 ${d.title || "音乐"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      {d.audioUrl ? (
        <audio src={d.audioUrl} controls preload="metadata" />
      ) : (
        <div className="meta">未生成</div>
      )}
      {d.model ? <span className="sg-shot-tag">{d.model}</span> : null}
      <div className="sg-editable-label">风格</div>
      <EditableText nodeId={id} value={d.style || ""} field="style" rows={1}
        placeholder="双击输入音乐风格…" />
      <div className="sg-editable-label">提示词</div>
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入音乐描述…" />
      <div className="sg-editable-label">歌词</div>
      <EditableText nodeId={id} value={d.lyrics || ""} field="lyrics" rows={3}
        placeholder="双击输入歌词（可选）…" />
    </Shell>
  );
}, nodePropsEqual);

export const nodeTypes = {
  shot: ShotNode,
  script: ScriptNode,
  image: ImageNode,
  video: VideoNode,
  prompt: PromptNode,
  text: TextNode,
  config: ConfigNode,
  generator: GeneratorNode,
  group: GroupNode,
  audio: AudioNode,
  music: MusicNode,
};
