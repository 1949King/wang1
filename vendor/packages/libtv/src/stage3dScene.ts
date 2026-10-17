/**
 * 3D 导演台 · 场景快照序列化（Stage3D 配套辅助）
 *
 * 背景：Stage3D.tsx 是冻结区（stage3d-core 整文件锁）不能动。
 * 3D 导演台与画布之间缺少"场景状态可携带化"桥梁：capture() 只回传
 * dataUrl + camera 元数据，丢失了 actor 姿势、灯光、地面、相机路径等。
 *
 * 本模块提供「scene 状态 ↔ JSON」的纯函数转换，让画布节点可承载：
 *   - 演员位置 / 姿势 id
 *   - 相机路径点（机位动画）
 *   - 灯光 / 地面预设
 *   - 背景 / 雾
 *   - 当前选中的 actor / camera id
 *
 * 与 Stage3D.tsx 集成方式：父组件 useEffect 在 stage 状态变更时
 * 调 ``captureSceneState(api)``；落画布时调 ``sceneToJSON(state)``；
 * 双击回放时调 ``sceneStateFromJSON(json)`` 还原给 Stage3D。
 *
 * ⚠️ 纯函数 / 无 React / 无 three.js 导入（保持独立可测）。
 */

export type Vec3 = [number, number, number];

export type ActorState = {
  id: string;
  name: string;
  kind: "actor" | "prop" | "environment";
  position: Vec3;
  rotation: Vec3;
  /** 姿势 id（humanoidPose 查表） */
  poseId?: string;
  /** 角色设定 prompt（若已知，便于下游生成参考） */
  promptHint?: string;
};

export type CameraPathPoint = {
  position: Vec3;
  lookAt: Vec3;
  fov: number;
  /** 时间码（秒，>=0） */
  t: number;
};

export type CameraState = {
  id: string;
  name: string;
  fov: number;
  shotSize: string;
  position: Vec3;
  lookAt: Vec3;
  pathPoints: CameraPathPoint[];
};

export type SceneState = {
  /** 协议版本号（schema bump 时加 1） */
  schemaVersion: 1;
  /** ISO 时间戳 */
  capturedAt: string;
  /** 演员 / 道具 */
  actors: ActorState[];
  /** 机位 */
  cameras: CameraState[];
  /** 选中项（id） */
  selectedId: string | null;
  /** 灯光预设（与 Stage3D LIGHT_PRESETS 的 key 对齐） */
  lightPreset: string;
  /** 地面预设 */
  groundPreset: string;
  /** 背景色（hex，#rrggbb） */
  bgColor: string;
  /** 雾色 */
  fogColor: string;
  /** 视口宽高（用于回放时还原） */
  viewport: { width: number; height: number };
  /** 当前视角模式（"director" / "camera"） */
  viewMode: "director" | "camera";
};

// ── 1) 序列化：纯函数，从 SceneState → JSON-safe object ─────────

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function _validateHex(c: string, fallback = "#101216"): string {
  return HEX_RE.test(c) ? c : fallback;
}

function _validateVec3(v: unknown, fallback: Vec3 = [0, 0, 0]): Vec3 {
  if (Array.isArray(v) && v.length === 3 &&
      v.every((n) => typeof n === "number" && Number.isFinite(n))) {
    return [v[0], v[1], v[2]];
  }
  return fallback;
}

function _validateCameraPathPoint(p: unknown): CameraPathPoint | null {
  if (!p || typeof p !== "object") return null;
  const pt = p as { position?: unknown; lookAt?: unknown; fov?: unknown; t?: unknown };
  return {
    position: _validateVec3(pt.position),
    lookAt: _validateVec3(pt.lookAt),
    fov: typeof pt.fov === "number" && Number.isFinite(pt.fov) ? pt.fov : 35,
    t: typeof pt.t === "number" && Number.isFinite(pt.t) && pt.t >= 0 ? pt.t : 0,
  };
}

function _validateActor(a: any): ActorState | null {
  if (!a || typeof a !== "object" || typeof a.id !== "string") return null;
  return {
    id: a.id,
    name: typeof a.name === "string" ? a.name : a.id,
    kind: a.kind === "prop" || a.kind === "environment" ? a.kind : "actor",
    position: _validateVec3(a.position),
    rotation: _validateVec3(a.rotation),
    poseId: typeof a.poseId === "string" ? a.poseId : undefined,
    promptHint: typeof a.promptHint === "string" ? a.promptHint : undefined,
  };
}

