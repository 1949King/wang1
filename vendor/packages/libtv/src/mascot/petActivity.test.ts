/**
 * 桌宠状态机回归。
 *
 * 这套用例锁的是四件容易悄悄坏掉的事：
 *   1. 「历史成功」不能冒充「刚刚成功」（否则一进画布桌宠就无脑点头）；
 *   2. 失败必须压过成功（同一批 key 既失败又成功时报错，不能假报成功）；
 *   3. 「等你确认」优先级最高，且**弹窗关掉后必须回落**（曾经会永久卡在 awaiting）；
 *   4. 状态没变就不该让调用方动定时器（否则「成功」的 1.8s 保留期会被无关变更反复重置）。
 */
import { describe, expect, it } from "vitest";

import {
  RESULT_HOLD_MS,
  hasTrackedKey,
  selectPetActivity,
  stepPetStatus,
  type PetActivity,
} from "./petActivity";

const EMPTY: PetActivity = { busyKeys: "", successKeys: "", errorKeys: "" };
const node = (id: string, status: string) => ({ id, data: { status } });

describe("selectPetActivity", () => {
  it("空列表 / undefined / 脏数据都不炸", () => {
    expect(selectPetActivity([])).toEqual(EMPTY);
    expect(selectPetActivity(undefined)).toEqual(EMPTY);
    expect(selectPetActivity(null)).toEqual(EMPTY);
    expect(selectPetActivity([{ id: "a" }, null as never])).toEqual(EMPTY);
  });

  it("三组 key 分开归类，且已排序（内容不变时字符串可直接比较）", () => {
    const activity = selectPetActivity([
      node("b", "generating"),
      node("a", "generating"),
      node("c", "success"),
      node("d", "failed"),
      node("e", "done"),
      node("f", "error"),
      node("g", ""), // 无状态 → 忽略
    ]);
    expect(activity.busyKeys).toBe("node:a|node:b");
    expect(activity.successKeys).toBe("node:c|node:e");
    expect(activity.errorKeys).toBe("node:d|node:f");
  });
});

describe("hasTrackedKey", () => {
  it("只认自己盯着的那批 key", () => {
    const tracked = new Set(["node:a"]);
    expect(hasTrackedKey(tracked, "node:a|node:b")).toBe(true);
    expect(hasTrackedKey(tracked, "node:b")).toBe(false);
    expect(hasTrackedKey(tracked, "")).toBe(false);
  });
});

describe("stepPetStatus", () => {
  const step = (
    previous: Parameters<typeof stepPetStatus>[0]["previous"],
    previousActivity: PetActivity,
    activity: PetActivity,
    trackedBusyKeys = new Set<string>(),
    modalOpen = false,
  ) => stepPetStatus({ previous, previousActivity, activity, trackedBusyKeys, modalOpen });

  it("有节点在忙 → thinking，并记住这批 key", () => {
    const tracked = new Set<string>();
    const busy: PetActivity = { ...EMPTY, busyKeys: "node:a" };
    const res = step("idle", EMPTY, busy, tracked);
    expect(res.status).toBe("thinking");
    expect(res.holdResult).toBe(false);
    expect([...tracked]).toEqual(["node:a"]);
  });

  it("忙完成功 → success，且要求保留 1.8s；已结算的 key 被清空", () => {
    const tracked = new Set(["node:a"]);
    const busy: PetActivity = { ...EMPTY, busyKeys: "node:a" };
    const done: PetActivity = { ...EMPTY, successKeys: "node:a" };
    const res = step("thinking", busy, done, tracked);
    expect(res.status).toBe("success");
    expect(res.holdResult).toBe(true);
    expect(tracked.size).toBe(0);
    expect(RESULT_HOLD_MS).toBeGreaterThan(600);
  });

  it("忙完失败 → error", () => {
    const tracked = new Set(["node:a"]);
    const busy: PetActivity = { ...EMPTY, busyKeys: "node:a" };
    const failed: PetActivity = { ...EMPTY, errorKeys: "node:a" };
    const res = step("thinking", busy, failed, tracked);
    expect(res.status).toBe("error");
    expect(res.holdResult).toBe(true);
  });

  it("同一批 key 既失败又成功 → 报失败（不许假报成功）", () => {
    const tracked = new Set(["node:a"]);
    const busy: PetActivity = { ...EMPTY, busyKeys: "node:a" };
    const mixed: PetActivity = { busyKeys: "", successKeys: "node:a", errorKeys: "node:a" };
    const res = step("thinking", busy, mixed, tracked);
    expect(res.status).toBe("error");
  });

  it("历史遗留的成功节点不会被当成「刚刚成功」", () => {
    const done: PetActivity = { ...EMPTY, successKeys: "node:old" };
    const res = step("idle", EMPTY, done);
    expect(res.status).toBe("idle");
    expect(res.holdResult).toBe(false);
  });

  it("有确认弹窗 → awaiting 优先于在忙", () => {
    const busy: PetActivity = { ...EMPTY, busyKeys: "node:a" };
    const res = step("thinking", busy, busy, new Set(["node:a"]), true);
    expect(res.status).toBe("awaiting");
  });

  it("弹窗关掉后必须从 awaiting 回落（曾经会永久卡住）", () => {
    const res = step("awaiting", EMPTY, EMPTY, new Set(), false);
    expect(res.status).toBe("idle");
  });

  it("快照没变化时不动状态、也不要求动定时器", () => {
    const busy: PetActivity = { ...EMPTY, busyKeys: "node:a" };
    const res = step("thinking", busy, busy, new Set(["node:a"]));
    expect(res.status).toBe("thinking");
    expect(res.holdResult).toBe(false);
  });
});
