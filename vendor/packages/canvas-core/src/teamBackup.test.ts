/**
 * 拉取前另存（2026-11-04 · 画布 0.3.47）
 *
 * 这个模块的价值只有一条：**覆盖之前，用户那一版真的还在**。所以测试的重点不是
 * 名字好不好听，而是「写进去的备份能被原样读回来」—— `backupBeforePull` 里少一个
 * `canvases`、少一个 `activeCanvasId`，用户在「我的画布」里打开备份就会看到一张空画布，
 * 而这条路径平时没人走，坏了也没人发现。
 *
 * ⚠️ 画布侧 vitest 没有 jsdom（见画布测试约束）⇒ 自己给一个最小 localStorage 桩；
 * store 的初始状态用 `setState` 灌，避免依赖真实浏览器环境。
 */
import { beforeAll, describe, expect, it } from "vitest";

import { useCanvasStore } from "./store";
import { readProjectBundle, readProjectsIndex, writeProjectBundle } from "./stores/project-storage";
import { backupBeforePull, backupName } from "./teamBackup";

/** setState 的部分状态是测试专用的宽松形状，用这个别名避开 Store 的严格类型 */
const setState = useCanvasStore.setState as unknown as (p: Record<string, unknown>) => void;

const NODE = {
  id: "n1",
  type: "note",
  position: { x: 1, y: 2 },
  data: { label: "旧画布" },
};

beforeAll(() => {
  const mem = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: {
      getItem: (k: string) => (mem.has(k) ? String(mem.get(k)) : null),
      setItem: (k: string, v: string) => void mem.set(k, String(v)),
      removeItem: (k: string) => void mem.delete(k),
      clear: () => mem.clear(),
      key: (i: number) => Array.from(mem.keys())[i] ?? null,
      get length() {
        return mem.size;
      },
    },
  });
});

describe("backupName", () => {
  it("写清「覆盖前 + 月-日 时:分」，个位数补零", () => {
    expect(backupName("第三集", new Date(2026, 10, 4, 9, 5))).toBe("第三集（覆盖前 11-04 09:05）");
  });

  it("源工程没名字时给「未命名工作区」，不留半截括号", () => {
    expect(backupName("", new Date(2026, 10, 4, 15, 20))).toBe("未命名工作区（覆盖前 11-04 15:20）");
  });

  it("同名源工程、不同分钟 ⇒ 名字不同（不靠「副本(2)」区分）", () => {
    const a = backupName("第三集", new Date(2026, 10, 4, 15, 20));
    const b = backupName("第三集", new Date(2026, 10, 4, 15, 21));
    expect(a).not.toBe(b);
  });
});

describe("backupBeforePull", () => {
  it("备份能原样读回：节点还在、id 是新的、源工程不被改动", () => {
    localStorage.clear();
    writeProjectBundle({
      id: "proj_src",
      name: "第三集",
      dramaTitle: "第三集",
      episode: "",
      nodes: [],
      edges: [],
      savedAt: "2026-11-01T00:00:00.000Z",
      tier: "pro",
    });
    // 内存里的「现在的画布」比旧存档多一个节点 —— 备份必须存内存这一份，不是存档
    setState({
      nodes: [NODE],
      edges: [],
      activeProjectId: "proj_src",
      activeProjectName: "第三集",
      activeCanvasId: "canvas_a",
      activeCanvasName: "画布 1",
      dramaTitle: "第三集",
      episode: "",
    });

    const out = backupBeforePull(new Date(2026, 10, 4, 15, 20));
    expect(out.ok).toBe(true);
    expect(out.skipped).toBeUndefined();
    expect(out.id).toBeTruthy();
    expect(out.id).not.toBe("proj_src");

    const back = readProjectBundle(String(out.id));
    expect(back).not.toBeNull();
    expect(back?.name).toBe("第三集（覆盖前 11-04 15:20）");
    // 🔴 关键：读回来能在画布上看到那个节点（canvases + activeCanvasId 一个都不能少）
    expect(back?.nodes?.length).toBe(1);
    expect(back?.nodes?.[0]?.id).toBe("n1");
    expect(back?.activeCanvasId).toBe("canvas_a");
    expect(back?.canvases?.[0]?.nodes?.length).toBe(1);
    // 源工程原样不动，且新工程进了「我的画布」索引第一位
    expect(readProjectBundle("proj_src")?.nodes?.length).toBe(0);
    expect(readProjectsIndex()[0]?.id).toBe(out.id);
    expect(readProjectsIndex()[0]?.nodeCount).toBe(1);
  });

  it("空画布不产出垃圾备份（skipped 而非 ok:false）", () => {
    localStorage.clear();
    setState({ nodes: [], edges: [], activeProjectId: null, activeProjectName: "" });
    const out = backupBeforePull();
    expect(out.ok).toBe(true);
    expect(out.skipped).toBe(true);
    expect(readProjectsIndex().length).toBe(0);
  });

  it("配额顶满时如实失败，不假装存好了", () => {
    localStorage.clear();
    setState({ nodes: [NODE], edges: [], activeProjectId: "proj_src", activeProjectName: "第三集" });
    // 灌满配额
    for (let i = 0; i < 5; i += 1) {
      try {
        localStorage.setItem(`filler_${i}`, "x".repeat(1_000_000));
      } catch {
        // 桩子本身不会抛，这里只是留出上限
      }
    }
    const realSet = localStorage.setItem;
    localStorage.setItem = (k: string, v: string) => {
      if (k.startsWith("shiguang-canvas:bundle:")) {
        throw new DOMException("quota", "QuotaExceededError");
      }
      realSet.call(localStorage, k, v);
    };
    const out = backupBeforePull();
    localStorage.setItem = realSet;
    expect(out.ok).toBe(false);
    expect(String(out.why)).toBeTruthy();
  });
});
