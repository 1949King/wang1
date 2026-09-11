/**
 * Stage3D 姿态重定向模块（模式 B 第三刀）
 * =========================================
 * 把 pose_worker.py 产出的 BlazePose 关键点 JSON 逐帧重定向为 JointPose，
 * 驱动 3D 导演台白模；并提供坏帧插值与 COCO18 可视化常量。
 *
 * 架构位置：Stage3D.tsx（UI/状态） → 本模块（纯函数） → riggedHumanoid.applyPoseResolved
 *
 * 坐标约定（正面全身参考视频，角色面向相机）：
 *  - 图像 x∈[0,1] 右正、y∈[0,1] 下正；角色左侧 = 图像右侧 = 世界 +X（镜像）；
 *  - BlazePose z 以髋中点为原点，越小越靠近相机 → 世界 +Z（身前）取 -z；
 *  - 角度约定与 riggedHumanoid.JOINT_LABELS 对齐：ShoulderX/HipX 正=前摆，
 *    lShoulderZ/lHipZ 正=外展，rShoulderZ/rHipZ 负=外展，肘/膝正=弯曲。
 */
import type { JointPose } from "./riggedHumanoid";

/** 单帧关键点（与后端 pose_worker.py 输出对齐） */
export type PoseFrame = {
  /** 源视频帧号 */
  frame: number;
  /** 采样时间（秒） */
  time: number;
  /** BlazePose 33 关键点 [x, y, z, vis]，无检出为空数组 */
  kps33: number[][];
  /** COCO 18 关键点 [x, y, vis]，无检出为空数组 */
  coco18: number[][];
};

/** 整段姿态轨迹（后端 JSON 规范化后） */
export type PoseTrack = {
  fps: number;
  duration: number;
  frameCount: number;
  width: number;
  height: number;
  frames: PoseFrame[];
};

/** COCO 18 关键点索引约定（对齐 stage3dControlNet.ts） */
export const COCO18_SKELETON: [number, number][] = [
  [0, 1], [0, 14], [0, 15], [1, 2], [1, 5], [1, 8], [1, 11],
  [2, 3], [2, 16], [3, 4], [5, 6], [5, 17], [6, 7],
  [8, 9], [9, 10], [11, 12], [12, 13], [14, 16], [15, 17],
];

/** COCO 18 关键点中文名（编辑小窗提示用） */
export const COCO18_CN: string[] = [
  "鼻", "颈", "右肩", "右肘", "右腕", "左肩", "左肘", "左腕",
  "右髋", "右膝", "右踝", "左髋", "左膝", "左踝",
  "右眼", "左眼", "右耳", "左耳",
];

/** 关键点可信阈值：低于此值按缺失处理 */
export const KP_VIS_THRESHOLD = 0.4;

/** 解析后端 pose JSON；结构不符时返回 null（诚实失败，不猜数据） */
export function parsePoseTrack(json: unknown): PoseTrack | null {
  if (!json || typeof json !== "object") return null;
  const raw = json as Record<string, unknown>;
  const framesRaw = Array.isArray(raw.frames) ? raw.frames : null;
  if (!framesRaw || framesRaw.length === 0) return null;
  const frames: PoseFrame[] = [];
  for (const f of framesRaw) {
    if (!f || typeof f !== "object") continue;
    const item = f as Record<string, unknown>;
    const coco18 = Array.isArray(item.coco18) ? (item.coco18 as number[][]) : [];
    const kps33 = Array.isArray(item.kps33) ? (item.kps33 as number[][]) : [];
    if (coco18.length === 0 && kps33.length === 0) continue;
    frames.push({
      frame: Number(item.frame) || 0,
      time: Number(item.time) || 0,
      kps33,
      coco18,
    });
  }
  if (frames.length === 0) return null;
  return {
    fps: Number(raw.fps) || 30,
    duration: Number(raw.duration) || 0,
    frameCount: frames.length,
    width: Number(raw.width) || 0,
    height: Number(raw.height) || 0,
    frames,
  };
}

/* ────────────────────────── 内部几何工具 ────────────────────────── */

