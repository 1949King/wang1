/**
 * CanvasToolbar — 画布右下角浮动工具条（tenney95 风格移植）
 *
 * 功能：网格显隐切换、连线样式切换（直线/曲线）、缩放滑块
 * 缩放通过 React Flow useStore + useReactFlow 直接操作，其他状态走自研 useCanvasStore
 */
import { memo, useCallback } from "react";
import { useReactFlow, useStore, type ReactFlowState } from "@xyflow/react";
import { useCanvasStore } from "../../store";

const selectZoomPercent = (state: ReactFlowState) =>
  Math.round(state.transform[2] * 100);

function ZoomControl() {
  const zoomPercent = useStore(selectZoomPercent);
  const { zoomTo, fitView } = useReactFlow();

  const handleZoomChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      zoomTo(Number(e.target.value) / 100);
    },
    [zoomTo],
  );

  return (
    <div className="canvas-toolbar-zoom">
      <button
        type="button"
        className="canvas-toolbar-btn"
        title="缩小"
        onClick={() => zoomTo(Math.max(0.15, zoomPercent / 100 - 0.1))}
      >
        −
      </button>
      <input
        type="range"
        min="10"
        max="200"
        value={zoomPercent}
        onChange={handleZoomChange}
        aria-label="画布缩放比例"
        className="canvas-toolbar-slider"
      />
      <span className="canvas-toolbar-pct" title="缩放百分比（点击 fitView ）">
        {zoomPercent}%
      </span>
      <button
        type="button"
        className="canvas-toolbar-btn"
        title="放大"
        onClick={() => zoomTo(Math.min(2.5, zoomPercent / 100 + 0.1))}
      >
        +
      </button>
      <button
        type="button"
        className="canvas-toolbar-btn fit-btn"
        title="适配全部节点（F）"
        onClick={() => fitView({ padding: 0.18, duration: 220 })}
      >
        ⤢
      </button>
    </div>
  );
}

/** 自定义 SVG 图标组件，避免外部依赖 */
const GridIcon = ({ active }: { active: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={active ? 2 : 1.5} aria-hidden>
    <circle cx="5" cy="5" r="1.5" />
    <circle cx="12" cy="5" r="1.5" />
    <circle cx="19" cy="5" r="1.5" />
    <circle cx="5" cy="12" r="1.5" />
    <circle cx="12" cy="12" r="1.5" />
    <circle cx="19" cy="12" r="1.5" />
    <circle cx="5" cy="19" r="1.5" />
    <circle cx="12" cy="19" r="1.5" />
    <circle cx="19" cy="19" r="1.5" />
  </svg>
);

const CurveIcon = ({ active }: { active: boolean }) =>
  active ? (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden>
      <path d="M4 20 Q12 8 20 4" />
    </svg>
  ) : (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden>
      <path d="M4 20 L10 20 L10 10 L20 4" />
    </svg>
  );

const SnapIcon = ({ active }: { active: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={active ? 2 : 1.5} strokeLinecap="round" aria-hidden>
    <path d="M4 4h4v4H4zM10 4h4v4h-4zM16 4h4v4h-4zM4 10h4v4H4zM10 10h4v4h-4zM16 10h4v4h-4zM4 16h4v4H4zM10 16h4v4h-4zM16 16h4v4h-4z" />
  </svg>
);

/** 磁吸图标 — U 形磁铁 */
const MagneticIcon = ({ active }: { active: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={active ? 2 : 1.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M6 4v8a6 6 0 0 0 12 0V4" />
    <path d="M6 4h4v4H6zM14 4h4v4h-4z" fill={active ? "currentColor" : "none"} />
  </svg>
);

export default function CanvasToolbar() {
  const showGrid = useCanvasStore((s) => s.showGrid);
  const smoothLine = useCanvasStore((s) => s.smoothLine);
  const magneticMode = useCanvasStore((s) => s.magneticMode);
  const setShowGrid = useCanvasStore((s) => s.setShowGrid);
  const setSmoothLine = useCanvasStore((s) => s.setSmoothLine);
  const setMagneticMode = useCanvasStore((s) => s.setMagneticMode);

  // snapToGrid 状态走 CanvasShell 本地 state，通过 eventBus 或回调同步
  // 这里只读 localStorage 兜底
  const snapGrid = (() => {
    try { return localStorage.getItem("shiguang-canvas:snap-grid") !== "0"; } catch { return true; }
  })();
  const setSnapGrid = (v: boolean) => {
    try { localStorage.setItem("shiguang-canvas:snap-grid", v ? "1" : "0"); } catch { /* */ }
    // 触发 window event 通知 CanvasShell 更新
    window.dispatchEvent(new CustomEvent("shiguang:snap-grid-change", { detail: v }));
  };

  return (
    <div className="canvas-toolbar">
      <button
        type="button"
        className={`canvas-toolbar-icon${showGrid ? " active" : ""}`}
        title={showGrid ? "隐藏背景网格" : "显示背景网格"}
        onClick={() => setShowGrid(!showGrid)}
      >
        <GridIcon active={showGrid} />
      </button>
      <button
        type="button"
        className={`canvas-toolbar-icon${smoothLine ? " active" : ""}`}
        title={smoothLine ? "切换为直角连线" : "切换为曲线连线"}
        onClick={() => setSmoothLine(!smoothLine)}
      >
        <CurveIcon active={smoothLine} />
      </button>
      <button
        type="button"
        className={`canvas-toolbar-icon${snapGrid ? " active" : ""}`}
        title={snapGrid ? "关闭网格吸附" : "开启网格吸附"}
        onClick={() => setSnapGrid(!snapGrid)}
      >
        <SnapIcon active={snapGrid} />
      </button>
      <button
        type="button"
        className={`canvas-toolbar-icon${magneticMode ? " active" : ""}`}
        title={magneticMode ? "关闭磁吸模式" : "开启磁吸模式 — 拖拽节点靠近其他节点时自动吸附"}
        onClick={() => setMagneticMode(!magneticMode)}
      >
        <MagneticIcon active={magneticMode} />
      </button>
      <div className="canvas-toolbar-sep" />
      <ZoomControl />
    </div>
  );
}

// 保留 memo 导出
export const MemoizedCanvasToolbar = memo(CanvasToolbar);
