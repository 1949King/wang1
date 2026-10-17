/**
 * stage3dLighting.test.ts — 24 位灯位 → 3D 导演台灯光可视化单测（2026-10-12）。
 *
 * 覆盖四类东西：
 *   A. **纯函数** —— 方位角/高度角 → 世界坐标的**符号与量级**（抄反 sin/cos 是最易犯的错），
 *      色温 → RGB 的冷暖方向与单调性，`lightStateFor` 的端到端映射，以及**确定性**。
 *   B. **副作用** —— `applyLightingToApi` 真跑在 three 对象上：位置精确、轮廓灯**不重复创建**、
 *      空 rims 全关、**不越权碰** `scene.background`/`fog`。
 *   C. **源级接线守卫** —— 三类编译器抓不到、运行期不报错的缺陷：
 *      ① `useStage3dLighting()` 被放到 `const apiRef` 之前 ⇒ TDZ ReferenceError（一渲染就崩）；
 *      ② `consume` 被挪到 `apply` **之后** ⇒ 若 apply 抛错会**重复应用**（违反"先消费"纪律）；
 *      ③ `Stage3D.tsx:1331` 的 `lightPreset` effect 少了 `seq === 0` 守卫
 *         ⇒ 两个 effect 抢改 hemi/dir，谁后跑谁赢（**顺序相关**，随机漂移）。
 *   D. **反例验证** —— 见 `_verify` 与 CHANGELOG（本刀 7 条反例逐条喂破坏版本，确认守卫会红）。
 *
 * 源文件用 Vite 的 `?raw` 导入（而不是 `node:fs`）：本包没装 `@types/node`，
 * 用 node 内建模块会直接给 tsc 添新错误、破坏"零新增"的棘轮基线。参考先例：`stage3dCast.test.ts`。
 */
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import stage3dSource from "./Stage3D.tsx?raw";
import panelSource from "./LightingPanel.tsx?raw";
import storeSource from "./store.ts?raw";
import lightingSource from "./stage3dLighting.ts?raw";
import { RIM_LIGHTS } from "./lightingPresets";
import {
  LIGHT_RADIUS,
  SUBJECT_Y,
  RIM_INTENSITY,
  applyLightingToApi,
  kelvinToHex,
  kelvinToRgb,
  killRimLights,
  lightPosition,
  lightStateFor,
  restorePresetLighting,
  rimLightCount,
  rimLightsFor,
  type LightingApi,
  type Stage3dLightState,
} from "./stage3dLighting";

// ------------------------------------------------------------- A. 纯函数：坐标

describe("lightPosition（球坐标 → 世界坐标）", () => {
  it("0° / 0° ⇒ 落在 +Z（镜头侧）、x≈0、y≈主体高度", () => {
    const [x, y, z] = lightPosition(0, 0);
    expect(x).toBeCloseTo(0, 6);
    expect(z).toBeCloseTo(LIGHT_RADIUS, 6); // z 最大
    expect(y).toBeCloseTo(SUBJECT_Y, 6);
  });

  it("90° ⇒ +X（sin 管 X / cos 管 Z，抄反即报红）", () => {
    const [x, , z] = lightPosition(90, 20);
    expect(x).toBeGreaterThan(0);
    expect(z).toBeCloseTo(0, 6);
  });

  it("180° ⇒ −Z；270° ⇒ −X", () => {
    const [x180, , z180] = lightPosition(180, 15);
    expect(z180).toBeLessThan(0);
    expect(x180).toBeCloseTo(0, 6);

    const [x270, , z270] = lightPosition(270, 20);
    expect(x270).toBeLessThan(0);
    expect(z270).toBeCloseTo(0, 6);
  });

  it("高度 90° ⇒ 正上方：y≈SUBJECT_Y+R，水平分量≈0", () => {
    const [x, y, z] = lightPosition(0, 90);
    expect(y).toBeCloseTo(SUBJECT_Y + LIGHT_RADIUS, 6);
    expect(Math.hypot(x, z)).toBeCloseTo(0, 6);
  });

  it("负高度 ⇒ 低于主体（底补轮廓用）", () => {
    const [, y] = lightPosition(0, -60);
    expect(y).toBeLessThan(SUBJECT_Y);
  });

  it("水平半径恒 = R·cos(h)（与方位角无关）", () => {
    for (let az = 0; az < 360; az += 15) {
      const [x, , z] = lightPosition(az, 30);
      expect(Math.hypot(x, z)).toBeCloseTo(LIGHT_RADIUS * Math.cos((30 * Math.PI) / 180), 6);
    }
  });

  it("确定性：同输入连算 200 次逐位相同", () => {
    const first = lightPosition(45, 45);
    for (let i = 0; i < 200; i++) expect(lightPosition(45, 45)).toEqual(first);
  });
});

