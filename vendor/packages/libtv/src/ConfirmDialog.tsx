/** 应用内确认框 — 替代 Qt WebEngine 下难读的 window.confirm */
import { useEffect, useRef } from "react";

export type ConfirmDialogProps = {
  open: boolean;
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

export default function ConfirmDialog({
  open,
  title = "请确认",
  message,
  confirmLabel = "确定",
  cancelLabel = "取消",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="sg-modal-root" role="presentation" onClick={onCancel}>
      <div
        className="sg-modal"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="sg-modal-title"
        aria-describedby="sg-modal-desc"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="sg-modal-title" className="sg-modal-title">
          {title}
        </h2>
        <p id="sg-modal-desc" className="sg-modal-body">
          {message}
        </p>
        <div className="sg-modal-actions">
          <button type="button" className="btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={okRef}
            type="button"
            className={`btn primary${danger ? " danger" : ""}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
