/**
 * 云端不可用 ⇒ 自动回落本地（2026-11-01）
 *
 * 实测触发场景：密钥库写盘失败 ⇒ 云端渠道按未配置处理，
 * 但 selectedModelKey 仍停在云端 ⇒ 每次点「生成」都报「没有可用的 AIGC 生图渠道」。
 *
 * 测法：mock 掉 bridge.generateImageViaHost（它走 submit+轮询队列，不适合用 fetch 造假），
 * 本地那半段仍走真实 fetch（只 stub 返回），这样能验证"两条链路都被正确调用"。
 * 纪律：换路必须**说出来**（消息带原因），不许静默降级。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type FakeLS = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void };

const cloudResult = { value: { ok: false, message: "没有可用的 AIGC 生图渠道。请到「模型管理」填写 Key", fallback_placeholder: true } as Record<string, unknown> };

vi.mock("./bridge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./bridge")>();
  return {
    ...actual,
    generateImageViaHost: vi.fn(async () => cloudResult.value),
  };
});

function installEnv() {
  const store = new Map<string, string>([["__shiguang_bridge_token", "tok"]]);
  const ls: FakeLS = {
    getItem: (k) => (store.has(k) ? store.get(k)! : null),
    setItem: (k, v) => store.set(k, v),
    removeItem: (k) => store.delete(k),
  };
  (globalThis as unknown as { window: Record<string, unknown> }).window = {
    localStorage: ls,
    __SHIGUANG_BRIDGE_TOKEN: "tok",
  };
}

function stubLocalFetch(payload: Record<string, unknown>) {
  const calls: string[] = [];
  (globalThis as unknown as { fetch: unknown }).fetch = vi.fn(async (url: string) => {
    calls.push(String(url));
    return { ok: true, status: 200, json: async () => payload };
  });
  return calls;
}

describe("generateImageUnified · 云端无渠道时回落本地", () => {
  beforeEach(() => {
    installEnv();
    cloudResult.value = { ok: false, message: "没有可用的 AIGC 生图渠道。请到「模型管理」填写 Key", fallback_placeholder: true };
  });
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as { window?: unknown }).window;
    delete (globalThis as { fetch?: unknown }).fetch;
  });

  it("云端 fallback_placeholder ⇒ 改走本地并说明原因", async () => {
    const calls = stubLocalFetch({
      ok: true,
      image_url: "data:image/png;base64,AAA",
      image_data_url: "data:image/png;base64,AAA",
      message: "生成完成：本地 SD1.5",
    });
    vi.resetModules();
    const m = await import("./localImage");
    const res = await m.generateImageUnified({
      parsed: { channel_id: "deepseek", model: "some-model" },
      prompt: "a cat",
      n: 1,
      quality: "standard",
    } as never);

    expect(res.ok).toBe(true);
    expect(String(res.message)).toContain("已自动改用");
    expect(calls.some((u) => u.includes("/host/local-image-generate"))).toBe(true);
  });

  it("云端普通失败（非无渠道）⇒ 不擅自动用本地", async () => {
    cloudResult.value = { ok: false, message: "渠道 500 内部错误" };
    const calls = stubLocalFetch({ ok: true, image_url: "data:image/png;base64,AAA" });
    vi.resetModules();
    const m = await import("./localImage");
    const res = await m.generateImageUnified({
      parsed: { channel_id: "deepseek", model: "m" },
      prompt: "a cat",
      n: 1,
    } as never);

    expect(res.ok).toBe(false);
    expect(calls.length).toBe(0);
  });
});