// --------------------------------------------------------- A. 纯函数：色温 → RGB

describe("kelvinToRgb（Tanner Helland 近似）", () => {
  it("3200K 暖 ⇒ r>g>b；5600K 中性偏冷 ⇒ b 抬起来", () => {
    const warm = kelvinToRgb(3200);
    expect(warm[0]).toBeGreaterThan(warm[1]); // r > g
    expect(warm[1]).toBeGreaterThan(warm[2]); // g > b

    const cool = kelvinToRgb(5600);
    expect(cool[2]).toBeGreaterThan(warm[2]); // 冷白蓝分更高
  });

  it("低色温比高色温更红（单调方向）", () => {
    expect(kelvinToRgb(2000)[0]).toBeGreaterThan(kelvinToRgb(10000)[0]);
  });

  it("通道全部落在 0–255 合法区间", () => {
    for (const k of [1000, 2000, 3200, 4300, 5600, 6500, 10000, 20000, 40000]) {
      for (const v of kelvinToRgb(k)) {
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(255);
        expect(Number.isInteger(v)).toBe(true);
      }
    }
  });

  it("定义域外不抛错（先夹紧再算）", () => {
    expect(() => kelvinToRgb(500)).not.toThrow();
    expect(() => kelvinToRgb(99999)).not.toThrow();
    expect(() => kelvinToRgb(0)).not.toThrow();
    expect(() => kelvinToRgb(-100)).not.toThrow();
  });

  it("确定性：同输入连算 200 次相同", () => {
    const first = kelvinToRgb(4300).join(",");
    for (let i = 0; i < 200; i++) expect(kelvinToRgb(4300).join(",")).toBe(first);
  });
});

