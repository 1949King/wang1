// 3D 导演台 · 场景快照（Stage3D 配套辅助）自检
// 源：vendor/packages/canvas-core/src/stage3dScene.ts
//
// ⚠️ 本文件是 stage3dScene.ts 的**纯函数副本**快照（无 React / 无 three.js）。
// 改源时务必同步本文件。下面用 `@source:` 标记关键函数。
//
// 关键不变量：
//   - sceneToJSON 必含 schemaVersion: 1 + capturedAt + actors + cameras
//   - sceneStateFromJSON 对损坏输入返回**合法** SceneState（不抛）
//   - diffScenes 列出 id 差异（不比较嵌套属性）

// @source: stage3dScene.ts (SceneState 类型 + sceneToJSON)
function _validateHex(c, fallback = "#101216") {
  return /^#[0-9a-fA-F]{6}$/.test(c) ? c : fallback;
}
function _validateVec3(v, fallback = [0, 0, 0]) {
  if (Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === "number" && Number.isFinite(n))) {
    return [v[0], v[1], v[2]];
  }
  return fallback;
}

// @source: _validateActor / _validateCamera / _validateCameraPathPoint
function _validateActor(a) {
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
function _validateCamera(c) {
  if (!c || typeof c !== "object" || typeof c.id !== "string") return null;
  return {
    id: c.id, name: typeof c.name === "string" ? c.name : c.id,
    fov: typeof c.fov === "number" && Number.isFinite(c.fov) ? c.fov : 35,
    shotSize: typeof c.shotSize === "string" ? c.shotSize : "中景",
    position: _validateVec3(c.position), lookAt: _validateVec3(c.lookAt),
    pathPoints: Array.isArray(c.pathPoints) ? c.pathPoints : [],
  };
}

// @source: sceneStateFromJSON
function sceneStateFromJSON(raw, fallback = {}) {
  if (!raw || typeof raw !== "object") return _emptyScene(fallback);
  const obj = raw;
  return {
    schemaVersion: 1,
    capturedAt: typeof obj.capturedAt === "string" ? obj.capturedAt : new Date().toISOString(),
    actors: Array.isArray(obj.actors) ? obj.actors.map(_validateActor).filter((x) => x !== null) : [],
    cameras: Array.isArray(obj.cameras) ? obj.cameras.map(_validateCamera).filter((x) => x !== null) : [],
    selectedId: typeof obj.selectedId === "string" ? obj.selectedId : null,
    lightPreset: typeof obj.lightPreset === "string" ? obj.lightPreset : (fallback.lightPreset || "studio-soft"),
    groundPreset: typeof obj.groundPreset === "string" ? obj.groundPreset : (fallback.groundPreset || "studio-dark"),
    bgColor: _validateHex(typeof obj.bgColor === "string" ? obj.bgColor : "", fallback.bgColor || "#101216"),
    fogColor: _validateHex(typeof obj.fogColor === "string" ? obj.fogColor : "", fallback.fogColor || "#0a0c10"),
    viewport: obj.viewport && typeof obj.viewport.width === "number" && typeof obj.viewport.height === "number"
      ? { width: obj.viewport.width, height: obj.viewport.height }
      : (fallback.viewport || { width: 1280, height: 720 }),
    viewMode: obj.viewMode === "camera" ? "camera" : "director",
  };
}

function _emptyScene(fallback) {
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

// @source: diffScenes
function diffScenes(before, after) {
  const bA = new Set(before.actors.map((a) => a.id));
  const aA = new Set(after.actors.map((a) => a.id));
  const bC = new Set(before.cameras.map((c) => c.id));
  const aC = new Set(after.cameras.map((c) => c.id));
  return {
    actorsAdded: [...aA].filter((id) => !bA.has(id)),
    actorsRemoved: [...bA].filter((id) => !aA.has(id)),
    camerasAdded: [...aC].filter((id) => !bC.has(id)),
    camerasRemoved: [...bC].filter((id) => !aC.has(id)),
    presetChanged: before.lightPreset !== after.lightPreset || before.groundPreset !== after.groundPreset,
    bgColorChanged: before.bgColor !== after.bgColor,
  };
}

// ── 断言 ────────────────────────────────────────────────────
let pass = 0, fail = 0;
function check(label, cond, detail) {
  if (cond) { pass++; console.log("  OK  " + label); }
  else { fail++; console.log("  FAIL " + label + "  →  " + (typeof detail === "string" ? detail : JSON.stringify(detail))); }
}

console.log("=== 3D 导演台 · 场景快照自检 ===");

// ── 基础合法性 ──
const empty = sceneStateFromJSON(null);
check("null 输入 → 返回合法 SceneState", empty && empty.schemaVersion === 1, empty);
check("空 scene 必含默认 viewport", empty.viewport.width > 0 && empty.viewport.height > 0, empty.viewport);
check("空 scene 默认 lightPreset=studio-soft", empty.lightPreset === "studio-soft", empty.lightPreset);
check("空 scene 默认 viewMode=director", empty.viewMode === "director", empty.viewMode);

const valid = sceneStateFromJSON({
  schemaVersion: 1,
  capturedAt: "2026-09-14T00:00:00Z",
  actors: [{ id: "a1", name: "角色1", kind: "actor", position: [1, 2, 3], rotation: [0, 0, 0] }],
  cameras: [{ id: "c1", name: "机位1", fov: 35, shotSize: "中景", position: [0, 0, 5], lookAt: [0, 0, 0], pathPoints: [] }],
  selectedId: "a1",
  lightPreset: "golden-hour",
  groundPreset: "concrete",
  bgColor: "#202028",
  fogColor: "#000000",
  viewport: { width: 1920, height: 1080 },
  viewMode: "camera",
});
check("合法 JSON 完整保留", valid.actors.length === 1 && valid.cameras.length === 1 && valid.viewMode === "camera", valid);

// ── 损坏输入容错 ──
const broken = sceneStateFromJSON({ actors: "not-array", cameras: null, bgColor: "蓝色" });
check("损坏 actors→空数组", Array.isArray(broken.actors) && broken.actors.length === 0, broken.actors);
check("损坏 cameras→空数组", Array.isArray(broken.cameras) && broken.cameras.length === 0, broken.cameras);
check("非法 hex → fallback", broken.bgColor === "#101216", broken.bgColor);
check("非法 viewMode → director", broken.viewMode === "director", broken.viewMode);

// ── Vec3 校验 ──
const badVec = sceneStateFromJSON({ actors: [{ id: "x", name: "x", kind: "actor", position: "center", rotation: [1, 2] }] });
check("非数组 position → [0,0,0]", JSON.stringify(badVec.actors[0].position) === "[0,0,0]", badVec.actors[0]);

// ── diffScenes ──
const a = { actors: [{ id: "a1" }, { id: "a2" }], cameras: [{ id: "c1" }], lightPreset: "studio-soft", groundPreset: "studio-dark", bgColor: "#101216" };
const b = { actors: [{ id: "a1" }, { id: "a3" }], cameras: [{ id: "c1" }, { id: "c2" }], lightPreset: "golden-hour", groundPreset: "studio-dark", bgColor: "#101216" };
const d = diffScenes(a, b);
check("diff actorsAdded=[a3]", d.actorsAdded.length === 1 && d.actorsAdded[0] === "a3", d);
check("diff actorsRemoved=[a2]", d.actorsRemoved.length === 1 && d.actorsRemoved[0] === "a2", d);
check("diff camerasAdded=[c2]", d.camerasAdded.length === 1 && d.camerasAdded[0] === "c2", d);
check("diff camerasRemoved=[]", d.camerasRemoved.length === 0, d);
check("diff presetChanged=true（light 改）", d.presetChanged === true, d);
check("diff bgColorChanged=false（未改）", d.bgColorChanged === false, d);

// ── 源硬值校验（防副本漂移） ──
const { readFileSync } = await import("node:fs");
const SRC = readFileSync("vendor/packages/canvas-core/src/stage3dScene.ts", "utf-8");
check("源 schemaVersion=1", /schemaVersion:\s*1/.test(SRC), "改了 schemaVersion 请同步测试");
check("源有 sceneToJSON", /export function sceneToJSON/.test(SRC), "sceneToJSON 不在源里");
check("源有 sceneStateFromJSON", /export function sceneStateFromJSON/.test(SRC), "sceneStateFromJSON 不在源里");
check("源有 diffScenes", /export function diffScenes/.test(SRC), "diffScenes 不在源里");
check("源 LIGHT_PRESETS 默认 'studio-soft' 兜底", /studio-soft/.test(SRC), "默认预设名变了");
check("源 GROUND_PRESETS 默认 'studio-dark' 兜底", /studio-dark/.test(SRC), "默认地面预设名变了");

console.log(`\n${fail === 0 ? "OK 3D 场景快照全部通过" : "✗ 失败 " + fail + " 项"}（${pass} 项）`);
if (fail > 0) process.exit(1);
