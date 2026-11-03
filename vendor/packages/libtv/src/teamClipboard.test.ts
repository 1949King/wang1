/**
 * 剪贴板（2026-11-03 · 画布 0.3.44）
 *
 * 这个函数的唯一价值是**说实话**：复制没成功却返回 true，人就以为码在剪贴板里，
 * 粘出来是上一次的内容 —— 排查成本极高。所以这几条都锁「失败必须报 false」。
 *
 * ⚠️ Node 22 的 `globalThis.navigator` 是只读 getter，直接赋值会抛
 * `Cannot set property navigator` —— 必须 defineProperty 才测得动。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "./teamClipboard";

function setNavigator(value: unknown) {
  Object.defineProperty(globalThis, "navigator", { value, configurable: true, writable: true });
}

function installClipboard(impl: (t: string) => Promise<void>) {
  const calls: string[] = [];
  setNavigator({ clipboard: { writeText: async (t: string) => { calls.push(t); await impl(t); } } });
  return calls;
}

afterEach(() => {
  setNavigator(undefined);
  delete (globalThis as Record<string, unknown>).document;
  vi.restoreAllMocks();
});

describe("copyText", () => {
  it("空串直接 false，不去碰剪贴板", async () => {
    const calls = installClipboard(async () => {});
    await expect(copyText("")).resolves.toBe(false);
    await expect(copyText("   ")).resolves.toBe(false);
    expect(calls).toEqual([]);
  });

  it("标准 API 成功就回 true，并且原样写入（不去空格）", async () => {
    const calls = installClipboard(async () => {});
    await expect(copyText(" 229140 ")).resolves.toBe(true);
    expect(calls).toEqual([" 229140 "]);
  });

  it("标准 API 抛错且没有 DOM 兜底 ⇒ false（绝不假装成功）", async () => {
    setNavigator({ clipboard: { writeText: async () => { throw new Error("NotAllowedError"); } } });
    await expect(copyText("229140")).resolves.toBe(false);
  });

  it("没有 clipboard 也没有 document ⇒ false", async () => {
    await expect(copyText("229140")).resolves.toBe(false);
  });
});
