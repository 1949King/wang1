/**
 * LibTV 向3D 导演台：Dummy13 风格关节素模（可调）+ 群像站位 + 多机位。
 * 纯 three.js，无 R3F，便于 Qt WebEngine 稳定加载；无需导入外部模型。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import {
  applyPose,
  applyPoseResolved,
  applyPreset,
  boneKeyToRegion,
  chainBonesFor,
  defaultPose,
  EASING_LABELS,
  EASING_NAMES,
  endEffectorBoneKey,
  exportBVH,
  formationPositions,
  facingYForFormation,
  getPoseBones,
  GROUP_TEMPLATES,
  highlightBonesFor,
  HUMAN_PRESETS,
  isIkOnlyUnlockBone,
  JOINT_LABELS,
  limbDragMode,
  makeRiggedHumanoid,
  mergePose,
  MOTION_BREATHING,
  MOTION_IDLE_SWAY,
  MOTION_PRESETS,
  MOTION_WALK_GAIT,
  POSE_PRESETS,
  POSE_ROOT_OFFSET_Y,
  preloadBodyFigures,
  readPosePatchFromBone,
  resolveHitBoneKey,
  RIG_MESH_STYLE,
  sampleCompositeMotion,
  sampleKeyframes,
  sampleMotionFrames,
  solveChainIk,
  solveSegmentFk,
  yawToward,
  type EasingName,
  type FormationId,
  type HairStyle,
  type HumanVariant,
  type JointPose,
  type MotionPreset,
  type PoseKeyframe,
  type PosePresetId,
} from "./riggedHumanoid";
import { exportAllControlNetChannels } from "./stage3dControlNet";
import { fovToFocalLength, setHelpersVisible, syncCameraGizmos } from "./stage3dCamGizmo";
import {
  COCO18_CN,
  COCO18_SKELETON,
  findStandHipY,
  isFrameEmpty,
  KP_VIS_THRESHOLD,
  lerpJointPose,
  parsePoseTrack,
  solveFramePose,
  solveFrameRoot,
  type PoseFrame,
  type PoseTrack,
} from "./stage3dPoseRetarget";
import StageImportModal, { type StageImportResult } from "./StageImportModal";
import {
  capturePoseFrames,
  encodePoseVideo,
  planPoseVideoFrames,
} from "./stage3dPoseVideo";
import { useCanvasStore } from "./store";
import { uploadAssetToHost, poseExtractViaHost } from "./bridge";
import { publishStage3dArtifact, registerControlNetArtifacts, sendLatestArtifactToTimeline, useLatestStage3dArtifact } from "./stage3dArtifacts";
import { CameraRecorder } from "./cameraRecorder";
import { disposeObject3D, isWorldVisible, readRenderTargetToDataURL } from "./stage3dGlUtils";
import { Stage3dCastPanel, useStage3dCast } from "./stage3dCast";
import { useStage3dLighting } from "./stage3dLighting";
import CommandPalette, { isTypingTarget, type CommandItem } from "./CommandPalette";

export type StageActor = {
  id: string;
  name: string;
  kind: "actor" | "box" | "cylinder" | "sphere" | "half-dome" | "chair" | "table";
  color: string;
  position: [number, number, number];
  rotationY: number;
  scale: number;
  /** 体素骨骼关节角（度） */
  pose?: JointPose;
  /** 体型预设（仅 kind==="actor" 时生效） */
  variant?: HumanVariant;
  /** 发型预设（仅 kind==="actor" 时生效） */
  hairStyle?: HairStyle;
  /** 角色移动路线（点列 + 形状 + 速度 + 播放状态） */
  route?: {
    points: [number, number, number][];
    shape: "smooth" | "polyline";
    speed: "uniform" | "soft" | "custom";
    playing: boolean;
    /** 播放进度 0~1 */
    progress?: number;
  };
};

export type StageCamera = {
  id: string;
  name: string;
  position: [number, number, number];
  lookAt: [number, number, number];
  fov: number;
  /** 镜头景别（中景/特写/全景/近景等），由预设推断 */
  shotSize?: string;
  /** 路径点数组 —— 沿位置点 + 对应 lookAt 点插值 */
  pathPoints?: { pos: [number, number, number]; look: [number, number, number] }[];
  /** 路径播放时长（毫秒） */
  pathDuration?: number;
};

export type AspectId = "auto" | "21:9" | "16:9" | "4:3" | "1:1" | "3:4" | "9:16";

type ScenePersist = {
  actors: StageActor[];
  cameras: StageCamera[];
  fov: number;
  aspect: AspectId;
  activeCamId: string | null;
  lightPreset?: LightPreset;
  groundPreset?: GroundPreset;
  /** 姿势关键帧轨：actorId → 关键帧数组（每帧可携带 easing / bezier / interpolation） */
  poseTracks?: Record<string, PoseKeyframe[]>;
  selectedId?: string | null;
  sceneMode?: "solo" | "group";
  /** 全景图环境贴图 base64（equirectangular） */
  envEquirect?: string | null;
};

const STAGE_KEY = "shiguang-canvas:stage3d:v5";
const DRAG_THRESHOLD_PX = 6;
const GRID = 0.5;

const BONE_CN: Record<string, string> = {
  abdomen: "腰腹",
  spine: "胸",
  head: "头",
  lShoulder: "左臂",
  lElbow: "左肘",
  lWrist: "左腕",
  rShoulder: "右臂",
  rElbow: "右肘",
  rWrist: "右腕",
  lHip: "左腿",
  lKnee: "左膝",
  lAnkle: "左脚",
  rHip: "右腿",
  rKnee: "右膝",
  rAnkle: "右脚",
};

function isFrontMarkerHit(obj: THREE.Object3D): boolean {
  let p: THREE.Object3D | null = obj;
  while (p) {
    if (p.userData.frontMarker || p.userData.tint === "front") return true;
    p = p.parent;
  }
  return false;
}

type Props = {
  onCapture: (dataUrl: string, meta: {
    cameraName: string;
    fov: number;
    /** 反推的焦段 mm（全画幅近似） */
    focalLength: number;
    /** 镜头景别（中景/特写/全景/近景等） */
    shotSize: string;
    /** 当前画幅，如 9:16 */
    aspect: string;
    /** 默认光圈 */
    aperture: number;
  }) => void;
  onCaptureActorViews?: (
    views: { front: string; side: string; back: string },
    actorName: string,
  ) => void;
  /** 导出首尾帧回调：给视频生成管线用 */
  onExportFirstLast?: (
    firstFrame: string,
    lastFrame: string,
    meta: {
      cameraName: string;
      totalPoints: number;
      aspect: string;
      resolution?: string;
      referenceImage?: string;
      referenceActor?: string;
      /** 参考视频（motion-ref 模式 A）inbox URL；空串表示未挂载 */
      referenceVideoUrl?: string;
    },
  ) => void;
  /** 批量导出分镜回调：给 V2 多机位编排 + V3 完整时长管线用 */
  onExportBatch?: (
    segments: Array<{
      cameraName: string;
      firstFrame: string;
      lastFrame: string;
      referenceImage?: string;
      referenceActor?: string;
      totalPoints: number;
      resolution: string;
      promptHint: string;
    }>,
  ) => void;
  onStatus: (msg: string) => void;
};

function uid(p: string) {
  return `${p}_${Math.random().toString(36).slice(2, 8)}`;
}

/** 光源预设 */
export type LightPreset = "studio-soft" | "hard" | "golden-hour" | "neutral";

const LIGHT_PRESETS: Record<LightPreset, {
  label: string;
  bg: string;
  fog: string;
  hemiSky: string;
  hemiGround: string;
  hemiIntensity: number;
  dirColor: string;
  dirIntensity: number;
  dirPos: [number, number, number];
}> = {
  "studio-soft": {
    label: "柔光棚",
    bg: "#1a2533",
    fog: "#1a2533",
    hemiSky: "#dbeaff",
    hemiGround: "#334455",
    hemiIntensity: 1.0,
    dirColor: "#ffffff",
    dirIntensity: 0.7,
    dirPos: [2, 6, 4],
  },
  hard: {
    label: "硬光",
    bg: "#0a0a0a",
    fog: "#0a0a0a",
    hemiSky: "#888888",
    hemiGround: "#333333",
    hemiIntensity: 0.35,
    dirColor: "#ffffff",
    dirIntensity: 1.7,
    dirPos: [6, 10, 2],
  },
  "golden-hour": {
    label: "黄金时刻",
    bg: "#3d2817",
    fog: "#3d2817",
    hemiSky: "#ffcc99",
    hemiGround: "#553322",
    hemiIntensity: 0.9,
    dirColor: "#ffbb77",
    dirIntensity: 1.3,
    dirPos: [5, 3, 2],
  },
  neutral: {
    label: "默认",
    bg: "#0c1118",
    fog: "#0c1118",
    hemiSky: "#b8d4ff",
    hemiGround: "#1a1a1a",
    hemiIntensity: 0.85,
    dirColor: "#ffffff",
    dirIntensity: 1.1,
    dirPos: [4, 8, 3],
  },
};

/** 地面纹理预设（Canvas 程序化生成） */
export type GroundPreset = "studio-dark" | "concrete" | "wood" | "grass";

function makeGroundTexture(preset: GroundPreset): THREE.CanvasTexture | null {
  if (preset === "studio-dark") return null;
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;

  if (preset === "concrete") {
    ctx.fillStyle = "#5a5a5a";
    ctx.fillRect(0, 0, size, size);
    for (let i = 0; i < 2000; i++) {
      ctx.fillStyle = `rgba(${Math.random() * 100},${Math.random() * 100},${Math.random() * 100},${Math.random() * 0.3})`;
      ctx.fillRect(Math.random() * size, Math.random() * size, 2, 2);
    }
    // 细纹
    ctx.strokeStyle = "rgba(80,80,80,0.4)";
    ctx.lineWidth = 1;
    for (let i = 0; i < 10; i++) {
      ctx.beginPath();
      ctx.moveTo(0, Math.random() * size);
      ctx.lineTo(size, Math.random() * size);
      ctx.stroke();
    }
  } else if (preset === "wood") {
    const colors = ["#8b5a2b", "#6b4423", "#a0632f", "#7a4c24"];
    const plankH = size / 8;
    for (let y = 0; y < 8; y++) {
      ctx.fillStyle = colors[y % colors.length];
      ctx.fillRect(0, y * plankH, size, plankH);
      ctx.strokeStyle = "rgba(30,20,10,0.5)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, (y + 1) * plankH);
      ctx.lineTo(size, (y + 1) * plankH);
      ctx.stroke();
      // 木纹细节
      ctx.strokeStyle = `rgba(40,25,10,0.3)`;
      ctx.lineWidth = 0.5;
      for (let i = 0; i < 5; i++) {
        ctx.beginPath();
        const midY = y * plankH + plankH / 2;
        ctx.moveTo(0, midY + (Math.random() - 0.5) * plankH * 0.6);
        ctx.bezierCurveTo(size / 3, midY + (Math.random() - 0.5) * plankH * 0.8, (size * 2) / 3, midY + (Math.random() - 0.5) * plankH * 0.8, size, midY + (Math.random() - 0.5) * plankH * 0.6);
        ctx.stroke();
      }
    }
  } else if (preset === "grass") {
    ctx.fillStyle = "#3d7a2a";
    ctx.fillRect(0, 0, size, size);
    for (let i = 0; i < 8000; i++) {
      const g = 80 + Math.random() * 100;
      ctx.fillStyle = `rgba(${40 + Math.random() * 30},${g},${30 + Math.random() * 30},${0.3 + Math.random() * 0.4})`;
      ctx.fillRect(Math.random() * size, Math.random() * size, 1, 1 + Math.random() * 2);
    }
    // 草丛纹理
    ctx.strokeStyle = "rgba(50,120,40,0.4)";
    ctx.lineWidth = 0.5;
    for (let i = 0; i < 300; i++) {
      ctx.beginPath();
      const x = Math.random() * size;
      const y = Math.random() * size;
      ctx.moveTo(x, y);
      ctx.lineTo(x + (Math.random() - 0.5) * 4, y - 4 - Math.random() * 4);
      ctx.stroke();
    }
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(8, 8);
  tex.anisotropy = 8;
  return tex;
}

function snap(v: number) {
  return Math.round(v / GRID) * GRID;
}

function migrateActors(list: StageActor[]): StageActor[] {
  return list.map((a) => {
    const kind = a.kind ?? (a.pose ? "actor" : "box");
    const base = { ...a, kind } as StageActor;
    if (kind === "actor") {
      const patch: Partial<StageActor> = {};
      if (!base.pose) patch.pose = defaultPose();
      if (!base.variant) patch.variant = "male_std";
      if (!base.hairStyle) patch.hairStyle = "none";
      return { ...base, ...patch };
    }
    return base;
  });
}

/** 旧存档可能只有几何体、无人模 — 补一个默认可调姿势素模 */
function ensureActorScene(actors: StageActor[]): StageActor[] {
  const migrated = migrateActors(actors);
  if (migrated.some((a) => a.kind === "actor")) return migrated;
  const solo = defaultActors()[0];
  return solo ? [{ ...solo, id: uid("a"), name: "角色 A" }, ...migrated] : migrated;
}

function pickInitialSelection(actors: StageActor[], savedId: string | null | undefined): string | null {
  if (savedId && actors.some((a) => a.id === savedId)) return savedId;
  return actors.find((a) => a.kind === "actor")?.id ?? actors[0]?.id ?? null;
}

function loadScene(): ScenePersist | null {
  try {
    const raw =
      localStorage.getItem(STAGE_KEY) ||
      localStorage.getItem("shiguang-canvas:stage3d:v4") ||
      localStorage.getItem("shiguang-canvas:stage3d:v2") ||
      localStorage.getItem("shiguang-canvas:stage3d:v1");
    if (!raw) return null;
    const data = JSON.parse(raw) as ScenePersist;
    if (Array.isArray(data.actors)) data.actors = migrateActors(data.actors);
    return data;
  } catch {
    return null;
  }
}

function actorPose(a: StageActor): JointPose {
  return a.pose ? mergePose(defaultPose(), a.pose) : defaultPose();
}

function makeProp(kind: StageActor["kind"], color: string): THREE.Object3D {
  if (kind === "actor") {
    return makeRiggedHumanoid(color, defaultPose());
  }
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.6 });
  if (kind === "box") {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.6, 0.6), mat);
    mesh.position.y = 0.3;
    mesh.castShadow = true;
    return mesh;
  }
  if (kind === "cylinder") {
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.8, 16), mat);
    mesh.position.y = 0.4;
    mesh.castShadow = true;
    return mesh;
  }
  if (kind === "sphere") {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.35, 24, 16), mat);
    mesh.position.y = 0.35;
    mesh.castShadow = true;
    return mesh;
  }
  if (kind === "half-dome") {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.5, 24, 16, 0, Math.PI * 2, 0, Math.PI / 2), mat);
    mesh.position.y = 0;
    mesh.castShadow = true;
    return mesh;
  }
  if (kind === "chair") {
    const group = new THREE.Group();
    const seatMat = new THREE.MeshStandardMaterial({ color, roughness: 0.7 });
    const legMat = new THREE.MeshStandardMaterial({ color: "#3a3a3a", roughness: 0.5 });
    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.05, 0.5), seatMat);
    seat.position.y = 0.45;
    seat.castShadow = true;
    seat.userData.propBody = true;
    group.add(seat);
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.04), seatMat);
    back.position.set(0, 0.72, -0.22);
    back.castShadow = true;
    back.userData.propBody = true;
    group.add(back);
    for (const [x, z] of [[-0.2, -0.2], [0.2, -0.2], [-0.2, 0.2], [0.2, 0.2]]) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.45, 8), legMat);
      leg.position.set(x, 0.225, z);
      leg.castShadow = true;
      group.add(leg);
    }
    return group;
  }
  if (kind === "table") {
    const group = new THREE.Group();
    const topMat = new THREE.MeshStandardMaterial({ color, roughness: 0.5 });
    const legMat = new THREE.MeshStandardMaterial({ color: "#3a3a3a", roughness: 0.4 });
    const top = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.06, 0.7), topMat);
    top.position.y = 0.75;
    top.castShadow = true;
    top.userData.propBody = true;
    group.add(top);
    for (const [x, z] of [[-0.5, -0.28], [0.5, -0.28], [-0.5, 0.28], [0.5, 0.28]]) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.75, 0.05), legMat);
      leg.position.set(x, 0.375, z);
      leg.castShadow = true;
      group.add(leg);
    }
    return group;
  }
  const fallback = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), mat);
  fallback.position.y = 0.25;
  fallback.castShadow = true;
  return fallback;
}

function defaultActors(): StageActor[] {
  // 默认单人素模（LibTV 导演台常见起步）；群像用模板一键生成
  return [
    {
      id: uid("a"),
      name: "角色 A",
      kind: "actor",
      color: "#3b82f6",
      position: [0, 0, 0],
      rotationY: 0,
      scale: 1,
      pose: applyPreset("idle"),
    },
  ];
}

const CROWD_COLORS = ["#3b82f6", "#ef4444", "#eab308", "#22c55e", "#a855f7"];
/** 2026-10-19：高亮色**复用实例**，禁止在遍历里 new Color（替换 material.emissive 引用会让材质版本变化
 *  ⇒ shader 重编译；用户实测「鼠标划过模型时闪出巨大脚残影」，GPU 合成降级环境下极易错乱）。 */
const HL_SEL = new THREE.Color("#f59e0b");
const HL_HOVER = new THREE.Color("#fbbf24");
const HL_ACTIVE = new THREE.Color("#1d4ed8");
const HL_NONE = new THREE.Color("#000000");

function makeCrowdActors(count: number, formation: FormationId): StageActor[] {
  const slots = formationPositions(count, formation);
  // 按索引轮流分配不同姿势/体型，避免全员站桩
  const CROWD_POSES: PosePresetId[] = [
    "idle", "wave", "think", "hands_hips", "cross_arms",
    "phone", "surprised", "cheer", "step_turn", "point",
  ];
  const CROWD_VARIANTS: HumanVariant[] = [
    "male_std", "female_std", "male_heavy", "male_thin", "child",
  ];
  return slots.map((pos, i) => ({
    id: uid("a"),
    name: `角色 ${String.fromCharCode(65 + i)}`,
    kind: "actor" as const,
    color: CROWD_COLORS[i % CROWD_COLORS.length],
    position: pos,
    rotationY: facingYForFormation(pos, formation),
    scale: 1,
    pose: applyPreset(CROWD_POSES[i % CROWD_POSES.length]),
    variant: CROWD_VARIANTS[i % CROWD_VARIANTS.length],
    hairStyle: i % 4 === 0 ? "short" : i % 4 === 1 ? "long" : i % 4 === 2 ? "none" : "round",
  }));
}

function defaultCameras(): StageCamera[] {
  return [
    {
      id: uid("cam"),
      name: "机位 1",
      position: [0, 1.6, 4.5],
      lookAt: [0, 1.2, 0],
      fov: 45,
    },
  ];
}

