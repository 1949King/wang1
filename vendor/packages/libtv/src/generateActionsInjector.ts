/**
 * generateActionsInjector.ts — V4.41.20 把 9 个生成/入轨回调注入 store 的 hook。
 *
 * 设计：
 *  - 9 个回调随 App render 重建（模型 key 等状态在闭包里），因此依赖变化必须
 *    重新注入；只挂载时注入一次会一直调用首次 render 的旧闭包。
 *  - 9 个参数直接传（不用对象），让 App.tsx 那侧 1 行调用，省行数；
 *  - store 更新只通知浮窗订阅者，不会反向触发 App，因此不会形成渲染环。
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
    // 回调闭包包含选中模型/节点等状态，必须随引用变化重新注入
  }, [
    onGenerate,
    onCompareGenerate,
    onMultiAngleGenerate,
    onBatchGenerate,
    runToHere,
    onAbortBatch,
    onSendToEditor,
    onSendAllToEditor,
    onSyncModels,
  ]);
}