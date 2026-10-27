/**
 * GeneratePanel.tsx — V4.41.20「生成/入轨」浮动面板。
 *
 * 从 CanvasShell 左侧 sidebar 深处挪出，与 OutputHistoryPanel / LightingPanel /
 * DirectorPanel / GalleryPanel 同架构（useWindowPanel 拖动 + focus + minimize）。
 *
 * 内容 = 原 sidebar 「生成/入轨」details 块：4 个模型选择器（生图 / 生视频 /
 * 对比 + 对比视频）+ 6 个生成按钮（生成选中 / 双模型对比 / 多角度预览 / 批量 /
 * 运行到此处 / 中断）+ 3 个入轨按钮（入轨 / 全部入轨 / 同步模型池）。
 *
 * 模型列表与选择状态统一放在 generationModels store（App.tsx 与浮窗共用）：
 * 面板改了选中模型，真实生成立即使用同一 key；模型池同步也会同时刷新两边。
 * 9 个生成/入轨 callback 仍通过 generateActions store 注入，避免多层 props。
 */
import { useMemo } from "react";

import { useCanvasStore, type NodeData } from "./store";
import { isGenerateActionsReady, useGenerateActionsStore } from "./generateActions";
import { MODEL_STORAGE_KEYS, useGenerationModelStore } from "./generationModels";
import { useWindowPanel } from "./hooks/useWindowPanel";
import ModelSelector from "./components/canvas/ModelSelector";
import "./generatePanel.css";

