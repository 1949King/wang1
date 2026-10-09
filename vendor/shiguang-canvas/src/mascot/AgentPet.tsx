/**
 * 桌宠主体：Q 版拟人狐狸「拾岚」的桌面形态。
 *
 * 对标参考实现（`vendor/AI-Canvas-tauri/src/components/shared/mascot/Mascot.tsx`）
 * ========================================================================
 * 两者是同一套骨架：**常驻 rAF 渲染循环 + ref 传参（不重建场景）+ 参数化动作**。
 * 三条关键经验直接沿用：
 *   1. 所有随帧变化的输入（status / theme / 拖拽受力）走 **ref**，不进 effect 依赖 ——
 *      否则每次状态变化都要重建整个 WebGL 场景，桌宠会闪一下并泄漏上下文。
 *   2. 帧率分档：待命 30fps、有动作 60fps。桌宠常驻画布，不能和生成任务抢 GPU。
 *   3. `document.hidden` 时完全不画。
 *
 * 不沿用的一条：参考实现有 48 层壳状毛发着色器（48 次绘制/帧）。狐狸是光面卡通风格，
 * 且本机 8GB 显存要与生成任务共存 —— 桌宠只允许占一档绘制。
 *
 * 「被驱动」而不是「放动画」
 * ========================
 * 每一帧的姿态都由真实状态算出来：
 *   - 节点在跑生成 → thinking（眯眼 + 视线急扫 + 尾巴快摆 + 蓝边缘光）
 *   - 弹了确认框在等你 → **awaiting（举手 + 蹦一下）** ← 最有价值的一态：你没动手时它能提醒你
 *   - 刚失败 / 刚成功 → shake / hop 一次性反应 + 红绿边缘光，1.8s 后回落
 *   - 其余 → idle（呼吸 + 眨眼 + 偶尔歪头 + 耳朵偶尔抖 + 视线游移）
 * 用户明确否定过「随机效果」；此处的随机只用于**同一状态内的自然变化**（几点眨、看向哪边），
 * 状态之间的切换完全由真实数据决定（`petActivity.ts` + `usePetStatus.ts`）。
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { PerspectiveCamera, Scene, WebGLRenderer } from "three";

import "./agentPet.css";
import { buildFox, FOX_BRAND, FOX_EYE_BASE_Y, foxColorToCss, type FoxRig, type FoxTheme } from "./foxScene";
import {
  BLINK_DURATION,
  EAR_FLICK_DURATION,
  EYE_MAX_ANGLE,
  EYE_POSES,
  FOLLOW_LERP,
  HEAD_MAX_ANGLE,
  REACTION_DURATIONS,
  STATUS_BUBBLES,
  STATUS_LABELS,
  STATUS_RIM_COLORS,
  getBlinkScaleY,
  getBreath,
  getEarDroop,
  getEarFlick,
  getReactionPose,
  getSquashWidth,
  getStatusEnergy,
  getTailSwing,
  nextBlinkGap,
  pickNextGazeIndex,
  planBlink,
  reactionForStatus,
  type MascotReactionKind,
  type PetStatus,
} from "./mascotMotion";
import { usePetDrag } from "./usePetDrag";

/** 两种形态的边长（px）。迷你形态 = 用户说的「收起它时就是一个专属形象」。 */
export const PET_SIZE = { expanded: 132, mini: 56 } as const;

/** 取景：整体 2.55 个世界单位；迷你形态镜头推进到只剩头部（含耳尖）。 */
const FIT = { body: 2.55, head: 1.75 };
const CAM_FOV = 34;
const CAM_TARGET_Y = { body: 0, head: 0.4 };
/** 根组基准高度（与 foxScene 里 `root.position.y` 一致）。 */
const ROOT_BASE_Y = -0.66;
/** 视线归一化半径（px）：鼠标离桌宠中心这么远就算「看到极限」。与桌宠尺寸无关。 */
const GAZE_RADIUS = 320;

const IDLE_FPS = 30;
const ACTIVE_FPS = 60;
/** 鼠标静止多久后不再跟手，改为自己东张西望。 */
const POINTER_IDLE_MS = 2600;
/** 歪头跟随系数 / 待命时两次歪头的间隔与保持时长。 */
const HEAD_ROLL_LERP = 0.05;
const TILT_MIN_GAP = 6;
const TILT_MAX_GAP = 11;
const TILT_HOLD = 1.3;
const TILT_ANGLE = 0.09;
/** 耳朵自动抖动间隔（秒）。 */
const EAR_FLICK_MIN_GAP = 2.6;
const EAR_FLICK_MAX_GAP = 7;

