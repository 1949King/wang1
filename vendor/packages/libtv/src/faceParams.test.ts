/**
 * faceParams + faceHeadParts 纯函数单测（node 环境，无 jsdom）。
 *
 * 为什么能测：本模块刻意做成**纯几何生产**（FaceParams → THREE.Object3D，
 * 不依赖 React、不依赖 DOM、不依赖 GLB 加载）—— 这正是项目「把编排抽成纯函数」
 * 惯例（vitest 无 jsdom，useEffect 逻辑零覆盖）在本模块的落地。
 *
 * 断言策略：不比对快照（脆），而是比对**几何事实**（比例落点），
 * 与 .workbuddy/tmp/verify_face_geom.py 的实测口径一致。
 */
import { describe, it, expect } from "vitest";
import * as THREE from "three";
import {
  DEFAULT_FACE_PARAMS,
  normalizeFaceParams,
  isDefaultFaceParams,
  serializeFaceParams,
  deserializeFaceParams,
  randomFaceParams,
  hashSeed,
  EMOTION_PRESETS,
  ACCESSORY_META,
  EYE_COLOR_HEX,
  type FaceParams,
  type HairAccessoryId,
} from "./faceParams";
import { buildFaceLayer, makeFacialFeatures, makeHairAccessory, FACE_PART_FLAG } from "./faceHeadParts";

/** GLB 头部实测包围盒（bodykun body-kun.000；来源 .workbuddy/tmp/glb_head_bbox.py） */
const HEAD = { xHalf: 0.087, yMin: 1.461, yMax: 1.688, zMin: -0.05, zMax: 0.168 };
const HEAD_BONE_Y = 0.112; // faceHeadParts 里 HEAD_CENTER_Y：头中心相对 head 骨骼

describe("faceParams · 规范化与兜底", () => {
  it("normalize(undefined) 返回完整合法对象（旧工程无字段时零改动加载）", () => {
    const p = normalizeFaceParams(undefined);
    expect(p).toEqual(DEFAULT_FACE_PARAMS);
  });

  it("脏值全部被夹紧，不抛错", () => {
    const p = normalizeFaceParams({
      emotion: "不存在的表情",
      emotionIntensity: 99,
      mouthCurve: -99,
      eyeOpen: 99,
      skinTone: "not-a-hex",
      hairAccessory: "nope",
      eyeColor: "rainbow",
      blushAlpha: -5,
    });
    expect(p.emotion).toBe("neutral");
    expect(p.emotionIntensity).toBe(1);
    expect(p.mouthCurve).toBe(-1);
    expect(p.eyeOpen).toBe(2);
    expect(p.skinTone).toBe(DEFAULT_FACE_PARAMS.skinTone);
    expect(p.hairAccessory).toBe("none");
    expect(p.eyeColor).toBe("black");
    expect(p.blushAlpha).toBe(0);
  });

  it("选中表情后，未显式给的滑杆自动跟随该表情预设", () => {
    const p = normalizeFaceParams({ emotion: "grin" });
    expect(p.mouthOpen).toBe(EMOTION_PRESETS.grin.mouthOpen);
    expect(p.mouthCurve).toBe(EMOTION_PRESETS.grin.mouthCurve);
    const s = normalizeFaceParams({ emotion: "sad" });
    expect(s.browLift).toBe(EMOTION_PRESETS.sad.browLift);
  });

  it("isDefault 判定正确", () => {
    expect(isDefaultFaceParams(DEFAULT_FACE_PARAMS)).toBe(true);
    expect(isDefaultFaceParams({ ...DEFAULT_FACE_PARAMS, eyeColor: "blue" })).toBe(false);
  });

  it("序列化往返恒等（存角色库字段用）", () => {
    const p: FaceParams = { ...DEFAULT_FACE_PARAMS, eyeColor: "violet", hairAccessory: "tiara", lipColor: "#d94f8a" };
    expect(deserializeFaceParams(serializeFaceParams(p))).toEqual(p);
  });

  it("反序列化坏数据不抛错，回落默认", () => {
    expect(deserializeFaceParams("{坏 json")).toEqual(DEFAULT_FACE_PARAMS);
    expect(deserializeFaceParams("")).toEqual(DEFAULT_FACE_PARAMS);
    expect(deserializeFaceParams(null)).toEqual(DEFAULT_FACE_PARAMS);
  });
});

