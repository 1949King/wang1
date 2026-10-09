/**
 * LibTV 空画布四卡 + 底栏（图一）。
 */
import { useEffect, useRef, useState } from "react";

import "./LibTvChrome.css";
import { getGraphFuture, getGraphPast } from "./stores/history-store";
import { useToolboxStore } from "./toolboxStore";
import { useCanvasStore } from "./store";
import type { NodeData } from "./store";

export type EmptyCardId = "script" | "threeview" | "refvideo" | "audiovideo";

const CARDS: {
  id: EmptyCardId;
  title: string;
  badge?: string;
  tone: string;
  icon: string;
}[] = [
  { id: "script", title: "故事脚本生成", tone: "#22c55e", icon: "▣" },
  { id: "threeview", title: "角色三视图", tone: "#ef4444", icon: "☺" },
  { id: "refvideo", title: "全能参考生视频", badge: "SD 2.5", tone: "#3b82f6", icon: "〰" },
  { id: "audiovideo", title: "音频生视频", badge: "SD 2.5", tone: "#a855f7", icon: "♫" },
];

export function LibTvEmptyState({
  onCard,
}: {
  onCard: (id: EmptyCardId) => void;
}) {
  return (
    <div className="libtv-empty">
      <div className="libtv-empty-hint">
        <span className="libtv-wand">✧</span>
        双击画布 自由生成节点
      </div>
      <div className="libtv-empty-cards">
        {CARDS.map((c) => (
          <button
            key={c.id}
            type="button"
            className="libtv-empty-card"
            onClick={() => onCard(c.id)}
          >
            <span className="libtv-empty-ico" style={{ color: c.tone }}>
              {c.icon}
            </span>
            <span className="libtv-empty-label">{c.title}</span>
            {c.badge ? <span className="libtv-badge">{c.badge}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * 底部停靠栏 V2（2026-10-10 C 方案重做）：dock 只留 4 按钮，其余全部收进
 * 「⚡工具」向上的**横向工具板**（4 组并排、组内横排、图标+文字常显）。
 *
 * 重做动机（用户实测截图反馈）：
 * 旧版一行塞 13 个无文字图标 + 右下浮层 4 胶囊 + ReactFlow 自带 Controls，
 * 三套控件叠加重复（缩放 3 处 / 历史 2 处），「排列混乱、不知道是哪些」。
 *
 * 约束：
 *  - props 签名**一字不动**（调用方 CanvasShell.tsx 在 canvas-magnetic-intent
 *    冻结区，本文件不在锁内但接口变更会连带冻结区改动）；
 *  - 容器类名 `.libtv-dock` 保留（styles.css 的定位样式继续生效，零冻结区触碰），
 *    子元素全部换 `ltd-*` 新类名，旧 `.libtv-dock-*` 样式自然失效；
 *  - 「数据」组（历史/灯位/导演/上游引用）的面板本体在 CanvasOverlays 渲染，
 *    开关经 toolboxStore（zustand）联动，不新增 props。
 *
 * V4.41.16 功能补全（占位 → 真功能）：
 *  - 「打开图库」→ 真·缩略图网格面板（GalleryPanel，toggleGallery 开关）；
 *  - 「预览」→ 连线时序预览（previewPlayer 拓扑序逐节点高亮，togglePreview 开关），
 *    挪进视图组；onPreview/onGallery props 保留在签名里但不再被调用
 *    （CanvasShell 的旧实现是统计提示，被真功能取代）；
 *  - 「历史栈」→ 拆成「↶ 撤销 / ↷ 重做」直连 store.undoGraph/redoGraph。
 */
export function LibTvBottomDock({
  zoomPct,
  onAdd,
  onAssets,
  onZoomFit,
  onHelp,
  onRole,
  onConnect,
  onSend,
  onShare,
  onBranch,
  onPreview,
  onHistory,
  onGallery,
}: {
  zoomPct: number;
  onAdd: () => void;
  onAssets: () => void;
  onZoomFit: () => void;
  onHelp: () => void;
  onRole: () => void;
  onConnect: () => void;
  onSend: () => void;
  onShare: () => void;
  onBranch: () => void;
  onPreview: () => void;
  onHistory: () => void;
  onGallery: () => void;
}) {
  const [toolsOpen, setToolsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const historyOpen = useToolboxStore((s) => s.historyOpen);
  const lightingOpen = useToolboxStore((s) => s.lightingOpen);
  const directorOpen = useToolboxStore((s) => s.directorOpen);
  const galleryOpen = useToolboxStore((s) => s.galleryOpen);
  const previewPlaying = useToolboxStore((s) => s.previewPlaying);
  const previewStep = useToolboxStore((s) => s.previewStep);
  const previewTotal = useToolboxStore((s) => s.previewTotal);
  const upstreamRefs = useToolboxStore((s) => s.upstreamRefs);
  const toggleHistory = useToolboxStore((s) => s.toggleHistory);
  const toggleLighting = useToolboxStore((s) => s.toggleLighting);
  const toggleDirector = useToolboxStore((s) => s.toggleDirector);
  const toggleGallery = useToolboxStore((s) => s.toggleGallery);
  const togglePreview = useToolboxStore((s) => s.togglePreview);
  const toggleUpstreamRefs = useToolboxStore((s) => s.toggleUpstreamRefs);
  // 撤销/重做直连画布 store（V4.41.16：「历史栈」占位 → 真按钮）
  const undoGraph = useCanvasStore((s) => s.undoGraph);
  const redoGraph = useCanvasStore((s) => s.redoGraph);
  // V4.41.17：开板时读一次历史栈步数进 title（history-store 是模块级数组，非响应式；
  // toolsOpen 变化触发重渲染时刷新，关板不读）
  const pastCount = toolsOpen ? getGraphPast().length : 0;
  const futureCount = toolsOpen ? getGraphFuture().length : 0;
  // 保留引用避免「未使用参数」告警：签名不能动（冻结区调用点），旧实现已被真功能取代
  void onPreview;
  void onHistory;
  void onGallery;

  /* 点击外部 / Esc 关闭工具板（面板类开关不关板：开了就让它开着） */
  useEffect(() => {
    if (!toolsOpen) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setToolsOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setToolsOpen(false);
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [toolsOpen]);

  /** 触发类动作：执行后随手关板（保持「工具板是瞬时操作面板」的语义） */
  const fire = (fn: () => void) => () => {
    fn();
    setToolsOpen(false);
  };

  return (
    <div className="libtv-dock" ref={rootRef}>
      <div className="ltd-main">
        <button type="button" className="ltd-btn" onClick={onAssets} title="资产库（图片 / 视频 / 音频素材）">
          <span className="ltd-ico">📁</span>资产
        </button>
        <button type="button" className="ltd-btn ltd-btn--primary" onClick={onAdd} title="添加节点（双击画布亦可）">
          <span className="ltd-plus">＋</span>添加
        </button>
        <button type="button" className="ltd-btn" onClick={onZoomFit} title="聚焦全部（缩放复位）">
          <span className="ltd-ico">⊙</span>
          <span className="ltd-zoom">{zoomPct}%</span>
        </button>
        <button
          type="button"
          className={`ltd-btn ltd-tools${toolsOpen ? " on" : ""}`}
          onClick={() => setToolsOpen((v) => !v)}
          title="画布工具：视图 / 节点 / 数据 / 帮助"
          aria-expanded={toolsOpen}
        >
          {previewPlaying && previewTotal > 0 ? (
            <>
              <span className="ltd-ico">⌕</span>预览 {previewStep + 1}/{previewTotal}
            </>
          ) : (
            <>
              <span className="ltd-ico">⚡</span>工具{toolsOpen ? " ▴" : " ▾"}
            </>
          )}
        </button>
      </div>

      {toolsOpen ? (
        <div className="ltd-board" role="menu">
          <div className="ltd-group">
            <div className="ltd-group-title">视图</div>
            <div className="ltd-group-items">
              <button type="button" className="ltd-item" onClick={fire(onZoomFit)}>
                <span className="ltd-ico">▦</span>聚焦全部
              </button>
              <button type="button" className="ltd-item" onClick={fire(onRole)}>
                <span className="ltd-ico">☺</span>角色三视图
              </button>
              <button type="button" className="ltd-item" onClick={fire(onConnect)}>
                <span className="ltd-ico">⚭</span>自动连线
              </button>
              <button
                type="button"
                className={`ltd-item${previewPlaying ? " on" : ""}`}
                onClick={togglePreview}
                title="时序预览：按连线拓扑从上游到下游逐节点高亮（再点一次停止）"
              >
                <span className="ltd-ico">⌕</span>{previewPlaying ? "停止预览" : "时序预览"}
              </button>
            </div>
          </div>

          <div className="ltd-group">
            <div className="ltd-group-title">节点</div>
            <div className="ltd-group-items">
              <button type="button" className="ltd-item" onClick={fire(onSend)} title="把选中节点发送到剪辑时间线">
                <span className="ltd-ico">✈</span>发送到剪辑
              </button>
              <button type="button" className="ltd-item" onClick={fire(onShare)}>
                <span className="ltd-ico">⤴</span>分享 JSON
              </button>
              <button type="button" className="ltd-item" onClick={fire(onBranch)} title="复制选中节点为新分支">
                <span className="ltd-ico">⎇</span>从选中分支
              </button>
              <button
                type="button"
                className={`ltd-item${galleryOpen ? " on" : ""}`}
                onClick={toggleGallery}
                title="图库：画布全部图片/视频产物的缩略图网格，点击定位节点"
              >
                <span className="ltd-ico">▤</span>打开图库
              </button>
            </div>
          </div>

          <div className="ltd-group">
            <div className="ltd-group-title">数据</div>
            <div className="ltd-group-items">
              <button
                type="button"
                className={`ltd-item${historyOpen ? " on" : ""}`}
                onClick={toggleHistory}
                title="输出历史（Ctrl+H）"
              >
                <span className="ltd-ico">⏱</span>输出历史
              </button>
              <button
                type="button"
                className={`ltd-item${lightingOpen ? " on" : ""}`}
                onClick={toggleLighting}
                title="电影级灯位：24 主光位 + 9 轮廓光（Ctrl+L）"
              >
                <span className="ltd-ico">💡</span>灯位
              </button>
              <button
                type="button"
                className={`ltd-item${directorOpen ? " on" : ""}`}
                onClick={toggleDirector}
                title="导演指导：诊断分镜缺什么并一键写回（Ctrl+D）"
              >
                <span className="ltd-ico">🎬</span>导演指导
              </button>
              <button
                type="button"
                className={`ltd-item${upstreamRefs ? " on" : ""}`}
                onClick={toggleUpstreamRefs}
                title="连线上游素材引用：开启后连线的上游产物会写进下游节点的引用字段（不覆盖你已设的首帧）"
              >
                <span className="ltd-ico">🔗</span>上游引用
                <span className={`ltd-switch${upstreamRefs ? " on" : ""}`} aria-hidden="true" />
              </button>
            </div>
          </div>

          <div className="ltd-group">
            <div className="ltd-group-title">帮助</div>
            <div className="ltd-group-items">
              <button
                type="button"
                className="ltd-item"
                onClick={fire(undoGraph)}
                title={`撤销上一步画布操作（Ctrl+Z）${pastCount ? ` · 可撤销 ${pastCount} 步` : " · 已是最早状态"}`}
              >
                <span className="ltd-ico">↶</span>撤销
              </button>
              <button
                type="button"
                className="ltd-item"
                onClick={fire(redoGraph)}
                title={`重做被撤销的操作（Ctrl+Y）${futureCount ? ` · 可重做 ${futureCount} 步` : " · 没有可重做的操作"}`}
              >
                <span className="ltd-ico">↷</span>重做
              </button>
              <button type="button" className="ltd-item" onClick={fire(onHelp)} title="快捷键与命令面板">
                <span className="ltd-ico">?</span>快捷键
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 右键菜单：添加节点 / 添加资源（图二） */
export type CtxPaneAction =
  | { type: "node"; kind: NodeData["kind"] }
  | { type: "stage3d" }
  | { type: "breakdown" }
  | { type: "smart_edit" }
  | { type: "upload" }
  | { type: "history" }
  | { type: "assets" }
  | { type: "palette" }
  | { type: "paste" };

export function LibTvPaneContextMenu({
  onAction,
}: {
  onAction: (a: CtxPaneAction) => void;
}) {
  return (
    <>
      <div className="ctx-menu-title">添加节点</div>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "prompt" })}>
        <span className="ctx-ico">☰</span> 文本
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "image" })}>
        <span className="ctx-ico">🖼</span> 图片
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "video" })}>
        <span className="ctx-ico">▶</span> 视频
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "smart_edit" })}>
        <span className="ctx-ico">✂</span> 智能剪辑 <span className="badge-beta">Beta</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "director" })}>
        <span className="ctx-ico">🎥</span> 3D 导演台节点 <span className="badge-new">NEW</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "digitalHuman" })}>
        <span className="ctx-ico">🧑</span> 数字人 <span className="badge-new">NEW</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "stage3d" })}>
        <span className="ctx-ico">▦</span> 打开导演台页
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "animation" })}>
        <span className="ctx-ico">🎞️</span> 逐帧动画
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "panorama" })}>
        <span className="ctx-ico">🌐</span> 全景
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "note" })}>
        <span className="ctx-ico">📌</span> 画布笔记
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "source" })}>
        <span className="ctx-ico">📂</span> 源文件
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "breakdown" })}>
        <span className="ctx-ico">🎞</span> 逐帧拉片 <span className="libtv-badge">SD 2.5</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "audio" })}>
        <span className="ctx-ico">▮</span> 音频
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "node", kind: "script" })}>
        <span className="ctx-ico">📄</span> 脚本 <span className="ctx-chev">›</span>
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "assets" })}>
        <span className="ctx-ico">◇</span> 素材库 <span className="ctx-chev">›</span>
      </button>
      <div className="ctx-menu-sep" />
      <div className="ctx-menu-title">添加资源</div>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "upload" })}>
        <span className="ctx-ico">⬆</span> 上传
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "history" })}>
        <span className="ctx-ico">↩</span> 从生成历史选择
      </button>
      <div className="ctx-menu-sep" />
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "palette" })}>
        搜索添加…
      </button>
      <button type="button" className="ctx-menu-item" onClick={() => onAction({ type: "paste" })}>
        粘贴
      </button>
    </>
  );
}
