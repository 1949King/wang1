/**
 * GalleryPanel.tsx — 画布图库（V4.41.16 真功能 · V4.41.17 大图预览 + 筛选）。
 *
 * 此前「打开图库」是占位（弹统计文字），V4.41.16 做成真面板：
 * 画布上所有**有产物的图片 / 视频节点**收进缩略图网格，
 * 点击缩略图 = 选中对应节点（画布自动高亮 + 右侧检查器显示）。
 *
 * V4.41.17 增补（用户拍板 A1+A2）：
 *  - **大图预览（lightbox）**：缩略图 hover 出现 ⤢ 角标，点击放大查看，
 *    ←→ 在产物间切换、Esc / 点遮罩关闭；不与「点击选中节点」冲突（两个动作分开）。
 *  - **类型筛选**：全部 / 图片 / 视频 三个 tab（复用 .oh-tabs 视觉家族）。
 *
 * 视觉复用 .oh-panel 外壳（与输出历史同一家族），网格/灯箱样式在 gallery.css。
 * 视频用 posterUrl（首帧）做缩略图。
 */
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { assetFromGallery } from "./assetFromOutputs";
import { useContextMenu } from "./hooks/useContextMenu";
import { addAsset } from "./localLibrary";
import { useCanvasStore } from "./store";
import { useWindowPanel } from "./hooks/useWindowPanel";

import "./gallery.css";
import "./ctxmenu.css";

interface GalleryItem {
  id: string;
  kind: "image" | "video";
  title: string;
  thumb: string;
  isVideo: boolean;
  /** 生成时用的提示词（右键「加入我的资产」要带上，空则不带） */
  prompt: string;
}

type GalleryFilter = "all" | "image" | "video";

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

