/**
 * 磁吸拖拽 Hook
 *
 * 包装 ReactFlow 的 onNodeDragStart / onNodeDrag / onNodeDragStop，提供三层手感：
 *
 *  1. 磁吸（未咬合时）—— 拖拽中**不覆写卡片位置**（1:1 跟手，借鉴手机主屏「手指到哪
 *     图标到哪」手感），只记录「松手会落在哪」（MagneticEngine.computeMagnetic）；
 *     松手才滑入落点。
 *  2. 咬合阻力（已吸附时）—— 直接拖拽不会立刻脱离，必须先「绷断」：
 *        · 拉力 ≤ stretchThreshold(30px)  → 完全粘住（卡片不动，缝隙变琥珀色「拉伸中」）
 *        · 30px < 拉力 < breakThreshold(50px) → 只让出超出量的 bondGiveRatio(28%)，绷住感
 *        · 拉力 ≥ breakThreshold(50px)    → 断裂，卡片脱开并闪一下「已断开」
 *     断裂后本次拖拽内临时屏蔽该目标，避免刚拉开又被吸回去。
 *  3. 落座 —— 松开时从当前位置**动画滑到**落点（snapAnimationMs=200；强吸附落座带
 *     overshootPx(5) 过冲），落位后若形成咬合则闪光提示「已吸附」。
 *
 * 依赖时序（已核对 @xyflow/system v12 的 XYDrag 实现）：
 *   updateNodes 内部是「先 updateNodePositions 写回位置 → 再调用 onNodeDrag」，
 *   拖拽结束时同理「先 updateNodePositions → 再 onNodeDragStop」。
 *   因此本 Hook 在回调里对位置的覆写一定生效、不会被覆盖。
 *
 * ⚠️ 2026-09-18 用户裁定（借鉴手机主屏拖拽手感）：
 *   取消 V4.28.2「拖拽中进入磁吸范围即整卡瞬移」——那与手机主屏「绝不瞬移」的手感相反，
 *   且每帧 writeNodePos 重建 nodes 数组带来严重卡顿。现改为「跟手 + 松手落座」。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Node, ReactFlowInstance } from "@xyflow/react";
import { useCanvasStore } from "../store";
import { computeMagnetic, rectOf, resolveNodeSize } from "./MagneticEngine";
import { SpatialIndex } from "./SpatialIndex";
import { findBondFor, neighborOf } from "./bonds";
import { isEmptyPlan, planReflow, type ReflowPlan } from "./reflow";
import {
  DEFAULT_MAG_CONFIG,
  IDLE_BOND_STATE,
  type Bond,
  type BondFlash,
  type BondState,
  type MagneticDragState,
} from "./types";

interface UseMagneticDragOptions {
  /** 预留：后续版本用于坐标转换 */
  rfRef?: React.MutableRefObject<ReactFlowInstance | null>;
  enabled: boolean;
  nodes: Node[];
}

/** 初始状态：无磁吸 */
const IDLE_STATE: MagneticDragState = {
  level: "none",
  targetId: null,
  direction: null,
  snapX: 0,
  snapY: 0,
};

/** 落座 / 断裂闪光的展示时长（ms） */
const FLASH_MS = 1100;

/** 空让位规划（初始值 / 拖拽结束时复位） */
const EMPTY_REFLOW: ReflowPlan = { ghost: null, shifts: [], axis: null, blocked: false };

/** 让位落座时整列平移的动画时长（ms）：略快于落座，避免「卡先到、邻居后到」的拖影 */
const REFLOW_SHIFT_MS = 180;

