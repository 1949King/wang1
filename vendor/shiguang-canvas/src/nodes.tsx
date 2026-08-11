import { type ReactNode } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { NodeData } from "./store";

function Shell({
  selected,
  kind,
  title,
  children,
}: {
  selected?: boolean;
  kind: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className={`sg-node ${kind}${selected ? " selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="head">{title}</div>
      <div className="body">{children}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export function ShotNode({ data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "shot" }>;
  return (
    <Shell selected={selected} kind="shot" title={`🎬 ${d.title || "镜头"}`}>
      {d.imageUrl ? <img src={d.imageUrl} alt="" /> : null}
      <div className="frame-row">
        {d.firstFrameUrl ? <img className="frame-thumb" src={d.firstFrameUrl} alt="首帧" /> : null}
        {d.lastFrameUrl ? <img className="frame-thumb" src={d.lastFrameUrl} alt="尾帧" /> : null}
      </div>
      <div>
        {d.shotSize} · {d.duration}s
      </div>
      <div className="meta">{(d.prompt || "").slice(0, 60)}</div>
    </Shell>
  );
}

export function ScriptNode({ data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "script" }>;
  return (
    <Shell selected={selected} kind="script" title={`📜 ${d.title || "剧本"}`}>
      <div className="meta">{(d.content || "").slice(0, 120)}</div>
    </Shell>
  );
}

export function ImageNode({ data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "image" }>;
  return (
    <Shell selected={selected} kind="image" title={`🖼️ ${d.title || "图片"}`}>
      {d.imageUrl ? <img src={d.imageUrl} alt="" /> : <div className="meta">未生成</div>}
      <div className="meta">{(d.prompt || "").slice(0, 60)}</div>
    </Shell>
  );
}

export function VideoNode({ data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "video" }>;
  return (
    <Shell selected={selected} kind="video" title={`🎥 ${d.title || "视频"}`}>
      {d.posterUrl ? <img src={d.posterUrl} alt="" /> : <div className="meta">未生成</div>}
      <div className="frame-row">
        {d.firstFrameUrl ? <img className="frame-thumb" src={d.firstFrameUrl} alt="首帧" /> : null}
        {d.lastFrameUrl ? <img className="frame-thumb" src={d.lastFrameUrl} alt="尾帧" /> : null}
      </div>
      <div className="meta">{(d.prompt || "").slice(0, 60)}</div>
    </Shell>
  );
}

export function PromptNode({ data, selected }: NodeProps) {
  const d = data as Extract<NodeData, { kind: "prompt" }>;
  return (
    <Shell selected={selected} kind="prompt" title={`✨ ${d.title || "提示词"}`}>
      <div className="meta">{(d.text || "").slice(0, 120)}</div>
    </Shell>
  );
}

export const nodeTypes = {
  shot: ShotNode,
  script: ScriptNode,
  image: ImageNode,
  video: VideoNode,
  prompt: PromptNode,
};
