import { useEffect, useMemo, useRef, useState } from "react";
import type { NodeData } from "./store";
import { listNodeDefinitions } from "./plugins/node-registry";
import { isPluginNodeType } from "./infiniteCoreNodes";
import { NOVICE_ENTRY, NOVICE_STAGE_GROUPS } from "./novice/types";

export type PaletteItem = {
  type: string;
  label: string;
  keywords: string;
  hint: string;
  plugin?: boolean;
  /** V4.41.19 AI 画布重组：节点大类（左侧 sidebar 分组 + Ctrl+K 分组用） */
  category?: NodeCategory;
};

/** V4.41.19 节点五大类（业界共识「左=库」按类别分块；空类「双击空白/搜索/临时」已删） */
export const NODE_CATEGORIES = [
  { id: "create", title: "创作", icon: "✍️" },
  { id: "media", title: "媒体", icon: "🎞️" },
  { id: "generate", title: "生成", icon: "✨" },
  { id: "space", title: "空间", icon: "🧭" },
  { id: "note", title: "标注", icon: "📌" },
] as const;

export type NodeCategory = (typeof NODE_CATEGORIES)[number]["id"];

/** 内置节点（拾光 + infinite 核心对齐 · V4.41.19 按 5 大类编目） */
export const NODE_PALETTE: PaletteItem[] = [
  // ── 创作 ─────────────────────────────────────────────
  { type: "script", label: "剧本", keywords: "script 剧本 text", hint: "剧本文本节点", category: "create" },
  { type: "directorCard", label: "导演卡", keywords: "directorCard 导演卡 剧本 拆解 拉片", hint: "剧本输入 → 自动拆解分镜", category: "create" },
  { type: "shot", label: "镜头", keywords: "shot 镜头 分镜", hint: "分镜 / 生图主节点", category: "create" },
  { type: "shotlist", label: "分镜表", keywords: "shotlist 分镜表 表格", hint: "AI-Canvas 对齐 · 可编辑镜号表", category: "create" },
  { type: "storyboard", label: "宫格分镜", keywords: "storyboard 宫格 九宫格", hint: "AI-Canvas 对齐 · 交互裁格", category: "create" },
  { type: "prompt", label: "提示词", keywords: "prompt 提示词 style", hint: "可复用提示词", category: "create" },
  { type: "text", label: "文本", keywords: "text 文本 infinite", hint: "infinite 对齐 · 说明/提示", category: "create" },
  { type: "character", label: "角色", keywords: "character 角色 捏脸 形象 脸 角色库", hint: "角色库条目 · 点卡片打开捏脸", category: "create" },
  // ── 媒体 ─────────────────────────────────────────────
  { type: "image", label: "图片", keywords: "image 图片 图", hint: "图片资产节点", category: "media" },
  { type: "video", label: "视频", keywords: "video 视频 运镜 参考", hint: "视频生成 / 可上传参考片段", category: "media" },
  { type: "audio", label: "音频", keywords: "audio 音频 配音", hint: "音频节点", category: "media" },
  { type: "music", label: "音乐", keywords: "music 音乐 BGM 配乐 yuE suno", hint: "音乐节点（Suno / YuE 乐）", category: "media" },
  { type: "source", label: "源文件", keywords: "source 源文件 本地 上传", hint: "本地图/视频/音频/文本", category: "media" },
  // ── 生成 ─────────────────────────────────────────────
  { type: "generator", label: "生成器", keywords: "generator 生成", hint: "汇聚上游批量生成", category: "generate" },
  { type: "config", label: "生成配置", keywords: "config 配置 generation", hint: "infinite 对齐 · 锁定生成参数", category: "generate" },
  { type: "digitalHuman", label: "数字人", keywords: "digital human 数字人 tts 配音 口型", hint: "形象 + 台词配音；口型后置", category: "generate" },
  { type: "animation", label: "逐帧动画", keywords: "animation sprite 逐帧 动作", hint: "Sprite Sheet / 占位 / AI", category: "generate" },
  { type: "codeVideo", label: "做图形动画", keywords: "codeVideo 图形动画 字幕 图表 几何 html 逐帧 渲染 代码成片 一键成片", hint: "字幕/图表/几何动画 · Chromium 逐帧 + ffmpeg 编码（诚实失败）", category: "generate" },
  // ── 空间 ─────────────────────────────────────────────
  { type: "director", label: "3D 导演台", keywords: "director stage3d 导演台 3d", hint: "自研 Stage3D · 截图回写", category: "space" },
  { type: "panorama", label: "全景", keywords: "panorama 全景 360", hint: "等距柱状图环视", category: "space" },
  { type: "group", label: "编组", keywords: "group 编组 组", hint: "容器编组", category: "space" },
  // ── 标注 ─────────────────────────────────────────────
  { type: "markdown", label: "Markdown", keywords: "markdown md 文档 说明", hint: "AI-Canvas 对齐 · 文档节点", category: "note" },
  { type: "note", label: "画布笔记", keywords: "note 笔记 标注 箭头", hint: "文字 / 形状标注", category: "note" },
];