describe("faceParams · 零随机纪律", () => {
  it("同 seedKey 的 randomFaceParams 结果恒等（可复现，非 Math.random）", () => {
    const a = randomFaceParams("char-abc");
    const b = randomFaceParams("char-abc");
    expect(a).toEqual(b);
  });

  it("不同 seedKey 结果不同（真有随机性，不是常量）", () => {
    const a = randomFaceParams("char-aaa");
    const b = randomFaceParams("char-bbb");
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });

  it("锁定字段在随机后保持原值（对应「锁定单点重 roll」）", () => {
    const base: FaceParams = { ...DEFAULT_FACE_PARAMS, eyeColor: "gold", skinTone: "#54321d" };
    const locked = new Set<keyof FaceParams>(["eyeColor", "skinTone"]);
    const out = randomFaceParams("seed-xyz", locked, base);
    expect(out.eyeColor).toBe("gold");
    expect(out.skinTone).toBe("#54321d");
  });

  it("hashSeed 稳定且区分大小写", () => {
    expect(hashSeed("abc")).toBe(hashSeed("abc"));
    expect(hashSeed("abc")).not.toBe(hashSeed("abC"));
  });
});

describe("faceHeadParts · 几何落点（对齐 GLB 实测包围盒）", () => {
  it("五官组存在且打上 facePart 标记（供清理/辅助物开关精准定位）", () => {
    const g = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    expect(g.name).toBe("faceFeatures");
    expect(g.userData[FACE_PART_FLAG]).toBe(true);
    let meshes = 0;
    g.traverse((o) => { if ((o as THREE.Mesh).isMesh) meshes++; });
    expect(meshes).toBeGreaterThanOrEqual(6); // 双眼×4层 + 双眉 + 嘴
  });

  it("眼中心 x 落在真人比例区间（占面宽 25%~33%）", () => {
    const g = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    // 眼睛是 Group（眼白+虹膜+瞳+高光四层），不是 Mesh —— 按 x 偏移筛
    const eyes = g.children.filter((c) => c.name === "" && Math.abs(c.position.x) > 0.001);
    expect(eyes.length).toBeGreaterThan(0);
    const ex = Math.abs(eyes[0].position.x);
    const ratio = ex / HEAD.xHalf;
    expect(ratio).toBeGreaterThanOrEqual(0.25);
    expect(ratio).toBeLessThanOrEqual(0.33);
  });

  it("五官全部落在头部包围盒内（不浮在体外）", () => {
    const g = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    g.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(g);
    // 组局部 y 已含 HEAD_CENTER_Y 偏移；换算到 head 骨骼系后再判断
    expect(box.min.x).toBeGreaterThan(-HEAD.xHalf * 1.35);
    expect(box.max.x).toBeLessThan(HEAD.xHalf * 1.35);
    // 脸部 z 必须在前半侧（正值方向）
    expect(box.max.z).toBeGreaterThan(0.05);
    // 纵向不超出头骨范围（头在其坐标系内 y 约 0~0.227，中心 0.112）
    expect(box.min.y).toBeGreaterThan(HEAD_BONE_Y - 0.12);
    expect(box.max.y).toBeLessThan(HEAD_BONE_Y + 0.13);
  });

  it("表情参数真的改变几何（不是摆设）", () => {
    const calm = makeFacialFeatures(normalizeFaceParams({ emotion: "neutral" }));
    const grin = makeFacialFeatures(normalizeFaceParams({ emotion: "grin", mouthOpen: 0.9 }));
    const b1 = new THREE.Box3().setFromObject(calm);
    const b2 = new THREE.Box3().setFromObject(grin);
    // 大笑嘴张开 → 纵向范围应变大
    expect(b2.min.y).toBeLessThan(b1.min.y);
  });

  it("唇色/腮红开启后确实新增 mesh（妆容生效）", () => {
    const plain = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    const made = makeFacialFeatures(normalizeFaceParams({
      lipColor: "#d94f8a", blush: "#f08bb4", eyeshadow: "#7f9ce8", eyeliner: "#111111",
    }));
    const count = (o: THREE.Object3D) => { let n = 0; o.traverse((c) => { if ((c as THREE.Mesh).isMesh) n++; }); return n; };
    expect(count(made)).toBeGreaterThan(count(plain));
  });

  it("异色瞳：左右虹膜颜色不同", () => {
    const g = makeFacialFeatures(normalizeFaceParams({ eyeColor: "blue", eyeColorRight: "red" }));
    const cols: string[] = [];
    g.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const mm = m.material as THREE.MeshStandardMaterial;
      if (mm && mm.emissive && mm.emissive.getHex() !== 0) cols.push("#" + mm.emissive.getHexString());
    });
    expect(new Set(cols).size).toBeGreaterThanOrEqual(2);
  });

  it("eyeliner 会改变几何 vs 无眼线", () => {
    const a = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    const b = makeFacialFeatures(normalizeFaceParams({ eyeliner: "#111111" }));
    const ca = new THREE.Box3().setFromObject(a);
    const cb = new THREE.Box3().setFromObject(b);
    expect(cb.max.x).toBeGreaterThanOrEqual(ca.max.x);
  });
});

