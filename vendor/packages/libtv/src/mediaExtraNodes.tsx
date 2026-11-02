/**
 * AI-Canvas 对齐补缺：3D 导演台 / 数字人 / 逐帧动画 / 全景 / 画布笔记 / 源文件
 */
import React, { memo, useMemo, useRef, useState } from "react";
import { Handle, Position, NodeResizer, type NodeProps } from "@xyflow/react";
import {
  useCanvasStore,
  type DirectorData,
  type DirectorCardData,
  type DigitalHumanData,
  type AnimationData,
  type AnimationAction,
  type PanoramaData,
  type NoteData,
  type SourceData,
  type CharacterData,
  ANIMATION_ACTION_LABELS,
  animationGrid,
} from "./store";
import { generateImageViaHost, generateAudioViaHost, readFileAsDataUrl, uploadAssetToHost, breakdownStoryboard, planStoryboardCameras } from "./bridge";
import { runVideoEdit, type VideoEditChannel } from "./hostVideoEdit";
import { useVideoBad, VideoUnplayable } from "./videoUnplayable";

function nodePropsEqual(prev: NodeProps, next: NodeProps): boolean {
  return (
    prev.id === next.id &&
    prev.selected === next.selected &&
    prev.dragging === next.dragging &&
    prev.data === next.data
  );
}

function stop(e: React.SyntheticEvent) {
  e.stopPropagation();
}

/** 动作图标（火柴人风格，对应图片中的 6 个动作按钮） */
const ACTION_ICONS: Record<AnimationAction, string> = {
  idle: "🧍",
  walk: "🚶",
  run: "🏃",
  jump: "🤸",
  attack: "🤺",
  hit: "💥",
};

/** 占位 Sprite Sheet（无模型时也能预览播放） */
export function makePlaceholderSpriteSheet(
  action: AnimationAction,
  frames: number,
): string {
  const { cols, rows } = animationGrid(frames);
  const fw = 96;
  const fh = 96;
  const canvas = document.createElement("canvas");
  canvas.width = cols * fw;
  canvas.height = rows * fh;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";
  for (let i = 0; i < frames; i++) {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const ox = col * fw;
    const oy = row * fh;
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(ox, oy, fw, fh);
    ctx.strokeStyle = "#334155";
    ctx.strokeRect(ox + 0.5, oy + 0.5, fw - 1, fh - 1);
    const t = i / Math.max(frames - 1, 1);
    const cx = ox + fw / 2;
    const cy = oy + fh / 2 + 6;
    const bob =
      action === "jump"
        ? -Math.sin(t * Math.PI) * 18
        : action === "hit"
          ? Math.sin(t * Math.PI * 2) * 4
          : Math.sin(t * Math.PI * 2) * (action === "run" ? 5 : 3);
    const lean =
      action === "attack"
        ? t * 12
        : action === "walk" || action === "run"
          ? Math.sin(t * Math.PI * 2) * 6
          : 0;
    const leg =
      action === "idle"
        ? 0
        : Math.sin(t * Math.PI * 2) * (action === "run" ? 16 : 10);
    ctx.save();
    ctx.translate(cx + lean, cy + bob);
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(0, -28, 8, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, -18);
    ctx.lineTo(0, 6);
    ctx.moveTo(0, -8);
    ctx.lineTo(-14, action === "attack" ? -2 : 4);
    ctx.moveTo(0, -8);
    ctx.lineTo(14, action === "attack" ? 8 : 4);
    ctx.moveTo(0, 6);
    ctx.lineTo(-10, 28 + leg);
    ctx.moveTo(0, 6);
    ctx.lineTo(10, 28 - leg);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = "#94a3b8";
    ctx.font = "10px sans-serif";
    ctx.fillText(String(i + 1), ox + 4, oy + 12);
  }
  ctx.fillStyle = "#64748b";
  ctx.font = "11px sans-serif";
  ctx.fillText(`${ANIMATION_ACTION_LABELS[action]} · ${frames}f`, 8, canvas.height - 8);
  return canvas.toDataURL("image/png");
}