/** 按大类分组（左侧 sidebar / Ctrl+K 共用；插件节点无 category 归「扩展」组） */
export function groupPaletteByCategory(items: PaletteItem[]): { cat: string; title: string; icon: string; items: PaletteItem[] }[] {
  const groups = new Map<string, { cat: string; title: string; icon: string; items: PaletteItem[] }>();
  // 先按内置 5 类建组（保持声明顺序）
  NODE_CATEGORIES.forEach((c) => {
    groups.set(c.id, { cat: c.id, title: c.title, icon: c.icon, items: [] });
  });
  let ext = groups.get("__ext__");
  items.forEach((it) => {
    if (it.category && groups.has(it.category)) {
      groups.get(it.category)!.items.push(it);
    } else {
      if (!ext) {
        ext = { cat: "__ext__", title: "扩展", icon: "🧩", items: [] };
        groups.set("__ext__", ext);
      }
      ext.items.push(it);
    }
  });
  return Array.from(groups.values()).filter((g) => g.items.length > 0);
}

const BUILTIN_TYPES = new Set(NODE_PALETTE.map((p) => p.type));

/** 合并内置 + 已注册插件节点（供搜索面板） */
export function buildFullPalette(): PaletteItem[] {
  const pluginItems: PaletteItem[] = listNodeDefinitions()
    .filter((d) => d.showInCreateMenu !== false && !BUILTIN_TYPES.has(d.type))
    .map((d) => ({
      type: d.type,
      label: d.title,
      keywords: `${d.type} ${d.title} ${d.description || ""} plugin`,
      hint: d.description || (isPluginNodeType(d.type) ? "插件节点" : "扩展节点"),
      plugin: isPluginNodeType(d.type),
    }));
  return [...NODE_PALETTE, ...pluginItems];
}

type Props = {
  open: boolean;
  x: number;
  y: number;
  onClose: () => void;
  onPick: (type: string) => void;
};