const DEG = 180 / Math.PI;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** 取 COCO18 关键点；缺失或低可见度返回 null */
function kp(frame: PoseFrame, i: number): [number, number, number] | null {
  const p = frame.coco18[i];
  if (!p || p.length < 3) return null;
  const [x, y, v] = p;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (v < KP_VIS_THRESHOLD) return null;
  return [x, y, v];
}

/** 取 BlazePose 33 关键点的 z 深度（相对髋原点，小=近相机） */
function kpZ(frame: PoseFrame, blazeIdx: number): number | null {
  const p = frame.kps33[blazeIdx];
  if (!p || p.length < 4 || p[3] < KP_VIS_THRESHOLD) return null;
  const z = p[2];
  return Number.isFinite(z) ? z : null;
}

/**
 * 关节摆角（度）：母骨骼→子骨骼向量在「前-上」平面内的角度。
 * front = 世界Z 前分量（-Δz_blaze），up = 图像上分量（-Δy_img）。
 * 垂直下垂=0，前平举=+90，后摆为负。
 */
function swingX(front: number, up: number): number {
  const len = Math.hypot(front, up);
  if (len < 1e-6) return 0;
  return Math.atan2(front, up) * DEG;
}

/**
 * 关节侧展角（度）：图像平面内相对竖直向下的角度。
 * out 正 = 关节向世界 +X（角色左侧/图像右侧）展开。
 */
function abductZ(dxImg: number, dyImg: number): number {
  const len = Math.hypot(dxImg, dyImg);
  if (len < 1e-6) return 0;
  return Math.atan2(dxImg, dyImg) * DEG;
}

/** 三点内角（度）：a-b-c 在 b 处的夹角，输入为 2D 图像向量分量 */
function innerAngleDeg(
  ax: number, ay: number, bx: number, by: number,
  cx: number, cy: number,
): number {
  const v1x = ax - bx, v1y = ay - by;
  const v2x = cx - bx, v2y = cy - by;
  const l1 = Math.hypot(v1x, v1y);
  const l2 = Math.hypot(v2x, v2y);
  if (l1 < 1e-6 || l2 < 1e-6) return 180;
  const cos = clamp((v1x * v2x + v1y * v2y) / (l1 * l2), -1, 1);
  return Math.acos(cos) * DEG;
}

/* ────────────────────────── IK 求解 ────────────────────────── */

/**
 * 单帧 COCO18 + BlazePose z → JointPose（25 关节角度，度）。
 * 关键点缺失的关节沿用 prevPose 对应角度（保持动作连续），无 prev 则 0（中立）。
 */
