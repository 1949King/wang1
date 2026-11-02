/** 顶栏导航 — 对齐 infinite-canvas 落地页信息架构 */
import { TeamTopBarButton } from "./teamTopBar";
import type { CanvasTheme, CanvasTier } from "./store";

export type AppRoute =
  | "home"
  | "projects"
  | "canvas"
  | "stage3d"
  | "image"
  | "video"
  | "prompts"
  | "assets"
  | "settings";

/** 不含 home：左侧品牌「无限画布」已进落地页，避免双入口同名 */
export const NAV_ITEMS: { id: AppRoute; label: string; icon: string }[] = [
  { id: "projects", label: "我的画布", icon: "▦" },
  { id: "image", label: "生图工作台", icon: "▣" },
  { id: "video", label: "视频创作台", icon: "▶" },
  { id: "prompts", label: "提示词库", icon: "☰" },
  { id: "assets", label: "我的资产", icon: "▢" },
  { id: "settings", label: "配置", icon: "⚙" },
];

type Props = {
  active: AppRoute;
  onNavigate: (id: AppRoute) => void;
  /**
   * 画布版本显示串（如 "v0.2.0"）。
   *
   * ⚠️ 2026-09-19：默认值已移除。历史默认值 `"v0.1.0"` 让「忘记传参」也能正常渲染，
   * 结果画布版本号从项目建立起一直停在 v0.1.0、历经十余轮改动无人维护。
   * 现在必须由调用方从 `canvasVersion.ts` 显式传入，漏传会在界面上直接暴露。
   */
  version: string;
  /** 版本号 tooltip 文案（非必填，缺省回退到通用说明） */
  versionTitle?: string;
  /** 当前画布档位：小白模式 / 专业模式 */
  tier: CanvasTier;
  onTierChange: (t: CanvasTier) => void;
  /** 当前主题（V4.41.22 引入）：暗色 / 浅色 */
  theme: CanvasTheme;
  /** 切换主题回调（Ctrl+Shift+T 也走它） */
  onThemeChange: (t: CanvasTheme) => void;
  /** V4.41.23 引入：打开快捷键参考面板 */
  onOpenShortcuts?: () => void;
};

export default function AppNav({
  active,
  onNavigate,
  version,
  versionTitle = "拾光导演台",
  tier,
  onTierChange,
  theme,
  onThemeChange,
  onOpenShortcuts,
}: Props) {
  // 形态切换（小白 / 专业）**刻意不在导航里** —— 2026-10-19 用户纠正：
  // 它属于「视图级」操作，和「画布 / 3D 导演台」并排放在画布顶栏
  // （CanvasShell 的第二个 `.seg`）。props 仍保留以维持调用方签名。
  void tier;
  void onTierChange;

  return (
    <nav className="ic-nav" aria-label="主导航">
      {/* 2026-10-19（用户授权解冻 canvas-magnetic-intent）：顶栏 → 左侧竖排栏。
          品牌只留图标（文字进 title），给竖排腾宽度；点击回落地页。 */}
      <button
        type="button"
        className="ic-nav-brand"
        onClick={() => onNavigate("home")}
        title="无限画布 · 首页"
        aria-label="无限画布 · 首页"
      >
        <span className="ic-nav-mark" aria-hidden>
          ↗
        </span>
      </button>
      <div className="ic-nav-links">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`ic-nav-link${active === item.id ? " on" : ""}`}
            onClick={() => onNavigate(item.id)}
            title={item.label}
          >
            <span className="ic-nav-ico" aria-hidden>
              {item.icon}
            </span>
            <span className="ic-nav-label">{item.label}</span>
          </button>
        ))}
      </div>
      <div className="ic-nav-right">
        {/* 2026-11-02（用户授权解冻 canvas-magnetic-intent）：团队协作入口。
            团队是「工作区级」能力，必须任何视图都够得着 —— 原先只挂在画布视图
            第二条顶栏（`CanvasShell.tsx:929 showWorkspace = viewMode === "canvas"`），
            而开机默认落在首页（`App.tsx:141-149`）⇒ 用户按默认路径打开完全看不到。
            这里用 28px 图标按钮复用 `.ic-shortcut-btn` 的尺寸与主题变体；
            面板本体 `TeamPanel` 仍是同一个，不做第二套。 */}
        <TeamTopBarButton />
        {/* V4.41.23 快捷键参考（用户授权解冻 canvas-magnetic-intent）：图标 + Ctrl+Shift+K */}
        {onOpenShortcuts && (
          <button
            type="button"
            className="ic-shortcut-btn"
            aria-label="打开快捷键参考"
            title="快捷键参考（Ctrl+Shift+K）"
            onClick={onOpenShortcuts}
          >
            <span aria-hidden>?</span>
          </button>
        )}
        {/* V4.41.22 主题切换（用户授权解冻 canvas-magnetic-intent）：暗色默认 / 浅色 */}
        <button
          type="button"
          className="ic-theme-btn"
          aria-label={theme === "dark" ? "切换到浅色主题" : "切换到暗色主题"}
          title={theme === "dark" ? "当前：暗色（Ctrl+Shift+T 切换）" : "当前：浅色（Ctrl+Shift+T 切换）"}
          onClick={() => onThemeChange(theme === "dark" ? "light" : "dark")}
        >
          <span aria-hidden>{theme === "dark" ? "☀" : "☾"}</span>
        </button>
        {/* 形态切换（小白 / 专业）不在导航里 —— 唯一入口是画布顶栏
            「画布 | 3D 导演台」并排的 CanvasTierSeg（CanvasShell.tsx）。
            这里刻意不渲染任何形态切换控件，避免出现两个入口。 */}
        <span className="ic-nav-ver" title={versionTitle}>
          {version}
        </span>
      </div>
    </nav>
  );
}
