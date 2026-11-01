/**
 * 人物卡 store（2026-11-01 · C 项 UI）—— 只测纯逻辑，不碰 React 渲染。
 *
 * 重点守两条：
 *  ① 空卡不传（否则会覆盖用户的自由文本提示词）；
 *  ② 节点卡覆盖默认卡（节点是更具体的那一层）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

describe("personCard · 持久化与合并", () => {
  beforeEach(() => {
    installLS();
    vi.resetModules();
  });
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
    vi.resetModules();
  });

  it("setField 写默认卡并持久化", async () => {
    const m = await import("./personCard");
    m.usePersonCardStore.getState().setField("hair", "黑长直");
    expect(m.usePersonCardStore.getState().card.hair).toBe("黑长直");
    expect(JSON.parse(window.localStorage.getItem("shiguang:person-card:default:v1") || "{}").hair).toBe("黑长直");
  });

  it("空卡 hasCard=false（生成时不传，避免盖掉自由提示词）", async () => {
    const m = await import("./personCard");
    expect(m.hasCard({})).toBe(false);
    expect(m.hasCard(null)).toBe(false);
    expect(m.hasCard({ hair: "  " })).toBe(false);
    expect(m.hasCard({ hair: "黑长直" })).toBe(true);
  });

  it("effectiveCard：节点卡覆盖默认卡", async () => {
    const m = await import("./personCard");
    m.usePersonCardStore.getState().replace({ gender: "女生", outfit: "白衬衫" });
    const merged = m.effectiveCard({ outfit: "汉服" });
    expect(merged.gender).toBe("女生");   // 默认卡保留
    expect(merged.outfit).toBe("汉服");   // 节点覆盖
  });

  it("reset 清空默认卡", async () => {
    const m = await import("./personCard");
    m.usePersonCardStore.getState().replace({ gender: "女生" });
    m.usePersonCardStore.getState().reset();
    expect(m.usePersonCardStore.getState().card).toEqual({});
    expect(window.localStorage.getItem("shiguang:person-card:default:v1")).toBe("{}");
  });
});
