/**
 * stage3dLighting.ts — 24 位灯位 → 3D 导演台灯光可视化（2026-10-12，用户授权解冻 stage3d-core + canvas-magnetic-intent）
 * ================================================================================================================
 * 在此之前 **「电影级灯位」面板与 3D 导演台零数据流**（读码实测）：
 *   · `lightingPresets.ts`（24 主光位 + 9 轮廓光）在 `Stage3D.tsx` 里 **0 引用**；
 *   · 它的消费者只有 `LightingPanel.tsx` / `lighting.test.ts`，而且面板 `apply()` **只写提示词**；
 *   · `Stage3D.tsx` 自己另有一套 `LIGHT_PRESETS`（4 档死预设），物理上只有 2 盏灯（hemi + dir）。
 * ⇒ 用户在面板上选 24 个方位之一，**3D 预览纹丝不动**，只能盲选。
 * 这正是本项目 `zone8` 不变量点名的反模式：**同一语义被两条链路各写一遍**。
 *
 * 本模块把这条线接上，走的是**项目已有的正统通道**——照抄
 * `stage3dApplySeq` / `pendingStage3dCameras` / `consumeStage3dCameraPlan`（store.ts）
 * 与缺口① 的 `stage3dCastSeq` / `pendingStage3dCast` / `consumeStage3dCast`：
 *   灯位面板 UI → `requestStage3dLighting(快照)` → `stage3dLightingSeq+1` → Stage3D 侧的
 *   `useStage3dLighting()` 消费一次 → 把 hemi/dir/轮廓灯真正摆到位。
 * 为什么必须经 store 而不是直接互调：面板在画布节点浮层里、导演台在 Stage3D 里，
 * **唯一共同且可测的会合点是 store**。
 *
 * 四条设计红线：
 *   1. **不许随机**（用户反复强调）：同一个 `LightingChoice` 必须得到**逐位相同**的
 *      位置/颜色/强度 —— 本模块全是纯函数，没有 `Math.random`、没有时间戳。
 *   2. **不打架**：`Stage3D.tsx:1331` 那个 `lightPreset` effect 在 `stage3dLightingSeq > 0`
 *      之后**不得再覆盖 hemi/dir**（只保留 bg/fog/地面）。守卫让两个 effect 顺序无关、幂等。
 *   3. **单一来源**：方位角→笛卡尔的**全部数学**与色温→RGB **只存在于本文件**，
 *      禁止在 `Stage3D.tsx` 另写一套（否则又回到"两套各写一遍"）。
 *   4. **`apiRef` 零改动**：轮廓灯由本文件用 `WeakMap<THREE.Scene, DirectionalLight[]>` 惰性
 *      持有，**不往 `apiRef` 加第三个字段**（那是冻结区类型，改它风险与收益不成比例）。
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { keyLightAt, rimLightNamed, type LightingChoice } from "./lightingPresets";
import { useCanvasStore } from "./store";

// ── 常量：坐标约定（与 Stage3D.tsx / LightingPanel.tsx 的既有口径逐字对齐）────────────

/** 灯与主体的距离（与既有 `LIGHT_PRESETS[*].dirPos` 的模长同量级：4~11） */
export const LIGHT_RADIUS = 7;
/** 主体高度基准（≈ `Stage3D.tsx:987` 的 `controls.target.y = 0.95`） */
export const SUBJECT_Y = 1.0;

// ── A. 纯函数：球坐标 → 世界坐标 ────────────────────────────────────────────────

/**
 * 「俯视方位角 + 高度角」→ 世界坐标。
 *
 * 坐标约定（**逐条读源核实，不是假设**）：
 *   · 相机在 `(3.05, 2.15, 4.2)`（`Stage3D.tsx:965`）⇒ 在 **+Z 侧**；地面是 XZ 平面、**Y 向上**；
 *   · 角色正面 = **世界 +Z**（`riggedHumanoid` 不变量）；
 *   · 面板方位角 **0° = 镜头方向 = 世界 +Z**，**顺时针**增大（`LightingPanel.tsx:9,28-32`）
 *     ⇒ 90° = **+X**、180° = **−Z**、270° = **−X**。
 *
 * ⚠️ **单位陷阱**：`heightFor()` 返回的是**度**（`lightingPresets.ts:71-85`），
 * 而 `Math.sin/cos` 吃**弧度** ⇒ 这里必须 `* π/180`。这是本刀最易写错处，单测第一条锁它。
 */
