/**
 * 媒体查看器宿主（2026-11-13）：双击放大/播放 + 右键中文菜单。
 *
 * 从 App.tsx 抽出：App 已顶到单文件 2000 行规模守卫，逻辑不再往里塞。
 * 用 document 级事件委托，避免改冻结区的 nodes.tsx / CanvasShell.tsx。
 */
import { useEffect, useState } from "react";

import { MediaContextMenu, type MediaMenuState } from "./MediaContextMenu";
import { MediaLightbox } from "./MediaLightbox";
import { classifyMedia, type MediaView } from "./mediaView";

export function MediaViewerHost() {
  const [mediaView, setMediaView] = useState<MediaView | null>(null);
  const [mediaMenu, setMediaMenu] = useState<MediaMenuState | null>(null);

  useEffect(() => {
    const onDblClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (t.closest("input, textarea, select, [contenteditable='true'], .sg-mlb-mask")) return;
      const el = t.closest("img, video") as HTMLImageElement | HTMLVideoElement | null;
      if (!el) return;
      const src = (el as HTMLVideoElement).currentSrc || (el as HTMLImageElement).src || "";
      const media = classifyMedia(el.tagName, src);
      if (!media) return;
      e.preventDefault();
      e.stopPropagation();
      setMediaView(media);
    };
    const onCtx = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      if (t.closest("input, textarea, select, [contenteditable='true'], .sg-mctx, .sg-mlb-mask")) return;
      e.preventDefault();
      e.stopPropagation();
      const el = t.closest("img, video") as HTMLImageElement | HTMLVideoElement | null;
      if (!el) {
        // 非媒体区域也给中文菜单（否则会回落到 QtWebEngine 的英文默认菜单）
        setMediaMenu({ x: e.clientX, y: e.clientY, media: null, title: "" });
        return;
      }
      const src = (el as HTMLVideoElement).currentSrc || (el as HTMLImageElement).src || "";
      const media = classifyMedia(el.tagName, src);
      const nodeTitle = (el.closest(".sg-node")?.querySelector(".head")?.textContent || "").trim().slice(0, 30);
      setMediaMenu({ x: e.clientX, y: e.clientY, media, title: nodeTitle });
    };
    document.addEventListener("dblclick", onDblClick, true);
    document.addEventListener("contextmenu", onCtx, true);
    return () => {
      document.removeEventListener("dblclick", onDblClick, true);
      document.removeEventListener("contextmenu", onCtx, true);
    };
  }, []);

  return (
    <>
      <MediaLightbox media={mediaView} onClose={() => setMediaView(null)} />
      <MediaContextMenu
        state={mediaMenu}
        onClose={() => setMediaMenu(null)}
        onZoom={(m) => setMediaView(m)}
      />
    </>
  );
}
