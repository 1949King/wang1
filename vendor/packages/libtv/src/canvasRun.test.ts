/**
 * canvasRun.test.ts — 「运行到此处」桥回归（刀 A4 第 3 项，2026-10-05）。
 *
 * 后端 `/host/canvas-run` 早已建好（`canvas_workflow_runner`：拓扑序 + 指纹增量缓存 +
 * counters + 默认 dry_run），本文件锁住**接线侧**最容易错的两件事：
 *  ① **`dry_run` 缺省不发**：后端按「显式 false」判定（`bool("false") === true` 是双方
 *     都踩过的坑）。缺省必须让后端用自己的默认（True=只出计划），而不是前端硬塞一个值；
 *  ② **失败不抛**：网络/非法响应一律 `ok:false`，调用方不需要 try/catch。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./bridge", () => ({
  BRIDGE: "http://test-bridge",
  bridgeToken: () => "tok",
}));

import {
  fetchCanvasCacheStats,
  formatPlanForConfirm,
  resultToNodePatches,
  runCanvasGraph,
  runGraphWithConfirm,
} from "./canvasRun";

const RESULT = {
  ok: true,
  dry_run: true,
  use_cache: true,
  order: ["a", "b"],
  planned: [{ node_id: "a", kind: "image", title: "图" }],
  executed: [],
  skipped: [],
  outputs: {},
  counters: { total: 2, planned: 1, skipped: 1, done: 0, cached: 0, failed: 0 },
  port_problems: [],
  note: "这是执行计划（dry_run）",
};

const GRAPH = { nodes: [{ id: "a" }, { id: "b" }], edges: [{ source: "a", target: "b" }] };

let lastBody: any = null;
let lastUrl = "";

function mockFetch(payload: any) {
  (globalThis as any).fetch = vi.fn(async (url: string, init: any) => {
    lastUrl = String(url);
    lastBody = init?.body ? JSON.parse(String(init.body)) : null;
    return { status: 200, json: async () => payload };
  });
}

beforeEach(() => {
  lastBody = null;
  lastUrl = "";
});

describe("runCanvasGraph 请求形状", () => {
  it("缺省不发 dry_run（让后端用自己的默认 = 只出计划）", async () => {
    mockFetch(RESULT);
    const r = await runCanvasGraph({ graph: GRAPH });
    expect(lastUrl).toContain("/host/canvas-run");
    expect("dry_run" in lastBody).toBe(false);
    expect(lastBody.use_cache).toBe(true);
    expect(lastBody.graph.nodes).toHaveLength(2);
    expect(r.ok).toBe(true);
    expect(r.counters?.planned).toBe(1);
  });

  it("显式执行时才发 dry_run=false（按「显式 false」语义）", async () => {
    mockFetch({ ...RESULT, dry_run: false });
    await runCanvasGraph({ graph: GRAPH, dryRun: false });
    expect(lastBody.dry_run).toBe(false);
  });

  it("dryRun=true 也不发字段（避免双方对默认值理解不一致）", async () => {
    mockFetch(RESULT);
    await runCanvasGraph({ graph: GRAPH, dryRun: true });
    expect("dry_run" in lastBody).toBe(false);
  });

  it("增量缓存可显式关闭", async () => {
    mockFetch(RESULT);
    await runCanvasGraph({ graph: GRAPH, useCache: false });
    expect(lastBody.use_cache).toBe(false);
  });

  it("quality / aspect 透传", async () => {
    mockFetch(RESULT);
    await runCanvasGraph({ graph: GRAPH, quality: "high", aspect: "landscape" });
    expect(lastBody.quality).toBe("high");
    expect(lastBody.aspect).toBe("landscape");
  });
});

describe("runCanvasGraph 失败路径（都不抛）", () => {
  it("网络异常 ⇒ ok=false 且 message 含原因", async () => {
    (globalThis as any).fetch = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const r = await runCanvasGraph({ graph: GRAPH });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("ECONNREFUSED");
  });

  it("非对象响应 ⇒ ok=false", async () => {
    mockFetch(null);
    const r = await runCanvasGraph({ graph: GRAPH });
    expect(r.ok).toBe(false);
  });

  it("后端 ok=false（如检测到环）原样透出", async () => {
    mockFetch({ ok: false, message: "检测到环，无法执行（工作流必须是 DAG）", cyclic: ["a", "b"] });
    const r = await runCanvasGraph({ graph: GRAPH });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("环");
  });
});

describe("fetchCanvasCacheStats", () => {
  it("用 **POST** + body{action:stats}（后端只注册 POST，GET 会 404）", async () => {
    mockFetch({ ok: true, action: "stats", stats: { entries: 3 } });
    const r = await fetchCanvasCacheStats();
    expect(lastUrl).toContain("/host/canvas-cache");
    expect(lastBody.action).toBe("stats");
    expect((r.stats as { entries: number }).entries).toBe(3);
  });

  it("异常 ⇒ 返回 ok=false 不抛", async () => {
    (globalThis as any).fetch = vi.fn(async () => {
      throw new Error("boom");
    });
    expect((await fetchCanvasCacheStats()).ok).toBe(false);
  });
});

// ── 编排层（runGraphWithConfirm / 计划格式化 / 结果映射）─────────────────

describe("formatPlanForConfirm", () => {
  it("把付费调用与增量跳过摆到用户面前", () => {
    const txt = formatPlanForConfirm({
      ok: true, planned: [{ node_id: "a", kind: "image", title: "主角定妆" }],
      counters: { total: 5, planned: 1, skipped: 4, done: 0, cached: 0, failed: 0 },
      port_problems: [{ edge: "x" }],
    } as any);
    expect(txt).toContain("共 5 个节点");
    expect(txt).toContain("待执行 1");
    expect(txt).toContain("增量跳过 4");
    expect(txt).toContain("主角定妆");
    expect(txt).toContain("端口问题 1 处");
    expect(txt).toContain("确认执行？");
  });

  it("超过 12 个计划项折叠显示（不刷屏）", () => {
    const planned = Array.from({ length: 20 }, (_, i) => ({ node_id: `n${i}`, kind: "image" }));
    const txt = formatPlanForConfirm({ ok: true, planned, counters: { total: 20, planned: 20, skipped: 0, done: 0, cached: 0, failed: 0 } } as any);
    expect(txt).toContain("…另有 8 个");
  });
});

describe("resultToNodePatches", () => {
  it("done/cached → success；failed → failed+原因", () => {
    const patches = resultToNodePatches({
      ok: true,
      executed: [
        { node_id: "a", status: "done" },
        { node_id: "b", status: "cached" },
        { node_id: "c", status: "failed", reason: "显存不足" },
      ],
    } as any);
    expect(patches).toEqual([
      { id: "a", patch: { status: "success" } },
      { id: "b", patch: { status: "success" } },
      { id: "c", patch: { status: "failed", errorMessage: "显存不足" } },
    ]);
  });
});

describe("runGraphWithConfirm 编排", () => {
  const GRAPH = { nodes: [{ id: "a" }], edges: [] };
  const hooks = () => ({
    getGraph: () => GRAPH,
    confirm: vi.fn(() => true),
    onStatus: vi.fn(),
    onNodePatch: vi.fn(),
    onBusy: vi.fn(),
  });

  it("空图：不请求、不确认", async () => {
    const h = hooks();
    h.getGraph = () => ({ nodes: [], edges: [] });
    mockFetch(RESULT);
    const r = await runGraphWithConfirm(h);
    expect(r.ok).toBe(false);
    expect(h.confirm).not.toHaveBeenCalled();
  });

  it("无待执行节点：不确认、不真跑", async () => {
    const h = hooks();
    mockFetch({ ...RESULT, planned: [], counters: { total: 1, planned: 0, skipped: 1, done: 0, cached: 0, failed: 0 } });
    const r = await runGraphWithConfirm(h);
    expect(r.ok).toBe(true);
    expect(h.confirm).not.toHaveBeenCalled();
    expect(h.onStatus).toHaveBeenCalledWith(expect.stringContaining("没有需要执行"));
  });

  it("用户取消 ⇒ 只发了一次 dry_run 请求，绝不真跑", async () => {
    const h = hooks();
    h.confirm = vi.fn(() => false);
    mockFetch(RESULT);
    const r = await runGraphWithConfirm(h);
    expect(r.ok).toBe(false);
    expect((globalThis as any).fetch).toHaveBeenCalledTimes(1);
    expect(lastBody.dry_run).toBeUndefined();     // 第一次永远是"只出计划"
  });

  it("确认后：先 dry_run 再真跑，并回写节点状态 + busy 收尾", async () => {
    const h = hooks();
    const calls: any[] = [];
    (globalThis as any).fetch = vi.fn(async (_u: string, init: any) => {
      const b = JSON.parse(String(init.body));
      calls.push(b);
      return {
        status: 200,
        json: async () =>
          b.dry_run === false
            ? { ...RESULT, dry_run: false, executed: [{ node_id: "a", status: "done" }], counters: { total: 1, planned: 1, skipped: 0, done: 1, cached: 0, failed: 0 } }
            : RESULT,
      };
    });
    const r = await runGraphWithConfirm(h);
    expect(calls.length).toBe(2);
    expect(calls[0].dry_run).toBeUndefined();     // 第一次：只出计划
    expect(calls[1].dry_run).toBe(false);         // 第二次：显式执行
    expect(h.onNodePatch).toHaveBeenCalledWith("a", { status: "success" });
    expect(h.onBusy).toHaveBeenCalledWith(true);
    expect(h.onBusy).toHaveBeenLastCalledWith(false);
    expect(r.ok).toBe(true);
  });

  it("执行异常也把 busy 复位（finally）", async () => {
    const h = hooks();
    let n = 0;
    (globalThis as any).fetch = vi.fn(async () => {
      n += 1;
      if (n === 1) return { status: 200, json: async () => RESULT };
      throw new Error("中途炸了");
    });
    await runGraphWithConfirm(h);
    expect(h.onBusy).toHaveBeenLastCalledWith(false);
  });
});
