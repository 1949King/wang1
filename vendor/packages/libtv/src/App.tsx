import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type Node } from "@xyflow/react";
import { useCanvasStore, type NodeData } from "./store";
import { useEditorCanvasLink } from "./hooks/useEditorCanvasLink";
import CanvasShell from "./CanvasShell";
// V4.41.20：把 9 个生成/入轨回调注入 generateActions store，给浮窗 GeneratePanel 用
import { useInjectGenerateActions } from "./generateActionsInjector";
import { NodeActionsContext } from "./nodes";
import { registerBuiltinNodes } from "./registerBuiltinNodes";
import { registerNodeDefinitions } from "./plugins/node-registry";
import { STICKY_PLUGIN } from "./plugins/examples/sticky-note";
import { ensurePluginsLoaded, installPluginFromUrl, setPluginEnabled, uninstallPlugin } from "./plugins/plugin-loader";
import { usePluginStore } from "./plugins/plugin-store";
import { getPluginRuntime, setPluginRuntimeAI } from "./plugins/plugin-runtime";
import { buildNodeTypes, useNodeRegistryVersion } from "./plugins/node-registry";
import {
  breakdownStoryboard,
  collectUpstreamContext,
  dataUrlToBlob,
  expandAssetMentions,
  expandCharacterMentions,
  ensureTauriBridgeCredentials,
  fetchPrefs,
  generateImageViaHost,
  generateVideoViaHost,
  generateAudioViaHost,
  generateTextViaHost,
  batchGenerateVideos,
  getBatchStatus,
  concatVideos,
  imagesToStillVideos,
  inpaintViaHost,
  installInjectScript,
  listImageModels,
  listVideoModels,
  listAudioModels,
  listMusicModels,
  listChatModels,
  sendBlobToEditor,
  syncModelPool,
  waitForVideoPostprocess,
  type BridgePrefs,
  type CanvasAssetRef,
  type ImageModelOption,
  type VideoModelOption,
  type AudioModelOption,
  type MusicModelOption,
  type BatchStatusResult,
} from "./bridge";
// Wave 0 #13：入轨编排抽到独立文件（App.tsx 已1999/2000 顶格，只减不增）
// + 批量快通道：后端 /host/batch-to-timeline 已完整实现但前端零调用。
import { ingestNodes, nodeImageUrl, nodeLink } from "./editorIngress";
import { pickDoneIndices } from "./hostBatchOps";
import {
  generateVideoUnified,
  listLocalVideoModels,
  mergeLocalVideoModels,
} from "./localVideo";
import { generateMusicForNode } from "./canvasMusic";
import { primeAgentPolicy } from "./agentPolicy";
import { runGraphWithConfirm } from "./canvasRun";
import { useRunToHereShortcut } from "./useRunToHereShortcut";
import CanvasOverlays from "./CanvasOverlays";
import { isTypingTarget } from "./CommandPalette";
import { type GenJob } from "./generationQueue";
import { buildCameraPromptBlock, multiAngleBatch, type AnglePreset } from "./shotCamera";
import { applyActiveAestheticToPrompt } from "./aestheticPresets";
import type { PromptItem } from "./promptLibrary";
import { buildWorkflowSkill, downloadWorkflowSkill, readWorkflowSkillFile, skillToProjectBundle } from "./workflowSkill";

const Stage3D = lazy(() => import("./Stage3D"));

/** 应用启动前注册内置节点到 registry（同步，ReactFlow 首次渲染前完成） */
registerBuiltinNodes();
/** 注册示例插件 — 便利贴节点（生产环境应放 public/plugins/ 动态加载） */
registerNodeDefinitions(STICKY_PLUGIN, "plugin:sticky-note");