describe("kelvinToHex", () => {
  it("是合法的 #rrggbb", () => {
    for (const k of [1000, 3200, 5600, 40000]) {
      expect(kelvinToHex(k)).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("与 kelvinToRgb 一致", () => {
    const [r, g, b] = kelvinToRgb(3200);
    const hex = kelvinToHex(3200);
    expect(hex).toBe(`#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`);
  });
});

// ------------------------------------------------------- A. 纯函数：快照映射

describe("rimLightsFor / rimLightCount", () => {
  it("「无轮廓光」「环境轮廓」= 不点灯（空数组）", () => {
    expect(rimLightsFor("无轮廓光")).toEqual([]);
    expect(rimLightsFor("环境轮廓")).toEqual([]);
    expect(rimLightCount("无轮廓光")).toBe(0);
    expect(rimLightCount("环境轮廓")).toBe(0);
  });

  it("「双侧轮廓」= 真给 2 盏（用户已确认，不是 1 盏取巧）", () => {
    expect(rimLightCount("双侧轮廓")).toBe(2);
    const rims = rimLightsFor("双侧轮廓");
    expect(rims).toHaveLength(2);
    // 左右各 120°/240° ⇒ x 一正一负
    expect(Math.sign(rims[0].pos[0])).toBe(1);
    expect(Math.sign(rims[1].pos[0])).toBe(-1);
  });

  it("单盏档位给 1 盏，且强度取约定值", () => {
    for (const name of ["后上 30° 轮廓", "后上 45° 轮廓", "正后 180° 轮廓", "顶轮廓", "底补轮廓"]) {
      const rims = rimLightsFor(name);
      expect(rims).toHaveLength(1);
      expect(rims[0].intensity).toBe(RIM_INTENSITY);
    }
  });

  it("未知名不抛错、不点灯", () => {
    expect(rimLightsFor("不存在的轮廓")).toEqual([]);
    expect(rimLightCount("不存在的轮廓")).toBe(0);
  });

  it("★ 每个『要点灯』的轮廓档都必须有结构化 azimuth/height（缺了会静默不亮）", () => {
    // 这条锁住：9 档里除「无轮廓光」「环境轮廓」外，其余都必须给了方位
    for (const r of RIM_LIGHTS) {
      const shouldLight = r.name !== "无轮廓光" && r.name !== "环境轮廓";
      if (shouldLight) {
        expect(r.azimuth, `${r.name} 缺 azimuth`).toBeTypeOf("number");
        expect(r.height, `${r.name} 缺 height`).toBeTypeOf("number");
      }
    }
  });
});

describe("lightStateFor（端到端映射）", () => {
  it("45° 伦勃朗：主光在前右上（+X/+Z）、轮廓 1 盏", () => {
    const st = lightStateFor({ keyAzimuth: 45, rimName: "后上 45° 轮廓" });
    expect(st.dirPos[0]).toBeGreaterThan(0); // +X
    expect(st.dirPos[2]).toBeGreaterThan(0); // +Z（前）
    expect(st.rims).toHaveLength(1);
  });

  it("主光色温口径与 lightingPresets 一致：侧后位（90–270°）3200K，正面 5600K", () => {
    expect(lightStateFor({ keyAzimuth: 90, rimName: "无轮廓光" }).dirColor).toBe(kelvinToHex(3200));
    expect(lightStateFor({ keyAzimuth: 180, rimName: "无轮廓光" }).dirColor).toBe(kelvinToHex(3200));
    expect(lightStateFor({ keyAzimuth: 0, rimName: "无轮廓光" }).dirColor).toBe(kelvinToHex(5600));
    expect(lightStateFor({ keyAzimuth: 45, rimName: "无轮廓光" }).dirColor).toBe(kelvinToHex(5600));
  });

  it("「无轮廓光」⇒ rims 空数组", () => {
    expect(lightStateFor({ keyAzimuth: 45, rimName: "无轮廓光" }).rims).toEqual([]);
  });

  it("「双侧轮廓」⇒ rims 2 盏", () => {
    expect(lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }).rims).toHaveLength(2);
  });

  it("未知方位兜底：不抛错、给出合法快照", () => {
    const st = lightStateFor({ keyAzimuth: 999, rimName: "无轮廓光" });
    expect(st.dirPos.every((v) => Number.isFinite(v))).toBe(true);
    expect(st.dirIntensity).toBeGreaterThan(0);
    expect(st.hemiIntensity).toBeGreaterThan(0);
  });

  it("★ 确定性：同一 choice 连算 200 次快照逐位相同（拒绝随机）", () => {
    const c = { keyAzimuth: 135, rimName: "双侧轮廓" };
    const first = JSON.stringify(lightStateFor(c));
    for (let i = 0; i < 200; i++) expect(JSON.stringify(lightStateFor(c))).toBe(first);
  });

  it("24 个主光位全部能生成合法快照", () => {
    for (let az = 0; az < 360; az += 15) {
      const st = lightStateFor({ keyAzimuth: az, rimName: "后上 45° 轮廓" });
      expect(st.dirPos.every((v) => Number.isFinite(v))).toBe(true);
      expect(st.dirColor).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});

// --------------------------------------------------------------- B. 副作用

function makeApi(): LightingApi {
  const scene = new THREE.Scene();
  const hemi = new THREE.HemisphereLight();
  const dir = new THREE.DirectionalLight();
  return { scene, hemi, dir };
}

function rimLightsIn(api: LightingApi): THREE.DirectionalLight[] {
  return api.scene.children.filter(
    (o): o is THREE.DirectionalLight => o instanceof THREE.DirectionalLight,
  );
}

describe("applyLightingToApi（副作用）", () => {
  it("dir 的位置/颜色/强度与快照逐位一致", () => {
    const api = makeApi();
    const st: Stage3dLightState = {
      dirPos: [1, 2, 3],
      dirColor: "#ff8800",
      dirIntensity: 1.2,
      hemiSky: "#223344",
      hemiIntensity: 0.7,
      rims: [],
    };
    applyLightingToApi(api, st);
    expect(api.dir.position.toArray()).toEqual([1, 2, 3]);
    expect(api.dir.color.getHexString()).toBe("ff8800");
    expect(api.dir.intensity).toBe(1.2);
    expect(api.hemi.color.getHexString()).toBe("223344");
    expect(api.hemi.intensity).toBe(0.7);
  });

  it("轮廓灯惰性创建，且 2 盏封顶（连调 3 次不重复创建）", () => {
    const api = makeApi();
    const before = rimLightsIn(api).length;
    for (let i = 0; i < 3; i++) {
      applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }));
    }
    const rims = rimLightsIn(api);
    expect(rims.length).toBe(before + 2); // 只建 2 盏，第 2/3 次复用
    expect(rims.map((l) => l.name)).toEqual(["stage3d-rim-light-0", "stage3d-rim-light-1"]);
  });

  it("轮廓灯 castShadow=false（不抢主光阴影预算）", () => {
    const api = makeApi();
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }));
    for (const l of rimLightsIn(api)) expect(l.castShadow).toBe(false);
  });

  it("rims 空 ⇒ 全部轮廓灯关闭（不留残灯）", () => {
    const api = makeApi();
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }));
    expect(rimLightsIn(api).every((l) => l.intensity > 0)).toBe(true);

    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "无轮廓光" }));
    expect(rimLightsIn(api).every((l) => l.intensity === 0)).toBe(true);
  });

  it("从双侧（2 盏）降到单盏 ⇒ 多余那盏被关掉", () => {
    const api = makeApi();
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }));
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "后上 45° 轮廓" }));
    const lights = rimLightsIn(api);
    expect(lights[0].intensity).toBeGreaterThan(0);
    expect(lights[1].intensity).toBe(0);
  });

  it("★ 不越权：绝不改 scene.background / scene.fog（那归 lightPreset 管）", () => {
    const api = makeApi();
    const bg = new THREE.Color("#123456");
    const fog = new THREE.Fog("#123456", 18, 42);
    api.scene.background = bg;
    api.scene.fog = fog;
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 90, rimName: "双侧轮廓" }));
    expect(api.scene.background).toBe(bg); // 同一个对象，没被换掉
    expect(api.scene.fog).toBe(fog);
    expect((api.scene.background as THREE.Color).getHexString()).toBe("123456");
  });
});

