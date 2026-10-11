import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { initCanvasBackground } from "./canvasBackgrounds";
import "./styles.css";

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
