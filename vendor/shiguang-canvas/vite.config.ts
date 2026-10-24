import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { rmSync } from "node:fs";
import path from "node:path";

// §13.3 波次1-3：dist 混装运行时数据瘦身 —— public/prompts/bundled（约 8MB 社区提示词 JSON）
// 是 promptLibrary 运行时 fetch 的静态数据，非 import 依赖，每次构建整目录复制纯属浪费。
// 构建后从 dist 删除；读取路径不受影响：
//   Qt 静态服务器 → _SPAHandler 兜底 public/；vite dev → 直接 serve public；
//   preview / Tauri 包 → fallbackUrl 远程 + bridge /host/prompt-bundled 读仓库 public。
// 保留 flat prompts/shiguang-*.json（GEUPACK 门禁校验 dist 一致性）与 models/*.glb（Tauri 无兜底）。
function pruneBundledPrompts(): Plugin {
  let outDir = "";
  return {
    name: "prune-bundled-prompts",
    apply: "build",
    configResolved(cfg) {
      outDir = path.resolve(cfg.root, cfg.build.outDir);
    },
    closeBundle() {
      rmSync(path.join(outDir, "prompts", "bundled"), { recursive: true, force: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), pruneBundledPrompts()],
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
