/**
 * 免责声明首屏：只出现一次 + 必须滑到底（2026-11-12）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COMPLIANCE_VERSION } from "./complianceDoc";

function installLS() {
  const map = new Map<string, string>();
  (globalThis as unknown as { window: Record<string, unknown> }).window = {
    localStorage: {
      getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
      setItem: (k: string, v: string) => map.set(k, v),
      removeItem: (k: string) => map.delete(k),
    },
  };
  return map;
}

describe("compliance 只出现一次", () => {
  beforeEach(() => { installLS(); vi.resetModules(); });
  afterEach(() => { delete (globalThis as { window?: unknown }).window; vi.resetModules(); });

  it("首次进入需要提示", async () => {
    const m = await import("./complianceStore");
    expect(m.needsCompliance()).toBe(true);
  });

  it("确认后不再提示", async () => {
    const m = await import("./complianceStore");
    expect(m.acceptCompliance()).toBe(true);
    expect(m.needsCompliance()).toBe(false);
    expect(m.readAcceptance()?.version).toBe(COMPLIANCE_VERSION);
  });

  it("条款版本升级后重新提示（合规要求）", async () => {
    const m = await import("./complianceStore");
    m.acceptCompliance("2020-01-01.1");
    expect(m.needsCompliance()).toBe(true);
  });

  it("localStorage 不可用时不崩（按未确认处理）", async () => {
    (globalThis as unknown as { window: Record<string, unknown> }).window = {
      localStorage: { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); }, removeItem: () => {} },
    };
    const m = await import("./complianceStore");
    expect(m.readAcceptance()).toBeNull();
    expect(m.acceptCompliance()).toBe(false);
  });
});

describe("滑到底判定", () => {
  it("未到底 ⇒ false；到底/内容过短 ⇒ true", async () => {
    const { isScrolledToBottom } = await import("./complianceStore");
    expect(isScrolledToBottom(0, 400, 1200)).toBe(false);
    expect(isScrolledToBottom(800, 400, 1200)).toBe(true);
    expect(isScrolledToBottom(0, 800, 800)).toBe(true);
    expect(isScrolledToBottom(0, 800, 700)).toBe(true);
  });
});

describe("decideCompliance（服务端优先）", () => {
  it("服务端已同意且版本一致 ⇒ 不再弹", async () => {
    const m = await import("./complianceStore");
    expect(m.decideCompliance({ accepted: true, version: "v1" }, null, "v1")).toBe(false);
  });

  it("服务端未同意 ⇒ 弹（即使本地记过 —— localStorage 不可信）", async () => {
    const m = await import("./complianceStore");
    expect(m.decideCompliance({ accepted: false, version: "" }, "agreed", "2026")).toBe(true);
  });

  it("服务端版本升级 ⇒ 再弹一次", async () => {
    const m = await import("./complianceStore");
    expect(m.decideCompliance({ accepted: true, version: "old" }, "agreed", "new")).toBe(true);
  });

  it("服务端不可用 ⇒ 回落本地记录", async () => {
    const m = await import("./complianceStore");
    expect(m.decideCompliance(null, null, "v1")).toBe(true);
    expect(m.decideCompliance(null, "v1", "v1")).toBe(false);
  });
});