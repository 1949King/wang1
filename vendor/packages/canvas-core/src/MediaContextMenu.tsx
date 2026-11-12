/**
 * 媒体右键菜单（2026-11-12）。
 *
 * 解决两件事：
 * 1. 浏览器默认右键菜单是英文 —— 媒体上直接 preventDefault，交给这里；
 * 2. 默认菜单里没有"加入我的资产" —— 这里补上（复用 localLibrary.addAsset）。
 */
import { useEffect } from "react";

import { addAsset } from "./localLibrary";
import type { MediaView } from "./mediaView";
import "./mediaContextMenu.css";

export type MediaMenuState = { x: number; y: number; media: MediaView | null; title: string };

export function MediaContextMenu({
  state,
  onClose,
  onZoom,
}: {
  state: MediaMenuState | null;
  onClose: () => void;
  onZoom: (m: MediaView) => void;
}) {
  useEffect(() => {
    if (!state) return undefined;
    const close = () => onClose();
    window.addEventListener("pointerdown", close);
    window.addEventListener("blur", close);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [state, onClose]);

  if (!state) return null;

  const copyUrl = async () => {
    if (!state.media) return;
    try {
      await navigator.clipboard.writeText(state.media.src);
    } catch {
      /* 剪贴板不可用时静默（不弹英文 alert） */
    }
    onClose();
  };

  const saveAsset = () => {
    if (!state.media) return;
    addAsset({
      title: state.title || (state.media.kind === "video" ? "视频" : "图片"),
      kind: state.media.kind,
      url: state.media.src,
      prompt: "",
    });
    onClose();
  };

  return (
    <div
      className="sg-mctx"
      style={{ left: state.x, top: state.y }}
      role="menu"
      onContextMenu={(e) => e.preventDefault()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {state.media ? (
        <>
          <button type="button" className="sg-mctx-item" onClick={() => { onZoom(state.media!); onClose(); }}>
            <span aria-hidden>⤢</span> 放大查看
          </button>
          <button type="button" className="sg-mctx-item" onClick={saveAsset}>
            <span aria-hidden>★</span> 收藏到我的资产
          </button>
          <div className="sg-mctx-sep" />
          <button type="button" className="sg-mctx-item" onClick={() => void copyUrl()}>
            <span aria-hidden>⧉</span> 复制{state.media.kind === "video" ? "视频" : "图片"}地址
          </button>
        </>
      ) : (
        <>
          <button type="button" className="sg-mctx-item" onClick={() => { document.execCommand("selectAll"); onClose(); }}>
            <span aria-hidden>▤</span> 全选
          </button>
          <div className="sg-mctx-sep" />
          <button type="button" className="sg-mctx-item" onClick={() => { window.location.reload(); }}>
            <span aria-hidden>⟳</span> 刷新画布
          </button>
        </>
      )}
    </div>
  );
}