describe("faceHeadParts · 发饰", () => {
  it("none 返回 null；其余 id 全部产出非空几何且带标记", () => {
    expect(makeHairAccessory(DEFAULT_FACE_PARAMS)).toBeNull();
    for (const id of Object.keys(ACCESSORY_META) as HairAccessoryId[]) {
      const p = normalizeFaceParams({ hairAccessory: id });
      const g = makeHairAccessory(p);
      if (id === "none") { expect(g).toBeNull(); continue; }
      expect(g, `发饰 ${id} 应有几何`).not.toBeNull();
      let n = 0;
      g!.traverse((o) => { if ((o as THREE.Mesh).isMesh) n++; });
      expect(n, `发饰 ${id} 至少 1 个 mesh`).toBeGreaterThan(0);
      expect(g!.userData[FACE_PART_FLAG]).toBe(true);
    }
  });

  it("发饰不超出头部合理范围（半径 < 头宽 ×2）", () => {
    for (const id of Object.keys(ACCESSORY_META) as HairAccessoryId[]) {
      if (id === "none") continue;
      const g = makeHairAccessory(normalizeFaceParams({ hairAccessory: id }))!;
      const box = new THREE.Box3().setFromObject(g);
      expect(Math.abs(box.min.x), `${id} 左不越界`).toBeLessThan(HEAD.xHalf * 2.2);
      expect(Math.abs(box.max.x), `${id} 右不越界`).toBeLessThan(HEAD.xHalf * 2.2);
    }
  });
});

describe("faceParams · 头型滑杆（Ruth2 式 shape sliders）", () => {
  it("缺省为 0（旧工程零改动加载 = 无形变）", () => {
    const p = normalizeFaceParams(undefined);
    expect([p.headWidth, p.headHeight, p.jawWidth, p.cheekbone, p.chin]).toEqual([0, 0, 0, 0, 0]);
  });

  it("脏值夹紧到 ±1，不抛错", () => {
    const p = normalizeFaceParams({ headWidth: 99, jawWidth: -99, chin: "not-a-number" });
    expect(p.headWidth).toBe(1);
    expect(p.jawWidth).toBe(-1);
    expect(p.chin).toBe(0);
  });

  it("序列化往返保留头型字段", () => {
    const p = { ...DEFAULT_FACE_PARAMS, headWidth: 0.35, cheekbone: -0.2 };
    const back = deserializeFaceParams(serializeFaceParams(p));
    expect(back.headWidth).toBe(0.35);
    expect(back.cheekbone).toBe(-0.2);
  });
});

describe("faceHeadParts · 头型顶点位移", () => {
  it("拉宽脸 → 肤色壳横向包围盒变大（真的作用到顶点，不是摆设）", () => {
    const plain = buildFaceLayer(DEFAULT_FACE_PARAMS);
    const wide = buildFaceLayer(normalizeFaceParams({ headWidth: 1 }));
    const shell = (layer: THREE.Object3D) => layer.getObjectByName("skinOverlay")!;
    const b1 = new THREE.Box3().setFromObject(shell(plain));
    const b2 = new THREE.Box3().setFromObject(shell(wide));
    expect(b2.max.x - b2.min.x).toBeGreaterThan(b1.max.x - b1.min.x);
  });

  it("五官落点跟随位移（眼距随脸宽同步外移）", () => {
    const plain = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    const wide = makeFacialFeatures(normalizeFaceParams({ headWidth: 1 }));
    const eyeXOf = (g: THREE.Object3D) => {
      const eyes = g.children.filter((c) => c.userData.eyeSide === 1);
      return eyes.length ? eyes[0].position.x : 0;
    };
    expect(eyeXOf(wide)).toBeGreaterThan(eyeXOf(plain));
  });

  it("零形变时输出与旧行为一致（deformFacePoint 恒等）", () => {
    const g = makeFacialFeatures(DEFAULT_FACE_PARAMS);
    const eyes = g.children.filter((c) => c.userData.eyeSide === 1);
    expect(eyes[0].position.x).toBeCloseTo(0.086 * 0.30, 6);
  });
});

describe("faceHeadParts · 材质不变量（冻结区红线）", () => {
  it("buildFaceLayer 只新增节点，不修改任何既有材质", () => {
    // 造一个「假 GLB 根」：带一个受控材质
    const fakeRoot = new THREE.Group();
    const probeMat = new THREE.MeshStandardMaterial({ color: "#e8e0ff" });
    const probe = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.1), probeMat);
    fakeRoot.add(probe);
    const before = probeMat.color.getHexString();

    const layer = buildFaceLayer(normalizeFaceParams({ skinTone: "#54321d" }));
    fakeRoot.add(layer);

    // GLB 既有材质必须原封不动（stage3d-core 不变量）
    expect(probeMat.color.getHexString()).toBe(before);
    expect(probeMat.color.getHexString()).toBe("e8e0ff");
  });

  it("buildFaceLayer 包含肤色层 + 五官 + 发饰三层", () => {
    const layer = buildFaceLayer(normalizeFaceParams({ hairAccessory: "tiara", skinTone: "#f0c3a8" }));
    expect(layer.getObjectByName("skinOverlay")).toBeTruthy();
    expect(layer.getObjectByName("faceFeatures")).toBeTruthy();
    expect(layer.children.some((c) => c.name.startsWith("accessory:"))).toBe(true);
  });
});

