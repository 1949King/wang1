// 24 位灯位 → 3D 导演台灯光：端到端数据流验证（2026-10-12）
// ==================================================================================
// 背景：`lightingPresets.ts`（24 主光位 + 9 轮廓光）此前在 `Stage3D.tsx` **零引用**，
// 面板 apply() 只写提示词 ⇒ 用户选灯位时 3D 预览纹丝不动、只能盲选。
// 本刀加了一条 store 单通道把它接上。vitest 是 node 环境（无 DOM），
// `useStage3dLighting` 里的 useEffect 一行都测不到 ⇒ 那部分由本脚本用**真 three 场景**
// 走一遍完整链路（request → store → consume → apply）。
//
// 本文件是 `stage3dLighting.ts` 的**数学副本**（沿用本项目 mjs 镜像测试约定：
// 源改公式必须同步本副本）。同时用源级 regex 校验副本没漂。
//
// 运行：node _verify/check_stage3d_lighting.mjs
// 打印模式：加 --dump 输出全部测量值
import { readFileSync } from "node:fs";
import { dirname, resolve as pathResolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "../vendor/shiguang-canvas/node_modules/three/build/three.module.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = pathResolve(HERE, "../vendor/packages/canvas-core/src/stage3dLighting.ts");
const SRC_PRESETS = pathResolve(HERE, "../vendor/packages/canvas-core/src/lightingPresets.ts");
const SRC_STAGE = pathResolve(HERE, "../vendor/packages/canvas-core/src/Stage3D.tsx");
const DUMP = process.argv.includes("--dump");

let pass = 0, fail = 0;
function check(name, ok, detail = "") {
  if (ok) { pass++; console.log(`  [OK  ] ${name}`); }
  else { fail++; console.log(`  [FAIL] ${name}${detail !== "" ? " — " + JSON.stringify(detail) : ""}`); }
}
const deg = (n) => (n * Math.PI) / 180;

// ── 与源逐行等价的纯函数（数学副本）────────────────────────────────────────────
const LIGHT_RADIUS = 7;
const SUBJECT_Y = 1.0;

function lightPosition(azimuthDeg, heightDeg, radius = LIGHT_RADIUS) {
  const az = deg(azimuthDeg);
  const h = deg(heightDeg);
  const horiz = radius * Math.cos(h);
  return [horiz * Math.sin(az), SUBJECT_Y + radius * Math.sin(h), horiz * Math.cos(az)];
}

function kelvinToRgb(kelvin) {
  const t = Math.min(40000, Math.max(1000, kelvin)) / 100;
  let r, g, b;
  if (t <= 66) { r = 255; g = 99.4708025861 * Math.log(t) - 161.1195681661; }
  else { r = 329.698727446 * Math.pow(t - 60, -0.1332047592);
         g = 288.1221695283 * Math.pow(t - 60, -0.0755148492); }
  if (t >= 66) b = 255;
  else if (t <= 19) b = 0;
  else b = 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  const c = (x) => Math.max(0, Math.min(255, Math.round(x)));
  return [c(r), c(g), c(b)];
}

// ── 最小 store 通道复刻（验证「先消费再应用」的次序契约）──────────────────────
function makeChannel(seqShots) {
  let seq = 0;
  let pending = null;
  let consumedDuringApply = null;
  const store = {
    get seq() { return seq; },
    get pending() { return pending; },
    requestStage3dLighting: (state) => { pending = state; seq += 1; },
    consumeStage3dLighting: () => { pending = null; },
    getState: () => ({
      pendingStage3dLighting: pending,
      consumeStage3dLighting: () => { pending = null; },
    }),
  };
  const hookRun = (api, preset) => {
    if (!seq) return false;
    const st = store.getState();
    const p = st.pendingStage3dLighting;
    st.consumeStage3dLighting(); // 先消费
    if (p) applyLightingToApi(api, p);
    else if (preset) restore(api, preset);
    return true;
  };
  return { store, hookRun, get consumedDuringApply() { return consumedDuringApply; } };
}

const rimStore = new WeakMap();
function ensureRimLights(scene) {
  let arr = rimStore.get(scene);
  if (!arr) {
    arr = [0, 1].map((i) => {
      const l = new THREE.DirectionalLight("#ffffff", 0);
      l.castShadow = false;
      l.name = `stage3d-rim-light-${i}`;
      scene.add(l);
      return l;
    });
    rimStore.set(scene, arr);
  }
  return arr;
}

function applyLightingToApi(api, state) {
  api.dir.position.set(...state.dirPos);
  api.dir.color.set(state.dirColor);
  api.dir.intensity = state.dirIntensity;
  api.hemi.color.set(state.hemiSky);
  api.hemi.intensity = state.hemiIntensity;
  const lights = ensureRimLights(api.scene);
  for (let i = 0; i < lights.length; i++) {
    const rim = state.rims[i];
    if (!rim) { lights[i].intensity = 0; continue; }
    lights[i].position.set(...rim.pos);
    lights[i].color.set(rim.color);
    lights[i].intensity = rim.intensity;
  }
}

function restore(api, preset) {
  api.hemi.color.set(preset.hemiSky);
  api.hemi.groundColor.set(preset.hemiGround);
  api.hemi.intensity = preset.hemiIntensity;
  api.dir.color.set(preset.dirColor);
  api.dir.intensity = preset.dirIntensity;
  api.dir.position.set(...preset.dirPos);
  const lights = rimStore.get(api.scene);
  if (lights) for (const l of lights) l.intensity = 0;
}

function makeApi() {
  const scene = new THREE.Scene();
  return { scene, hemi: new THREE.HemisphereLight(), dir: new THREE.DirectionalLight() };
}
const rimLightsIn = (api) =>
  api.scene.children.filter((o) => o instanceof THREE.DirectionalLight);

// ═══════════════════════════════════════════════════════════════════════════════
console.log("24 位灯位 → 3D 灯光：端到端数据流验证");
console.log("=".repeat(78));

// [1] 副本与源一致性（源级 regex：改了公式没同步副本 ⇒ 这里报红）
const src = readFileSync(SRC, "utf8");
const presets = readFileSync(SRC_PRESETS, "utf8");
const stage = readFileSync(SRC_STAGE, "utf8");
console.log("\n[1] 副本与源一致");
check("源含 LIGHT_RADIUS = 7", /LIGHT_RADIUS\s*=\s*7/.test(src));
check("源含 SUBJECT_Y = 1.0", /SUBJECT_Y\s*=\s*1\.0/.test(src));
check("源的 lightPosition 用 sin(az) 作 X", /horiz \* Math\.sin\(az\)/.test(src));
check("源的 lightPosition 用 cos(az) 作 Z", /horiz \* Math\.cos\(az\)/.test(src));
check("源做度→弧度换算（* Math.PI / 180）", /Math\.PI\)\s*\/\s*180/.test(src));
check("源 kelvinToRgb 用 Tanner Helland 分段", /99\.4708025861/.test(src));
check("源轮廓灯 castShadow=false", /castShadow\s*=\s*false/.test(src));
check("源轮廓灯名 stage3d-rim-light-", /`stage3d-rim-light-\$\{i\}`/.test(src));
check("源有 WeakMap 持有轮廓灯", /WeakMap<THREE\.Scene,\s*THREE\.DirectionalLight\[\]>/.test(src));
check("源 consume 在 apply 之前", (() => {
  const fnAt = src.indexOf("export function useStage3dLighting");
  const consumeAt = src.indexOf("consumeStage3dLighting()", fnAt);
  const applyAt = src.indexOf("applyLightingToApi(", fnAt);
  return consumeAt > -1 && applyAt > -1 && consumeAt < applyAt;
})());

