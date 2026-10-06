/**
 * 小白模式卡片 — 纯矩形磁吸卡片（对齐 spec 4.1 外观规格）
 *
 * ┌─────────────────────────────┐
 * │ [类型图标] 卡片标题           │  ← 标题栏 40px
 * ├─────────────────────────────┤
 * │ 内容区                       │  ← 最小 120px（含黄色意图提示条）
 * ├─────────────────────────────┤
 * │ [状态灯] [胶囊] [层数] [菜单] │  ← 状态栏 32px
 * └─────────────────────────────┘
 *
 * 与专业模式共用同一份 node.data，不写入任何小白专属必填字段；
 * 仅在 data 上读取 intentDepth（可选，默认 2）用于胶囊显示。
 */

import { memo, useState } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useCanvasStore } from "../store";
import {
  CARD_GEOMETRY,
  INTENT_LAYERS,
  LAMP_STYLE,
  kindStyle,
  lampOf,
  noviceHint,
  textFieldFor,
} from "./types";
import "./novice-cards.css";

type LooseData = Record<string, unknown> & {
  kind?: string;
  title?: string;
  status?: string;
  stack?: { layers?: unknown[] };
  intentDepth?: number;
  characterName?: string;
  name?: string;
  content?: string;
  text?: string;
  script?: string;
  prompt?: string;
  dialogue?: string;
  line?: string;
  imageUrl?: string;
  posterUrl?: string;
  firstFrameUrl?: string;
  sheetUrl?: string;
  videoUrl?: string;
  refVideoUrl?: string;
  fileName?: string;
  shotSize?: string;
  duration?: number;
  qualityTier?: string;
  mode?: string;
  count?: number;
  action?: string;
  frames?: number;
  yaw?: number;
  pitch?: number;
};

/** 标题：优先 title，其次角色名/剧名，最后回落类型名 */
function titleOf(d: LooseData, fallback: string): string {
  const cand = [d.title, d.characterName, d.name].find(
    (v) => typeof v === "string" && v.trim(),
  );
  return (cand as string) || fallback;
}

/** 内容区主文本：按节点类型挑最有用的一句话 */
function summaryOf(d: LooseData, kind: string): string {
  const pick = (...keys: string[]) => {
    for (const k of keys) {
      const v = d[k];
      if (typeof v === "string" && v.trim()) return v.trim();
    }
    return "";
  };
  switch (kind) {
    case "script":
    case "markdown":
      return pick("content", "text", "script");
    case "directorCard":
    case "director":
      return pick("script", "content");
    case "shot":
    case "image":
    case "video":
    case "audio":
    case "generator":
    case "animation":
    case "panorama":
      return pick("prompt", "dialogue", "line");
    case "music": {
      // YuE 乐：卡片承载「意图」= 可编辑乐谱（而非空 prompt），
      // 让「谱面」成为磁吸卡片上第一眼可见的东西（2026-09-28 适配）。
      const abc = typeof d.abc === "string" ? d.abc.trim() : "";
      if (d.engine === "yue" && abc) {
        const seg = abc.split("\n").map((s) => s.trim()).filter(Boolean);
        return seg.slice(0, 3).join(" · ").slice(0, 90);
      }
      return pick("prompt", "style", "lyrics", "dialogue", "line");
    }
    case "prompt":
      return pick("text", "prompt");
    case "digitalHuman":
      return pick("line", "prompt", "characterName");
    case "source":
      return pick("fileName", "content", "prompt");
    default:
      return pick("prompt", "content", "text", "line");
  }
}

/** 内容区缩略图（图片/视频节点） */
function thumbOf(d: LooseData): { url?: string; video?: boolean } {
  const img = [d.imageUrl, d.posterUrl, d.firstFrameUrl, d.sheetUrl].find(
    (v) => typeof v === "string" && v,
  );
  const vid = [d.videoUrl, d.refVideoUrl].find((v) => typeof v === "string" && v);
  if (vid) return { url: vid as string, video: true };
  if (img) return { url: img as string, video: false };
  return {};
}

