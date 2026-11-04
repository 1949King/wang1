/**
 * 出码后的轮询（2026-11-04 · 从 `TeamPanel` 抽出来）
 *
 * 面板上出现 6 位码之后，得有人每 2 秒问一次服务端：「这张码还剩几个名额 / 有没有
 * 人刚加进来」。这段逻辑与渲染无关，抽成 hook 有两个实际好处：
 *   · 面板组件不再背一个 300 行的「函数」（质量棘轮按函数跨度算，会把后面
 *     一大段一起算进去 —— 那段代码里正好没有独立的函数起点）；
 *   · 轮询的生命周期只由 `pairCode` / `live` 决定，不会因为父组件重渲染而重启。
 *
 * 两条纪律：
 *   ① **失败不说话**。人正在念号码，网络抖一下就弹错误等于打断他；
 *      下一轮自己会好，真出问题在别的出口（心跳）会显示。
 *   ② **回调用 ref 存**，不进依赖数组 —— 依赖它会让每帧都重建定时器，
 *      2 秒的轮询变成「每帧轮询」。
 */
import { useEffect, useRef } from "react";

import { teamMembers, teamPairingStatus, type TeamMember, type TeamPairingInfo } from "./teamClient";

type Args = {
  /** 正在轮询的配对码（空串 = 还没出码，不轮询） */
  pairCode: string;
  /** 码还活着吗（过期/作废后停掉，省得一直打空请求） */
  live: boolean;
  /** 拿到最新状态且**还是同一张码** */
  onStatus: (st: TeamPairingInfo) => void;
  /** 服务端手上已经没有这张活码了（用尽 / 被废 / 过期清理） */
  onGone: () => void;
  /** 成员列表（顺便当「谁刚加入」的依据） */
  onMembers: (list: TeamMember[]) => void;
};

export function usePairingPoll({ pairCode, live, onStatus, onGone, onMembers }: Args): void {
  const ref = useRef({ onStatus, onGone, onMembers });
  ref.current = { onStatus, onGone, onMembers };

  useEffect(() => {
    if (!pairCode || !live) return;
    let stop = false;

    const poll = async () => {
      try {
        const st = await teamPairingStatus();
        if (stop) return;
        if (st.code === pairCode) ref.current.onStatus(st);
        else ref.current.onGone();
      } catch {
        /* 网络抖一下就跳过，下一轮再来 */
      }
      try {
        const list = await teamMembers();
        if (stop) return;
        ref.current.onMembers(list);
      } catch {
        /* 同上 */
      }
    };

    void poll();
    const timer = window.setInterval(() => { void poll(); }, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [pairCode, live]);
}