export function solveFramePose(frame: PoseFrame, prevPose?: JointPose | null): JointPose {
  const fallback = prevPose ?? null;
  const get = (key: keyof JointPose): number =>
    (fallback && Number.isFinite(fallback[key]) ? fallback[key] : 0);

  const pose: JointPose = {
    spineX: get("spineX"), spineY: get("spineY"), spineZ: get("spineZ"),
    abdomenX: get("abdomenX"), abdomenY: get("abdomenY"), abdomenZ: get("abdomenZ"),
    headX: get("headX"), headY: get("headY"), headZ: get("headZ"),
    lShoulderX: get("lShoulderX"), lShoulderZ: get("lShoulderZ"),
    lElbowX: get("lElbowX"), lWristX: get("lWristX"),
    rShoulderX: get("rShoulderX"), rShoulderZ: get("rShoulderZ"),
    rElbowX: get("rElbowX"), rWristX: get("rWristX"),
    lHipX: get("lHipX"), lHipZ: get("lHipZ"),
    lKneeX: get("lKneeX"), lAnkleX: get("lAnkleX"),
    rHipX: get("rHipX"), rHipZ: get("rHipZ"),
    rKneeX: get("rKneeX"), rAnkleX: get("rAnkleX"),
  };

  // ── 躯干：肩中点 vs 髋中点 ──
  const lSh = kp(frame, 5), rSh = kp(frame, 2);
  const lHip = kp(frame, 11), rHip = kp(frame, 8);
  const nose = kp(frame, 0);
  if (lSh && rSh && lHip && rHip) {
    const mShX = (lSh[0] + rSh[0]) / 2, mShY = (lSh[1] + rSh[1]) / 2;
    const mHipX = (lHip[0] + rHip[0]) / 2, mHipY = (lHip[1] + rHip[1]) / 2;
    // 侧倾：图像右倾 = 角色左倾 = spineZ 负
    pose.spineZ = clamp(-abductZ(mShX - mHipX, mShY - mHipY) * 0.5, -40, 40);
    // 前倾：肩相对髋的前向深度差
    const zSh = (kpZ(frame, 11) ?? 0) + (kpZ(frame, 12) ?? 0);
    const zHip = (kpZ(frame, 23) ?? 0) + (kpZ(frame, 24) ?? 0);
    const dzWorld = -(zSh - zHip) / 2; // 肩在前为正
    const up = -(mShY - mHipY);
    if (up > 0.02) pose.spineX = clamp(swingX(dzWorld, up) * 0.7, -40, 40);
    // 扭转：肩线与髋线的图像角差（简化比例）
    const shoulderAng = Math.atan2(rSh[1] - lSh[1], rSh[0] - lSh[0]);
    const hipAng = Math.atan2(rHip[1] - lHip[1], rHip[0] - lHip[0]);
    pose.spineY = clamp((hipAng - shoulderAng) * DEG * 0.5, -50, 50);

    // ── 头：鼻相对肩中点 ──
    if (nose) {
      pose.headZ = clamp(-abductZ(nose[0] - mShX, nose[1] - mShY) * 0.6, -40, 40);
      const zNose = kpZ(frame, 0);
      if (zNose !== null) {
        const front = -(zNose - zSh / 2);
        const up2 = -(nose[1] - mShY);
        if (up2 > 0.01) pose.headX = clamp(swingX(front, up2) * 0.6, -45, 45);
      }
    }
  }

  // ── 四肢：肩/髋 → 肘/膝 → 腕/踝 ──
  // 肢体求解器：side=+1 左肢 / -1 右肢（镜像）
  const solveArm = (
    shIdx: number, elIdx: number, wrIdx: number,
    blazeSh: number, blazeEl: number,
    side: 1 | -1,
  ) => {
    const sh = kp(frame, shIdx), el = kp(frame, elIdx), wr = kp(frame, wrIdx);
    if (!sh || !el) return;
    // 侧展（图像平面角）
    const abd = abductZ(el[0] - sh[0], el[1] - sh[1]) * side;
    // 前后（BlazePose z 差 → 世界前分量）
    const zSh = kpZ(frame, blazeSh), zEl = kpZ(frame, blazeEl);
    if (zSh !== null && zEl !== null) {
      const front = -(zEl - zSh);
      const up = -(el[1] - sh[1]);
      const swing = swingX(front, up);
      if (side === 1) {
        pose.lShoulderZ = clamp(abd, -20, 170);
        pose.lShoulderX = clamp(swing, -170, 80);
      } else {
        pose.rShoulderZ = clamp(abd, -170, 20);
        pose.rShoulderX = clamp(swing, -170, 80);
      }
    } else {
      if (side === 1) pose.lShoulderZ = clamp(abd, -20, 170);
      else pose.rShoulderZ = clamp(abd, -170, 20);
    }
    // 肘弯曲 = 180 - 内角
    if (wr) {
      const bend = 180 - innerAngleDeg(sh[0], sh[1], el[0], el[1], wr[0], wr[1]);
      if (side === 1) pose.lElbowX = clamp(bend, 0, 145);
      else pose.rElbowX = clamp(bend, 0, 145);
    }
  };

  const solveLeg = (
    hipIdx: number, knIdx: number, anIdx: number,
    blazeHip: number, blazeKn: number, blazeAn: number, blazeFoot: number,
    side: 1 | -1,
  ) => {
    const hip = kp(frame, hipIdx), kn = kp(frame, knIdx), an = kp(frame, anIdx);
    if (!hip || !kn) return;
    const abd = abductZ(kn[0] - hip[0], kn[1] - hip[1]) * side;
    const zHip = kpZ(frame, blazeHip), zKn = kpZ(frame, blazeKn);
    if (zHip !== null && zKn !== null) {
      const front = -(zKn - zHip);
      const up = -(kn[1] - hip[1]);
      const swing = swingX(front, up);
      if (side === 1) {
        pose.lHipZ = clamp(abd, -20, 80);
        pose.lHipX = clamp(swing, -100, 90);
      } else {
        pose.rHipZ = clamp(abd, -80, 20);
        pose.rHipX = clamp(swing, -100, 90);
      }
    } else {
      if (side === 1) pose.lHipZ = clamp(abd, -20, 80);
      else pose.rHipZ = clamp(abd, -80, 20);
    }
    if (an) {
      const bend = 180 - innerAngleDeg(hip[0], hip[1], kn[0], kn[1], an[0], an[1]);
      if (side === 1) pose.lKneeX = clamp(bend, 0, 140);
      else pose.rKneeX = clamp(bend, 0, 140);
      // 踝：脚尖（foot_index）相对踝的前向角，脚水平=0
      const fi = kpZ(frame, blazeFoot);
      const zAn = kpZ(frame, blazeAn);
      if (fi !== null && zAn !== null) {
        const footPose = frame.kps33[blazeFoot];
        if (footPose && footPose.length >= 3) {
          const front = -(fi - zAn);
          const down = footPose[1] - an[1];
          const ankle = swingX(front, Math.max(down, 0.01)) - 90;
          if (side === 1) pose.lAnkleX = clamp(ankle, -40, 40);
          else pose.rAnkleX = clamp(ankle, -40, 40);
        }
      }
    }
  };

  solveArm(5, 6, 7, 11, 13, 1);   // 左臂（COCO 5/6/7，BlazePose 11/13）
  solveArm(2, 3, 4, 12, 14, -1);  // 右臂（COCO 2/3/4，BlazePose 12/14）
  solveLeg(11, 12, 13, 23, 25, 27, 31, 1);  // 左腿（COCO 11/12/13，BlazePose 23/25/27/31）
  solveLeg(8, 9, 10, 24, 26, 28, 32, -1);   // 右腿（COCO 8/9/10，BlazePose 24/26/28/32）

  return pose;
}

