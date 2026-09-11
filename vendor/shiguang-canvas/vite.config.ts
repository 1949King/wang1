import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { host: "127.0.0.1", port: 3010, strictPort: true },
  preview: { host: "127.0.0.1", port: 3010, strictPort: true },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // bridge.ts 含 Tauri 动态 import("@tauri-apps/api/core")（仅 Tauri 宿主运行时触发，
    // Qt WebEngine 宿主 isTauri 恒 false 不会执行）。真源未装 @tauri-apps/api，
    // 标为 external 让其作为运行时外部模块，避免 Rollup 构建期解析失败。
    rollupOptions: { external: ["@tauri-apps/api/core"] },
  },
});
