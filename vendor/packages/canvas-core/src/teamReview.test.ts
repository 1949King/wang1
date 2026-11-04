/**
 * 评审意见的纯函数（2026-11-04 · 画布 0.3.52）
 *
 * 这些判断错了的代价是**意见看不到**：把已解决混进待处理，人会一直翻旧账；
 * 把「刚刚」写成「0 分钟前」，人会觉得这功能没做完。
 */
import { describe, expect, it } from "vitest";

import { agoText, anchorText, composeTarget, groupComments, reviewSummary, revText } from "./teamReview";
import type { TeamComment } from "./teamClient";

const C = (id: string, patch: Partial<TeamComment> = {}): TeamComment => ({
  id,
  project_id: "p1",
  node_id: "",
  rev: 1,
  author_id: "m1",
  author: "张三",
  body: "改一下",
  created_at: 1000,
  resolved: false,
  resolved_at: 0,
  resolved_by: "",
  resolver: "",
  ...patch,
});

describe("groupComments", () => {
  it("未解决与已解决分开，各自按时间正序", () => {
    const { open, done } = groupComments([
      C("c3", { created_at: 300 }),
      C("c1", { created_at: 100 }),
      C("c2", { created_at: 200, resolved: true }),
    ]);
    expect(open.map((c) => c.id)).toEqual(["c1", "c3"]);
    expect(done.map((c) => c.id)).toEqual(["c2"]);
  });

  it("空 / undefined 不炸", () => {
    expect(groupComments(undefined)).toEqual({ open: [], done: [] });
    expect(groupComments([])).toEqual({ open: [], done: [] });
  });
});

describe("reviewSummary", () => {
  it("分别说清待处理与已解决", () => {
    expect(reviewSummary([C("a"), C("b", { resolved: true })])).toBe("1 条待处理 · 1 条已解决");
  });

  it("全空时说人话，不说「0 条待处理」", () => {
    expect(reviewSummary([])).toBe("还没有人提意见");
  });

  it("只有已解决时也说（否则人会以为意见丢了）", () => {
    expect(reviewSummary([C("a", { resolved: true })])).toBe("1 条已解决");
  });
});

describe("anchorText", () => {
  it("有标签用标签", () => {
    expect(anchorText(C("a", { node_id: "n1" }), "镜 03")).toBe("镜 03");
  });

  it("没有 node_id ⇒ 整份画布（不是空字符串）", () => {
    expect(anchorText(C("a"))).toBe("整份画布");
  });

  it("有 node_id 但没标签 ⇒ 说「某一处」，**不暴露内部 id**", () => {
    expect(anchorText(C("a", { node_id: "n1" }))).toBe("某一处");
  });
});

describe("agoText", () => {
  it("刚提的是「刚刚」，不出现「0 分钟前」", () => {
    expect(agoText(1000, 1000)).toBe("刚刚");
    expect(agoText(1000, 1030)).toBe("刚刚");
  });

  it("分钟 / 小时 / 天", () => {
    expect(agoText(1000, 1000 + 120)).toBe("2 分钟前");
    expect(agoText(1000, 1000 + 7200)).toBe("2 小时前");
    expect(agoText(1000, 1000 + 86400 * 2)).toBe("2 天前");
  });

  it("超过 7 天给日期（「23 天前」没人换算得过来）", () => {
    const at = new Date(2026, 10, 4, 9, 5, 0).getTime() / 1000;
    expect(agoText(at, at + 86400 * 20)).toBe("11-04");
  });

  it("时间戳为 0 时返回空串（不知道就说不知道）", () => {
    expect(agoText(0, 5000)).toBe("");
  });
});

describe("revText", () => {
  it("有版本号就说第几版，0 不编", () => {
    expect(revText(C("a", { rev: 3 }))).toBe("第 3 版");
    expect(revText(C("a", { rev: 0 }))).toBe("");
  });
});

describe("composeTarget", () => {
  it("没选节点 ⇒ 挂整份画布", () => {
    expect(composeTarget(null)).toEqual({ nodeId: "", label: "整份画布" });
  });

  it("选了节点 ⇒ 挂节点，有标签用标签", () => {
    expect(composeTarget("n1", "镜 03")).toEqual({ nodeId: "n1", label: "镜 03" });
  });

  it("选了节点但没标签 ⇒ 「选中这一处」，不给用户看 id", () => {
    expect(composeTarget("n1")).toEqual({ nodeId: "n1", label: "选中这一处" });
  });
});