export function useMagneticDrag({ enabled, nodes }: UseMagneticDragOptions) {
  const [magState, setMagState] = useState<MagneticDragState>(IDLE_STATE);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [bondState, setBondState] = useState<BondState>(IDLE_BOND_STATE);
  const [flash, setFlash] = useState<BondFlash | null>(null);
  /**
   * 让位预览规划（2026-09-18 借鉴手机主屏手感 · 第 2 条机制）。
   *
   * 拖拽中**只记录**「档在落位点上的同行/列卡片将如何让开」，
   * 真正的位移一律推迟到 onNodeDragStop —— 与「跟手浮起」不变量同源：
   * 拖拽中绝不覆写任何卡片位置（包括邻居），否则又会出现「卡片自己乱跑」。
   */
  const [reflowPlan, setReflowPlan] = useState<ReflowPlan>(EMPTY_REFLOW);

  const draggingIdRef = useRef<string | null>(null);
  /** 本次拖拽起点所咬合的对象（拖拽开始时快照，拖拽中不变） */
  const bondRef = useRef<Bond | null>(null);
  /** 咬合原点：卡片贴合时所在的位置 */
  const bondOriginRef = useRef<{ x: number; y: number } | null>(null);
  /** 本次拖拽内咬合是否已断裂 */
  const brokenRef = useRef(false);
  /** 断裂后临时屏蔽的磁吸目标，避免刚拉开又被吸回去 */
  const mutedRef = useRef<Set<string>>(new Set());
  const flashTimerRef = useRef<number | null>(null);
  /** 正在运行的落座动画帧句柄（新的拖拽开始时取消旧的） */
  const animFrameRef = useRef<number | null>(null);

  // 空间索引：拖拽时只遍历附近候选节点，避免全量 O(n²)
  const spatialIndex = useMemo(() => new SpatialIndex(nodes), [nodes]);

  const fireFlash = useCallback((kind: BondFlash["kind"], bond: Bond) => {
    setFlash({ kind, bond, at: performance.now() });
    if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
    flashTimerRef.current = window.setTimeout(() => {
      setFlash(null);
      flashTimerRef.current = null;
    }, FLASH_MS);
  }, []);

  useEffect(
    () => () => {
      if (flashTimerRef.current !== null) window.clearTimeout(flashTimerRef.current);
      if (animFrameRef.current !== null) cancelAnimationFrame(animFrameRef.current);
    },
    [],
  );

  /** 写入节点绝对位置（流坐标）；位置无变化时不触发 setState，避免多余渲染 */
  const writeNodePos = useCallback((id: string, pos: { x: number; y: number }) => {
    const state = useCanvasStore.getState();
    let changed = false;
    const next = state.nodes.map((n) => {
      if (n.id !== id) return n;
      if (n.position.x === pos.x && n.position.y === pos.y) return n;
      changed = true;
      return { ...n, position: { x: pos.x, y: pos.y } };
    });
    if (changed) useCanvasStore.setState({ nodes: next });
  }, []);

  /** 把节点从当前位置平滑移到目标位置 */
  const animateNodeTo = useCallback(
    (
      id: string,
      from: { x: number; y: number },
      to: { x: number; y: number },
      duration: number,
      overshootPx: number,
      onDone?: (bond: Bond | null) => void,
    ) => {
      if (animFrameRef.current !== null) cancelAnimationFrame(animFrameRef.current);
      const startTime = performance.now();

      const step = (now: number) => {
        const t = Math.min((now - startTime) / duration, 1);
        const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        // 落座过冲：结束前轻微越过目标再回弹
        const overshoot =
          overshootPx <= 0 || t < 0.7
            ? 0
            : Math.sin(((t - 0.7) * Math.PI) / 0.3) * -overshootPx;

        writeNodePos(id, {
          x: from.x + (to.x - from.x) * eased + overshoot,
          y: from.y + (to.y - from.y) * eased + overshoot,
        });

        if (t < 1) {
          animFrameRef.current = requestAnimationFrame(step);
        } else {
          animFrameRef.current = null;
          // 动画收尾时落到精确目标，抹掉过冲/浮点误差
          writeNodePos(id, to);
          if (onDone) {
            onDone(findBondFor(id, useCanvasStore.getState().nodes));
          }
        }
      };
      animFrameRef.current = requestAnimationFrame(step);
    },
    [writeNodePos],
  );

  /**
   * 批量平移多张卡到新位置（让位落座专用）。
   *
   * 与 animateNodeTo 的区别：
   *   - 一次写入整批位置（单次 setState），避免 n 张卡各建一个动画帧循环；
   *   - 从每张卡的**当前真实位置**出发（而不是从规划时的快照），
   *     因为拖拽过程中这些卡可能已被其它机制移动过；
   *   - 不带过冲（过冲是拖拽卡落座的专属手感，邻居让位要「安静地滑开」）。
   */
  const animateNodesTo = useCallback(
    (shifts: { id: string; x: number; y: number }[], duration: number) => {
      if (shifts.length === 0) return;
      if (animFrameRef.current !== null) cancelAnimationFrame(animFrameRef.current);

      const state = useCanvasStore.getState();
      const from = new Map<string, { x: number; y: number }>();
      for (const s of shifts) {
        const node = state.nodes.find((n) => n.id === s.id);
        if (node) from.set(s.id, { x: node.position.x, y: node.position.y });
      }
      const moving = shifts.filter((s) => from.has(s.id));
      if (moving.length === 0) return;

      const startTime = performance.now();
      const step = (now: number) => {
        const t = Math.min((now - startTime) / duration, 1);
        const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

        const cur = useCanvasStore.getState();
        const next = cur.nodes.map((n) => {
          const target = moving.find((s) => s.id === n.id);
          if (!target) return n;
          const origin = from.get(n.id)!;
          return {
            ...n,
            position: {
              x: origin.x + (target.x - origin.x) * eased,
              y: origin.y + (target.y - origin.y) * eased,
            },
          };
        });
        useCanvasStore.setState({ nodes: next });

        if (t < 1) {
          animFrameRef.current = requestAnimationFrame(step);
        } else {
          animFrameRef.current = null;
          // 收尾落到精确目标
          const final = useCanvasStore.getState();
          useCanvasStore.setState({
            nodes: final.nodes.map((n) => {
              const target = moving.find((s) => s.id === n.id);
              return target ? { ...n, position: { x: target.x, y: target.y } } : n;
            }),
          });
        }
      };
      animFrameRef.current = requestAnimationFrame(step);
    },
    [],
  );

  /** 拖拽开始：快照咬合关系与咬合原点，重置本次拖拽的临时状态 */
  const onNodeDragStart = useCallback(
    (_event: unknown, node: Node) => {
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = null;
      }
      draggingIdRef.current = node.id;
      setDraggingId(node.id);
      bondRef.current = null;
      bondOriginRef.current = null;
      brokenRef.current = false;
      mutedRef.current = new Set();
      setBondState(IDLE_BOND_STATE);
      if (!enabled) return;

      const all = useCanvasStore.getState().nodes;
      const current = all.find((n) => n.id === node.id);
      const bond = findBondFor(node.id, all, DEFAULT_MAG_CONFIG);
      if (bond && current) {
        bondRef.current = bond;
        // 以 store 中的真实位置为原点（用户看到的就是它）
        bondOriginRef.current = { x: current.position.x, y: current.position.y };
      }
    },
    [enabled],
  );

  /** 拖拽中：先处理咬合阻力，未咬合时走常规磁吸 */
  const onNodeDrag = useCallback(
    (_event: unknown, draggingNode: Node) => {
      if (!enabled) {
        if (magState.level !== "none") setMagState(IDLE_STATE);
        return;
      }

      draggingIdRef.current = draggingNode.id;
      setDraggingId(draggingNode.id);

      const cfg = DEFAULT_MAG_CONFIG;

      // ══════ 1. 咬合阻力：已吸附的卡片必须先绷断才能移动 ══════
      const bond = bondRef.current;
      const origin = bondOriginRef.current;
      if (bond && origin && !brokenRef.current) {
        const pullX = draggingNode.position.x - origin.x;
        const pullY = draggingNode.position.y - origin.y;
        const pull = Math.hypot(pullX, pullY);

        if (pull < cfg.breakThreshold) {
          // 拉伸段完全粘住；张力段只让出超出量的一小部分 → 「绷住」的阻力感
          const give =
            pull <= cfg.stretchThreshold
              ? 0
              : (pull - cfg.stretchThreshold) * cfg.bondGiveRatio;
          const len = pull || 1;
          writeNodePos(draggingNode.id, {
            x: origin.x + (pullX / len) * give,
            y: origin.y + (pullY / len) * give,
          });
          setBondState({
            bond,
            phase: pull <= cfg.stretchThreshold ? "stretching" : "strained",
            strain: Math.min(pull / cfg.breakThreshold, 1),
            resisted: true,
          });
          if (magState.level !== "none") setMagState(IDLE_STATE);
          return;
        }

        // 拉过头 → 断裂。本次拖拽内屏蔽该目标，避免刚拉开又被吸回去
        brokenRef.current = true;
        bondRef.current = null;
        mutedRef.current.add(neighborOf(bond, draggingNode.id));
        setBondState(IDLE_BOND_STATE);
        fireFlash("break", bond);
      }

      // ══════ 2. 常规磁吸 ══════
      const dragSize = resolveNodeSize(draggingNode);
      const candidates = spatialIndex.queryNear(
        draggingNode.position.x + dragSize.width / 2,
        draggingNode.position.y + dragSize.height / 2,
      );
      const result = computeMagnetic(
        draggingNode,
        nodes,
        cfg,
        candidates,
        mutedRef.current,
      );

      if (result.level !== "none" && result.targetId) {
        /**
         * 跟手浮起（2026-09-18 用户裁定「借鉴手机主屏拖拽手感」）：
         *
         * 旧实现（V4.28.2「靠近即吸附」）在拖拽中对所有等级直接 writeNodePos 贴到落点，
         * 用户看到的是「卡片进入 120px 范围就自己跳走」——与手机主屏「手指到哪图标到哪、
         * 绝不瞬移」的手感完全相反。
         *
         * 新规则：**拖拽中绝不覆写卡片位置**，让它 1:1 跟指针走（React Flow 原生行为）。
         * 这里只记录「如果现在松手会落在哪」，落座动作交给 onNodeDragStop 执行。
         * 这同时消除了旧实现的性能问题：不再每帧重建 nodes 数组。
         */
        setMagState({
          level: result.level,
          targetId: result.targetId,
          direction: result.direction,
          snapX: result.snapX,
          snapY: result.snapY,
        });

        /**
         * 整列让位预览（2026-09-18 借鉴手机主屏手感 · 第 2 条机制）。
         *
         * 手机主屏上把图标拖到已有图标的位置，那一排会让开一格。这里用**磁吸算出的
         * 落点**作为「打算落到的矩形」交给 planReflow，得到：
         *   - ghost：让位后拖拽卡真正该占的位置（= 被推开那张卡的原位置）
         *   - shifts：需要一起挪开的邻居
         *
         * 拖拽中**只记录、不执行** —— 与「跟手浮起」同源，绝不移动任何卡。
         * 规划为空（没挡住 / 层叠 / 链断）时保持原 snapPos，行为与 V4.29.0 一致。
         */
        const plan = planReflow(
          { x: result.snapX, y: result.snapY, w: dragSize.width, h: dragSize.height },
          nodes.filter((n) => n.id !== draggingNode.id),
          cfg,
        );
        setReflowPlan(plan);
      } else {
        if (magState.level !== "none") setMagState(IDLE_STATE);
        setReflowPlan((prev) => (prev.ghost ? EMPTY_REFLOW : prev));
      }
    },
    [enabled, nodes, magState.level, spatialIndex, setMagState, fireFlash],
  );

  /** 拖拽结束：断裂后无动作；仍粘住时回弹归位；吸附到目标时钉回落点并闪光 */
  const onNodeDragStop = useCallback(
    (_event: unknown, draggingNode: Node) => {
      const bond = bondRef.current;
      const origin = bondOriginRef.current;

      if (enabled && bond && origin && !brokenRef.current) {
        // 用户松手时仍被粘住 → 平滑回弹到贴合位（不闪「已吸附」，因为它本来就没断开）
        animateNodeTo(
          draggingNode.id,
          { x: draggingNode.position.x, y: draggingNode.position.y },
          origin,
          150,
          0,
        );
      } else if (enabled && magState.level !== "none" && magState.targetId) {
        /**
         * 松手落座（2026-09-18 用户裁定「借鉴手机主屏拖拽手感」）：
         *
         * 旧实现是瞬间 writeNodePos 钉到落点（无过渡），配合拖拽中的每帧瞬移，
         * 观感是「跳过去」。手机主屏是「松手后图标滑入格点」。
         *
         * 新实现：从卡片当前位置 **动画滑到** 落点，启用一直闲置的
         * snapAnimationMs(200) + overshootPx(5)（仅强吸附落座带过冲，与冻结不变量
         * 「强吸附落座才带 overshootPx(5) 过冲」一致；weak/medium 不带过冲）。
         *
         * ⚠️ 仍用 animateNodeTo（内部 writeNodePos 逐帧写）。XYDrag 结束时会把
         * 卡片写回鼠标位置，动画第一帧会覆盖它，故时序安全。
         */
        const strongLanding = magState.level === "strong" || magState.level === "instant";

        /**
         * 整列让位落座（2026-09-18 借鉴手机主屏手感 · 第 2 条机制）。
         *
         * 执行顺序必须是「**邻居先滑开 → 拖拽卡再落进那个坑**」：
         * 反过来的话，拖拽卡会先落在被占用的位置上、与邻居短暂重叠，
         * 观感是「卡片叠了一下又被挤走」。
         *
         * 落点也要相应改写：有让位时拖拽卡应落进 ghost（锚点让出的坑），
         * 而不是原来的 snapPos —— 后者正是锚点当前所占的位置。
         */
        const plan = reflowPlan;
        const hasReflow = !isEmptyPlan(plan) && plan.ghost !== null;
        if (hasReflow) {
          animateNodesTo(plan.shifts, REFLOW_SHIFT_MS);
        }

        const landing = hasReflow
          ? { x: plan.ghost!.x, y: plan.ghost!.y }
          : { x: magState.snapX, y: magState.snapY };

        animateNodeTo(
          draggingNode.id,
          { x: draggingNode.position.x, y: draggingNode.position.y },
          landing,
          DEFAULT_MAG_CONFIG.snapAnimationMs,
          strongLanding ? DEFAULT_MAG_CONFIG.overshootPx : 0,
          // animateNodeTo 收尾时已自带 findBondFor，参数即形成的咬合（无则 null）
          (formed) => {
            if (formed) fireFlash("snap", formed);
          },
        );
      }

      draggingIdRef.current = null;
      setDraggingId(null);
      setMagState(IDLE_STATE);
      setReflowPlan(EMPTY_REFLOW);
      setBondState(IDLE_BOND_STATE);
      bondRef.current = null;
      bondOriginRef.current = null;
      brokenRef.current = false;
      mutedRef.current = new Set();
    },
    [
      enabled,
      magState.level,
      magState.targetId,
      magState.snapX,
      magState.snapY,
      reflowPlan,
      writeNodePos,
      animateNodeTo,
      animateNodesTo,
      fireFlash,
    ],
  );

  return {
    onNodeDrag,
    onNodeDragStart,
    onNodeDragStop,
    magState,
    draggingId,
    bondState,
    flash,
    reflowPlan,
  };
}
