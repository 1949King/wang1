import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// P0-1 抽包 Phase 1（2026-10-18）：画布真源已迁 @shiguang/canvas-core（vendor/packages/canvas-core），
// 宿主壳只保留入口；改导演台画布只能改 packages/canvas-core，禁止往宿主复制源码。
import App from "@shiguang/canvas-core/App";
import { AppErrorBoundary } from "@shiguang/canvas-core/AppErrorBoundary";
import { initCanvasBackground } from "@shiguang/canvas-core/canvasBackgrounds";
import { installChunkLoadGuard } from "@shiguang/canvas-core/chunkLoadGuard";
import "@shiguang/canvas-core/styles.css";

// V4.43.2：画布背景预设（移植自 AI-Canvas-tauri backgroundOptions.ts）
// 注入样式 + 应用本地背景 + 按 revision 轮询宿主 /host/canvas-settings
initCanvasBackground();

// 必须早于 render 安装：dist 换代时分包 import 会 404，
// 该错误是**异步**的，AppErrorBoundary 抓不到 ⇒ 整页黑屏（2026-10-25 实证）。
installChunkLoadGuard();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