export default function App() {
  // registry 版本号：插件启用/禁用时 +1，触发 CanvasShell 重新 buildNodeTypes
  useNodeRegistryVersion();
  // 插件系统启动：异步加载已启用的插件 bundle + 监听 Qt 端 manifest 变更
  useEffect(() => {
    ensurePluginsLoaded().catch((e) => console.warn("[plugin] ensurePluginsLoaded failed", e));

    /** Qt → React 插件状态同步（inject.js 每 5s 轮询 /host/plugins 后回调） */
    (window as unknown as { __shiguangPluginSync?: (qtPlugins: Array<{ id: string; url?: string; enabled?: boolean; version?: string; name?: string }>) => void }).__shiguangPluginSync =
      async (qtPlugins) => {
        try {
          const store = usePluginStore.getState();
          const existingById = new Map(store.plugins.map((p) => [p.id, p]));
          const seen = new Set<string>();

          for (const qt of qtPlugins) {
            const id = qt.id;
            if (!id) continue;
            seen.add(id);
            const existing = existingById.get(id);

            if (!existing) {
              // Qt 端新安装 → React 端同步安装
              const url = qt.url;
              if (url) {
                try {
                  await installPluginFromUrl(url, { official: !!qt.name?.includes("官方") });
                  console.log("[plugin] synced install from Qt:", id);
                } catch (e) {
                  console.warn("[plugin] sync install failed:", id, e);
                }
              }
            } else {
              // 启停状态同步
              const qtEnabled = !!qt.enabled;
              if (existing.enabled !== qtEnabled) {
                try {
                  await setPluginEnabled(existing, qtEnabled);
                  console.log("[plugin] synced toggle from Qt:", id, qtEnabled);
                } catch (e) {
                  console.warn("[plugin] sync toggle failed:", id, e);
                }
              }
            }
          }

          // Qt 端已删除 → React 端卸载
          for (const existing of store.plugins) {
            if (!seen.has(existing.id)) {
              try {
                uninstallPlugin(existing.id);
                console.log("[plugin] synced uninstall from Qt:", existing.id);
              } catch (e) {
                console.warn("[plugin] sync uninstall failed:", existing.id, e);
              }
            }
          }
        } catch (e) {
          console.warn("[plugin] Qt sync reconcile failed:", e);
        }
      };

    return () => {
      delete (window as unknown as { __shiguangPluginSync?: unknown }).__shiguangPluginSync;
    };
  }, []);

  // 2026-10-20 启动提速：原逻辑在首屏后 Idle 预热 Stage3D 分包 + BodyKun/BodyChan GLB。
  // 实测首屏因此额外拉取 ~610KB 3D 分包（Stage3D/OrbitControls+three）+ 2.8MB GLB，
  // 与首屏资源争抢主线程/带宽 ⇒ 用户点其他功能时明显卡顿。
  // 现改为**完全不预热**：Stage3D 仍由 React.lazy 在首次切导演台时按需加载；
  // GLB 由 Stage3D 挂载时预热。首屏只付画布自身成本。

  // 启动引导：确保工作区存在并跳到画布视图
  useEffect(() => {
    // 1) ensureWorkspace 负责：迁移 legacy 数据 → 创建默认项目 → 打开首个项目
    useCanvasStore.getState().ensureWorkspace();
    // 2) 默认进入画布视图（而非 home 首页），让顶栏/侧栏/Tab bar 立即可见
    const lastMode = localStorage.getItem("shiguang-canvas:last-viewmode");
    const mode = lastMode && ["canvas", "stage3d", "assets", "home"].includes(lastMode)
      ? (lastMode as import("./store").ViewMode)
      : "canvas";
    useCanvasStore.getState().setViewMode(mode);
    // 3) 后续 viewMode 变化时持久化（用户切到 home 再回来保留状态）
    // 4) 拉角色库（bridge 在线时填充；bridge 离线时静默跳过）
    useCanvasStore.getState().refreshCharacters();
  }, []);
  // viewMode 变化时持久化到 localStorage，下次刷新恢复
  useEffect(() => {
    const m = useCanvasStore.getState().viewMode;
    if (m !== "home") localStorage.setItem("shiguang-canvas:last-viewmode", m);
    const unsub = useCanvasStore.subscribe((s) => {
      if (s.viewMode !== "home") localStorage.setItem("shiguang-canvas:last-viewmode", s.viewMode);
    });
    return unsub;
  }, []);
  // onNodesChange/onEdgesChange/onConnect 改由 CanvasShell 从 store 直取，
  // 避免 App.tsx 每次节点拖拽都重渲染并向下传递新数组引用
  const nodes = useCanvasStore((s) => s.nodes);
  const edges = useCanvasStore((s) => s.edges);
  const status = useCanvasStore((s) => s.status);
  const selectedId = useCanvasStore((s) => s.selectedId);
  const dramaTitle = useCanvasStore((s) => s.dramaTitle);
  const episode = useCanvasStore((s) => s.episode);
  const viewMode = useCanvasStore((s) => s.viewMode);
  const addNode = useCanvasStore((s) => s.addNode);
  const addRegistryNode = useCanvasStore((s) => s.addRegistryNode);
  const addStoryboardGrid = useCanvasStore((s) => s.addStoryboardGrid);
  const addThreeView = useCanvasStore((s) => s.addThreeView);
  const addVariants = useCanvasStore((s) => s.addVariants);
  const applyStoryboard = useCanvasStore((s) => s.applyStoryboard);
  const removeSelected = useCanvasStore((s) => s.removeSelected);
  const deleteEdge = useCanvasStore((s) => s.deleteEdge);
  const duplicateSelected = useCanvasStore((s) => s.duplicateSelected);
  const copySelected = useCanvasStore((s) => s.copySelected);
  const pasteClipboard = useCanvasStore((s) => s.pasteClipboard);
  const selectAll = useCanvasStore((s) => s.selectAll);
  const undoGraph = useCanvasStore((s) => s.undoGraph);
  const redoGraph = useCanvasStore((s) => s.redoGraph);
  const clearSelection = useCanvasStore((s) => s.clearSelection);
  const alignSelected = useCanvasStore((s) => s.alignSelected);
  const beginGraphEdit = useCanvasStore((s) => s.beginGraphEdit);
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
  const setNodeVideo = useCanvasStore((s) => s.setNodeVideo);
  const setPrimaryVideo = useCanvasStore((s) => s.setPrimaryVideo);
  const setNodeAudio = useCanvasStore((s) => s.setNodeAudio);
  const setPrimaryImage = useCanvasStore((s) => s.setPrimaryImage);
  const groupSelected = useCanvasStore((s) => s.groupSelected);
  const getProjectBundle = useCanvasStore((s) => s.getProjectBundle);
  const loadProjectBundle = useCanvasStore((s) => s.loadProjectBundle);
  const addCaptureToCanvas = useCanvasStore((s) => s.addCaptureToCanvas);
  const addStudioNode = useCanvasStore((s) => s.addStudioNode);
  const { clipCount: editorClipCount } = useEditorCanvasLink();

  const [prefs, setPrefs] = useState<BridgePrefs>({});
  /** Wave 0 #13：最近一次批量作业的 job_id / 分段清单。「全部入轨」据此走后端快通道。 */
  const [lastBatchJobId, setLastBatchJobId] = useState<string | null>(null);
  const [lastBatchSegments, setLastBatchSegments] = useState<
    BatchStatusResult["segments"] | undefined
  >(undefined);
  const [imageModels, setImageModels] = useState<ImageModelOption[]>([]);
  const [videoModels, setVideoModels] = useState<VideoModelOption[]>([]);
  const [audioModels, setAudioModels] = useState<AudioModelOption[]>([]);
  const [musicModels, setMusicModels] = useState<MusicModelOption[]>([]);
  const [chatModelKeys, setChatModelKeys] = useState<string[]>([]);
  const [selectedModelKey, setSelectedModelKey] = useState("");
  const [compareModelKey, setCompareModelKey] = useState("");
  const [selectedVideoModelKey, setSelectedVideoModelKey] = useState("");
  const [compareVideoModelKey, setCompareVideoModelKey] = useState("");
  const [selectedAudioModelKey, setSelectedAudioModelKey] = useState("");
  const [selectedMusicModelKey, setSelectedMusicModelKey] = useState("");
  const [generating, setGenerating] = useState(false);
  const [breaking, setBreaking] = useState(false);
  const [templates, setTemplates] = useState(() => listTemplates());
  const [breakdownDraft, setBreakdownDraft] = useState("");
  const batchAbortRef = useRef(false);
  /** 单节点生成的取消控制器（「中断」按钮复用：同时取消在飞的单节点/批量任务） */
  const genAbortRef = useRef<AbortController | null>(null);
  const batchGenAbortRef = useRef<AbortController | null>(null);

  const pickDefaultKey = (
    models: ImageModelOption[],
    def: string,
    current: string,
    setter: (k: string) => void,
  ) => {
    if (current) return;
    if (def && def.includes("::")) {
      const [cid, ...rest] = def.split("::");
      const model = rest.join("::");
      const hit = models.find((m) => m.channel_id === cid && m.model === model);
      if (hit) {
        setter(`${hit.channel_id}::${hit.model}`);
        return;
      }
    }
    if (models[0]) setter(`${models[0].channel_id}::${models[0].model}`);
  };

  const pickCompareKey = (
    models: ImageModelOption[],
    primaryKey: string,
    current: string,
    setter: (k: string) => void,
  ) => {
    if (current) return;
    const alt = models.find((m) => `${m.channel_id}::${m.model}` !== primaryKey);
    if (alt) setter(`${alt.channel_id}::${alt.model}`);
    else if (models[1]) setter(`${models[1].channel_id}::${models[1].model}`);
  };

  const refreshModels = useCallback(async () => {
    const [img, vid, aud, mus, chat, localVid] = await Promise.all([
      listImageModels(),
      listVideoModels(),
      listAudioModels(),
      listMusicModels(),
      listChatModels(),
      // 本机（diffusers）视频模型 —— 与云端并列展示，通道 id 固定为 "local"。
      // 只读探测：不下载权重、不加载模型（慢的是生成，不是列清单）。
      listLocalVideoModels(),
    ]);
    setImageModels(img.models);
    // 云端 + **本机**模型合并展示（标注体积/已下未下/显存内存需求，细节见 localVideo.ts）
    setVideoModels(mergeLocalVideoModels(vid.models, localVid));
    setAudioModels(aud.models);
    setMusicModels(mus.models);
    const chatKeys: string[] = [];
    for (const p of chat.providers || []) {
      if (!p.configured) continue;
      for (const m of p.models || []) {
        chatKeys.push(`${p.id}::${m}`);
      }
    }
    setChatModelKeys(chatKeys);
    pickDefaultKey(img.models, img.default, selectedModelKey, setSelectedModelKey);
    pickDefaultKey(vid.models, vid.default, selectedVideoModelKey, setSelectedVideoModelKey);
    pickDefaultKey(aud.models, aud.default, selectedAudioModelKey, setSelectedAudioModelKey);
    pickDefaultKey(mus.models, mus.default, selectedMusicModelKey, setSelectedMusicModelKey);
    pickCompareKey(img.models, selectedModelKey, compareModelKey, setCompareModelKey);
    pickCompareKey(vid.models, selectedVideoModelKey, compareVideoModelKey, setCompareVideoModelKey);
    const warns = [...(img.warnings || []), ...(vid.warnings || []), ...(aud.warnings || []), ...(mus.warnings || [])];
    if (!img.models.length && warns[0]) {
      setStatus(warns[0]);
    } else if (img.active_provider_label) {
      setStatus(
        `模型池：生图 ${img.models.length} · 生视频 ${vid.models.length} · TTS ${aud.models.length} · 音乐 ${mus.models.length} · 激活 ${img.active_provider_label}`,
      );
    }
  }, [
    selectedModelKey,
    selectedVideoModelKey,
    selectedAudioModelKey,
    selectedMusicModelKey,
    compareModelKey,
    compareVideoModelKey,
    setStatus,
  ]);

  useEffect(() => {
    // Tauri 桌面模式：先从 Rust 端拿到 Python 后端凭据（token / URL）写入 window，
    // 之后 bridgeToken() / BRIDGE 才能正确返回后端实际地址。
    // Qt WebEngine 模式：ensureTauriBridgeCredentials 是 no-op，回退到 inject.js 注入路径。
    ensureTauriBridgeCredentials().finally(() => {
      // 仅 Qt WebEngine 嵌入模式需要 inject.js（注入浮动面板 + Qt WebChannel 通信）。
      // Tauri 独立窗口已有自己的 UI 和桥接，跳过避免注入无用 DOM 和 Qt 依赖。
      const isTauri =
        typeof window !== "undefined" &&
        ("__TAURI__" in window || "__TAURI_INTERNALS__" in window);
      if (!isTauri) {
        installInjectScript();
      }
      fetchPrefs().then(setPrefs);
      refreshModels();
      void primeAgentPolicy();   // 拉取 Agent 策略（单一真源在后端；失败走保守兜底）
    });
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
      } else if (d.kind === "digitalHuman") {
        imageUrl = d.imageUrl || "";
        promptSnippet = d.line || d.prompt || "";
      } else if (d.kind === "director" || d.kind === "panorama") {
        imageUrl = d.imageUrl || "";
        promptSnippet = d.prompt || "";
      } else if (d.kind === "animation") {
        imageUrl = d.sheetUrl || "";
        promptSnippet = d.prompt || "";
      } else if (d.kind === "source") {
        imageUrl = d.imageUrl || "";
        promptSnippet = d.prompt || d.content || "";
      } else if (d.kind === "video") {
        imageUrl = d.posterUrl || d.firstFrameUrl || "";
        promptSnippet = d.prompt || "";
      } else if (d.kind === "prompt") {
        promptSnippet = d.text || "";
      } else if (d.kind === "text") {
        promptSnippet = (d.content || "").slice(0, 80);
      } else if (d.kind === "config") {
        promptSnippet = (d.prompt || d.content || "").slice(0, 80);
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
        : data.kind === "text"
          ? data.content
          : data.kind === "config"
            ? data.prompt || data.content || ""
            : "prompt" in data
              ? data.prompt
              : "";
    const frameHints: string[] = [];
    if (data.kind === "shot" || data.kind === "video") {
      if (data.firstFrameUrl) frameHints.push("参考首帧构图与人物造型保持一致");
      if (data.lastFrameUrl) frameHints.push("结尾画面朝向尾帧过渡");
    }
    if (
      (data.kind === "shot" || data.kind === "video" || data.kind === "image") &&
      "refVideoUrl" in data &&
      data.refVideoUrl
    ) {
      frameHints.push(
        `参考视频片段${data.refVideoName ? `「${data.refVideoName}」` : ""}的运镜节奏与构图气质`,
      );
    }
    const upstream = collectUpstreamContext(node.id, nodes, edges);
    const cameraBlock =
      data.kind === "shot"
        ? buildCameraPromptBlock({
            shotSize: data.shotSize,
            cameraYaw: data.cameraYaw,
            cameraPitch: data.cameraPitch,
            focalLength: data.focalLength,
            aperture: data.aperture,
            movement: data.movement,
          })
        : "";
    let raw = [
      dramaTitle ? `剧名:${dramaTitle}` : "",
      episode ? `第${episode}集` : "",
      cameraBlock,
      data.kind === "shot" && !cameraBlock ? `景别:${data.shotSize}` : "",
      upstream,
      ...frameHints,
      (data.kind === "shot" || data.kind === "image" || data.kind === "video") ? applyActiveAestheticToPrompt(prompt || "") : prompt,
    ]
      .filter(Boolean)
      .join("；");
    raw = expandCharacterMentions(raw, prefs, { autoInject: true });
    const asseted = expandAssetMentions(raw, listCanvasAssets().filter((a) => a.id !== node.id));
    return { prompt: asseted.text, assetRef: asseted.referenceImage };
  };

  const buildPrompt = () =>
    selected && selectedData ? buildPromptFor(selected, selectedData).prompt : "";

  const resolveModel = (key: string) => {
    let channel_id = "";
    let model = "";
    if (key.includes("::")) {
      const [cid, ...rest] = key.split("::");
      channel_id = cid;
      model = rest.join("::");
    }
    return { channel_id, model };
  };


  useEffect(() => {
    const modelKey = (m: { channel_id: string; model: string }) => `${m.channel_id}::${m.model}`;
    setPluginRuntimeAI({
      generateImage: async (prompt, opts) => {
        const parsed = opts?.model?.includes("::")
          ? resolveModel(opts.model)
          : resolveModel(selectedModelKey);
        const res = await generateImageViaHost({
          prompt,
          model: parsed.model,
          channel_id: parsed.channel_id,
          n: opts?.count || 1,
          size: opts?.size,
          reference_image: opts?.references?.[0] || "",
          quality: opts?.quality || "standard",
        });
        if (res.images?.length) return res.images;
        const one = res.image_data_url || res.image_url;
        return one ? [one] : [];
      },
      generateVideo: async (prompt, opts) => {
        const parsed = opts?.model?.includes("::")
          ? resolveModel(opts.model)
          : resolveModel(selectedVideoModelKey);
        const res = await generateVideoViaHost({
          prompt,
          model: parsed.model,
          channel_id: parsed.channel_id,
          duration: opts?.duration || 5,
          reference_image: opts?.references?.[0] || "",
          quality: opts?.quality || "standard",
        });
        const final = await waitForVideoPostprocess(res);
        return final.video_url || "";
      },
      generateText: async (prompt, opts) => {
        const res = await generateTextViaHost({
          prompt,
          provider: opts?.channel_id,
          model: opts?.model,
        });
        return res.text || "";
      },
      listModels: (kind) => {
        if (kind === "video") return videoModels.map(modelKey);
        if (kind === "audio") return audioModels.map(modelKey);
        if (kind === "text") return chatModelKeys;
        return imageModels.map(modelKey);
      },
      defaultModel: (kind) => {
        if (kind === "video") return selectedVideoModelKey;
        if (kind === "audio") return selectedAudioModelKey;
        if (kind === "text") return chatModelKeys[0] || "";
        return selectedModelKey;
      },
    });
  }, [
    imageModels,
    videoModels,
    audioModels,
    chatModelKeys,
    selectedModelKey,
    selectedVideoModelKey,
    selectedAudioModelKey,
  ]);

  const generateForNode = async (
    node: Node,
    data: NodeData,
    genOpts?: { signal?: AbortSignal; onProgress?: (job: GenJob) => void },
  ): Promise<{ ok: boolean; message: string }> => {
    // 异步任务化透传：传了 genOpts 的调用可取消、可收到阶段/进度上报；
    // 不传（插件运行时、对比生成等）则行为与旧同步端点完全一致。
    const awaitOpts = genOpts
      ? { signal: genOpts.signal, onProgress: genOpts.onProgress, maxAttempts: 1 }
      : undefined;
    if (data.kind === "config") {
      const mode = data.generationMode || "image";
      const count = Math.max(1, Math.min(4, Number(data.count) || 1));
      const basePrompt = data.prompt || buildPromptFor(node, data).prompt;
      const pseudoGen = { ...data, kind: "generator" as const, mode, prompt: basePrompt, count };
      return generateForNode(node, pseudoGen, genOpts);
    }

    if (data.kind === "text") {
      const res = await generateTextViaHost({
        prompt: buildPromptFor(node, data).prompt || data.content || "续写",
      });
      if (res.ok && res.text) {
        useCanvasStore.getState().updateNodeData(node.id, {
          content: res.text,
          status: "success",
        });
        return { ok: true, message: res.message || "文本生成成功" };
      }
      return { ok: false, message: res.message || "文本生成失败" };
    }

    // 生成器：按 mode 分发，count 叠卡
    if (data.kind === "generator") {
      const count = Math.max(1, Math.min(4, Number(data.count) || 1));
      const mode = data.mode || "image";
      if (mode === "audio") {
        const { channel_id, model } = resolveModel(selectedAudioModelKey);
        const res = await generateAudioViaHost({
          prompt: data.prompt || "环境音",
          model,
          channel_id,
        });
        if (res.ok && res.audio_url) {
          addStudioNode("audio", {
            title: `${data.title || "生成器"}·音频`,
            prompt: data.prompt,
            audioUrl: res.audio_url,
          });
          return { ok: true, message: res.message || "生成器已产出音频节点" };
        }
        return { ok: false, message: res.message || "生成器生音频失败" };
      }
      if (mode === "video") {
        if (!videoModels.length) {
          return { ok: false, message: "生成器·视频：无可用生视频模型" };
        }
        const bp = buildPromptFor(node, data);
        const res = await generateVideoUnified({
          parsed: resolveModel(selectedVideoModelKey),
          prompt: data.prompt || bp.prompt,
          // 原实现不传参考图（保持 ""）；若用本机图生视频模型，会如实提示「需要首帧图」
          referenceImage: "",
          duration: 5,
          quality: "standard",
          awaitOpts,
        });
        if (res.ok && res.video_url) {
          addStudioNode("video", {
            title: `${data.title || "生成器"}·视频`,
            prompt: data.prompt,
            videoUrl: res.video_url,
          });
          return { ok: true, message: res.message || "生成器已产出视频节点" };
        }
        return { ok: false, message: res.message || "生成器生视频失败" };
      }
      if (mode === "text") {
        addStudioNode("prompt", {
          title: data.title || "生成文本",
          text: data.prompt || buildPromptFor(node, data).prompt,
        });
        return { ok: true, message: "已写入提示词节点（文本模式不走云端）" };
      }
      const { channel_id, model } = resolveModel(selectedModelKey);
      const { prompt: fullPrompt, assetRef } = buildPromptFor(node, {
        ...data,
        kind: "image",
        title: data.title,
        prompt: data.prompt,
      } as NodeData);
      const res = await generateImageViaHost({
        prompt: fullPrompt || data.prompt || "竖屏漫剧",
        model,
        channel_id,
        n: count,
        reference_image: assetRef || "",
        awaitOpts,
      });
      const urls = res.images?.length
        ? res.images
        : res.image_data_url || res.image_url
          ? [res.image_data_url || res.image_url || ""]
          : [];
      if (!urls.length) {
        return { ok: false, message: res.message || "生成器生图失败" };
      }
      const imgNode = {
        title: data.title || "生成器·图",
        prompt: data.prompt,
        imageUrl: urls[0],
      };
      addStudioNode("image", imgNode);
      // 叠卡写入刚加的选中节点
      const sid = useCanvasStore.getState().selectedId;
      if (sid) {
        for (let i = 0; i < urls.length; i++) {
          setNodeImage(sid, urls[i]);
        }
      }
      return { ok: true, message: res.message || `生成器叠卡 ${urls.length} 张` };
    }

    if (data.kind === "audio") {
      if (data.audioUrl) {
        return { ok: true, message: "音频节点已有文件；上传优先于 TTS" };
      }
      const { channel_id, model } = resolveModel(selectedAudioModelKey);
      const res = await generateAudioViaHost({
        prompt: data.prompt || "旁白",
        model,
        channel_id,
      });
      if (res.ok && res.audio_url) {
        setNodeAudio(node.id, res.audio_url);
        return { ok: true, message: res.message || "TTS 生成成功" };
      }
      return { ok: false, message: res.message || "生音频不可用，请上传音频" };
    }

    if (data.kind === "digitalHuman") {
      const line = (data.line || "").trim();
      if (!line) {
        return { ok: false, message: "请先填写台词" };
      }
      const { channel_id, model } = resolveModel(selectedAudioModelKey);
      const prompt = data.characterName?.trim()
        ? `${data.characterName.trim()}：${line}`
        : line;
      const res = await generateAudioViaHost({
        prompt,
        model,
        channel_id,
      });
      if (res.ok && res.audio_url) {
        setNodeAudio(node.id, res.audio_url);
        return {
          ok: true,
          message: `${res.message || "配音已生成"}（口型成片未接入，请入轨配音+形象图）`,
        };
      }
      return {
        ok: false,
        message: res.message || "配音失败。口型成片未配置形象驱动模型，不会假写视频。",
      };
    }

    if (data.kind === "music") {
      if (data.audioUrl) {
        return { ok: true, message: "音乐节点已有文件；再次生成将覆盖" };
      }
      // 音乐生成编排已抽到 canvasMusic.ts（Suno 黑盒 / YuE 符号规划两条链路）
      const { channel_id, model } = resolveModel(selectedMusicModelKey);
      const out = await generateMusicForNode({
        data: data as any,
        channelId: channel_id,
        model,
        musicModelCount: musicModels.length,
      });
      if (out.ok && out.audioUrl) {
        setNodeAudio(node.id, out.audioUrl);
        if (out.patch) useCanvasStore.getState().updateNodeData(node.id, out.patch as any);
        return { ok: true, message: out.message };
      }
      return { ok: false, message: out.message, hint: out.hint } as any;
    }

    const { prompt: fullPrompt, assetRef } = buildPromptFor(node, data);
    let reference_image = "";
    if (data.kind === "shot" || data.kind === "video") {
      reference_image = data.firstFrameUrl || "";
    }
    if (!reference_image && assetRef) reference_image = assetRef;

    if (data.kind === "video") {
      if (data.isReference && data.videoUrl) {
        return {
          ok: true,
          message: "这是参考视频片段节点，无需生成；可挂到镜头或发给 Agent-IM。",
        };
      }
      if (!videoModels.length) {
        return {
          ok: false,
          message: "无可用生视频模型。请在模型管理配置视频渠道 Key，再同步模型池。",
        };
      }
      const duration = Math.max(2, Math.min(10, Number(data.duration) || 5));
      const res = await generateVideoUnified({
        parsed: resolveModel(selectedVideoModelKey),
        prompt: fullPrompt || "竖屏漫剧镜头，电影感运镜",
        referenceImage: reference_image,
        duration,
        quality: data.qualityTier || "standard",
        size: "720x1280",
        awaitOpts,
      });
      if (res.ok && res.video_url) {
        setNodeVideo(node.id, res.video_url, data.posterUrl || data.firstFrameUrl);
        useCanvasStore.getState().reviewNode(node.id);
        return { ok: true, message: res.message || "视频生成成功" };
      }
      return { ok: false, message: res.message || "生视频失败（未写入假结果）" };
    }

    const { channel_id, model } = resolveModel(selectedModelKey);
    const res = await generateImageViaHost({
      prompt: fullPrompt || "竖屏漫剧分镜",
      model,
      channel_id,
      // size 不传：交后端按 quality + aspect 推导（默认竖屏短剧 9:16）
      aspect: (data as any).aspect || "",
      reference_image,
      strength: 0.65,
      n: 1,
      quality: (data as any).qualityTier || "standard",
      onPreloadProgress: (p) => setStatus(`人脸修复模型预载 ${p.progress}%：${p.message}`),
      awaitOpts,
    });
    if (res.ok && (res.image_data_url || res.image_url || res.images?.length)) {
      const urls = res.images?.length
        ? res.images
        : [res.image_data_url || res.image_url || ""];
      for (const u of urls) {
        if (u) setNodeImage(node.id, u);
      }
      // 抽卡闭环产物回写节点（V4.40.10）：推荐 / 代理分 / 种子 / 坏区修复计划
      // 前端此前零消费这些字段（DEFECT C），现落到节点数据由 NoviceInspector 展示。
      const rec = (res as any).recommendation;
      const patch: Record<string, unknown> = {};
      if (typeof res.seed === "number") patch.lastSeed = res.seed;
      if (typeof res.seed_sent === "boolean") patch.lastSeedSent = res.seed_sent;
      if (typeof (res as any).proxy_score === "number") {
        patch.proxyScore = (res as any).proxy_score;
        patch.isProxy = (res as any).is_proxy === true;
      }
      if (rec && (rec.best_seed != null || rec.mean != null)) {
        patch.recommendation = rec;
      }
      if ((res as any).repair_plan) patch.repairPlan = (res as any).repair_plan;
      if (Object.keys(patch).length) {
        useCanvasStore.getState().updateNodeData(node.id, patch);
      }
      useCanvasStore.getState().reviewNode(node.id);
      return { ok: true, message: res.message || "生成成功" };
    }
    return { ok: false, message: res.message || "生图失败（未写入占位图）" };
  };

  const generateImageAtKey = async (
    node: Node,
    data: NodeData,
    modelKey: string,
    promptSuffix = "",
  ) => {
    const { prompt: fullPrompt, assetRef } = buildPromptFor(node, data);
    let reference_image = "";
    if (data.kind === "shot" || data.kind === "video") {
      reference_image = data.firstFrameUrl || "";
    }
    if (!reference_image && assetRef) reference_image = assetRef;
    const { channel_id, model } = resolveModel(modelKey);
    const res = await generateImageViaHost({
      prompt: `${fullPrompt}${promptSuffix ? `；${promptSuffix}` : ""}` || "竖屏漫剧分镜",
      model,
      channel_id,
      // size 不传：交后端按 quality + aspect 推导（默认竖屏短剧 9:16）
      aspect: (data as any).aspect || "",
      reference_image,
      strength: 0.65,
      n: 1,
      quality: (data as any).qualityTier || "standard",
    });
    const url =
      res.images?.[0] ||
      res.image_data_url ||
      res.image_url ||
      "";
    return { res, url, modelKey };
  };

  const generateVideoAtKey = async (
    node: Node,
    data: Extract<NodeData, { kind: "video" }>,
    modelKey: string,
  ) => {
    const { prompt: fullPrompt, assetRef } = buildPromptFor(node, data);
    let reference_image = data.firstFrameUrl || "";
    if (!reference_image && assetRef) reference_image = assetRef;
    const duration = Math.max(2, Math.min(10, Number(data.duration) || 5));
    const res = await generateVideoUnified({
      parsed: resolveModel(modelKey),
      prompt: fullPrompt || "竖屏漫剧镜头，电影感运镜",
      referenceImage: reference_image,
      duration,
      quality: data.qualityTier || "standard",
    });
    return { res, url: res.video_url || "", modelKey };
  };

  const onCompareGenerate = async () => {
    if (!selected || !selectedData) {
      setStatus("请先选中镜头/图片/视频节点");
      return;
    }

    if (selectedData.kind === "video") {
      if (selectedData.isReference && selectedData.videoUrl) {
        setStatus("参考视频节点无需对比生成");
        return;
      }
      if (!videoModels.length) {
        setStatus("无可用生视频模型");
        return;
      }
      if (!compareVideoModelKey || compareVideoModelKey === selectedVideoModelKey) {
        setStatus("请选择与主模型不同的对比视频模型");
        return;
      }
      const primaryLabel =
        videoModels.find((m) => `${m.channel_id}::${m.model}` === selectedVideoModelKey)?.label ||
        "视频A";
      const compareLabel =
        videoModels.find((m) => `${m.channel_id}::${m.model}` === compareVideoModelKey)?.label ||
        "视频B";
      setGenerating(true);
      setStatus(`双模型对比生视频：${primaryLabel} vs ${compareLabel}（较慢）…`);
      try {
        const vd = selectedData as Extract<NodeData, { kind: "video" }>;
        const a = await generateVideoAtKey(selected, vd, selectedVideoModelKey);
        if (a.url) setNodeVideo(selected.id, a.url, vd.posterUrl || vd.firstFrameUrl, { label: primaryLabel });
        setStatus(`对比 1/2 完成 · 正在跑 ${compareLabel}…`);
        const b = await generateVideoAtKey(selected, vd, compareVideoModelKey);
        let ok = a.url ? 1 : 0;
        if (b.url) {
          setNodeVideo(selected.id, b.url, vd.posterUrl || vd.firstFrameUrl, { label: compareLabel });
          ok += 1;
        }
        setStatus(
          ok === 2
            ? `视频对比完成 · 叠卡切换 ${primaryLabel} / ${compareLabel}`
            : `视频对比部分成功 (${ok}/2) · ${a.res.message || ""} ${b.res.message || ""}`.trim(),
        );
      } catch (e) {
        setStatus(`视频对比异常: ${e}`);
      } finally {
        setGenerating(false);
      }
      return;
    }

    if (selectedData.kind !== "shot" && selectedData.kind !== "image") {
      setStatus("双模型对比支持镜头/图片/视频节点");
      return;
    }
    if (!compareModelKey || compareModelKey === selectedModelKey) {
      setStatus("请选择与主模型不同的对比模型");
      return;
    }
    const primaryLabel =
      imageModels.find((m) => `${m.channel_id}::${m.model}` === selectedModelKey)?.label ||
      "模型A";
    const compareLabel =
      imageModels.find((m) => `${m.channel_id}::${m.model}` === compareModelKey)?.label ||
      "模型B";
    setGenerating(true);
    setStatus(`双模型对比生成：${primaryLabel} vs ${compareLabel}…`);
    try {
      const [a, b] = await Promise.all([
        generateImageAtKey(selected, selectedData, selectedModelKey),
        generateImageAtKey(selected, selectedData, compareModelKey),
      ]);
      let ok = 0;
      if (a.url) {
        setNodeImage(selected.id, a.url, { label: primaryLabel });
        ok += 1;
      }
      if (b.url) {
        setNodeImage(selected.id, b.url, { label: compareLabel });
        ok += 1;
      }
      setStatus(
        ok === 2
          ? `对比完成 · 叠卡可切换 ${primaryLabel} / ${compareLabel}`
          : `对比部分成功 (${ok}/2) · ${a.res.message || ""} ${b.res.message || ""}`.trim(),
      );
    } catch (e) {
      setStatus(`对比生成异常: ${e}`);
    } finally {
      setGenerating(false);
    }
  };

  const onMultiAngleGenerate = async () => {
    if (!selected || !selectedData || selectedData.kind !== "shot") {
      setStatus("请先选中分镜/镜头节点");
      return;
    }
    const angles = multiAngleBatch();
    setGenerating(true);
    setStatus(`多角度预览：${angles.length} 个机位…`);
    try {
      let ok = 0;
      for (let i = 0; i < angles.length; i++) {
        const ang: AnglePreset = angles[i];
        const patched = {
          ...selectedData,
          cameraYaw: ang.yaw,
          cameraPitch: ang.pitch,
        } as NodeData;
        const suffix = buildCameraPromptBlock({
          shotSize: selectedData.shotSize,
          cameraYaw: ang.yaw,
          cameraPitch: ang.pitch,
          focalLength: selectedData.focalLength,
          movement: selectedData.movement,
        });
        setStatus(`多角度 ${i + 1}/${angles.length}：${ang.label}…`);
        const { url } = await generateImageAtKey(selected, patched, selectedModelKey, suffix);
        if (url) {
          setNodeImage(selected.id, url, { label: ang.label });
          ok += 1;
        }
      }
      setStatus(`多角度完成 ${ok}/${angles.length} · 叠卡切换机位预览`);
    } catch (e) {
      setStatus(`多角度生成异常: ${e}`);
    } finally {
      setGenerating(false);
    }
  };

  const onExportSkill = () => {
    const name = window.prompt("Skill 名称", dramaTitle ? `${dramaTitle} 工作流` : "漫剧分镜 Skill");
    if (!name) return;
    const bundle = getProjectBundle();
    downloadWorkflowSkill(
      buildWorkflowSkill({
        name,
        dramaTitle: bundle.dramaTitle,
        episode: bundle.episode,
        nodes: bundle.nodes,
        edges: bundle.edges,
      }),
    );
    setStatus(`已导出 Skill：${name}.json`);
  };

  const onImportSkill = async (file: File) => {
    try {
      const skill = await readWorkflowSkillFile(file);
      const replace = nodes.length
        ? window.confirm(`导入 Skill「${skill.name}」将覆盖当前画布节点，是否继续？`)
        : true;
      if (!replace) return;
      loadProjectBundle(skillToProjectBundle(skill));
      setStatus(`已导入 Skill：${skill.name}（${skill.nodes.length} 节点）`);
    } catch (e) {
      setStatus(`导入 Skill 失败: ${e}`);
    }
  };

  const onGenerate = async () => {
    if (!selected || !selectedData) {
      setStatus("请先选中镜头/图片/视频/生成器/音频/导演台/动画/数字人节点");
      return;
    }
    if (
      selectedData.kind !== "shot" &&
      selectedData.kind !== "image" &&
      selectedData.kind !== "video" &&
      selectedData.kind !== "generator" &&
      selectedData.kind !== "audio" &&
      selectedData.kind !== "music" &&
      selectedData.kind !== "director" &&
      selectedData.kind !== "animation" &&
      selectedData.kind !== "panorama" &&
      selectedData.kind !== "digitalHuman"
    ) {
      setStatus("当前节点不支持生成");
      return;
    }
    useCanvasStore.getState().updateNodeData(selected.id, {
      status: "generating",
      progress: 0,
      errorMessage: "",
    });
    setGenerating(true);
    setStatus(
      selectedData.kind === "video"
        ? "正在调用 AIGC 生视频（可能需要 1–3 分钟）…"
        : "正在调用 AIGC…",
    );
    const ctrl = new AbortController();
    genAbortRef.current = ctrl;
    const nodeId = selected.id;
    try {
      const { ok, message } = await generateForNode(selected, selectedData, {
        signal: ctrl.signal,
        onProgress: (job) => {
          // 如实上报：progress 为 null 表示上游没有真实进度信号，
          // 只显示阶段与已用时，绝不编造百分比（契约见 generationQueue.ts）
          const secs = Math.round((job.elapsed_ms || 0) / 1000);
          setStatus(
            job.progress != null
              ? `${job.stage_label} ${job.progress}%（已用时 ${secs}s）`
              : `${job.stage_label} · 已用时 ${secs}s`,
          );
          if (job.progress != null) {
            useCanvasStore.getState().updateNodeData(nodeId, { progress: job.progress });
          }
        },
      });
      if (!ok && message === "已取消") {
        // 用户主动中断：回 idle，不亮红、不残留错误
        useCanvasStore.getState().updateNodeData(nodeId, {
          status: "idle",
          progress: 0,
          errorMessage: "",
        });
        setStatus("已取消生成");
        return;
      }
      useCanvasStore.getState().updateNodeData(nodeId, {
        status: ok ? "success" : "failed",
        progress: ok ? 100 : 0,
        errorMessage: ok ? "" : String(message || "生成失败").slice(0, 200),
      });
      setStatus(message);
    } catch (e) {
      const errMsg = String(e);
      useCanvasStore.getState().updateNodeData(nodeId, {
        status: "failed",
        errorMessage: errMsg.slice(0, 200),
      });
      setStatus(`生成异常: ${e}`);
    } finally {
      genAbortRef.current = null;
      setGenerating(false);
    }
  };

  const onInpaint = async (mask: string, prompt: string) => {
    if (!selected || !selectedData) return;
    const imageUrl =
      selectedData.kind === "shot" || selectedData.kind === "image"
        ? selectedData.imageUrl
        : "";
    if (!imageUrl) {
      setStatus("当前节点没有可重绘的图片");
      return;
    }
    setGenerating(true);
    setStatus("正在局部重绘…");
    const { channel_id, model } = resolveModel(selectedModelKey);
    try {
      const res = await inpaintViaHost({
        prompt,
        image: imageUrl,
        mask,
        model,
        channel_id,
      });
      if (res.ok && (res.image_data_url || res.image_url)) {
        setNodeImage(selected.id, res.image_data_url || res.image_url || "");
        setStatus(res.message || "局部重绘成功");
      } else {
        setStatus(res.message || "局部重绘失败（未写入假图）");
      }
    } catch (e) {
      setStatus(`局部重绘异常: ${e}`);
    } finally {
      setGenerating(false);
    }
  };

  // 「运行到此处」：后端 /host/canvas-run 出计划→确认→执行；编排见 canvasRun.ts（App 顶到规模上限，逻辑外置）
  const runToHere = useCallback(async () => {
    await runGraphWithConfirm({
      getGraph: () => {
        const st = useCanvasStore.getState();
        return { nodes: st.nodes as unknown[], edges: st.edges as unknown[] };
      },
      confirm: (text) => (typeof window === "undefined" ? false : window.confirm(text)),
      onStatus: setStatus,
      onNodePatch: (id, patch) =>
        useCanvasStore.getState().updateNodeData(id, patch as never),
      onBusy: setGenerating,
    });
  }, []);

  useRunToHereShortcut(() => {
    void runToHere();
  });

  const onBatchGenerate = async () => {
    const shots = nodes.filter((n) => {
      const d = n.data as NodeData;
      return d.kind === "shot" || d.kind === "image" || d.kind === "video";
    });
    if (!shots.length) {
      setStatus("没有可生成的镜头/图/视频节点");
      return;
    }
    shots.forEach((n) => {
      useCanvasStore.getState().updateNodeData(n.id, {
        status: "generating",
        progress: 0,
        errorMessage: "",
      });
    });
    setGenerating(true);
    batchAbortRef.current = false;
    const batchCtrl = new AbortController();
    batchGenAbortRef.current = batchCtrl;
    let ok = 0;
    let skipped = 0;
    for (let i = 0; i < shots.length; i++) {
      if (batchAbortRef.current) {
        setStatus(`批量已中断：完成 ${ok}/${shots.length}`);
        break;
      }
      const n = shots[i];
      const d = n.data as NodeData;
      const label = (d as { title?: string }).title || n.id;
      if (d.kind === "video" && !videoModels.length) {
        skipped += 1;
        useCanvasStore.getState().updateNodeData(n.id, {
          status: "failed",
          errorMessage: "无可用生视频模型",
        });
        setStatus(`批量 ${i + 1}/${shots.length}：跳过视频「${label}」（无生视频模型）`);
        continue;
      }
      setStatus(
        `批量生成 ${i + 1}/${shots.length}：${label}${d.kind === "video" ? "（视频）" : ""}`,
      );
      setSelected(n.id);
      useCanvasStore.getState().updateNodeData(n.id, {
        status: "generating",
        progress: Math.round(((i + 1) / shots.length) * 100),
      });
      try {
        const res = await generateForNode(n, d, { signal: batchCtrl.signal });
        if (res.ok) {
          ok += 1;
          useCanvasStore.getState().updateNodeData(n.id, {
            status: "success",
            progress: 100,
            errorMessage: "",
          });
        } else if (res.message === "已取消") {
          // 中断按钮取消了在飞任务：回 idle，不计失败
          useCanvasStore.getState().updateNodeData(n.id, {
            status: "idle",
            progress: 0,
            errorMessage: "",
          });
        } else {
          useCanvasStore.getState().updateNodeData(n.id, {
            status: "failed",
            errorMessage: (res.message || "").slice(0, 200),
          });
        }
      } catch (e) {
        useCanvasStore.getState().updateNodeData(n.id, {
          status: "failed",
          errorMessage: String(e).slice(0, 200),
        });
      }
    }
    if (!batchAbortRef.current) {
      setStatus(
        `批量完成：成功 ${ok}/${shots.length}` +
          (skipped ? `，跳过视频 ${skipped}` : ""),
      );
      // 一键成片：只收集「本次批量生成」的成功节点媒体，拼成一条成片
      await tryConcatToFilm(shots.map((s) => s.id), ok);
    }
    batchGenAbortRef.current = null;
    setGenerating(false);
  };

  /** 成片闭环：把批量生成的成功结果（静帧图 + 真视频）拼成一条成片 */
  const tryConcatToFilm = async (shotIds: string[], okCount: number) => {
    if (okCount < 2) return; // 少于 2 段无法拼接
    const all = useCanvasStore.getState().nodes;
    const mediaItems: { url: string; title: string }[] = [];
    // 只收集本次批量生成的节点，且保持 shotIds 的时间链顺序
    for (const sid of shotIds) {
      const n = all.find((x) => x.id === sid);
      if (!n) continue;
      const d = n.data as NodeData;
      if ((d as { status?: string }).status !== "success") continue; // 跳过失败/未完成的
      const title = (d as { title?: string }).title || n.id;
      if (d.kind === "video" && (d as { videoUrl?: string }).videoUrl) {
        mediaItems.push({ url: (d as { videoUrl?: string }).videoUrl!, title });
      } else if (
        (d.kind === "shot" || d.kind === "image" || d.kind === "director" || d.kind === "panorama") &&
        (d as { imageUrl?: string }).imageUrl
      ) {
        mediaItems.push({ url: (d as { imageUrl?: string }).imageUrl!, title });
      }
    }
    if (mediaItems.length < 2) return;
    setStatus(`🧩 正在把 ${mediaItems.length} 段素材拼成一条成片…`);
    // 统一走 /host/still-video：图片转静帧视频，视频原样返回本地路径
    const paths = await imagesToStillVideos(
      mediaItems.map((m) => m.url),
      3,
    );
    if (paths.length < 2) {
      setStatus(`⚠️ 可拼接的有效素材不足（${paths.length} 段）`);
      return;
    }
    const cr = await concatVideos({ paths, transition_sec: 0.4 });
    if (cr.ok && (cr.output_path || cr.video_url)) {
      addStudioNode("video", {
        title: `一键成片（${cr.segment_count ?? paths.length} 段 · ${cr.total_duration?.toFixed(1) || "?"}s）`,
        prompt: mediaItems.map((m) => m.title).join(" → "),
        videoUrl: cr.video_url || cr.output_path,
      });
      setStatus(`✅ 成片完成：${cr.segment_count ?? paths.length} 段 → ${cr.total_duration?.toFixed(1) || "?"}s`);
    } else {
      setStatus(`拼接失败: ${cr.message || "未知错误"}（${paths.length} 段素材已就绪，可重试）`);
    }
  };

  const onSendToEditor = async () => {
    if (!selected || !selectedData) {
      setStatus("请先选中带图/视频的节点");
      return;
    }
    try {
      setStatus("正在发送到剪辑…");
      const title =
        ("title" in selectedData ? selectedData.title : "") ||
        `${selectedData.kind}_${selected.id}`;
      const link = nodeLink(selected.id, selectedData);

      if (selectedData.kind === "video" && selectedData.videoUrl) {
        const resp = await fetch(selectedData.videoUrl);
        const blob = await resp.blob();
        const msg = await sendBlobToEditor(blob, `${title}.mp4`, prefs, {
          title,
          duration_sec: Number(selectedData.duration) || 0,
          ...link,
        });
        setStatus(msg);
        return;
      }

      if ((selectedData.kind === "audio" || selectedData.kind === "music") && selectedData.audioUrl) {
        const resp = await fetch(selectedData.audioUrl);
        const blob = await resp.blob();
        const ext = blob.type.includes("mpeg") || blob.type.includes("mp3") ? "mp3" : "wav";
        const msg = await sendBlobToEditor(blob, `${title}.${ext}`, prefs, { title, ...link });
        setStatus(msg);
        return;
      }

      if (selectedData.kind === "digitalHuman") {
        if (selectedData.videoUrl) {
          const resp = await fetch(selectedData.videoUrl);
          const blob = await resp.blob();
          const msg = await sendBlobToEditor(blob, `${title}.mp4`, prefs, { title, ...link });
          setStatus(msg);
          return;
        }
        const parts: string[] = [];
        if (selectedData.audioUrl) {
          const resp = await fetch(selectedData.audioUrl);
          const blob = await resp.blob();
          const ext = blob.type.includes("mpeg") || blob.type.includes("mp3") ? "mp3" : "wav";
          parts.push(
            await sendBlobToEditor(blob, `${title}.${ext}`, prefs, { title: `${title}·配音`, ...link }),
          );
        }
        if (selectedData.imageUrl) {
          const blob = await dataUrlToBlob(selectedData.imageUrl);
          parts.push(
            await sendBlobToEditor(blob, `${title}.png`, prefs, { title: `${title}·形象`, ...link }),
          );
        }
        if (!parts.length) {
          setStatus("请先上传形象或生成配音");
          return;
        }
        setStatus(parts.join("；"));
        return;
      }

      const imageUrl = nodeImageUrl(selectedData);
      if (!imageUrl) {
        setStatus(
          selectedData.kind === "video"
            ? "视频节点还没有成片，请先生成"
            : "节点还没有图，请先生成",
        );
        return;
      }
      const blob = await dataUrlToBlob(imageUrl);
      const dur =
        selectedData.kind === "shot"
          ? Number(selectedData.duration) || 0
          : selectedData.kind === "video"
            ? Number(selectedData.duration) || 0
            : 0;
      const msg = await sendBlobToEditor(blob, `${title}.png`, prefs, {
        title,
        duration_sec: dur,
        ...link,
      });
      setStatus(msg);
    } catch (e) {
      setStatus(`发送失败: ${e}`);
    }
  };

  /**
   * 全部入轨 = 编排委托给 `editorIngress.ingestNodes`（Wave 0 #13 抽模块）。
   * 本函数只负责「拿到批量 job_id 就走后端快通道」，不新增按钮、不新增通道。
   * `lastBatchJobId` 由批量提交处写入，批量作业结束后仍在有效期内的才走后端。
   */
  const onSendAllToEditor = async () => {
    const batchOk = pickDoneIndices(lastBatchSegments).length > 0;
    await ingestNodes({ nodes, setStatus, setGenerating, prefs }, batchOk ? lastBatchJobId : null,
      batchOk ? lastBatchSegments : undefined);
  };

  /** 时间线回滚（Wave 0 #13 第 5 条）：交互编排在 `editorRollback`（App.tsx 已顶格），
   *  这里只注入依赖。唯一入口是「导入工程包直导时间线之后」那一刻 —— 用户最可能反悔时。 */
  const offerRollback = async () => {
    const { offerTimelineRollback } = await import("./editorRollback");
    await offerTimelineRollback({ setStatus, onExportZip: doExportZip });
  };

  /** 导出工程包（Wave 0 #13 抽成具名函数）：既作`onExportZip` prop，
   *  也供回滚编排当「先导出再回滚」的兜底建议。**定义在offerRollback 之前**避免 TDZ。 */
  const doExportZip = async () => {
    const { exportProjectZip, downloadBlob, fetchProjectTimeline } = await import("./projectZip");
    const b = getProjectBundle();
    // P1-4：导出时并入剪辑器完整时间线（可回滚/diff/直导）
    const timeline = await fetchProjectTimeline();
    const blob = await exportProjectZip({
      version: 1,
      dramaTitle: b.dramaTitle,
      episode: b.episode,
      nodes: b.nodes,
      edges: b.edges,
      stage3d: b.stage3d,
      timeline: timeline ?? undefined,
      savedAt: new Date().toISOString(),
    });
    downloadBlob(blob, `shiguang-canvas-${Date.now()}.zip`);
    setStatus(
      timeline
        ? `已导出工程 ZIP（含时间线 ${timeline.clip_count ?? timeline.clips.length} 片段）`
        : "已导出工程 ZIP（未取到时间线）",
    );
  };

  const onSyncModels = async () => {
    setStatus("同步模型池…");
    const msg = await syncModelPool();
    setStatus(msg);
    fetchPrefs().then(setPrefs);
    await refreshModels();
  };

  const onApplyPromptLibrary = useCallback(
    (item: PromptItem) => {
      const applyToSelected = () => {
        const sid = useCanvasStore.getState().selectedId;
        const node = useCanvasStore.getState().nodes.find((n) => n.id === sid);
        const data = node?.data as NodeData | undefined;
        if (!data) return false;
        if (data.kind === "prompt") {
          updateSelectedData({ text: item.prompt, title: item.title || data.title });
          return true;
        }
        if ("prompt" in data) {
          updateSelectedData({
            prompt: item.prompt,
            title: item.title || ("title" in data ? data.title : ""),
          });
          return true;
        }
        return false;
      };

      if (selected && selectedData) {
        if (applyToSelected()) {
          setStatus(`已应用提示词「${item.title}」到选中节点`);
          return;
        }
      }
      addNode("prompt");
      const sid = useCanvasStore.getState().selectedId;
      if (sid) {
        useCanvasStore.getState().updateSelectedData({
          text: item.prompt,
          title: item.title,
        });
      }
      setStatus(`已新建提示词节点：${item.title}`);
    },
    [selected, selectedData, updateSelectedData, addNode, setStatus],
  );

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
      setBreaking(false);
      // I2 补强：拉片铺完分镜后自动接「运行到此处」（runGraphWithConfirm 出 dry_run 计划并弹确认后再执行）。
      if (Array.isArray(res.shots) && res.shots.length > 0) {
        await runToHere();
      }
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
    // 同时取消在飞的异步生成任务（单节点 + 批量当前节点），后端任务一并取消
    genAbortRef.current?.abort();
    batchGenAbortRef.current?.abort();
    setStatus("正在中断批量…");
  };

  // V4.41.20：9 个生成/入轨回调注入 generateActions（hook 拆出到 generateActionsInjector.ts）
  useInjectGenerateActions(
    onGenerate, onCompareGenerate, onMultiAngleGenerate, onBatchGenerate,
    runToHere, onAbortBatch, onSendToEditor, onSendAllToEditor, onSyncModels,
  );

  /** 节点一键重试 — 由 NodeActionsContext 注入给各节点组件的 Shell */
  const retryNode = useCallback(async (nodeId: string) => {
    const node = useCanvasStore.getState().nodes.find((n) => n.id === nodeId);
    if (!node) {
      setStatus(`节点不存在（${nodeId}）`);
      return;
    }
    const data = node.data as NodeData;
    const kind = data.kind;
    if (
      kind !== "shot" && kind !== "image" && kind !== "video" &&
      kind !== "generator" && kind !== "audio" && kind !== "music" &&
      kind !== "text"
    ) {
      setStatus(`当前节点类型（${kind}）不支持重试生成`);
      return;
    }
    useCanvasStore.getState().setSelected(nodeId);
    useCanvasStore.getState().updateNodeData(nodeId, {
      status: "generating",
      progress: 0,
      errorMessage: "",
    });
    setGenerating(true);
    setStatus(`重试生成：${(data as { title?: string }).title || nodeId}…`);
    try {
      const { ok, message } = await generateForNode(node, data);
      useCanvasStore.getState().updateNodeData(nodeId, {
        status: ok ? "success" : "failed",
        progress: ok ? 100 : 0,
        errorMessage: ok ? "" : String(message || "生成失败").slice(0, 200),
      });
      setStatus(message);
    } catch (e) {
      const errMsg = String(e);
      useCanvasStore.getState().updateNodeData(nodeId, {
        status: "failed",
        errorMessage: errMsg.slice(0, 200),
      });
      setStatus(`重试异常: ${e}`);
    } finally {
      setGenerating(false);
    }
  }, []);

  return (
    <NodeActionsContext.Provider value={{ retryNode }}>
    <CanvasShell
      viewMode={viewMode}
      setViewMode={setViewMode}
      status={status}
      prefs={prefs}
      generating={generating}
      editorClipCount={editorClipCount}
      breaking={breaking}
            musicModels={musicModels}
      selectedMusicModelKey={selectedMusicModelKey}
      setSelectedMusicModelKey={setSelectedMusicModelKey}
      breakdownDraft={breakdownDraft}
      setBreakdownDraft={setBreakdownDraft}
      templates={templates}
      dramaTitle={dramaTitle}
      episode={episode}
      setMeta={setMeta}
      selectedData={selectedData}
      onSelectionChange={onSelectionChange}
      updateSelectedData={updateSelectedData}
      addNode={addNode}
      addRegistryNode={addRegistryNode}
      addStoryboardGrid={addStoryboardGrid}
      addThreeView={addThreeView}
      addVariants={addVariants}
      removeSelected={removeSelected}
      deleteEdge={deleteEdge}
      duplicateSelected={duplicateSelected}
      copySelected={copySelected}
      pasteClipboard={pasteClipboard}
      selectAll={selectAll}
      undoGraph={undoGraph}
      redoGraph={redoGraph}
      clearSelection={clearSelection}
      alignSelected={alignSelected}
      beginGraphEdit={beginGraphEdit}
      saveProject={saveProject}
      loadProject={loadProject}
      saveTemplate={saveTemplate}
      loadTemplate={loadTemplate}
      deleteTemplate={deleteTemplate}
      refreshTemplates={refreshTemplates}
      onGenerate={onGenerate}
      onCompareGenerate={onCompareGenerate}
      onMultiAngleGenerate={onMultiAngleGenerate}
      onExportSkill={onExportSkill}
      onImportSkill={onImportSkill}
      onSetPrimaryVideo={setPrimaryVideo}
      onBatchGenerate={onBatchGenerate}
      onRunToHere={runToHere}
      onAbortBatch={onAbortBatch}
      onSendToEditor={onSendToEditor}
      onSendAllToEditor={onSendAllToEditor}
      onSyncModels={onSyncModels}
      onApplyPromptLibrary={onApplyPromptLibrary}
      onBreakdown={onBreakdown}
      onExportStoryboard={onExportStoryboard}
      onInpaint={onInpaint}
      onSetPrimaryImage={setPrimaryImage}
      onGroupSelected={groupSelected}
      onExportZip={doExportZip}
      onImportZip={async (file) => {
        try {
          const { importProjectZip, pushTimelineToEditor } = await import("./projectZip");
          const bundle = await importProjectZip(file);
          loadProjectBundle(bundle);
          // P1-4：导入时若快照带时间线，提供直导剪辑器
          let pushed = false;
          if (bundle.timeline && Array.isArray(bundle.timeline.clips) && bundle.timeline.clips.length) {
            const push = window.confirm(
              `该工程快照包含 ${bundle.timeline.clips.length} 个时间线片段，是否一并直导剪辑器？`,
            );
            if (push) {
              const r = await pushTimelineToEditor(bundle.timeline.clips as Record<string, unknown>[]);
              setStatus(r.ok ? `时间线已直导剪辑器：${r.message}` : `直导失败：${r.message}`);
              pushed = r.ok;
            }
          }
          // Wave 0 #13 第 5 条（2026-10-15）：直导是**破坏性**的（write_clips 整体覆盖
          // 剪辑器时间线），后端在 import 里自动压了一条「导入前自动快照」，
          // 但前端原本没有回滚入口 ⇒ 这里在**用户最可能想反悔的时刻**给出。
          if (pushed) await offerRollback();
        } catch (e) {
          setStatus(`导入 ZIP 失败: ${e}`);
        }
      }}
      onApplyImageTool={async (tool) => {
        if (!selected || !selectedData) return;
        const url =
          selectedData.kind === "shot" || selectedData.kind === "image"
            ? selectedData.imageUrl
            : "";
        if (!url) {
          setStatus("请先选中带图节点");
          return;
        }
        try {
          const tools = await import("./imageTools");
          if (tool === "crop916") {
            setNodeImage(selected.id, await tools.cropCenter(url, 9, 16));
            setStatus("已裁剪 9:16");
          } else if (tool === "split2" || tool === "split3") {
            const parts = await tools.splitGrid(url, tool === "split2" ? 2 : 3);
            for (const p of parts) {
              addStudioNode("image", {
                title: `拆分 ${tool}`,
                prompt: ("prompt" in selectedData ? selectedData.prompt : "") || "",
                imageUrl: p,
              });
            }
            setStatus(`已拆分 ${parts.length} 张`);
          } else if (tool === "upscale") {
            setNodeImage(selected.id, await tools.upscaleLocal(url, 2));
            setStatus("已本地放大 2×（非神经网络超分）");
          } else if (tool === "rotate90") {
            setNodeImage(selected.id, await tools.rotateImage(url, 90));
            setStatus("已旋转 90°");
          }
        } catch (e) {
          setStatus(`图工具失败: ${e}`);
        }
      }}
      onSetNodeAudio={(dataUrl) => {
        if (selected) setNodeAudio(selected.id, dataUrl);
      }}
      onSendStudioToCanvas={(payload) => {
        if (payload.kind === "image") {
          addStudioNode("image", {
            title: payload.title,
            prompt: payload.prompt || "",
            imageUrl: payload.imageUrl,
          });
        } else if (payload.kind === "video") {
          addStudioNode("video", {
            title: payload.title,
            prompt: payload.prompt || "",
            videoUrl: payload.videoUrl,
            posterUrl: payload.posterUrl,
          });
        } else {
          addStudioNode("prompt", {
            title: payload.title,
            text: payload.text || payload.prompt || "",
          });
        }
      }}
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
              addCaptureToCanvas(dataUrl, meta.cameraName, {
                focalLength: meta.focalLength,
                shotSize: meta.shotSize,
                aspect: meta.aspect,
                aperture: meta.aperture,
              });
            }}
            onCaptureActorViews={(views, actorName) => {
              const baseMeta = { focalLength: Infinity, aperture: 1, aspect: "9:16" };
              addCaptureToCanvas(views.front, `${actorName} · 正面`, { ...baseMeta, shotSize: "正视图" });
              addCaptureToCanvas(views.side, `${actorName} · 侧面`, { ...baseMeta, shotSize: "侧视图" });
              addCaptureToCanvas(views.back, `${actorName} · 背面`, { ...baseMeta, shotSize: "背视图" });
            }}
            onExportFirstLast={async (firstFrame, lastFrame, meta) => {
              const { channel_id, model } = resolveModel(selectedVideoModelKey);
              if (!channel_id || !model) {
                setStatus("请先在模型池中选择可用的视频模型");
                return;
              }
              const charCtx = [
                prefs.character_name && `角色「${prefs.character_name}」`,
                prefs.character_prompt && prefs.character_prompt,
                meta.referenceActor && `参考角色 ${meta.referenceActor}`,
              ]
                .filter(Boolean)
                .join("，");
              const defaultPrompt =
                `${charCtx ? charCtx + "。" : ""}${meta.cameraName}，${meta.totalPoints} 个路径点，首尾帧运镜插值，电影感构图`;
              setGenerating(true);
              try {
                const hintParts = [meta.resolution ? meta.resolution : ""];
                if (meta.referenceImage) hintParts.push(`含参考图「${meta.referenceActor || "角色"}」`);
                if (meta.referenceVideoUrl) hintParts.push("含动作参考视频（motion-ref）");
                setStatus(`正在通过 ${model} 生成首尾帧视频…${hintParts.filter(Boolean).join(" · ")}`);
                const res = await generateVideoViaHost({
                  prompt: defaultPrompt,
                  model,
                  channel_id,
                  duration: 5,
                  first_frame: firstFrame,
                  last_frame: lastFrame,
                  reference_image: meta.referenceImage || "",
                  reference_video: meta.referenceVideoUrl || "",
                });
                if (res.ok && res.video_url) {
                  addStudioNode("video", {
                    title: `${meta.cameraName} · 首尾帧视频`,
                    prompt: defaultPrompt,
                    videoUrl: res.video_url,
                  });
                  setStatus(`✅ 首尾帧视频已生成，已加到画布（${res.channel_name || ""} / ${model}）`);
                } else {
                  setStatus(`❌ 生视频失败：${res.message || "未知错误"}`);
                }
              } catch (e) {
                setStatus(`❌ 首尾帧生视频异常：${(e as Error).message}`);
              } finally {
                setGenerating(false);
              }
            }}
            onExportBatch={async (segments) => {
              const { channel_id, model } = resolveModel(selectedVideoModelKey);
              if (!channel_id || !model) {
                setStatus("请先在模型池中选择可用的视频模型");
                return;
              }
              setGenerating(true);
              try {
                setStatus(`🎬 提交 ${segments.length} 个分镜到 ${model} 批量生成…`);
                const res = await batchGenerateVideos({
                  segments: segments.map((s) => ({
                    cameraName: s.cameraName,
                    prompt: s.promptHint,
                    duration: 5,
                    firstFrame: s.firstFrame,
                    lastFrame: s.lastFrame,
                    referenceImage: s.referenceImage,
                  })),
                  channel_id,
                  model,
                  auto_concat: false,
                });
                if (!res.ok || !res.job_id) {
                  setStatus(`❌ 批量提交失败: ${res.message || "未知错误"}`);
                  return;
                }
                const jobId = res.job_id;
                setStatus(`✅ 已提交批量任务 ${jobId}（${segments.length} 段），等待生成…`);
                // Wave 0 #13：记下 job_id 与分段清单，「全部入轨」按钮据此走后端快通道
                // （逐段直接 emit_canvas_to_editor，不经前端 fetch blob 中转）。
                setLastBatchJobId(jobId);
                setLastBatchSegments(undefined);
                // 轮询进度
                const poll = async () => {
                  for (let i = 0; i < 200; i++) {
                    await new Promise((r) => setTimeout(r, 8000));
                    const st = await getBatchStatus(jobId);
                    if (!st.ok) continue;
                    const done = st.done || 0;
                    const failed = st.failed || 0;
                    const total = st.total || segments.length;
                    setStatus(`🎬 批量进度 ${done + failed}/${total}（成功 ${done}，失败 ${failed}）${failed > 0 ? " ⚠️" : ""}`);
                    if (st.status === "done" || st.status === "failed") {
                      // Wave 0 #13：留存分段清单供「全部入轨」走快通道
                      setLastBatchSegments(st.segments);
                      // 成功后自动拼接
                      if (done >= 2) {
                        setStatus(`🧩 开始 FFmpeg 拼接 ${done} 个成功分段…`);
                        const cr = await concatVideos({ job_id: jobId, transition_sec: 0.4 });
                        if (cr.ok && cr.output_path) {
                          addStudioNode("video", {
                            title: `批量成片（${done} 段 · ${cr.total_duration?.toFixed(1) || "?"}s）`,
                            prompt: segments.map((s) => s.cameraName).join(" → "),
                            videoUrl: cr.video_url || cr.output_path,
                          });
                          setStatus(`✅ 批量成片已生成：${cr.segment_count} 段 → ${cr.total_duration?.toFixed(1) || "?"}s`);
                        } else {
                          setStatus(`拼接失败: ${cr.message || "未知错误"}`);
                          // 至少把成功的分段加到画布
                          if (st.segments) {
                            st.segments.forEach((s) => {
                              if (s.status === "done" && s.video_url) {
                                addStudioNode("video", {
                                  title: s.camera_name,
                                  videoUrl: s.video_url,
                                });
                              }
                            });
                          }
                        }
                      } else if (done === 1) {
                        const seg = st.segments?.find((s) => s.status === "done");
                        if (seg?.video_url) {
                          addStudioNode("video", {
                            title: seg.camera_name,
                            videoUrl: seg.video_url,
                          });
                        }
                        setStatus(`⚠️ 仅 1 段成功，无法拼接，已单独加到画布`);
                      } else {
                        setStatus(`❌ 全部失败，无可用分段`);
                      }
                      break;
                    }
                  }
                };
                poll();
              } catch (e) {
                setStatus(`❌ 批量异常: ${(e as Error).message}`);
              } finally {
                setGenerating(false);
              }
            }}
          />
        </Suspense>
      }
    />
    {/* 画布浮层簇（桌宠 + 输出历史）：兄弟位置 ⇒ 零解冻；App 顶到规模上限，故收成一个入口 */}
    <CanvasOverlays />
    </NodeActionsContext.Provider>
  );
}
