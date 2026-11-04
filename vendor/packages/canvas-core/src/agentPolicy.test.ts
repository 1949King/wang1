/**
 * agentPolicy.test.ts — Agent 工具策略**派生化**回归（刀 A4，2026-10-05）。
 *
 * 锁死三件事：
 *  ① **真源在后端**：前端不再自持映射，`primeAgentPolicy()` 拉 `/host/agent-policy` 后按下发值判定；
 *  ② **保守兜底**：未就绪 / 未知工具 ⇒ 一律「写 + 付费 + 危险」⇒ 协作必问、Plan 必拦。
 *     **绝不静默放行未知工具**（这正是「两个真源」时代最危险的失效模式）；
 *  ③ **失败不炸**：拉取失败只降级为保守兜底，不抛异常、不阻塞画布。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./bridge", () => ({
  BRIDGE: "http://test-bridge",
  bridgeToken: () => "test-token",
}));

import {
  _resetAgentPolicyForTest,
  decideCanvasTool,
  getAgentPolicySnapshot,
  isWriteEffect,
  lookupCanvasTool,
  primeAgentPolicy,
} from "./agentPolicy";

const PAYLOAD = {
  ok: true,
  table_hash: "abc123",
  tools: {
    addNode: { effect: "canvas_write", paid: false, danger: "safe", desc: "新增节点" },
    queryNodes: { effect: "read", paid: false, danger: "safe", desc: "查询" },
    deleteNode: { effect: "canvas_write", paid: false, danger: "dangerous", desc: "删除节点" },
    runGenerate: { effect: "media_write", paid: true, danger: "safe", desc: "生成" },
  },
};

function mockFetch(impl: (url: string) => any) {
  (globalThis as any).fetch = vi.fn(async (url: string) => impl(String(url)));
}

describe("agentPolicy 未就绪时（保守兜底）", () => {
  beforeEach(() => {
    _resetAgentPolicyForTest();
    mockFetch(() => {
      throw new Error("should not be called");
    });
  });

  it("未知工具按「写+付费+危险」处理，不静默放行", () => {
    const p = lookupCanvasTool("someBrandNewTool");
    expect(p.effect).toBe("media_write");
    expect(p.paid).toBe(true);
    expect(p.danger).toBe("dangerous");
  });

  it("协作模式下未知工具必须确认", () => {
    expect(decideCanvasTool("someBrandNewTool", "collaborative").action).toBe(
      "require_approval",
    );
  });

  it("Plan 模式下未知工具必须拦截", () => {
    expect(decideCanvasTool("someBrandNewTool", "plan").action).toBe("deny");
  });

  it("已知工具在未就绪时也走保守（不猜测）", () => {
    // addNode 实际是 canvas_write/safe，但策略没拉下来时**不许猜**
    expect(lookupCanvasTool("addNode").danger).toBe("dangerous");
  });
});

describe("agentPolicy 拉取成功后", () => {
  beforeEach(() => {
    _resetAgentPolicyForTest();
    mockFetch(() => ({ ok: true, json: async () => PAYLOAD }));
  });

  it("按后端下发值判定 effect / paid / danger", async () => {
    expect(await primeAgentPolicy()).toBe(true);
    expect(lookupCanvasTool("addNode")).toMatchObject({
      effect: "canvas_write",
      paid: false,
      danger: "safe",
    });
    expect(lookupCanvasTool("runGenerate")).toMatchObject({
      effect: "media_write",
      paid: true,
    });
    expect(lookupCanvasTool("deleteNode").danger).toBe("dangerous");
  });

  it("Plan 模式拦写、放行读", async () => {
    await primeAgentPolicy();
    expect(decideCanvasTool("addNode", "plan").action).toBe("deny");
    expect(decideCanvasTool("queryNodes", "plan").action).toBe("allow");
  });

  it("协作模式：读放行、写需确认、已确认则放行", async () => {
    await primeAgentPolicy();
    expect(decideCanvasTool("queryNodes", "collaborative").action).toBe("allow");
    expect(decideCanvasTool("addNode", "collaborative").action).toBe("require_approval");
    expect(decideCanvasTool("addNode", "collaborative", true).action).toBe("allow");
  });

  it("自治模式直接放行（danger 级别随结果透出，供调用方使用）", async () => {
    await primeAgentPolicy();
    const r = decideCanvasTool("deleteNode", "autonomous");
    expect(r.action).toBe("allow");
    expect(r.danger).toBe("dangerous");
  });

  it("快照带条数与后端表哈希（便于比对版本）", async () => {
    await primeAgentPolicy();
    const snap = getAgentPolicySnapshot();
    expect(snap.loaded).toBe(true);
    expect(snap.count).toBe(4);
    expect(snap.tableHash).toBe("abc123");
  });

  it("幂等：重复 prime 不再发请求", async () => {
    await primeAgentPolicy();
    const calls = ((globalThis as any).fetch as any).mock.calls.length;
    await primeAgentPolicy();
    expect(((globalThis as any).fetch as any).mock.calls.length).toBe(calls);
  });

  it("isWriteEffect 判定与后端 write_effects 一致", () => {
    expect(isWriteEffect("canvas_write")).toBe(true);
    expect(isWriteEffect("media_write")).toBe(true);
    expect(isWriteEffect("read")).toBe(false);
  });
});

describe("agentPolicy 拉取失败", () => {
  beforeEach(() => _resetAgentPolicyForTest());

  it("网络异常 ⇒ 返回 false 且保持保守兜底（不抛异常）", async () => {
    mockFetch(() => {
      throw new Error("ECONNREFUSED");
    });
    expect(await primeAgentPolicy()).toBe(false);
    expect(getAgentPolicySnapshot().loaded).toBe(false);
    expect(lookupCanvasTool("addNode").danger).toBe("dangerous");
  });

  it("响应非法（ok=false）⇒ 不采纳，保持兜底", async () => {
    mockFetch(() => ({ ok: false, json: async () => ({ ok: false, message: "unauthorized" }) }));
    expect(await primeAgentPolicy()).toBe(false);
    expect(lookupCanvasTool("addNode").danger).toBe("dangerous");
  });
});
