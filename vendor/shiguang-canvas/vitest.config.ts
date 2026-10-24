import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    // ★ 2026-10-06：**关掉文件级并行**。实测（沙箱/低速盘环境）并行跑时收集会**漏文件**：
    //   同一份代码连续三次跑出 170 / 180 / 188 三种总数，一度被误判成"测试丢了"。
    //   关掉后总数稳定且与逐文件求和一致 ⇒ 门禁数字才可信（这里的用例都是纯逻辑，串行只慢几秒）。
    fileParallelism: false,
    // 纯函数模块测试不依赖 DOM；如需 DOM 组件测试可另配 environment
    globals: false,
  },
});
