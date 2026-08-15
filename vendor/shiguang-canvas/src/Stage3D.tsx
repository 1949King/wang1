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
  applyPreset,
  boneKeyToRegion,
  chainBonesFor,
  defaultPose,
  endEffectorBoneKey,
  exportBVH,
  formationPositions,
  facingYForFormation,
  getPoseBones,
  GROUP_TEMPLATES,
  HUMAN_PRESETS,
  JOINT_LABELS,
  makeRiggedHumanoid,
  mergePose,
  MOTION_PRESETS,
  POSE_PRESETS,
  readPosePatchFromBone,
  resolveHitBoneKey,
  RIG_MESH_STYLE,
  sampleCompositeMotion,
  sampleKeyframes,
  sampleMotionFrames,
  solveChainIk,
  yawToward,
  type FormationId,
  type HairStyle,
  type HumanVariant,
  type JointPose,
  type MotionPreset,
  type PosePresetId,
} from "./riggedHumanoid";
import { exportAllControlNetChannels } from "./stage3dControlNet";
import StageImportModal, { type StageImportResult } from "./StageImportModal";
import { useCanvasStore } from "./store";
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
  /** 姿势关键帧轨：actorId → 关键帧数组 */
  poseTracks?: Record<string, { t: number; pose: JointPose }[]>;
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

