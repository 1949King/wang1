/**
 * teamDiffText 单测（2026-11-02）
 *
 * 这段是「拉取前给人看的那几行字」。它不参与任何业务判断，但**写错了会让人做错决定**
 * （比如把「没动」说成「改了」，人就不敢拉；或者漏掉时间线变化，人拉了才发现成片变了）。
 * 所以逐条锁住文案与判定。
 */
import { describe, expect, it } from "vitest";

import type { TeamDiff } from "./teamClient";
import { diffHeadline, diffIsEmpty, formatTeamDiff } from "./teamDiffText";

function make(over: Partial<TeamDiff> = {}): TeamDiff {
  return {
    project_id: "p_1",
    from_rev: 3,
    to_rev: 5,
    revisions: 2,
    same: false,
    nodes: { added: 0, removed: 0, changed: 0, added_titles: [], removed_titles: [], changed_titles: [] },
    edges: { added: 0, removed: 0 },
    timeline: { before: 0, after: 0, added: 0, removed: 0, changed: 0 },
    title: { before: "", after: "", changed: false },
    ...over,
  };
}

describe("teamDiffText · 判定", () => {
  it("同版本 / 内容没变都算空", () => {
    expect(diffIsEmpty(make({ same: true }))).toBe(true);
    expect(diffIsEmpty(make())).toBe(true);
  });

  it("任何一项有变化就不算空", () => {
    expect(diffIsEmpty(make({ nodes: { added: 1, removed: 0, changed: 0 } }))).toBe(false);
    expect(diffIsEmpty(make({ edges: { added: 0, removed: 1 } }))).toBe(false);
    expect(diffIsEmpty(make({ timeline: { before: 1, after: 2, added: 1, removed: 0, changed: 0 } }))).toBe(false);
    expect(diffIsEmpty(make({ title: { before: "a", after: "b", changed: true } }))).toBe(false);
  });

  it("首行先说落后多少", () => {
    expect(diffHeadline(make({ same: true }), 3)).toContain("同一版");
    expect(diffHeadline(make(), 3)).toContain("你在 rev 3");
    expect(diffHeadline(make(), 3)).toContain("改了 2 版");
  });

  it("没有版本锚点时如实说，不假装知道", () => {
    const line = diffHeadline(make(), 0);
    expect(line).toContain("没有版本记录");
    expect(line).toContain("rev 5");
  });
});

describe("teamDiffText · 正文", () => {
  it("逐项列出节点 / 连线 / 时间线 / 工程名", () => {
    const text = formatTeamDiff(
      make({
        nodes: { added: 2, removed: 1, changed: 5, added_titles: ["镜 07", "镜 08"],
                 removed_titles: ["剧本"], changed_titles: ["镜 03", "镜 05"] },
        edges: { added: 3, removed: 2 },
        timeline: { before: 6, after: 7, added: 2, removed: 1, changed: 3 },
        title: { before: "旧名", after: "新名", changed: true },
      }),
      3,
    );
    expect(text).toContain("节点：新增 2、删除 1、改动 5");
    expect(text).toContain("新增：镜 07、镜 08");
    expect(text).toContain("改过：镜 03、镜 05");
    expect(text).toContain("删掉：剧本");
    expect(text).toContain("连线：+3 / -2");
    expect(text).toContain("新增 2 段、删除 1 段、改动 3 段（6 → 7 段）");
    expect(text).toContain("工程名：旧名 → 新名");
  });

  it("只动时间线也要说出来（成片变了最容易被忽略）", () => {
    const text = formatTeamDiff(
      make({ timeline: { before: 6, after: 6, added: 0, removed: 0, changed: 1 } }),
      3,
    );
    expect(text).toContain("剪辑时间线：改动 1 段");
  });

  it("节点没动就写「没动」，不空着让人以为漏报", () => {
    const text = formatTeamDiff(make({ edges: { added: 1, removed: 0 } }), 3);
    expect(text).toContain("节点：没动");
    expect(text).toContain("连线：+1 / -0");
  });

  it("时间线存在但没变化时给数量，不报「改动」", () => {
    // 必须有别的变化，否则 diffIsEmpty 会提前收成一行（那样也合理：没东西可说）
    const text = formatTeamDiff(
      make({
        nodes: { added: 1, removed: 0, changed: 0 },
        timeline: { before: 4, after: 4, added: 0, removed: 0, changed: 0 },
      }),
      3,
    );
    expect(text).toContain("4 段，没动");
    expect(text).not.toContain("剪辑时间线：新增");
  });

  it("完全没内容时只回一行", () => {
    const text = formatTeamDiff(make(), 3);
    expect(text.split("\n")).toHaveLength(1);
  });

  it("缺字段不炸（老服务器可能回瘦身结构）", () => {
    const thin: TeamDiff = { project_id: "p", from_rev: 1, to_rev: 2, revisions: 1, same: false };
    expect(() => formatTeamDiff(thin, 1)).not.toThrow();
    expect(diffIsEmpty(thin)).toBe(true);
  });
});