// [2] 坐标系（几何不变式）
console.log("\n[2] 坐标系几何不变式");
{
  const [x0, y0, z0] = lightPosition(0, 0);
  check("0°/0° ⇒ +Z 最大、x≈0、y≈1", Math.abs(x0) < 1e-9 && Math.abs(z0 - 7) < 1e-9 && Math.abs(y0 - 1) < 1e-9,
    { x0, y0, z0 });
  const [x90] = lightPosition(90, 20);
  check("90° ⇒ +X（sin 管 X）", x90 > 0, { x90 });
  const [x180, , z180] = lightPosition(180, 15);
  check("180° ⇒ −Z", z180 < 0 && Math.abs(x180) < 1e-9, { x180, z180 });
  const [x270] = lightPosition(270, 20);
  check("270° ⇒ −X", x270 < 0, { x270 });
  const [, y90] = lightPosition(0, 90);
  check("高度 90° ⇒ y≈1+7", Math.abs(y90 - 8) < 1e-9, { y90 });
  const [, yNeg] = lightPosition(0, -60);
  check("负高度 ⇒ 低于主体", yNeg < SUBJECT_Y, { yNeg });
  // 所有方位水平半径 = R·cos(h)
  let radiusOk = true;
  for (let az = 0; az < 360; az += 15) {
    const [x, , z] = lightPosition(az, 30);
    if (Math.abs(Math.hypot(x, z) - 7 * Math.cos(deg(30))) > 1e-9) radiusOk = false;
  }
  check("任意方位的水平半径恒 = R·cos(h)", radiusOk);
}

// [3] 色温 → RGB
console.log("\n[3] 色温 → RGB");
{
  const [r3, g3, b3] = kelvinToRgb(3200);
  check("3200K 暖 ⇒ r>g>b", r3 > g3 && g3 > b3, { r3, g3, b3 });
  const [, , b56] = kelvinToRgb(5600);
  check("5600K 比 3200K 更蓝", b56 > b3, { b56, b3 });
  check("2000K 比 10000K 更红", kelvinToRgb(2000)[0] > kelvinToRgb(10000)[0]);
  let rangeOk = true;
  for (const k of [500, 1000, 3200, 5600, 40000, 99999]) {
    for (const v of kelvinToRgb(k)) if (!(v >= 0 && v <= 255 && Number.isInteger(v))) rangeOk = false;
  }
  check("全域通道落在 0–255 且为整数（含越界输入）", rangeOk);
}

