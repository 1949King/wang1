import { describeImageSize } from "./imageSize";
import React, { createContext, memo, useContext, useRef, useState, type ReactNode } from "react";
import { Handle, Position, type NodeProps, NodeResizer } from "@xyflow/react";
import type { NodeData, NodeStatus } from "./store";
import { useCanvasStore } from "./store";
import { pickVideoPoster } from "./videoFallback";
import { useVideoBad, VideoUnplayable } from "./videoUnplayable";
// 节点内「生成」按钮样式（独立文件：styles.css 在冻结区，不该为一个小按钮动它）
import "./nodeActions.css";

/** 节点全局动作上下文 — 由 App.tsx 注入，节点组件通过它触发生成/重试 */
export const NodeActionsContext = createContext<{
  /** 重试指定节点（内部会自动 select + 调 generateForNode） */
  retryNode?: (nodeId: string) => void;
  /** 对指定节点发起生成 —— 与 retryNode 同一实现，语义用于「首次生成」按钮。
   *  存在的意义：生成不再依赖画布全局 selected，用户在节点内填完词可直接点按钮。 */
  generateNode?: (nodeId: string) => void;
}>({});
const useNodeActions = () => useContext(NodeActionsContext);

/**
 * 支持「一键生成」的节点类型 —— 与 App.tsx 的 onGenerate 白名单保持同口径。
 * 不在此列的节点（剧本 / 提示词 / 文本 / 编组 / 配置）不显示生成按钮。
 */
const GENERATABLE_KINDS = new Set([
  "shot",
  "image",
  "video",
  "generator",
  "audio",
  "music",
  "director",
  "animation",
  "panorama",
  "digitalHuman",
]);

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
  shot: "💡 镜头节点：填写 Prompt → 点卡片下方「✦ 生成」开始生图/生视频",
  script: "💡 剧本节点：写剧本大纲 → 按 Enter 自动拆成分镜镜头节点",
  prompt: "💡 提示词节点：写风格/氛围 → 连到镜头节点自动附加到 Prompt",
  image: "💡 图片节点：拖入参考图 → 点卡片下方「✦ 生成」出图",
  video: "💡 视频节点：拖入参考视频 → 或导入视频片段",
  text: "💡 文本节点：可存复用提示词、角色台词、说明文字",
  config: "💡 生成配置：设模型/张数/风格，连到多个镜头节点生效",
  generator: "💡 生成器：一键批量生成下游所有镜头节点",
  group: "💡 编组节点：圈选多个节点后 Ctrl+G 编组，Ctrl+Shift+G 解组",
  audio: "💡 音频节点：拖入 BGM/配音 → 或导入音频文件",
  music: "💡 音乐节点：Suno 一键出曲；切 YuE 可先生成可编辑乐谱再渲染整曲",
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

/**
 * 通用 Shell — 带状态 badge + 首次使用提示条 + 失败重试按钮 + **节点内生成按钮**。
 *
 * 生成按钮（2026-10-31 加）：此前生成入口只在顶栏 ☰ 菜单与浮动面板里，且要求
 * 「先选中节点」，而节点内提示却写「点底部生成选中」⇒ 用户照着找必然找不到。
 * 这里把入口放回节点本身：按钮自带 nodeId，不依赖画布全局 selected，
 * 放卡 → 填词 → 点按钮即可生成。仅在 `GENERATABLE_KINDS` 显示，generating 时禁用。
 */
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
  const { retryNode, generateNode } = useNodeActions();

  const canRetry = status === "failed" && !!retryNode;
  const generating = status === "generating";
  const canGenerate = GENERATABLE_KINDS.has(kind) && !!generateNode;

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
      {canGenerate ? (
        <div className="sg-node-actions">
          <button
            type="button"
            className="sg-gen-btn"
            disabled={generating}
            title={generating ? "正在生成…" : "对此节点生成（不需要先选中节点）"}
            onClick={(e) => {
              e.stopPropagation();
              generateNode!(nodeId);
            }}
          >
            {generating ? (
              <span className="sg-gen-label">
                <span className="sg-gen-dot" />
                生成中…
              </span>
            ) : (
              "✦ 生成"
            )}
          </button>
        </div>
      ) : null}
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

