/**
 * generateActionsInjector.ts — V4.41.20 把 9 个生成/入轨回调注入 store 的 hook。
 *
 * 设计：
 *  - App.tsx 里这 9 个 onGenerate/onBatchGenerate/... 都是 const 声明（每次 render
 *    同一引用），所以挂载时注入一次即可，后续不必重注入；
 *  - 9 个参数直接传（不用对象），让 App.tsx 那侧 1 行调用，省行数；
 *  - store 端用 setActions 写一次，后续无需再触发——订阅者读 store 拿到稳定引用。
 */
import { useEffect } from "react";
import { useGenerateActionsStore } from "./generateActions";

export function useInjectGenerateActions(
  onGenerate: () => void,
  onCompareGenerate: () => void,
  onMultiAngleGenerate: () => void,
  onBatchGenerate: () => void,
  runToHere: () => void,
  onAbortBatch: () => void,
  onSendToEditor: () => void,
  onSendAllToEditor: () => void,
  onSyncModels: () => void,
): void {
  useEffect(() => {
    useGenerateActionsStore.getState().setActions({
      onGenerate,
      onCompareGenerate,
      onMultiAngleGenerate,
      onBatchGenerate,
      runToHere,
      onAbortBatch,
      onSendToEditor,
      onSendAllToEditor,
      onSyncModels,
    });
    // 9 个 callback 在 App.tsx 都是 const，同一引用；挂载时一次性注入
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}