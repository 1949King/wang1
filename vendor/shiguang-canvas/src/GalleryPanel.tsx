/**
 * GalleryPanel.tsx — 画布图库（V4.41.16 真功能）。
 *
 * 此前「打开图库」是占位（弹一行统计文字），本刀做成真面板：
 * 画布上所有**有产物的图片 / 视频节点**收进缩略图网格，
 * 点击缩略图 = 选中对应节点（画布自动高亮 + 右侧检查器显示）。
 *
 * 视觉复用 .oh-panel 外壳（与输出历史同一家族），网格区单独样式（gallery.css）。
 * 视频用 posterUrl（首帧）做缩略图。
 */
import { useMemo } from "react";

import { useCanvasStore } from "./store";

import "./gallery.css";

interface GalleryItem {
  id: string;
  kind: "image" | "video";
  title: string;
  thumb: string;
  isVideo: boolean;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

export default function GalleryPanel({ onClose }: { onClose: () => void }) {
  const nodes = useCanvasStore((s) => s.nodes);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const setSelected = useCanvasStore((s) => s.setSelected);

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
      });
    }
    // 新生成的排前面（节点数组顺序 = 添加顺序，倒序 = 最新在上）
    return out.reverse();
  }, [nodes]);

  return (
    <div className="oh-panel sg-gallery" data-pinned="0">
      <header className="oh-head">
        <span className="oh-title">图库</span>
        <span className="oh-count">共 {items.length} 个产物</span>
        <span className="oh-spacer" />
        <button type="button" className="oh-close" onClick={onClose} title="关闭">
          ✕
        </button>
      </header>
      <div className="sg-gallery-body">
        {items.length === 0 ? (
          <div className="sg-gallery-empty">
            画布上还没有图片 / 视频产物
            <br />
            <span className="sg-gallery-hint">生成完成后会自动出现在这里</span>
          </div>
        ) : (
          <div className="sg-gallery-grid">
            {items.map((it) => (
              <button
                key={it.id}
                type="button"
                className={`sg-gallery-cell${selectedId === it.id ? " on" : ""}`}
                onClick={() => setSelected(it.id)}
                title={`${it.isVideo ? "视频" : "图片"}：${it.title}\n（点击选中对应节点）`}
              >
                <span className="sg-gallery-thumb">
                  <img src={it.thumb} alt="" loading="lazy" draggable={false} />
                  {it.isVideo ? <span className="sg-gallery-badge">▶</span> : null}
                </span>
                <span className="sg-gallery-label">{it.title}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
