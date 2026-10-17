/**
 * generateActions.ts — V4.41.20 生成/入轨浮动面板的 callback 注入层。
 *
 * 为什么需要它
 * ============
 * 原来「生成/入轨」面板在 CanvasShell 内部，9 个回调（onGenerate / onBatchGenerate /
 * onCompareGenerate / onMultiAngleGenerate / runToHere / onAbortBatch / onSendToEditor /
 * onSendAllToEditor / onSyncModels）都是 CanvasShell 的 props，从 App.tsx 透传。
 *
 * 现在面板要挪出去做浮动面板（GeneratePanel.tsx），但不让 App.tsx → CanvasShell →
 * CanvasOverlays → GeneratePanel 透传 9 个 props（链路太长、CanvasShell 已在冻结区）。
 *
 * 解法：App.tsx 在 useEffect 里把这 9 个回调注入到这个 store；GeneratePanel 从 store
 * 里 dispatch。回调未注入时（早期 mount）按钮 disabled，不崩。
 *
 * 这是 zustand 标准用法（actions 注入），与 toolboxStore 的「toggle 是方法」一致。
 */
import { create } from "zustand";

export interface GenerateActions {
  onGenerate: () => void;
  onCompareGenerate: () => void;
  onMultiAngleGenerate: () => void;
  onBatchGenerate: () => void;
  runToHere: () => void;
  onAbortBatch: () => void;
  onSendToEditor: () => void;
  onSendAllToEditor: () => void;
  onSyncModels: () => void;
}

export const useGenerateActionsStore = create<{
  actions: Partial<GenerateActions>;
  setActions: (a: Partial<GenerateActions>) => void;
}>((set) => ({
  actions: {},
  setActions: (a) => set({ actions: a }),
}));

/** 全部回调都已注入（用于按钮灰度） */
export function isGenerateActionsReady(a: Partial<GenerateActions>): a is GenerateActions {
  return Boolean(
    a.onGenerate && a.onCompareGenerate && a.onMultiAngleGenerate && a.onBatchGenerate &&
    a.runToHere && a.onAbortBatch && a.onSendToEditor && a.onSendAllToEditor && a.onSyncModels,
  );
}