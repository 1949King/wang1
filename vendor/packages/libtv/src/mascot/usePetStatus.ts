/**
 * 桌宠状态订阅：把画布 store 的节点快照 + 「是否有确认弹窗」两路信号喂给 petActivity 状态机。
 *
 * 弹窗为什么用 MutationObserver 而不是给 AgentPanel 加回调
 * =====================================================
 * 「在等你确认」这个状态位在代码里的落点是 `ConfirmDialog`（`.sg-modal-root`），它被 CanvasShell 与
 * AgentPanel 各自 import，没有一个全局 store 字段。给它加全局字段要改 58KB 的 AgentPanel（且容易和
 * 并行的会话冲突）。改用「盯 DOM」是**本项目已经确立过的做法**（V4.40.54 的 `.workspace.agent-open`
 * 让位就是这么做的，起因是同机 Qt WebEngine 对 `:has()` 失效不可靠）——这里反过来用观察器读状态，
 * 不改任何被观测方，零耦合、零冻结。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useCanvasStore } from "../store";
import type { PetStatus } from "./mascotMotion";
import { RESULT_HOLD_MS, selectPetActivity, stepPetStatus, type PetActivity } from "./petActivity";

/** 确认弹窗根节点（`ConfirmDialog.tsx`）。存在即「程序在等你拍板」。 */
export const CONFIRM_MODAL_SELECTOR = ".sg-modal-root";

export function usePetStatus(): PetStatus {
  const nodes = useCanvasStore((s) => s.nodes);
  const [status, setStatus] = useState<PetStatus>("idle");

  const statusRef = useRef<PetStatus>("idle");
  const activityRef = useRef<PetActivity>(selectPetActivity(nodes));
  const trackedBusyKeys = useRef(new Set<string>());
  const holdTimer = useRef<number | null>(null);
  const modalOpenRef = useRef(false);

  const apply = useCallback(() => {
    const activity = selectPetActivity(useCanvasStore.getState().nodes);
    const result = stepPetStatus({
      previous: statusRef.current,
      previousActivity: activityRef.current,
      activity,
      trackedBusyKeys: trackedBusyKeys.current,
      modalOpen: modalOpenRef.current,
    });
    activityRef.current = activity;

    // 只在**状态真的变了**的时候动定时器。否则每次无关的 store 变更（拖一个节点）都会把
    // 「成功」的 1.8s 保留期重置，导致成功反馈永远不消失。
    if (result.status !== statusRef.current) {
      statusRef.current = result.status;
      setStatus(result.status);
      if (holdTimer.current !== null) {
        window.clearTimeout(holdTimer.current);
        holdTimer.current = null;
      }
      if (result.holdResult) {
        holdTimer.current = window.setTimeout(() => {
          holdTimer.current = null;
          statusRef.current = "idle";
          setStatus("idle");
        }, RESULT_HOLD_MS);
      }
    }
  }, []);

  // ① 节点快照变化
  useEffect(() => {
    apply();
  }, [apply, nodes]);

  // ② 确认弹窗出现/消失
  useEffect(() => {
    const sync = () => {
      const open = Boolean(document.querySelector(CONFIRM_MODAL_SELECTOR));
      if (open === modalOpenRef.current) return;
      modalOpenRef.current = open;
      apply();
    };
    sync();
    // 用 rAF 合并同一帧内的多次回调：WebView 里画布会频繁增删节点，逐次 querySelector 没必要。
    // 只观察 childList（不观察 attributes）——节点拖拽改的是 transform 样式，不该惊动这里。
    let scheduled = 0;
    const mo = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = window.requestAnimationFrame(() => {
        scheduled = 0;
        sync();
      });
    });
    mo.observe(document.body, { childList: true, subtree: true });
    return () => {
      mo.disconnect();
      if (scheduled) window.cancelAnimationFrame(scheduled);
    };
  }, [apply]);

  useEffect(
    () => () => {
      if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    },
    [],
  );

  return status;
}