export default function GeneratePanel({ onClose }: { onClose: () => void }) {
  const win = useWindowPanel("generate");
  const selectedId = useCanvasStore((s) => s.selectedId);
  const selectedData = useCanvasStore((s) =>
    s.nodes.find((n) => n.id === s.selectedId)?.data as NodeData | undefined,
  );
  // 「生成中」派生：busyStatus 已有节点级 batchQueue state（useCanvasStore 取 isGenerating）；
  // 这里偷懒——读 CanvasShell 持久化的生成中 flag。最简方案是 useCanvasStore 取 batchQueue.length。
  const generating = useCanvasStore((s) => (s as any).batchQueue?.length > 0);
  const actions = useGenerateActionsStore((s) => s.actions);
  const ready = isGenerateActionsReady(actions);

  /* 模型列表与选择状态：与 App 真实生成共用同一个 store */
  const imageModels = useGenerationModelStore((s) => s.imageModels);
  const videoModels = useGenerationModelStore((s) => s.videoModels);
  const audioModels = useGenerationModelStore((s) => s.audioModels);
  const selectedModelKey = useGenerationModelStore((s) => s.selectedModelKey);
  const selectedVideoModelKey = useGenerationModelStore((s) => s.selectedVideoModelKey);
  const compareModelKey = useGenerationModelStore((s) => s.compareModelKey);
  const compareVideoModelKey = useGenerationModelStore((s) => s.compareVideoModelKey);
  const setSelectedModelKey = useGenerationModelStore((s) => s.setSelectedModelKey);
  const setSelectedVideoModelKey = useGenerationModelStore((s) => s.setSelectedVideoModelKey);
  const setCompareModelKey = useGenerationModelStore((s) => s.setCompareModelKey);
  const setCompareVideoModelKey = useGenerationModelStore((s) => s.setCompareVideoModelKey);

  const primaryBtnLabel = useMemo(() => {
    if (generating) return "生成中…";
    if (selectedData?.kind === "video") return "生成选中视频";
    if (selectedData?.kind === "digitalHuman") return "生成配音";
    return "生成选中";
  }, [generating, selectedData?.kind]);

  const compareDisabled =
    generating ||
    (selectedData?.kind === "video"
      ? videoModels.length < 2 || !compareVideoModelKey
      : selectedData?.kind === "shot" || selectedData?.kind === "image"
        ? imageModels.length < 2 || !compareModelKey
        : true);

  return (
    <div
      className="gen-panel"
      ref={win.panelRef}
      style={win.style}
      onPointerDown={win.focusPanel}
    >
      <header className="gen-head" onPointerDown={win.startDrag}>
        <span className="gen-ico">🚀</span>
        <span className="gen-title">生成/入轨</span>
        <span className="gen-sub">
          {imageModels.length} 图 / {videoModels.length} 视频 / {audioModels.length} TTS
        </span>
        <span className="gen-spacer" />
        <button type="button" className="gen-min" onClick={win.minimize} title="最小化到任务栏">
          —
        </button>
        <button type="button" className="gen-close" onClick={onClose} title="关闭面板">
          ×
        </button>
      </header>

      <div className="gen-body">
        {!ready ? (
          <p className="muted" style={{ fontSize: 11, margin: "0 0 8px" }}>
            画布正在初始化回调，1 秒后自动可用…
          </p>
        ) : null}

        <div className="field">
          <label>生图模型</label>
          <ModelSelector
            models={imageModels}
            value={selectedModelKey}
            onChange={setSelectedModelKey}
            placeholder={imageModels.length === 0 ? "请先同步模型池" : "选择生图模型"}
            disabled={imageModels.length === 0}
            persistKey={MODEL_STORAGE_KEYS.image}
          />
        </div>
        <div className="field">
          <label>生视频模型</label>
          <ModelSelector
            models={videoModels}
            value={selectedVideoModelKey}
            onChange={setSelectedVideoModelKey}
            placeholder={videoModels.length === 0 ? "无视频模型" : "选择视频模型"}
            disabled={videoModels.length === 0}
            persistKey={MODEL_STORAGE_KEYS.video}
          />
        </div>
        <div className="field">
          <label>TTS 模型</label>
          <ModelSelector
            models={audioModels}
            value=""
            onChange={() => undefined}
            placeholder={audioModels.length === 0 ? "无 TTS 模型（走本地 edge-tts 降级）" : "TTS 模型选择见「AI 模型管理」"}
            disabled
            persistKey="shiguang-canvas:model:audio"
          />
        </div>
        <div className="field">
          <label>对比模型（TapNow 式 A/B）</label>
          <select value={compareModelKey} onChange={(e) => setCompareModelKey(e.target.value)}>
            {imageModels.length < 2 ? (
              <option value="">需至少 2 个生图模型</option>
            ) : (
              imageModels.map((m) => (
                <option key={`cmp_${m.channel_id}::${m.model}`} value={`${m.channel_id}::${m.model}`}>
                  {m.label}
                </option>
              ))
            )}
          </select>
        </div>
        <div className="field">
          <label>对比视频模型</label>
          <select value={compareVideoModelKey} onChange={(e) => setCompareVideoModelKey(e.target.value)}>
            {videoModels.length < 2 ? (
              <option value="">需至少 2 个视频模型</option>
            ) : (
              videoModels.map((m) => (
                <option key={`vcmp_${m.channel_id}::${m.model}`} value={`${m.channel_id}::${m.model}`}>
                  {m.label}
                </option>
              ))
            )}
          </select>
        </div>

        <button className="btn primary" onClick={() => actions.onGenerate?.()} disabled={!ready || generating}>
          {primaryBtnLabel}
        </button>
        <button
          className="btn"
          onClick={() => actions.onCompareGenerate?.()}
          disabled={!ready || compareDisabled}
        >
          双模型对比
        </button>
        <button
          className="btn"
          onClick={() => actions.onMultiAngleGenerate?.()}
          disabled={!ready || generating || selectedData?.kind !== "shot"}
        >
          多角度预览
        </button>
        <button className="btn" onClick={() => actions.onBatchGenerate?.()} disabled={!ready || generating}>
          批量生成
        </button>
        <button
          className="btn"
          onClick={() => actions.runToHere?.()}
          disabled={!ready || generating}
          title="先出执行计划（不消耗额度），确认后按依赖顺序整图执行；Ctrl+Shift+Enter"
        >
          运行到此处
        </button>
        {generating ? (
          <button className="btn" onClick={() => actions.onAbortBatch?.()} disabled={!ready}>
            中断
          </button>
        ) : null}

        <div className="btn-row">
          <button className="btn" onClick={() => actions.onSendToEditor?.()} disabled={!ready}>
            入轨
          </button>
          <button className="btn" onClick={() => actions.onSendAllToEditor?.()} disabled={!ready || generating}>
            全部入轨
          </button>
        </div>
        <button className="btn teal" onClick={() => actions.onSyncModels?.()} disabled={!ready}>
          同步模型池
        </button>
      </div>
    </div>
  );
}