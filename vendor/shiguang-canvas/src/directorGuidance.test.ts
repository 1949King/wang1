/**
 * directorGuidance.test.ts — 导演指导回归（2026-10-06）。
 *
 * 判据错会让**用户的分镜提示词被写坏或被无脑堆词**，所以锁四件：
 *  ① 招式库自检（id/name/phrase 唯一且非空）；
 *  ② **诊断分界**：已写的维度不再建议（这是"指导"与"堆词"的分界线）；
 *  ③ 幂等：compose 反复组合不叠加、不膨胀；
 *  ④ 撤销只摘我们的片语，用户文字不受伤。
 */
import { describe, expect, it } from "vitest";

import {
  appliedMoves,
  composePrompt,
  DIRECTOR_MOVES,
  diagnose,
  moveById,
  movesAreConsistent,
  stripAllMoves,
  stripMove,
  suggestMoves,
} from "./directorGuidance";

describe("招式库", () => {
  it("自检通过（id/name/片语唯一非空）", () => {
    expect(movesAreConsistent()).toBe(true);
    expect(DIRECTOR_MOVES.length).toBeGreaterThanOrEqual(12);
  });

  it("每条招式都有理由（why 非空）——不给理由的建议就是堆词", () => {
    for (const m of DIRECTOR_MOVES) expect(m.why.trim().length).toBeGreaterThan(4);
  });

  it("片语都被 〔〕 包裹（便于精确摘除）", () => {
    for (const m of DIRECTOR_MOVES) {
      expect(m.phrase.startsWith("〔")).toBe(true);
      expect(m.phrase.endsWith("〕")).toBe(true);
    }
  });
});

describe("诊断（指导与堆词的分界）", () => {
  it("空提示词 ⇒ 五个维度都缺，且给出起步建议", () => {
    const d = diagnose({ prompt: "" });
    expect(d.missing).toContain("景别");
    expect(d.summary).toContain("还没有提示词");
  });

  it("已写景别 ⇒ 不再建议景别", () => {
    const d = diagnose({ prompt: "中景，女孩站在雨里" });
    expect(d.present).toContain("景别");
    expect(d.missing).not.toContain("景别");
  });

  it("已写运镜 ⇒ 不再建议运镜", () => {
    const d = diagnose({ prompt: "镜头缓慢推近，女孩回头" });
    expect(d.present).toContain("运镜");
    expect(d.missing).not.toContain("运镜");
  });

  it("六维齐全 ⇒ 明确说「不是继续加词」", () => {
    const d = diagnose({
      prompt: "中景，镜头缓慢推近，前景有窗框遮挡，强明暗对比，女孩露出惊讶的表情",
    });
    expect(d.missing).toHaveLength(0);
    expect(d.summary).toContain("不是继续加词");
  });

  it("建议项只来自缺失维度", () => {
    const shot = { prompt: "中景，镜头缓慢推近" };
    const ids = suggestMoves(shot);
    for (const id of ids) {
      const m = moveById(id)!;
      expect(["景别", "运镜"]).not.toContain(m.category);
    }
  });
});

describe("组合与幂等", () => {
  it("组合后包含所选招式片语", () => {
    const out = composePrompt("女孩站在雨里", ["cu", "react"]);
    expect(out).toContain(moveById("cu")!.phrase);
    expect(out).toContain(moveById("react")!.phrase);
    expect(out.startsWith("女孩站在雨里")).toBe(true);
  });

  it("★ 反复组合不叠加（同一条只出现一次）", () => {
    let p = composePrompt("分镜", ["cu"]);
    p = composePrompt(p, ["cu"]);
    p = composePrompt(p, ["cu", "push"]);
    expect((p.match(/〔特写，面部占画面主体，浅景深〕/g) || []).length).toBe(1);
    expect(appliedMoves(p).sort()).toEqual(["cu", "push"]);
  });

  it("不选任何招式 ⇒ 回到原文（去掉我们旧的片语）", () => {
    const withMove = composePrompt("分镜", ["cu"]);
    expect(composePrompt(withMove, [])).toBe("分镜");
  });

  it("空提示词 + 招式 ⇒ 只有片语", () => {
    expect(composePrompt("", ["cu"])).toBe(moveById("cu")!.phrase);
  });
});

describe("撤销", () => {
  it("stripMove 只摘那一条", () => {
    const p = composePrompt("分镜", ["cu", "react"]);
    const after = stripMove(p, "cu");
    expect(after).not.toContain(moveById("cu")!.phrase);
    expect(after).toContain(moveById("react")!.phrase);
  });

  it("stripAllMoves 回到用户原文", () => {
    const user = "雨夜街头，女孩回头";
    const p = composePrompt(user, ["cu", "react", "contrast"]);
    expect(stripAllMoves(p)).toBe(user);
  });

  it("没有片语时幂等", () => {
    expect(stripAllMoves("纯用户文本")).toBe("纯用户文本");
    expect(stripAllMoves("")).toBe("");
  });

  it("appliedMoves 能报出已应用的（面板回显用）", () => {
    const p = composePrompt("x", ["push", "rim"]);
    expect(appliedMoves(p).sort()).toEqual(["push", "rim"]);
  });
});
