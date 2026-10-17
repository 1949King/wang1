/** 轻量工作台页 — 提示词 / 资产 / 工程 / 配置；生图/视频由独立 Studio 组件承接 */
import { useEffect, useMemo, useState } from "react";
import type { AppRoute } from "./AppNav";
import {
  getAgentStatus,
  listImageModels,
  listVideoModels,
  listLocalVisionModels,
  startCanvasAgent,
} from "./bridge";
import { getVisionModel, setVisionModel } from "./visionModel";
import {
  ASSET_SEMANTIC_LABEL,
  ASSET_TYPE_LABEL,
  buildAssetTree,
  deleteAsset,
  deletePrompt,
  listAssets,
  listPrompts,
  upsertPrompt,
  type AssetSemantic,
  type AssetTypeKind,
  type LocalAsset,
  type LocalPrompt,
} from "./localLibrary";
import PromptLibraryPanel from "./PromptLibraryPanel";
import AestheticPresetPanel from "./AestheticPresetPanel";
import type { PromptItem } from "./promptLibrary";
import { useCanvasStore } from "./store";
import { readProjectsIndex } from "./stores/project-storage";
import "./assets-folder.css";

type Props = {
  route: Exclude<AppRoute, "home" | "canvas" | "stage3d" | "image" | "video">;
  onOpenCanvas: () => void;
  onOpenStage3d: () => void;
  onSyncModels: () => void;
  templateCount: number;
  assetCount: number;
  status: string;
  onInsertPrompt: (p: LocalPrompt) => void;
  onInsertAsset: (a: LocalAsset) => void;
};

