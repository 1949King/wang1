/**
 * ModelSelector — 分组模型选择器（tenney95 风格融合）
 *
 * 替代原生 `<select>`，按 Provider 分组折叠显示，带配置状态指示器。
 * 支持搜索过滤、键盘导航、点击外部关闭。
 */
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

export interface ModelOption {
  channel_id: string;
  channel_name: string;
  model: string;
  label: string;
}

interface Props {
  models: ModelOption[];
  value: string;
  onChange: (key: string) => void;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  /** localStorage 持久化 key（可选） */
  persistKey?: string;
}

/** 按 channel_name 分组 */
function groupByProvider(models: ModelOption[]): Map<string, ModelOption[]> {
  const map = new Map<string, ModelOption[]>();
  for (const m of models) {
    const key = m.channel_name || m.channel_id || "其他";
    const list = map.get(key);
    if (list) list.push(m);
    else map.set(key, [m]);
  }
  return map;
}

function ModelSelector({
  models,
  value,
  onChange,
  label,
  placeholder = "选择模型",
  disabled = false,
  persistKey,
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  // 持久化：从 localStorage 读取上次选择
  useEffect(() => {
    if (persistKey && !value) {
      try {
        const saved = localStorage.getItem(persistKey);
        if (saved && models.some((m) => `${m.channel_id}::${m.model}` === saved)) {
          onChange(saved);
        }
      } catch {
        /* ignore */
      }
    }
  }, []); // 仅挂载时执行

  // 持久化：选择后写入 localStorage
  const handleChange = useCallback(
    (key: string) => {
      onChange(key);
      if (persistKey) {
        try {
          localStorage.setItem(persistKey, key);
        } catch {
          /* ignore */
        }
      }
      setOpen(false);
      setSearch("");
    },
    [onChange, persistKey],
  );

  // 点击外部关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    window.addEventListener("mousedown", handler, true);
    return () => window.removeEventListener("mousedown", handler, true);
  }, [open]);

  // 打开时自动聚焦搜索框
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // 键盘导航
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setSearch("");
      }
    },
    [],
  );

  // 分组
  const groups = useMemo(() => groupByProvider(models), [models]);

  // 搜索过滤
  const filtered = useMemo(() => {
    if (!search.trim()) return groups;
    const q = search.toLowerCase();
    const result = new Map<string, ModelOption[]>();
    for (const [provider, list] of groups) {
      const matched = list.filter(
        (m) =>
          m.label.toLowerCase().includes(q) ||
          m.model.toLowerCase().includes(q) ||
          provider.toLowerCase().includes(q),
      );
      if (matched.length > 0) result.set(provider, matched);
    }
    return result;
  }, [groups, search]);

  // 当前选中项
  const selectedLabel = useMemo(() => {
    const m = models.find((m) => `${m.channel_id}::${m.model}` === value);
    return m?.label || placeholder;
  }, [models, value, placeholder]);

  // 选中项颜色
  const selectedColor = value && models.some((m) => `${m.channel_id}::${m.model}` === value)
    ? "#e8eef6"
    : "#6b7a8f";

  return (
    <div className="model-selector" ref={rootRef} onKeyDown={handleKeyDown}>
      {/* 标签 */}
      {label && <div className="model-selector-label">{label}</div>}

      {/* 触发按钮 */}
      <button
        type="button"
        className="model-selector-trigger"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="model-selector-trigger-text" style={{ color: selectedColor }}>
          {selectedLabel}
        </span>
        <span className={`model-selector-arrow${open ? " open" : ""}`}>▼</span>
      </button>

      {/* 下拉面板 */}
      {open && (
        <div className="model-selector-dropdown" ref={listRef}>
          {/* 搜索框 */}
          <div className="model-selector-search">
            <input
              ref={inputRef}
              type="text"
              className="model-selector-search-input"
              placeholder="搜索模型…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {/* 分组列表 */}
          <div className="model-selector-list">
            {filtered.size === 0 ? (
              <div className="model-selector-empty">无匹配模型</div>
            ) : (
              Array.from(filtered.entries()).map(([provider, list]) => (
                <div key={provider} className="model-selector-group">
                  <div className="model-selector-group-header">
                    <span className="model-selector-group-name">{provider}</span>
                    <span className="model-selector-group-status" title="已配置">
                      ✓
                    </span>
                  </div>
                  {list.map((m) => {
                    const key = `${m.channel_id}::${m.model}`;
                    const isSelected = key === value;
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`model-selector-item${isSelected ? " selected" : ""}`}
                        onClick={() => handleChange(key)}
                      >
                        <span className="model-selector-item-name">{m.label}</span>
                        {isSelected && <span className="model-selector-item-check">✓</span>}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(ModelSelector);