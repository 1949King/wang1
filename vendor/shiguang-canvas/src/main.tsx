import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// P0-1 抽包 Phase 1（2026-10-18）：画布真源已迁 @shiguang/libtv（vendor/packages/libtv），
// 宿主壳只保留入口；改导演台画布只能改 packages/libtv，禁止往宿主复制源码。
import App from "@shiguang/libtv/App";
import { AppErrorBoundary } from "@shiguang/libtv/AppErrorBoundary";
import { initCanvasBackground } from "@shiguang/libtv/canvasBackgrounds";
import "@shiguang/libtv/styles.css";

// V4.43.2：画布背景预设（移植自 AI-Canvas-tauri backgroundOptions.ts）
// 注入样式 + 应用本地背景 + 按 revision 轮询宿主 /host/canvas-settings
initCanvasBackground();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
