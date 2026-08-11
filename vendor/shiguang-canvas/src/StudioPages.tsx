/** 轻量工作台页 — 复用现有画布能力，不引入第二套业务引擎 */
import type { AppRoute } from "./AppNav";

type Props = {
  route: Exclude<AppRoute, "home" | "canvas" | "stage3d">;
  onOpenCanvas: () => void;
  onOpenStage3d: () => void;
  onSyncModels: () => void;
  templateCount: number;
  assetCount: number;
  status: string;
};

const COPY: Record<
  Exclude<AppRoute, "home" | "canvas" | "stage3d">,
  { title: string; desc: string; actions: { label: string; go: "canvas" | "stage3d" | "sync" }[] }
> = {
  projects: {
    title: "我的画布",
    desc: "打开导演台画布继续编排分镜；本地模板可在画布侧栏「工程」里加载。",
    actions: [
      { label: "打开画布", go: "canvas" },
      { label: "3D 导演台", go: "stage3d" },
    ],
  },
  image: {
    title: "生图工作台",
    desc: "在画布上添加图片/镜头节点，选择 AIGC 模型后生成；支持 @素材 与变体。",
    actions: [
      { label: "进入画布生图", go: "canvas" },
      { label: "同步模型池", go: "sync" },
    ],
  },
  video: {
    title: "视频创作台",
    desc: "用视频节点 + 首尾帧参考生成；生成后可「入轨」回流剪辑时间线。",
    actions: [
      { label: "进入画布做视频", go: "canvas" },
      { label: "同步模型池", go: "sync" },
    ],
  },
  prompts: {
    title: "提示词库",
    desc: "提示词节点可在画布中复用；落地页「沉淀」区展示近期好结果入口。",
    actions: [{ label: "去画布编辑提示词", go: "canvas" }],
  },
  assets: {
    title: "我的资产",
    desc: "画布节点上的图片/视频即资产来源；可一键全部入轨到剪辑模块。",
    actions: [{ label: "打开画布查看资产", go: "canvas" }],
  },
  settings: {
    title: "配置",
    desc: "模型 Key 在宿主「模型管理 → AIGC」配置；点同步写入画布渠道。Agent 在宿主顶栏「连接 Agent」。",
    actions: [
      { label: "同步模型池", go: "sync" },
      { label: "回到画布", go: "canvas" },
    ],
  },
};

export default function StudioPage({
  route,
  onOpenCanvas,
  onOpenStage3d,
  onSyncModels,
  templateCount,
  assetCount,
  status,
}: Props) {
  const cfg = COPY[route];
  const run = (go: "canvas" | "stage3d" | "sync") => {
    if (go === "canvas") onOpenCanvas();
    else if (go === "stage3d") onOpenStage3d();
    else onSyncModels();
  };

  return (
    <main className="ic-studio">
      <div className="ic-studio-card">
        <h1>{cfg.title}</h1>
        <p>{cfg.desc}</p>
        <div className="ic-studio-stats">
          <span>本地模板 {templateCount}</span>
          <span>画布节点资产 {assetCount}</span>
        </div>
        <p className="ic-studio-status">{status}</p>
        <div className="ic-cta-row">
          {cfg.actions.map((a) => (
            <button
              key={a.label}
              type="button"
              className={a.go === "sync" ? "ic-btn-ghost" : "ic-btn-primary"}
              onClick={() => run(a.go)}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </main>
  );
}
