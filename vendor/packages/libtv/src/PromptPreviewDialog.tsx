import { useEffect, useRef, useState } from "react";
import type { PromptItem } from "./promptLibrary";
import { maturityLabel } from "./promptLibrary";
import PromptCoverImage from "./PromptCoverImage";
import { promptImageSrc } from "./bridge";

export type PromptPreviewDialogProps = {
  item: PromptItem | null;
  onClose: () => void;
  onApply: (item: PromptItem) => void;
  onToggleFavorite: (item: PromptItem) => void;
  onStatus?: (msg: string) => void;
};

export default function PromptPreviewDialog({
  item,
  onClose,
  onApply,
  onToggleFavorite,
  onStatus,
}: PromptPreviewDialogProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [zoomUrl, setZoomUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!item) return;
    closeRef.current?.focus();
    setZoomUrl(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (zoomUrl) setZoomUrl(null);
        else onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, onClose, zoomUrl]);

  if (!item) return null;

  const images = [
    item.coverUrl,
    ...item.referenceImageUrls.filter((u) => u && u !== item.coverUrl),
  ].filter(Boolean);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(item.prompt);
      onStatus?.("已复制提示词");
    } catch {
      onStatus?.("复制失败，请手动选择文本复制");
    }
  };

  return (
    <>
      <div className="sg-modal-root prompt-preview-root" role="presentation" onClick={onClose}>
        <div
          className="sg-modal prompt-preview-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="prompt-preview-title"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="prompt-preview-head">
            <div>
              <h2 id="prompt-preview-title" className="sg-modal-title">
                {item.title}
              </h2>
              <div className="prompt-preview-meta">
                {item.categoryGroup} · {item.category}
                <span className={`prompt-badge ${item.maturity}`}>{maturityLabel(item.maturity)}</span>
                {item.favorite ? <span className="prompt-badge sfw">已收藏</span> : null}
              </div>
            </div>
            <button ref={closeRef} type="button" className="sg-modal-x" onClick={onClose} aria-label="关闭">
              ×
            </button>
          </div>

          {images.length ? (
            <div className={`prompt-preview-gallery${images.length === 1 ? " single" : ""}`}>
              {images.map((url, i) => (
                <button
                  key={`${url}-${i}`}
                  type="button"
                  className="prompt-preview-img-wrap"
                  title="点击查看完整大图"
                  onClick={() => setZoomUrl(url)}
                >
                  <PromptCoverImage url={url} fit="contain" alt={i === 0 ? "封面" : `参考图 ${i}`} />
                </button>
              ))}
            </div>
          ) : (
            <div className="prompt-preview-noimg">
              暂无参考图（拾光精选/短剧离线包无封面；部分社区条目本身未附带图片）
            </div>
          )}

          {item.description ? <p className="prompt-preview-desc">{item.description}</p> : null}

          {item.tags.length ? (
            <div className="prompt-preview-tags">
              {item.tags.slice(0, 24).map((t) => (
                <span key={t} className="prompt-preview-tag">
                  {t}
                </span>
              ))}
            </div>
          ) : null}

          <label className="prompt-preview-label">完整提示词</label>
          <textarea className="prompt-preview-text" readOnly value={item.prompt} rows={8} />

          <div className="sg-modal-actions prompt-preview-actions">
            <button type="button" className="btn" onClick={onClose}>
              关闭
            </button>
            <button type="button" className="btn" onClick={() => void onCopy()}>
              复制
            </button>
            <button type="button" className="btn" onClick={() => onToggleFavorite(item)}>
              {item.favorite ? "★ 取消收藏" : "☆ 收藏"}
            </button>
            <button
              type="button"
              className="btn primary"
              onClick={() => {
                onApply(item);
                onClose();
              }}
            >
              应用到选中
            </button>
            {item.githubUrl ? (
              <a className="btn link" href={item.githubUrl} target="_blank" rel="noreferrer">
                来源
              </a>
            ) : null}
          </div>
        </div>
      </div>

      {zoomUrl ? (
        <div
          className="prompt-image-lightbox"
          role="presentation"
          onClick={() => setZoomUrl(null)}
        >
          <img src={promptImageSrc(zoomUrl)} alt="完整参考图" draggable={false} />
          <p className="prompt-image-lightbox-hint">点击任意处关闭 · Esc</p>
        </div>
      ) : null}
    </>
  );
}
