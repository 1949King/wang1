/** 顶栏导航 — 对齐 infinite-canvas 落地页信息架构 */
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
  version?: string;
};

export default function AppNav({ active, onNavigate, version = "v0.1.0" }: Props) {
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
        <span className="ic-nav-ver" title="拾光导演台">
          {version}
        </span>
      </div>
    </nav>
  );
}
