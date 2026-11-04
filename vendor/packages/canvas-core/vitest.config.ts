import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // ★ 沿用宿主壳 2026-10-06 结论：**关掉文件级并行**（并行收集在低速盘会漏文件，
    //   总数 170/180/188 漂移过）；串行后总数稳定，门禁数字才可信。
    fileParallelism: false,
    globals: false,
  },
});
