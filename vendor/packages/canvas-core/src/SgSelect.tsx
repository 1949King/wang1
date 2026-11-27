/**
 * SgSelect — 轻量通用下拉（替代原生 <select>）。
 *
 * 为什么替代原生 <select>（2026-11-21 真机实测 v4.47.0）：
 * QtWebEngine 的原生 select 弹层由 Qt 侧 delegate 窗口绘制，不跟随页面暗色
 * 主题、弹层容器尺寸计算异常 ⇒ 下拉出现大块白色空白（拉片视觉模型下拉、
 * Agent-IM 模式下拉两处用户截图）。项目既有约定：弹层改前端渲染
 * （先例：右键菜单 React 化、ModelSelector 替代原生 select）。
 *
 * 样式复用 .model-selector-* 族：styles.css 体积守卫基线 3980+30 容差，
 * 实测已 4004 行（余量 6 行）⇒ 不新增 CSS 族，零 CSS 改动。
 */
import { memo, useEffect, useRef, useState } from "react";

export interface SgSelectOption {
  value: string;
  label: string;
}

interface Props {
  options: SgSelectOption[];
  value: string;
  onChange: (value: string) => void;
  /** 触发按钮 id（供 label htmlFor 关联） */
  id?: string;
  title?: string;
  /** 根节点宽度（默认 100%；紧凑场景传数值如 88） */
  width?: number | string;
}

function SgSelect({ options, value, onChange, id, title, width }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // 点击外部关闭（与 ModelSelector 同纪律）
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", handler, true);
    return () => window.removeEventListener("mousedown", handler, true);
  }, [open]);

  const selected = options.find((o) => o.value === value);

  return (
    <div
      className="model-selector"
      ref={rootRef}
      style={width !== undefined ? { width } : undefined}
      onKeyDown={(e: React.KeyboardEvent) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <button
        type="button"
        id={id}
        className="model-selector-trigger"
        title={title}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="model-selector-trigger-text">{selected?.label ?? ""}</span>
        <span className={`model-selector-arrow${open ? " open" : ""}`}>▼</span>
      </button>
      {open && (
        <div className="model-selector-dropdown">
          <div className="model-selector-list">
            {options.map((o) => (
              <button
                key={o.value}
                type="button"
                className={`model-selector-item${o.value === value ? " selected" : ""}`}
                onClick={() => {
                  setOpen(false);
                  // 与原生 select 一致：仅值变化才触发 onChange
                  if (o.value !== value) onChange(o.value);
                }}
              >
                <span className="model-selector-item-name">{o.label}</span>
                {o.value === value && <span className="model-selector-item-check">✓</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(SgSelect);