export const DirectorNode = memo(function DirectorNode({ id, data, selected }: NodeProps) {
  const d = data as DirectorData;
  const openDirectorForNode = useCanvasStore((s) => s.openDirectorForNode);
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const captures = d.captureUrls || [];

  return (
    <div className={`sg-node director${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={260} minHeight={200} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🎥 {d.title || "3D 导演台"}</span>
        <button
          type="button"
          className="sg-node-mini-btn primary"
          onClick={() => openDirectorForNode(id)}
        >
          打开舞台
        </button>
      </div>
      <div className="body nodrag">
        {d.imageUrl ? (
          <div className="img-wrap">
            <img src={d.imageUrl} alt="" />
          </div>
        ) : (
          <div className="sg-director-empty">摆姿 · 机位 · 截图回写本节点</div>
        )}
        {d.lastCameraName ? (
          <div className="meta">最近机位：{d.lastCameraName}</div>
        ) : null}
        {captures.length > 1 ? (
          <div className="sg-director-thumbs">
            {captures.slice(-6).map((u, i) => (
              <button
                key={`${i}_${u.slice(0, 24)}`}
                type="button"
                className="sg-director-thumb"
                onClick={() => updateNodeData(id, { imageUrl: u })}
                title="设为主图"
              >
                <img src={u} alt="" />
              </button>
            ))}
          </div>
        ) : null}
        <textarea
          className="sg-node-inline-ta"
          value={d.prompt || ""}
          placeholder="镜头意图 / 下游提示词备注…"
          onChange={(e) => updateNodeData(id, { prompt: e.target.value })}
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

/** 导演卡：输入剧本 → 调用宿主 LLM 自动拆解 → 生成下游分镜卡（spec §6） */
export const DirectorCardNode = memo(function DirectorCardNode({ id, data, selected }: NodeProps) {
  const d = data as DirectorCardData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const breakdownDirectorCard = useCanvasStore((s) => s.breakdownDirectorCard);
  const busy = d.status === "generating";

  const onBreakdown = async () => {
    const script = (d.script || "").trim();
    if (!script) {
      updateNodeData(id, { status: "failed", errorMessage: "请先填写剧本/脚本" });
      return;
    }
    updateNodeData(id, { status: "generating", errorMessage: "" });
    try {
      const res = await breakdownStoryboard(script);
      if (!res.ok && !(res.shots && res.shots.length)) {
        throw new Error(res.message || "拆解失败");
      }
      // 拆解后顺带规划 AI 相机计划（机位 + 运镜），写进每张分镜卡供 Stage3D 摆机位
      let cameras: Parameters<typeof breakdownDirectorCard>[2] = [];
      try {
        const plan = await planStoryboardCameras({ shots: res.shots || [] });
        if (plan.ok) cameras = plan.cameras || [];
      } catch {
        cameras = [];
      }
      breakdownDirectorCard(id, res.shots || [], cameras);
    } catch (e) {
      updateNodeData(id, { status: "failed", errorMessage: String(e).slice(0, 200) });
    }
  };

  return (
    <div className={`sg-node director-card${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={280} minHeight={200} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🎬 {d.title || "导演卡"}</span>
        <button
          type="button"
          className="sg-node-mini-btn primary"
          disabled={busy}
          onClick={() => void onBreakdown()}
        >
          {busy ? "拆解中…" : "自动拆解"}
        </button>
      </div>
      <div className="body nodrag">
        <textarea
          className="sg-node-inline-ta sg-director-card-script"
          value={d.script || ""}
          placeholder="在此粘贴剧本/脚本，点击「自动拆解」生成分镜卡…"
          onChange={(e) => updateNodeData(id, { script: e.target.value })}
        />
        {d.lastBreakdown ? (
          <div className="sg-director-card-result">
            已拆解 → {d.lastBreakdown.shots} 个分镜卡
          </div>
        ) : null}
        {d.errorMessage ? <div className="sg-node-error">{d.errorMessage}</div> : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

const TALKING_HEAD_UNAVAILABLE =
  "未配置形象驱动模型，口型成片未接入。请先生成配音并上传形象图入轨。";

export const DigitalHumanNode = memo(function DigitalHumanNode({ id, data, selected }: NodeProps) {
  const d = data as DigitalHumanData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const setNodeAudio = useCanvasStore((s) => s.setNodeAudio);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const fileRef = useRef<HTMLInputElement>(null);
  const busy = d.status === "generating";

  const onUploadPortrait = async (file: File | null) => {
    if (!file) return;
    try {
      const url = await readFileAsDataUrl(file);
      updateNodeData(id, { imageUrl: url, status: "success", errorMessage: "" });
      setStatus("已载入数字人形象");
    } catch (e) {
      updateNodeData(id, { status: "failed", errorMessage: String(e).slice(0, 200) });
    }
  };

  const bindSelectedImage = () => {
    const st = useCanvasStore.getState();
    const sel = st.nodes.find((n) => n.id === st.selectedId && n.id !== id);
    const sd = sel?.data as { kind?: string; imageUrl?: string } | undefined;
    if (
      sd?.imageUrl &&
      (sd.kind === "image" || sd.kind === "shot" || sd.kind === "director" || sd.kind === "digitalHuman")
    ) {
      updateNodeData(id, { imageUrl: sd.imageUrl });
      setStatus("已绑定选中节点图片为数字人形象");
      return;
    }
    setStatus("请先选中带图片的镜头/图片/导演台节点");
  };

  const generateVoice = async () => {
    const line = (d.line || "").trim();
    if (!line) {
      updateNodeData(id, { status: "failed", errorMessage: "请先填写台词" });
      setStatus("请先填写台词");
      return;
    }
    updateNodeData(id, { status: "generating", errorMessage: "" });
    const prompt = d.characterName?.trim() ? `${d.characterName.trim()}：${line}` : line;
    try {
      const res = await generateAudioViaHost({ prompt });
      if (!res.ok || !res.audio_url) {
        throw new Error(res.message || "配音失败");
      }
      setNodeAudio(id, res.audio_url);
      updateNodeData(id, { status: "success", errorMessage: "" });
      setStatus(`${res.message || "配音已生成"}（口型成片未接入）`);
    } catch (e) {
      updateNodeData(id, { status: "failed", errorMessage: String(e).slice(0, 200) });
      setStatus(`配音失败：${e}`);
    }
  };

  const talkingHead = () => {
    updateNodeData(id, { status: "failed", errorMessage: TALKING_HEAD_UNAVAILABLE });
    setStatus(TALKING_HEAD_UNAVAILABLE);
  };

  return (
    <div className={`sg-node digital-human${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={260} minHeight={240} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🧑 {d.title || "数字人"}</span>
        <button
          type="button"
          className="sg-node-mini-btn primary"
          disabled={busy}
          onClick={() => void generateVoice()}
        >
          {busy ? "配音中…" : "生成配音"}
        </button>
      </div>
      <div className="body nodrag">
        {d.imageUrl ? (
          <div className="img-wrap">
            <img src={d.imageUrl} alt="" />
          </div>
        ) : (
          <div className="sg-director-empty">上传或绑定形象图 · 台词走 TTS</div>
        )}
        <input
          className="sg-node-inline-input"
          value={d.characterName || ""}
          placeholder="角色名（可选）"
          onChange={(e) => updateNodeData(id, { characterName: e.target.value })}
        />
        <textarea
          className="sg-node-inline-ta"
          value={d.line || ""}
          placeholder="台词…"
          onChange={(e) => updateNodeData(id, { line: e.target.value })}
        />
        <div className="sg-anim-actions">
          <button type="button" className="sg-node-mini-btn" onClick={() => fileRef.current?.click()}>
            上传形象
          </button>
          <button type="button" className="sg-node-mini-btn" onClick={bindSelectedImage}>
            绑选中图
          </button>
          <button type="button" className="sg-node-mini-btn" onClick={talkingHead}>
            口型成片
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => void onUploadPortrait(e.target.files?.[0] || null)}
        />
        {d.audioUrl ? <audio src={d.audioUrl} controls style={{ width: "100%", marginTop: 6 }} /> : null}
        {d.errorMessage ? <div className="sg-node-error">{d.errorMessage}</div> : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

export const AnimationNode = memo(function AnimationNode({ id, data, selected }: NodeProps) {
  const d = data as AnimationData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const { cols, rows } = useMemo(() => animationGrid(d.frames || 20), [d.frames]);
  const fileRef = useRef<HTMLInputElement>(null);

  const onUpload = async (file: File | null) => {
    if (!file) return;
    try {
      const url = await readFileAsDataUrl(file);
      updateNodeData(id, { sheetUrl: url, status: "success", errorMessage: "" });
      setStatus("已载入 Sprite Sheet");
    } catch (e) {
      updateNodeData(id, { status: "failed", errorMessage: String(e) });
    }
  };

  const makePlaceholder = () => {
    const sheetUrl = makePlaceholderSpriteSheet(d.action || "walk", d.frames || 20);
    updateNodeData(id, { sheetUrl, status: "success", previewMode: "playing" });
    setStatus("已生成占位逐帧表");
  };

  const aiGenerate = async () => {
    updateNodeData(id, { status: "generating", errorMessage: "" });
    const prompt =
      `${d.prompt || "2D俯视角游戏角色，保持角色造型、朝向、比例和光照一致"}，` +
      `${ANIMATION_ACTION_LABELS[d.action] || d.action}动作，` +
      `${cols}x${rows} sprite sheet，${d.frames}帧，纯白背景，侧视图，游戏像素清晰轮廓`;
    try {
      const res = await generateImageViaHost({
        prompt,
        n: 1,
        onPreloadProgress: (p) => setStatus(`人脸修复模型预载 ${p.progress}%：${p.message}`),
      });
      const url = res.images?.[0] || res.image_data_url || res.image_url;
      if (!res.ok || !url) throw new Error(res.message || "生图失败");
      updateNodeData(id, { sheetUrl: url, status: "success", previewMode: "sheet" });
      setStatus("逐帧表已生成");
    } catch (e) {
      updateNodeData(id, { status: "failed", errorMessage: String(e) });
      setStatus(`逐帧生成失败：${e}`);
    }
  };

  return (
    <div className={`sg-node animation${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={280} minHeight={220} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🎞️ {d.title || "生成动画"}</span>
        <span className="head-actions">
          {d.sheetUrl ? (
            <>
              <button
                type="button"
                className="sg-node-mini-btn"
                title={d.previewMode === "playing" ? "播放动画" : "播放"}
                onClick={() => updateNodeData(id, { previewMode: "playing" })}
              >
                ▶
              </button>
              <button
                type="button"
                className={`sg-node-mini-btn${d.previewMode === "sheet" ? " on" : ""}`}
                title="查看整表（网格）"
                onClick={() => updateNodeData(id, { previewMode: "sheet" })}
              >
                ▦
              </button>
            </>
          ) : null}
        </span>
      </div>
      <div className="body nodrag">
        {d.sheetUrl ? (
          d.previewMode === "playing" ? (
            <div
              className="sg-sprite-play"
              style={{
                backgroundImage: `url(${d.sheetUrl})`,
                backgroundSize: `${cols * 100}% ${rows * 100}%`,
                animationDuration: `${(d.frames || 20) / Math.max(d.fps || 8, 1)}s`,
                // @ts-expect-error CSS custom props
                "--sg-sprite-steps": d.frames - 1,
                "--sg-sprite-cols": cols,
                "--sg-sprite-rows": rows,
              }}
            />
          ) : (
            <div className="img-wrap">
              <img src={d.sheetUrl} alt="" />
            </div>
          )
        ) : (
          <div className="sg-anim-empty">
            <span className="sg-anim-empty-icon">🎞️</span>
            <span className="sg-anim-empty-title">点击节点描述角色并生成</span>
            <span className="sg-anim-empty-meta">
              {d.status === "generating" ? "生成中…" : "待机"} · {d.frames} 帧 · {cols}×{rows}
            </span>
          </div>
        )}
        <textarea
          className="sg-anim-prompt"
          rows={2}
          placeholder="2D俯视角游戏角色，保持角色造型、朝向、比例和光照一致"
          value={d.prompt || ""}
          onChange={(e) => updateNodeData(id, { prompt: e.target.value })}
        />
        <div className="sg-anim-toolbar">
          {/* 动作图标行 */}
          <div className="sg-anim-actions-row">
            {(Object.keys(ANIMATION_ACTION_LABELS) as AnimationAction[]).map((k) => (
              <button
                key={k}
                type="button"
                className={`sg-anim-action-icon${d.action === k ? " on" : ""}`}
                title={ANIMATION_ACTION_LABELS[k]}
                onClick={() => updateNodeData(id, { action: k })}
              >
                {ACTION_ICONS[k]}
              </button>
            ))}
          </div>
          <select
            value={d.frames}
            onChange={(e) => updateNodeData(id, { frames: Number(e.target.value) as AnimationData["frames"] })}
            title="帧数"
          >
            {[6, 8, 12, 16, 20].map((n) => (
              <option key={n} value={n}>
                {n} 帧
              </option>
            ))}
          </select>
          <input
            type="number"
            min={1}
            max={30}
            value={d.fps || 8}
            title="FPS"
            onChange={(e) => updateNodeData(id, { fps: Math.max(1, Number(e.target.value) || 8) })}
          />
          <button type="button" className="sg-node-mini-btn primary" onClick={() => void aiGenerate()} title="AI 生成">
            →
          </button>
        </div>
        <div className="sg-anim-actions">
          <button type="button" className="sg-node-mini-btn" onClick={() => fileRef.current?.click()}>
            上传
          </button>
          <button type="button" className="sg-node-mini-btn" onClick={makePlaceholder}>
            占位表
          </button>
          <button type="button" className="sg-node-mini-btn primary" onClick={() => void aiGenerate()}>
            AI 生成
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => void onUpload(e.target.files?.[0] || null)}
        />
        {d.status === "failed" && d.errorMessage ? (
          <div className="meta" style={{ color: "#fca5a5" }}>
            {d.errorMessage}
          </div>
        ) : null}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

function PanoramaViewport({
  imageUrl,
  yaw,
  pitch,
  onYawPitch,
}: {
  imageUrl: string;
  yaw: number;
  pitch: number;
  onYawPitch: (yaw: number, pitch: number) => void;
}) {
  const drag = useRef<{ x: number; y: number; yaw: number; pitch: number } | null>(null);
  const xPct = ((yaw % 360) + 360) % 360 / 360 * 100;
  const yPct = 50 - Math.max(-80, Math.min(80, pitch)) * 0.4;

  return (
    <div
      className="sg-pano-view"
      style={{
        backgroundImage: `url(${imageUrl})`,
        backgroundPosition: `${xPct}% ${yPct}%`,
      }}
      onPointerDown={(e) => {
        (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, y: e.clientY, yaw, pitch };
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const dx = e.clientX - drag.current.x;
        const dy = e.clientY - drag.current.y;
        onYawPitch(drag.current.yaw - dx * 0.4, Math.max(-80, Math.min(80, drag.current.pitch + dy * 0.3)));
      }}
      onPointerUp={() => {
        drag.current = null;
      }}
    />
  );
}

export const PanoramaNode = memo(function PanoramaNode({ id, data, selected }: NodeProps) {
  const d = data as PanoramaData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const fileRef = useRef<HTMLInputElement>(null);

  const onUpload = async (file: File | null) => {
    if (!file) return;
    const url = await readFileAsDataUrl(file);
    updateNodeData(id, { imageUrl: url, status: "success" });
    setStatus("已载入全景图");
  };

  const bindSelectedImage = () => {
    const st = useCanvasStore.getState();
    const sel = st.nodes.find((n) => n.id === st.selectedId && n.id !== id);
    const sd = sel?.data as { kind?: string; imageUrl?: string } | undefined;
    if (sd?.imageUrl && (sd.kind === "image" || sd.kind === "shot" || sd.kind === "director")) {
      updateNodeData(id, { imageUrl: sd.imageUrl });
      setStatus("已绑定选中节点图片为全景源");
      return;
    }
    setStatus("请先选中带图片的镜头/图片/导演台节点");
  };

  return (
    <div className={`sg-node panorama${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={280} minHeight={200} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🌐 {d.title || "全景"}</span>
        <span className="sg-meta-tiny">
          {Math.round(d.yaw || 0)}° / {Math.round(d.pitch || 0)}°
        </span>
      </div>
      <div className="body nodrag">
        {d.imageUrl ? (
          <PanoramaViewport
            imageUrl={d.imageUrl}
            yaw={d.yaw || 0}
            pitch={d.pitch || 0}
            onYawPitch={(yaw, pitch) => updateNodeData(id, { yaw, pitch })}
          />
        ) : (
          <div className="sg-director-empty">等距柱状全景图 · 拖拽环视</div>
        )}
        <div className="sg-anim-actions">
          <button type="button" className="sg-node-mini-btn" onClick={() => fileRef.current?.click()}>
            上传
          </button>
          <button type="button" className="sg-node-mini-btn" onClick={bindSelectedImage}>
            绑选中图
          </button>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => void onUpload(e.target.files?.[0] || null)}
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

export const NoteNode = memo(function NoteNode({ id, data, selected }: NodeProps) {
  const d = data as NoteData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const color = d.color || "#fbbf24";

  return (
    <div
      className={`sg-node note note-${d.noteType || "text"}${selected ? " selected" : ""}`}
      style={{ borderColor: color, ["--note-accent" as string]: color }}
      onMouseDown={stop}
    >
      <NodeResizer minWidth={160} minHeight={100} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>📌 {d.title || "笔记"}</span>
        <select
          value={d.noteType || "text"}
          onChange={(e) =>
            updateNodeData(id, {
              noteType: e.target.value as NoteData["noteType"],
            })
          }
        >
          <option value="text">文字</option>
          <option value="rect">矩形</option>
          <option value="ellipse">椭圆</option>
          <option value="arrow">箭头</option>
        </select>
      </div>
      <div className="body nodrag">
        {d.noteType === "arrow" ? (
          <div className="sg-note-arrow" style={{ color }}>
            ➜
            <input
              value={d.content || ""}
              onChange={(e) => updateNodeData(id, { content: e.target.value })}
              placeholder="标注…"
            />
          </div>
        ) : (
          <textarea
            className="sg-note-body"
            style={{
              borderRadius: d.noteType === "ellipse" ? "50%" : 8,
              borderColor: color,
            }}
            value={d.content || ""}
            onChange={(e) => updateNodeData(id, { content: e.target.value })}
          />
        )}
        <input
          type="color"
          value={color}
          onChange={(e) => updateNodeData(id, { color: e.target.value })}
          title="颜色"
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

export const SourceNode = memo(function SourceNode({ id, data, selected }: NodeProps) {
  const d = data as SourceData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const fileRef = useRef<HTMLInputElement>(null);
  /** ✂️ 指令式编辑卡状态（P1-2 步骤 4，2026-10-15）：
   *  指令/渠道/公网 URL/出域勾选/执行中 —— 全部组件本地态，成功结果才写回节点数据。 */
  const [editIns, setEditIns] = useState("");
  const [editChannel, setEditChannel] = useState<VideoEditChannel>("auto");
  const [editPublicUrl, setEditPublicUrl] = useState("");
  /** 素材出域显式同意：两个渠道都是云端，默认关，未勾不放行（项目既有纪律）。 */
  const [editEgress, setEditEgress] = useState(false);
  const [editing, setEditing] = useState(false);
  const editFileRef = useRef<HTMLInputElement>(null);
  // 画布内核没带 H.264 ⇒ mp4 的 <video> 报 error.code=4，退回一帧图 + 说清原因
  const vbad = useVideoBad();

  const accept =
    d.mediaType === "video"
      ? "video/*"
      : d.mediaType === "audio"
        ? "audio/*"
        : d.mediaType === "text"
          ? ".txt,.md,.json,text/*"
          : "image/*";

  const onFile = async (file: File | null) => {
    if (!file) return;
    try {
      if (d.mediaType === "text") {
        const content = await file.text();
        updateNodeData(id, { content, fileName: file.name, title: file.name });
        setStatus(`已载入文本：${file.name}`);
        return;
      }
      if (file.size > 4 * 1024 * 1024) {
        const up = await uploadAssetToHost(file);
        if (!up.ok || !up.url) throw new Error(up.message || "上传失败");
        if (d.mediaType === "image") updateNodeData(id, { imageUrl: up.url, fileName: file.name, title: file.name });
        if (d.mediaType === "video") updateNodeData(id, { videoUrl: up.url, hostPath: up.path, fileName: file.name, title: file.name });
        if (d.mediaType === "audio") updateNodeData(id, { audioUrl: up.url, fileName: file.name, title: file.name });
      } else {
        const url = await readFileAsDataUrl(file);
        if (d.mediaType === "image") updateNodeData(id, { imageUrl: url, fileName: file.name, title: file.name });
        if (d.mediaType === "video") updateNodeData(id, { videoUrl: url, fileName: file.name, title: file.name });
        if (d.mediaType === "audio") updateNodeData(id, { audioUrl: url, fileName: file.name, title: file.name });
      }
      setStatus(`源文件已载入：${file.name}`);
    } catch (e) {
      setStatus(`源文件失败：${e}`);
    }
  };

  /** 编辑卡补上传：小文件走 dataURL 内联时没有磁盘路径（clip_path 拿不到），
   *  这里强制经宿主上传拿 up.path，节点素材同步换成上传后的可播放 URL。 */
  const onEditUpload = async (file: File | null) => {
    if (!file) return;
    try {
      const up = await uploadAssetToHost(file);
      if (!up.ok || !up.path) throw new Error(up.message || "上传失败");
      updateNodeData(id, {
        hostPath: up.path,
        videoUrl: up.url || d.videoUrl,
        fileName: file.name,
        title: file.name,
      });
      setStatus(`片段已上传，本地路径就绪：${file.name}`);
    } catch (e) {
      setStatus(`片段上传失败：${e}`);
    } finally {
      if (editFileRef.current) editFileRef.current.value = "";
    }
  };

  /** ✂️ 执行指令式编辑（hostVideoEdit.runVideoEdit 负责全部预检与诚实映射）：
   *  成功 → 节点指向新片段（磁盘路径 + inbox 可播放 URL，原文件后端不删）；
   *  失败 → 原镜保持不动，message/errors 逐字回报，不美化。 */
  const onRunEdit = async () => {
    if (!d.hostPath) {
      setStatus("指令式编辑：先点「上传片段拿本地路径」");
      return;
    }
    setEditing(true);
    try {
      const res = await runVideoEdit({
        clipPath: d.hostPath,
        instruction: editIns,
        channel: editChannel,
        videoUrl: editPublicUrl.trim(),
        egressAck: editEgress,
      });
      if (res.ok) {
        updateNodeData(id, {
          hostPath: res.clipPath || d.hostPath,
          ...(res.url ? { videoUrl: res.url } : {}),
        });
        setStatus(
          `指令式编辑完成（${res.channelUsed || "auto"}）：${res.url ? "新片段已就位" : `新片段在 ${res.clipPath}`}` +
            `${res.costNote ? ` · ${res.costNote}` : ""}` +
            `${res.errors.length ? ` · 顺延失败：${res.errors.join("；")}` : ""}`,
        );
      } else {
        setStatus(
          `指令式编辑失败（原片段保留）：${res.message}` +
            `${res.errors.length ? ` · ${res.errors.join("；")}` : ""}`,
        );
      }
    } finally {
      setEditing(false);
    }
  };

  return (
    <div className={`sg-node source${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={240} minHeight={160} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>📂 {d.title || "源文件"}</span>
        <select
          value={d.mediaType}
          onChange={(e) =>
            updateNodeData(id, { mediaType: e.target.value as SourceData["mediaType"] })
          }
        >
          <option value="image">图片</option>
          <option value="video">视频</option>
          <option value="audio">音频</option>
          <option value="text">文本</option>
        </select>
      </div>
      <div className="body nodrag">
        {d.mediaType === "image" && d.imageUrl ? (
          <div className="img-wrap">
            <img src={d.imageUrl} alt="" />
          </div>
        ) : null}
        {d.mediaType === "video" && d.videoUrl ? (
          vbad.bad ? <VideoUnplayable poster={d.imageUrl} /> : (
            <div className="img-wrap">
              <video src={d.videoUrl} muted playsInline controls onError={vbad.onError} />
            </div>
          )
        ) : null}
        {d.mediaType === "video" ? (
          <div className="sg-source-edit">
            <textarea
              className="sg-node-inline-ta"
              value={editIns}
              placeholder="✂️ 编辑指令（如「去掉背景里走动的人」）…"
              onChange={(e) => setEditIns(e.target.value)}
            />
            {editChannel !== "seedance" ? (
              <input
                className="sg-node-inline-ta"
                value={editPublicUrl}
                placeholder="公网视频 URL（Kling 必填；auto 选填用于顺延）"
                onChange={(e) => setEditPublicUrl(e.target.value)}
              />
            ) : null}
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
              <select
                value={editChannel}
                onChange={(e) => setEditChannel(e.target.value as VideoEditChannel)}
              >
                <option value="auto">auto（Seedance 先）</option>
                <option value="seedance">Seedance</option>
                <option value="kling">Kling</option>
              </select>
              <label style={{ fontSize: 10, color: "#94a3b8" }} title="两个渠道都在云端处理片段，勾选才会发送">
                <input
                  type="checkbox"
                  checked={editEgress}
                  onChange={(e) => setEditEgress(e.target.checked)}
                />
                允许发送到云端
              </label>
              <button
                type="button"
                className="sg-node-mini-btn primary"
                disabled={editing || !editEgress}
                onClick={() => void onRunEdit()}
              >
                {editing ? "编辑中…" : "✂️ 执行编辑"}
              </button>
            </div>
            {d.hostPath ? (
              <div className="meta">本地片段路径就绪：{d.fileName || ""}</div>
            ) : (
              <>
                <button
                  type="button"
                  className="sg-node-mini-btn"
                  disabled={editing}
                  onClick={() => editFileRef.current?.click()}
                >
                  上传片段拿本地路径
                </button>
                <div className="meta">小文件走 dataURL 内联，编辑需先上传拿磁盘路径</div>
              </>
            )}
            <input
              ref={editFileRef}
              type="file"
              accept="video/*"
              hidden
              onChange={(e) => void onEditUpload(e.target.files?.[0] || null)}
            />
          </div>
        ) : null}
        {d.mediaType === "audio" && d.audioUrl ? <audio src={d.audioUrl} controls /> : null}
        {d.mediaType === "text" ? (
          <textarea
            className="sg-node-inline-ta"
            value={d.content || ""}
            onChange={(e) => updateNodeData(id, { content: e.target.value })}
            placeholder="文本源…"
          />
        ) : null}
        {!d.imageUrl && !d.videoUrl && !d.audioUrl && d.mediaType !== "text" ? (
          <div className="sg-director-empty">本地素材入口 · 连到下游生成</div>
        ) : null}
        <button type="button" className="sg-node-mini-btn primary" onClick={() => fileRef.current?.click()}>
          选择文件
        </button>
        {d.fileName ? <div className="meta">{d.fileName}</div> : null}
        {d.editorRange || d.editorStatus ? (
          <div className="meta">
            剪辑{d.editorStatus === "in_timeline" ? "已入轨" : d.editorStatus === "sent" ? "已推送" : ""}{" "}
            {d.editorRange || ""}
          </div>
        ) : null}
        <input
          ref={fileRef}
          type="file"
          accept={accept}
          hidden
          onChange={(e) => void onFile(e.target.files?.[0] || null)}
        />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);

/**
 * 角色节点：把角色库条目放到画布上，并给出「捏脸」入口。
 * 捏脸卡片是固定定位模态，必须渲染在 React Flow viewport 之外，
 * 故本节点只派发 `sg-open-face-card` 窗口事件，由 CanvasShell 统一承载 FaceCard。
 */
export const CharacterNode = memo(function CharacterNode({ id, data, selected }: NodeProps) {
  const d = data as CharacterData;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const refreshCharacters = useCanvasStore((s) => s.refreshCharacters);
  const characters = useCanvasStore((s) => s.characters);
  const bound = useMemo(
    () => characters.find((c) => c.id === d.characterId),
    [characters, d.characterId],
  );

  const openFaceCard = () => {
    if (!d.characterId) return;
    window.dispatchEvent(
      new CustomEvent("sg-open-face-card", { detail: { characterId: d.characterId, nodeId: id } }),
    );
  };

  return (
    <div className={`sg-node character${selected ? " selected" : ""}`} onMouseDown={stop}>
      <NodeResizer minWidth={200} minHeight={180} isVisible={!!selected} />
      <Handle type="target" position={Position.Left} />
      <div className="head">
        <span>🧑‍🎨 {d.title || "角色"}</span>
        <button
          type="button"
          className="sg-node-mini-btn"
          onClick={() => void refreshCharacters()}
          title="从角色库刷新"
        >
          ↻
        </button>
      </div>
      <div className="body nodrag">
        <select
          value={d.characterId || ""}
          onChange={(e) => {
            const cid = e.target.value;
            const c = characters.find((x) => x.id === cid);
            updateNodeData(id, { characterId: cid, characterName: c?.name || "" });
          }}
        >
          <option value="">— 选择角色 —</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.role_type ? `（${c.role_type}）` : ""}
            </option>
          ))}
        </select>
        {bound?.avatar_url ? (
          <div className="img-wrap">
            <img src={bound.avatar_url} alt={bound.name} />
          </div>
        ) : (
          <div className="sg-director-empty">
            {bound ? "尚未捏脸：点下方「捏脸」生成参考脸" : "角色库暂无头像 · 先选角色再捏脸"}
          </div>
        )}
        <button
          type="button"
          className="sg-node-mini-btn primary"
          disabled={!d.characterId}
          onClick={openFaceCard}
          title="打开独立捏脸卡片；参数随角色库保存，并进生图提示词保持跨镜一致"
        >
          🎨 捏脸
        </button>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}, nodePropsEqual);
