import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type Node } from "@xyflow/react";
import { useCanvasStore, type NodeData } from "./store";
import CanvasShell from "./CanvasShell";
import {
  breakdownStoryboard,
  collectUpstreamContext,
  dataUrlToBlob,
  expandAssetMentions,
  expandCharacterMentions,
  fetchPrefs,
  generateImageViaHost,
  installInjectScript,
  listImageModels,
  placeholderImageDataUrl,
  sendBlobToEditor,
  syncModelPool,
  type BridgePrefs,
  type CanvasAssetRef,
  type ImageModelOption,
} from "./bridge";

const Stage3D = lazy(() => import("./Stage3D"));
export default function App() {
  const nodes = useCanvasStore((s) => s.nodes);
  const edges = useCanvasStore((s) => s.edges);
  const status = useCanvasStore((s) => s.status);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const dramaTitle = useCanvasStore((s) => s.dramaTitle);
  const episode = useCanvasStore((s) => s.episode);
  const viewMode = useCanvasStore((s) => s.viewMode);
  const onNodesChange = useCanvasStore((s) => s.onNodesChange);
  const onEdgesChange = useCanvasStore((s) => s.onEdgesChange);
  const onConnect = useCanvasStore((s) => s.onConnect);
  const addNode = useCanvasStore((s) => s.addNode);
  const addStoryboardGrid = useCanvasStore((s) => s.addStoryboardGrid);
  const addThreeView = useCanvasStore((s) => s.addThreeView);
  const addVariants = useCanvasStore((s) => s.addVariants);
  const applyStoryboard = useCanvasStore((s) => s.applyStoryboard);
  const removeSelected = useCanvasStore((s) => s.removeSelected);
  const saveProject = useCanvasStore((s) => s.saveProject);
  const loadProject = useCanvasStore((s) => s.loadProject);
  const listTemplates = useCanvasStore((s) => s.listTemplates);
  const saveTemplate = useCanvasStore((s) => s.saveTemplate);
  const loadTemplate = useCanvasStore((s) => s.loadTemplate);
  const deleteTemplate = useCanvasStore((s) => s.deleteTemplate);
  const setSelected = useCanvasStore((s) => s.setSelected);
  const updateSelectedData = useCanvasStore((s) => s.updateSelectedData);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const setMeta = useCanvasStore((s) => s.setMeta);
  const setViewMode = useCanvasStore((s) => s.setViewMode);
  const setNodeImage = useCanvasStore((s) => s.setNodeImage);
  const addCaptureToCanvas = useCanvasStore((s) => s.addCaptureToCanvas);

  const [prefs, setPrefs] = useState<BridgePrefs>({});
  const [imageModels, setImageModels] = useState<ImageModelOption[]>([]);
  const [selectedModelKey, setSelectedModelKey] = useState("");
  const [generating, setGenerating] = useState(false);
  const [breaking, setBreaking] = useState(false);
  const [templates, setTemplates] = useState(() => listTemplates());
  const [breakdownDraft, setBreakdownDraft] = useState("");
  const batchAbortRef = useRef(false);

  const refreshModels = useCallback(async () => {
    const { models, default: def } = await listImageModels();
    setImageModels(models);
    if (!selectedModelKey) {
      if (def && def.includes("::")) {
        const [cid, ...rest] = def.split("::");
        const model = rest.join("::");
        const hit = models.find((m) => m.channel_id === cid && m.model === model);
        if (hit) setSelectedModelKey(`${hit.channel_id}::${hit.model}`);
        else if (models[0]) setSelectedModelKey(`${models[0].channel_id}::${models[0].model}`);
      } else if (models[0]) {
        setSelectedModelKey(`${models[0].channel_id}::${models[0].model}`);
      }
    }
  }, [selectedModelKey]);

  useEffect(() => {
    installInjectScript();
    fetchPrefs().then(setPrefs);
    refreshModels();
    const t = setInterval(() => {
      fetchPrefs().then(setPrefs);
      refreshModels();
    }, 8000);
    return () => clearInterval(t);
  }, [refreshModels]);

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId) || null,
    [nodes, selectedId],
  );
  const selectedData = (selected?.data || null) as NodeData | null;

  const onSelectionChange = useCallback(
    ({ nodes: ns }: { nodes: Node[] }) => {
      setSelected(ns[0]?.id || null);
    },
    [setSelected],
  );

  const listCanvasAssets = useCallback((): CanvasAssetRef[] => {
    return nodes.map((n) => {
      const d = n.data as NodeData;
      const title = ("title" in d ? d.title : n.id) || n.id;
      let imageUrl = "";
      let promptSnippet = "";
      if (d.kind === "shot") {
        imageUrl = d.imageUrl || d.firstFrameUrl || "";
        promptSnippet = d.prompt || "";
      } else if (d.kind === "image") {
        imageUrl = d.imageUrl || "";
        promptSnippet = d.prompt || "";
      } else if (d.kind === "video") {
        imageUrl = d.posterUrl || d.firstFrameUrl || "";
        promptSnippet = d.prompt || "";
      } else if (d.kind === "prompt") {
        promptSnippet = d.text || "";
      } else if (d.kind === "script") {
        promptSnippet = (d.content || "").slice(0, 80);
      }
      return {
        id: n.id,
        title,
        kind: d.kind,
        imageUrl: imageUrl || undefined,
        promptSnippet: promptSnippet || undefined,
      };
    });
  }, [nodes]);

  const buildPromptFor = (node: Node, data: NodeData) => {
    const prompt =
      data.kind === "prompt"
        ? data.text
        : "prompt" in data
          ? data.prompt
          : "";
    const frameHints: string[] = [];
    if (data.kind === "shot" || data.kind === "video") {
      if (data.firstFrameUrl) frameHints.push("参考首帧构图与人物造型保持一致");
      if (data.lastFrameUrl) frameHints.push("结尾画面朝向尾帧过渡");
    }
    const upstream = collectUpstreamContext(node.id, nodes, edges);
    let raw = [
      dramaTitle ? `剧名:${dramaTitle}` : "",
      episode ? `第${episode}集` : "",
      data.kind === "shot" ? `景别:${data.shotSize}` : "",
      upstream,
      ...frameHints,
      prompt,
    ]
      .filter(Boolean)
      .join("；");
    raw = expandCharacterMentions(raw, prefs, { autoInject: true });
    const asseted = expandAssetMentions(raw, listCanvasAssets().filter((a) => a.id !== node.id));
    return { prompt: asseted.text, assetRef: asseted.referenceImage };
  };

  const buildPrompt = () =>
    selected && selectedData ? buildPromptFor(selected, selectedData).prompt : "";

  const resolveModel = () => {
    let channel_id = "";
    let model = "";
    if (selectedModelKey.includes("::")) {
      const [cid, ...rest] = selectedModelKey.split("::");
      channel_id = cid;
      model = rest.join("::");
    }
    return { channel_id, model };
  };

  const generateForNode = async (node: Node, data: NodeData) => {
    const { prompt: fullPrompt, assetRef } = buildPromptFor(node, data);
    const { channel_id, model } = resolveModel();
    let reference_image = "";
    if (data.kind === "shot" || data.kind === "video") {
      reference_image = data.firstFrameUrl || "";
    }
    if (!reference_image && assetRef) reference_image = assetRef;
    const res = await generateImageViaHost({
      prompt: fullPrompt || "竖屏漫剧分镜",
      model,
      channel_id,
      size: "1024x576",
      reference_image,
      strength: 0.65,
    });
    if (res.ok && (res.image_data_url || res.image_url)) {
      setNodeImage(node.id, res.image_data_url || res.image_url || "");
      return res.message || "生成成功";
    }
    const url = placeholderImageDataUrl(
      `[占位] ${fullPrompt}\n${res.message || ""}`,
    );
    setNodeImage(node.id, url);
    return `${res.message || "生图失败"} — 占位兜底`;
  };

  const onGenerate = async () => {
    if (!selected || !selectedData) {
      setStatus("请先选中镜头/图片/视频节点");
      return;
    }
    if (
      selectedData.kind !== "shot" &&
      selectedData.kind !== "image" &&
      selectedData.kind !== "video"
    ) {
      setStatus("当前节点不支持生成");
      return;
    }
    setGenerating(true);
    setStatus("正在调用 AIGC 生图…");
    try {
      const msg = await generateForNode(selected, selectedData);
      setStatus(msg);
    } catch (e) {
      const url = placeholderImageDataUrl(String(buildPrompt()));
      setNodeImage(selected.id, url);
      setStatus(`生图异常: ${e} — 已用占位图`);
    } finally {
      setGenerating(false);
    }
  };

  const onBatchGenerate = async () => {
    const shots = nodes.filter((n) => {
      const d = n.data as NodeData;
      return d.kind === "shot" || d.kind === "image" || d.kind === "video";
    });
    if (!shots.length) {
      setStatus("没有可生成的镜头/图/视频节点");
      return;
    }
    setGenerating(true);
    batchAbortRef.current = false;
    let ok = 0;
    for (let i = 0; i < shots.length; i++) {
      if (batchAbortRef.current) {
        setStatus(`批量已中断：完成 ${ok}/${shots.length}`);
        break;
      }
      const n = shots[i];
      const d = n.data as NodeData;
      setStatus(`批量生成 ${i + 1}/${shots.length}：${(d as { title?: string }).title || n.id}`);
      setSelected(n.id);
      try {
        await generateForNode(n, d);
        ok += 1;
      } catch {
        /* continue */
      }
    }
    if (!batchAbortRef.current) setStatus(`批量完成：${ok}/${shots.length}`);
    setGenerating(false);
  };

  const nodeImageUrl = (data: NodeData) => {
    if (data.kind === "shot" || data.kind === "image") return data.imageUrl || "";
    if (data.kind === "video") return data.posterUrl || "";
    return "";
  };

  const onSendToEditor = async () => {
    if (!selected || !selectedData) {
      setStatus("请先选中带图的节点");
      return;
    }
    const imageUrl = nodeImageUrl(selectedData);
    if (!imageUrl) {
      setStatus("节点还没有图，请先生成");
      return;
    }
    try {
      setStatus("正在发送到剪辑…");
      const blob = await dataUrlToBlob(imageUrl);
      const title =
        ("title" in selectedData ? selectedData.title : "") ||
        `${selectedData.kind}_${selected.id}`;
      const dur =
        selectedData.kind === "shot" ? Number(selectedData.duration) || 0 : 0;
      const msg = await sendBlobToEditor(blob, `${title}.png`, prefs, {
        title,
        duration_sec: dur,
      });
      setStatus(msg);
    } catch (e) {
      setStatus(`发送失败: ${e}`);
    }
  };

  const onSendAllToEditor = async () => {
    const list = nodes.filter((n) => {
      const d = n.data as NodeData;
      return Boolean(nodeImageUrl(d));
    });
    if (!list.length) {
      setStatus("没有带图的节点可入轨");
      return;
    }
    setGenerating(true);
    let ok = 0;
    for (let i = 0; i < list.length; i++) {
      const n = list[i];
      const d = n.data as NodeData;
      const imageUrl = nodeImageUrl(d);
      setStatus(`入轨 ${i + 1}/${list.length}…`);
      try {
        const blob = await dataUrlToBlob(imageUrl);
        const title = ("title" in d ? d.title : "") || `${d.kind}_${n.id}`;
        const dur = d.kind === "shot" ? Number(d.duration) || 0 : 0;
        await sendBlobToEditor(blob, `${String(i + 1).padStart(2, "0")}_${title}.png`, prefs, {
          title,
          duration_sec: dur,
        });
        ok += 1;
      } catch {
        /* continue */
      }
    }
    setStatus(`全部入轨完成：${ok}/${list.length}（静图按时长转短视频）`);
    setGenerating(false);
  };

  const onSyncModels = async () => {
    setStatus("同步模型池…");
    const msg = await syncModelPool();
    setStatus(msg);
    fetchPrefs().then(setPrefs);
    await refreshModels();
  };

  const resolveScriptText = () => {
    if (breakdownDraft.trim()) return breakdownDraft.trim();
    if (selectedData?.kind === "script" && selectedData.content.trim()) {
      return selectedData.content.trim();
    }
    const first = nodes.find((n) => (n.data as NodeData).kind === "script");
    if (first) {
      const d = first.data as Extract<NodeData, { kind: "script" }>;
      if (d.content.trim()) return d.content.trim();
    }
    return "";
  };

  const onBreakdown = async () => {
    const script = resolveScriptText();
    if (!script) {
      setStatus("请先填写拉片文本，或选中/添加剧本节点");
      return;
    }
    setBreaking(true);
    setStatus("正在一键拉片…");
    try {
      const res = await breakdownStoryboard(script);
      if (!res.ok && !(res.shots && res.shots.length)) {
        setStatus(res.message || "拉片失败");
        return;
      }
      applyStoryboard(res.shots || [], "拉片剧本");
      if (res.fallback) {
        setStatus(`拉片完成（启发式兜底）${res.shots?.length || 0} 镜 — ${res.message || ""}`);
      }
      setViewMode("canvas");
    } catch (e) {
      setStatus(`拉片异常: ${e}`);
    } finally {
      setBreaking(false);
    }
  };

  const refreshTemplates = () => setTemplates(listTemplates());

  const onExportStoryboard = () => {
    const shots = nodes
      .filter((n) => (n.data as NodeData).kind === "shot")
      .map((n, i) => {
        const d = n.data as Extract<NodeData, { kind: "shot" }>;
        return {
          id: i + 1,
          title: d.title,
          shot: d.shotSize,
          duration: d.duration,
          dialogue: d.dialogue,
          description: d.prompt,
          has_image: Boolean(d.imageUrl),
        };
      });
    const payload = {
      dramaTitle,
      episode,
      exportedAt: new Date().toISOString(),
      shots,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `storyboard_${dramaTitle || "untitled"}_${episode || "ep"}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    const header = "id,title,shot,duration,dialogue,description\n";
    const rows = shots
      .map((s) =>
        [s.id, s.title, s.shot, s.duration, s.dialogue, s.description]
          .map((x) => `"${String(x ?? "").replace(/"/g, '""')}"`)
          .join(","),
      )
      .join("\n");
    const csvBlob = new Blob(["\uFEFF" + header + rows], {
      type: "text/csv;charset=utf-8",
    });
    const a2 = document.createElement("a");
    a2.href = URL.createObjectURL(csvBlob);
    a2.download = `storyboard_${dramaTitle || "untitled"}_${episode || "ep"}.csv`;
    a2.click();
    URL.revokeObjectURL(a2.href);
    setStatus(`已导出分镜 JSON+CSV（${shots.length} 镜）`);
  };

  const onAbortBatch = () => {
    batchAbortRef.current = true;
    setStatus("正在中断批量…");
  };

  return (
    <CanvasShell
      viewMode={viewMode}
      setViewMode={setViewMode}
      status={status}
      prefs={prefs}
      generating={generating}
      breaking={breaking}
      imageModels={imageModels}
      selectedModelKey={selectedModelKey}
      setSelectedModelKey={setSelectedModelKey}
      breakdownDraft={breakdownDraft}
      setBreakdownDraft={setBreakdownDraft}
      templates={templates}
      dramaTitle={dramaTitle}
      episode={episode}
      setMeta={setMeta}
      selectedData={selectedData}
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onSelectionChange={onSelectionChange}
      updateSelectedData={updateSelectedData}
      addNode={addNode}
      addStoryboardGrid={addStoryboardGrid}
      addThreeView={addThreeView}
      addVariants={addVariants}
      removeSelected={removeSelected}
      saveProject={saveProject}
      loadProject={loadProject}
      saveTemplate={saveTemplate}
      loadTemplate={loadTemplate}
      deleteTemplate={deleteTemplate}
      refreshTemplates={refreshTemplates}
      onGenerate={onGenerate}
      onBatchGenerate={onBatchGenerate}
      onAbortBatch={onAbortBatch}
      onSendToEditor={onSendToEditor}
      onSendAllToEditor={onSendAllToEditor}
      onSyncModels={onSyncModels}
      onBreakdown={onBreakdown}
      onExportStoryboard={onExportStoryboard}
      stage3dContent={
        <Suspense
          fallback={
            <div className="stage3d" style={{ display: "grid", placeItems: "center", color: "#8b9bb0" }}>
              正在加载 3D 导演台…
            </div>
          }
        >
          <Stage3D
            onStatus={setStatus}
            onCapture={(dataUrl, meta) => {
              addCaptureToCanvas(dataUrl, meta.cameraName);
            }}
          />
        </Suspense>
      }
    />
  );
}
