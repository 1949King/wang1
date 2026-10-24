/**
 * 快捷键参考面板（V4.41.23 引入 · 用户授权解冻 canvas-magnetic-intent）
 *
 * 设计要点（vs AI-Canvas-tauri 24 行原版）：
 *  - 4 分组卡片（编辑 / 节点创建 / 视图与导航 / 系统与资源）
 *  - 拟物键帽（圆角 + 渐变 + 投影 + 组合键真实排布）
 *  - 每行右侧触发预览 SVG（删除→trashcan、撤销→回退箭头、Ctrl+Shift+T→☀↔☾）
 *  - 顶部搜索实时过滤
 *  - 沿用 styles.css [data-theme] 变量，主题切换实时生效
 *
 * 触发方式：AppNav 顶栏 [?] 按钮 / Ctrl+Shift+K
 */
import { useEffect, useMemo, useRef, useState } from "react";
import "./shortcut-settings.css";

type Key = {
  /** 显示文本 */
  label: string;
  /** 单键宽度档位：1=28px 2=48px 3=68px 4=88px */
  w?: 1 | 2 | 3 | 4;
  /** 强调色：mod=主蓝  fn=主蓝 fn=聚焦  del=红 */
  variant?: "mod" | "fn" | "del";
};

type Shortcut = {
  op: string;
  sub?: string;
  /** 顺序连接的键组合（最后一个即操作主键） */
  keys: Key[];
  /** 触发效果 SVG 预览（内联渲染，0 资源消耗） */
  preview: React.ReactNode;
  /** 用于搜索/匹配的别名 */
  search?: string;
};

type Group = {
  id: "edit" | "node" | "view" | "system";
  title: string;
  icon: string;
  desc: string;
  items: Shortcut[];
};