/** L1 导演参数面板 — 生成卡内嵌（spec §7.2：画质/时长/运动幅度/相似度，提示词走下方 EditableText） */
function DirectorL1Panel({ nodeId, d }: {
  nodeId: string;
  d: Extract<NodeData, { kind: "video" }>;
}) {
  const set = (patch: Record<string, unknown>) =>
    useCanvasStore.getState().updateNodeData(nodeId, patch);

  const qualityOptions = [
    { key: "draft", label: "草稿" },
    { key: "standard", label: "标准" },
    { key: "fine", label: "精修" },
    { key: "cinema", label: "电影级" },
  ] as const;
  const motionOptions = [
    { key: 30, label: "小" },
    { key: 60, label: "中" },
    { key: 90, label: "大" },
  ] as const;

  const currentQuality = d.qualityTier ?? "standard";
  // 分辨率档位（2026-10-27）：与意图卡片/后端同口径（长边 ≤ 768/832/1024）
  const currentSize = describeImageSize(String((d as { aspect?: string }).aspect || "1:1"), currentQuality);
  const currentMotion = d.motionStrength ?? 60;
  const currentConsistency = d.consistency ?? 75;
  const currentDuration = d.duration ?? 5;

  return (
    <div className="sg-l1-panel nodrag">
      <div className="sg-l1-row">
        <span className="sg-l1-label">画质 · {currentSize}</span>
        <div className="sg-l1-seg">
          {qualityOptions.map((q) => (
            <button
              key={q.key}
              type="button"
              className={`sg-l1-seg-btn${currentQuality === q.key ? " active" : ""}`}
              onClick={() => set({ qualityTier: q.key })}
            >
              {q.label}
            </button>
          ))}
        </div>
      </div>
      <div className="sg-l1-row">
        <span className="sg-l1-label">时长</span>
        <input
          type="range"
          min={2}
          max={30}
          step={1}
          value={currentDuration}
          onChange={(e) => set({ duration: Number(e.target.value) })}
          className="sg-l1-range"
        />
        <span className="sg-l1-val">{currentDuration}s</span>
      </div>
      <div className="sg-l1-row">
        <span className="sg-l1-label">运动</span>
        <div className="sg-l1-seg">
          {motionOptions.map((m) => (
            <button
              key={m.key}
              type="button"
              className={`sg-l1-seg-btn${currentMotion === m.key ? " active" : ""}`}
              onClick={() => set({ motionStrength: m.key })}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      <div className="sg-l1-row">
        <span className="sg-l1-label">相似度</span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={currentConsistency}
          onChange={(e) => set({ consistency: Number(e.target.value) })}
          className="sg-l1-range"
        />
        <span className="sg-l1-val">{currentConsistency}%</span>
      </div>
    </div>
  );
}

export const VideoNode = memo(function VideoNode({ id, data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "video" }>;
  const stackCount = d.videos?.length || (d.videoUrl ? 1 : 0);
  // 画布内核没有 H.264 ⇒ mp4 的 <video> 必然报错，退回首帧图 + 说清原因（见 videoFallback.ts）
  const vbad = useVideoBad();
  return (
    <Shell
      nodeId={id}
      selected={selected}
      kind="video"
      title={`${d.isReference ? "📎" : "🎥"} ${d.title || (d.isReference ? "参考视频" : "视频")}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}
    >
      {d.videoUrl ? (
        vbad.bad ? (
          <VideoUnplayable poster={pickVideoPoster(d.posterUrl, d.firstFrameUrl, d.lastFrameUrl)} />
        ) : (
          <div className="img-wrap">
            <video src={d.videoUrl} muted playsInline controls onError={vbad.onError} />
            <StackBadge count={stackCount} />
          </div>
        )
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
      {!d.isReference ? (
        <DirectorL1Panel nodeId={id} d={d} />
      ) : null}
      {d.firstFrameWeight != null || d.lastFrameWeight != null ? (
        <div className="sg-video-tags">
          {d.firstFrameWeight != null && <span className="sg-shot-tag">首帧{d.firstFrameWeight}</span>}
          {d.lastFrameWeight != null && <span className="sg-shot-tag">尾帧{d.lastFrameWeight}</span>}
        </div>
      ) : null}
      {d.seed != null ? <div className="sg-meta-tiny">seed:{d.seed}</div> : null}
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
  const isYue = d.engine === "yue";
  return (
    <Shell nodeId={id} selected={selected} kind="music"
      title={`🎵 ${d.title || "音乐"}`}
      status={d.status} progress={d.progress} errorMessage={d.errorMessage}>
      {d.audioUrl ? (
        <audio src={d.audioUrl} controls preload="metadata" />
      ) : (
        <div className="meta">未生成</div>
      )}
      <span className="sg-shot-tag">{isYue ? "YuE · 符号规划" : d.model || "Suno"}</span>
      <div className="sg-editable-label">风格</div>
      <EditableText nodeId={id} value={d.style || ""} field="style" rows={1}
        placeholder="双击输入音乐风格…" />
      <div className="sg-editable-label">提示词</div>
      <EditableText nodeId={id} value={d.prompt || ""} field="prompt" rows={2}
        placeholder="双击输入音乐描述…" />
      <div className="sg-editable-label">歌词</div>
      <EditableText nodeId={id} value={d.lyrics || ""} field="lyrics" rows={3}
        placeholder="双击输入歌词（可选）…" />
      {isYue ? (
        <>
          <div className="sg-editable-label">
            乐谱（ABC）{d.cot === "melody" ? " · 旋律模式" : ""}
          </div>
          <EditableText nodeId={id} value={d.abc || ""} field="abc" rows={4}
            placeholder="先点「生成谱面」，这里会出现可编辑的旋律+和弦谱…" />
        </>
      ) : null}
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
