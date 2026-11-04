import { useEffect, useMemo, useRef, useState } from "react";

export type CommandItem = {
  id: string;
  label: string;
  hint?: string;
  shortcut?: string;
  keywords?: string;
  run: () => void;
};

export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return Boolean(el?.closest?.("input, textarea, select, [contenteditable='true']"));
}

/** 指令面板：Ctrl+K / Ctrl+P / / 打开，可搜索并显示快捷键 */
export default function CommandPalette({
  open,
  title,
  placeholder,
  items,
  onClose,
}: {
  open: boolean;
  title: string;
  placeholder?: string;
  items: CommandItem[];
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [hi, setHi] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return items;
    return items.filter((it) => {
      const blob = `${it.label} ${it.hint || ""} ${it.shortcut || ""} ${it.keywords || ""} ${it.id}`.toLowerCase();
      return blob.includes(s);
    });
  }, [items, q]);

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

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  if (!open) return null;

  const run = (it: CommandItem) => {
    onClose();
    it.run();
  };

  return (
    <div
      className="sg-cmd-root"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="sg-cmd-panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="sg-cmd-head">
          <strong>{title}</strong>
          <span className="muted tiny">↑↓ 选择 · Enter 执行 · Esc 关闭</span>
        </div>
        <input
          ref={inputRef}
          className="sg-cmd-input"
          placeholder={placeholder || "搜索指令或快捷键…"}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setHi((i) => Math.min(filtered.length - 1, i + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHi((i) => Math.max(0, i - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              const it = filtered[hi];
              if (it) run(it);
            }
          }}
        />
        <div className="sg-cmd-list">
          {filtered.length === 0 ? (
            <div className="sg-cmd-empty">无匹配指令</div>
          ) : (
            filtered.map((it, i) => (
              <button
                key={it.id}
                type="button"
                className={`sg-cmd-item${i === hi ? " on" : ""}`}
                onMouseEnter={() => setHi(i)}
                onClick={() => run(it)}
              >
                <span className="sg-cmd-label">
                  {it.label}
                  {it.hint ? <span className="sg-cmd-hint">{it.hint}</span> : null}
                </span>
                {it.shortcut ? <kbd className="sg-cmd-kbd">{it.shortcut}</kbd> : null}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