/* ─── 触发预览 SVG（每个操作 56×32） ─── */
const Pv = {
  save: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="4" y="6" width="20" height="20" rx="2" stroke="var(--text-muted)" strokeWidth="1.4" fill="var(--accent-soft)" />
      <path d="M10 14h8M10 18h8M10 22h5" stroke="var(--text-muted)" strokeWidth="1" strokeLinecap="round" />
      <path d="M28 16l4-4 4 4M32 12v8" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="44" cy="16" r="2" fill="#22c55e" />
    </svg>
  ),
  undo: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="6" y="10" width="14" height="14" rx="2" stroke="#f97316" strokeWidth="1.4" fill="rgba(249,115,22,0.18)" />
      <rect x="20" y="6" width="14" height="14" rx="2" stroke="#f97316" strokeWidth="1.4" fill="rgba(249,115,22,0.28)" />
      <path d="M40 10a6 6 0 1 0 0 12" stroke="#f97316" strokeWidth="1.5" fill="none" />
      <path d="M37 11l3 2-1 3" stroke="#f97316" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  copy: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="6" y="6" width="14" height="14" rx="2" stroke="var(--accent)" strokeWidth="1.4" fill="rgba(37,99,235,0.2)" />
      <rect x="14" y="14" width="14" height="14" rx="2" stroke="var(--accent)" strokeWidth="1.4" fill="rgba(37,99,235,0.4)" />
      <path d="M32 8h12v16h-12" stroke="var(--text-muted)" strokeWidth="1.4" strokeDasharray="2 2" fill="none" />
    </svg>
  ),
  paste: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <path d="M32 8h12v16h-12" stroke="var(--text-muted)" strokeWidth="1.4" strokeDasharray="2 2" fill="none" />
      <rect x="38" y="12" width="14" height="14" rx="2" stroke="var(--accent)" strokeWidth="1.4" fill="rgba(37,99,235,0.4)" />
      <path d="M45 17l-3 3 3 3" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  ),
  del: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="8" y="6" width="16" height="20" rx="2" stroke="#f87171" strokeWidth="1.4" fill="rgba(248,113,113,0.18)" />
      <path d="M14 12v6M22 12v6" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="6" y1="6" x2="26" y2="26" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  gen6: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="2" y="10" width="8" height="12" rx="1.5" fill="#6366f1" />
      <rect x="12" y="10" width="8" height="12" rx="1.5" fill="#22c55e" />
      <rect x="22" y="10" width="8" height="12" rx="1.5" fill="#f59e0b" />
      <rect x="32" y="10" width="8" height="12" rx="1.5" fill="#3b82f6" />
      <rect x="42" y="10" width="8" height="12" rx="1.5" fill="#ec4899" />
      <text x="29" y="29" fontSize="8" fill="var(--text-muted)" textAnchor="middle">1—6</text>
    </svg>
  ),
  alt6: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="2" y="10" width="8" height="12" rx="1.5" fill="#22c55e" opacity="0.7" />
      <rect x="12" y="10" width="8" height="12" rx="1.5" fill="#3b82f6" opacity="0.7" />
      <rect x="22" y="10" width="8" height="12" rx="1.5" fill="#f97316" opacity="0.7" />
      <rect x="32" y="10" width="8" height="12" rx="1.5" fill="#a855f7" opacity="0.7" />
      <rect x="42" y="10" width="8" height="12" rx="1.5" fill="#06b6d4" opacity="0.7" />
    </svg>
  ),
  menu: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="6" y="6" width="20" height="20" rx="2" stroke="var(--accent)" strokeWidth="1.4" fill="rgba(37,99,235,0.18)" />
      <rect x="22" y="14" width="28" height="14" rx="3" stroke="var(--accent)" strokeWidth="1.4" fill="rgba(37,99,235,0.32)" />
      <line x1="28" y1="20" x2="44" y2="20" stroke="var(--text-muted)" strokeWidth="1.2" />
      <line x1="28" y1="24" x2="38" y2="24" stroke="var(--text-muted)" strokeWidth="1.2" />
    </svg>
  ),
  group: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="6" y="8" width="18" height="16" rx="2" stroke="#a855f7" strokeWidth="1.4" fill="rgba(168,85,247,0.18)" />
      <rect x="10" y="12" width="6" height="6" rx="1" fill="#a855f7" />
      <rect x="20" y="12" width="6" height="6" rx="1" fill="#a855f7" />
      <rect x="10" y="20" width="6" height="6" rx="1" fill="#a855f7" />
      <rect x="20" y="20" width="6" height="6" rx="1" fill="#a855f7" />
    </svg>
  ),
  fit: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="6" y="6" width="20" height="20" rx="2" stroke="var(--text-muted)" strokeWidth="1" strokeDasharray="3 2" fill="none" />
      <rect x="16" y="12" width="12" height="12" rx="1" fill="rgba(37,99,235,0.4)" stroke="var(--accent)" />
      <path d="M22 12v-3l4 3-4 3v-3z" fill="var(--accent)" />
    </svg>
  ),
  mini: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="4" y="4" width="36" height="24" rx="2" stroke="var(--text-muted)" strokeWidth="1" fill="none" />
      <circle cx="22" cy="16" r="4" fill="rgba(37,99,235,0.5)" />
      <rect x="40" y="20" width="14" height="10" rx="1.5" fill="var(--accent)" opacity="0.85" />
      <rect x="42" y="22" width="6" height="3" fill="#fff" opacity="0.6" />
    </svg>
  ),
  zoom: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="6" y="4" width="20" height="24" rx="2" stroke="var(--text-muted)" strokeWidth="1" fill="none" />
      <rect x="22" y="8" width="14" height="16" rx="1.5" fill="rgba(37,99,235,0.4)" stroke="var(--accent)" />
      <line x1="14" y1="28" x2="38" y2="8" stroke="#f97316" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  ),
  esc: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <rect x="8" y="6" width="40" height="20" rx="3" stroke="var(--text-muted)" strokeWidth="1" fill="rgba(14,20,28,0.4)" />
      <line x1="44" y1="10" x2="36" y2="18" stroke="#f87171" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="44" y1="18" x2="36" y2="10" stroke="#f87171" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  ),
  search: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <circle cx="20" cy="14" r="6" stroke="#f97316" strokeWidth="1.5" fill="none" />
      <line x1="25" y1="19" x2="30" y2="24" stroke="#f97316" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="32" y="8" width="20" height="14" rx="2" fill="rgba(249,115,22,0.15)" stroke="#f97316" />
    </svg>
  ),
  pet: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <circle cx="28" cy="18" r="8" fill="rgba(249,115,22,0.3)" stroke="#f97316" strokeWidth="1.4" />
      <circle cx="25" cy="16" r="1.2" fill="#fff" />
      <circle cx="31" cy="16" r="1.2" fill="#fff" />
      <path d="M25 21q3 2 6 0" stroke="#f97316" strokeWidth="1.2" strokeLinecap="round" fill="none" />
    </svg>
  ),
  theme: (
    <svg width="56" height="32" viewBox="0 0 56 32" fill="none" aria-hidden>
      <circle cx="22" cy="16" r="6" fill="#f97316" />
      <path d="M28 16a6 6 0 0 1-6 6" fill="var(--brand-deep)" stroke="#f97316" />
    </svg>
  ),
};

/* ─── 拟物键帽（Kbd 子组件） ─── */
function Kbd({ k }: { k: Key }) {
  const cls = [
    "sc-kbd-key",
    k.variant ? `is-${k.variant}` : "",
    k.w === 2 ? "w-2" : k.w === 3 ? "w-3" : k.w === 4 ? "w-4" : "",
  ].filter(Boolean).join(" ");
  return <span className={cls}>{k.label}</span>;
}

