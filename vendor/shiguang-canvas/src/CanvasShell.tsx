import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { type NodeData, type ViewMode } from "./store";
import { nodeTypes } from "./nodes";
import { readFileAsDataUrl, type BridgePrefs, type ImageModelOption } from "./bridge";
import AppNav, { type AppRoute } from "./AppNav";
import HomeLanding from "./HomeLanding";
import StudioPage from "./StudioPages";

export function FrameSlot({
  label,
  url,
  onPick,
  onClear,
}: {
  label: string;
  url?: string;
  onPick: (dataUrl: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      {url ? (
        <div className="frame-row">
          <img className="frame-thumb" src={url} alt={label} />
          <button type="button" className="btn" onClick={onClear}>
            清除
          </button>
        </div>
      ) : null}
      <label className="file-btn">
        选择图片…
        <input
          type="file"
          accept="image/*"
          hidden
          onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            onPick(await readFileAsDataUrl(f));
          }}
        />
      </label>
    </div>
  );
}

export type CanvasShellProps = {
  viewMode: ViewMode;
  setViewMode: (m: ViewMode) => void;
  status: string;
  prefs: BridgePrefs;
  generating: boolean;
  breaking: boolean;
  imageModels: ImageModelOption[];
  selectedModelKey: string;
  setSelectedModelKey: (k: string) => void;
  breakdownDraft: string;
  setBreakdownDraft: (v: string) => void;
  templates: { id: string; name: string; savedAt: string }[];
  dramaTitle: string;
  episode: string;
  setMeta: (dramaTitle: string, episode: string) => void;
  selectedData: NodeData | null;
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  onSelectionChange: (params: { nodes: Node[] }) => void;
  updateSelectedData: (patch: Record<string, unknown>) => void;
  addNode: (type: NodeData["kind"]) => void;
  addStoryboardGrid: (count?: 9 | 25) => void;
  addThreeView: () => void;
  addVariants: (axis?: "表情" | "服装" | "背景", count?: number) => void;
  removeSelected: () => void;
  saveProject: () => void;
  loadProject: () => void;
  saveTemplate: (name: string) => void;
  loadTemplate: (id: string) => void;
  deleteTemplate: (id: string) => void;
  refreshTemplates: () => void;
  onGenerate: () => void;
  onBatchGenerate: () => void;
  onAbortBatch: () => void;
  onSendToEditor: () => void;
  onSendAllToEditor: () => void;
  onSyncModels: () => void;
  onBreakdown: () => void;
  onExportStoryboard: () => void;
  stage3dContent?: React.ReactNode;
};