/** 内容区的机位/时长摘要（镜头类） */
function metaOf(d: LooseData): string {
  const parts: string[] = [];
  if (typeof d.shotSize === "string" && d.shotSize) parts.push(d.shotSize);
  if (typeof d.duration === "number" && d.duration) parts.push(`${d.duration}s`);
  if (typeof d.qualityTier === "string" && d.qualityTier) {
    const map: Record<string, string> = {
      draft: "草稿",
      standard: "标准",
      fine: "精修",
      cinema: "电影级",
    };
    parts.push(map[d.qualityTier] || d.qualityTier);
  }
  // 生成器：模式 + 数量
  if (typeof d.mode === "string" && d.mode) parts.push(String(d.mode));
  if (typeof d.count === "number" && d.count > 1) parts.push(`×${d.count}`);
  // 动画：动作 + 帧数 + 帧率
  if (typeof d.action === "string" && d.action) parts.push(String(d.action));
  if (typeof d.frames === "number" && d.frames) parts.push(`${d.frames}帧`);
  // 全景：当前视角
  if (typeof d.yaw === "number" && typeof d.pitch === "number") {
    parts.push(`视角 ${Math.round(d.yaw)}°/${Math.round(d.pitch)}°`);
  }
  // 音乐：引擎 + 是否已规划出谱面（YuE 适配，2026-09-28）
  if (typeof d.engine === "string" && d.engine) {
    parts.push(d.engine === "yue" ? "YuE 乐" : "Suno");
  }
  if (d.engine === "yue" && typeof d.yueMode === "string" && d.yueMode === "cover") {
    parts.push("翻唱");
  }
  if (typeof d.abc === "string" && d.abc.trim()) parts.push("有乐谱");
  return parts.join(" · ");
}