/* ─── 触发预览包装（保证固定 60×36） ─── */
function PvBox({ children }: { children: React.ReactNode }) {
  return <div className="sc-kbd-pv" aria-hidden>{children}</div>;
}

/* ─── 4 分组定义（用户截图反馈"可视化不足"的关键修复） ─── */
const IS_MAC = typeof navigator !== "undefined" && /Macintosh|Mac OS X/.test(navigator.userAgent);
const MOD_LABEL = IS_MAC ? "⌘" : "Ctrl";
const CTRL_LABEL = IS_MAC ? "⌃" : "Ctrl";
const ALT_LABEL = IS_MAC ? "⌥" : "Alt";
const SHIFT_LABEL = IS_MAC ? "⇧" : "Shift";

function buildGroups(): Group[] {
  return [
    {
      id: "edit",
      title: "编辑",
      icon: "✎",
      desc: "操作画布内容 · 剪贴板 · 历史",
      items: [
        {
          op: "保存画布",
          sub: "立即写 localStorage · 状态栏显示时间戳",
          keys: [{ label: MOD_LABEL, w: 3, variant: "mod" }, { label: "S" }],
          preview: Pv.save, search: "save",
        },
        {
          op: "撤销",
          sub: "回退上一步画布操作",
          keys: [{ label: MOD_LABEL, w: 3, variant: "mod" }, { label: "Z" }],
          preview: Pv.undo, search: "undo",
        },
        {
          op: "重做",
          sub: "Ctrl+Y 或 Ctrl+Shift+Z 双路径兼容",
          keys: [
            { label: MOD_LABEL, w: 3, variant: "mod" }, { label: "Y" },
          ],
          preview: Pv.undo, search: "redo",
        },
        {
          op: "复制节点",
          sub: "复制选中节点到剪贴板 · 不写系统剪贴板",
          keys: [{ label: MOD_LABEL, w: 3, variant: "mod" }, { label: "C" }],
          preview: Pv.copy, search: "copy",
        },
        {
          op: "粘贴节点",
          sub: "从剪贴板贴在指针位置 · 自动滚屏到可见",
          keys: [{ label: MOD_LABEL, w: 3, variant: "mod" }, { label: "V" }],
          preview: Pv.paste, search: "paste",
        },
        {
          op: "删除节点",
          sub: "含连线一并清理 · Backspace 同效",
          keys: [{ label: "Delete", w: 4, variant: "del" }],
          preview: Pv.del, search: "delete remove trash",
        },
      ],
    },
    {
      id: "node",
      title: "节点创建",
      icon: "▣",
      desc: "在指针位置快速生成节点 · 仅小白模式生效",
      items: [
        {
          op: "创建生成节点 · 剧本/镜头/提示词/设定/生成器/文本",
          sub: "数字 1-6 → 6 种内置生成节点",
          keys: [{ label: "1" }, { label: "—" }, { label: "6" }],
          preview: Pv.gen6, search: "1 2 3 4 5 6 number digit",
        },
        {
          op: "创建源节点 · 图片/视频/音频/音乐/分镜/导演卡",
          sub: "按住 Alt 再按数字 · 从素材而非生成得到",
          keys: [{ label: ALT_LABEL, w: 2, variant: "fn" }, { label: "1" }, { label: "—" }, { label: "6" }],
          preview: Pv.alt6, search: "alt",
        },
        {
          op: "弹出节点菜单",
          sub: "在选中节点时按 Space",
          keys: [{ label: "Space", w: 3 }],
          preview: Pv.menu, search: "space menu",
        },
        {
          op: "分组 / 取消分组",
          sub: "Ctrl+G 把选中节点包成组 · 再次触发取消分组",
          keys: [{ label: MOD_LABEL, w: 3, variant: "mod" }, { label: "G" }],
          preview: Pv.group, search: "group ungroup",
        },
      ],
    },
    {
      id: "view",
      title: "视图与导航",
      icon: "◉",
      desc: "画布缩放/导航/缩略图",
      items: [
        {
          op: "画布复位",
          sub: "fitView · 把所有节点塞进可视区 · 220ms 缓动",
          keys: [{ label: "F", variant: "fn" }],
          preview: Pv.fit, search: "fit view zoom",
        },
        {
          op: "小地图切换",
          sub: "显示 / 隐藏右下角缩略图",
          keys: [{ label: "M", variant: "fn" }],
          preview: Pv.mini, search: "minimap minimap",
        },
        {
          op: "锁定比例缩放",
          sub: "滚轮缩放时按住 Shift · 防止宽高比变形",
          keys: [{ label: SHIFT_LABEL, w: 2, variant: "fn" }, { label: "滚轮" }],
          preview: Pv.zoom, search: "shift scroll wheel lock",
        },
      ],
    },
    {
      id: "system",
      title: "系统与资源",
      icon: "⚙",
      desc: "面板/弹窗/资源检索/吉祥物",
      items: [
        {
          op: "关闭菜单 / 设置",
          sub: "Esc · 弹窗/菜单/指令面板通用关闭",
          keys: [{ label: "Esc", w: 3 }],
          preview: Pv.esc, search: "escape close",
        },
        {
          op: "资源搜索窗口",
          sub: "Alt+Space 或 Ctrl+Shift+Space",
          keys: [
            { label: ALT_LABEL, w: 2, variant: "fn" }, { label: "Space", w: 3 },
          ],
          preview: Pv.search, search: "search resource asset",
        },
        {
          op: "显示/隐藏吉祥物",
          sub: "右下角 Agent 宠物",
          keys: [
            { label: MOD_LABEL, w: 3, variant: "mod" },
            { label: SHIFT_LABEL, w: 2, variant: "fn" },
            { label: "M", variant: "fn" },
          ],
          preview: Pv.pet, search: "pet mascot",
        },
        {
          op: "切换主题",
          sub: "Ctrl+Shift+T · 暗色 ↔ 浅色 · 持久化",
          keys: [
            { label: MOD_LABEL, w: 3, variant: "mod" },
            { label: SHIFT_LABEL, w: 2, variant: "fn" },
            { label: "T", variant: "fn" },
          ],
          preview: Pv.theme, search: "theme dark light toggle",
        },
      ],
    },
  ];
}