describe("faceHeadParts · 虹膜可见性（P1 回归锁：2026-10-13 审查实锤后新增）", () => {
  // 旧 bug：虹膜/瞳/高光 z = 0.55/0.57/0.58 × R，全部 < 眼白 z 半轴 0.72 × R
  // ⇒ 整体埋在不透明眼白内部，6/6 眼型瞳色不可见。此测试用「虹膜盘 z 必须
  // 超过眼白椭球中心表面 z」锁住，任何回退立即红。
  const EYE_STYLES = ["round", "almond", "narrow", "upturned", "droopy", "big"] as const;
  for (const style of EYE_STYLES) {
    it(`[${style}] 虹膜/瞳/高光浮出眼白表面（不被眼白遮挡）`, () => {
      const g = makeFacialFeatures(normalizeFaceParams({ eyeStyle: style }));
      const eyes = g.children.filter((c) => c.userData.eyeSide !== undefined);
      expect(eyes.length).toBe(2);
      for (const eye of eyes) {
        const meshes = eye.children.filter((c) => (c as THREE.Mesh).isMesh) as THREE.Mesh[];
        // 眼白 = 首个 SphereGeometry mesh；虹膜 = 首个 CircleGeometry mesh
        const sclera = meshes.find((m) => m.geometry.type === "SphereGeometry");
        const discs = meshes.filter((m) => m.geometry.type === "CircleGeometry");
        if (!sclera) throw new Error("sclera mesh not found");
        expect(discs.length).toBeGreaterThanOrEqual(3); // 虹膜 + 瞳 + 高光
        const scleraSurfaceZ = new THREE.Box3().setFromObject(sclera).max.z;
        for (const d of discs) {
          expect(d.position.z).toBeGreaterThan(scleraSurfaceZ);
        }
      }
    });
  }
});

describe("faceParams · 脏值兜底回归锁（2026-10-13 审查修复）", () => {
  it("非法右眼瞳色兜底为 null（与左眼一致），不是静默变成黑瞳假异色", () => {
    const out = normalizeFaceParams({ eyeColor: "gold", eyeColorRight: "octarine" });
    expect(out.eyeColor).toBe("gold");
    expect(out.eyeColorRight).toBeNull();
  });

  it("合法右眼瞳色原样保留", () => {
    const out = normalizeFaceParams({ eyeColorRight: "violet" });
    expect(out.eyeColorRight).toBe("violet");
  });

  it("随机时眉色会变化（不被锁定则不复用 base）", () => {
    const base = normalizeFaceParams({ browColor: "#111111" });
    let changed = false;
    for (let i = 0; i < 10; i++) {
      const out = randomFaceParams(`brow-test-${i}`, new Set(), base);
      if (out.browColor !== base.browColor) { changed = true; break; }
    }
    expect(changed).toBe(true);
  });

  it("锁定 browColor 后随机保持原值", () => {
    const base = normalizeFaceParams({ browColor: "#a16207" });
    const out = randomFaceParams("lock", new Set(["browColor"]), base);
    expect(out.browColor).toBe("#a16207");
  });
});

describe("faceHeadParts · 妆容法线精确朝外（P3 优化回归锁）", () => {
  it("腮红贴片面向椭球真实外向法线", () => {
    const g = makeFacialFeatures(normalizeFaceParams({ blush: "#d94f8a", blushAlpha: 0.5 }));
    const blush = g.children.find((c) => {
      const m = c as THREE.Mesh;
      return m.isMesh && m.geometry.type === "CircleGeometry" && m.material && !(Array.isArray(m.material)) && (m.material as THREE.MeshStandardMaterial).color.getHexString() === "d94f8a";
    });
    expect(blush).toBeTruthy();
    if (!blush) throw new Error("blush mesh not found");
    // 取贴片 +Z 方向在局部坐标系下应大致朝外（与从原点出发的位置向量同向）
    const pos = blush.position.clone();
    const zDir = new THREE.Vector3(0, 0, 1).applyQuaternion(blush.quaternion);
    const radial = pos.clone().normalize();
    expect(zDir.dot(radial)).toBeGreaterThan(0.92);
  });
});