export function lightPosition(
  azimuthDeg: number,
  heightDeg: number,
  radius: number = LIGHT_RADIUS,
): [number, number, number] {
  const az = (azimuthDeg * Math.PI) / 180;
  const h = (heightDeg * Math.PI) / 180;
  const horiz = radius * Math.cos(h);
  return [
    horiz * Math.sin(az), // az=90 → +X
    SUBJECT_Y + radius * Math.sin(h),
    horiz * Math.cos(az), // az=0 → +Z（镜头侧）
  ];
}

// ── B. 纯函数：色温 → RGB（Tanner Helland 近似）──────────────────────────────────

function clamp255(x: number): number {
  return Math.max(0, Math.min(255, Math.round(x)));
}

/**
 * 色温 → sRGB（0–255）。Tanner Helland 的分段对数近似：
 * **无查表、无随机、纯算术** ⇒ 可单测、跨机器一致。
 * 定义域外（<1000K / >40000K）先夹紧再算，**绝不抛错**。
 */
export function kelvinToRgb(kelvin: number): [number, number, number] {
  const t = Math.min(40000, Math.max(1000, kelvin)) / 100;
  let r: number;
  let g: number;
  let b: number;
  if (t <= 66) {
    r = 255;
    g = 99.4708025861 * Math.log(t) - 161.1195681661;
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592);
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492);
  }
  if (t >= 66) b = 255;
  else if (t <= 19) b = 0;
  else b = 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  return [clamp255(r), clamp255(g), clamp255(b)];
}