function NoviceCardImpl({ id, data, selected }: NodeProps) {
  const d = data as LooseData;
  const kind = String(d.kind || "");
  const style = kindStyle(kind);
  const lamp = lampOf(d.status);
  const hint = noviceHint(kind);
  const summary = summaryOf(d, kind);
  const meta = metaOf(d);
  const thumb = thumbOf(d);
  const layerCount = Array.isArray(d.stack?.layers) ? (d.stack!.layers as unknown[]).length : 0;
  const depth = Math.min(3, Math.max(1, Number(d.intentDepth) || 2));

  // ── 咬合侧隐形（2026-09-16 用户裁定，对齐 Windows 磁贴）──
  // 贴合边的描边透明 + 直角，两卡接缝处融为一块；表由 CanvasShell 按 bonds 推导。
  const bonded = useCanvasStore((s) => s.bondedSides[id]);
  const bondedCls =
    bonded && bonded.length > 0
      ? " " + bonded.map((s) => `bonded-${s}`).join(" ")
      : "";

  const [menuOpen, setMenuOpen] = useState(false);

  /** 生成新版本：把当前参数快照压入层叠栈（与 FloatingToolbar 行为一致） */
  const pushVersion = () => {
    const node = useCanvasStore.getState().nodes.find((n) => n.id === id);
    if (!node) return;
    useCanvasStore.getState().pushLayer(id, { ...node.data });
    setMenuOpen(false);
  };

  /** 原地复制一张同类型卡片 */
  const duplicate = () => {
    const st = useCanvasStore.getState();
    const node = st.nodes.find((n) => n.id === id);
    if (!node) return;
    const k = (node.data as { kind?: string }).kind;
    if (k) st.addNode(k as never, { x: node.position.x + 30, y: node.position.y + 30 });
    setMenuOpen(false);
  };

  /** 打开舞台：仅 3D 导演台卡片可用，切入内嵌 Stage3D */
  const openStage = () => {
    const st = useCanvasStore.getState();
    if (st.nodes.find((n) => n.id === id)?.data.kind === "director") {
      st.openDirectorForNode(id);
    }
    setMenuOpen(false);
  };

  /** 删除卡片及其连线 */
  const remove = () => {
    const st = useCanvasStore.getState();
    useCanvasStore.setState({
      nodes: st.nodes.filter((n) => n.id !== id),
      edges: st.edges.filter((e) => e.source !== id && e.target !== id),
      selectedId: null,
      dirtyVersion: st.dirtyVersion + 1,
    });
    setMenuOpen(false);
  };

  // ── 卡片内直接输入（2026-09-16 交互升级）──
  // 单击选中后，内容区主文本原位变成输入框，绑定该类型的主文本字段
  // （KIND_TEXT_FIELD，全部是 node-factory 真实字段）。nodrag 防止打字时拖动卡片。
  const textField = textFieldFor(kind);
  const fieldValue = textField ? String((d as Record<string, unknown>)[textField.field] ?? "") : "";

  /** 双击 = 打开右侧精细编辑（Inspector 自动展开进阶设置 L2） */
  const onCardDoubleClick = () => {
    useCanvasStore.getState().requestProEdit();
  };

  return (
    <article
      className={`nv-card${selected ? " on" : ""}${bondedCls}`}
      /**
       * 空间记忆（2026-09-18 用户裁定「下一代 · 第一层」）：
       * data-depth 暴露意图胶囊层深（1 表面 / 2 语义 / 3 实现），由 CSS 承担视觉分档。
       * 严格只改颜色，不改尺寸、不加 box-shadow——避免触碰冻结不变量
       * 「卡片实尺寸必须 240×200（磁吸落位基准）」与「不再有 box-shadow 光晕」。
       */
      data-depth={depth}
      style={{
        width: CARD_GEOMETRY.width,
        /**
         * 固定高度（2026-09-23 用户裁定修复「卡片大小不统一」）：
         * 原 minHeight 会被内容撑高（实测最高 ≈306px），既让画布上卡片高矮不一，
         * 也违反冻结不变量「卡片实尺寸必须 240×200（磁吸落位基准）」。
         * 现为 fixed height，超出部分由 .nv-card-body 的 overflow:hidden +
         * 缩略图弹性收缩（flex:1 1 auto）承担，DOM 实尺寸恒 240×200。
         */
        height: CARD_GEOMETRY.height,
        /* 圆角交由 .nv-card（16px）控制；此前内联 borderRadius 会压过圆角规则，故移除 */
        ["--nv-accent" as string]: style.color,
      }}
      onDoubleClick={onCardDoubleClick}
    >
      <Handle type="target" position={Position.Left} className="nv-handle" isConnectable={false} />
      <Handle type="source" position={Position.Right} className="nv-handle" isConnectable={false} />

      <header className="nv-card-head" style={{ height: CARD_GEOMETRY.headerHeight }}>
        <span className="nv-card-ico" aria-hidden>
          {style.icon}
        </span>
        <span className="nv-card-title" title={titleOf(d, style.label)}>
          {titleOf(d, style.label)}
        </span>
      </header>

      <div className="nv-card-body">
        <p className="nv-card-hint">{hint}</p>
        {thumb.url ? (
          <div className="nv-card-thumb">
            {thumb.video ? <video src={thumb.url} muted playsInline /> : <img src={thumb.url} alt="" />}
          </div>
        ) : null}
        {selected && textField ? (
          <textarea
            className="nv-card-editor nodrag nowheel"
            rows={textField.rows}
            value={fieldValue}
            placeholder={textField.placeholder}
            onChange={(e) => useCanvasStore.getState().updateNodeData(id, { [textField.field]: e.target.value })}
            onKeyDown={(e) => {
              // Esc 退出编辑（把焦点还给画布）；Enter 保留换行不拦截
              if (e.key === "Escape") (e.target as HTMLTextAreaElement).blur();
              e.stopPropagation();
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          summary ? <p className="nv-card-text">{summary}</p> : null
        )}
        {meta ? <p className="nv-card-meta">{meta}</p> : null}
      </div>

      <footer className="nv-card-foot" style={{ height: CARD_GEOMETRY.footerHeight }}>
        <span
          className="nv-lamp"
          style={{ background: LAMP_STYLE[lamp].color }}
          title={LAMP_STYLE[lamp].label}
        />
        <span className="nv-capsule" title={`意图胶囊：已展开 ${INTENT_LAYERS[depth - 1].label}`}>
          {INTENT_LAYERS.map((l, i) => (
            <i key={l.id} className={i < depth ? "on" : ""} title={l.label} />
          ))}
        </span>
        {layerCount > 0 ? <span className="nv-layers">×{layerCount}</span> : null}
        <span className="nv-foot-spacer" />
        <button
          type="button"
          className="nv-more nodrag"
          title="卡片菜单"
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((v) => !v);
          }}
        >
          ⋯
        </button>
        {menuOpen ? (
          <div className="nv-menu nodrag" onMouseLeave={() => setMenuOpen(false)}>
            {kind === "director" ? (
              <button type="button" onClick={openStage}>
                打开舞台
              </button>
            ) : null}
            <button type="button" onClick={pushVersion}>
              生成新版本
            </button>
            <button type="button" onClick={duplicate}>
              复制卡片
            </button>
            <button type="button" onClick={remove}>
              删除卡片
            </button>
          </div>
        ) : null}
      </footer>
    </article>
  );
}

export const NoviceCard = memo(NoviceCardImpl);
export default NoviceCard;