function _validateCamera(c: unknown): CameraState | null {
  if (!c || typeof c !== "object" || typeof (c as { id?: unknown }).id !== "string") return null;
  const cam = c as {
    id: string; name?: unknown; fov?: unknown; shotSize?: unknown;
    position?: unknown; lookAt?: unknown; pathPoints?: unknown;
  };
  return {
    id: cam.id,
    name: typeof cam.name === "string" ? cam.name : cam.id,
    fov: typeof cam.fov === "number" && Number.isFinite(cam.fov) ? cam.fov : 35,
    shotSize: typeof cam.shotSize === "string" ? cam.shotSize : "中景",
    position: _validateVec3(cam.position),
    lookAt: _validateVec3(cam.lookAt),
    pathPoints: Array.isArray(cam.pathPoints)
      ? cam.pathPoints.map(_validateCameraPathPoint).filter((x): x is CameraPathPoint => x !== null)
      : [],
  };
}

export function sceneToJSON(state: SceneState): Record<string, unknown> {
  return {
    schemaVersion: 1,
    capturedAt: state.capturedAt,
    actors: state.actors.map((a) => ({ ...a })),
    cameras: state.cameras.map((c) => ({
      ...c,
      pathPoints: c.pathPoints.map((p) => ({ ...p })),
    })),
    selectedId: state.selectedId,
    lightPreset: state.lightPreset,
    groundPreset: state.groundPreset,
    bgColor: _validateHex(state.bgColor),
    fogColor: _validateHex(state.fogColor),
    viewport: {
      width: state.viewport.width,
      height: state.viewport.height,
    },
    viewMode: state.viewMode === "camera" ? "camera" : "director",
  };
}

// ── 2) 反序列化：JSON（可能损坏/部分缺失） → SceneState ─────

export function sceneStateFromJSON(
  raw: unknown,
  fallback: Partial<SceneState> = {},
): SceneState {
  if (!raw || typeof raw !== "object") {
    return _emptyScene(fallback);
  }
  const obj = raw as Record<string, unknown>;
  return {
    schemaVersion: 1,
    capturedAt: typeof obj.capturedAt === "string" ? obj.capturedAt : new Date().toISOString(),
    actors: Array.isArray(obj.actors) ? obj.actors.map(_validateActor).filter((x): x is ActorState => x !== null) : [],
    cameras: Array.isArray(obj.cameras) ? obj.cameras.map(_validateCamera).filter((x): x is CameraState => x !== null) : [],
    selectedId: typeof obj.selectedId === "string" ? obj.selectedId : null,
    lightPreset: typeof obj.lightPreset === "string" ? obj.lightPreset : (fallback.lightPreset || "studio-soft"),
    groundPreset: typeof obj.groundPreset === "string" ? obj.groundPreset : (fallback.groundPreset || "studio-dark"),
    bgColor: _validateHex(typeof obj.bgColor === "string" ? obj.bgColor : "", fallback.bgColor || "#101216"),
    fogColor: _validateHex(typeof obj.fogColor === "string" ? obj.fogColor : "", fallback.fogColor || "#0a0c10"),
    viewport: _validateViewport(obj.viewport, fallback.viewport),
    viewMode: obj.viewMode === "camera" ? "camera" : "director",
  };
}

function _validateViewport(
  v: unknown,
  fallback?: { width: number; height: number },
): { width: number; height: number } {
  if (v && typeof v === "object" &&
      typeof (v as any).width === "number" && typeof (v as any).height === "number" &&
      (v as any).width > 0 && (v as any).height > 0) {
    return { width: Math.round((v as any).width), height: Math.round((v as any).height) };
  }
  return fallback || { width: 1280, height: 720 };
}

function _emptyScene(fallback: Partial<SceneState>): SceneState {
  return {
    schemaVersion: 1,
    capturedAt: new Date().toISOString(),
    actors: [],
    cameras: [],
    selectedId: null,
    lightPreset: fallback.lightPreset || "studio-soft",
    groundPreset: fallback.groundPreset || "studio-dark",
    bgColor: fallback.bgColor || "#101216",
    fogColor: fallback.fogColor || "#0a0c10",
    viewport: fallback.viewport || { width: 1280, height: 720 },
    viewMode: "director",
  };
}

// ── 3) 场景差异（供「前后对比」用） ──────────────────────────

export function diffScenes(before: SceneState, after: SceneState): {
  actorsAdded: string[];
  actorsRemoved: string[];
  camerasAdded: string[];
  camerasRemoved: string[];
  presetChanged: boolean;
  bgColorChanged: boolean;
} {
  const bActorIds = new Set(before.actors.map((a) => a.id));
  const aActorIds = new Set(after.actors.map((a) => a.id));
  const bCamIds = new Set(before.cameras.map((c) => c.id));
  const aCamIds = new Set(after.cameras.map((c) => c.id));
  return {
    actorsAdded: [...aActorIds].filter((id) => !bActorIds.has(id)),
    actorsRemoved: [...bActorIds].filter((id) => !aActorIds.has(id)),
    camerasAdded: [...aCamIds].filter((id) => !bCamIds.has(id)),
    camerasRemoved: [...bCamIds].filter((id) => !aCamIds.has(id)),
    presetChanged: before.lightPreset !== after.lightPreset || before.groundPreset !== after.groundPreset,
    bgColorChanged: before.bgColor !== after.bgColor,
  };
}