function isWorldVisible(obj: THREE.Object3D): boolean {
  let p: THREE.Object3D | null = obj;
  while (p) {
    if (!p.visible) return false;
    p = p.parent;
  }
  return true;
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

/** 全画幅近似：f = 43.27 / (2 * tan(fov° / 2))，再取常见焦段 */
function fovToFocalLength(fovDeg: number): number {
  if (fovDeg <= 0) return 50;
  const exact = 43.27 / (2 * Math.tan((fovDeg * Math.PI) / 360));
  const COMMON = [14, 18, 24, 28, 35, 50, 58, 85, 135, 200];
  let best = COMMON[0];
  let bestDiff = Math.abs(exact - best);
  for (const f of COMMON) {
    const d = Math.abs(exact - f);
    if (d < bestDiff) {
      bestDiff = d;
      best = f;
    }
  }
  return best;
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

function saveScene(data: ScenePersist) {
  try {
    localStorage.setItem(STAGE_KEY, JSON.stringify(data));
  } catch {
    /* ignore quota */
  }
}

function disposeObject3D(obj: THREE.Object3D) {
  obj.traverse((ch) => {
    if (ch instanceof THREE.Mesh) {
      ch.geometry?.dispose();
      const mat = ch.material;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose();
    }
  });
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

/** 姿势关键帧时间轴小组件 —— 组件内维护一个时间戳输入框 + 关键帧列表 */
function PoseTimeline({
  track,
  onRecord,
  onDelete,
  onPlay,
  onStop,
}: {
  track: { t: number; pose: JointPose }[];
  onRecord: (t: number) => void;
  onDelete: (t: number) => void;
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
                title={`t=${k.t}ms · 点右键删除`}
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
  const [poseTracks, setPoseTracks] = useState<Record<string, { t: number; pose: JointPose }[]>>(persisted?.poseTracks ?? {});
  /** 选了"从X到Y的路径"时保存两个相机 id */
  const [pathFromId, setPathFromId] = useState<string | null>(null);
  const pathRafRef = useRef<number | null>(null);
  const poseRafRef = useRef<number | null>(null);
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
  const transformDraggingRef = useRef(false);
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const actorsRef = useRef(actors);
  actorsRef.current = actors;
  const actorSyncRafRef = useRef(false);
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

  // Persist scene — 同时同步到 store.stage3dSnapshot，便于工程 bundle 导出/导入
  useEffect(() => {
    const persistData: ScenePersist = {
      actors, cameras, fov, aspect, activeCamId, lightPreset, groundPreset, poseTracks, selectedId, sceneMode, envEquirect,
    };
    saveScene(persistData);
    try {
      useCanvasStore.getState().setStage3dSnapshot(persistData);
    } catch {
      /* store 尚未初始化时跳过，不影响本地持久化 */
    }
  }, [actors, cameras, fov, aspect, activeCamId, lightPreset, groundPreset, poseTracks, selectedId, sceneMode, envEquirect]);

  // Init three.js
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const scene = new THREE.Scene();
    const initialLight = LIGHT_PRESETS[persisted?.lightPreset ?? "neutral"];
    scene.background = new THREE.Color(initialLight.bg);
    scene.fog = new THREE.Fog(initialLight.fog, 18, 42);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.set(5, 4, 7);

    const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
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
    controls.target.set(0, 1, 0);
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
    scene.add(ground);

    const grid = new THREE.GridHelper(40, 40, 0x2a3a4d, 0x1a2433);
    (grid.material as THREE.Material).opacity = 0.55;
    (grid.material as THREE.Material).transparent = true;
    scene.add(grid);

    const axisHelper = new THREE.AxesHelper(1.2);
    axisHelper.visible = false;
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
    };

    // TransformControls 拖拽时临时禁用 Orbit，结束后恢复
    transform.addEventListener("dragging-changed", (e: { value: boolean }) => {
      controls.enabled = !e.value;
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
      // MotionPreset 采样：直接写 3D 对象，绕过 React state
      const apiNow = apiRef.current;
      if (apiNow) {
        const nowMs = performance.now();
        activeMotionsRef.current.forEach((motions, actorId) => {
          const obj = apiNow.objects.get(actorId);
          if (!obj) return;
          const isDraggingTransform = transformBoneKeyRef.current !== null;
          if (isDraggingTransform) return;
          const startedAt = motionStartRef.current.get(actorId) ?? nowMs;
          const elapsed = nowMs - startedAt;
          const { pose, rootOffset } = sampleCompositeMotion(motions, elapsed);
          applyPose(obj, pose);
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
      // 动态 Bloom 强度：用 ref 直接读，避免 state 延迟
      const targetStrength = bloomStrengthRef.current;
      if (bloomPass.strength !== targetStrength) {
        bloomPass.strength = targetStrength;
      }
      composer.render();
    };
    tick();

    onStatus("3D 导演台就绪 — 点姿势或拉手/脚摆动作 · 空白处拖动旋转视角 · 右键平移");

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      transform.dispose();
      scene.remove(transform);
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
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
    api.hemi.color.set(preset.hemiSky);
    api.hemi.groundColor.set(preset.hemiGround);
    api.hemi.intensity = preset.hemiIntensity;
    api.dir.color.set(preset.dirColor);
    api.dir.intensity = preset.dirIntensity;
    api.dir.position.set(...preset.dirPos);

    const oldTex = (api.ground.material as THREE.MeshStandardMaterial).map;
    const newTex = makeGroundTexture(groundPreset);
    const mat = api.ground.material as THREE.MeshStandardMaterial;
    if (oldTex && oldTex !== newTex) oldTex.dispose();
    mat.map = newTex ?? null;
    mat.color.set(newTex ? 0xffffff : groundPreset === "studio-dark" ? 0x141c28 : 0xaaaaaa);
    mat.needsUpdate = true;
  }, [lightPreset, groundPreset]);

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
          obj.traverse((ch) => {
            if (
              ch instanceof THREE.Mesh &&
              ch.userData.tint === "clothes" &&
              ch.material instanceof THREE.MeshStandardMaterial
            ) {
              ch.material.color.set(a.color);
            }
          });
        } else if (obj instanceof THREE.Mesh && obj.material instanceof THREE.MeshStandardMaterial) {
          obj.material.color.set(a.color);
        }
        obj.position.set(a.position[0], a.position[1], a.position[2]);
        obj.rotation.y = a.rotationY;
        obj.scale.setScalar(a.scale);
        const isSel = a.id === sid;
        const selChain = isSel && sBone ? chainBonesFor(sBone) : [];
        const hoverChain = isSel && hBone ? chainBonesFor(hBone) : [];
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
            ch.material.emissive = new THREE.Color("#f59e0b");
            ch.material.emissiveIntensity = 0.62;
          } else if (isHover) {
            ch.material.emissive = new THREE.Color("#fbbf24");
            ch.material.emissiveIntensity = 0.4;
          } else if (isSel && canGlow) {
            ch.material.emissive = new THREE.Color("#1d4ed8");
            ch.material.emissiveIntensity = 0.16;
          } else {
            ch.material.emissive = new THREE.Color("#000000");
            ch.material.emissiveIntensity = 0;
          }
        });
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
    });
  }, [actors, selectedId, selectedBoneKey, hoveredBoneKey]);

  // Sync camera helpers
  useEffect(() => {
    const api = apiRef.current;
    if (!api) return;
    const keep = new Set(cameras.map((c) => c.id));
    for (const [id, obj] of api.camHelpers) {
      if (!keep.has(id)) {
        api.scene.remove(obj);
        api.camHelpers.delete(id);
      }
    }
    for (const c of cameras) {
      let helper = api.camHelpers.get(c.id);
      if (!helper) {
        const g = new THREE.Group();
        const cone = new THREE.Mesh(
          new THREE.ConeGeometry(0.18, 0.4, 12),
          new THREE.MeshStandardMaterial({ color: "#fbbf24" }),
        );
        cone.rotation.x = Math.PI / 2;
        const body = new THREE.Mesh(
          new THREE.BoxGeometry(0.28, 0.2, 0.35),
          new THREE.MeshStandardMaterial({ color: "#f59e0b" }),
        );
        body.position.z = 0.2;
        g.add(cone, body);
        api.scene.add(g);
        api.camHelpers.set(c.id, g);
        helper = g;
      }
      helper.position.set(c.position[0], c.position[1], c.position[2]);
      helper.lookAt(c.lookAt[0], c.lookAt[1], c.lookAt[2]);
    }
  }, [cameras]);

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
          api.camera.position.set(5, 4, 7);
          api.controls.target.set(0, 1, 0);
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
      api.transform.enabled = true;
      api.transform.attach(bone);
      api.transform.setMode("rotate");
      onStatus(`已选 ${BONE_CN[boneKey] || boneKey} · 拖肢体带动整条链 · 旋转环可微调`);
    };

    const beginIkSession = (actorId: string, boneKey: string, point: THREE.Vector3, ev: PointerEvent) => {
      const actorObj = api.objects.get(actorId);
      if (!actorObj) return;
      const bones = getPoseBones(actorObj);
      const endKey = endEffectorBoneKey(boneKey);
      const endBone = bones[endKey] || bones[boneKey];
      const endWorld = new THREE.Vector3();
      if (endBone) endBone.getWorldPosition(endWorld);
      else endWorld.copy(point);
      ikSessionRef.current = {
        actorId,
        boneKey,
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

      if (editModeRef.current === "joint" && !ev.altKey && !ev.shiftKey) {
        const hit = pickHit(ev);
        if (hit.actorId && hit.boneKey && hit.point) {
          ev.stopImmediatePropagation();
          attachSelectedBone(hit.actorId, hit.boneKey);
          beginIkSession(hit.actorId, hit.boneKey, hit.point, ev);
          pendingDragRef.current = null;
          dragStartRef.current = null;
          marqueeSessionRef.current = null;
          setMarquee(null);
          return;
        }
      }

      if (editModeRef.current === "joint" && ev.shiftKey && !ev.altKey) {
        ev.stopImmediatePropagation();
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
        const dist = Math.hypot(ev.clientX - ik.clientX, ev.clientY - ik.clientY);
        if (!ik.active && dist < DRAG_THRESHOLD_PX) return;
        if (!ik.active) {
          ik.active = true;
          ikDraggingRef.current = true;
          api.controls.enabled = false;
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
        const next = mergePose(actorPose(actor), solveChainIk(obj, ik.boneKey, target, actorPose(actor)));
        applyPose(obj, next);
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
        const next = Math.min(2.5, Math.max(0.4, base.scale + -dy * 0.01));
        setActors((prev) =>
          prev.map((a) => (a.id === sid ? { ...a, scale: next } : a)),
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
          onStatus(`已拉「${BONE_CN[ik.boneKey] || ik.boneKey}」整条肢体 · 空白处拖可转视角`);
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
              onStatus("框选未命中部位 · 再拖框或点选");
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
          onStatus("点选或拉肢体摆姿势 · 拉手带动整臂 · Alt 移动整人");
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
        onStatus("已取消部位选中 · 再点选或拉肢体");
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
    setActors((prev) =>
      prev.map((a) => (a.id === selectedId ? { ...a, pose: next } : a)),
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
    api.renderer.render(api.scene, api.camera);
    const dataUrl = api.renderer.domElement.toDataURL("image/png");
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
      composer ? composer.render(api.scene, api.camera) : api.renderer.render(api.scene, api.camera);
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
    });
    onStatus(
      `已导出首尾帧 ${resSize}（${cam.pathPoints.length} 点${meta.referenceActor ? ` · 参考「${meta.referenceActor}」` : ""}）`,
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

  /** 从 WebGLRenderTarget 读像素 → Canvas → PNG data URL */
  const readRenderTargetToDataURL = (
    renderer: THREE.WebGLRenderer,
    rt: THREE.WebGLRenderTarget,
    w: number,
    h: number,
  ): string => {
    const buf = new Uint8Array(w * h * 4);
    renderer.readRenderTargetPixels(rt, 0, 0, w, h, buf);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d")!;
    const imgData = ctx.createImageData(w, h);
    // WebGL 左下角起点 → Canvas 左上角起点，需要垂直翻转
    for (let row = 0; row < h; row++) {
      const srcStart = row * w * 4;
      const dstStart = (h - 1 - row) * w * 4;
      for (let col = 0; col < w * 4; col++) {
        imgData.data[dstStart + col] = buf[srcStart + col];
      }
    }
    ctx.putImageData(imgData, 0, 0);
    return canvas.toDataURL("image/png");
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
      api.renderer.render(api.scene, ortho);
      const dataUrl = api.renderer.domElement.toDataURL("image/png");
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

  /** 停止正在播放的路径 */
  const stopCamPath = () => {
    if (pathRafRef.current !== null) {
      cancelAnimationFrame(pathRafRef.current);
      pathRafRef.current = null;
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
      // 同时间戳覆盖
      const idx = list.findIndex((k) => k.t === t);
      if (idx >= 0) list[idx] = { t, pose: currentPose };
      else list.push({ t, pose: currentPose });
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
      applyPose(actorObj, pose);
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
      { id: "fit", label: "重置轨道视角", shortcut: "F", run: () => { apiRef.current?.controls.reset(); onStatus("已重置视角"); } },
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
        apiRef.current?.controls.reset();
        onStatus("已重置视角");
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
            ? `已选「${BONE_CN[selectedBoneKey] || selectedBoneKey}」· 拖肢体带动整条链 · 空白处转视角`
            : "点姿势预设或拉手/脚摆动作 · 空白处拖动旋转视角 · 右键平移"
          : "移整人模式 · 拖模型平移 · J 回到框选调关节"}
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
                <div className="section-title">姿势 · {selected.name}</div>
                <p className="muted tiny">
                  点「挥手/思考」等预设会立刻改姿势。在手上拖会带动整臂（黄色轨迹）。空白处拖动旋转视角，右键平移。
                </p>
                <div className="seg">
                  <button
                    type="button"
                    className={editMode === "joint" ? "on" : ""}
                    onClick={() => {
                      setEditMode("joint");
                      onStatus("点选或拉肢体摆姿势 · 拉手带动整臂 · Alt 移动整人");
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
                <div className="section-title">正反面</div>
                <p className="muted tiny">眼睛/胸口白块/脚前黄箭头 = 正面。挥手等动作相对正面，勿背对镜头再调。</p>
                <div className="seg">
                  <button type="button" onClick={faceSelectedToCamera}>正面朝向镜头</button>
                  <button type="button" onClick={flipSelectedFront}>转身 180°</button>
                </div>
                <div className="section-title">姿势预设</div>
                <div className="stage3d-chips">
                  {POSE_PRESETS.map((p) => (
                    <button key={p.id} type="button" className="chip" onClick={() => setPosePreset(p.id)}>
                      {p.label}
                    </button>
                  ))}
                </div>
                <details className="stage3d-add-block">
                  <summary>关节滑条（精调，可选）</summary>
                  <div className="stage3d-joints">
                    {JOINT_LABELS.map((j) => {
                      const pose = actorPose(selected);
                      return (
                        <div className="field compact" key={j.key}>
                          <label>
                            {j.label} {Math.round(pose[j.key])}°
                          </label>
                          <input
                            type="range"
                            min={j.min}
                            max={j.max}
                            step={1}
                            value={pose[j.key]}
                            onChange={(e) => patchPose({ [j.key]: Number(e.target.value) })}
                          />
                        </div>
                      );
                    })}
                  </div>
                </details>
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
                <div className="section-title">动作轨迹（循环播放）</div>
                <p className="muted tiny">多选叠加 · tick 内直接驱动骨骼 · 拖拽关节时自动暂停</p>
                <div className="stage3d-chips">
                  {MOTION_PRESETS.map((m) => {
                    const on = isMotionActive(selected.id, m.id);
                    return (
                      <button
                        key={m.id}
                        type="button"
                        className={`chip${on ? " on" : ""}`}
                        onClick={() => toggleActorMotion(selected.id, m.id)}
                        title={`${m.label} · ${(m.duration / 1000).toFixed(1)}s`}
                      >
                        {m.label}
                      </button>
                    );
                  })}
                </div>
                <div className="section-title">姿势关键帧</div>
                <PoseTimeline
                  track={poseTracks[selected.id] || []}
                  onRecord={(t) => recordPoseKeyframe(selected.id, t)}
                  onDelete={(t) => deletePoseKeyframe(selected.id, t)}
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
                  onStatus("已重置为单人素模 · 点选或拉肢体摆姿势");
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
                onStatus("点选或拉肢体摆姿势 · 拉手带动整臂 · Alt 移动整人");
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