/** 视线落点（归一化 [-1,1]，与鼠标共用同一坐标系）。 */
const GAZE_POINTS: ReadonlyArray<readonly [number, number]> = [
  [0, 0],
  [0.6, 0.15],
  [-0.6, 0.15],
  [0.35, -0.4],
  [-0.35, -0.4],
  [0.75, 0.45],
  [-0.75, 0.45],
];

const clamp = (v: number, min: number, max: number) => Math.min(Math.max(v, min), max);
const rand = (min: number, max: number) => min + Math.random() * (max - min);

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
  /** 收起态：只留专属小形象（Agent 面板打开时自动收起，避免挡住画布） */
  mini: boolean;
  /** 单击：进入 Agent 对话画面 */
  onActivate: () => void;
  theme?: FoxTheme;
  /** 覆盖系统「减弱动态」偏好；不传则自动读取 `prefers-reduced-motion` */
  reduceMotion?: boolean;
}

export default function AgentPet({
  status,
  mini,
  onActivate,
  theme = "dark",
  reduceMotion,
}: AgentPetProps) {
  const prefersReduce = useReducedMotion();
  const reduceMotionResolved = reduceMotion ?? prefersReduce;
  const hostRef = useRef<HTMLSpanElement | null>(null);
  const size = mini ? PET_SIZE.mini : PET_SIZE.expanded;
  // 迷你形态 == Agent 侧栏已打开。默认落位要让开面板那一列（320 上限 + 18 间距），
  // 否则「一点桌宠，Agent 面板盖住桌宠」。用户手动拖过位置后不再自动挪动。
  const drag = usePetDrag(size, mini ? 338 : 0);
  const { rootRef, getDragForce, onPointerDown, consumeClick, dragging } = drag;

  // 随帧输入一律走 ref（见文件头第 1 条）
  const statusRef = useRef<PetStatus>(status);
  const themeRef = useRef<FoxTheme>(theme);
  const reduceRef = useRef(reduceMotion);
  const miniRef = useRef(mini);
  const draggingRef = useRef(dragging);
  const rigRef = useRef<FoxRig | null>(null);

  if (statusRef.current !== status) statusRef.current = status;
  themeRef.current = theme;
  reduceRef.current = reduceMotionResolved;
  miniRef.current = mini;
  draggingRef.current = dragging;

  // 场景生命周期：**只建一次**（依赖必须为空，否则桌宠会在状态变化时闪烁并泄漏 WebGL 上下文）
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const scene = new Scene();
    const camera = new PerspectiveCamera(CAM_FOV, 1, 0.1, 100);
    const renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearAlpha(0);
    host.appendChild(renderer.domElement);

    let rig: FoxRig;
    try {
      rig = buildFox(themeRef.current, scene);
    } catch (err) {
      // WebGL 不可用（软件渲染/上下文耗尽）时不该把画布带崩：诚实降级成「没有桌宠」+ 留一行日志
      console.warn("[AgentPet] 桌宠场景创建失败，已跳过：", err);
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
      return;
    }
    rigRef.current = rig;

    const resize = () => {
      const side = host.clientWidth || 1;
      renderer.setSize(side, side, false);
      camera.aspect = 1; // 容器恒为正方形
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    const fitDistance = (height: number) => height / 2 / Math.tan(((CAM_FOV * Math.PI) / 180) / 2);

    /* ── 动画状态（都在循环闭包里，不触发 React 重渲染） ── */
    let timeSec = 0;
    let lastMs = performance.now();
    let acc = 0;
    let rafId = 0;
    let disposed = false;

    let reaction: { kind: MascotReactionKind; start: number } | null = null;
    let observedStatus = statusRef.current;

    let blinkAt = timeSec + rand(1, 3);
    let blinkStart = -1;
    let blinkSecondAt = -1;
    let blinkWink = false;

    let tiltNextAt = rand(2, 6);
    let tiltHoldUntil = 0;
    let tiltTarget = 0;
    let headRoll = 0;

    let earFlickStart = -1;
    let earFlickNextAt = rand(1, 4);

    let gazeIndex = 0;
    let gazeNextAt = 0;
    let gazeTargetX = 0;
    let gazeTargetY = 0;
    let gazeX = 0;
    let gazeY = 0;

    let armAmount = 0;
    let leanZ = 0;
    let leanX = 0;
    let camY = CAM_TARGET_Y.body;
    let camDist = fitDistance(FIT.body);
    let rimR = 0;
    let rimG = 0;
    let rimB = 0;

    const pointer = { x: 0, y: 0, at: -Infinity };

    const onPointerMove = (e: PointerEvent) => {
      const el = hostRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0) return;
      // 以桌宠中心为原点、固定半径归一化：桌宠缩到 56px 时视线幅度也不会被放大
      pointer.x = clamp((e.clientX - (rect.left + rect.width / 2)) / GAZE_RADIUS, -1, 1);
      pointer.y = clamp(-(e.clientY - (rect.top + rect.height / 2)) / GAZE_RADIUS, -1, 1);
      pointer.at = performance.now();
    };
    window.addEventListener("pointermove", onPointerMove, { passive: true });

    camera.position.set(0, camY, camDist);
    camera.lookAt(0, camY, 0);

    const tick = (nowMs: number) => {
      if (disposed) return;
      rafId = window.requestAnimationFrame(tick);

      const dtRaw = Math.min((nowMs - lastMs) / 1000, 0.25);
      lastMs = nowMs;
      if (document.hidden) return; // 窗口不可见时完全不画
      timeSec += dtRaw;

      const currentStatus = statusRef.current;
      if (currentStatus !== observedStatus) {
        observedStatus = currentStatus;
        const kind = reactionForStatus(currentStatus);
        if (kind && !reduceRef.current) reaction = { kind, start: timeSec };
      }

      const isMini = miniRef.current;
      const running = Boolean(reaction) || draggingRef.current || currentStatus !== "idle";
      const minStep = 1 / (running ? ACTIVE_FPS : IDLE_FPS);
      acc += dtRaw;
      if (acc < minStep) return;
      acc = 0;

      const reduce = reduceRef.current;
      const energy = getStatusEnergy(currentStatus);

      /* ① 呼吸 + 一次性反应（跳跃/摇头）—— 两者叠加，反应结束后只剩呼吸 */
      const breath = getBreath(timeSec);
      let lift = 0;
      let squashY = breath;
      let yaw = 0;
      if (reaction) {
        const progress = (timeSec - reaction.start) / REACTION_DURATIONS[reaction.kind];
        if (progress >= 1) {
          reaction = null;
        } else {
          const pose = getReactionPose(reaction.kind, progress);
          lift = pose.lift;
          yaw = pose.yaw;
          squashY = breath * pose.squashY;
        }
      }
      if (reduce) {
        lift = 0;
        yaw = 0;
        squashY = breath;
      }

      /* ② 拖拽受力 → 身体滞后倾斜（松手弹簧回正） */
      const force = getDragForce();
      const targetLeanZ = force.active && !reduce ? force.x * 0.26 : 0;
      const targetLeanX = force.active && !reduce ? -force.y * 0.2 : 0;
      leanZ += (targetLeanZ - leanZ) * 0.18;
      leanX += (targetLeanX - leanX) * 0.18;

      rig.root.position.y = ROOT_BASE_Y + lift;
      const width = getSquashWidth(squashY);
      rig.root.scale.set(width, squashY, width);
      rig.root.rotation.z = leanZ + (reduce ? 0 : Math.sin(timeSec * 0.7) * 0.012);
      rig.root.rotation.x = leanX;

      /* ③ 接地阴影：跳起来时缩小变淡（阴影挂在 scene 上，不受 root 挤压拉伸影响） */
      const shadowScale = clamp(1 - lift * 1.7, 0.55, 1);
      rig.shadow.scale.set(shadowScale, shadowScale, 1);

      /* ④ 视线：鼠标优先（静止 2.6s 后放弃），否则自己东张西望 */
      const pointerFresh = nowMs - pointer.at < POINTER_IDLE_MS;
      if (pointerFresh) {
        gazeTargetX = pointer.x;
        gazeTargetY = pointer.y;
      } else if (timeSec > gazeNextAt) {
        gazeIndex = pickNextGazeIndex(gazeIndex, GAZE_POINTS.length, Math.random());
        const [gx, gy] = GAZE_POINTS[gazeIndex];
        gazeTargetX = gx;
        gazeTargetY = gy;
        gazeNextAt = timeSec + (energy > 0.5 ? rand(0.8, 1.4) : rand(1.8, 3.4));
      }
      const gazeLerp = pointerFresh ? FOLLOW_LERP : energy > 0.5 ? 0.2 : 0.06;
      gazeX += (gazeTargetX - gazeX) * gazeLerp;
      gazeY += (gazeTargetY - gazeY) * gazeLerp;

      /* ⑤ 头部：反应摇头 + 跟手轻转 + 歪头（待命偶尔来一次，思考/等待确认常驻） */
      if (currentStatus === "thinking" || currentStatus === "awaiting") {
        tiltTarget = Math.sin(timeSec * 0.9) * (currentStatus === "awaiting" ? 0.07 : 0.05);
      } else if (timeSec >= tiltNextAt) {
        tiltTarget = (Math.random() < 0.5 ? -1 : 1) * TILT_ANGLE;
        tiltHoldUntil = timeSec + TILT_HOLD;
        tiltNextAt = tiltHoldUntil + rand(TILT_MIN_GAP, TILT_MAX_GAP);
      } else if (timeSec > tiltHoldUntil) {
        tiltTarget = 0;
      }
      headRoll += (tiltTarget - headRoll) * HEAD_ROLL_LERP;
      rig.head.rotation.set(
        -gazeY * HEAD_MAX_ANGLE * 0.8,
        yaw + gazeX * HEAD_MAX_ANGLE,
        reduce ? 0 : headRoll,
      );

      /* ⑥ 眼睛：眼形随状态、视线驱动瞳孔、眨眼（含单眼 wink）覆盖在上面 */
      if (timeSec > blinkAt) {
        const plan = planBlink(Math.random(), Math.random());
        blinkStart = timeSec;
        blinkWink = plan.wink;
        blinkSecondAt = plan.double ? timeSec + BLINK_DURATION + 0.22 : -1;
        blinkAt = timeSec + nextBlinkGap(Math.random());
      }
      let blinkScale = 1;
      const bp = blinkStart >= 0 ? (timeSec - blinkStart) / BLINK_DURATION : 2;
      if (bp < 1) {
        blinkScale = getBlinkScaleY(bp);
      } else if (blinkSecondAt >= 0) {
        const bp2 = (timeSec - blinkSecondAt) / BLINK_DURATION;
        if (bp2 < 1) blinkScale = getBlinkScaleY(bp2);
        else blinkSecondAt = -1;
      }
      const winking = blinkWink && bp < 1;
      const eyePose = EYE_POSES[currentStatus];
      rig.eyeL.scale.set(1, eyePose.scaleY[0] * blinkScale, 1);
      rig.eyeR.scale.set(1, eyePose.scaleY[1] * (winking ? 1 : blinkScale), 1);
      rig.eyeL.rotation.z = eyePose.rotationZ[0];
      rig.eyeR.rotation.z = eyePose.rotationZ[1];
      rig.eyeL.rotation.y = rig.eyeR.rotation.y = gazeX * EYE_MAX_ANGLE;
      rig.eyeL.rotation.x = rig.eyeR.rotation.x = -gazeY * EYE_MAX_ANGLE * 0.7;
      rig.eyeL.position.y = FOX_EYE_BASE_Y + eyePose.offsetY[0] * 0.6;
      rig.eyeR.position.y = FOX_EYE_BASE_Y + eyePose.offsetY[1] * 0.6;
      rig.pupilL.scale.setScalar(eyePose.pupilScale);
      rig.pupilR.scale.setScalar(eyePose.pupilScale);
      rig.pupilL.position.set(gazeX * 0.05, gazeY * 0.045, 0);
      rig.pupilR.position.set(gazeX * 0.05, gazeY * 0.045, 0);

      /* ⑦ 耳朵：情绪基态倾角 + 偶尔双耳抖动 */
      const droop = getEarDroop(currentStatus);
      if (timeSec > earFlickNextAt) {
        earFlickStart = timeSec;
        earFlickNextAt = timeSec + rand(EAR_FLICK_MIN_GAP, EAR_FLICK_MAX_GAP);
      }
      let flick = 0;
      if (earFlickStart >= 0) {
        const fp = (timeSec - earFlickStart) / EAR_FLICK_DURATION;
        if (fp >= 1) earFlickStart = -1;
        else flick = getEarFlick(fp);
      }
      rig.earL.rotation.z = -0.22 - droop - flick * 0.5;
      rig.earR.rotation.z = 0.22 + droop + flick * 0.5;

      /* ⑧ 尾巴：能量决定振幅与频率，尖端走行波（甩起来才不像一根棍） */
      const tailFreq = 1.5 + 2.6 * energy;
      const swing = getTailSwing(timeSec, energy);
      rig.tail.rotation.y = swing;
      rig.tail.rotation.x = -lift * 0.9 + Math.sin(timeSec * 1.1) * 0.03;
      rig.tailSegments.forEach((seg, i) => {
        seg.position.x = Math.sin(timeSec * tailFreq * Math.PI * 2 - i * 0.35) * 0.03 * i;
      });

      /* ⑨ 手：awaiting 举手并轻轻晃动（「这步要我继续吗？」的身体语言） */
      const armTarget = reduce ? 0 : currentStatus === "awaiting" ? 1 : 0;
      armAmount += (armTarget - armAmount) * 0.14;
      const wave = armAmount > 0.4 ? Math.sin(timeSec * 6) * 0.14 * armAmount : 0;
      rig.armL.rotation.z = -0.35 + (-2.55 + 0.35) * armAmount - wave;
      rig.armR.rotation.z = 0.35 + (2.55 - 0.35) * armAmount + wave;

      /* ⑩ 边缘光承载状态色（低强度，不喧宾夺主） */
      const rim = STATUS_RIM_COLORS[currentStatus];
      rimR += (((rim >> 16) & 255) / 255 - rimR) * 0.08;
      rimG += (((rim >> 8) & 255) / 255 - rimG) * 0.08;
      rimB += ((rim & 255) / 255 - rimB) * 0.08;
      rig.rimLight.color.setRGB(rimR, rimG, rimB);
      rig.rimLight.intensity = 0.42 + energy * 0.55;

      /* ⑪ 取景：迷你形态镜头推进到只剩头部 —— 「收起来就是一个专属小形象」 */
      const targetCamY = isMini ? CAM_TARGET_Y.head : CAM_TARGET_Y.body;
      const targetDist = fitDistance(isMini ? FIT.head : FIT.body);
      camY += (targetCamY - camY) * 0.09;
      camDist += (targetDist - camDist) * 0.09;
      camera.position.set(0, camY, camDist);
      camera.lookAt(0, camY, 0);

      renderer.render(scene, camera);
    };

    rafId = window.requestAnimationFrame(tick);

    return () => {
      disposed = true;
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("pointermove", onPointerMove);
      ro.disconnect();
      const canvas = renderer.domElement;
      rigRef.current = null;
      rig.dispose();
      renderer.dispose();
      renderer.forceContextLoss(); // 不主动丢上下文会累积到「无法创建新上下文」
      if (canvas.parentNode === host) host.removeChild(canvas);
    };
  }, [getDragForce]);

  // 主题切换只调光，不重建场景
  useEffect(() => {
    rigRef.current?.setTheme(theme);
  }, [theme]);

  const handleClick = useCallback(() => {
    if (consumeClick()) return; // 刚拖过，这次 click 是拖拽收尾
    onActivate();
  }, [consumeClick, onActivate]);

  const bubble = mini ? null : STATUS_BUBBLES[status];

  return (
    <div
      ref={rootRef}
      className={`sg-pet${mini ? " sg-pet--mini" : ""}${dragging ? " sg-pet--dragging" : ""}`}
      data-state={status}
      data-sg-no-autoclick="1"
      style={
        {
          "--sg-pet-rim": foxColorToCss(STATUS_RIM_COLORS[status]),
          "--sg-pet-brand": foxColorToCss(FOX_BRAND.blue),
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
        title={`${STATUS_LABELS[status]}（单击打开 / 拖动移位 / 右键复位）`}
        aria-label={STATUS_LABELS[status]}
        onPointerDown={onPointerDown}
        onClick={handleClick}
        onContextMenu={(e) => {
          e.preventDefault();
          drag.resetPosition();
        }}
      >
        <span className="sg-pet-halo" aria-hidden="true" />
        <span ref={hostRef} className="sg-pet-stage" aria-hidden="true" />
        {mini ? null : <span className="sg-pet-name">拾岚</span>}
      </button>
    </div>
  );
}
