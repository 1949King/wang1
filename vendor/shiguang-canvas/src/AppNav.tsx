/** 顶栏导航 — 对齐 infinite-canvas 落地页信息架构 */
import type { CanvasTier } from "./store";

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
};

export default function AppNav({
  active,
  onNavigate,
  version,
  versionTitle = "拾光导演台",
  tier,
  onTierChange,
}: Props) {
  return (
    <nav className="ic-nav" aria-label="主导航">
      <button type="button" className="ic-nav-brand" onClick={() => onNavigate("home")}>
        <span className="ic-nav-mark" aria-hidden>
          ↗
        </span>
        无限画布
      </button>
      <div className="ic-nav-links">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`ic-nav-link${active === item.id ? " on" : ""}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="ic-nav-ico" aria-hidden>
              {item.icon}
            </span>
            {item.label}
          </button>
        ))}
      </div>
      <div className="ic-nav-right">
        <div
          className="ic-tier-seg"
          role="group"
          aria-label="画布模式"
          title="小白模式 = 磁吸意图画布；专业模式 = 节点画布（同一份数据，随时互切）"
        >
          {(["novice", "pro"] as CanvasTier[]).map((t) => (
            <button
              key={t}
              type="button"
              className={tier === t ? "on" : ""}
              onClick={() => onTierChange(t)}
            >
              {t === "novice" ? "小白模式" : "专业模式"}
            </button>
          ))}
        </div>
        <span className="ic-nav-ver" title={versionTitle}>
          {version}
        </span>
      </div>
    </nav>
  );
}