describe("killRimLights / restorePresetLighting", () => {
  it("killRimLights 把已有轮廓灯全关", () => {
    const api = makeApi();
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }));
    killRimLights(api.scene);
    expect(rimLightsIn(api).every((l) => l.intensity === 0)).toBe(true);
  });

  it("killRimLights 对没有轮廓灯的场景不抛错（幂等）", () => {
    const api = makeApi();
    expect(() => killRimLights(api.scene)).not.toThrow();
  });

  it("restorePresetLighting 把 hemi/dir 还原成预设值且关掉轮廓灯", () => {
    const api = makeApi();
    applyLightingToApi(api, lightStateFor({ keyAzimuth: 45, rimName: "双侧轮廓" }));
    restorePresetLighting(api, {
      hemiSky: "#dbeaff",
      hemiGround: "#334455",
      hemiIntensity: 1.0,
      dirColor: "#ffffff",
      dirIntensity: 0.7,
      dirPos: [2, 6, 4],
    });
    expect(api.hemi.color.getHexString()).toBe("dbeaff");
    expect(api.hemi.groundColor.getHexString()).toBe("334455");
    expect(api.hemi.intensity).toBe(1.0);
    expect(api.dir.color.getHexString()).toBe("ffffff");
    expect(api.dir.intensity).toBe(0.7);
    expect(api.dir.position.toArray()).toEqual([2, 6, 4]);
    expect(rimLightsIn(api).every((l) => l.intensity === 0)).toBe(true);
  });
});

