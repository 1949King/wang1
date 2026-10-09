/**
 * 桌宠主体：Q 版拟人狐狸「拾岚」的桌面形态 —— **2D 立绘 + 表情帧**版。
 *
 * 为什么从 3D 几何改成 2D 立绘（2026-10-10 用户实测拍板）
 * =======================================================
 * 上一版（b237626）用 Three.js 程序化几何拼狐狸，用户看到实机效果后直接否定：
 * 「这是一个正常人审美能做出来的东西吗？」——程序化几何做角色形象是错误路线：
 * 可爱感来自设计（比例 / 线条 / 配色），不来自几何参数；参考实现能看是因为
 * 它有 48 层专业毛发着色器。项目 `assets/mascot/` 里本来就有 AI 生成的
 * chibi 立绘（用户认可的审美基准），本版直接以立绘为形象本体。
 *
 * 表情帧体系（用户点名「不要一直挂笑」）
 * =====================================
 * 三帧同一画布（316×480，质心对齐 IoU≥0.985，叠放零位移）：
 *   - pet_neutral  自然平和表情 —— 默认主帧，idle/thinking/awaiting/error 全用它
 *   - pet_blink    眨眼帧 —— 随机 2.2~5.5s 闪一次（180ms），她就是"活"的
 *   - pet_cheer    大笑挥手帧 —— 只在 success 状态出现，庆祝完回自然脸
 *
 * 沿用的骨架经验（来自参考实现 + 上一版）：
 *   1. 拖拽逐帧零重渲染（usePetDrag 直接写 style）；
 *   2. 动作曲线纯函数层（mascotMotion.ts）——本版只用它的眨眼间隔与状态反应调度，
 *      3D 专属的耳/尾/眼球曲线保留在文件里供回归基线，不再参与渲染；
 *   3. 状态之间的切换完全由真实数据决定（petActivity + usePetStatus），
 *      随机只用于同一状态内的自然变化（几点眨眼）。
 * 渲染层从 WebGL 换成纯 CSS transform + img opacity 切换：
 * 不再创建 GL 上下文（不与生成任务抢 GPU/上下文配额），帧率分档也随之不需要了。
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import "./agentPet.css";
import {
  STATUS_BUBBLES,
  STATUS_LABELS,
  STATUS_RIM_COLORS,
  nextBlinkGap,
  reactionForStatus,
  type PetStatus,
} from "./mascotMotion";
import { usePetDrag } from "./usePetDrag";

/** 立绘素材（public/mascot/，三帧同画布 316×480）。 */
const PET_NEUTRAL = `${import.meta.env.BASE_URL}mascot/pet_neutral.png`;
const PET_BLINK = `${import.meta.env.BASE_URL}mascot/pet_blink.png`;
const PET_CHEER = `${import.meta.env.BASE_URL}mascot/pet_cheer.png`;

/**
 * 形态尺寸（px）。立绘显示高约 200px。
 * `mini` = Agent 面板打开 —— 桌宠**完全隐藏**（对齐参考开源项目：
 * 点开桌宠 → 桌宠变成对话窗口并消失；关闭对话 → 桌宠回来），
 * 不再有「缩成角落小头像」形态，故只此一档尺寸。
 */
export const PET_SIZE = { expanded: 224 } as const;

/** 眨眼帧显示时长（ms）。 */
const BLINK_MS = 180;

const rimCss = (n: number) => `#${n.toString(16).padStart(6, "0")}`;

/** 跟随系统「减弱动态」偏好（三种状态：不支持 matchMedia / 关 / 开）。 */
function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduce(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduce;
}

export interface AgentPetProps {
  status: PetStatus;
  /** Agent 面板已打开 —— 桌宠完全隐藏（面板关闭即回归，位置记忆保留） */
  mini: boolean;
  /** 单击：进入 Agent 对话画面 */
  onActivate: () => void;
  /** 覆盖系统「减弱动态」偏好；不传则自动读取 `prefers-reduced-motion` */
  reduceMotion?: boolean;
}

