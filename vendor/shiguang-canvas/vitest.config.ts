import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // 纯函数模块测试不依赖 DOM；如需 DOM 组件测试可另配 environment
    globals: false,
  },
});