export default function StudioPage({
  route,
  onOpenCanvas,
  onOpenStage3d,
  onSyncModels,
  templateCount,
  assetCount,
  status,
  onInsertPrompt,
  onInsertAsset,
}: Props) {
  const [tick, setTick] = useState(0);
  const refresh = () => setTick((t) => t + 1);
  const prompts = useMemo(() => listPrompts(), [tick]);
  const assets = useMemo(() => listAssets(), [tick]);
  /** 画布档位与当前档位下的工程数（两个档位各自独立工程文件） */
  const editorTier = useCanvasStore((s) => s.editorTier);
  const setEditorTier = useCanvasStore((s) => s.setEditorTier);
  const tierProjectCount = useMemo(
    () => readProjectsIndex().filter((m) => (m.tier || "pro") === editorTier).length,
    [editorTier, tick],
  );
  const [q, setQ] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftText, setDraftText] = useState("");
  const [promptTab, setPromptTab] = useState<"community" | "mine" | "aesthetic">("community");
  const [promptStatus, setPromptStatus] = useState("");
  /** 资产分类导航：null = 顶层类型文件夹；{kind, semantic:null} = 语义层；{kind, semantic} = 资产列表 */
  const [assetNav, setAssetNav] = useState<{
    kind: AssetTypeKind;
    semantic: AssetSemantic | null;
  } | null>(null);

  const [modelInfo, setModelInfo] = useState({
    image: 0,
    video: 0,
    active: "",
    warnings: [] as string[],
  });
  const [agentInfo, setAgentInfo] = useState({ listening: false, url: "", message: "" });
  const [agentBusy, setAgentBusy] = useState(false);
  const [localStatus, setLocalStatus] = useState("");
  /** 拉片 · 本机视觉模型（I1）：可选列表 + 当前选择（空 = 自动） */
  const [visionModels, setVisionModels] = useState<{ name: string; size?: string }[]>([]);
  const [visionModel, setVisionModelState] = useState(getVisionModel());

  const refreshHostStatus = async () => {
    const [img, vid, ag, vis] = await Promise.all([
      listImageModels(),
      listVideoModels(),
      getAgentStatus(),
      listLocalVisionModels(),
    ]);
    setModelInfo({
      image: img.models.length,
      video: vid.models.length,
      active: img.active_provider_label || "",
      warnings: [...(img.warnings || []), ...(vid.warnings || [])],
    });
    setAgentInfo({
      listening: Boolean(ag.listening && ag.token),
      url: ag.url || "",
      message: ag.message || "",
    });
    setVisionModels(vis);
    setVisionModelState(getVisionModel());
  };

  useEffect(() => {
    if (route === "settings") refreshHostStatus();
  }, [route, tick]);

  if (route === "prompts") {
    const filtered = prompts.filter(
      (p) =>
        !q.trim() ||
        p.title.includes(q) ||
        p.text.includes(q) ||
        p.tags.some((t) => t.includes(q)),
    );
    const applyCommunity = (item: PromptItem) => {
      onInsertPrompt({
        id: `community_${item.sourceId}_${item.id}`,
        title: item.title,
        text: item.prompt,
        tags: [...item.tags, item.category],
        updatedAt: new Date().toISOString(),
      });
      setPromptStatus(`已插入画布：${item.title}`);
    };
    return (
      <main className="studio-page library prompt-studio">
        <aside className="studio-side">
          <h1>提示词库</h1>
          <p className="muted">社区 GitHub 源 + 离线精选 + 本地自建。可收藏、细分类、插入画布节点。</p>
          <div className="prompt-studio-tabs">
            <button
              type="button"
              className={`btn${promptTab === "community" ? " primary" : ""}`}
              onClick={() => setPromptTab("community")}
            >
              社区 / 精选
            </button>
            <button
              type="button"
              className={`btn${promptTab === "mine" ? " primary" : ""}`}
              onClick={() => setPromptTab("mine")}
            >
              我的本地（{prompts.length}）
            </button>
            <button
              type="button"
              className={`btn${promptTab === "aesthetic" ? " primary" : ""}`}
              onClick={() => setPromptTab("aesthetic")}
            >
              美学预设
            </button>
          </div>
          {promptTab === "mine" ? (
            <>
              <div className="field">
                <label>搜索本地</label>
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="标题 / 正文 / 标签" />
              </div>
              <div className="field">
                <label>新建标题</label>
                <input value={draftTitle} onChange={(e) => setDraftTitle(e.target.value)} />
              </div>
              <div className="field">
                <label>正文</label>
                <textarea rows={5} value={draftText} onChange={(e) => setDraftText(e.target.value)} />
              </div>
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  if (!draftText.trim()) return;
                  upsertPrompt({ title: draftTitle || "未命名", text: draftText });
                  setDraftTitle("");
                  setDraftText("");
                  refresh();
                }}
              >
                保存提示词
              </button>
            </>
          ) : promptTab === "aesthetic" ? (
            <p className="muted">
              右侧沉淀「风格词 + 镜头语言 + 色调·LUT + 节奏·音乐」四维度预设，一键套到全部/选中分镜，也可导出 JSON 复用。
            </p>
          ) : (
            <p className="muted">右侧浏览社区库。点「同步源」可拉取数千条；离线精选包无需联网。</p>
          )}
          <button type="button" className="btn" onClick={onOpenCanvas}>
            打开画布
          </button>
          {promptStatus ? <p className="muted">{promptStatus}</p> : null}
        </aside>
        <section className="studio-results">
          {promptTab === "aesthetic" ? (
            <AestheticPresetPanel onStatus={(msg) => setPromptStatus(msg)} />
          ) : promptTab === "community" ? (
            <PromptLibraryPanel
              variant="page"
              onApply={applyCommunity}
              onStatus={(msg) => setPromptStatus(msg)}
            />
          ) : filtered.length === 0 ? (
            <div className="studio-empty">还没有本地提示词。可在左侧新建，或从社区库点「存本地」。</div>
          ) : (
            <div className="lib-list">
              {filtered.map((p) => (
                <article key={p.id} className="lib-card">
                  <h3>{p.title}</h3>
                  <p>{p.text}</p>
                  <div className="studio-card-actions">
                    <button type="button" className="btn primary" onClick={() => onInsertPrompt(p)}>
                      插入画布
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => {
                        deletePrompt(p.id);
                        refresh();
                      }}
                    >
                      删除
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    );
  }

  if (route === "assets") {
    const tree = buildAssetTree(assets);
    const searching = q.trim().length > 0;
    const searchList = searching
      ? assets.filter((a) => a.title.includes(q.trim()) || (a.prompt || "").includes(q.trim()))
      : [];
    const currentFolder = assetNav
      ? tree.folders.find(
          (f) => f.kind === assetNav.kind && (assetNav.kind === "text" || f.semantic === assetNav.semantic),
        )
      : undefined;

    const renderFolder = (id: string, label: string, count: number, open: () => void) => (
      <button key={id} type="button" className="asset-folder-card" onClick={open}>
        <span className="asset-folder-ico">📁</span>
        <span className="asset-folder-name">{label}</span>
        <span className="asset-folder-count">{count} 项</span>
      </button>
    );
    const renderAssetCard = (a: LocalAsset) => (
      <article key={a.id} className="studio-card">
        {a.kind === "video" ? (
          <video src={a.url} controls playsInline />
        ) : a.kind === "image" ? (
          <img src={a.url} alt="" />
        ) : (
          <div className="studio-empty">{a.prompt || a.title}</div>
        )}
        <div className="studio-card-meta">{a.title}</div>
        <div className="studio-card-actions">
          <button type="button" className="btn primary" onClick={() => onInsertAsset(a)}>
            进画布
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              deleteAsset(a.id);
              refresh();
            }}
          >
            删除
          </button>
        </div>
      </article>
    );

    return (
      <main className="studio-page library">
        <aside className="studio-side">
          <h1>我的资产</h1>
          <p className="muted">自动按「类型 + 语义」分类收纳</p>
          <div className="field">
            <label>搜索</label>
            <input value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <p className="muted">共 {assets.length} 条 · 画布节点资产约 {assetCount}</p>
          {assetNav && !searching && (
            <button type="button" className="btn" onClick={() => setAssetNav(null)}>
              ← 返回分类
            </button>
          )}
          <button type="button" className="btn" onClick={onOpenCanvas}>
            打开画布
          </button>
        </aside>
        <section className="studio-results">
          {searching ? (
            searchList.length === 0 ? (
              <div className="studio-empty">没有匹配的资产</div>
            ) : (
              <div className="studio-grid">{searchList.map(renderAssetCard)}</div>
            )
          ) : !assetNav ? (
            tree.types.length === 0 ? (
              <div className="studio-empty">暂无本地资产</div>
            ) : (
              <>
                <div className="asset-breadcrumb">全部分类</div>
                <div className="asset-folder-grid">
                  {tree.types.map((t) =>
                    renderFolder(t.kind, t.label, t.count, () => setAssetNav({ kind: t.kind, semantic: null })),
                  )}
                </div>
              </>
            )
          ) : assetNav.semantic === null && assetNav.kind !== "text" ? (
            <>
              <div className="asset-breadcrumb">全部 / {ASSET_TYPE_LABEL[assetNav.kind]}</div>
              <div className="asset-folder-grid">
                {tree.foldersOfType(assetNav.kind).map((f) =>
                  renderFolder(f.id, f.label, f.count, () =>
                    setAssetNav({ kind: assetNav.kind, semantic: f.semantic }),
                  ),
                )}
              </div>
            </>
          ) : currentFolder && currentFolder.items.length > 0 ? (
            <>
              <div className="asset-breadcrumb">
                全部 / {ASSET_TYPE_LABEL[assetNav.kind]}
                {assetNav.semantic ? ` / ${ASSET_SEMANTIC_LABEL[assetNav.semantic]}` : ""}
              </div>
              <div className="studio-grid">{currentFolder.items.map(renderAssetCard)}</div>
            </>
          ) : (
            <div className="studio-empty">暂无资产</div>
          )}
        </section>
      </main>
    );
  }

  if (route === "projects") {
    return (
      <main className="ic-studio">
        <div className="ic-studio-card">
          <h1>我的画布</h1>
          <p>
            打开导演台画布继续编排分镜；本地模板可在画布侧栏「工程」里加载。
            <br />
            小白模式用磁吸卡片（靠近即建立关系），专业模式用节点连线，两种模式共用同一套数据模型，
            但各自保存为独立工程文件，互不干扰。
          </p>
          <div className="ic-tier-seg" style={{ margin: "0 auto 12px" }}>
            <button
              type="button"
              className={editorTier === "novice" ? "on" : ""}
              onClick={() => setEditorTier("novice")}
            >
              小白模式
            </button>
            <button
              type="button"
              className={editorTier === "pro" ? "on" : ""}
              onClick={() => setEditorTier("pro")}
            >
              专业模式
            </button>
          </div>
          <div className="ic-studio-stats">
            <span>当前档位 {editorTier === "novice" ? "小白模式" : "专业模式"}</span>
            <span>该档位工程 {tierProjectCount}</span>
            <span>本地模板 {templateCount}</span>
            <span>画布节点资产 {assetCount}</span>
          </div>
          <p className="ic-studio-status">{status}</p>
          <div className="ic-cta-row">
            <button type="button" className="ic-btn-primary" onClick={onOpenCanvas}>
              打开画布
            </button>
            <button type="button" className="ic-btn-ghost" onClick={onOpenStage3d}>
              3D 导演台
            </button>
          </div>
        </div>
      </main>
    );
  }

  // settings — 对接模型管理 + Agent
  return (
    <main className="ic-studio">
      <div className="ic-studio-card" style={{ width: "min(640px, 100%)" }}>
        <h1>配置 · 模型与 Agent</h1>
        <p>
          画布通过宿主桥读取「模型管理」里已填 Key 的渠道。生图/生视频需要硅基流动、OpenAI、通义等
          AIGC Key；仅配置 DeepSeek 等对话模型时，拉片可用，生图会提示缺 Key。
        </p>

        <div className="ic-studio-stats">
          <span>激活 {modelInfo.active || "未同步"}</span>
          <span>生图模型 {modelInfo.image}</span>
          <span>生视频模型 {modelInfo.video}</span>
          <span>Agent {agentInfo.listening ? "已连接" : "未启动"}</span>
        </div>

        {modelInfo.warnings.map((w) => (
          <p key={w} className="ic-studio-status" style={{ color: "#fbbf24" }}>
            {w}
          </p>
        ))}
        {agentInfo.listening ? (
          <p className="ic-studio-status">Agent：{agentInfo.url}</p>
        ) : (
          <p className="ic-studio-status">{agentInfo.message || "Agent 未启动"}</p>
        )}
        <p className="ic-studio-status">{localStatus || status}</p>

        <div style={{ marginTop: 12, marginBottom: 12 }}>
          <label htmlFor="vision-model-select" style={{ fontWeight: 600 }}>
            拉片 · 本地视觉模型
          </label>
          <p className="muted" style={{ margin: "4px 0 8px" }}>
            一键拉片用本机视觉模型解析景别 / 运镜 / 画面描述；素材只在本机处理，不出机。
            {visionModels.length === 0
              ? "（未检测到视觉模型，可在 Ollama 安装如 qwen3.5:4b）"
              : ""}
          </p>
          <select
            id="vision-model-select"
            value={visionModel}
            onChange={(e) => {
              setVisionModel(e.target.value);
              setVisionModelState(e.target.value);
            }}
            style={{ maxWidth: 320 }}
          >
            <option value="">自动（优先视觉模型）</option>
            {visionModels.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </div>

        <div className="ic-cta-row">
          <button
            type="button"
            className="ic-btn-primary"
            onClick={async () => {
              onSyncModels();
              await refreshHostStatus();
              setLocalStatus("已请求同步模型池");
              refresh();
            }}
          >
            同步模型池
          </button>
          <button
            type="button"
            className="ic-btn-ghost"
            disabled={agentBusy}
            onClick={async () => {
              setAgentBusy(true);
              setLocalStatus("正在启动 Agent…");
              const res = await startCanvasAgent();
              setLocalStatus(res.message || (res.ok ? "Agent 已连接" : "Agent 失败"));
              await refreshHostStatus();
              setAgentBusy(false);
            }}
          >
            {agentBusy ? "连接中…" : "连接 Agent"}
          </button>
          <button type="button" className="ic-btn-ghost" onClick={onOpenCanvas}>
            回到画布
          </button>
        </div>
        <p className="muted" style={{ marginTop: 14 }}>
          「连接 Agent」拉起本机 canvas-agent（默认 :17371），供 Codex / MCP 调画布工具；
          <strong>不会在 3D 导演台出现人物</strong>。对话 Agent 在剪辑侧栏；画布生图走 AIGC 渠道。
          也可在顶栏直接点「连接 Agent」。
        </p>
      </div>
    </main>
  );
}