/** 姿势关键帧时间轴小组件 —— 组件内维护一个时间戳输入框 + 关键帧列表 + 逐帧缓动/贝塞尔 */
function PoseTimeline({
  track,
  onRecord,
  onDelete,
  onPatch,
  onPlay,
  onStop,
}: {
  track: PoseKeyframe[];
  onRecord: (t: number) => void;
  onDelete: (t: number) => void;
  onPatch: (t: number, patch: Partial<PoseKeyframe>) => void;
  onPlay: () => void;
  onStop: () => void;
}) {
  const [t, setT] = useState(0);
  const sorted = [...track].sort((a, b) => a.t - b.t);
  return (
    <div className="stage3d-pose-timeline">
      <div className="field compact">
        <label>时间戳 (ms)</label>
        <input
          type="number"
          min={0}
          step={100}
          value={t}
          onChange={(e) => setT(Math.max(0, Number(e.target.value) || 0))}
        />
        <button type="button" className="btn" onClick={() => onRecord(t)}>存帧</button>
        <button type="button" className="btn" onClick={() => setT(sorted.length ? sorted[sorted.length - 1].t + 500 : 0)}>+0.5s</button>
      </div>
      {sorted.length > 0 ? (
        <div className="stage3d-pose-track">
          <div className="stage3d-pose-track-bar">
            {sorted.map((k) => (
              <button
                key={k.t}
                type="button"
                className="stage3d-pose-key"
                title={`t=${k.t}ms · 点击定位 · 点右键删除`}
                onContextMenu={(e) => {
                  e.preventDefault();
                  onDelete(k.t);
                }}
                onClick={() => setT(k.t)}
                style={{ left: `${sorted.length > 1 ? (k.t - sorted[0].t) / (sorted[sorted.length - 1].t - sorted[0].t) * 100 : 0}%` }}
              >
                {k.t}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="muted tiny">无关键帧</p>
      )}
      {sorted.length > 0 ? (
        <div className="stage3d-pose-list">
          {sorted.map((k) => (
            <div className="stage3d-pose-row" key={k.t}>
              <button type="button" className="muted tiny" onClick={() => setT(k.t)}>t={k.t}</button>
              <select
                value={k.easing ?? "ease_in_out"}
                onChange={(e) => onPatch(k.t, { easing: e.target.value as EasingName })}
              >
                {EASING_NAMES.map((n) => (
                  <option key={n} value={n}>{EASING_LABELS[n]}</option>
                ))}
              </select>
              <select
                value={k.interpolation ?? "linear"}
                onChange={(e) => onPatch(k.t, { interpolation: e.target.value as PoseKeyframe["interpolation"] })}
              >
                <option value="linear">线性</option>
                <option value="bezier">贝塞尔</option>
                <option value="step">阶跃</option>
              </select>
              {k.interpolation === "bezier" ? (
                <span className="stage3d-pose-bezier">
                  控制点
                  <input
                    type="number"
                    step={0.05}
                    value={k.bezierC1 ? k.bezierC1[1] : 0.33}
                    onChange={(e) => onPatch(k.t, { bezierC1: [0, Number(e.target.value) || 0] })}
                  />
                  <input
                    type="number"
                    step={0.05}
                    value={k.bezierC2 ? k.bezierC2[1] : 0.67}
                    onChange={(e) => onPatch(k.t, { bezierC2: [0, Number(e.target.value) || 0] })}
                  />
                </span>
              ) : null}
              <button type="button" className="btn" onClick={() => onDelete(k.t)}>删</button>
            </div>
          ))}
        </div>
      ) : null}
      <div className="seg">
        <button type="button" className="on" onClick={onPlay} disabled={sorted.length < 2}>▶ 播放循环</button>
        <button type="button" onClick={onStop}>■ 停止</button>
      </div>
    </div>
  );
}

export default function Stage3D({ onCapture, onCaptureActorViews, onExportFirstLast, onExportBatch, onStatus }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    controls: OrbitControls;
    transform: TransformControls;
    objects: Map<string, THREE.Object3D>;
    camHelpers: Map<string, THREE.Object3D>;
    raycaster: THREE.Raycaster;
    ground: THREE.Mesh;
    axisHelper: THREE.AxesHelper;
    hemi: THREE.HemisphereLight;
    dir: THREE.DirectionalLight;
    ikTrail: THREE.Line;
    ikRubber: THREE.Line;
    ikTrailCount: number;
    fitDirectorFraming: () => void;
  } | null>(null);

  const persisted = loadScene();
  const initialActors = persisted?.actors?.length
    ? ensureActorScene(persisted.actors)
    : defaultActors();
  const initialCams = persisted?.cameras?.length ? persisted.cameras : defaultCameras();
  const [actors, setActors] = useState<StageActor[]>(initialActors);
  const [cameras, setCameras] = useState<StageCamera[]>(initialCams);
  const [selectedId, setSelectedId] = useState<string | null>(
    pickInitialSelection(initialActors, persisted?.selectedId),
  );
  const [sceneMode, setSceneMode] = useState<"solo" | "group">(
    persisted?.sceneMode ??
      (initialActors.filter((a) => a.kind === "actor").length >= 2 ? "group" : "solo"),
  );
  const [activeCamId, setActiveCamId] = useState<string | null>(
    persisted?.activeCamId ?? initialCams[0]?.id ?? null,
  );
  const [viewMode, setViewMode] = useState<"director" | "camera">("director");
  const directorCamRef = useRef<{
    pos: [number, number, number];
    target: [number, number, number];
  } | null>(null);
  const prevViewModeRef = useRef<"director" | "camera">("director");
  const [cmdOpen, setCmdOpen] = useState(false);
  const cmdOpenRef = useRef(false);
  cmdOpenRef.current = cmdOpen;
  const [tool, setTool] = useState<"move" | "rotate" | "scale">("move");
  const [editMode, setEditMode] = useState<"actor" | "joint">("joint");
  const [selectedBoneKey, setSelectedBoneKey] = useState<string | null>(null);
  const [hoveredBoneKey, setHoveredBoneKey] = useState<string | null>(null);
  const [fov, setFov] = useState(persisted?.fov ?? 45);
  const [aspect, setAspect] = useState<AspectId>((persisted?.aspect as AspectId) || "9:16");
  const [lightPreset, setLightPreset] = useState<LightPreset>(persisted?.lightPreset ?? "neutral");
  const [groundPreset, setGroundPreset] = useState<GroundPreset>(persisted?.groundPreset ?? "studio-dark");
  const [poseTracks, setPoseTracks] = useState<Record<string, PoseKeyframe[]>>(persisted?.poseTracks ?? {});
  /** 选了"从X到Y的路径"时保存两个相机 id */
  const [pathFromId, setPathFromId] = useState<string | null>(null);
  const pathRafRef = useRef<number | null>(null);
  const poseRafRef = useRef<number | null>(null);
  /** 一键运镜：跟踪主体（角色 id，空=用当前 lookAt） */
  const [trackTargetId, setTrackTargetId] = useState<string>("");
  /** 一键运镜：轨迹范围 0~100% */
  const [moveRange, setMoveRange] = useState(100);
  /** 录制运镜：采样用户手动拖动的相机轨迹（纯相机层，不触模型包） */
  const camRecRef = useRef<CameraRecorder | null>(null);
  const [camRecording, setCamRecording] = useState(false);
  const ASPECTS: { id: AspectId; label: string }[] = [
    { id: "auto", label: "自适应" },
    { id: "21:9", label: "21:9" },
    { id: "16:9", label: "16:9" },
    { id: "4:3", label: "4:3" },
    { id: "1:1", label: "1:1" },
    { id: "3:4", label: "3:4" },
    { id: "9:16", label: "9:16" },
  ];

  const CAM_PRESETS: { id: string; label: string; pos: [number, number, number]; look: [number, number, number]; fov: number; shotSize: string }[] = [
    { id: "front_m", label: "正面中景", pos: [0, 1.6, 4.2], look: [0, 1.2, 0], fov: 40, shotSize: "中景" },
    { id: "front_c", label: "正面特写", pos: [0, 1.55, 2.2], look: [0, 1.45, 0], fov: 35, shotSize: "特写" },
    { id: "front_w", label: "正面全景", pos: [0, 2.2, 7], look: [0, 1, 0], fov: 50, shotSize: "全景" },
    { id: "side_t", label: "侧面跟拍", pos: [4, 1.5, 0.5], look: [0, 1.2, 0], fov: 42, shotSize: "中景" },
    { id: "side_c", label: "侧面近景", pos: [2.4, 1.5, 0.2], look: [0, 1.35, 0], fov: 38, shotSize: "近景" },
    { id: "back_m", label: "背面中景", pos: [0, 1.6, -4], look: [0, 1.2, 0], fov: 40, shotSize: "中景" },
    { id: "top_w", label: "俯拍全景", pos: [0, 8, 0.1], look: [0, 0, 0], fov: 48, shotSize: "全景" },
    { id: "top_45", label: "45° 俯拍", pos: [3.5, 5, 3.5], look: [0, 1, 0], fov: 45, shotSize: "中景" },
    { id: "low", label: "低角度仰拍", pos: [0.2, 0.4, 3.5], look: [0, 1.5, 0], fov: 48, shotSize: "仰拍" },
    { id: "low_w", label: "低角度广角", pos: [0.3, 0.35, 4.5], look: [0, 1.4, 0], fov: 65, shotSize: "仰拍广角" },
    { id: "ots_l", label: "过肩镜头", pos: [-1.2, 1.55, 2.4], look: [0.4, 1.4, 0], fov: 36, shotSize: "过肩" },
    { id: "ots_r", label: "过肩镜头 (右)", pos: [1.2, 1.55, 2.4], look: [-0.4, 1.4, 0], fov: 36, shotSize: "过肩" },
    { id: "bird", label: "鸟瞰", pos: [0, 12, 0.01], look: [0, 0, 0], fov: 55, shotSize: "鸟瞰" },
    { id: "dutch", label: "荷兰角", pos: [1.5, 1.4, 3.2], look: [0, 1.3, 0], fov: 42, shotSize: "荷兰角" },
  ];

  const ACTOR_PRESETS: { id: string; label: string; scale: number; color: string; variant: HumanVariant; hairStyle: HairStyle }[] = [
    { id: "white", label: "男·标准", scale: 1, color: "#f1f5f9", variant: "male_std", hairStyle: "short" },
    { id: "red", label: "男·标准 2", scale: 1, color: "#ef4444", variant: "male_std", hairStyle: "short" },
    { id: "pink", label: "女·标准", scale: 0.96, color: "#f472b6", variant: "female_std", hairStyle: "long" },
    { id: "blue", label: "男·胖", scale: 1.05, color: "#1d4ed8", variant: "male_heavy", hairStyle: "short" },
    { id: "yellow", label: "男·瘦", scale: 1, color: "#eab308", variant: "male_thin", hairStyle: "none" },
    { id: "purple", label: "女·标准 2", scale: 0.98, color: "#a855f7", variant: "female_std", hairStyle: "short" },
    { id: "green", label: "男·标准 3", scale: 1, color: "#22c55e", variant: "male_std", hairStyle: "none" },
    { id: "black", label: "男·标准 4", scale: 1.02, color: "#334155", variant: "male_std", hairStyle: "short" },
    { id: "chibi", label: "儿童", scale: 0.58, color: "#14b8a6", variant: "child", hairStyle: "round" },
  ];

  const [railTab, setRailTab] = useState<"frame" | "actor" | "camera" | "shot" | "image">("actor");
  /** 角色面板四子标签页（属性/姿势/动作/路线） */
  const [actorTab, setActorTab] = useState<"attr" | "pose" | "motion" | "route">("pose");
  const motionFileRef = useRef<HTMLInputElement | null>(null);
  /** 参考视频驱动（motion-ref 模式 A）：上传到宿主 inbox 后的引用，生成视频时作为动作参考条件 */
  const [motionRefVideo, setMotionRefVideo] = useState<{ url: string; name: string } | null>(null);
  const motionRefFileRef = useRef<HTMLInputElement | null>(null);
  /** 模式 B 姿态解析结果：关键点 JSON 摘要（帧数/时长/URL），第三刀驱动白模的直接输入 */
  const [motionPoseData, setMotionPoseData] = useState<{
    frames: number;
    duration: number;
    fps: number;
    url: string;
  } | null>(null);
  const [poseBusy, setPoseBusy] = useState(false);
  /* ── 模式 B 第三刀：关键点 → 白模 IK 时序驱动状态 ── */
  /** 已解析的姿态轨迹（含用户修正；ref 存活跨渲染，驱动循环直接读） */
  const poseTrackRef = useRef<PoseTrack | null>(null);
  /** 驱动开关：开启后选中 actor 由姿态轨迹逐帧驱动 */
  const [poseDriveOn, setPoseDriveOn] = useState(false);
  /** 播放开关（驱动开启时生效） */
  const [posePlaying, setPosePlaying] = useState(false);
  /** 当前帧索引（UI 显示与叠加小窗同步） */
  const [poseFrameIdx, setPoseFrameIdx] = useState(0);
  /** 手动标记的坏帧集合（播放时线性插值跳过） */
  const [poseBadFrames, setPoseBadFrames] = useState<Set<number>>(new Set());
  /** 关键点编辑模式：叠加小窗可拖拽修正 */
  const [poseEditOn, setPoseEditOn] = useState(false);
  /* ── 模式 B 第四刀：录制白模视频（逐帧采集 → 后端 FFmpeg 合成 → reference_video） ── */
  /** 录制进行中（防重复点击） */
  const [poseVideoBusy, setPoseVideoBusy] = useState(false);
  /** 录制进度（已采集帧 / 总帧），0 表示未在录制 */
  const [poseVideoProgress, setPoseVideoProgress] = useState(0);
  /** 驱动播放 rAF 句柄 */
  const poseDriveRafRef = useRef<number | null>(null);
  /** 播放起始时间戳（帧推进基准） */
  const poseDriveT0Ref = useRef(0);
  /** 已求解姿态缓存（帧号 → JointPose；关键点修正后按帧失效） */
  const poseSolvedCacheRef = useRef<Map<number, JointPose>>(new Map());
  /** 髋部站立基线 y（root 高度换算） */
  const poseStandHipYRef = useRef(0.5);
  /** 驱动前 actor 的原始位置（关闭驱动时还原） */
  const poseDriveBasePosRef = useRef<[number, number, number] | null>(null);
  /** OpenPose 参考小窗 canvas */
  const poseOverlayCanvasRef = useRef<HTMLCanvasElement | null>(null);
  /** 小窗拖拽会话（命中关键点索引 + 修正中坐标） */
  const poseDragKpRef = useRef<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [refImage, setRefImage] = useState<string | null>(null);
  const [scenePrompt, setScenePrompt] = useState("");
  const [snapOn, setSnapOn] = useState(true);
  /** equirectangular 全景图 base64 dataURL，为 null 时用纯色背景 */
  const [envEquirect, setEnvEquirect] = useState<string | null>(persisted?.envEquirect ?? null);
  /** 环境贴图 PMREM 结果（用于 scene.environment IBL 光照） */
  const envPMREMRef = useRef<THREE.Texture | null>(null);
  /** 全景图天空球（默认隐藏，加载 env 后显示） */
  const envSphereRef = useRef<THREE.Mesh | null>(null);
  /** Bloom 强度（0 = 关闭后处理） */
  const [bloomStrength, setBloomStrength] = useState(0);
  const bloomStrengthRef = useRef(0);
  /** EffectComposer（Bloom 后处理） */
  const composerRef = useRef<EffectComposer | null>(null);
  const undoRef = useRef<StageActor[] | null>(null);
  /** 2026-10-19（解冻 stage3d-core）：角色渲染尺寸自检的节流时间戳（避免每帧遍历 GLB 树） */
  const actorAuditAtRef = useRef(0);
  /** 每个 actor 当前正在播放的 MotionPreset 列表（tick 闭包用 ref 避免 state 陈旧） */
  const activeMotionsRef = useRef<Map<string, MotionPreset[]>>(new Map());
  /** 每个 actor 的 motion 播放起点时间（用于 elapsed 计算） */
  const motionStartRef = useRef<Map<string, number>>(new Map());
  /** 每个 actor 启用 motion 前的原始 position（用于停止后恢复） */
  const motionBasePosRef = useRef<Map<string, [number, number, number]>>(new Map());
  /** FPS 监控 */
  const fpsRef = useRef({ frames: 0, lastTime: performance.now(), value: 60 });
  const [fps, setFps] = useState(60);
  const [, forceTick] = useState(0);

  const dragStartRef = useRef<{ x: number; y: number; actors: StageActor[] } | null>(null);
  const pendingDragRef = useRef<{ x: number; y: number; sid: string } | null>(null);
  const marqueeSessionRef = useRef<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
    active: boolean;
  } | null>(null);
  const framedOnceRef = useRef(false);
  const transformDraggingRef = useRef(false);
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const actorsRef = useRef(actors);
  actorsRef.current = actors;
  const actorSyncRafRef = useRef(false);
  const highlightSigRef = useRef("");
  const toolRef = useRef(tool);
  const selectedRef = useRef(selectedId);
  const viewModeRef = useRef(viewMode);
  const snapRef = useRef(snapOn);
  const editModeRef = useRef(editMode);
  const transformBoneKeyRef = useRef<string | null>(null);
  const ikDraggingRef = useRef(false);
  const ikSessionRef = useRef<{
    actorId: string;
    boneKey: string;
    mode: "chainIk" | "segmentFk" | "look";
    grabPoint: THREE.Vector3;
    endOffset: THREE.Vector3;
    clientX: number;
    clientY: number;
    active: boolean;
  } | null>(null);
  const selectedBoneKeyRef = useRef<string | null>(null);
  const hoveredBoneKeyRef = useRef<string | null>(null);
  toolRef.current = tool;
  selectedRef.current = selectedId;
  selectedBoneKeyRef.current = selectedBoneKey;
  hoveredBoneKeyRef.current = hoveredBoneKey;
  viewModeRef.current = viewMode;
  snapRef.current = snapOn;
  editModeRef.current = editMode;

  const selected = actors.find((a) => a.id === selectedId) || null;
  const activeCam = cameras.find((c) => c.id === activeCamId) || cameras[0] || null;

  // 消费 AI 分镜相机计划：applyStage3dCameraPlan 递增 stage3dApplySeq 后，把 pendingStage3dCameras 应用进实时视口
  const stage3dApplySeq = useCanvasStore((state) => state.stage3dApplySeq);
  // 灯位通道序号：灯位面板介入后（>0）让本文件里的 lightPreset effect 不再覆盖 hemi/dir
  const stage3dLightingSeq = useCanvasStore((state) => state.stage3dLightingSeq);
  /** 最近一条已导出的 3D 产物（「→ 时间线」按钮的可用性与提示用，通道见 stage3dArtifacts.ts） */
  const last3dArtifact = useLatestStage3dArtifact();
  useEffect(() => {
    const pending = useCanvasStore.getState().pendingStage3dCameras;
    if (!pending || !pending.length) return;
    // 后端相机计划字段与 StageCamera 对齐，仅剔除冗余的 movement 字段
    const appliedCams: StageCamera[] = pending.map((c) => ({
      id: c.id,
      name: c.name,
      position: c.position,
      lookAt: c.lookAt,
      fov: c.fov,
      shotSize: c.shotSize,
      pathPoints: c.pathPoints,
      pathDuration: c.pathDuration,
    }));
    setCameras(appliedCams);
    setActiveCamId(appliedCams[0]?.id ?? null);
    setViewMode("camera");
    useCanvasStore.getState().consumeStage3dCameraPlan();
    onStatus(`已应用 ${appliedCams.length} 个 AI 分镜机位`);
  }, [stage3dApplySeq]);

  // Persist scene — 拖姿高频 setActors 时防抖，避免主线程被 localStorage 卡住
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistLastJsonRef = useRef("");
  const persistPendingRef = useRef<ScenePersist | null>(null);
  useEffect(() => {
    const persistData: ScenePersist = {
      actors, cameras, fov, aspect, activeCamId, lightPreset, groundPreset, poseTracks, selectedId, sceneMode, envEquirect,
    };
    persistPendingRef.current = persistData;
    const flush = () => {
      const data = persistPendingRef.current;
      if (!data) return;
      persistPendingRef.current = null;
      let json = "";
      try {
        json = JSON.stringify(data);
      } catch {
        return;
      }
      if (json === persistLastJsonRef.current) return;
      persistLastJsonRef.current = json;
      try {
        localStorage.setItem(STAGE_KEY, json);
      } catch {
        /* ignore quota */
      }
      try {
        useCanvasStore.getState().setStage3dSnapshot(data);
      } catch {
        /* store 尚未初始化时跳过 */
      }
    };
    if (persistTimerRef.current) clearTimeout(persistTimerRef.current);
    persistTimerRef.current = setTimeout(() => {
      persistTimerRef.current = null;
      flush();
    }, 420);
    return () => {
      if (persistTimerRef.current) {
        clearTimeout(persistTimerRef.current);
        persistTimerRef.current = null;
        flush();
      }
    };
  }, [actors, cameras, fov, aspect, activeCamId, lightPreset, groundPreset, poseTracks, selectedId, sceneMode, envEquirect]);

  // Init three.js
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    // 空闲预热 BodyKun/BodyChan 处理后模板，缩短首个角色 GLB 等待
    preloadBodyFigures();

    const scene = new THREE.Scene();
    const initialLight = LIGHT_PRESETS[persisted?.lightPreset ?? "neutral"];
    scene.background = new THREE.Color(initialLight.bg);
    scene.fog = new THREE.Fog(initialLight.fog, 18, 42);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    // 默认入画：全身可见，避免素模贴满视口
    camera.position.set(3.05, 2.15, 4.2);

    // 不保留 drawing buffer：保留会迫使 GPU 每帧复制全屏缓冲，叠加 toDataURL 同步读像素
    // 在 NVIDIA 上易触发「GPU stall due to ReadPixels (GL_CLOSE_PATH_NV)」甚至杀 GPU 子进程。
    // 截图统一改走 WebGLRenderTarget + readRenderTargetPixels（见 readRenderTargetToDataURL）。
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = false;
    el.appendChild(renderer.domElement);

    // Bloom 后处理管线（strength=0 时等于直接 render，无额外开销）
    const composer = new EffectComposer(renderer);
    const renderPass = new RenderPass(scene, camera);
    composer.addPass(renderPass);
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 0, 0.4, 0.85);
    bloomPass.name = "bloom";
    composer.addPass(bloomPass);
    composerRef.current = composer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(0, 0.95, 0);
    controls.minDistance = 1.6;
    controls.maxDistance = 22;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };
    controls.touches = {
      ONE: THREE.TOUCH.ROTATE,
      TWO: THREE.TOUCH.DOLLY_PAN,
    };

    const hemi = new THREE.HemisphereLight(initialLight.hemiSky, initialLight.hemiGround, initialLight.hemiIntensity);
    scene.add(hemi);
    const dir = new THREE.DirectionalLight(initialLight.dirColor, initialLight.dirIntensity);
    dir.position.set(...initialLight.dirPos);
    dir.castShadow = true;
    scene.add(dir);

    const groundTex = makeGroundTexture(persisted?.groundPreset ?? "studio-dark");
    const groundMat = new THREE.MeshStandardMaterial({
      color: persisted?.groundPreset === "studio-dark" ? "#141c28" : "#aaaaaa",
      roughness: 0.9,
      map: groundTex ?? undefined,
    });
    if (groundTex) {
      groundMat.color.set(0xffffff);
    }
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(40, 40),
      groundMat,
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    ground.name = "stage-ground";
    ground.userData.locked = true;
    ground.matrixAutoUpdate = true;
    scene.add(ground);

    const grid = new THREE.GridHelper(40, 40, 0x2a3a4d, 0x1a2433);
    grid.name = "stage-grid";
    grid.userData.locked = true;
    (grid.material as THREE.Material).opacity = 0.55;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    const axisHelper = new THREE.AxesHelper(1.2);
    axisHelper.visible = false;
    axisHelper.userData.isHelper = true; // 导出/截图时被 setHelpersVisible 排除
    scene.add(axisHelper);

    // 全景图天空球（默认隐藏，加载 equirectangular 后显示为环境背景）
    const envGeo = new THREE.SphereGeometry(200, 64, 32);
    envGeo.scale(-1, 1, 1); // 内向外（反绕序），从球内看
    const envMat = new THREE.MeshBasicMaterial({ color: 0x141c28, side: THREE.BackSide });
    const envSphere = new THREE.Mesh(envGeo, envMat);
    envSphere.visible = false;
    envSphere.renderOrder = -1;
    scene.add(envSphere);
    envSphereRef.current = envSphere;

    const objects = new Map<string, THREE.Object3D>();
    const camHelpers = new Map<string, THREE.Object3D>();
    const raycaster = new THREE.Raycaster();

    const transform = new TransformControls(camera, renderer.domElement);
    transform.mode = "rotate";
    transform.setSpace("local");
    transform.size = 0.85;
    transform.enabled = false;
    scene.add(transform);

    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(240 * 3), 3));
    trailGeo.setDrawRange(0, 0);
    const ikTrail = new THREE.Line(
      trailGeo,
      new THREE.LineBasicMaterial({ color: 0xfbbf24, transparent: true, opacity: 0.95 }),
    );
    ikTrail.frustumCulled = false;
    ikTrail.visible = false;
    scene.add(ikTrail);
    const ikRubber = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.85 }),
    );
    ikRubber.frustumCulled = false;
    ikRubber.visible = false;
    scene.add(ikRubber);

    const fitDirectorFraming = () => {
      const box = new THREE.Box3();
      let has = false;
      objects.forEach((obj) => {
        const b = new THREE.Box3().setFromObject(obj);
        if (!b.isEmpty()) {
          box.union(b);
          has = true;
        }
      });
      const size = new THREE.Vector3(0.55, 1.82, 0.4);
      const center = new THREE.Vector3(0, 0.9, 0);
      if (has) {
        box.getSize(size);
        box.getCenter(center);
      }
      // 异常巨大包围盒（坏缩放）压回合理人体尺度
      const rawMax = Math.max(size.x, size.y, size.z, 0.01);
      const maxDim = Math.min(6.5, Math.max(0.9, rawMax > 12 ? 1.85 : rawMax));
      if (rawMax > 12) {
        center.set(center.x, 0.9, center.z);
      }
      const fovRad = (camera.fov * Math.PI) / 180;
      const dist = (maxDim * 0.62) / Math.tan(fovRad / 2);
      const safeDist = Math.min(16, Math.max(2.6, dist * 1.2));
      controls.target.set(center.x, Math.max(0.55, Math.min(1.35, center.y)), center.z);
      camera.position.set(
        center.x + safeDist * 0.58,
        Math.max(1.2, center.y + safeDist * 0.32),
        center.z + safeDist * 0.78,
      );
      controls.minDistance = Math.max(1.4, maxDim * 0.5);
      controls.maxDistance = Math.max(14, maxDim * 7);
      controls.update();
      camera.lookAt(controls.target);
    };

    apiRef.current = {
      scene,
      camera,
      renderer,
      controls,
      transform,
      objects,
      camHelpers,
      raycaster,
      ground,
      axisHelper,
      hemi,
      dir,
      ikTrail,
      ikRubber,
      ikTrailCount: 0,
      fitDirectorFraming,
    };

    // TransformControls 拖拽时临时禁用 Orbit，结束后恢复
    transform.addEventListener("dragging-changed", (e: { value: boolean }) => {
      // 转环拖动时同样锁死导演轨道，避免视角跟着转
      controls.enabled = !e.value && viewModeRef.current === "director";
      transformDraggingRef.current = e.value;
      if (e.value) {
        marqueeSessionRef.current = null;
        setMarquee(null);
      } else {
        transformBoneKeyRef.current = null;
      }
    });

    // 拖拽旋转时，把骨骼 Group 的 rotation 实时同步回 JointPose
    transform.addEventListener("objectChange", () => {
      if (ikDraggingRef.current) return;
      const bone = transform.object;
      if (!bone || !bone.userData.boneKey) return;
      const boneKey = bone.userData.boneKey as string;

      // 标记正在拖拽的骨骼，避免 sync actors 回写 applyPose 覆盖
      transformBoneKeyRef.current = boneKey;

      // 找到当前选中的 actor（从 objects 里遍历找）
      let targetActorId: string | null = null;
      let targetRoot: THREE.Object3D | null = null;
      objects.forEach((actorObj, id) => {
        const bones = getPoseBones(actorObj);
        if (bones && bones[boneKey] === bone) {
          targetActorId = id;
          targetRoot = actorObj;
        }
      });
      if (!targetActorId || !targetRoot) return;
      const patch = readPosePatchFromBone(targetRoot, bone, boneKey);
      if (!Object.keys(patch).length) return;

      setActors((prev) =>
        prev.map((a) =>
          a.id === targetActorId
            ? { ...a, pose: mergePose(actorPose(a), patch) }
            : a,
        ),
      );
    });

    // 拖拽结束后清除标记
    transform.addEventListener("mouseUp", () => {
      transformBoneKeyRef.current = null;
    });
    transform.addEventListener("pointerUp", () => {
      transformBoneKeyRef.current = null;
    });

    const resize = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w < 2 || h < 2) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
      composer.setSize(w, h);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      // FPS 计数：每秒更新一次
      const f = fpsRef.current;
      f.frames++;
      const nowFps = performance.now();
      if (nowFps - f.lastTime >= 1000) {
        f.value = f.frames * 1000 / (nowFps - f.lastTime);
        f.frames = 0;
        f.lastTime = nowFps;
        setFps(Math.round(f.value));
      }
      controls.update();
      // —— 录制运镜：采样当前相机位姿（纯相机层）——
      const rec = camRecRef.current;
      if (rec?.isRecording) {
        rec.record(
          [camera.position.x, camera.position.y, camera.position.z],
          [controls.target.x, controls.target.y, controls.target.z],
        );
      }
      const apiNow = apiRef.current;
      if (apiNow) {
        // 2026-10-19（解冻 stage3d-core）：角色尺寸自检必须放在**渲染循环**里。
        // 之前挂在 actors 同步 effect，而 GLB 是异步挂载的 —— 加载完 actors 数组没变 ⇒ effect
        // 不再执行 ⇒ 自检从未跑过（用户实测：群像第三个角色整体放大十几倍，另外两个正常）。
        // 每秒一次 precise 包围盒（含蒙皮），>4m 即回正姿势并归一到 1.7m，实测高度报到状态条。
        if (nowFps - actorAuditAtRef.current > 1000) {
          actorAuditAtRef.current = nowFps;
          for (const a of actorsRef.current) {
            const o = a.kind === "actor" ? apiNow.objects.get(a.id) : undefined;
            if (!o) continue;
            const wb = new THREE.Box3().setFromObject(o, true);
            const wh = new THREE.Vector3();
            if (!wb.isEmpty()) wb.getSize(wh);
            if (wh.y > 4) {
              applyPose(o, actorPose(a));
              o.scale.multiplyScalar(1.7 / wh.y);
              const msg = `角色「${a.name}」渲染异常（实测 ${wh.y.toFixed(1)}m），已回正并归一`;
              console.warn("[Stage3D] " + msg, a.id);
              onStatus(msg);
            }
          }
        }
        // —— 掌镜 WASD：自由走镜头 ——
        if (wasdActiveRef.current && wasdRef.current.size) {
          const spd = 0.06;
          const fwd = new THREE.Vector3();
          apiNow.camera.getWorldDirection(fwd);
          fwd.y = 0; fwd.normalize();
          const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
          const delta = new THREE.Vector3();
          const keys = wasdRef.current;
          if (keys.has("w")) delta.add(fwd);
          if (keys.has("s")) delta.sub(fwd);
          if (keys.has("d")) delta.add(right);
          if (keys.has("a")) delta.sub(right);
          if (keys.has("e")) delta.y += 1;
          if (keys.has("q")) delta.y -= 1;
          if (delta.lengthSq() > 0) {
            delta.normalize().multiplyScalar(spd);
            apiNow.camera.position.add(delta);
            apiNow.controls.target.add(delta);
          }
        }
        // —— 角色路线跟随：沿点列插值移动 ——
        actorsRef.current.forEach((actor) => {
          const route = actor.route;
          if (!route?.playing || route.points.length < 1) return;
          const obj = apiNow.objects.get(actor.id);
          if (!obj) return;
          const pts = route.points;
          const speedMul = route.speed === "soft" ? 0.5 : route.speed === "custom" ? 1.5 : 1;
          const prevProg = routeProgressRef.current.get(actor.id) ?? 0;
          const prog = prevProg + 0.0015 * speedMul;
          const p = prog >= 1 ? 0 : prog; // 循环
          routeProgressRef.current.set(actor.id, p);
          const segT = p * Math.max(pts.length - 1, 1);
          const i = Math.min(Math.floor(segT), pts.length - 2);
          const localT = route.shape === "smooth" ? (segT - i) * (segT - i) * (3 - 2 * (segT - i)) : segT - i;
          const a = pts[Math.max(i, 0)];
          const b = pts[Math.min(i + 1, pts.length - 1)];
          const nx = a[0] + (b[0] - a[0]) * localT;
          const nz = a[2] + (b[2] - a[2]) * localT;
          // 朝向：沿移动方向
          const dx = b[0] - a[0], dz = b[2] - a[2];
          const rotY = Math.abs(dx) + Math.abs(dz) > 1e-4 ? Math.atan2(dx, dz) : obj.rotation.y;
          obj.position.set(nx, obj.position.y, nz);
          obj.rotation.y = rotY;
        });
        const nowMs = performance.now();
        activeMotionsRef.current.forEach((motions, actorId) => {
          const obj = apiNow.objects.get(actorId);
          if (!obj) return;
          const isDraggingTransform = transformBoneKeyRef.current !== null;
          if (isDraggingTransform) return;
          const startedAt = motionStartRef.current.get(actorId) ?? nowMs;
          const elapsed = nowMs - startedAt;
          const { pose, rootOffset } = sampleCompositeMotion(motions, elapsed);
          applyPoseResolved(obj, pose);
          const basePos = motionBasePosRef.current.get(actorId);
          if (basePos) {
            obj.position.set(
              basePos[0] + rootOffset[0],
              basePos[1] + rootOffset[1],
              basePos[2] + rootOffset[2],
            );
          }
        });
      }
      // Bloom=0 时直渲，避免 EffectComposer 双通道开销
      const targetStrength = bloomStrengthRef.current;
      if (bloomPass.strength !== targetStrength) {
        bloomPass.strength = targetStrength;
      }
      if (targetStrength > 0.001) {
        composer.render();
      } else {
        renderer.render(scene, camera);
      }
    };
    tick();

    onStatus("3D 导演台就绪 — 手/脚整肢 · 大腿小腿肘肩单关节 · 空白处转视角");

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      objects.forEach((obj) => {
        scene.remove(obj);
        disposeObject3D(obj);
      });
      objects.clear();
      transform.dispose();
      scene.remove(transform);
      controls.dispose();
      try {
        composer.dispose();
      } catch {
        /* older three */
      }
      renderer.dispose();
      if (renderer.domElement.parentElement === el) {
        el.removeChild(renderer.domElement);
      }
      apiRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply light/ground presets dynamically
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;

    const preset = LIGHT_PRESETS[lightPreset];
    api.scene.background = new THREE.Color(preset.bg);
    api.scene.fog = new THREE.Fog(preset.fog, 18, 42);
    // 灯位面板介入后（seq>0）让位：hemi/dir 归 stage3dLighting 管，这里只留 bg/fog/地面。
    // 守卫使本 effect 与 useStage3dLighting 顺序无关且幂等（否则两者抢改 hemi/dir，谁后跑谁赢）。
    if (useCanvasStore.getState().stage3dLightingSeq === 0) {
      api.hemi.color.set(preset.hemiSky);
      api.hemi.groundColor.set(preset.hemiGround);
      api.hemi.intensity = preset.hemiIntensity;
      api.dir.color.set(preset.dirColor);
      api.dir.intensity = preset.dirIntensity;
      api.dir.position.set(...preset.dirPos);
    }

    const oldTex = (api.ground.material as THREE.MeshStandardMaterial).map;
    const newTex = makeGroundTexture(groundPreset);
    const mat = api.ground.material as THREE.MeshStandardMaterial;
    if (oldTex && oldTex !== newTex) oldTex.dispose();
    mat.map = newTex ?? null;
    mat.color.set(newTex ? 0xffffff : groundPreset === "studio-dark" ? 0x141c28 : 0xaaaaaa);
    mat.needsUpdate = true;
  }, [lightPreset, groundPreset, stage3dLightingSeq]);

  // 全景图环境：equirectangular → PMREM 生成 IBL + 天空球背景
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const sphere = envSphereRef.current;

    if (!envEquirect) {
      // 清除：恢复纯色背景
      api.scene.background = new THREE.Color(LIGHT_PRESETS[lightPreset]?.bg ?? "#141c28");
      api.scene.environment = null;
      api.scene.fog = new THREE.Fog(LIGHT_PRESETS[lightPreset]?.fog ?? "#0c1220", 18, 42);
      if (sphere) {
        sphere.visible = false;
        (sphere.material as THREE.MeshBasicMaterial).map = null;
        (sphere.material as THREE.MeshBasicMaterial).needsUpdate = true;
      }
      if (envPMREMRef.current) {
        envPMREMRef.current.dispose();
        envPMREMRef.current = null;
      }
      return;
    }

    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin("anonymous");
    loader.load(
      envEquirect,
      (tex) => {
        tex.mapping = THREE.EquirectangularReflectionMapping;
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.needsUpdate = true;

        // 天空球显示：用 MeshBasicMaterial 直接贴 equirectangular
        if (sphere) {
          const m = sphere.material as THREE.MeshBasicMaterial;
          m.map = tex;
          m.color.set(0xffffff);
          m.needsUpdate = true;
          sphere.visible = true;
        }

        // PMREM：用于 MeshStandardMaterial 的 IBL 环境光反射
        try {
          const pmrem = new THREE.PMREMGenerator(api.renderer);
          const envMap = pmrem.fromEquirectangular(tex).texture;
          api.scene.environment = envMap;
          api.scene.background = envMap;
          // 加载全景图时关闭雾（360° 环境里雾会显得怪异）
          api.scene.fog = null;
          api.hemi.intensity = Math.max(0.15, api.hemi.intensity * 0.6);
          api.dir.intensity = Math.max(0.2, api.dir.intensity * 0.5);
          if (envPMREMRef.current) envPMREMRef.current.dispose();
          envPMREMRef.current = envMap;
          pmrem.dispose();
        } catch {
          // PMREM 失败降级：仅贴天空球背景，不启用 IBL
          api.scene.background = tex;
          api.scene.fog = null;
        }
      },
      undefined,
      () => {
        onStatus("全景图加载失败，已回退纯色背景");
        api.scene.background = new THREE.Color(LIGHT_PRESETS[lightPreset]?.bg ?? "#141c28");
        if (sphere) sphere.visible = false;
      },
    );
  }, [envEquirect]);

  // Bloom 强度 state → ref 同步（tick 闭包读 ref，避免 state 延迟）
  useEffect(() => {
    bloomStrengthRef.current = bloomStrength;
  }, [bloomStrength]);

  // Sync actors into scene + axis helper（rAF 节流：一帧内多次 actors 变化只同步一次）
  useEffect(() => {
    if (actorSyncRafRef.current) return;
    actorSyncRafRef.current = true;
    requestAnimationFrame(() => {
      actorSyncRafRef.current = false;
      const api = apiRef.current;
      if (!api) return;
      const latestActors = actorsRef.current;
      const sid = selectedRef.current;
      const sBone = selectedBoneKeyRef.current;
      const hBone = hoveredBoneKeyRef.current;
      const keep = new Set(latestActors.map((a) => a.id));
      let spawned = false;
      for (const [id, obj] of api.objects) {
        if (!keep.has(id)) {
          api.scene.remove(obj);
          disposeObject3D(obj);
          api.objects.delete(id);
        }
      }
      for (const a of latestActors) {
        let obj = api.objects.get(a.id);
        const staleActor =
          Boolean(obj) &&
          a.kind === "actor" &&
          (obj!.userData.meshStyle !== RIG_MESH_STYLE ||
            obj!.userData.variant !== (a.variant || "male_std") ||
            obj!.userData.hairStyle !== (a.hairStyle || "none"));
        if (staleActor && obj) {
          api.scene.remove(obj);
          disposeObject3D(obj);
          api.objects.delete(a.id);
          obj = undefined;
        }
        if (!obj) {
          obj =
            a.kind === "actor"
              ? makeRiggedHumanoid(a.color, actorPose(a), a.variant || "male_std", a.hairStyle || "none")
              : makeProp(a.kind, a.color);
          obj.userData.id = a.id;
          api.scene.add(obj);
          api.objects.set(a.id, obj);
          spawned = true;
        } else if (a.kind === "actor") {
          const draggingKey = transformBoneKeyRef.current || null;
          const ikActorId = ikDraggingRef.current ? ikSessionRef.current?.actorId : null;
          const isDraggingThisActor = draggingKey
            ? Boolean(getPoseBones(obj!)[draggingKey])
            : ikActorId === a.id;
          const hasActiveMotion = activeMotionsRef.current.has(a.id);
          if (!isDraggingThisActor && !hasActiveMotion) {
            applyPose(obj!, actorPose(a));
          }
        } else if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) {
          obj.material.color.set(a.color);
        }
        obj.position.set(a.position[0], a.position[1], a.position[2]);
        obj.rotation.y = a.rotationY;
        const safeScale = Math.min(2.2, Math.max(0.35, Number.isFinite(a.scale) ? a.scale : 1));
        obj.scale.setScalar(safeScale);
      }
      if (spawned) highlightSigRef.current = "";
      // 拖姿每帧都会 setActors；高亮/衣服色只在选中或配色变化时遍历，避免 GLB 全树 emissive 开销
      const highlightSig = latestActors
        .map((a) => `${a.id}:${a.color}:${a.id === sid ? "1" : "0"}`)
        .join("|") + `:${sBone || ""}:${hBone || ""}`;
      if (highlightSig !== highlightSigRef.current) {
        highlightSigRef.current = highlightSig;
        for (const a of latestActors) {
          const obj = api.objects.get(a.id);
          if (!obj) continue;
          if (a.kind === "actor") {
            obj.traverse((ch) => {
              if (
                ch instanceof THREE.Mesh &&
                ch.userData.tint === "clothes" &&
                ch.material instanceof THREE.MeshStandardMaterial
              ) {
                ch.material.color.set(a.color);
              }
            });
          }
          const isSel = a.id === sid;
          const selChain = isSel && sBone ? highlightBonesFor(sBone) : [];
          const hoverChain = isSel && hBone ? highlightBonesFor(hBone) : [];
          const selRegions = new Set(selChain.map(boneKeyToRegion).filter(Boolean) as string[]);
          const hoverRegions = new Set(hoverChain.map(boneKeyToRegion).filter(Boolean) as string[]);
          obj.traverse((ch) => {
            if (!(ch instanceof THREE.Mesh) || !(ch.material instanceof THREE.MeshStandardMaterial)) return;
            const tint = ch.userData.tint as string | undefined;
            if (tint === "front" || ch.userData.frontMarker) return;
            const bone = ch.userData.boneKey as string | undefined;
            const region = ch.userData.boneRegion as string | undefined;
            const isBone =
              isSel &&
              sBone &&
              (selChain.includes(bone || "") || Boolean(region && selRegions.has(region)));
            const isHover =
              isSel &&
              hBone &&
              !isBone &&
              (hoverChain.includes(bone || "") || Boolean(region && hoverRegions.has(region)));
            const canGlow = !tint || tint === "clothes" || tint === "skin" || tint === "face";
            if (isBone) {
              ch.material.emissive.copy(HL_SEL);
              ch.material.emissiveIntensity = 0.62;
            } else if (isHover) {
              ch.material.emissive.copy(HL_HOVER);
              ch.material.emissiveIntensity = 0.4;
            } else if (isSel && canGlow) {
              ch.material.emissive.copy(HL_ACTIVE);
              ch.material.emissiveIntensity = 0.16;
            } else {
              ch.material.emissive.copy(HL_NONE);
              ch.material.emissiveIntensity = 0;
            }
          });
        }
      }
      if (sid) {
        const sel = latestActors.find((a) => a.id === sid);
        if (sel) {
          api.axisHelper.visible = true;
          api.axisHelper.position.set(sel.position[0], 0.05, sel.position[2]);
        }
      } else {
        api.axisHelper.visible = false;
      }
      // 地面/网格锁定，防止误挂到骨骼矩阵
      api.ground.position.set(0, 0, 0);
      api.ground.scale.set(1, 1, 1);
      api.ground.rotation.set(-Math.PI / 2, 0, 0);
      if (!framedOnceRef.current && latestActors.length > 0 && api.objects.size > 0) {
        framedOnceRef.current = true;
        requestAnimationFrame(() => api.fitDirectorFraming());
      }
    });
  }, [actors, selectedId, selectedBoneKey, hoveredBoneKey]);

  // Sync camera helpers（机身/视锥/标签/状态全部在 stage3dCamGizmo.ts，此处只留接线）
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    syncCameraGizmos(api, cameras, activeCamId);
  }, [cameras, activeCamId]);

  // Director vs camera view — 切回导演视角时恢复相机位姿（此前只开 Orbit，镜头停在机位上）
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const prev = prevViewModeRef.current;
    prevViewModeRef.current = viewMode;

    if (viewMode === "camera" && activeCam) {
      if (prev === "director") {
        directorCamRef.current = {
          pos: [api.camera.position.x, api.camera.position.y, api.camera.position.z],
          target: [api.controls.target.x, api.controls.target.y, api.controls.target.z],
        };
      }
      api.controls.enabled = false;
      api.camera.fov = activeCam.fov || fov;
      api.camera.position.set(...activeCam.position);
      api.camera.lookAt(...activeCam.lookAt);
      api.controls.target.set(...activeCam.lookAt);
      api.camera.updateProjectionMatrix();
    } else {
      api.controls.enabled = true;
      api.camera.fov = 45;
      if (prev === "camera") {
        const saved = directorCamRef.current;
        if (saved) {
          api.camera.position.set(...saved.pos);
          api.controls.target.set(...saved.target);
          directorCamRef.current = null;
        } else {
          api.camera.position.set(3.05, 2.15, 4.2);
          api.controls.target.set(0, 0.95, 0);
          api.fitDirectorFraming();
        }
      }
      api.controls.update();
      api.camera.lookAt(api.controls.target);
      api.camera.updateProjectionMatrix();
    }
  }, [viewMode, activeCam, fov]);

  // Pointer: 关节模式 = 框选/点选部位 → 旋转环调关节；Alt / 整体模式 = 平移整人
  useEffect(() => {
    const api = apiRef.current;
    const el = mountRef.current;
    if (!api || !el) return;

    const proj = new THREE.Vector3();

    const pickHit = (ev: Pick<PointerEvent, "clientX" | "clientY">) => {
      const rect = el.getBoundingClientRect();
      const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      api.raycaster.setFromCamera(new THREE.Vector2(x, y), api.camera);
      const meshes: THREE.Object3D[] = [];
      api.objects.forEach((o) => meshes.push(o));
      const hits = api.raycaster.intersectObjects(meshes, true);
      const hit = hits.find((h) => isWorldVisible(h.object) && !isFrontMarkerHit(h.object));
      if (!hit) {
        return { actorId: null as string | null, boneKey: null as string | null, point: null as THREE.Vector3 | null };
      }
      let obj: THREE.Object3D | null = hit.object;
      let actorId: string | null = null;
      while (obj) {
        if (obj.userData.id && !actorId) actorId = obj.userData.id;
        if (actorId) break;
        obj = obj.parent;
      }
      const actorObj = actorId ? api.objects.get(actorId) : undefined;
      const boneKey = actorObj ? resolveHitBoneKey(actorObj, hit.object, hit.point) : null;
      return { actorId, boneKey, point: hit.point.clone() };
    };

    const projectToClient = (obj: THREE.Object3D) => {
      obj.getWorldPosition(proj);
      proj.project(api.camera);
      const rect = el.getBoundingClientRect();
      return {
        x: rect.left + (proj.x * 0.5 + 0.5) * rect.width,
        y: rect.top + (-proj.y * 0.5 + 0.5) * rect.height,
      };
    };

    const selectBoneFromMarquee = (x0: number, y0: number, x1: number, y1: number) => {
      const left = Math.min(x0, x1);
      const right = Math.max(x0, x1);
      const top = Math.min(y0, y1);
      const bottom = Math.max(y0, y1);
      if (right - left < DRAG_THRESHOLD_PX && bottom - top < DRAG_THRESHOLD_PX) return null;

      const cx = (left + right) / 2;
      const cy = (top + bottom) / 2;
      let best: { actorId: string; boneKey: string; dist: number } | null = null;

      for (const [actorId, obj] of api.objects) {
        const actor = actorsRef.current.find((a) => a.id === actorId);
        if (actor?.kind !== "actor") continue;
        const bones = getPoseBones(obj);
        if (!bones) continue;
        for (const [key, bone] of Object.entries(bones)) {
          if (!bone) continue;
          const p = projectToClient(bone);
          if (p.x < left || p.x > right || p.y < top || p.y > bottom) continue;
          const dist = Math.hypot(p.x - cx, p.y - cy);
          if (!best || dist < best.dist) best = { actorId, boneKey: key, dist };
        }
      }
      return best ? { actorId: best.actorId, boneKey: best.boneKey } : null;
    };

    const resetIkTrail = () => {
      api.ikTrailCount = 0;
      api.ikTrail.geometry.setDrawRange(0, 0);
      api.ikTrail.visible = false;
      api.ikRubber.visible = false;
    };

    const pushIkTrail = (point: THREE.Vector3, origin: THREE.Vector3) => {
      const attr = api.ikTrail.geometry.getAttribute("position") as THREE.BufferAttribute;
      let n = api.ikTrailCount;
      if (n >= 239) {
        for (let i = 0; i < 238; i++) {
          attr.setXYZ(i, attr.getX(i + 1), attr.getY(i + 1), attr.getZ(i + 1));
        }
        n = 238;
      }
      attr.setXYZ(n, point.x, point.y, point.z);
      api.ikTrailCount = n + 1;
      attr.needsUpdate = true;
      api.ikTrail.geometry.setDrawRange(0, api.ikTrailCount);
      api.ikTrail.visible = api.ikTrailCount > 1;
      const rubberPos = api.ikRubber.geometry.getAttribute("position") as THREE.BufferAttribute;
      rubberPos.setXYZ(0, origin.x, origin.y, origin.z);
      rubberPos.setXYZ(1, point.x, point.y, point.z);
      rubberPos.needsUpdate = true;
      api.ikRubber.geometry.computeBoundingSphere();
      api.ikRubber.visible = true;
    };

    const chainOrigin = (actorObj: THREE.Object3D, boneKey: string) => {
      const bones = getPoseBones(actorObj);
      const originKey = chainBonesFor(boneKey)[0] || boneKey;
      const bone = bones[originKey] || bones[boneKey];
      const out = new THREE.Vector3();
      if (bone) bone.getWorldPosition(out);
      else actorObj.getWorldPosition(out);
      return out;
    };

    const attachSelectedBone = (actorId: string, boneKey: string) => {
      setSelectedId(actorId);
      setRailTab("actor");
      setSelectedBoneKey(boneKey);
      const actorObj = api.objects.get(actorId);
      const bones = actorObj ? getPoseBones(actorObj) : {};
      const bone = bones[boneKey];
      if (!bone) return;
      undoRef.current = actorsRef.current;
      const mode = limbDragMode(boneKey);
      const label = BONE_CN[boneKey] || boneKey;
      if (isIkOnlyUnlockBone(boneKey) || mode === "look") {
        api.transform.enabled = false;
        api.transform.detach();
        onStatus(`已选 ${label} · 拖动调节朝向`);
      } else if (mode === "segmentFk") {
        // 单关节：转环可微调；主拖动走 FK，不整肢
        api.transform.enabled = true;
        api.transform.attach(bone);
        api.transform.setMode("rotate");
        onStatus(`已选 ${label} · 单关节调节（大腿/小腿/上臂/前臂）`);
      } else {
        api.transform.enabled = true;
        api.transform.attach(bone);
        api.transform.setMode("rotate");
        onStatus(`已选 ${label} · 拖动手/脚带动整肢 · 转环微调腕踝`);
      }
    };

    const beginIkSession = (actorId: string, boneKey: string, point: THREE.Vector3, ev: PointerEvent) => {
      const actorObj = api.objects.get(actorId);
      if (!actorObj) return;
      const bones = getPoseBones(actorObj);
      const mode = limbDragMode(boneKey);
      // 整肢 IK 跟末端；单关节 FK 跟当前骨
      const trackKey = mode === "chainIk" ? endEffectorBoneKey(boneKey) : boneKey;
      const trackBone = bones[trackKey] || bones[boneKey];
      const endWorld = new THREE.Vector3();
      if (trackBone) trackBone.getWorldPosition(endWorld);
      else endWorld.copy(point);
      ikSessionRef.current = {
        actorId,
        boneKey,
        mode,
        grabPoint: point.clone(),
        endOffset: endWorld.sub(point),
        clientX: ev.clientX,
        clientY: ev.clientY,
        active: false,
      };
    };

    const onPointerDown = (ev: PointerEvent) => {
      if (viewModeRef.current === "camera") return;
      if (transformDraggingRef.current) return;
      if (ev.button !== 0) return;
      if (api.transform.enabled && api.transform.axis) return;

      // 点住部位即可拖：按下立即锁住导演视角，避免拖姿时相机跟着转
      if (editModeRef.current === "joint" && !ev.altKey && !ev.shiftKey) {
        const hit = pickHit(ev);
        if (hit.actorId && hit.boneKey && hit.point) {
          ev.preventDefault();
          ev.stopImmediatePropagation();
          api.controls.enabled = false;
          attachSelectedBone(hit.actorId, hit.boneKey);
          beginIkSession(hit.actorId, hit.boneKey, hit.point, ev);
          pendingDragRef.current = null;
          dragStartRef.current = null;
          marqueeSessionRef.current = null;
          setMarquee(null);
          try {
            api.renderer.domElement.setPointerCapture(ev.pointerId);
          } catch {
            /* ignore */
          }
          return;
        }
      }

      if (editModeRef.current === "joint" && ev.shiftKey && !ev.altKey) {
        ev.preventDefault();
        ev.stopImmediatePropagation();
        api.controls.enabled = false;
        marqueeSessionRef.current = {
          x0: ev.clientX,
          y0: ev.clientY,
          x1: ev.clientX,
          y1: ev.clientY,
          active: true,
        };
        setMarquee(null);
        pendingDragRef.current = null;
        dragStartRef.current = null;
        return;
      }

      if (editModeRef.current !== "joint" || ev.altKey) {
        const { actorId, boneKey } = pickHit(ev);
        if (!actorId) {
          api.transform.enabled = false;
          api.transform.detach();
          setSelectedBoneKey(null);
          return;
        }
        ev.preventDefault();
        ev.stopImmediatePropagation();
        api.controls.enabled = false;
        setSelectedId(actorId);
        setRailTab("actor");
        api.transform.enabled = false;
        api.transform.detach();
        setSelectedBoneKey(null);
        pendingDragRef.current = { x: ev.clientX, y: ev.clientY, sid: actorId };
        dragStartRef.current = null;
        void boneKey;
      }
    };

    const onPointerMove = (ev: PointerEvent) => {
      if (transformDraggingRef.current) {
        marqueeSessionRef.current = null;
        setMarquee(null);
        return;
      }

      const ik = ikSessionRef.current;
      if (ik && ev.buttons === 1 && editModeRef.current === "joint") {
        // 拖姿全程锁视角（含尚未超过阈值的微动）
        api.controls.enabled = false;
        const dist = Math.hypot(ev.clientX - ik.clientX, ev.clientY - ik.clientY);
        if (!ik.active && dist < DRAG_THRESHOLD_PX) return;
        if (!ik.active) {
          ik.active = true;
          ikDraggingRef.current = true;
          api.transform.enabled = false;
          api.transform.detach();
          resetIkTrail();
          try {
            api.renderer.domElement.setPointerCapture(ev.pointerId);
          } catch {
            /* ignore */
          }
        }
        const n = new THREE.Vector3();
        api.camera.getWorldDirection(n);
        const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, ik.grabPoint);
        const rect = el.getBoundingClientRect();
        const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
        api.raycaster.setFromCamera(new THREE.Vector2(x, y), api.camera);
        const target = new THREE.Vector3();
        if (!api.raycaster.ray.intersectPlane(plane, target)) return;
        target.add(ik.endOffset);
        const obj = api.objects.get(ik.actorId);
        const actor = actorsRef.current.find((a) => a.id === ik.actorId);
        if (!obj || !actor) return;
        const next = mergePose(
          actorPose(actor),
          ik.mode === "segmentFk"
            ? solveSegmentFk(obj, ik.boneKey, target, actorPose(actor))
            : solveChainIk(obj, ik.boneKey, target, actorPose(actor)),
        );
        applyPose(obj, next);
        if (isIkOnlyUnlockBone(ik.boneKey) || ik.mode === "look") {
          obj.position.set(actor.position[0], actor.position[1], actor.position[2]);
          api.ground.position.set(0, 0, 0);
          api.ground.scale.set(1, 1, 1);
        }
        pushIkTrail(target, chainOrigin(obj, ik.boneKey));
        setActors((prev) => prev.map((a) => (a.id === ik.actorId ? { ...a, pose: next } : a)));
        return;
      }

      const session = marqueeSessionRef.current;
      if (session?.active && editModeRef.current === "joint" && ev.buttons === 1) {
        session.x1 = ev.clientX;
        session.y1 = ev.clientY;
        const rect = el.getBoundingClientRect();
        const dist = Math.hypot(session.x1 - session.x0, session.y1 - session.y0);
        if (dist >= DRAG_THRESHOLD_PX) {
          setMarquee({
            x0: session.x0 - rect.left,
            y0: session.y0 - rect.top,
            x1: session.x1 - rect.left,
            y1: session.y1 - rect.top,
          });
          api.controls.enabled = false;
        }
        return;
      }

      if (ev.buttons === 0 && !session?.active) {
        const { boneKey, actorId } = pickHit(ev);
        const next = actorId && boneKey && editModeRef.current === "joint" ? boneKey : null;
        setHoveredBoneKey((prev) => (prev === next ? prev : next));
        return;
      }
      if (ev.buttons !== 1 || viewModeRef.current === "camera") return;

      const pending = pendingDragRef.current;
      if (pending && !dragStartRef.current) {
        const dx0 = ev.clientX - pending.x;
        const dy0 = ev.clientY - pending.y;
        if (Math.hypot(dx0, dy0) < DRAG_THRESHOLD_PX) return;
        setActors((prev) => {
          dragStartRef.current = { x: pending.x, y: pending.y, actors: prev };
          return prev;
        });
        api.controls.enabled = false;
      }
      const sid = selectedRef.current;
      if (!sid || !dragStartRef.current) return;
      const t = toolRef.current;
      const dx = ev.clientX - dragStartRef.current.x;
      const dy = ev.clientY - dragStartRef.current.y;

      if (t === "move") {
        const rect = el.getBoundingClientRect();
        const x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        const y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
        api.raycaster.setFromCamera(new THREE.Vector2(x, y), api.camera);
        const hit = api.raycaster.intersectObject(api.ground)[0];
        if (!hit) return;
        let px = hit.point.x;
        let pz = hit.point.z;
        if (snapRef.current) {
          px = snap(px);
          pz = snap(pz);
        }
        setActors((prev) =>
          prev.map((a) =>
            a.id === sid ? { ...a, position: [px, 0, pz] as [number, number, number] } : a,
          ),
        );
      } else if (t === "rotate") {
        const base = dragStartRef.current.actors.find((a) => a.id === sid);
        if (!base) return;
        setActors((prev) =>
          prev.map((a) =>
            a.id === sid ? { ...a, rotationY: base.rotationY + dx * 0.01 } : a,
          ),
        );
      } else if (t === "scale") {
        const base = dragStartRef.current.actors.find((a) => a.id === sid);
        if (!base) return;
        const nextScale = Math.min(2.2, Math.max(0.35, base.scale + -dy * 0.01));
        setActors((prev) =>
          prev.map((a) => (a.id === sid ? { ...a, scale: nextScale } : a)),
        );
      }
    };

    const onPointerUp = (ev: PointerEvent) => {
      const ik = ikSessionRef.current;
      if (ik) {
        const wasIk = ik.active;
        ikSessionRef.current = null;
        ikDraggingRef.current = false;
        resetIkTrail();
        try {
          api.renderer.domElement.releasePointerCapture(ev.pointerId);
        } catch {
          /* ignore */
        }
        if (wasIk) {
          attachSelectedBone(ik.actorId, ik.boneKey);
          onStatus(`已调「${BONE_CN[ik.boneKey] || ik.boneKey}」· 空白处拖可转视角`);
        }
        if (viewModeRef.current === "director") api.controls.enabled = true;
        return;
      }

      const session = marqueeSessionRef.current;
      if (session?.active) {
        marqueeSessionRef.current = null;
        setMarquee(null);
        try {
          el.releasePointerCapture(ev.pointerId);
        } catch {
          /* ignore */
        }

        if (editModeRef.current === "joint" && !ev.altKey) {
          const isBox =
            Math.hypot(session.x1 - session.x0, session.y1 - session.y0) >= DRAG_THRESHOLD_PX;
          if (isBox) {
            const hit = selectBoneFromMarquee(session.x0, session.y0, session.x1, session.y1);
            if (hit) attachSelectedBone(hit.actorId, hit.boneKey);
            else {
              api.transform.enabled = false;
              api.transform.detach();
              setSelectedBoneKey(null);
              onStatus("框选未命中 · 直接点住肢体拖动即可");
            }
          } else {
            const { actorId, boneKey } = pickHit(session);
            if (actorId && boneKey) attachSelectedBone(actorId, boneKey);
            else if (!actorId) {
              api.transform.enabled = false;
              api.transform.detach();
              setSelectedBoneKey(null);
            } else {
              setSelectedId(actorId);
            }
          }
          if (viewModeRef.current === "director") api.controls.enabled = true;
          return;
        }
      }

      pendingDragRef.current = null;
      if (dragStartRef.current) {
        undoRef.current = dragStartRef.current.actors;
        dragStartRef.current = null;
      }
      if (viewModeRef.current === "director") {
        api.controls.enabled = true;
      }
    };

    const onPointerLeave = () => setHoveredBoneKey(null);

    const onKey = (ev: KeyboardEvent) => {
      if (cmdOpenRef.current) return;
      if (isTypingTarget(ev.target)) return;
      if (ev.key === "/" || ev.key === "?") return;
      const k = ev.key.toLowerCase();
      if (ev.ctrlKey || ev.metaKey) {
        if (k === "z") {
          ev.preventDefault();
          if (undoRef.current) {
            setActors(undoRef.current);
            undoRef.current = null;
            onStatus("已撤销最近一次变换");
          }
        }
        return;
      }
      if (k === "v") setTool("move");
      if (k === "r") setTool("rotate");
      if (k === "s") setTool("scale");
      if (k === "j") {
        const next = editModeRef.current === "actor" ? "joint" : "actor";
        setEditMode(next);
        if (next === "actor") {
          api.transform.enabled = false;
          api.transform.detach();
          setSelectedBoneKey(null);
          onStatus("移整人：拖模型平移 · V/R/S 移动旋转缩放");
        } else {
          onStatus("手/脚整肢拖 · 大腿/小腿/上臂/前臂单关节 · Alt 移动整人");
        }
      }
      if (k === "escape") {
        api.transform.enabled = false;
        api.transform.detach();
        setSelectedBoneKey(null);
        marqueeSessionRef.current = null;
        setMarquee(null);
        ikSessionRef.current = null;
        ikDraggingRef.current = false;
        onStatus("已取消部位选中 · 再点住肢体拖动");
      }
      if (k === "delete" || k === "backspace") {
        const sid = selectedRef.current;
        if (sid && window.confirm("删除选中元素？")) {
          setActors((prev) => {
            undoRef.current = prev;
            return prev.filter((a) => a.id !== sid);
          });
          setSelectedId(null);
        }
      }
    };

    const canvas = api.renderer.domElement;
    canvas.addEventListener("pointerdown", onPointerDown, true);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerleave", onPointerLeave);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("keydown", onKey);
    return () => {
      canvas.removeEventListener("pointerdown", onPointerDown, true);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerleave", onPointerLeave);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("keydown", onKey);
    };
  }, [onStatus]);

  const pushUndo = () => {
    undoRef.current = actors;
  };

  // 缺口①「角色库 → 3D 导演台」消费端。必须放在 pushUndo 之后（它是 const，放前面会 TDZ）。
  useStage3dCast({ actors, setActors, setSelectedId, setSceneMode, onStatus, pushUndo });

  // 24 位灯位 → 3D 灯光消费端（2026-10-12）。与上一行同族通道；只在 seq 变化时应用，
  // 故首次 render 的 apiRef.current=null 无害（用户点灯位时场景必已初始化）。
  useStage3dLighting({ api: apiRef.current, preset: LIGHT_PRESETS[lightPreset] });

  const addActor = (kind: StageActor["kind"]) => {
    pushUndo();
    const colors = [
      "#f1f5f9",
      "#ef4444",
      "#f472b6",
      "#1d4ed8",
      "#eab308",
      "#a855f7",
      "#22c55e",
      "#0f172a",
      "#fb923c",
    ];
    const n = actors.length;
    setActors((prev) => [
      ...prev,
      {
        id: uid("a"),
        name: kind === "actor" ? `角色 ${n + 1}` : kind === "box" ? `方块 ${n + 1}` : `柱体 ${n + 1}`,
        kind,
        color: colors[n % colors.length],
        position: [n * 0.4 - 1, 0, n * 0.2],
        rotationY: 0,
        scale: 1,
        pose: kind === "actor" ? defaultPose() : undefined,
        variant: kind === "actor" ? "male_std" : undefined,
        hairStyle: kind === "actor" ? "none" : undefined,
      },
    ]);
  };

  const duplicateSelectedActor = () => {
    const a = actors.find((x) => x.id === selectedId);
    if (!a) {
      onStatus("请先选中角色或几何体");
      return;
    }
    pushUndo();
    const copy: StageActor = {
      ...a,
      id: uid("a"),
      name: `${a.name} 副本`,
      position: [a.position[0] + 0.55, a.position[1], a.position[2]],
      pose: a.pose ? { ...a.pose } : undefined,
    };
    setActors((prev) => [...prev, copy]);
    setSelectedId(copy.id);
    onStatus(`已复制「${a.name}」`);
  };

  const FORMATIONS: { id: FormationId; label: string }[] = [
    { id: "line", label: "一字排开" },
    { id: "arc", label: "弧形" },
    { id: "circle", label: "围圆" },
    { id: "face", label: "对峙" },
    { id: "triangle", label: "三角阵" },
  ];

  const applyFormation = (formation: FormationId) => {
    const people = actors.filter((a) => a.kind === "actor");
    if (people.length < 1) {
      onStatus("请先添加人体素模");
      return;
    }
    pushUndo();
    const slots = formationPositions(people.length, formation);
    const idToSlot = new Map(people.map((a, i) => [a.id, i]));
    setActors((prev) =>
      prev.map((a) => {
        const idx = idToSlot.get(a.id);
        if (idx === undefined) return a;
        const pos = slots[idx];
        return {
          ...a,
          position: pos,
          rotationY: facingYForFormation(pos, formation),
        };
      }),
    );
    onStatus(`已应用群像站位：${FORMATIONS.find((f) => f.id === formation)?.label || formation}`);
  };

  const applyGroupTemplate = (tpl: (typeof GROUP_TEMPLATES)[number]) => {
    pushUndo();
    const crowd = makeCrowdActors(tpl.count, tpl.formation);
    const props = actors.filter((a) => a.kind !== "actor");
    setActors([...crowd, ...props]);
    setSelectedId(crowd[0]?.id ?? null);
    setSceneMode("group");
    setViewMode("director");
    // 自动为群像分配不同的动作：第 1 人走姿，其余站立微晃 + 呼吸
    activeMotionsRef.current.clear();
    motionStartRef.current.clear();
    motionBasePosRef.current.clear();
    crowd.forEach((actor, i) => {
      if (i === 0) {
        activeMotionsRef.current.set(actor.id, [MOTION_WALK_GAIT, MOTION_BREATHING]);
      } else {
        activeMotionsRef.current.set(actor.id, [MOTION_IDLE_SWAY, MOTION_BREATHING]);
      }
      motionStartRef.current.set(actor.id, performance.now() + i * 120);
    });
    onStatus(`已布置${tpl.label}（${tpl.count}人）· 自动分配动作轨迹 ✓`);
  };

  const switchSceneMode = (mode: "solo" | "group") => {
    if (mode === "solo") {
      const keep =
        actors.find((a) => a.id === selectedId && a.kind === "actor") ||
        actors.find((a) => a.kind === "actor");
      pushUndo();
      const solo = keep
        ? [{ ...keep, position: [0, 0, 0] as [number, number, number], rotationY: 0 }]
        : defaultActors();
      setActors(solo);
      setSelectedId(solo[0]?.id ?? null);
      setSceneMode("solo");
      setViewMode("director");
      onStatus("已切到单人 · 五官朝向镜头为正面");
      return;
    }
    const people = actors.filter((a) => a.kind === "actor");
    setSceneMode("group");
    if (people.length < 2) {
      applyGroupTemplate(GROUP_TEMPLATES.find((t) => t.id === "trio-arc")!);
    } else {
      onStatus("群像模式：点模板生成多人，或用站位重排现有人模");
    }
  };

  const faceSelectedToCamera = () => {
    if (!selected || selected.kind !== "actor") return;
    const api = apiRef.current;
    if (!api) return;
    const yaw = yawToward(selected.position, [
      api.camera.position.x,
      0,
      api.camera.position.z,
    ]);
    patchSelected({ rotationY: yaw });
    onStatus(`${selected.name} 正面已朝向镜头`);
  };

  const flipSelectedFront = () => {
    if (!selected || selected.kind !== "actor") return;
    patchSelected({ rotationY: selected.rotationY + Math.PI });
    onStatus(`${selected.name} 已转身 180°（正反面互换）`);
  };

  const patchPose = (patch: Partial<JointPose>) => {
    if (!selectedId || selected?.kind !== "actor") return;
    pushUndo();
    const next = mergePose(actorPose(selected), patch);
    setActors((prev) =>
      prev.map((a) => (a.id === selectedId ? { ...a, pose: next } : a)),
    );
    const obj = apiRef.current?.objects.get(selectedId);
    if (obj) applyPose(obj, next);
  };

  const setPosePreset = (id: PosePresetId) => {
    if (!selectedId || selected?.kind !== "actor") return;
    pushUndo();
    const next = applyPreset(id);
    const rootY = POSE_ROOT_OFFSET_Y[id] ?? 0;
    setActors((prev) =>
      prev.map((a) =>
        a.id === selectedId
          ? {
              ...a,
              pose: next,
              // 坐蹲跪降髋；其它预设回到地面高度，避免沿用上次的漂浮 Y
              position: [a.position[0], rootY, a.position[2]] as [number, number, number],
            }
          : a,
      ),
    );
    const obj = apiRef.current?.objects.get(selectedId);
    if (obj) applyPose(obj, next);
    onStatus(`姿势：${POSE_PRESETS.find((p) => p.id === id)?.label || id}`);
  };

  const addCameraFromView = () => {
    const api = apiRef.current;
    if (!api) return;
    const p = api.camera.position;
    const t = api.controls.target;
    const cam: StageCamera = {
      id: uid("cam"),
      name: `机位 ${cameras.length + 1}`,
      position: [p.x, p.y, p.z],
      lookAt: [t.x, t.y, t.z],
      fov,
    };
    setCameras((prev) => [...prev, cam]);
    setActiveCamId(cam.id);
    onStatus(`已保存 ${cam.name}`);
  };

  const capture = (camOverride?: StageCamera | null) => {
    const api = apiRef.current;
    if (!api) return;
    const cam = camOverride || (viewMode === "camera" ? activeCam : null);
    const el = mountRef.current!;
    const w = el.clientWidth;
    const h = el.clientHeight;
    let rw = w;
    let rh = h;
    if (aspect !== "auto" && aspect.includes(":")) {
      const [aw, ah] = aspect.split(":").map(Number);
      const target = aw / ah;
      if (w / h > target) {
        rh = h;
        rw = Math.round(h * target);
      } else {
        rw = w;
        rh = Math.round(w / target);
      }
    }
    const prevW = api.renderer.domElement.width;
    const prevH = api.renderer.domElement.height;
    api.renderer.setSize(rw, rh, false);
    if (cam) {
      api.camera.fov = cam.fov || fov;
      api.camera.aspect = rw / rh;
      api.camera.position.set(...cam.position);
      api.camera.lookAt(...cam.lookAt);
      api.camera.updateProjectionMatrix();
    } else {
      api.camera.aspect = rw / rh;
      api.camera.updateProjectionMatrix();
    }
    const captureRt = new THREE.WebGLRenderTarget(rw, rh, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      type: THREE.UnsignedByteType,
      generateMipmaps: false,
    });
    api.renderer.setRenderTarget(captureRt);
    const restoreCsHelpers = setHelpersVisible(api.scene, false); // 拍到的画面不该有机位/坐标轴
    api.renderer.render(api.scene, api.camera);
    restoreCsHelpers();
    api.renderer.setRenderTarget(null);
    const dataUrl = readRenderTargetToDataURL(api.renderer, captureRt, rw, rh);
    captureRt.dispose();
    api.renderer.setSize(prevW, prevH, false);
    api.camera.aspect = w / Math.max(h, 1);
    api.camera.updateProjectionMatrix();
    // restore director/camera view
    if (viewMode === "camera" && activeCam) {
      api.camera.fov = activeCam.fov || fov;
      api.camera.position.set(...activeCam.position);
      api.camera.lookAt(...activeCam.lookAt);
      api.camera.updateProjectionMatrix();
    }
    const camFov = cam?.fov || activeCam?.fov || fov;
    const camShotSize = cam?.shotSize || activeCam?.shotSize || "中景";
    onCapture(dataUrl, {
      cameraName: cam?.name || activeCam?.name || "导演视角",
      fov: camFov,
      focalLength: fovToFocalLength(camFov),
      shotSize: camShotSize,
      aspect: aspect === "auto" ? "9:16" : aspect,
      aperture: 2.8,
    });
  };

  const captureAllCams = () => {
    if (!cameras.length) {
      onStatus("没有机位可截图");
      return;
    }
    cameras.forEach((c, i) => {
      window.setTimeout(() => capture(c), i * 120);
    });
    onStatus(`已按 ${cameras.length} 个机位截图入画布`);
  };

  /** 导出 ControlNet 三通道（Depth / Normal / OpenPose），打包 zip 下载 */
  const controlNetExport = () => {
    const api = apiRef.current;
    if (!api) {
      onStatus("3D 场景尚未就绪");
      return;
    }
    const actorActors = Array.from(api.objects.values()).filter(
      (o) => (o as THREE.Object3D).userData.meshStyle === RIG_MESH_STYLE,
    );
    const w = api.renderer.domElement.width || 1024;
    const h = api.renderer.domElement.height || 576;
    const current = api.camera;
    const result = exportAllControlNetChannels(api.scene, current, api.renderer, actorActors, w, h);
    const packs: { name: string; data: string }[] = [];
    if (result.depth) packs.push({ name: "controlnet_depth.png", data: result.depth });
    if (result.normal) packs.push({ name: "controlnet_normal.png", data: result.normal });
    if (result.openpose) packs.push({ name: "controlnet_openpose.png", data: result.openpose });
    if (!packs.length) {
      onStatus("导出失败，无有效数据");
      return;
    }
    packs.forEach((p) => {
      const a = document.createElement("a");
      a.href = p.data;
      a.download = p.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    });
    onStatus(`已导出 ${packs.length} 个 ControlNet 通道（${actorActors.length} 个演员骨架）`);
    // 除了浏览器下载，同时入库并登记 —— 这类产物在画布侧只有 data URL，没有本机路径，
    // 必须经 /host/upload-asset 落 inbox 才能送剪辑（唯一通道见 stage3dArtifacts.ts）
    void registerControlNetArtifacts(packs).then((n) =>
      onStatus(`已入库 ${n}/${packs.length} 个 ControlNet 通道，可点「最近产物 → 时间线」`),
    );
  };

  /** 导出选中角色（或第一个有 Motion 的角色）的 BVH 动画文件 */
  const bvhExportSelected = () => {
    const targetId = selectedId ?? activeMotionsRef.current.keys().next().value;
    if (!targetId) {
      onStatus("请先选中一个角色，或为角色启用动作轨迹");
      return;
    }
    const motions = activeMotionsRef.current.get(targetId);
    const actor = actorsRef.current.find((a) => a.id === targetId);
    if (!actor) {
      onStatus("未找到角色");
      return;
    }
    let frames: JointPose[];
    let roots: [number, number, number][] | null = null;
    if (motions && motions.length > 0) {
      const totalDuration = motions.reduce((s, m) => s + m.duration, 0);
      const { pose, rootPositions } = sampleMotionFrames(motions, Math.max(totalDuration, 4000), 30);
      frames = pose;
      roots = rootPositions.some((p) => p[0] !== 0 || p[1] !== 0 || p[2] !== 0) ? rootPositions : null;
    } else {
      frames = [actorPose(actor)];
    }
    const bvh = exportBVH(frames, roots, 30);
    const blob = new Blob([bvh], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${actor.name || "actor"}_${motions?.map((m) => m.id).join("_") || "static"}.bvh`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    onStatus(`BVH 已导出（${frames.length} 帧 · ${motions?.length ?? 0} 个动作轨迹）`);
  };

  /** 沿当前机位的 pathPoints 导出首尾帧，供视频生成管线使用 */
  /** 根据宽高比选最高可用的目标分辨率（与 CogVideoX 支持的尺寸对齐） */
  const pickExportResolution = (aspectRatio: number): [number, number] => {
    const candidates: Array<[number, number]> = [
      [1920, 1080],
      [1280, 720],
      [854, 480],
    ];
    const portraitCandidates: Array<[number, number]> = [
      [720, 1280],
      [1080, 1920],
      [480, 854],
    ];
    const isPortrait = aspectRatio < 1;
    const pool = isPortrait ? portraitCandidates : candidates;
    let best: [number, number] = pool[0];
    let bestErr = Infinity;
    for (const [w, h] of pool) {
      const err = Math.abs(w / h - aspectRatio);
      if (err < bestErr) { bestErr = err; best = [w, h]; }
    }
    return best;
  };


  /** 内部：导出单个机位的首尾帧 + 角色参考图，返回 meta */
  const _exportSingleCamMeta = (cam: any, aspectOverride?: string) => {
    const api = apiRef.current!;
    const el = mountRef.current!;
    const viewW = el.clientWidth;
    const viewH = el.clientHeight;
    let aspectRatio = viewW / viewH;
    const asp = aspectOverride || aspect;
    if (asp !== "auto" && asp.includes(":")) {
      const [aw, ah] = asp.split(":").map(Number);
      if (aw > 0 && ah > 0) aspectRatio = aw / ah;
    }
    const [targetW, targetH] = pickExportResolution(aspectRatio);

    const savedFov = api.camera.fov;
    const savedPos = api.camera.position.clone();
    const savedTarget = api.controls.target.clone();
    const savedCamAspect = api.camera.aspect;
    const prevW = api.renderer.domElement.width;
    const prevH = api.renderer.domElement.height;
    const composer = composerRef.current;

    const rt = new THREE.WebGLRenderTarget(targetW, targetH, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      type: THREE.UnsignedByteType,
      generateMipmaps: false,
    });

    api.renderer.setSize(targetW, targetH, false);
    composer?.setSize(targetW, targetH);
    api.camera.fov = cam.fov || fov;
    api.camera.aspect = targetW / targetH;
    api.camera.updateProjectionMatrix();
    api.renderer.setRenderTarget(rt);

    let firstFrame = "";
    let lastFrame = "";
    let referenceImage = "";
    let referenceActor = "";

    const renderScene = () => {
      const restorePathHelpers = setHelpersVisible(api.scene, false); // 导出视频不带编辑辅助物
      composer ? composer.render(api.scene, api.camera) : api.renderer.render(api.scene, api.camera);
      restorePathHelpers();
    };

    const firstPt = cam.pathPoints[0];
    api.camera.position.set(...firstPt.pos);
    api.controls.target.set(...firstPt.look);
    renderScene();
    firstFrame = readRenderTargetToDataURL(api.renderer, rt, targetW, targetH);

    const lastPt = cam.pathPoints[cam.pathPoints.length - 1];
    api.camera.position.set(...lastPt.pos);
    api.controls.target.set(...lastPt.look);
    renderScene();
    lastFrame = readRenderTargetToDataURL(api.renderer, rt, targetW, targetH);

    const refActorId = actors.find((a) => a.kind === "actor")?.id;
    if (refActorId) {
      const refActor = actors.find((a) => a.id === refActorId)!;
      const refObj = api.objects.get(refActorId);
      if (refObj) {
        const actorPos = refObj.position.clone();
        const headY = actorPos.y + (refActor.scale || 1) * 1.55;
        const faceDist = 2.2;
        const angle = refActor.rotationY || 0;
        const cx = actorPos.x + Math.sin(angle) * faceDist;
        const cz = actorPos.z + Math.cos(angle) * faceDist;
        api.camera.position.set(cx, headY - 0.3, cz);
        api.camera.fov = 35;
        api.camera.aspect = targetW / targetH;
        api.camera.updateProjectionMatrix();
        api.controls.target.set(actorPos.x, headY, actorPos.z);
        renderScene();
        referenceImage = readRenderTargetToDataURL(api.renderer, rt, targetW, targetH);
        referenceActor = refActor.name || refActor.id;
      }
    }

    api.renderer.setRenderTarget(null);
    api.renderer.setSize(prevW, prevH, false);
    composer?.setSize(prevW, prevH);
    api.camera.fov = savedFov;
    api.camera.position.copy(savedPos);
    api.controls.target.copy(savedTarget);
    api.camera.aspect = savedCamAspect;
    api.camera.updateProjectionMatrix();
    rt.dispose();

    return {
      firstFrame,
      lastFrame,
      referenceImage: referenceImage || undefined,
      referenceActor: referenceActor || undefined,
      resolution: `${targetW}x${targetH}`,
    };
  };

  const exportFirstLastFrames = () => {
    const api = apiRef.current;
    if (!api) return;
    const cam = activeCam;
    if (!cam?.pathPoints?.length) {
      onStatus("当前机位没有路径，请先生成路径后再导出首尾帧");
      return;
    }
    if (!onExportFirstLast) {
      onStatus("父组件未接入 onExportFirstLast 回调");
      return;
    }
    const meta = _exportSingleCamMeta(cam);
    const resSize = meta.resolution;
    onExportFirstLast(meta.firstFrame, meta.lastFrame, {
      cameraName: cam.name || "未命名机位",
      totalPoints: cam.pathPoints.length,
      aspect,
      resolution: resSize,
      referenceImage: meta.referenceImage,
      referenceActor: meta.referenceActor,
      referenceVideoUrl: motionRefVideo?.url || "",
    });
    onStatus(
      `已导出首尾帧 ${resSize}（${cam.pathPoints.length} 点${meta.referenceActor ? ` · 参考「${meta.referenceActor}」` : ""}${motionRefVideo ? ` · 动作参考「${motionRefVideo.name}」` : ""}）`,
    );
  };

  /** 批量导出所有有 pathPoints 的机位 → 分镜数组，交给 V2/V3 编排层 */
  const exportAllCamerasBatch = () => {
    if (!onExportBatch) {
      onStatus("父组件未接入 onExportBatch 回调");
      return;
    }
    const eligible = cameras.filter((c) => c.pathPoints?.length);
    if (!eligible.length) {
      onStatus("没有找到带路径点的机位，请先在各机位生成路径");
      return;
    }
    onStatus(`开始批量导出 ${eligible.length} 个机位的首尾帧…`);
    const segments: Array<{
      cameraName: string;
      firstFrame: string;
      lastFrame: string;
      referenceImage?: string;
      referenceActor?: string;
      totalPoints: number;
      resolution: string;
      promptHint: string;
    }> = [];
    // 全局共享一张角色正脸：批量模式下所有机位用同一张，保证角色身份一致
    let globalReferenceImage: string | undefined;
    let globalReferenceActor: string | undefined;
    const sharedActorId = actors.find((a) => a.kind === "actor")?.id;

    // 复用同一个离屏 RenderTarget 方案（通过 _exportSingleCamMeta 内部处理）
    for (const cam of eligible) {
      try {
        const meta = _exportSingleCamMeta(cam);
        segments.push({
          cameraName: cam.name || `机位${segments.length + 1}`,
          firstFrame: meta.firstFrame,
          lastFrame: meta.lastFrame,
          // 临时用 _exportSingleCamMeta 内部渲染的那张，后面统一覆盖
          referenceImage: meta.referenceImage,
          referenceActor: meta.referenceActor,
          totalPoints: cam.pathPoints.length,
          resolution: meta.resolution,
          promptHint: `${cam.name || "机位"} ${cam.pathPoints.length} 个路径点运镜插值，电影感构图`,
        });
        // 第一次拿到 referenceImage 就存作全局共享
        if (!globalReferenceImage && meta.referenceImage) {
          globalReferenceImage = meta.referenceImage;
          globalReferenceActor = meta.referenceActor;
        }
      } catch (e: any) {
        onStatus(`导出「${cam.name || cam.id}」失败: ${e?.message || e}`);
      }
    }
    // 用全局共享 reference_image 统一覆盖所有 segment — 保证角色身份在所有分镜中完全一致
    if (globalReferenceImage) {
      for (const seg of segments) {
        seg.referenceImage = globalReferenceImage;
        seg.referenceActor = globalReferenceActor;
      }
      onStatus(
        `✅ 已锁定角色「${globalReferenceActor || "角色"}」为全局参考图 · ${segments.length} 段共享`,
      );
    }
    if (!segments.length) {
      onStatus("所有机位导出失败");
      return;
    }
    onExportBatch(segments);
    onStatus(`✅ 批量导出完成 ${segments.length}/${eligible.length} 个分镜`);
  };

  const captureActorViews = (actorId: string) => {
    const api = apiRef.current;
    if (!api) return;
    const actor = actors.find((a) => a.id === actorId);
    if (!actor) {
      onStatus("请先选中一个角色");
      return;
    }
    if (!onCaptureActorViews) {
      onStatus("三视图功能未接入画布");
      return;
    }

    const el = mountRef.current!;
    const rw = Math.round(el.clientWidth * 0.6);
    const rh = Math.round(rw * 1.4);

    const prevW = api.renderer.domElement.width;
    const prevH = api.renderer.domElement.height;
    api.renderer.setSize(rw, rh, false);

    const actorCenter = new THREE.Vector3(
      actor.position[0],
      actor.position[1] + 0.9,
      actor.position[2],
    );
    const dist = 3;
    const halfSize = 1.3;

    const yaw = actor.rotationY;
    const forward = new THREE.Vector3(Math.sin(yaw), 0, Math.cos(yaw));
    const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));

    const renderOrtho = (camPos: THREE.Vector3): string => {
      const ortho = new THREE.OrthographicCamera(
        -halfSize,
        halfSize,
        halfSize * (rh / rw),
        -halfSize * (rh / rw),
        0.1,
        20,
      );
      ortho.position.copy(camPos);
      ortho.lookAt(actorCenter);
      const orthoRt = new THREE.WebGLRenderTarget(rw, rh, {
        minFilter: THREE.LinearFilter,
        magFilter: THREE.LinearFilter,
        format: THREE.RGBAFormat,
        type: THREE.UnsignedByteType,
        generateMipmaps: false,
      });
      api.renderer.setRenderTarget(orthoRt);
      api.renderer.render(api.scene, ortho);
      api.renderer.setRenderTarget(null);
      const dataUrl = readRenderTargetToDataURL(api.renderer, orthoRt, rw, rh);
      orthoRt.dispose();
      ortho.dispose();
      return dataUrl;
    };

    const views = {
      front: renderOrtho(actorCenter.clone().add(forward.clone().multiplyScalar(dist))),
      side: renderOrtho(actorCenter.clone().add(right.clone().multiplyScalar(dist))),
      back: renderOrtho(actorCenter.clone().add(forward.clone().negate().multiplyScalar(dist))),
    };

    api.renderer.setSize(prevW, prevH, false);
    onCaptureActorViews(views, actor.name);
    onStatus(`已导出三视图：${actor.name}`);
  };

  // ============ D: 镜头路径 MVP ============

  /** 选两个机位，生成 N 个插值中间点 */
  const generateCamPath = (fromId: string, toId: string, steps = 8, duration = 3000) => {
    const from = cameras.find((c) => c.id === fromId);
    const to = cameras.find((c) => c.id === toId);
    if (!from || !to) {
      onStatus("请先添加两个以上机位");
      return;
    }
    const pathPoints: { pos: [number, number, number]; look: [number, number, number] }[] = [];
    for (let i = 1; i <= steps; i++) {
      const t = i / steps;
      pathPoints.push({
        pos: [
          from.position[0] + (to.position[0] - from.position[0]) * t,
          from.position[1] + (to.position[1] - from.position[1]) * t,
          from.position[2] + (to.position[2] - from.position[2]) * t,
        ],
        look: [
          from.lookAt[0] + (to.lookAt[0] - from.lookAt[0]) * t,
          from.lookAt[1] + (to.lookAt[1] - from.lookAt[1]) * t,
          from.lookAt[2] + (to.lookAt[2] - from.lookAt[2]) * t,
        ],
      });
    }
    setCameras((prev) =>
      prev.map((c) =>
        c.id === toId ? { ...c, pathPoints, pathDuration: duration } : c,
      ),
    );
    onStatus(`已为「${to.name}」生成从「${from.name}」的 ${steps} 段路径`);
  };

  // ============ 一键运镜（8 种）+ 跟踪主体 + 轨迹范围 ============

  type CamMoveId =
    | "push" | "pull" | "panL" | "panR" | "tilt" | "crane" | "trackL" | "trackR";

  const CAM_MOVES: { id: CamMoveId; label: string }[] = [
    { id: "push", label: "推镜" },
    { id: "pull", label: "拉镜" },
    { id: "panL", label: "左摇镜" },
    { id: "panR", label: "右摇镜" },
    { id: "tilt", label: "俯仰抬镜" },
    { id: "crane", label: "俯拍压镜" },
    { id: "trackL", label: "左移镜" },
    { id: "trackR", label: "右移镜" },
  ];

  /** 生成一键运镜路径：以当前机位为起点，按运镜类型生成 pathPoints */
  const applyCameraMove = (move: CamMoveId) => {
    const cam = cameras.find((c) => c.id === activeCamId);
    if (!cam) {
      onStatus("请先选中一个机位（或添加当前视角机位）");
      return;
    }
    // 跟踪主体：优先用选中角色位置作为 lookAt 目标
    const trackActor = actors.find((a) => a.id === (trackTargetId || selectedId));
    const target: [number, number, number] = trackActor
      ? [trackActor.position[0], 1.2 * trackActor.scale, trackActor.position[2]]
      : cam.lookAt;
    const range = moveRange / 100; // 轨迹范围 0~1
    const steps = 10;
    const pts: { pos: [number, number, number]; look: [number, number, number] }[] = [];
    const start = cam.position;
    const dirToTarget = new THREE.Vector3(
      target[0] - start[0], target[1] - start[1], target[2] - start[2],
    );
    const dist = dirToTarget.length();
    dirToTarget.normalize();
    // 右向量（水平垂直于视线）
    const right = new THREE.Vector3().crossVectors(dirToTarget, new THREE.Vector3(0, 1, 0)).normalize();
    for (let i = 1; i <= steps; i++) {
      const t = (i / steps) * range;
      let pos: [number, number, number] = [...start] as [number, number, number];
      let look: [number, number, number] = [...target] as [number, number, number];
      switch (move) {
        case "push": {
          const d = Math.min(dist * 0.6, dist - 0.5) * t;
          pos = [start[0] + dirToTarget.x * d, start[1] + dirToTarget.y * d * 0.3, start[2] + dirToTarget.z * d];
          break;
        }
        case "pull": {
          const d = dist * 0.6 * t;
          pos = [start[0] - dirToTarget.x * d, start[1] + dirToTarget.y * d * 0.2, start[2] - dirToTarget.z * d];
          break;
        }
        case "panL":
        case "panR": {
          const sign = move === "panL" ? 1 : -1;
          const ang = sign * (Math.PI / 6) * t; // 30° 摇镜
          const rx = start[0] + (right.x * sign) * Math.sin(ang) * dist * 0.4;
          const rz = start[2] + (right.z * sign) * Math.sin(ang) * dist * 0.4;
          pos = [rx, start[1], rz];
          break;
        }
        case "tilt": {
          look = [target[0], target[1] + 1.2 * t, target[2]];
          break;
        }
        case "crane": {
          pos = [start[0], start[1] + 2.5 * t, start[2]];
          look = [target[0], target[1] - 0.5 * t, target[2]];
          break;
        }
        case "trackL":
        case "trackR": {
          const sign = move === "trackL" ? 1 : -1;
          const d = 2.0 * t * sign;
          pos = [start[0] + right.x * d, start[1], start[2] + right.z * d];
          break;
        }
      }
      pts.push({ pos, look });
    }
    setCameras((prev) =>
      prev.map((c) => (c.id === cam.id ? { ...c, pathPoints: pts, pathDuration: 3000 } : c)),
    );
    onStatus(`已生成「${CAM_MOVES.find((m) => m.id === move)?.label}」路径（范围 ${moveRange}%）`);
  };

  // ============ 掌镜（WASD 自由走镜头） ============
  const wasdRef = useRef<Set<string>>(new Set());
  const wasdActiveRef = useRef(false);
  const [wasdActive, setWasdActive] = useState(false);
  /** 角色路线播放进度（ref，避免 tick 内 setState 抖动） */
  const routeProgressRef = useRef<Map<string, number>>(new Map());

  // WASD 键盘监听（仅掌镜模式）
  useEffect(() => {
    if (!wasdActive) return;
    const down = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (["w", "a", "s", "d", "q", "e"].includes(k)) {
        e.preventDefault();
        wasdRef.current.add(k);
      }
    };
    const up = (e: KeyboardEvent) => {
      wasdRef.current.delete(e.key.toLowerCase());
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      wasdRef.current.clear();
    };
  }, [wasdActive]);

  const toggleWasd = () => {
    const next = !wasdActiveRef.current;
    wasdActiveRef.current = next;
    setWasdActive(next);
    if (next) {
      onStatus("掌镜模式：WASD 走镜头 · Q/E 升降 · 再点一次退出");
    } else {
      wasdRef.current.clear();
      onStatus("已退出掌镜模式");
    }
  };

  // ============ 角色路线（添加点 / 平滑折线 / 速度） ============
  type RouteShape = "smooth" | "polyline";
  type RouteSpeed = "uniform" | "soft" | "custom";
  const [routeShape, setRouteShape] = useState<RouteShape>("smooth");
  const [routeSpeed, setRouteSpeed] = useState<RouteSpeed>("uniform");

  const addRoutePoint = () => {
    const actor = actors.find((a) => a.id === selectedId);
    if (!actor) {
      onStatus("请先选中一个角色再添加路线点");
      return;
    }
    const api = apiRef.current;
    if (!api) return;
    // 在角色前方 1m 处添加一个点（可后续拖拽）
    const fwd = new THREE.Vector3(Math.sin(actor.rotationY), 0, Math.cos(actor.rotationY));
    const existing = actor.route?.points || [];
    const last = existing.length ? existing[existing.length - 1] : actor.position;
    const pt: [number, number, number] = [last[0] + fwd.x, 0, last[2] + fwd.z];
    setActors((prev) =>
      prev.map((a) =>
        a.id === actor.id
          ? { ...a, route: { points: [...existing, pt], shape: routeShape, speed: routeSpeed, playing: a.route?.playing ?? false } }
          : a,
      ),
    );
    onStatus(`已为「${actor.name}」添加路线点（共 ${existing.length + 1} 个）`);
  };

  const clearRoute = () => {
    if (!selectedId) return;
    setActors((prev) =>
      prev.map((a) => (a.id === selectedId ? { ...a, route: undefined } : a)),
    );
    onStatus("已清空角色路线");
  };

  const toggleRoutePlay = () => {
    const actor = actors.find((a) => a.id === selectedId);
    if (!actor?.route?.points?.length) {
      onStatus("请先添加至少一个路线点");
      return;
    }
    const playing = !actor.route.playing;
    setActors((prev) =>
      prev.map((a) => (a.id === selectedId ? { ...a, route: { ...a.route!, playing } } : a)),
    );
    onStatus(playing ? "角色开始沿路线移动" : "角色路线已暂停");
  };

  /** 导入自定义动作（FBX / GLB）— 记录文件名，占位提示（完整骨骼解析待后续） */
  const onImportMotion = async (file: File | null) => {
    if (!file) return;
    const name = file.name.replace(/\.(fbx|glb|gltf)$/i, "");
    onStatus(`已登记自定义动作「${name}」（${file.name}）· 骨骼解析待后续版本`);
  };

  /** 参考视频驱动（模式 A）：上传到宿主 inbox，生成视频时作为 motion-ref 条件 */
  const onMotionRefVideoPick = async (file: File | null) => {
    if (!file) return;
    onStatus(`正在上传参考视频「${file.name}」…`);
    const res = await uploadAssetToHost(file);
    if (res.ok && res.url) {
      setMotionRefVideo({ url: res.url, name: file.name });
      setMotionPoseData(null);
      // 换视频即丢弃旧轨迹与驱动状态（避免错配驱动）
      stopPoseDriveLoop();
      poseTrackRef.current = null;
      setPoseDriveOn(false);
      setPosePlaying(false);
      setPoseBadFrames(new Set());
      setPoseEditOn(false);
      onStatus(`参考视频已挂载「${file.name}」，生成视频时将作为动作参考条件`);
    } else {
      onStatus(`参考视频上传失败：${res.message || "未知错误"}`);
    }
  };

  /** 模式 B 姿态解析：参考视频 → 子进程 BlazePose 关键点 JSON（推理完进程退出释放显存） */
  const onPoseExtract = async () => {
    if (!motionRefVideo || poseBusy) return;
    setPoseBusy(true);
    onStatus(`正在解析参考视频姿态（模式 B）「${motionRefVideo.name}」…`);
    try {
      const res = await poseExtractViaHost({ video: motionRefVideo.url });
      if (res.ok && res.json_url) {
        setMotionPoseData({
          frames: res.frame_count || 0,
          duration: res.duration || 0,
          fps: res.fps || 0,
          url: res.json_url,
        });
        // 解析成功即拉取关键点轨迹（第三刀驱动白模的直接输入）
        await loadPoseTrack(res.json_url);
      } else {
        onStatus(`❌ 姿态解析失败：${res.message || "未知错误"}`);
      }
    } catch (e) {
      onStatus(`❌ 姿态解析异常：${(e as Error).message}`);
    } finally {
      setPoseBusy(false);
    }
  };

  /* ── 模式 B 第三刀：关键点 → 白模 IK 时序驱动 ─────────────────── */

  /** 求解第 i 帧姿态（缓存 + 坏帧插值；关键点全缺失帧自动插值，手动坏帧强制插值） */
  const solvePoseForFrame = (i: number): JointPose | null => {
    const track = poseTrackRef.current;
    if (!track || i < 0 || i >= track.frames.length) return null;
    const cached = poseSolvedCacheRef.current.get(i);
    if (cached) return cached;
    const isBad = poseBadFrames.has(i) || isFrameEmpty(track.frames[i]);
    if (!isBad) {
      const prev = poseSolvedCacheRef.current.get(i - 1) ?? null;
      const pose = solveFramePose(track.frames[i], prev);
      poseSolvedCacheRef.current.set(i, pose);
      return pose;
    }
    // 坏帧：向两侧找最近好帧线性插值
    let p = i - 1;
    while (p >= 0 && (poseBadFrames.has(p) || isFrameEmpty(track.frames[p]))) p--;
    let q = i + 1;
    while (q < track.frames.length && (poseBadFrames.has(q) || isFrameEmpty(track.frames[q]))) q++;
    const poseP = p >= 0 ? solvePoseForFrame(p) : null;
    const poseQ = q < track.frames.length ? solvePoseForFrame(q) : null;
    if (poseP && poseQ) {
      const t = q === p ? 0 : (i - p) / (q - p);
      return lerpJointPose(poseP, poseQ, t);
    }
    return poseP ?? poseQ;
  };

  /** 把第 i 帧姿态 + root 偏移应用到目标 actor（驱动与手动 scrub 共用） */
  const applyPoseFrameToActor = (i: number, actorId: string) => {
    const track = poseTrackRef.current;
    const api = apiRef.current;
    if (!track || !api) return;
    const obj = api.objects.get(actorId);
    if (!obj) return;
    const pose = solvePoseForFrame(i);
    if (!pose) return;
    applyPoseResolved(obj, pose);
    const base = poseDriveBasePosRef.current;
    if (base) {
      const [dx, dy, dz] = solveFrameRoot(track, i, poseStandHipYRef.current);
      obj.position.set(base[0] + dx, base[1] + dy, base[2] + dz);
    }
  };

  /** 停止姿态驱动播放（rAF），保留驱动开关状态 */
  const stopPoseDriveLoop = () => {
    if (poseDriveRafRef.current !== null) {
      cancelAnimationFrame(poseDriveRafRef.current);
      poseDriveRafRef.current = null;
    }
  };

  /** 停止姿态驱动播放（rAF） */
  const stopPoseDrive = () => {
    stopPoseDriveLoop();
    setPosePlaying(false);
    setPoseDriveOn(false);
    poseSolvedCacheRef.current.clear();
    // 还原 actor 姿势与位置
    const actorId = selectedRef.current;
    const obj = actorId ? apiRef.current?.objects.get(actorId) : null;
    const actor = actorId ? actorsRef.current.find((a) => a.id === actorId) : null;
    if (obj && actor) applyPose(obj, actorPose(actor));
    const base = poseDriveBasePosRef.current;
    if (obj && base) {
      obj.position.set(base[0], base[1], base[2]);
      poseDriveBasePosRef.current = null;
    }
  };

  /** 姿态驱动播放循环：按轨迹有效帧率推进，循环往返 */
  const startPoseDriveLoop = () => {
    const track = poseTrackRef.current;
    const actorId = selectedRef.current;
    if (!track || !actorId) return;
    stopPoseDriveLoop();
    const effFps = Math.max(1, track.fps);
    poseDriveT0Ref.current = performance.now();
    const step = () => {
      const trackNow = poseTrackRef.current;
      const aid = selectedRef.current;
      if (!trackNow || !aid) return;
      const elapsed = (performance.now() - poseDriveT0Ref.current) / 1000;
      const total = trackNow.frames.length;
      const cycle = total * 2;
      const raw = Math.floor(elapsed * effFps) % cycle;
      const idx = raw < total ? raw : cycle - 1 - raw;
      setPoseFrameIdx(idx);
      applyPoseFrameToActor(idx, aid);
      poseDriveRafRef.current = requestAnimationFrame(step);
    };
    poseDriveRafRef.current = requestAnimationFrame(step);
  };

  /** 拉取并解析姿态 JSON（解析完成后自动调用；失败诚实提示） */
  const loadPoseTrack = async (url: string) => {
    onStatus("正在加载关键点 JSON…");
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const track = parsePoseTrack(json);
      if (!track) throw new Error("JSON 结构无效（无有效帧）");
      poseTrackRef.current = track;
      poseSolvedCacheRef.current.clear();
      poseStandHipYRef.current = findStandHipY(track);
      setPoseBadFrames(new Set());
      setPoseFrameIdx(0);
      onStatus(`🦴 关键点轨迹已加载：${track.frameCount} 帧 · ${track.duration}s（可驱动白模）`);
    } catch (e) {
      poseTrackRef.current = null;
      onStatus(`❌ 关键点 JSON 加载失败：${(e as Error).message}`);
    }
  };

  /** 驱动开关切换：开启时记录 actor 基准位置并立即应用首帧 */
  const togglePoseDrive = () => {
    const track = poseTrackRef.current;
    if (!track) {
      onStatus("请先解析姿态并加载关键点轨迹");
      return;
    }
    if (poseDriveOn) {
      stopPoseDrive();
      onStatus("已关闭白模姿态驱动");
      return;
    }
    const actorId = selectedRef.current;
    const actor = actorId ? actorsRef.current.find((a) => a.id === actorId) : null;
    const obj = actorId ? apiRef.current?.objects.get(actorId) : null;
    if (!actor || actor.kind !== "actor" || !obj) {
      onStatus("请先选中一个角色（actor）再开启驱动");
      return;
    }
    poseDriveBasePosRef.current = [obj.position.x, obj.position.y, obj.position.z];
    setPoseDriveOn(true);
    setPosePlaying(false);
    applyPoseFrameToActor(poseFrameIdx, actorId);
    onStatus(`🧍 白模姿态驱动已开启（${track.frameCount} 帧，选中角色逐帧跟随）`);
  };

  /** 播放/暂停姿态时序 */
  const togglePosePlay = () => {
    if (!poseDriveOn) return;
    if (posePlaying) {
      stopPoseDriveLoop();
      setPosePlaying(false);
    } else {
      setPosePlaying(true);
      startPoseDriveLoop();
    }
  };

  /** 手动步进帧（暂停时 scrub；同时应用到 actor） */
  const stepPoseFrame = (delta: number) => {
    const track = poseTrackRef.current;
    if (!track) return;
    if (posePlaying) {
      stopPoseDriveLoop();
      setPosePlaying(false);
    }
    const next = Math.min(track.frames.length - 1, Math.max(0, poseFrameIdx + delta));
    setPoseFrameIdx(next);
    const actorId = selectedRef.current;
    if (poseDriveOn && actorId) applyPoseFrameToActor(next, actorId);
  };

  /** 时间轴 scrub 到指定帧 */
  const scrubPoseFrame = (i: number) => {
    const track = poseTrackRef.current;
    if (!track) return;
    const next = Math.min(track.frames.length - 1, Math.max(0, i));
    setPoseFrameIdx(next);
    const actorId = selectedRef.current;
    if (poseDriveOn && actorId) applyPoseFrameToActor(next, actorId);
  };

  /** 标记/取消坏帧（该帧播放时用前后好帧插值替换） */
  const togglePoseBadFrame = (i: number) => {
    setPoseBadFrames((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
    // 该帧缓存失效（插值结果随标记变化）
    poseSolvedCacheRef.current.delete(i);
    if (poseDriveOn && i === poseFrameIdx) {
      const actorId = selectedRef.current;
      if (actorId) applyPoseFrameToActor(i, actorId);
    }
  };

  /** 重置全部手动修正与坏帧标记（重新从解析结果求解） */
  const resetPoseEdits = () => {
    const track = poseTrackRef.current;
    if (!track) return;
    // 重新加载原始 JSON（丢弃叠加在 ref 上的关键点修正）
    void loadPoseTrack(motionPoseData?.url || "");
    setPoseEditOn(false);
  };

  /**
   * 第四刀：录制白模动作视频（逐帧渲染 → 采集 PNG → 后端 FFmpeg 合成 → 挂为 reference_video）
   *
   * 为什么逐帧采集而不是前端实时录制：见 `stage3dPoseVideo.ts` 顶部说明
   * （MediaRecorder 会掉帧；主画面 canvas 是 preserveDrawingBuffer:false）。
   *
   * ⚠️ 两个必须处理的细节（不处理就会录出"能看但不对"的片子）：
   *  1. **必须先设 `poseDriveBasePosRef`** —— `applyPoseFrameToActor` 的 root 位移
   *     依赖它，为空时只应用原地姿态、**走位丢失**。而走位是漫剧刚需（设计文档 §一）。
   *  2. 录制分辨率压到 540 宽即可 —— 运动参考视频的模型只看动作，不需要高分辨率；
   *     压小可显著降低帧内存与编码耗时。
   */
  const recordPoseVideo = async () => {
    const track = poseTrackRef.current;
    const actorId = selectedRef.current;
    const api = apiRef.current;
    const el = mountRef.current;
    if (!track) {
      onStatus("请先解析姿态并加载关键点轨迹");
      return;
    }
    if (!actorId) {
      onStatus("请先选中一个角色再录制白模动作");
      return;
    }
    if (!api || !el) {
      onStatus("3D 视图未就绪，无法录制");
      return;
    }
    if (poseVideoBusy) return;

    // 运动参考不需要高分辨率：压到 ≤540 宽，保证偶数边长（libx264 + yuv420p 要求）
    const viewW = Math.max(1, el.clientWidth);
    const viewH = Math.max(1, el.clientHeight);
    let targetW = Math.max(2, Math.min(540, viewW));
    targetW -= targetW % 2;
    let targetH = Math.max(2, Math.round((targetW * viewH) / viewW));
    targetH -= targetH % 2;

    const savedPos = api.camera.position.clone();
    const savedTarget = api.controls.target.clone();
    const savedAspect = api.camera.aspect;
    const prevW = api.renderer.domElement.width;
    const prevH = api.renderer.domElement.height;
    const composer = composerRef.current;

    // ① 记录并设置 root 基准（否则走位丢失）；录制结束恢复
    const actorObj = api.objects.get(actorId);
    const savedBase = poseDriveBasePosRef.current;
    const savedActorPos = actorObj ? actorObj.position.clone() : null;
    if (actorObj) {
      poseDriveBasePosRef.current = [actorObj.position.x, actorObj.position.y, actorObj.position.z];
    }

    const rt = new THREE.WebGLRenderTarget(targetW, targetH, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      type: THREE.UnsignedByteType,
      generateMipmaps: false,
    });

    setPoseVideoBusy(true);
    setPoseVideoProgress(0);
    try {
      api.renderer.setSize(targetW, targetH, false);
      composer?.setSize(targetW, targetH);
      api.camera.aspect = targetW / targetH;
      api.camera.updateProjectionMatrix();
      api.renderer.setRenderTarget(rt);

      const cap = await capturePoseFrames(
        {
          renderFrameToRT: (i) => {
            applyPoseFrameToActor(i, actorId);
            // 注意：EffectComposer.render() 的签名是 render(deltaTime?: number)，
            // scene/camera 在 RenderPass 构造时就已绑定（见本文件 new RenderPass(scene, camera)）。
            // 传 (scene, camera) 会被当成 deltaTime —— 类型不匹配（TS2554）且语义错误。
            const restorePoseHelpers = setHelpersVisible(api.scene, false); // 白模视频不带编辑辅助物
            if (composer) composer.render();
            else api.renderer.render(api.scene, api.camera);
            restorePoseHelpers();
          },
          readRTAsDataUrl: () => readRenderTargetToDataURL(api.renderer, rt, targetW, targetH),
        },
        track.frames.length,
        { onProgress: (done) => setPoseVideoProgress(done) },
      );

      if (!cap.ok) {
        onStatus(`❌ ${cap.message}`);
        return;
      }
      if (cap.capped) {
        onStatus(
          `帧数超上限已抽稀：每 ${cap.step.toFixed(1)} 帧取 1（共 ${cap.frames.length} 帧）`,
        );
      }

      // 帧率按「采集帧数 ÷ 原时长」反推 —— 这样成片时长与原动作一致（抽稀后仍对得上）
      const dur = Number(track.duration) || 0;
      const fps = dur > 0
        ? Math.max(1, Math.min(120, Math.round(cap.frames.length / dur)))
        : 25;

      onStatus(`⏳ 正在合成白模视频（${cap.frames.length} 帧 @ ${fps}fps）…`);
      const enc = await encodePoseVideo(cap.frames, fps, `白模动作_${cap.frames.length}帧`);
      if (!enc.ok || !enc.url) {
        onStatus(`❌ ${enc.message || "白模视频合成失败"}`);
        return;
      }
      // 挂为动作参考视频 → 走第一刀既有通道（reference_video）
      setMotionRefVideo({
        url: enc.url,
        name: `白模动作_${enc.frames}帧_${enc.duration}s.mp4`,
      });
      // 登记为可送剪辑的产物（是否入轨由用户点「→ 时间线」决定，录制本身不自动入轨）
      if (enc.path) {
        publishStage3dArtifact({ path: enc.path, kind: "video", source: "stage3d_pose_video",
          title: `白模动作_${enc.frames}帧_${enc.duration}s`, durationSec: enc.duration });
      }
      onStatus(`✅ 白模动作视频已生成（${enc.frames} 帧 / ${enc.duration}s）— 可点「最近产物 → 时间线」`);
    } finally {
      api.renderer.setRenderTarget(null);
      api.renderer.setSize(prevW, prevH, false);
      composer?.setSize(prevW, prevH);
      api.camera.aspect = savedAspect;
      api.camera.updateProjectionMatrix();
      api.camera.position.copy(savedPos);
      api.controls.target.copy(savedTarget);
      rt.dispose();
      // 恢复 root 基准与角色位置，避免录制把场景留在末帧姿态
      poseDriveBasePosRef.current = savedBase;
      if (actorObj && savedActorPos) actorObj.position.copy(savedActorPos);
      setPoseVideoBusy(false);
      setPoseVideoProgress(0);
    }
  };

  /** 把最近一次导出的 3D 产物送进剪辑时间线 —— 唯一通道见 stage3dArtifacts.ts */
  const sendLastArtifactToTimeline = async () => {
    onStatus(`⏳ 正在送入剪辑时间线：${last3dArtifact?.title || ""}…`);
    const r = await sendLatestArtifactToTimeline();
    onStatus(`${r.ok ? "✅" : "❌"} ${r.message}`);
  };

  /** 停止正在播放的路径 */
  const stopCamPath = () => {
    if (pathRafRef.current !== null) {
      cancelAnimationFrame(pathRafRef.current);
      pathRafRef.current = null;
    }
  };

  /** 开始录制运镜：采样用户手动拖动的相机轨迹 */
  const startCamRecord = () => {
    const api = apiRef.current;
    if (!api) return;
    if (!camRecRef.current) camRecRef.current = new CameraRecorder();
    camRecRef.current.start();
    setCamRecording(true);
    onStatus("⏺ 录制运镜中 — 拖动镜头运镜，再点「停止录制」生成路径点");
  };

  /** 停止录制运镜：抽稀成 pathPoints，写入当前机位（无当前机位则从视角新建） */
  const stopCamRecord = () => {
    const rec = camRecRef.current;
    if (!rec) return;
    const { durationMs, pathPoints } = rec.stop(24);
    setCamRecording(false);
    if (pathPoints.length < 2) {
      onStatus("录制太短，至少需要 2 个路径点");
      return;
    }
    const api = apiRef.current;
    if (activeCamId) {
      setCameras((prev) =>
        prev.map((c) =>
          c.id === activeCamId
            ? { ...c, pathPoints, pathDuration: Math.max(1000, Math.round(durationMs)) }
            : c,
        ),
      );
      onStatus(
        `已录制运镜：${pathPoints.length} 点 · ${(durationMs / 1000).toFixed(1)}s，写入「${activeCam?.name || "当前机位"}」`,
      );
    } else if (api) {
      const p = api.camera.position;
      const t = api.controls.target;
      const cam: StageCamera = {
        id: uid("cam"),
        name: `运镜 ${cameras.length + 1}`,
        position: [p.x, p.y, p.z],
        lookAt: [t.x, t.y, t.z],
        fov,
        pathPoints,
        pathDuration: Math.max(1000, Math.round(durationMs)),
      };
      setCameras((prev) => [...prev, cam]);
      setActiveCamId(cam.id);
      onStatus(`已录制运镜为新机位「${cam.name}」：${pathPoints.length} 点`);
    }
  };

  /** 播放机位路径：循环沿 pathPoints 插值移动当前 view camera */
  const playCamPath = (cam: StageCamera) => {
    if (!cam.pathPoints?.length) {
      onStatus("该机位没有路径，请先生成");
      return;
    }
    const api = apiRef.current;
    if (!api) return;
    stopCamPath();

    const startCam = api.camera.position.clone();
    const startLook = new THREE.Vector3(0, 1.2, 0);
    api.controls.target.copy(startLook);

    const pathPts = [
      { pos: [...cam.position] as [number, number, number], look: [...cam.lookAt] as [number, number, number] },
      ...cam.pathPoints,
    ];
    const totalMs = cam.pathDuration || 3000;
    const loopMs = totalMs * 2;
    const startedAt = performance.now();

    const step = () => {
      const now = performance.now();
      const elapsed = (now - startedAt) % loopMs;
      const forward = elapsed < totalMs;
      const t = forward ? elapsed / totalMs : 1 - (elapsed - totalMs) / totalMs;
      const segT = t * (pathPts.length - 1);
      const i = Math.min(Math.floor(segT), pathPts.length - 2);
      const localT = segT - i;
      const a = pathPts[i];
      const b = pathPts[i + 1];
      api.camera.position.set(
        a.pos[0] + (b.pos[0] - a.pos[0]) * localT,
        a.pos[1] + (b.pos[1] - a.pos[1]) * localT,
        a.pos[2] + (b.pos[2] - a.pos[2]) * localT,
      );
      api.controls.target.set(
        a.look[0] + (b.look[0] - a.look[0]) * localT,
        a.look[1] + (b.look[1] - a.look[1]) * localT,
        a.look[2] + (b.look[2] - a.look[2]) * localT,
      );
      pathRafRef.current = requestAnimationFrame(step);
    };
    pathRafRef.current = requestAnimationFrame(step);
    onStatus(`播放机位路径（${cam.name}）· 循环往返`);
  };

  // ============ E: 姿势关键帧 MVP ============

  /** 把选中 actor 的当前姿势记录为一个关键帧 */
  const recordPoseKeyframe = (actorId: string, t: number) => {
    const actor = actors.find((a) => a.id === actorId);
    if (!actor || actor.kind !== "actor") {
      onStatus("只能给 actor 角色存关键帧");
      return;
    }
    const currentPose = actorPose(actor);
    setPoseTracks((prev) => {
      const list = [...(prev[actorId] || [])];
      // 同时间戳覆盖：保留既有 easing/interpolation/bezier，仅刷新 pose
      const idx = list.findIndex((k) => k.t === t);
      if (idx >= 0) {
        list[idx] = { ...list[idx], pose: currentPose };
      } else {
        list.push({ t, pose: currentPose, easing: "ease_in_out" });
      }
      list.sort((a, b) => a.t - b.t);
      onStatus(`已记录关键帧 t=${t}ms（${actor.name}）`);
      return { ...prev, [actorId]: list };
    });
  };

  const deletePoseKeyframe = (actorId: string, t: number) => {
    setPoseTracks((prev) => {
      const list = (prev[actorId] || []).filter((k) => k.t !== t);
      return { ...prev, [actorId]: list };
    });
  };

  /** 修改关键帧的 easing / interpolation / bezier 控制点 */
  const patchPoseKeyframe = (actorId: string, t: number, patch: Partial<PoseKeyframe>) => {
    setPoseTracks((prev) => {
      const list = (prev[actorId] || []).map((k) => (k.t === t ? { ...k, ...patch } : k));
      return { ...prev, [actorId]: list };
    });
  };

  const stopPoseTimeline = () => {
    if (poseRafRef.current !== null) {
      cancelAnimationFrame(poseRafRef.current);
      poseRafRef.current = null;
    }
    // 恢复所有 actor 到存储状态
    setActors((prev) => [...prev]);
  };

  /** 循环播放选中 actor 的姿势时间轴 */
  const playPoseTimeline = (actorId: string) => {
    const track = poseTracks[actorId];
    if (!track || track.length < 2) {
      onStatus("至少需要 2 个关键帧才能播放");
      return;
    }
    const api = apiRef.current;
    if (!api) return;
    stopPoseTimeline();

    const actorObj = api.objects.get(actorId);
    if (!actorObj) return;

    const minT = track[0].t;
    const maxT = track[track.length - 1].t;
    const range = Math.max(1, maxT - minT);
    const startedAt = performance.now();

    const step = () => {
      const elapsed = performance.now() - startedAt;
      const nowMs = minT + ((elapsed % (range * 2)) < range ? elapsed % (range * 2) : range * 2 - (elapsed % (range * 2)));
      const pose = sampleKeyframes(track, nowMs);
      applyPoseResolved(actorObj, pose);
      poseRafRef.current = requestAnimationFrame(step);
    };
    poseRafRef.current = requestAnimationFrame(step);
    onStatus(`播放姿势时间轴（共 ${track.length} 帧）· 循环往返`);
  };

  const patchSelected = (patch: Partial<StageActor>) => {
    if (!selectedId) return;
    pushUndo();
    setActors((prev) => prev.map((a) => (a.id === selectedId ? { ...a, ...patch } : a)));
  };

  // ─── MotionPreset 控制 ────────────────────────────────────────────
  const toggleActorMotion = (actorId: string, motionId: string) => {
    const preset = MOTION_PRESETS.find((m) => m.id === motionId);
    if (!preset) return;
    const current = activeMotionsRef.current.get(actorId) ?? [];
    const idx = current.findIndex((m) => m.id === motionId);
    const next =
      idx >= 0 ? current.filter((m) => m.id !== motionId) : [...current, preset];
    if (next.length > 0) {
      activeMotionsRef.current.set(actorId, next);
      if (!motionStartRef.current.has(actorId)) {
        motionStartRef.current.set(actorId, performance.now());
        // 首次启用 motion 时保存 actor 当前 position 作为 base
        const obj = apiRef.current?.objects.get(actorId);
        if (obj && !motionBasePosRef.current.has(actorId)) {
          motionBasePosRef.current.set(actorId, [obj.position.x, obj.position.y, obj.position.z]);
        }
      }
    } else {
      activeMotionsRef.current.delete(actorId);
      motionStartRef.current.delete(actorId);
      const obj = apiRef.current?.objects.get(actorId);
      const actor = actorsRef.current.find((a) => a.id === actorId);
      if (obj && actor) applyPose(obj, actorPose(actor));
      // 恢复 actor 原始位置
      const base = motionBasePosRef.current.get(actorId);
      if (base) {
        obj.position.set(base[0], base[1], base[2]);
        motionBasePosRef.current.delete(actorId);
      }
    }
    forceTick((n) => n + 1);
  };

  const isMotionActive = (actorId: string, motionId: string): boolean => {
    const list = activeMotionsRef.current.get(actorId);
    return Boolean(list?.some((m) => m.id === motionId));
  };

  const applyCamPreset = (preset: (typeof CAM_PRESETS)[number]) => {
    const cam: StageCamera = {
      id: uid("cam"),
      name: preset.label,
      position: preset.pos,
      lookAt: preset.look,
      fov: preset.fov,
      shotSize: preset.shotSize,
    };
    setCameras((prev) => [...prev, cam]);
    setActiveCamId(cam.id);
    setFov(preset.fov);
    setViewMode("camera");
    onStatus(`已添加机位：${preset.label}`);
  };

  const addPresetActor = (preset: (typeof ACTOR_PRESETS)[number]) => {
    pushUndo();
    const a: StageActor = {
      id: uid("actor"),
      name: preset.label,
      kind: "actor",
      color: preset.color,
      position: [actors.length * 0.9 - 1, 0, 0],
      rotationY: 0,
      scale: preset.scale,
      pose: defaultPose(),
      variant: preset.variant,
      hairStyle: preset.hairStyle,
    };
    setActors((prev) => [...prev, a]);
    setSelectedId(a.id);
    setSceneMode("group");
    onStatus(`已添加角色：${preset.label} · ${HUMAN_PRESETS[preset.variant].label}`);
  };

  const onImportConfirm = (result: StageImportResult) => {
    setRefImage(result.dataUrl);
    if (result.mode === "overwrite") {
      pushUndo();
      setActors(defaultActors());
      setCameras(defaultCameras());
      onStatus("已覆盖导演台场景，并挂上站位参考图");
    } else {
      onStatus("已插入站位参考层（不覆盖现有角色/机位）");
    }
    setRailTab("image");
  };

  const stageCommands: CommandItem[] = useMemo(
    () => [
      { id: "move", label: "移动工具", shortcut: "V", run: () => setTool("move") },
      { id: "rotate", label: "旋转工具", shortcut: "R", run: () => setTool("rotate") },
      { id: "scale", label: "缩放工具", shortcut: "S", run: () => setTool("scale") },
      { id: "joint", label: "切换关节 / 移整人", shortcut: "J", keywords: "pose ik", run: () => setEditMode((m) => (m === "joint" ? "actor" : "joint")) },
      { id: "add-actor", label: "添加素模角色", shortcut: "N", run: () => addActor("actor") },
      { id: "dup", label: "复制选中", shortcut: "D", run: () => duplicateSelectedActor() },
      { id: "capture", label: "当前视角截图入画布", shortcut: "C", keywords: "capture 截图", run: () => capture() },
      { id: "cam-view", label: "切换导演视图 / 点位视角", shortcut: "Tab", run: () => setViewMode((v) => (v === "director" ? "camera" : "director")) },
      { id: "fit", label: "适配入画（全身可见）", shortcut: "F", run: () => { apiRef.current?.fitDirectorFraming(); onStatus("已适配相机入画"); } },
      { id: "face", label: "角色正面朝向镜头", keywords: "face 正面", run: () => faceSelectedToCamera() },
      { id: "flip", label: "角色转身 180°", run: () => flipSelectedFront() },
      { id: "undo", label: "撤销变换", shortcut: "Ctrl+Z", run: () => {
        if (undoRef.current) { setActors(undoRef.current); undoRef.current = null; onStatus("已撤销最近一次变换"); }
      } },
      ...POSE_PRESETS.slice(0, 9).map((p, i) => ({
        id: `pose-${p.id}`,
        label: `姿势：${p.label}`,
        shortcut: String(i + 1),
        keywords: `pose ${p.id} ${p.label}`,
        run: () => setPosePreset(p.id),
      })),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [actors, selectedId],
  );

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && (ev.key.toLowerCase() === "k" || ev.key.toLowerCase() === "p") && !ev.shiftKey) {
        ev.preventDefault();
        setCmdOpen(true);
        return;
      }
      if (cmdOpen) return;
      if (isTypingTarget(ev.target)) return;
      if (ev.key === "/" || ev.key === "?") {
        ev.preventDefault();
        setCmdOpen(true);
        return;
      }
      if (mod) return;
      const k = ev.key.toLowerCase();
      if (k === "n") {
        ev.preventDefault();
        addActor("actor");
      } else if (k === "d") {
        ev.preventDefault();
        duplicateSelectedActor();
      } else if (k === "c") {
        ev.preventDefault();
        capture();
      } else if (k === "f") {
        ev.preventDefault();
        apiRef.current?.fitDirectorFraming();
        onStatus("已适配相机入画");
      } else if (k === "tab") {
        ev.preventDefault();
        setViewMode((v) => (v === "director" ? "camera" : "director"));
      } else if (/^[1-9]$/.test(ev.key)) {
        const p = POSE_PRESETS[Number(ev.key) - 1];
        if (p) setPosePreset(p.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cmdOpen, actors, selectedId]);

  return (
    <div className="stage3d libtv-stage">
      <div className="stage3d-viewport" ref={mountRef}>
        {marquee ? (
          <div
            className="stage3d-marquee"
            style={{
              left: Math.min(marquee.x0, marquee.x1),
              top: Math.min(marquee.y0, marquee.y1),
              width: Math.abs(marquee.x1 - marquee.x0),
              height: Math.abs(marquee.y1 - marquee.y0),
            }}
          />
        ) : null}
      </div>
      <div className="stage3d-drag-hint">
        {editMode === "joint"
          ? selectedBoneKey
            ? `已选「${BONE_CN[selectedBoneKey] || selectedBoneKey}」· ${
                limbDragMode(selectedBoneKey) === "segmentFk"
                  ? "单关节拖（大腿/小腿/肘）"
                  : limbDragMode(selectedBoneKey) === "chainIk"
                    ? "整肢拖（手/脚）"
                    : "拖动调节"
              } · 空白处转视角`
            : "手/脚=整肢 · 大腿小腿上臂前臂=单关节 · 空白处转视角"
          : "移整人模式 · 拖模型平移 · J 回到拉肢调关节"}
      </div>
      <div className="stage3d-frame" data-aspect={aspect} />
      {refImage ? (
        <div className="stage3d-ref-layer" title="站位参考层">
          <img src={refImage} alt="ref" />
        </div>
      ) : null}
      <div
        className="stage3d-fps"
        title="实时帧率（每秒刷新）"
        style={{
          position: "absolute",
          right: 8,
          bottom: 8,
          padding: "2px 8px",
          fontSize: 11,
          fontFamily: "monospace",
          color: fps >= 50 ? "#4ade80" : fps >= 30 ? "#fbbf24" : "#f87171",
          background: "rgba(0,0,0,0.55)",
          borderRadius: 4,
          pointerEvents: "none",
          userSelect: "none",
          zIndex: 5,
        }}
      >
        {fps} FPS
      </div>

      <CommandPalette
        open={cmdOpen}
        title="3D 导演台指令"
        items={stageCommands}
        onClose={() => setCmdOpen(false)}
      />
      <div className="stage3d-top-seg">
        <button
          type="button"
          className={viewMode === "director" ? "on" : ""}
          onClick={() => setViewMode("director")}
        >
          导演视图
        </button>
        <button
          type="button"
          className={viewMode === "camera" ? "on" : ""}
          onClick={() => setViewMode("camera")}
        >
          点位视角
        </button>
      </div>

      <nav className="stage3d-icon-rail" aria-label="导演台导航">
        <button type="button" className={railTab === "frame" ? "on" : ""} title="画幅" onClick={() => setRailTab("frame")}>▦</button>
        <button type="button" className={railTab === "actor" ? "on" : ""} title="角色" onClick={() => setRailTab("actor")}>☺</button>
        <button type="button" className={railTab === "camera" ? "on" : ""} title="机位" onClick={() => setRailTab("camera")}>📹</button>
        <button type="button" className={railTab === "shot" ? "on" : ""} title="工具" onClick={() => setRailTab("shot")}>🎬</button>
        <button type="button" className={railTab === "image" ? "on" : ""} title="识图" onClick={() => { setRailTab("image"); setImportOpen(true); }}>🖼</button>
        <div className="spacer" />
        <button type="button" title="指令与快捷键 Ctrl+K" onClick={() => setCmdOpen(true)}>?</button>
      </nav>

      <aside className="stage3d-panel">
        <div className="stage3d-title">3D 导演台</div>
        {railTab === "frame" ? (
          <>
            <div className="section-title">选择画幅比例</div>
            <div className="stage3d-aspect-grid">
              {ASPECTS.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={`stage3d-aspect${aspect === a.id ? " on" : ""}`}
                  onClick={() => setAspect(a.id)}
                >
                  <span className={`aspect-box ratio-${a.id.replace(":", "-")}`} />
                  {a.label}
                </button>
              ))}
            </div>
            <div className="section-title">光照预设</div>
            <div className="seg">
              {(Object.keys(LIGHT_PRESETS) as LightPreset[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={lightPreset === k ? "on" : ""}
                  onClick={() => setLightPreset(k)}
                >
                  {LIGHT_PRESETS[k].label}
                </button>
              ))}
            </div>
            <div className="section-title">地面</div>
            <div className="seg">
              <button type="button" className={groundPreset === "studio-dark" ? "on" : ""} onClick={() => setGroundPreset("studio-dark")}>默认黑</button>
              <button type="button" className={groundPreset === "concrete" ? "on" : ""} onClick={() => setGroundPreset("concrete")}>水泥</button>
              <button type="button" className={groundPreset === "wood" ? "on" : ""} onClick={() => setGroundPreset("wood")}>木地板</button>
              <button type="button" className={groundPreset === "grass" ? "on" : ""} onClick={() => setGroundPreset("grass")}>草地</button>
            </div>
            <div className="section-title">全景图环境（720° equirectangular）</div>
            <p className="muted tiny">上传 360° 全景图作为背景 + IBL 光照 · 支持 .jpg / .png · 建议 2:1 比例</p>
            <div className="seg">
              <label className="btn" style={{ cursor: "pointer" }}>
                上传全景图
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = () => {
                      setEnvEquirect(reader.result as string);
                      onStatus("全景图已加载（关闭光照/雾，启用 IBL）");
                    };
                    reader.onerror = () => onStatus("读取全景图失败");
                    reader.readAsDataURL(file);
                    e.target.value = "";
                  }}
                />
              </label>
              <button
                type="button"
                className="btn"
                disabled={!envEquirect}
                onClick={() => {
                  setEnvEquirect(null);
                  onStatus("已清除全景图环境，恢复纯色背景");
                }}
              >
                清除
              </button>
              {envEquirect ? <span className="muted tiny">✓ 已加载</span> : null}
            </div>
            <div className="section-title">后处理 · 辉光 Bloom</div>
            <p className="muted tiny">强度 0 = 关闭 · 推荐 0.3~0.8 · 过强会导致高光边缘融化</p>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={bloomStrength}
                onChange={(e) => setBloomStrength(parseFloat(e.target.value))}
                style={{ flex: 1 }}
              />
              <span className="muted tiny" style={{ minWidth: 36, textAlign: "right" }}>
                {bloomStrength.toFixed(2)}
              </span>
              <button
                type="button"
                className="btn"
                style={{ padding: "2px 8px", fontSize: 11 }}
                onClick={() => setBloomStrength(0)}
              >
                关
              </button>
            </div>
          </>
        ) : null}

        {railTab === "actor" ? (
          <>
            <div className="section-title">场景规模</div>
            <div className="seg">
              <button
                type="button"
                className={sceneMode === "solo" ? "on" : ""}
                onClick={() => switchSceneMode("solo")}
              >
                单人
              </button>
              <button
                type="button"
                className={sceneMode === "group" ? "on" : ""}
                onClick={() => switchSceneMode("group")}
              >
                群像
              </button>
            </div>

            {/* 缺口①：直接从角色库投人偶进来（体型/发型/配色由角色字段决定，不随机） */}
            <Stage3dCastPanel visible={railTab === "actor"} />

            {sceneMode === "group" ? (
              <>
                <div className="section-title">群像模板（生成多人）</div>
                <div className="stage3d-chips">
                  {GROUP_TEMPLATES.map((t) => (
                    <button key={t.id} type="button" className="chip" onClick={() => applyGroupTemplate(t)}>
                      {t.label}
                    </button>
                  ))}
                </div>
                <div className="section-title">重排现有人模</div>
                <div className="stage3d-chips">
                  {FORMATIONS.map((f) => (
                    <button key={f.id} type="button" className="chip" onClick={() => applyFormation(f.id)}>
                      {f.label}
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <p className="muted tiny">单人摆姿势。切「群像」可一键布置 2–5 人；黄箭头与五官是正面。</p>
            )}

            <div className="section-title">场景元素 · 点选单个模型</div>
            <div className="stage3d-list">
              {actors.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  className={`stage3d-item${a.id === selectedId ? " on" : ""}`}
                  onClick={() => {
                    setSelectedId(a.id);
                    onStatus(
                      a.kind === "actor"
                        ? `已选 ${a.name} · 拉肢体带动整条链，旋转环可微调`
                        : `已选 ${a.name} · 几何体仅可整体移动/旋转`,
                    );
                  }}
                >
                  <span className="dot" style={{ background: a.color }} />
                  {a.name}
                  {a.kind === "actor" ? " · 人模" : ""}
                </button>
              ))}
            </div>

            {selected?.kind === "actor" ? (
              <div className="stage3d-pose-block">
                <div className="section-title">角色 · {selected.name}</div>
                {/* —— 四子标签页（图片：属性/姿势/动作/路线）—— */}
                <div className="stage3d-subtabs">
                  <button type="button" className={actorTab === "attr" ? "on" : ""} onClick={() => setActorTab("attr")}>属性</button>
                  <button type="button" className={actorTab === "pose" ? "on" : ""} onClick={() => setActorTab("pose")}>姿势</button>
                  <button type="button" className={actorTab === "motion" ? "on" : ""} onClick={() => setActorTab("motion")}>动作</button>
                  <button type="button" className={actorTab === "route" ? "on" : ""} onClick={() => setActorTab("route")}>路线</button>
                </div>

                {actorTab === "attr" ? (
                  <>
                    <div className="section-title">正反面</div>
                    <p className="muted tiny">眼睛/胸口白块/脚前黄箭头 = 正面。</p>
                    <div className="seg">
                      <button type="button" onClick={faceSelectedToCamera}>正面朝向镜头</button>
                      <button type="button" onClick={flipSelectedFront}>转身 180°</button>
                    </div>
                    <div className="field">
                      <label>体型</label>
                      <select
                        value={selected.variant || "male_std"}
                        onChange={(e) => patchSelected({ variant: e.target.value as HumanVariant })}
                        style={{ width: "100%" }}
                      >
                        {Object.values(HUMAN_PRESETS).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label>发型</label>
                      <select
                        value={selected.hairStyle || "none"}
                        onChange={(e) => patchSelected({ hairStyle: e.target.value as HairStyle })}
                        style={{ width: "100%" }}
                      >
                        <option value="none">光头 / 无</option>
                        <option value="short">短发</option>
                        <option value="long">长发（后披+刘海）</option>
                        <option value="round">圆头（儿童）</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>朝向 Y</label>
                      <input
                        type="range"
                        min={-Math.PI}
                        max={Math.PI}
                        step={0.01}
                        value={selected.rotationY}
                        onChange={(e) => patchSelected({ rotationY: Number(e.target.value) })}
                      />
                    </div>
                    <div className="field">
                      <label>体色</label>
                      <input
                        type="color"
                        value={selected.color}
                        onChange={(e) => patchSelected({ color: e.target.value })}
                      />
                    </div>
                  </>
                ) : null}

                {actorTab === "pose" ? (
                  <>
                    <div className="seg">
                      <button
                        type="button"
                        className={editMode === "joint" ? "on" : ""}
                        onClick={() => {
                          setEditMode("joint");
                          onStatus("手/脚整肢 · 大腿小腿肘肩单关节 · Alt 移动整人");
                        }}
                      >
                        拉肢摆姿势
                      </button>
                      <button
                        type="button"
                        className={editMode === "actor" ? "on" : ""}
                        onClick={() => {
                          setEditMode("actor");
                          const api = apiRef.current;
                          if (api) {
                            api.transform.enabled = false;
                            api.transform.detach();
                          }
                          setSelectedBoneKey(null);
                          onStatus("移整人：拖模型平移 · V/R/S 旋转缩放");
                        }}
                      >
                        移整人
                      </button>
                    </div>
                    <div className="section-title">姿势预设</div>
                    <div className="stage3d-pose-grid">
                      {POSE_PRESETS.map((p) => (
                        <button key={p.id} type="button" className="stage3d-pose-btn" onClick={() => setPosePreset(p.id)}>
                          {p.label}
                        </button>
                      ))}
                    </div>
                    <div className="section-title">姿势调节</div>
                    <div className="stage3d-joints">
                      {JOINT_LABELS.map((j) => {
                        const pose = actorPose(selected);
                        return (
                          <div className="field compact stage3d-joint-row" key={j.key}>
                            <label>{j.label}</label>
                            <input
                              type="range"
                              min={j.min}
                              max={j.max}
                              step={1}
                              value={pose[j.key]}
                              onChange={(e) => patchPose({ [j.key]: Number(e.target.value) })}
                            />
                            <input
                              type="number"
                              className="stage3d-joint-num"
                              min={j.min}
                              max={j.max}
                              value={Math.round(pose[j.key])}
                              onChange={(e) => patchPose({ [j.key]: Math.max(j.min, Math.min(j.max, Number(e.target.value) || 0)) })}
                            />
                          </div>
                        );
                      })}
                    </div>
                  </>
                ) : null}

                {actorTab === "motion" ? (
                  <>
                    <div className="section-title">动作预设</div>
                    <p className="muted tiny">多选叠加 · tick 内驱动骨骼 · 拖拽关节时自动暂停</p>
                    <div className="stage3d-chips">
                      <button
                        type="button"
                        className="chip"
                        onClick={() => {
                          MOTION_PRESETS.forEach((m) => {
                            if (isMotionActive(selected.id, m.id)) toggleActorMotion(selected.id, m.id);
                          });
                        }}
                      >
                        无动作
                      </button>
                      {MOTION_PRESETS.map((m) => {
                        const on = isMotionActive(selected.id, m.id);
                        return (
                          <button
                            key={m.id}
                            type="button"
                            className={`chip${on ? " on" : ""}`}
                            onClick={() => toggleActorMotion(selected.id, m.id)}
                            title={`${m.label} · ${(m.duration / 1000).toFixed(2)} 秒`}
                          >
                            {m.label}
                            <span className="stage3d-chip-dur">{(m.duration / 1000).toFixed(2)} 秒</span>
                          </button>
                        );
                      })}
                    </div>
                    <div className="section-title">我的动作</div>
                    <div className="stage3d-route-row">
                      <p className="muted tiny" style={{ flex: 1, margin: 0 }}>支持 FBX / GLB</p>
                      <button type="button" className="btn" onClick={() => motionFileRef.current?.click()}>
                        ⬆ 导入动作
                      </button>
                    </div>
                    <input
                      ref={motionFileRef}
                      type="file"
                      accept=".fbx,.glb,.gltf"
                      hidden
                      onChange={(e) => void onImportMotion(e.target.files?.[0] || null)}
                    />
                    <div className="section-title">参考视频驱动（模式 A）</div>
                    <p className="muted tiny">
                      整段动作参考视频直接作 motion-ref 条件送模型；当前模型池未接入支持的模型时会诚实提示
                    </p>
                    <div className="stage3d-route-row">
                      {motionRefVideo ? (
                        <>
                          <p className="muted tiny" style={{ flex: 1, margin: 0 }} title={motionRefVideo.url}>
                            🎞 {motionRefVideo.name}
                          </p>
                          <button
                            type="button"
                            className="btn danger"
                            onClick={() => {
                              setMotionRefVideo(null);
                              onStatus("已移除参考视频");
                            }}
                            title="移除参考视频"
                          >
                            🗑
                          </button>
                        </>
                      ) : (
                        <>
                          <p className="muted tiny" style={{ flex: 1, margin: 0 }}>尚未挂载参考视频</p>
                          <button type="button" className="btn" onClick={() => motionRefFileRef.current?.click()}>
                            ⬆ 上传参考视频
                          </button>
                        </>
                      )}
                    </div>
                    <input
                      ref={motionRefFileRef}
                      type="file"
                      accept="video/*"
                      hidden
                      onChange={(e) => {
                        const f = e.target.files?.[0] || null;
                        e.target.value = "";
                        void onMotionRefVideoPick(f);
                      }}
                    />
                    <div className="section-title">姿态解析（模式 B）</div>
                    <p className="muted tiny">
                      参考视频 → 子进程 BlazePose 关键点 JSON（推理完释放显存）；后续可在时间轴编辑、驱动白模、换机位
                    </p>
                    <div className="stage3d-route-row">
                      <button
                        type="button"
                        className="btn primary"
                        onClick={() => void onPoseExtract()}
                        disabled={!motionRefVideo || poseBusy}
                        title={motionRefVideo ? "解析参考视频的骨骼关键点" : "请先挂载参考视频"}
                      >
                        {poseBusy ? "⏳ 解析中…" : "🦴 解析姿态"}
                      </button>
                      {motionPoseData ? (
                        <p className="muted tiny" style={{ flex: 1, margin: 0 }} title={motionPoseData.url}>
                          ✓ {motionPoseData.frames} 帧 / {motionPoseData.duration}s · 关键点已就绪
                        </p>
                      ) : (
                        <p className="muted tiny" style={{ flex: 1, margin: 0 }}>未解析</p>
                      )}
                    </div>
                    {/* 第四刀：录制白模动作视频 → 合成 mp4 → 挂为 reference_video 走第一刀通道 */}
                    <div className="stage3d-route-row">
                      <button
                        type="button"
                        className="btn primary"
                        onClick={() => void recordPoseVideo()}
                        disabled={!motionPoseData || poseVideoBusy}
                        title={
                          motionPoseData
                            ? "逐帧渲染白模动作并合成为视频，挂为动作参考"
                            : "请先解析姿态并加载关键点轨迹"
                        }
                      >
                        {poseVideoBusy ? `⏺ 录制中 ${poseVideoProgress}` : "🎞 录制白模动作"}
                      </button>
                      <p className="muted tiny" style={{ flex: 1, margin: 0 }}>
                        {poseVideoBusy
                          ? `已采集 ${poseVideoProgress} 帧…`
                          : "生成 motion-ref 视频（无需实时录制，不掉帧）"}
                      </p>
                    </div>
                  </>
                ) : null}

                {actorTab === "route" ? (
                  <>
                    <div className="section-title">人物路线</div>
                    <p className="muted tiny">添加第一个路线点后，角色沿路线循环移动</p>
                    <div className="stage3d-route-row">
                      <button type="button" className="btn primary" onClick={addRoutePoint}>
                        ⊕ 添加点
                      </button>
                      <button type="button" className="btn" onClick={toggleRoutePlay} title="播放/暂停路线">
                        {selected.route?.playing ? "⏸" : "▶"}
                      </button>
                      <button type="button" className="btn danger" onClick={clearRoute} title="清空路线">
                        🗑
                      </button>
                    </div>
                    <div className="field">
                      <label>形状</label>
                      <div className="seg">
                        <button type="button" className={routeShape === "smooth" ? "on" : ""} onClick={() => setRouteShape("smooth")}>
                          平滑
                        </button>
                        <button type="button" className={routeShape === "polyline" ? "on" : ""} onClick={() => setRouteShape("polyline")}>
                          折线
                        </button>
                      </div>
                    </div>
                    <div className="field">
                      <label>速度</label>
                      <div className="seg">
                        <button type="button" className={routeSpeed === "uniform" ? "on" : ""} onClick={() => setRouteSpeed("uniform")}>
                          匀速
                        </button>
                        <button type="button" className={routeSpeed === "soft" ? "on" : ""} onClick={() => setRouteSpeed("soft")}>
                          柔和
                        </button>
                        <button type="button" className={routeSpeed === "custom" ? "on" : ""} onClick={() => setRouteSpeed("custom")}>
                          自定义
                        </button>
                      </div>
                    </div>
                    {selected.route?.points?.length ? (
                      <p className="muted tiny">已添加 {selected.route.points.length} 个路线点</p>
                    ) : null}
                  </>
                ) : null}
                <div className="section-title">姿势关键帧</div>
                <PoseTimeline
                  track={poseTracks[selected.id] || []}
                  onRecord={(t) => recordPoseKeyframe(selected.id, t)}
                  onDelete={(t) => deletePoseKeyframe(selected.id, t)}
                  onPatch={(t, patch) => patchPoseKeyframe(selected.id, t, patch)}
                  onPlay={() => playPoseTimeline(selected.id)}
                  onStop={stopPoseTimeline}
                />
              </div>
            ) : selected ? (
              <p className="muted tiny">「{selected.name}」是几何体，不能调关节。请点选人模，或下方添加 Dummy。</p>
            ) : (
              <p className="muted tiny">点击视口素模或上方列表选中单个模型，再调姿势。</p>
            )}

            <details className="stage3d-add-block">
              <summary>添加 / 重置角色</summary>
              <button
                type="button"
                className="btn primary"
                onClick={() => {
                  pushUndo();
                  const solo = defaultActors();
                  setActors(solo);
                  setSelectedId(solo[0]?.id ?? null);
                  setCameras(defaultCameras());
                  setViewMode("director");
                  setEditMode("joint");
                  setSceneMode("solo");
                  framedOnceRef.current = false;
                  requestAnimationFrame(() => apiRef.current?.fitDirectorFraming());
                  onStatus("已重置为单人素模 · 点住肢体拖动调节");
                }}
              >
                重置单人场景
              </button>
              {ACTOR_PRESETS.map((p) => (
                <button key={p.id} type="button" className="stage3d-list-btn" onClick={() => addPresetActor(p)}>
                  <span className="dot" style={{ background: p.color }} /> {p.label}
                </button>
              ))}
              <button type="button" className="stage3d-list-btn" onClick={() => addActor("box")}>▦ 几何模型</button>
            </details>
          </>
        ) : null}

        {railTab === "camera" ? (
          <>
            <div className="section-title">添加机位</div>
            <button type="button" className="stage3d-list-btn on" onClick={addCameraFromView}>
              📷 当前视角
            </button>
            <div className="stage3d-aspect-grid">
              {CAM_PRESETS.map((p) => (
                <button key={p.id} type="button" className="stage3d-aspect" onClick={() => applyCamPreset(p)}>
                  📷
                  <span>{p.label}</span>
                </button>
              ))}
            </div>
            <div className="section-title">已存机位</div>
            <div className="stage3d-list">
              {cameras.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`stage3d-item${c.id === activeCamId ? " on" : ""}`}
                  onClick={() => {
                    setActiveCamId(c.id);
                    setFov(c.fov);
                    setViewMode("camera");
                  }}
                >
                  📷 {c.name} · {c.fov}°
                </button>
              ))}
            </div>
            <div className="field">
              <label>FOV {fov}°</label>
              <input
                type="range"
                min={18}
                max={90}
                value={fov}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setFov(v);
                  if (activeCamId) {
                    setCameras((prev) =>
                      prev.map((c) => (c.id === activeCamId ? { ...c, fov: v } : c)),
                    );
                  }
                }}
              />
            </div>
            {/* —— 一键镜头（图片：8 运镜 + 跟踪主体 + 轨迹范围 + 掌镜）—— */}
            <div className="section-title">一键镜头</div>
            <p className="muted tiny">选择主体和幅度，再套用镜头</p>
            <div className="field">
              <label>跟踪主体</label>
              <select
                value={trackTargetId}
                onChange={(e) => setTrackTargetId(e.target.value)}
                style={{ width: "100%" }}
              >
                <option value="">— 不跟踪（用当前 lookAt）—</option>
                {actors.filter((a) => a.kind === "actor").map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>轨迹范围 {moveRange}%</label>
              <input
                type="range"
                min={10}
                max={100}
                step={5}
                value={moveRange}
                onChange={(e) => setMoveRange(Number(e.target.value))}
              />
            </div>
            <div className="stage3d-cammove-grid">
              {CAM_MOVES.map((m) => (
                <button key={m.id} type="button" className="stage3d-cammove" onClick={() => applyCameraMove(m.id)}>
                  {m.label}
                </button>
              ))}
            </div>
            <div className="section-title">制作镜头</div>
            <button type="button" className={`btn${wasdActive ? " primary" : ""}`} onClick={toggleWasd}>
              🎯 {wasdActive ? "退出掌镜" : "开始掌镜"}（WASD 走镜头）
            </button>
            <button className="btn primary" onClick={() => capture()}>当前视角 → 画布</button>
            <button className="btn teal" onClick={() => capture(activeCam)} disabled={!activeCam}>当前机位 → 镜头</button>
            <button className="btn" onClick={captureAllCams}>全部机位截图</button>
            <button className="btn" onClick={controlNetExport} title="导出 Depth / Normal / OpenPose 三通道 PNG 供 ComfyUI ControlNet 工作流">🎞 ControlNet 导出</button>
            <button className="btn" onClick={bvhExportSelected} title="导出标准 BVH 动画文件（Blender/Mixamo 兼容）— 选中角色优先，否则取第一个有动作的角色">💃 BVH 动画导出</button>
            <button
              className="btn"
              onClick={exportFirstLastFrames}
              disabled={!activeCam?.pathPoints?.length}
              title="需要当前机位有路径点"
            >
              🎬 首尾帧 → 视频
            </button>
            <button
              className="btn teal"
              onClick={exportAllCamerasBatch}
              disabled={!cameras.some((c) => c.pathPoints?.length)}
              title="遍历所有有路径的机位，批量导出首尾帧 → 分镜 → 成片"
            >
              🎬 批量分镜 → 成片
            </button>
            <button
              className="btn"
              onClick={() => selectedId && captureActorViews(selectedId)}
              disabled={!selectedId || !actors.find((a) => a.id === selectedId && a.kind === "actor")}
              title="选中角色时可用"
            >
              🎭 导出三视图（前·侧·背）
            </button>
            <button
              className="btn teal"
              onClick={() => void sendLastArtifactToTimeline()}
              disabled={!last3dArtifact}
              title="把最近一次导出的产物（白模动作视频/首尾帧/分镜/三视图/ControlNet）送入剪辑时间线"
            >
              ➡ 最近产物 → 时间线
            </button>
            <div className="section-title">镜头路径</div>
            <p className="muted tiny">选两个机位（先选起点再点"→"），生成插值路径后可循环预览</p>
            <div className="seg">
              <button type="button" className={pathFromId ? "on" : ""} onClick={() => { setPathFromId(activeCamId); onStatus(pathFromId ? `已选起点，再选终点机位 → 点"生成路径"` : "已选起点机位，去点另一个目标机位"); }}>
                {pathFromId ? `起点: ${cameras.find((c) => c.id === pathFromId)?.name || ""}` : "选起点 →"}
              </button>
              {pathFromId && activeCamId && pathFromId !== activeCamId && (
                <button type="button" className="on" onClick={() => { generateCamPath(pathFromId!, activeCamId!); setPathFromId(null); }}>
                  生成 → 「{cameras.find((c) => c.id === activeCamId)?.name}」
                </button>
              )}
            </div>
            <button
              type="button"
              className="btn primary"
              onClick={() => activeCam && playCamPath(activeCam)}
              disabled={!activeCam || !activeCam.pathPoints}
            >
              ▶ 播放当前机位路径
            </button>
            <button type="button" className="btn" onClick={stopCamPath}>■ 停止路径</button>
            <div className="section-title">录制运镜</div>
            <p className="muted tiny">点「录制」后拖动镜头运镜，再点「停止」生成路径点（写入当前机位）</p>
            <button
              type="button"
              className={`btn${camRecording ? " danger" : " teal"}`}
              onClick={camRecording ? stopCamRecord : startCamRecord}
            >
              {camRecording ? "⏹ 停止录制" : "⏺ 录制运镜"}
            </button>
          </>
        ) : null}

        {railTab === "shot" ? (
          <>
            <div className="section-title">变换工具</div>
            <div className="seg">
              <button type="button" className={tool === "move" ? "on" : ""} onClick={() => setTool("move")}>V 移动</button>
              <button type="button" className={tool === "rotate" ? "on" : ""} onClick={() => setTool("rotate")}>R 旋转</button>
              <button type="button" className={tool === "scale" ? "on" : ""} onClick={() => setTool("scale")}>S 缩放</button>
            </div>
            <div className="section-title">操作模式</div>
            <div className="seg">
              <button type="button" className={editMode === "joint" ? "on" : ""} onClick={() => {
                setEditMode("joint");
                onStatus("手/脚整肢 · 大腿小腿肘肩单关节");
              }}>拉肢摆姿势</button>
              <button type="button" className={editMode === "actor" ? "on" : ""} onClick={() => {
                setEditMode("actor");
                const api = apiRef.current;
                if (api) { api.transform.enabled = false; api.transform.detach(); }
                setSelectedBoneKey(null);
              }}>移整人</button>
            </div>
            <label className="stage3d-check">
              <input type="checkbox" checked={snapOn} onChange={(e) => setSnapOn(e.target.checked)} />
              网格吸附 ({GRID}m)
            </label>
            <button type="button" className="btn" onClick={() => {
              if (undoRef.current) {
                setActors(undoRef.current);
                undoRef.current = null;
                onStatus("已撤销最近一次变换");
              } else onStatus("没有可撤销的变换");
            }}>撤销 (Ctrl+Z)</button>
            <button type="button" className="btn" onClick={() => addActor("box")}>+ 立方体</button>
            <button type="button" className="btn" onClick={() => addActor("cylinder")}>+ 柱体</button>
            <button type="button" className="btn" onClick={() => addActor("sphere")}>+ 球体</button>
            <button type="button" className="btn" onClick={() => addActor("half-dome")}>+ 半球</button>
            <button type="button" className="btn" onClick={() => addActor("chair")}>+ 椅子</button>
            <button type="button" className="btn" onClick={() => addActor("table")}>+ 桌子</button>
          </>
        ) : null}

        {railTab === "image" ? (
          <>
            <div className="section-title">AI 识图</div>
            <button type="button" className="btn primary" onClick={() => setImportOpen(true)}>打开识图导入</button>
            {refImage ? (
              <div className="stage3d-ref-preview">
                <img src={refImage} alt="ref" />
                <button type="button" className="btn" onClick={() => setRefImage(null)}>清除参考层</button>
              </div>
            ) : (
              <p className="muted tiny">上传参考图作为站位层；当前无云端识图，仅本地参考。</p>
            )}
          </>
        ) : null}
      </aside>

      <div className="stage3d-bottom-bar">
        <div className="stage3d-bottom-tools">
          <button type="button" className={tool === "move" ? "on" : ""} onClick={() => setTool("move")} title="选择">↖</button>
          <button type="button" onClick={() => capture()} title="截图入画布">📷</button>
          <button type="button" onClick={() => setImportOpen(true)} title="识图">✧</button>
        </div>
        <div className="stage3d-prompt">
          <button type="button" className="plus" onClick={() => setImportOpen(true)}>+</button>
          <input
            value={scenePrompt}
            onChange={(e) => setScenePrompt(e.target.value)}
            placeholder="描述想搭建的场景"
            onKeyDown={(e) => {
              if (e.key === "Enter" && scenePrompt.trim()) {
                onStatus(`场景描述已记录：${scenePrompt.trim()}（后续可接生成）`);
              }
            }}
          />
          <button
            type="button"
            className="send"
            onClick={() => {
              if (!scenePrompt.trim()) {
                onStatus("请先填写场景描述");
                return;
              }
              onStatus(`场景描述已记录：${scenePrompt.trim()}（后续可接生成）`);
            }}
          >
            ↑
          </button>
        </div>
      </div>

      <StageImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onConfirm={onImportConfirm}
      />
    </div>
  );
}