export default function NodePalette({ open, x, y, onClose, onPick }: Props) {
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const fullPalette = useMemo(() => buildFullPalette(), [open]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return fullPalette;
    return fullPalette.filter(
      (it) =>
        it.label.toLowerCase().includes(s) ||
        it.type.includes(s) ||
        it.keywords.toLowerCase().includes(s),
    );
  }, [q, fullPalette]);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setHi(0);
    const t = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    setHi(0);
  }, [q]);

  if (!open) return null;

  const pick = (type: string) => {
    onPick(type);
    onClose();
  };

  return (
    <div
      className="node-palette"
      style={{ left: Math.min(x, window.innerWidth - 280), top: Math.min(y, window.innerHeight - 320) }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        className="node-palette-input"
        placeholder="搜索节点…（↑↓ 选择，Enter 确认，Esc 关闭）"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            setHi((h) => Math.min(h + 1, Math.max(filtered.length - 1, 0)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHi((h) => Math.max(h - 1, 0));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const hit = filtered[hi] || filtered[0];
            if (hit) pick(hit.type);
          }
        }}
      />
      <div className="node-palette-list">
        {filtered.length === 0 ? (
          <div className="node-palette-empty">无匹配节点</div>
        ) : (
          filtered.map((it, i) => (
            <button
              key={it.type}
              type="button"
              className={`node-palette-item${i === hi ? " on" : ""}`}
              onMouseEnter={() => setHi(i)}
              onClick={() => pick(it.type)}
            >
              <span className="node-palette-label">
                {it.label}
                {it.plugin ? <span className="node-palette-badge">插件</span> : null}
              </span>
              <span className="node-palette-hint">{it.hint}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

/** 左侧按钮栏用：内置 + 插件节点 */
export function buildAddNodeItems(): PaletteItem[] {
  return buildFullPalette();
}

/**
 * 小白模式「意图入口」分组（P0，2026-10-11）：21 种内置卡片**全量**按 7 个创作阶段
 * 分组（开始创作/做画面/做声音/摆位与实拍/批量与设定/素材与笔记/整理），
 * 插件节点保留在「扩展」组 —— 与专业模式的 5 大类并存，互不影响。
 *
 * 措辞与分组来自 novice/types.ts 的 NOVICE_ENTRY（用户拍板的 2026-10-11 原型 v3）。
 * 返回结构兼容 AddNodeGroups 组件（cat/title/icon/items）。
 */
export function buildNoviceAddNodeGroups(): {
  cat: string;
  title: string;
  icon: string;
  items: PaletteItem[];
}[] {
  // 技术名查表：专业模式 label（hover 提示里带原名，小白↔专业互认）
  const techLabel = new Map(NODE_PALETTE.map((p) => [p.type, p.label]));
  const groups: { cat: string; title: string; icon: string; items: PaletteItem[] }[] =
    NOVICE_STAGE_GROUPS.map((g) => ({
      cat: g.id,
      title: g.title,
      icon: g.icon,
      items: [] as PaletteItem[],
    }));
  const byStage = new Map(groups.map((g) => [g.cat, g]));

  // 21 种内置 kind 全量入组（一个不少 —— 改变组织方式，不减少可见性）
  for (const [kind, entry] of Object.entries(NOVICE_ENTRY)) {
    const bucket = byStage.get(entry.stage);
    if (!bucket) continue;
    const tech = techLabel.get(kind) || kind;
    bucket.items.push({
      type: kind,
      label: entry.name,
      keywords: `${kind} ${entry.name} ${tech} ${entry.desc}`,
      hint: `${entry.desc}（专业模式：${tech}）`,
    });
  }

  // 插件节点照旧归「扩展」组（与 groupPaletteByCategory 同款行为）
  const pluginItems: PaletteItem[] = listNodeDefinitions()
    .filter((d) => d.showInCreateMenu !== false && isPluginNodeType(d.type))
    .map((d) => ({
      type: d.type,
      label: d.title,
      keywords: `${d.type} ${d.title} ${d.description || ""} plugin`,
      hint: d.description || "插件节点",
      plugin: true,
    }));
  if (pluginItems.length) {
    groups.push({ cat: "__ext__", title: "扩展", icon: "🧩", items: pluginItems });
  }
  return groups.filter((g) => g.items.length > 0);
}

/** 判断是否为内置 kind（非插件 registry type） */
export function isBuiltinNodeKind(type: string): type is NodeData["kind"] {
  const kinds: NodeData["kind"][] = [
    "shot", "script", "image", "video", "prompt", "text", "config", "generator", "group", "audio",
    "markdown", "shotlist", "storyboard", "director", "directorCard", "digitalHuman", "animation", "panorama", "note", "source", "music",
    "character", "codeVideo",
  ];
  return kinds.includes(type as NodeData["kind"]);
}