export default function AgentPet({ status, mini, onActivate, reduceMotion }: AgentPetProps) {
  const prefersReduce = useReducedMotion();
  const reduceMotionResolved = reduceMotion ?? prefersReduce;
  const drag = usePetDrag(PET_SIZE.expanded, 0);
  const { rootRef, onPointerDown, consumeClick, resetPosition } = drag;

  const hopRef = useRef<HTMLSpanElement | null>(null);
  const prevStatusRef = useRef<PetStatus>(status);

  /* 状态转场的一次性肢体反应（success 跳 / error 摇头）：CSS 动画 + 强制 reflow 重触发。
     与演示页同一手法；曲线两端回中立位（mascotMotion 的不变量），不会留残余位移。 */
  useEffect(() => {
    if (prevStatusRef.current === status) return;
    prevStatusRef.current = status;
    const kind = reactionForStatus(status);
    const el = hopRef.current;
    if (!el || !kind || reduceMotionResolved) return;
    el.classList.remove("sg-pet-anim--hop", "sg-pet-anim--shake");
    void el.offsetWidth;
    el.classList.add(kind === "hop" ? "sg-pet-anim--hop" : "sg-pet-anim--shake");
  }, [status, reduceMotionResolved]);

  /* 眨眼调度：随机 2.2~5.5s（mascotMotion.nextBlinkGap，与旧版同分布）。
     success 显示大笑帧时眨眼没有意义，跳过即可，调度不必停。 */
  const [blinking, setBlinking] = useState(false);
  useEffect(() => {
    if (reduceMotionResolved) return;
    let timer = 0;
    let offTimer = 0;
    const schedule = () => {
      timer = window.setTimeout(() => {
        setBlinking(true);
        offTimer = window.setTimeout(() => setBlinking(false), BLINK_MS);
        schedule();
      }, nextBlinkGap(Math.random()) * 1000);
    };
    schedule();
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(offTimer);
    };
  }, [reduceMotionResolved]);

  /* 隐藏右下角旧「Agent」圆钮：桌宠就是 Agent 的入口，两个入口并存是混乱。
     `.sg-agent-fab` 在冻结区 CanvasShell.tsx 里，不能改它 —— 用 MutationObserver
     写内联样式（同「🧰 工具让位」先例），卸载时恢复。 */
  useEffect(() => {
    const HIDE_MARK = "data-sg-fab-hidden-by-pet";
    const apply = () => {
      document.querySelectorAll<HTMLElement>(".sg-agent-fab").forEach((el) => {
        el.style.setProperty("display", "none", "important");
        el.setAttribute(HIDE_MARK, "1");
      });
    };
    apply();
    const mo = new MutationObserver(() => {
      // 只在有「未被处理过的 FAB」时才动手，避免高频 DOM 变动空转
      if (document.querySelector(`.sg-agent-fab:not([${HIDE_MARK}])`)) apply();
    });
    mo.observe(document.body, { childList: true, subtree: true });
    return () => {
      mo.disconnect();
      document.querySelectorAll<HTMLElement>(`[${HIDE_MARK}]`).forEach((el) => {
        el.style.removeProperty("display");
        el.removeAttribute(HIDE_MARK);
      });
    };
  }, []);

  const handleClick = useCallback(() => {
    if (consumeClick()) return; // 刚拖过，这次 click 是拖拽收尾
    onActivate();
  }, [consumeClick, onActivate]);

  const bubble = mini ? null : STATUS_BUBBLES[status];
  const framesClass =
    "sg-pet-frames" +
    (blinking && status !== "success" ? " is-blink" : "") +
    (status === "success" ? " is-cheer" : "");

  return (
    <div
      ref={rootRef}
      className={`sg-pet${mini ? " sg-pet--hidden" : ""}${drag.dragging ? " sg-pet--dragging" : ""}`}
      data-state={status}
      data-sg-no-autoclick="1"
      aria-hidden={mini || undefined}
      style={
        {
          "--sg-pet-rim": rimCss(STATUS_RIM_COLORS[status]),
        } as CSSProperties
      }
    >
      {bubble ? (
        <div className="sg-pet-bubble" role="status">
          {bubble}
        </div>
      ) : null}
      <button
        type="button"
        className="sg-pet-btn"
        data-sg-no-autoclick="1"
        tabIndex={mini ? -1 : 0}
        title={`${STATUS_LABELS[status]}（单击打开 / 拖动移位 / 右键复位）`}
        aria-label={STATUS_LABELS[status]}
        onPointerDown={onPointerDown}
        onClick={handleClick}
        onContextMenu={(e) => {
          e.preventDefault();
          resetPosition();
        }}
      >
        <span ref={hopRef} className="sg-pet-hop" aria-hidden="true">
          <span className="sg-pet-lift">
            <span className="sg-pet-bob">
              <span className={framesClass}>
                <img className="sg-pet-img" src={PET_NEUTRAL} alt="" draggable={false} />
                <img className="sg-pet-img sg-pet-img--blink" src={PET_BLINK} alt="" draggable={false} />
                <img className="sg-pet-img sg-pet-img--cheer" src={PET_CHEER} alt="" draggable={false} />
              </span>
            </span>
          </span>
        </span>
        <span className="sg-pet-shadow" aria-hidden="true" />
        {mini ? null : <span className="sg-pet-name">拾岚</span>}
      </button>
    </div>
  );
}