/** 两姿态线性插值（坏帧替换用） */
export function lerpJointPose(a: JointPose, b: JointPose, t: number): JointPose {
  const out = {} as JointPose;
  const keys = Object.keys(a) as (keyof JointPose)[];
  for (const k of keys) {
    out[k] = a[k] + (b[k] - a[k]) * t;
  }
  return out;
}

/** 帧的根驱动偏移：[dx, dy, dz]（世界米制，相对首帧；图像右=世界-X，下蹲 dy 为负） */
export function solveFrameRoot(track: PoseTrack, frameIdx: number, standHipY: number): [number, number, number] {
  const frame = track.frames[frameIdx];
  if (!frame) return [0, 0, 0];
  const lHip = kp(frame, 11), rHip = kp(frame, 8);
  if (!lHip || !rHip) return [0, 0, 0];
  const mHipX = (lHip[0] + rHip[0]) / 2;
  const mHipY = (lHip[1] + rHip[1]) / 2;
  const first = track.frames[0];
  const f0 = first ? (kp(first, 11) ?? null) : null;
  const f1 = first ? (kp(first, 8) ?? null) : null;
  const baseX = f0 && f1 ? (f0[0] + f1[0]) / 2 : mHipX;
  const H_REF = 1.6; // 归一化 y → 米的粗略换算（身高量级）
  return [
    (baseX - mHipX) * H_REF, // 图像右移 = 世界 -X
    -(mHipY - standHipY) * H_REF, // 髋更低（y 更大）→ 下蹲 dy 负
    0,
  ];
}

/** 全轨迹髋部最高点（站立基线，y 最小值）；无有效帧返回 0.5 中位估计 */
export function findStandHipY(track: PoseTrack): number {
  let best = Infinity;
  for (const f of track.frames) {
    const l = kp(f, 11), r = kp(f, 8);
    if (l && r) best = Math.min(best, (l[1] + r[1]) / 2);
  }
  return Number.isFinite(best) ? best : 0.5;
}

/** 帧是否可判定为「自动坏帧」（关键点全缺失） */
export function isFrameEmpty(frame: PoseFrame): boolean {
  return !frame || frame.coco18.length === 0;
}
