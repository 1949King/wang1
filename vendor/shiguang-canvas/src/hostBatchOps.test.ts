/**
 * hostBatchOps.test.ts — 批量入轨接线回归（Wave 0 #13，2026-10-15）
 * ============================================================================
 * 项目纪律：vitest 是 **node 环境无 jsdom** ⇒ 纯逻辑抽出来才可测，useEffect 零覆盖。
 * 本文件只测纯函数（summarize / pickDoneIndices）；`pushBatchToTimeline` 走 fetch，
 * 属有副作用路径，靠「形状与后端契约对齐」由 tsc + 双库守保护，不做网络 mock。
 */
import { describe, it, expect } from "vitest";
import { summarizeBatchPush, pickDoneIndices } from "./hostBatchOps";
import type { BatchToTimelineResult } from "./hostBatchOps";

const base = { pushed: 0, failed: 0, items: [], errors: [] };

describe("summarizeBatchPush — 入轨结果状态文案", () => {
  it("全成功：报成功段数，无失败尾注", () => {
    const r: BatchToTimelineResult = { ...base, ok: true, pushed: 5 };
    expect(summarizeBatchPush(r)).toBe("✅ 5 段已入剪辑时间线");
  });

  it("部分失败：失败数必须说出来（最易被静默吞掉的场景）", () => {
    const r: BatchToTimelineResult = { ...base, ok: true, pushed: 3, failed: 2 };
    const s = summarizeBatchPush(r);
    expect(s).toContain("3 段已入");
    expect(s).toContain("2 段失败");
  });

  it("零成功但有失败：不得显示为成功", () => {
    const r: BatchToTimelineResult = { ...base, ok: true, pushed: 0, failed: 4 };
    const s = summarizeBatchPush(r);
    expect(s).toContain("没有分段成功入轨");
    expect(s).not.toContain("✅");
  });

  it("端点失败：回传后端 message，不吞", () => {
    const r: BatchToTimelineResult = { ...base, ok: false, message: "无已完成片段可入轨" };
    expect(summarizeBatchPush(r)).toContain("无已完成片段可入轨");
  });

  it("端点失败且无 message：给兜底文案而非空串", () => {
    expect(summarizeBatchPush({ ...base, ok: false })).toContain("未知错误");
  });
});

describe("pickDoneIndices — 筛选可入轨分段", () => {
  it("只取 status=done 且有产物的序号（done 但无产物要排除）", () => {
    expect(
      pickDoneIndices([
        { status: "done", video_url: "/inbox_file/a.mp4" }, // 0 ✓ 有产物
        { status: "running" },                             // 1 ✗ 未完成
        { status: "failed" },                              // 2 ✗ 失败
        { status: "done" },                                // 3 ✗ done 但无产物（对齐后端 local_path 判据）
        { status: "done", path: "x.mp4" },                 // 4 ✓ 有产物
      ]),
    ).toEqual([0, 4]);
  });

  it("done 但无任何产物 ⇒ 不入选（与后端 local_path 判据一致）", () => {
    expect(pickDoneIndices([{ status: "done" }, { status: "done", video_url: "" }])).toEqual([]);
  });

  it("undefined / 空数组 ⇒ 空结果，不抛", () => {
    expect(pickDoneIndices(undefined)).toEqual([]);
    expect(pickDoneIndices([])).toEqual([]);
  });
});