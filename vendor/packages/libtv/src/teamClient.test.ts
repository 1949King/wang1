/**
 * 团队协作客户端单测（2026-10-31 · V4.49.1）
 *
 * vitest 环境是 node（无 localStorage / 无 fetch）⇒ 两个都要手动打桩。
 * 这里刻意**只测纯逻辑与错误映射**，不测 UI 交互（UI 交给 tsc + 人工冒烟）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type FakeLS = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void };

function installFakes(): { store: Map<string, string> } {
  const store = new Map<string, string>();
  const ls: FakeLS = {
    getItem: (k) => (store.has(k) ? store.get(k)! : null),
    setItem: (k, v) => store.set(k, v),
    removeItem: (k) => store.delete(k),
  };
  (globalThis as unknown as { window: { localStorage: FakeLS } }).window = { localStorage: ls };
  return { store };
}

async function loadModule() {
  // 每次重新加载：模块内部依赖 window/fetch，需在打桩之后导入
  vi.resetModules();
  return await import("./teamClient");
}

describe("teamClient · 地址归一化", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("补协议 / 去尾斜杠 / 空串保持空", async () => {
    const m = await loadModule();
    expect(m.normalizeAddress("192.168.1.4:18770")).toBe("http://192.168.1.4:18770");
    expect(m.normalizeAddress("  http://192.168.1.4:18770/  ")).toBe("http://192.168.1.4:18770");
    expect(m.normalizeAddress("https://team.example.com/")).toBe("https://team.example.com");
    expect(m.normalizeAddress("")).toBe("");
    expect(m.normalizeAddress("   ")).toBe("");
  });
});

describe("teamClient · 团队调用与错误映射", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("join 会归一化地址并持久化凭据", async () => {
    const { store } = installFakes();
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }),
    }));
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;

    const m = await loadModule();
    const cred = await m.teamJoin("192.168.1.4:18770", "张三");

    expect(cred.address).toBe("http://192.168.1.4:18770");
    expect(cred.token).toBe("tok");
    // 落盘可读回
    expect(m.teamCred()?.member_id).toBe("m_1");
    expect(store.size).toBeGreaterThan(0);
    // 请求确实打到了归一化后的地址
    const calledUrl = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(calledUrl).toBe("http://192.168.1.4:18770/team/join");
  });

  it("409 冲突映射成 TeamError(conflict) 并带上作者", async () => {
    installFakes();
    // 先 join 拿到地址与令牌（teamPush 需要它们），再把响应改成 409
    const m0 = await loadModule();
    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, member_id: "m_1", name: "张三", token: "tok" }),
    })) as unknown as typeof fetch;
    await m0.teamJoin("192.168.1.4:18770", "张三");

    (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
      ok: false,
      status: 409,
      json: async () => ({ ok: false, code: "conflict", message: "项目已被 张三 更新到第 2 版", author: "张三", current_rev: 2 }),
    })) as unknown as typeof fetch;

    const m = await loadModule();
    await expect(m.teamPush("p_1", { nodes: [] }, 1, "x")).rejects.toMatchObject({
      code: "conflict",
      extra: expect.objectContaining({ author: "张三", current_rev: 2 }),
    });
  });

  it("没有地址时立刻报 no_address（不发请求）", async () => {
    installFakes();
    const fetchMock = vi.fn();
    (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;

    const m = await loadModule();
    await expect(m.teamListProjects()).rejects.toMatchObject({ code: "no_address" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