export default function GalleryPanel({ onClose }: { onClose: () => void }) {
  const win = useWindowPanel("gallery");
  const nodes = useCanvasStore((s) => s.nodes);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const setSelected = useCanvasStore((s) => s.setSelected);

  const [filter, setFilter] = useState<GalleryFilter>("all");
  /** lightbox 正在查看的产物索引（基于 filtered 列表）；null = 关闭 */
  const [zoomIdx, setZoomIdx] = useState<number | null>(null);
  /** 右键菜单：把缩略图对应的产物收进「我的资产」 */
  const menu = useContextMenu<GalleryItem>();
  const [flash, setFlash] = useState("");

  useEffect(() => {
    if (!flash) return;
    const t = window.setTimeout(() => setFlash(""), 1800);
    return () => window.clearTimeout(t);
  }, [flash]);

  const items = useMemo<GalleryItem[]>(() => {
    const out: GalleryItem[] = [];
    for (const n of nodes || []) {
      const d = (n.data || {}) as Record<string, unknown>;
      const kind = str(d.kind);
      if (kind !== "image" && kind !== "video") continue;
      const videoUrl = str(d.videoUrl);
      const posterUrl = str(d.posterUrl);
      const imageUrl = str(d.imageUrl);
      const thumb = kind === "video" ? posterUrl || videoUrl : imageUrl;
      if (!thumb) continue; // 还没有产物的节点不进图库
      out.push({
        id: n.id,
        kind: kind as "image" | "video",
        title: str(d.label) || str(d.prompt).slice(0, 30) || (kind === "video" ? "视频" : "图片"),
        thumb,
        isVideo: kind === "video",
        prompt: str(d.prompt),
      });
    }
    // 新生成的排前面（节点数组顺序 = 添加顺序，倒序 = 最新在上）
    return out.reverse();
  }, [nodes]);

  const filtered = useMemo<GalleryItem[]>(() => {
    if (filter === "all") return items;
    return items.filter((it) => it.kind === filter);
  }, [items, filter]);

  /* lightbox 打开时：Esc 关闭 + ←→ 切换；产物列表变化后夹住越界索引 */
  useEffect(() => {
    if (zoomIdx === null) return;
    if (zoomIdx >= filtered.length) {
      setZoomIdx(filtered.length ? Math.min(zoomIdx, filtered.length - 1) : null);
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setZoomIdx(null);
      } else if (e.key === "ArrowLeft" && filtered.length > 1) {
        setZoomIdx((i) => (i === null ? null : (i - 1 + filtered.length) % filtered.length));
      } else if (e.key === "ArrowRight" && filtered.length > 1) {
        setZoomIdx((i) => (i === null ? null : (i + 1) % filtered.length));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomIdx, filtered.length]);

  const zoomItem = zoomIdx !== null ? filtered[zoomIdx] : null;

  /** 右键「加入我的资产」：映射失败就不存，并在头部说清原因。 */
  const saveToAssets = (it: GalleryItem) => {
    const draft = assetFromGallery(it);
    if (!draft) {
      setFlash("这一条没有可存的产物");
      return;
    }
    addAsset(draft);
    setFlash(`已加入我的资产：${draft.title}`);
  };

  return (
    <div className="oh-panel sg-gallery" data-pinned="0"
         ref={win.panelRef} style={win.style} onPointerDown={win.focusPanel}>
      <header className="oh-head" onPointerDown={win.startDrag}>
        <span className="oh-title">图库</span>
        <span className="oh-count">
          {flash || `共 ${items.length} 个产物${filter !== "all" ? ` · 当前 ${filtered.length}` : ""}`}
        </span>
        <span className="oh-spacer" />
        <button type="button" className="oh-min" onClick={win.minimize} title="最小化到任务栏">
          —
        </button>
        <button type="button" className="oh-close" onClick={onClose} title="关闭">
          ✕
        </button>
      </header>
      <div className="oh-tabs sg-gallery-tabs">
        {(["all", "image", "video"] as const).map((f) => (
          <button
            key={f}
            type="button"
            className={`oh-tab${filter === f ? " on" : ""}`}
            onClick={() => {
              setFilter(f);
              setZoomIdx(null);
            }}
          >
            {f === "all" ? "全部" : f === "image" ? "图片" : "视频"}
            {f === "all" ? null : <i>{items.filter((it) => it.kind === f).length}</i>}
          </button>
        ))}
      </div>
      <div className="sg-gallery-body">
        {filtered.length === 0 ? (
          <div className="sg-gallery-empty">
            {items.length === 0
              ? "画布上还没有图片 / 视频产物"
              : filter === "image"
                ? "没有图片产物"
                : "没有视频产物"}
            <br />
            {items.length === 0 ? (
              <span className="sg-gallery-hint">生成完成后会自动出现在这里</span>
            ) : null}
          </div>
        ) : (
          <div className="sg-gallery-grid">
            {filtered.map((it, idx) => (
              <button
                key={it.id}
                type="button"
                className={`sg-gallery-cell${selectedId === it.id ? " on" : ""}`}
                onClick={() => setSelected(it.id)}
                onContextMenu={(ev) => menu.open(ev, it)}
                title={`${it.isVideo ? "视频" : "图片"}：${it.title}\n（点击选中对应节点 · ⤢ 放大查看 · 右键加入我的资产）`}
              >
                <span className="sg-gallery-thumb">
                  <img src={it.thumb} alt="" loading="lazy" draggable={false} />
                  {it.isVideo ? <span className="sg-gallery-badge">▶</span> : null}
                  <span
                    role="button"
                    tabIndex={-1}
                    aria-label="放大查看"
                    className="sg-gallery-zoom"
                    onClick={(e) => {
                      e.stopPropagation();
                      setZoomIdx(idx);
                    }}
                  >
                    ⤢
                  </span>
                </span>
                <span className="sg-gallery-label">{it.title}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {zoomItem ? (
        <div
          className="sg-lightbox"
          onClick={(e) => {
            if (e.target === e.currentTarget) setZoomIdx(null);
          }}
        >
          <button
            type="button"
            className="sg-lightbox-nav sg-lightbox-nav--prev"
            onClick={() => setZoomIdx((i) => (i === null ? null : (i - 1 + filtered.length) % filtered.length))}
            title="上一个（←）"
          >
            ‹
          </button>
          <div className="sg-lightbox-stage">
            <img src={zoomItem.thumb} alt={zoomItem.title} draggable={false} />
            <div className="sg-lightbox-caption">
              {zoomItem.isVideo ? "▶ 视频" : "图片"} · {zoomItem.title} · {zoomIdx! + 1}/{filtered.length}
            </div>
          </div>
          <button
            type="button"
            className="sg-lightbox-nav sg-lightbox-nav--next"
            onClick={() => setZoomIdx((i) => (i === null ? null : (i + 1) % filtered.length))}
            title="下一个（→）"
          >
            ›
          </button>
          <button
            type="button"
            className="sg-lightbox-close"
            onClick={() => setZoomIdx(null)}
            title="关闭（Esc）"
          >
            ✕
          </button>
        </div>
      ) : null}

      {/* 右键菜单 portal 到 body：面板在 CSS 模式下带 translateX(-50%)，
          挂里面会把 clientX 当成相对面板的坐标，菜单会飘出去 */}
      {menu.state
        ? createPortal(
            <div
              className="sg-ctxmenu"
              style={{ left: menu.state.x, top: menu.state.y }}
              role="menu"
              onPointerDown={(ev) => ev.stopPropagation()}
              onContextMenu={(ev) => ev.preventDefault()}
            >
              <button
                type="button"
                className="sg-ctxmenu-item"
                disabled={!assetFromGallery(menu.state.target)}
                title="收进「我的资产」，之后在资产页按类型/语义找得到"
                onClick={() => {
                  saveToAssets(menu.state!.target);
                  menu.close();
                }}
              >
                <span className="sg-ctxmenu-ico" aria-hidden>★</span>
                加入我的资产
              </button>
              <div className="sg-ctxmenu-sep" />
              <button
                type="button"
                className="sg-ctxmenu-item"
                onClick={() => {
                  setSelected(menu.state!.target.id);
                  menu.close();
                }}
              >
                <span className="sg-ctxmenu-ico" aria-hidden>◎</span>
                选中该节点
              </button>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