/** 色温 → `#rrggbb`（Three.js `Color.set()` 可直接吃） */
export function kelvinToHex(kelvin: number): string {
  const [r, g, b] = kelvinToRgb(kelvin);
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

// ── C. 纯函数：`LightingChoice` → 3D 灯光快照 ────────────────────────────────────

/** 单盏轮廓灯的摆位与外观 */
export type Stage3dRim = { pos: [number, number, number]; color: string; intensity: number };

/**
 * store 与 Stage3D 之间的**解耦契约**：store 只存这个快照，
 * 不 import `lightingPresets` 的内部结构 ⇒ 两边各自演化互不牵连。
 */
export type Stage3dLightState = {
  dirPos: [number, number, number];
  /** `#rrggbb` */
  dirColor: string;
  dirIntensity: number;
  hemiSky: string;
  hemiIntensity: number;
  /** 轮廓灯：**空数组 = 全关**；长度 1 = 单侧；长度 2 = 双侧 */
  rims: Stage3dRim[];
};

/** 轮廓灯强度（约定值：比主光弱一档，只勾边不夺主） */
export const RIM_INTENSITY = 0.55;

/**
 * 轮廓光名 → 摆位。**结构化读 `azimuth`/`height` 字段，绝不解析中文描述**
 * （`RimLight.from` 是给人看的文案，解析它等于把文案当协议，一改字就崩）。
 *
 * 没有 `azimuth` 的项 = **不点灯**（「无轮廓光」/「环境轮廓」——后者交给 hemi/IBL）。
 */
export function rimLightsFor(rimName: string): Stage3dRim[] {
  const r = rimLightNamed(rimName);
  if (!r || r.azimuth === undefined || r.height === undefined) return [];
  const color = kelvinToHex(DIR_RIM_KELVIN);
  // 「双侧轮廓」用 azimuths 数组给两盏；其余单盏
  const azs = r.azimuths ?? [r.azimuth];
  return azs.map((az) => ({
    pos: lightPosition(az, r.height as number),
    color,
    intensity: RIM_INTENSITY,
  }));
}

/** 轮廓灯色温：略暖于冷白，勾边更有分离感 */
export const DIR_RIM_KELVIN = 4300;

/** 该轮廓光名是否**真的要点灯**（供「双侧」这类需要 2 盏的项判断） */
export function rimLightCount(rimName: string): number {
  const r = rimLightNamed(rimName);
  if (!r || r.azimuth === undefined || r.height === undefined) return 0;
  return (r.azimuths ?? [r.azimuth]).length;
}

/**
 * `LightingChoice` → 3D 灯光快照（**唯一耦合点**，在非冻结文件里）。
 *
 * 映射依据（用户拍板）：**主光 → `dir` / 环境 → `hemi` / 新增轮廓灯**。
 * 注意 `KeyLight.kelvin` 在 `lightingPresets.ts:101` 是「90–270° → 3200K，其余 5600K」，
 * 即侧后位偏暖、正面偏冷 —— 这里原样透传，不二次创作。
 */
export function lightStateFor(choice: LightingChoice): Stage3dLightState {
  const k = keyLightAt(choice.keyAzimuth);
  const azimuth = k?.azimuth ?? choice.keyAzimuth;
  const height = k?.height ?? 30; // 未知方位兜底：略高于眼，不抛错
  const kelvin = k?.kelvin ?? 5600;
  const rims = rimLightsFor(choice.rimName);
  // 环境光：有主光时用同色温的天光，强度随主光强度走（亮主光配亮环境，整体曝光不飘）
  const hemiIntensity = 0.55 + 0.35 * (k?.intensity ?? 0.75);
  return {
    dirPos: lightPosition(azimuth, height),
    dirColor: kelvinToHex(kelvin),
    dirIntensity: k?.intensity ?? 0.75,
    hemiSky: kelvinToHex(kelvin),
    hemiIntensity,
    rims,
  };
}

// ── D. 副作用：把快照落到 three 对象上 ───────────────────────────────────────────

/** `Stage3D` 侧能提供的最小接口（**结构化子集** ⇒ 单测不必构造完整 `apiRef`） */
export type LightingApi = {
  scene: THREE.Scene;
  hemi: THREE.HemisphereLight;
  dir: THREE.DirectionalLight;
};

/**
 * 轮廓灯持有表。**模块级 WeakMap** ⇒ `apiRef` 零改动；
 * scene 被 dispose 后自动回收（重挂载会惰性重建）。
 */
const rimLightStore = new WeakMap<THREE.Scene, THREE.DirectionalLight[]>();

/** 轮廓灯上限（用户已确认「双侧真加 2 盏」⇒ 2 是当前最大需求，留 2 已是满配） */
const RIM_CAPACITY = 2;

function ensureRimLights(scene: THREE.Scene): THREE.DirectionalLight[] {
  let arr = rimLightStore.get(scene);
  if (!arr) {
    arr = Array.from({ length: RIM_CAPACITY }, (_, i) => {
      const l = new THREE.DirectionalLight("#ffffff", 0);
      l.castShadow = false; // 不抢 `dir` 的阴影预算（既有主光才是唯一投影源）
      l.name = `stage3d-rim-light-${i}`;
      scene.add(l);
      return l;
    });
    rimLightStore.set(scene, arr);
  }
  return arr;
}

/**
 * 把快照落到 `hemi` / `dir` / 轮廓灯上。
 *
 * ⚠️ **本函数不碰 `scene.background` / `scene.fog` / 地面** —— 那些归 `lightPreset`
 * 的 effect 管（用户已确认：切 preset 时背景要变、灯不变）。越权就会两处打架。
 *
 * 轮廓灯按下标逐个赋位；快照比容量短时**多出来的关掉**（intensity=0），
 * 而不是留着上一次的残光 —— 这就是「移除灯位不留残灯」的落点。
 */
export function applyLightingToApi(api: LightingApi, state: Stage3dLightState): void {
  api.dir.position.set(state.dirPos[0], state.dirPos[1], state.dirPos[2]);
  api.dir.color.set(state.dirColor);
  api.dir.intensity = state.dirIntensity;
  api.hemi.color.set(state.hemiSky);
  api.hemi.intensity = state.hemiIntensity;

  const lights = ensureRimLights(api.scene);
  for (let i = 0; i < lights.length; i++) {
    const light = lights[i];
    const rim = state.rims[i];
    if (!rim) {
      light.intensity = 0; // 多余的那盏关掉（不留残灯）
      continue;
    }
    light.position.set(rim.pos[0], rim.pos[1], rim.pos[2]);
    light.color.set(rim.color);
    light.intensity = rim.intensity;
  }
}

/**
 * 「移除灯位」时恢复 `lightPreset`：把 hemi/dir 还原成预设值、轮廓灯全关。
 *
 * ⚠️ 必须**在 `Stage3D.tsx` 之外**做这件事的理由：`LIGHT_PRESETS` 是 `Stage3D.tsx` 的
 * 模块私有常量（`:231-286`，未 export）。为了不把它 export 出去（那会给冻结区加新出口），
 * 这里由调用方把预设值**作为参数**传进来（见 `restorePresetLighting`）。
 */
export function killRimLights(scene: THREE.Scene): void {
  const lights = rimLightStore.get(scene);
  if (!lights) return;
  for (const l of lights) l.intensity = 0;
}

/** 恢复预设灯光（由调用方传入 `LIGHT_PRESETS[lightPreset]` 的相关字段） */
export function restorePresetLighting(
  api: LightingApi,
  preset: {
    hemiSky: string;
    hemiGround: string;
    hemiIntensity: number;
    dirColor: string;
    dirIntensity: number;
    dirPos: [number, number, number];
  },
): void {
  api.hemi.color.set(preset.hemiSky);
  api.hemi.groundColor.set(preset.hemiGround);
  api.hemi.intensity = preset.hemiIntensity;
  api.dir.color.set(preset.dirColor);
  api.dir.intensity = preset.dirIntensity;
  api.dir.position.set(preset.dirPos[0], preset.dirPos[1], preset.dirPos[2]);
  killRimLights(api.scene);
}

// ── E. hook：消费「灯位投递」（照抄 useStage3dCast 的正统形态）────────────────────

export type Stage3dLightingDeps = {
  /** `apiRef.current`（首帧为 null） */
  api: LightingApi | null;
  /** 当前灯光预设，用于「移除灯位」时恢复 */
  preset: {
    hemiSky: string;
    hemiGround: string;
    hemiIntensity: number;
    dirColor: string;
    dirIntensity: number;
    dirPos: [number, number, number];
  } | null;
};

/**
 * 消费「灯位投递」请求（每次投递只应用一次）。
 *
 * 依赖数组只放 `seq`：把 deps 收进 ref，否则每次 render 都会因对象新引用重跑 effect
 * —— 这正是 `useStage3dCast` 注释里点名的翻车模式（判据错 ⇒ 每帧重建）。
 *
 * **`api` 首帧为 null 的时序**：`apiRef.current` 要到 `Stage3D.tsx:1115`（`useEffect([])`）
 * 才赋值。但本 hook **只在 `seq` 变化时应用**，而 `seq` 只在用户点灯位时递增
 * ⇒ 那一刻场景必然已初始化。首行 `if (!api || !seq) return;` 是双保险。
 *
 * **`pending === null` 语义**：表示「恢复 lightPreset」（对应面板的「移除灯位」）。
 */
export function useStage3dLighting(deps: Stage3dLightingDeps): void {
  const seq = useCanvasStore((s) => s.stage3dLightingSeq);
  const depsRef = useRef(deps);
  depsRef.current = deps;

  useEffect(() => {
    if (!seq) return;
    const { api, preset } = depsRef.current;
    if (!api) return;
    const st = useCanvasStore.getState();
    const pending = st.pendingStage3dLighting;
    st.consumeStage3dLighting(); // 先消费再应用：即便后续抛错也不会重复应用
    if (pending) applyLightingToApi(api, pending);
    else if (preset) restorePresetLighting(api, preset);
    else killRimLights(api.scene);
  }, [seq]);
}

/** 供调用方复用的类型出口（store 与 Stage3D 都用得着） */
export type { LightingApi as Stage3dLightingApi };
