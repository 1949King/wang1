/**
 * 意图胶囊目录单测（2026-10-20）。
 * 纯数据校验：id 唯一 / 阶段覆盖 / 每胶囊有节点与能力 / 三层文案齐备。
 */
import { describe, expect, it } from "vitest";
import {
  INTENT_CAPSULES,
  STAGE_LABELS,
  allCapabilityIds,
  allNodeKinds,
  capsuleById,
  capsulesForStage,
  stageCoverage,
  type CapsuleStage,
} from "./intentCapsuleCatalog";

const KNOWN_NODE_KINDS = new Set([
  "script", "shot", "image", "video", "audio", "music", "digitalHuman",
  "director", "directorCard", "storyboard", "shotlist", "animation",
  "panorama", "generator", "source", "group", "prompt", "text", "config",
  "note", "markdown", "character",
]);

describe("意图胶囊目录", () => {
  it("id 唯一且非空", () => {
    const ids = INTENT_CAPSULES.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.every((id) => id.startsWith("capsule."))).toBe(true);
  });

  it("覆盖全部 7 个阶段", () => {
    const stages = Object.keys(STAGE_LABELS) as CapsuleStage[];
    for (const stage of stages) {
      expect(capsulesForStage(stage).length).toBeGreaterThan(0);
    }
  });

  it("每个胶囊都有节点、能力与三层文案", () => {
    for (const capsule of INTENT_CAPSULES) {
      expect(capsule.nodeKinds.length).toBeGreaterThan(0);
      expect(capsule.capabilities.length).toBeGreaterThan(0);
      expect(capsule.surface.length).toBeGreaterThan(0);
      expect(capsule.semantic.length).toBeGreaterThan(0);
      expect(capsule.implementation.length).toBeGreaterThan(0);
    }
  });

  it("节点 kind 都在已知集合内", () => {
    for (const kind of allNodeKinds()) {
      expect(KNOWN_NODE_KINDS.has(kind), `未知节点 kind: ${kind}`).toBe(true);
    }
  });

  it("能力 id 形状合法（prefix.method）", () => {
    for (const cap of allCapabilityIds()) {
      expect(cap).toMatch(/^(editor|pipeline|canvas|model|ext|workflow)\.[a-z0-9_.]+$/);
    }
  });

  it("按 id 查找", () => {
    expect(capsuleById("capsule.edit")?.title).toBe("精剪卡");
    expect(capsuleById("nope")).toBeUndefined();
  });

  it("阶段覆盖矩阵完整", () => {
    const coverage = stageCoverage();
    expect(coverage).toHaveLength(Object.keys(STAGE_LABELS).length);
    expect(coverage.every((row) => row.capsules > 0)).toBe(true);
    expect(coverage.reduce((n, row) => n + row.capsules, 0)).toBe(INTENT_CAPSULES.length);
  });
});