/* ─── 模态容器（自包含，不依赖第三方） ─── */
type ModalProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  ariaLabel?: string;
};

function ModalImpl({ open, onClose, title, children, ariaLabel }: ModalProps) {
  // Esc 关闭（与系统快捷键同源，避免双写）
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
  return (
    <div
      className="sc-modal-root"
      role="presentation"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="sc-modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel ?? title}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="sc-modal-head">
          <strong>{title}</strong>
          <button
            type="button"
            className="sc-modal-close"
            aria-label="关闭快捷键参考"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ─── 主组件 ─── */
type Props = {
  open: boolean;
  onClose: () => void;
};

export default function ShortcutSettings({ open, onClose }: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const groups = useMemo(() => buildGroups(), []);

  // 打开时聚焦搜索框
  useEffect(() => {
    if (!open) return;
    setQuery("");
    const t = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(t);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        items: g.items.filter((it) => {
          const blob = `${it.op} ${it.sub ?? ""} ${it.search ?? ""} ${it.keys.map((k) => k.label).join(" ")}`.toLowerCase();
          return blob.includes(q);
        }),
      }))
      .filter((g) => g.items.length > 0);
  }, [groups, query]);

  const totalShown = filtered.reduce((sum, g) => sum + g.items.length, 0);
  const totalAll = groups.reduce((sum, g) => sum + g.items.length, 0);

  return (
    <ModalImpl open={open} onClose={onClose} title="快捷键参考" ariaLabel="快捷键参考">
      <div className="sc-modal-search">
        <span className="sc-modal-search-ico" aria-hidden>🔍</span>
        <input
          ref={inputRef}
          className="sc-modal-search-input"
          placeholder="搜索快捷键（如「撤销」「Ctrl+Z」「创建」）"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="sc-modal-search-stat">
          <strong>{totalShown}</strong> / {totalAll}
        </span>
      </div>

      <div className="sc-modal-body">
        {filtered.length === 0 ? (
          <div className="sc-modal-empty">无匹配快捷键</div>
        ) : (
          filtered.map((g) => (
            <section className="sc-group" key={g.id}>
              <header className="sc-group-head">
                <span className="sc-group-ico" aria-hidden>{g.icon}</span>
                <h2>{g.title}</h2>
                <span className="sc-group-desc">{g.desc}</span>
                <span className="sc-group-count">{g.items.length} 个</span>
              </header>
              {g.items.map((it, i) => (
                <div className="sc-row" key={`${g.id}-${i}`}>
                  <div className="sc-row-op">
                    <div className="sc-row-name">{it.op}</div>
                    {it.sub && <div className="sc-row-sub">{it.sub}</div>}
                  </div>
                  <PvBox>{it.preview}</PvBox>
                  <div className="sc-row-keys">
                    {it.keys.map((k, ki) => {
                      // "—" 是范围连接符，单独渲染（不作为键帽）
                      const isRange = k.label === "—" || k.label === "—";
                      return (
                        <span key={ki} className="sc-row-key-group">
                          {ki > 0 && !isRange && <span className="sc-row-plus">+</span>}
                          {isRange ? (
                            <span className="sc-row-range">{k.label}</span>
                          ) : (
                            <Kbd k={k} />
                          )}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </section>
          ))
        )}
      </div>
    </ModalImpl>
  );
}