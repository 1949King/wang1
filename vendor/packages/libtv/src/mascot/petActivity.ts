/**
 * 画布真实状态 → 桌宠状态（纯函数）。
 *
 * 为什么单独一层
 * ==============
 * 桌宠「活不活」不取决于动画写得多花，而取决于**动画有没有接在真实状态上**。所以状态派生必须是
 * 纯函数、必须能单测：节点是「生成中」还是「失败」、有没有弹确认框在等人，都能用几个对象喂进去验。
 *
 * 对标参考实现（`AI-Canvas-tauri/src/hooks/useMascotStatus.ts`）：它把 nodes / agentTasks / messages
 * 三个来源归一成 busy / success / error 三组 key，并且**只有在「曾经忙过」的 key 结束**时才播
 * 成功/失败反馈——否则一进页面看到一堆历史 success 就会无脑点头。这套逻辑我们照搬，只是数据源换成
 * 画布 store 的 nodes（我们这里没有 agentTasks/messages 那两层结构）。
 */

import type { PetStatus } from "./mascotMotion";

/** 成功/失败反馈的保留时长（毫秒）——够看清，又不至于一直挂着。 */
export const RESULT_HOLD_MS = 1800;

/** 节点 data.status 里代表「在忙」的取值。 */
const BUSY_STATUS = new Set(["generating", "loading", "pending", "queued", "running", "analyzing"]);
/** 代表成功的取值。 */
const SUCCESS_STATUS = new Set(["success", "done"]);
/** 代表失败的取值。 */
const FAILURE_STATUS = new Set(["failed", "error"]);

interface MinimalNode {
  id: string;
  data?: { status?: unknown } | undefined;
}

export interface PetActivity {
  /** 有任务在跑 */
  busyKeys: string;
  /** 刚跑完（成功） */
  successKeys: string;
  /** 刚跑完（失败） */
  errorKeys: string;
}

const EMPTY_ACTIVITY: PetActivity = { busyKeys: "", successKeys: "", errorKeys: "" };

const readStatus = (node: MinimalNode): string => {
  const raw = node?.data?.status;
  return typeof raw === "string" ? raw : "";
};

/**
 * 把节点列表归一成三组已排序、以 `|` 连接的 key 串。
 * 排序是为了让「内容没变」可以直接用字符串比较判断（参考实现同款手法）。
 */
export function selectPetActivity(nodes: readonly MinimalNode[] | undefined | null): PetActivity {
  if (!nodes || nodes.length === 0) return EMPTY_ACTIVITY;
  const busy: string[] = [];
  const success: string[] = [];
  const error: string[] = [];
  for (const node of nodes) {
    if (!node || typeof node.id !== "string") continue;
    const status = readStatus(node);
    if (!status) continue;
    const key = `node:${node.id}`;
    if (BUSY_STATUS.has(status)) busy.push(key);
    else if (FAILURE_STATUS.has(status)) error.push(key);
    else if (SUCCESS_STATUS.has(status)) success.push(key);
  }
  return {
    busyKeys: busy.sort().join("|"),
    successKeys: success.sort().join("|"),
    errorKeys: error.sort().join("|"),
  };
}

/** 判断这批 key 里有没有「我们盯着的那批忙 key」中的任何一个。 */
export function hasTrackedKey(tracked: ReadonlySet<string>, encodedKeys: string): boolean {
  if (!encodedKeys) return false;
  return encodedKeys.split("|").some((key) => tracked.has(key));
}

export interface PetStatusInput {
  /** 上一轮的状态 */
  previous: PetStatus;
  /** 上一轮快照（用于跳过无变化的重复计算） */
  previousActivity: PetActivity;
  /** 本轮快照 */
  activity: PetActivity;
  /** 在这之前曾经忙过、还没结算的 key */
  trackedBusyKeys: Set<string>;
  /** 是否有确认弹窗打开（= 程序在等你拍板） */
  modalOpen: boolean;
}

export interface PetStatusResult {
  status: PetStatus;
  activity: PetActivity;
  /** 是否需要在 RESULT_HOLD_MS 之后回落（调用方据此挂定时器） */
  holdResult: boolean;
}

/**
 * 推进一次状态机。纯函数：不改入参（`trackedBusyKeys` 由调用方在结果里带走）。
 *
 * 优先级：**等确认 > 失败 > 成功 > 在忙 > 待命**。
 * ——「等确认」放最高，是因为它只会在你不动手时一直存在，被生成状态盖掉就永远看不到；
 * 而失败优先于成功，是同一批 key 既失败又成功时的保守取向（宁可报错也不假报成功）。
 */
export function stepPetStatus(input: PetStatusInput): PetStatusResult {
  const { previous, previousActivity, activity, trackedBusyKeys, modalOpen } = input;

  // 无变化 → 只处理弹窗这一路的进出，避免调用方无谓 setState。
  // ⚠️ 上一轮是 awaiting 而弹窗已关时**必须回落**，否则状态会永久卡在「等你确认」
  //    （awaiting 不来自节点快照，快照没变化就永远等不到下一次推进）。
  const unchanged =
    activity.busyKeys === previousActivity.busyKeys &&
    activity.successKeys === previousActivity.successKeys &&
    activity.errorKeys === previousActivity.errorKeys;
  if (unchanged) {
    if (modalOpen) return { status: "awaiting", activity, holdResult: false };
    return {
      status: previous === "awaiting" ? "idle" : previous,
      activity,
      holdResult: false,
    };
  }

  if (activity.busyKeys) {
    for (const key of activity.busyKeys.split("|")) trackedBusyKeys.add(key);
    return { status: "thinking", activity, holdResult: false };
  }

  // 没在忙，但有还没结算的 key ⇒ 看看它落到了成功还是失败
  if (trackedBusyKeys.size > 0) {
    const failed = hasTrackedKey(trackedBusyKeys, activity.errorKeys);
    const succeeded = hasTrackedKey(trackedBusyKeys, activity.successKeys);
    trackedBusyKeys.clear();
    if (failed) return { status: "error", activity, holdResult: true };
    if (succeeded) return { status: "success", activity, holdResult: true };
  }

  return { status: modalOpen ? "awaiting" : "idle", activity, holdResult: false };
}