export default function CanvasShell(props: CanvasShellProps) {
  const {
    viewMode,
    setViewMode,
    status,
    prefs,
    generating,
    breaking,
    imageModels,
    selectedModelKey,
    setSelectedModelKey,
    breakdownDraft,
    setBreakdownDraft,
    templates,
    dramaTitle,
    episode,
    setMeta,
    selectedData,
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    onSelectionChange,
    updateSelectedData,
    addNode,
    addStoryboardGrid,
    addThreeView,
    addVariants,
    removeSelected,
    saveProject,
    loadProject,
    saveTemplate,
    loadTemplate,
    deleteTemplate,
    refreshTemplates,
    onGenerate,
    onBatchGenerate,
    onAbortBatch,
    onSendToEditor,
    onSendAllToEditor,
    onSyncModels,
    onBreakdown,
    onExportStoryboard,
    stage3dContent,
  } = props;

  const showcaseItems = nodes
    .map((n) => {
      const d = n.data as NodeData;
      const cover =
        ("imageUrl" in d && d.imageUrl) ||
        ("posterUrl" in d && d.posterUrl) ||
        ("firstFrameUrl" in d && d.firstFrameUrl) ||
        "";
      if (!cover) return null;
      return {
        id: n.id,
        title: ("title" in d && d.title) || n.id,
        prompt: ("prompt" in d && d.prompt) || ("text" in d && d.text) || "",
        coverUrl: cover,
        tags: [d.kind],
      };
    })
    .filter(Boolean) as {
    id: string;
    title: string;
    prompt: string;
    coverUrl?: string;
    tags?: string[];
  }[];

  const assetCount = nodes.filter((n) => {
    const d = n.data as NodeData;
    return Boolean(
      ("imageUrl" in d && d.imageUrl) ||
        ("posterUrl" in d && d.posterUrl) ||
        ("firstFrameUrl" in d && d.firstFrameUrl),
    );
  }).length;

  const navActive: AppRoute =
    viewMode === "canvas" || viewMode === "stage3d"
      ? "projects"
      : (viewMode as AppRoute);

  const showWorkspace = viewMode === "canvas";
  const showStage = viewMode === "stage3d" && Boolean(stage3dContent);
  const showStudio =
    viewMode !== "home" && viewMode !== "canvas" && viewMode !== "stage3d";

  return (
    <div className="shell">
      <AppNav
        active={navActive}
        onNavigate={(id) => setViewMode(id as ViewMode)}
        version="v0.1.0"
      />

      {viewMode === "home" ? (
        <HomeLanding
          onStart={() => setViewMode("canvas")}
          onOpenCanvas={() => setViewMode("canvas")}
          onViewPrompts={() => setViewMode("prompts")}
          showcase={showcaseItems}
        />
      ) : null}

      {showStudio ? (
        <StudioPage
          route={viewMode}
          onOpenCanvas={() => setViewMode("canvas")}
          onOpenStage3d={() => setViewMode("stage3d")}
          onSyncModels={onSyncModels}
          templateCount={templates.length}
          assetCount={assetCount}
          status={status}
        />
      ) : null}

      {showStage ? (
        <>
          <header className="topbar subbar">
            <div className="seg">
              <button type="button" onClick={() => setViewMode("canvas")}>
                画布
              </button>
              <button type="button" className="on">
                3D 导演台
              </button>
            </div>
            <div className="spacer" />
            <div className="chip">
              {prefs.active_provider_label || prefs.active_provider || "未同步"}
              {prefs.character_name ? ` · ${prefs.character_name}` : ""}
            </div>
          </header>
          {stage3dContent}
        </>
      ) : null}

      {showWorkspace ? (
        <>
      <header className="topbar subbar">
        <div className="brand">
          拾光导演台
          <span>LibTV 向</span>
        </div>
        <div className="seg">
          <button
            type="button"
            className="on"
            onClick={() => setViewMode("canvas")}
          >
            画布
          </button>
          <button
            type="button"
            onClick={() => setViewMode("stage3d")}
          >
            3D 导演台
          </button>
        </div>
        <div className="spacer" />
        <div className="chip">
          {prefs.active_provider_label || prefs.active_provider || "未同步"}
          {prefs.character_name ? ` · ${prefs.character_name}` : ""}
        </div>
        <div className="top-actions">
          <button className="btn primary" onClick={onGenerate} disabled={generating}>
            {generating ? "生成中…" : "生成"}
          </button>
          <button className="btn" onClick={onSendToEditor}>
            入轨
          </button>
          <button className="btn teal" onClick={onSyncModels}>
            同步
          </button>
        </div>
      </header>

        <div className="workspace">
          <aside className="sidebar">
            <details className="panel" open>
              <summary>添加</summary>
              <div className="panel-body">
                <div className="btn-row">
                  <button className="btn" onClick={() => addNode("script")}>
                    剧本
                  </button>
                  <button className="btn" onClick={() => addNode("shot")}>
                    镜头
                  </button>
                  <button className="btn" onClick={() => addNode("prompt")}>
                    提示词
                  </button>
                  <button className="btn" onClick={() => addNode("image")}>
                    图片
                  </button>
                  <button className="btn" onClick={() => addNode("video")}>
                    视频
                  </button>
                  <button className="btn primary" onClick={() => addStoryboardGrid(9)}>
                    九宫格
                  </button>
                </div>
                <button className="btn" onClick={() => addStoryboardGrid(25)}>
                  二十五宫格
                </button>
                <button className="btn teal" onClick={addThreeView}>
                  角色三视图
                </button>
                <button className="btn" onClick={() => setViewMode("stage3d")}>
                  打开 3D 导演台
                </button>
              </div>
            </details>

            <details className="panel">
              <summary>变体 / 拉片</summary>
              <div className="panel-body">
                <div className="btn-row">
                  <button className="btn" onClick={() => addVariants("表情", 3)}>
                    表情×3
                  </button>
                  <button className="btn" onClick={() => addVariants("服装", 3)}>
                    服装×3
                  </button>
                </div>
                <button className="btn" onClick={() => addVariants("背景", 3)}>
                  背景×3
                </button>
                <div className="field">
                  <label>拉片文本</label>
                  <textarea
                    value={breakdownDraft}
                    onChange={(e) => setBreakdownDraft(e.target.value)}
                    placeholder="粘贴剧本，或用选中剧本节点"
                    rows={3}
                  />
                </div>
                <button className="btn primary" onClick={onBreakdown} disabled={breaking}>
                  {breaking ? "拉片中…" : "一键拉片"}
                </button>
              </div>
            </details>

            <details className="panel" open>
              <summary>生成 / 入轨</summary>
              <div className="panel-body">
                <div className="field">
                  <label>AIGC 模型</label>
                  <select
                    value={selectedModelKey}
                    onChange={(e) => setSelectedModelKey(e.target.value)}
                  >
                    {imageModels.length === 0 ? (
                      <option value="">请先同步模型池</option>
                    ) : (
                      imageModels.map((m) => (
                        <option
                          key={`${m.channel_id}::${m.model}`}
                          value={`${m.channel_id}::${m.model}`}
                        >
                          {m.label}
                        </option>
                      ))
                    )}
                  </select>
                </div>
                <button className="btn primary" onClick={onGenerate} disabled={generating}>
                  {generating ? "生成中…" : "生成选中"}
                </button>
                <button className="btn" onClick={onBatchGenerate} disabled={generating}>
                  批量生成
                </button>
                {generating ? (
                  <button className="btn" onClick={onAbortBatch}>
                    中断
                  </button>
                ) : null}
                <div className="btn-row">
                  <button className="btn" onClick={onSendToEditor}>
                    入轨
                  </button>
                  <button className="btn" onClick={onSendAllToEditor} disabled={generating}>
                    全部入轨
                  </button>
                </div>
                <button className="btn teal" onClick={onSyncModels}>
                  同步模型池
                </button>
                <button className="btn ghost" onClick={removeSelected}>
                  删除选中
                </button>
              </div>
            </details>

            <details className="panel">
              <summary>工程</summary>
              <div className="panel-body">
                <div className="btn-row">
                  <button className="btn" onClick={saveProject}>
                    保存
                  </button>
                  <button className="btn" onClick={loadProject}>
                    加载
                  </button>
                </div>
                <button className="btn" onClick={onExportStoryboard}>
                  导出分镜
                </button>
                <button
                  className="btn"
                  onClick={() => {
                    const name = window.prompt("模板名称", "漫剧分镜工作流");
                    if (!name) return;
                    saveTemplate(name);
                    refreshTemplates();
                  }}
                >
                  存为模板
                </button>
                {templates.map((t) => (
                  <div key={t.id} className="row" style={{ gap: 4, marginBottom: 4 }}>
                    <button className="btn" style={{ flex: 1 }} onClick={() => loadTemplate(t.id)}>
                      {t.name}
                    </button>
                    <button
                      className="btn"
                      onClick={() => {
                        deleteTemplate(t.id);
                        refreshTemplates();
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </details>
          </aside>

          <div className="canvas-wrap">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onSelectionChange={onSelectionChange}
              nodeTypes={nodeTypes}
              fitView
              minZoom={0.2}
              maxZoom={2}
              proOptions={{ hideAttribution: true }}
              colorMode="dark"
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1a2433" />
              <MiniMap pannable zoomable />
              <Controls />
            </ReactFlow>
            <div className="status-bar">{status}</div>
          </div>

          <aside className="inspector">
            <div className="section-title">项目</div>
            <div className="field">
              <label>剧名</label>
              <input
                value={dramaTitle}
                onChange={(e) => setMeta(e.target.value, episode)}
                placeholder="漫剧名"
              />
            </div>
            <div className="field">
              <label>集数</label>
              <input
                value={episode}
                onChange={(e) => setMeta(dramaTitle, e.target.value)}
                placeholder="01"
              />
            </div>
            <div className="section-title">选中节点</div>
            {!selectedData ? (
              <div className="muted">点击画布节点编辑</div>
            ) : (
              <>
                {"title" in selectedData && (
                  <div className="field">
                    <label>标题</label>
                    <input
                      value={(selectedData as { title?: string }).title || ""}
                      onChange={(e) => updateSelectedData({ title: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "shot" && (
                  <>
                    <div className="field">
                      <label>景别</label>
                      <select
                        value={selectedData.shotSize}
                        onChange={(e) => updateSelectedData({ shotSize: e.target.value })}
                      >
                        {["远景", "全景", "中景", "近景", "特写"].map((x) => (
                          <option key={x} value={x}>
                            {x}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label>时长（秒）</label>
                      <input
                        type="number"
                        min={0.5}
                        step={0.5}
                        value={selectedData.duration}
                        onChange={(e) =>
                          updateSelectedData({ duration: Number(e.target.value) || 1 })
                        }
                      />
                    </div>
                    <div className="field">
                      <label>对白</label>
                      <textarea
                        value={selectedData.dialogue}
                        onChange={(e) => updateSelectedData({ dialogue: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>提示词（@角色 / @素材）</label>
                      <textarea
                        value={selectedData.prompt}
                        onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                      />
                      <div className="row" style={{ marginTop: 4 }}>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => {
                            const tag = prefs.character_name
                              ? `@${prefs.character_name}`
                              : "@角色";
                            updateSelectedData({
                              prompt: `${selectedData.prompt || ""}${selectedData.prompt ? " " : ""}${tag}`,
                            });
                          }}
                        >
                          @角色
                        </button>
                        <button
                          type="button"
                          className="btn"
                          onClick={() =>
                            updateSelectedData({
                              prompt: `${selectedData.prompt || ""}${selectedData.prompt ? " " : ""}@素材`,
                            })
                          }
                        >
                          @素材
                        </button>
                      </div>
                    </div>
                    <FrameSlot
                      label="首帧"
                      url={selectedData.firstFrameUrl}
                      onPick={(u) => updateSelectedData({ firstFrameUrl: u })}
                      onClear={() => updateSelectedData({ firstFrameUrl: "" })}
                    />
                    <FrameSlot
                      label="尾帧"
                      url={selectedData.lastFrameUrl}
                      onPick={(u) => updateSelectedData({ lastFrameUrl: u })}
                      onClear={() => updateSelectedData({ lastFrameUrl: "" })}
                    />
                  </>
                )}
                {selectedData.kind === "script" && (
                  <div className="field">
                    <label>剧本</label>
                    <textarea
                      value={selectedData.content}
                      onChange={(e) => updateSelectedData({ content: e.target.value })}
                    />
                  </div>
                )}
                {(selectedData.kind === "image" || selectedData.kind === "video") && (
                  <div className="field">
                    <label>提示词</label>
                    <textarea
                      value={selectedData.prompt}
                      onChange={(e) => updateSelectedData({ prompt: e.target.value })}
                    />
                  </div>
                )}
                {selectedData.kind === "video" && (
                  <>
                    <FrameSlot
                      label="首帧"
                      url={selectedData.firstFrameUrl}
                      onPick={(u) => updateSelectedData({ firstFrameUrl: u })}
                      onClear={() => updateSelectedData({ firstFrameUrl: "" })}
                    />
                    <FrameSlot
                      label="尾帧"
                      url={selectedData.lastFrameUrl}
                      onPick={(u) => updateSelectedData({ lastFrameUrl: u })}
                      onClear={() => updateSelectedData({ lastFrameUrl: "" })}
                    />
                  </>
                )}
                {selectedData.kind === "prompt" && (
                  <div className="field">
                    <label>提示词</label>
                    <textarea
                      value={selectedData.text}
                      onChange={(e) => updateSelectedData({ text: e.target.value })}
                    />
                  </div>
                )}
              </>
            )}
          </aside>
        </div>
        </>
      ) : null}
    </div>
  );
}