// --------------------------------------------------------- C. 源级接线守卫

describe("接线守卫（源级）", () => {
  it("Stage3D 真的 import 并调用了消费端", () => {
    expect(stage3dSource).toContain('from "./stage3dLighting"');
    expect(stage3dSource).toContain("useStage3dLighting(");
  });

  it("useStage3dLighting 必须在 const apiRef 之后调用（否则 TDZ，一渲染就 ReferenceError）", () => {
    const call = stage3dSource.indexOf("useStage3dLighting(");
    const def = stage3dSource.indexOf("const apiRef = useRef");
    expect(def).toBeGreaterThan(-1);
    expect(call).toBeGreaterThan(def);
  });

  it("★ Stage3D 的 lightPreset effect 必须带 stage3dLightingSeq === 0 守卫", () => {
    // 没有守卫 ⇒ seq>0 后 preset 仍会覆盖 hemi/dir ⇒ 两个 effect 抢改、谁后跑谁赢。
    expect(stage3dSource).toContain("stage3dLightingSeq === 0");
    expect(stage3dSource).toMatch(/lightPreset, groundPreset, stage3dLightingSeq/);
  });

  it("LightingPanel 真的投递灯位快照（不只是写提示词）", () => {
    expect(panelSource).toContain("requestStage3dLighting(");
    expect(panelSource).toContain("lightStateFor(");
  });

  it("LightingPanel 界面明写「示意」（不对用户撒谎说是出图预览）", () => {
    expect(panelSource).toContain("示意");
  });

  it("「移除灯位」也投递 null（恢复 lightPreset），不留残灯", () => {
    expect(panelSource).toMatch(/requestStage3dLighting\(\s*null\s*\)/);
  });

  it("store 三个通道字段都已声明并初始化", () => {
    for (const key of ["stage3dLightingSeq", "pendingStage3dLighting", "consumeStage3dLighting"]) {
      expect(storeSource).toContain(key);
    }
    expect(storeSource).toMatch(/stage3dLightingSeq:\s*0/);
    expect(storeSource).toMatch(/pendingStage3dLighting:\s*null/);
  });

  it("★ consume 必须在 apply 之前（若 apply 抛错，脏 pending 会导致重复应用）", () => {
    const fnAt = lightingSource.indexOf("export function useStage3dLighting");
    expect(fnAt).toBeGreaterThan(-1);
    const consumeAt = lightingSource.indexOf("consumeStage3dLighting()", fnAt);
    const applyAt = lightingSource.indexOf("applyLightingToApi(", fnAt);
    expect(consumeAt).toBeGreaterThan(-1);
    expect(applyAt).toBeGreaterThan(-1);
    expect(consumeAt).toBeLessThan(applyAt); // 先消费再应用
  });

  it("★ hook 首行必须有 `!api` 守卫（apiRef 首帧为 null）", () => {
    expect(lightingSource).toMatch(/if\s*\(\s*!api/);
  });

  it("Stage3D 的导入行紧跟既有 stage3dCast 导入（同族通道挨着放，便于审查）", () => {
    const castImport = stage3dSource.indexOf('from "./stage3dCast"');
    const lightImport = stage3dSource.indexOf('from "./stage3dLighting"');
    expect(castImport).toBeGreaterThan(-1);
    expect(lightImport).toBeGreaterThan(castImport);
  });
});