// [4] 端到端：request → consume → apply（真 three 场景）
console.log("\n[4] 端到端通道（真 three 场景）");
{
  const api = makeApi();
  const ch = makeChannel();
  // 45° 伦勃朗 + 双侧轮廓
  const dirPos = lightPosition(45, 45);
  const rims = [120, 240].map((az) => ({
    pos: lightPosition(az, 30), color: "#ffd9a0", intensity: 0.55,
  }));
  ch.store.requestStage3dLighting({
    dirPos, dirColor: "#ffd9a0", dirIntensity: 0.75,
    hemiSky: "#ffd9a0", hemiIntensity: 0.81, rims,
  });
  const applied = ch.hookRun(api, null);
  check("hook 应用了一次", applied);
  check("dir.position 与快照逐位一致", JSON.stringify(api.dir.position.toArray()) === JSON.stringify(dirPos),
    api.dir.position.toArray());
  check("轮廓灯建了 2 盏", rimLightsIn(api).length === 2, rimLightsIn(api).length);
  check("轮廓灯 castShadow=false", rimLightsIn(api).every((l) => l.castShadow === false));
  check("双侧轮廓 x 一正一负", Math.sign(rimLightsIn(api)[0].position.x) !== Math.sign(rimLightsIn(api)[1].position.x));
  check("pending 已被消费（置空）", ch.store.pending === null);

  // 连调 3 次不重复创建
  for (let i = 0; i < 3; i++) {
    ch.store.requestStage3dLighting({ dirPos, dirColor: "#fff", dirIntensity: 1, hemiSky: "#fff", hemiIntensity: 1, rims });
    ch.hookRun(api, null);
  }
  check("连调 3 次不重复创建（仍 2 盏）", rimLightsIn(api).length === 2, rimLightsIn(api).length);

  // 切到「无轮廓光」⇒ 全关
  ch.store.requestStage3dLighting({ dirPos, dirColor: "#fff", dirIntensity: 1, hemiSky: "#fff", hemiIntensity: 1, rims: [] });
  ch.hookRun(api, null);
  check("rims=[] ⇒ 轮廓灯全关（不留残灯）", rimLightsIn(api).every((l) => l.intensity === 0));

  // 不越权：不改 background/fog
  const bgObj = new THREE.Color("#112233");
  api.scene.background = bgObj;
  ch.store.requestStage3dLighting({ dirPos, dirColor: "#fff", dirIntensity: 1, hemiSky: "#fff", hemiIntensity: 1, rims: [] });
  ch.hookRun(api, null);
  check("apply 不碰 scene.background", api.scene.background === bgObj);

  // 移除（pending=null）⇒ 恢复 preset
  const preset = { hemiSky: "#dbeaff", hemiGround: "#334455", hemiIntensity: 1.0,
    dirColor: "#ffffff", dirIntensity: 0.7, dirPos: [2, 6, 4] };
  ch.store.requestStage3dLighting(null);
  ch.hookRun(api, preset);
  check("移除 ⇒ dir 恢复 preset", JSON.stringify(api.dir.position.toArray()) === "[2,6,4]",
    api.dir.position.toArray());
  check("移除 ⇒ hemi 恢复 preset", api.hemi.color.getHexString() === "dbeaff");
  check("移除 ⇒ 轮廓灯全关", rimLightsIn(api).every((l) => l.intensity === 0));
}

// [5] 优先级守卫（Stage3D 源级）
console.log("\n[5] 优先级守卫（源级）");
check("Stage3D 含 seq===0 守卫", /stage3dLightingSeq === 0/.test(stage));
check("Stage3D effect deps 含 stage3dLightingSeq", /lightPreset, groundPreset, stage3dLightingSeq/.test(stage));
check("Stage3D 订阅了 stage3dLightingSeq", /useCanvasStore\(\(state\) => state\.stage3dLightingSeq\)/.test(stage));
check("Stage3D import 了 useStage3dLighting", /from "\.\/stage3dLighting"/.test(stage));
check("Stage3D 调用了 useStage3dLighting", /useStage3dLighting\(\{/.test(stage));

// [6] 轮廓光结构化字段（presets 源级）
console.log("\n[6] 轮廓光结构化（presets 源级）");
check("RimLight 有可选 azimuth", /azimuth\?: number/.test(presets));
check("RimLight 有可选 height", /height\?: number/.test(presets));
check("双侧轮廓给 2 个 azimuths", /azimuths: \[120, 240\]/.test(presets));
check("「无轮廓光」未给 azimuth（不点灯）",
  /\{ name: "无轮廓光", from: "—", note: "[^"]*" \}/.test(presets));
check("「环境轮廓」未给 azimuth（交给 IBL）",
  /\{ name: "环境轮廓", from: "背景反射", note: "[^"]*" \}/.test(presets));

console.log("\n" + "=".repeat(78));
console.log(`结果：${pass} 通过 / ${fail} 失败`);
if (DUMP) console.log({ LIGHT_RADIUS, SUBJECT_Y });
process.exit(fail === 0 ? 0 : 1);
