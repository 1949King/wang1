/**
 * 媒体查看器（2026-11-12）：双击图片放大、双击视频直接播放。
 *
 * 交互：Esc / 点背景 / × 关闭；图片点一下在「适应屏幕 ↔ 原始大小」间切换。
 */
import { useEffect, useState } from "react";

import type { MediaView } from "./mediaView";
import "./mediaLightbox.css";

export function MediaLightbox({ media, onClose }: { media: MediaView | null; onClose: () => void }) {
  const [zoom, setZoom] = useState(false);

  useEffect(() => {
    if (!media) return undefined;
    setZoom(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [media, onClose]);

  if (!media) return null;

  return (
    <div className="sg-mlb-mask" onClick={onClose} role="dialog" aria-modal="true" aria-label="媒体预览">
      <div className="sg-mlb-bar" onClick={(e) => e.stopPropagation()}>
        <span className="sg-mlb-tip">{media.kind === "video" ? "视频预览（Esc 关闭）" : "图片预览 · 点击画面缩放 · Esc 关闭"}</span>
        {media.kind === "image" ? (
          <button type="button" onClick={() => setZoom((v) => !v)}>{zoom ? "适应屏幕" : "原始大小"}</button>
        ) : null}
        <button type="button" onClick={onClose}>关闭</button>
      </div>
      <div className="sg-mlb-stage" onClick={(e) => e.stopPropagation()}>
        {media.kind === "image" ? (
          <img
            src={media.src}
            alt=""
            className={zoom ? "zoom" : ""}
            onClick={() => setZoom((v) => !v)}
            draggable={false}
          />
        ) : (
          <video src={media.src} controls autoPlay loop playsInline />
        )}
      </div>
    </div>
  );
}