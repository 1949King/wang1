// Stage3D 姿势自由度（DOF）几何验证 —— 真 GLB + 真变换数学，算关节世界坐标
// ============================================================================
// 背景（2026-10-05 用户反馈「3D 导演台姿势不像正常人」）：只读诊断查出三个根因：
//   ① 四肢 Y 轴（内旋/扭转）被硬编码为 0 ⇒ 肩/髋被砍成 2 自由度 ⇒ 肘弯曲平面锁死；
//   ② GLB 静止态是 **A 字型**（手在体外 0.47），而 lShoulderZ 下限被钳在 -20 ⇒ 手臂永远无法自然下垂；
//   ③ 躯干/头 X 轴符号与 UI 标签相反 ⇒ 「鞠躬」预设（躯干正值）实际表现为**后仰**。
//
// 本脚本用**真实 bodykun.glb + 与 riggedHumanoid.applyPoseToGLBResolved 逐行等价的变换**
// 计算关节世界坐标，用几何不变式验收修复，而不是"看代码猜"。
//
// 坐标约定（实测判定，勿凭直觉改）：**脚趾朝 +Z ⇒ +Z = 人体前方**。
//
// ⚠️ 本文件是 riggedHumanoid.applyBoneDelta / applyPoseToGLBResolved 的**数学副本**。
//    源改公式时必须同步本副本（沿用本项目 mjs 镜像测试约定）。
//
// 运行：node _verify/check_stage3d_pose_dof.mjs
// 打印模式：加 --dump 输出全部测量值
import { readFileSync } from "node:fs";
import { dirname, resolve as pathResolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "../vendor/shiguang-canvas/node_modules/three/build/three.module.js";
import { GLTFLoader } from "../vendor/shiguang-canvas/node_modules/three/examples/jsm/loaders/GLTFLoader.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const GLB = pathResolve(HERE, "../vendor/shiguang-canvas/public/models/bodykun.glb");
const SRC_TS = pathResolve(HERE, "../vendor/packages/libtv/src/stage3dPoseLibrary.ts");
const SRC_RIG = pathResolve(HERE, "../vendor/packages/libtv/src/riggedHumanoid.ts");
const DUMP = process.argv.includes("--dump");

let pass = 0, fail = 0;
function check(name, ok, detail = "") {
  if (ok) { pass++; console.log(`  [OK  ] ${name}`); }
  else { fail++; console.log(`  [FAIL] ${name} ${detail !== "" ? "— " + JSON.stringify(detail) : ""}`); }
}

const deg = (n) => (n * Math.PI) / 180;

// ── 与源逐行等价的变换 ──────────────────────────────────────────────────────
function applyBoneDelta(bone, identity, key, xDeg, yDeg, zDeg, order = "XYZ") {
  if (!bone) return;
  const rest = identity[key];
  if (rest) bone.quaternion.copy(rest); else bone.quaternion.identity();
  if (xDeg === 0 && yDeg === 0 && zDeg === 0) return;
  bone.quaternion.multiply(
    new THREE.Quaternion().setFromEuler(new THREE.Euler(deg(xDeg), deg(yDeg), deg(zDeg), order)),
  );
}

/** 源 applyPoseToGLBResolved 的数学副本（躯干已去 neg；肢体 YXZ） */
function applyPose(bones, identity, p, limbOrder = "YXZ") {
  const A = (b, k, x, y, z, o) => applyBoneDelta(b, identity, k, x, y, z, o);
  const neg = (v) => -v;
  A(bones.abdomen, "abdomen", p.abdomenX, p.abdomenY, p.abdomenZ, "XYZ");
  A(bones.spine2 || bones.spine, bones.spine2 ? "spine2" : "spine", p.spineX, p.spineY, p.spineZ, "XYZ");
  A(bones.neck, "neck", p.headX * 0.5, p.headY * 0.5, p.headZ * 0.5, "XYZ");
  A(bones.head, "head", p.headX * 0.5, p.headY * 0.5, p.headZ * 0.5, "XYZ");

  A(bones.lShoulder, "lShoulder", 0, 0, p.lShoulderZ * 0.35, "XYZ");
  A(bones.lArm, "lArm", neg(p.lShoulderX), p.lShoulderY, p.lShoulderZ, limbOrder);
  A(bones.lForeArm, "lForeArm", p.lElbowX, p.lElbowY, 0, limbOrder);
  A(bones.lWrist, "lWrist", p.lWristX, 0, 0, limbOrder);

  A(bones.rShoulder, "rShoulder", 0, 0, p.rShoulderZ * 0.35, "XYZ");
  A(bones.rArm, "rArm", neg(p.rShoulderX), p.rShoulderY, p.rShoulderZ, limbOrder);
  A(bones.rForeArm, "rForeArm", p.rElbowX, p.rElbowY, 0, limbOrder);
  A(bones.rWrist, "rWrist", p.rWristX, 0, 0, limbOrder);

  A(bones.lHip, "lHip", neg(p.lHipX), p.lHipY, p.lHipZ, limbOrder);
  A(bones.lKnee, "lKnee", p.lKneeX, 0, 0, limbOrder);
  A(bones.lAnkle, "lAnkle", p.lAnkleX, 0, 0, limbOrder);

  A(bones.rHip, "rHip", neg(p.rHipX), p.rHipY, p.rHipZ, limbOrder);
  A(bones.rKnee, "rKnee", p.rKneeX, 0, 0, limbOrder);
  A(bones.rAnkle, "rAnkle", p.rAnkleX, 0, 0, limbOrder);
}

const ZERO = {
  spineX: 0, spineY: 0, spineZ: 0, abdomenX: 0, abdomenY: 0, abdomenZ: 0,
  headX: 0, headY: 0, headZ: 0,
  lShoulderX: 0, lShoulderY: 0, lShoulderZ: 0, lElbowX: 0, lElbowY: 0, lWristX: 0,
  rShoulderX: 0, rShoulderY: 0, rShoulderZ: 0, rElbowX: 0, rElbowY: 0, rWristX: 0,
  lHipX: 0, lHipY: 0, lHipZ: 0, lKneeX: 0, lAnkleX: 0,
  rHipX: 0, rHipY: 0, rHipZ: 0, rKneeX: 0, rAnkleX: 0,
};
const pose = (o) => ({ ...ZERO, ...o });

// 被测预设（与 riggedHumanoid.POSE_PRESETS 数值一致 —— 源改数值须同步此处）
const PRESETS = {
  hands_hips: pose({ lShoulderX: 5, lShoulderY: 50, lShoulderZ: -30, lElbowX: 100, lElbowY: 20,
                     rShoulderX: 5, rShoulderY: -50, rShoulderZ: 30, rElbowX: 100, rElbowY: -20, spineX: 2 }),
  cross_arms: pose({ lShoulderX: -28, lShoulderY: 58, lShoulderZ: 26, lElbowX: 112, lElbowY: 26,
                     rShoulderX: -34, rShoulderY: -62, rShoulderZ: -22, rElbowX: 118, rElbowY: -26,
                     spineX: 3, headX: 2 }),
  hands_behind: pose({ lShoulderX: -20, lShoulderY: 60, lShoulderZ: -20, lElbowX: 70, lElbowY: -20,
                       rShoulderX: -20, rShoulderY: -60, rShoulderZ: 20, rElbowX: 70, rElbowY: 20, spineX: -1 }),
  hold_phone: pose({ rShoulderX: -22, rShoulderY: -34, rShoulderZ: -26, rElbowX: 104, rElbowY: 62,
                     lShoulderY: 10, lElbowX: 6, headX: 14, spineX: 4 }),
  handshake: pose({ rShoulderX: -64, rShoulderY: -22, rShoulderZ: -14, rElbowX: 48, rElbowY: 12,
                    lShoulderY: 10, lElbowX: 6, spineY: -6, headY: 8 }),
  stand_natural: pose({ lShoulderY: 12, lShoulderZ: -48, lElbowX: 8, rShoulderY: -12, rShoulderZ: 48,
                        rElbowX: 8, lHipY: -4, rHipY: 4, spineX: 1, headX: 1 }),
  bow: pose({ abdomenX: 32, spineX: 22, headX: 18, lShoulderX: 8, rShoulderX: 8, lHipX: 8, rHipX: 8 }),
  sad: pose({ spineX: 18, abdomenX: 12, headX: 42, headY: -20, lShoulderX: 12, lShoulderZ: 10,
              rShoulderX: 12, rShoulderZ: -10 }),
};

// ── 载入真实 GLB ───────────────────────────────────────────────────────────
const buf = readFileSync(GLB);
const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
const gltf = await new Promise((res, rej) =>
  new GLTFLoader().parse(ab, "", (g) => res(g), (e) => rej(new Error(String((e && e.message) || e)))));
const scene = gltf.scene;
const byTail = new Map();
scene.traverse((o) => { if (o.isBone) byTail.set(o.name.split("|").pop(), o); });
const pick = (...names) => { for (const n of names) if (byTail.has(n)) return byTail.get(n); return undefined; };

const bones = {
  hips: pick("Hips"), abdomen: pick("Spine"), spine2: pick("Spine2"), neck: pick("Neck"), head: pick("Head"),
  lShoulder: pick("LeftShoulder"), lArm: pick("LeftArm"), lForeArm: pick("LeftForeArm"), lWrist: pick("LeftHand"),
  rShoulder: pick("RightShoulder"), rArm: pick("RightArm"), rForeArm: pick("RightForeArm"), rWrist: pick("RightHand"),
  lHip: pick("LeftUpLeg"), lKnee: pick("LeftLeg"), lAnkle: pick("LeftFoot"),
  rHip: pick("RightUpLeg"), rKnee: pick("RightLeg"), rAnkle: pick("RightFoot"),
};

console.log("=== Stage3D 姿势自由度（DOF）几何验证 ===");
const missing = Object.entries(bones).filter(([, v]) => !v).map(([k]) => k);
check("GLB 骨骼齐备（bodykun.glb 真实骨架）", missing.length === 0, missing);
if (missing.length) { console.log("✗ 骨骼缺失，无法继续"); process.exit(1); }

const identity = {};
for (const [k, v] of Object.entries(bones)) if (v) identity[k] = v.quaternion.clone();
const refresh = () => scene.updateMatrixWorld(true);
const wp = (b) => { const v = new THREE.Vector3(); b.getWorldPosition(v); return v; };

refresh();
const hipsRestY = wp(bones.hips).y;
const S = hipsRestY > 0 ? hipsRestY : 1;   // 归一化：髋高 = 1

function measure(p, limbOrder = "YXZ") {
  for (const [k, v] of Object.entries(bones)) if (v && identity[k]) v.quaternion.copy(identity[k]);
  refresh();
  applyPose(bones, identity, p, limbOrder);
  refresh();
  const n = (v) => v.clone().divideScalar(S);
  return {
    hips: n(wp(bones.hips)), head: n(wp(bones.head)), neck: n(wp(bones.neck)),
    lHand: n(wp(bones.lWrist)), rHand: n(wp(bones.rWrist)),
    lElbow: n(wp(bones.lForeArm)), rElbow: n(wp(bones.rForeArm)),
    lHipJ: n(wp(bones.lHip)), rHipJ: n(wp(bones.rHip)),
    lFoot: n(wp(bones.lAnkle)), rFoot: n(wp(bones.rAnkle)),
  };
}
const dist = (a, b) => a.distanceTo(b);
const fmt = (v) => `(${v.x.toFixed(3)}, ${v.y.toFixed(3)}, ${v.z.toFixed(3)})`;

const rest = measure(pose({}));
const M = {};
for (const [name, p] of Object.entries(PRESETS)) M[name] = measure(p);

if (DUMP) {
  console.log("\n--- dump（归一化世界坐标，髋高=1，+Z=前）---");
  for (const [k, m] of Object.entries({ rest, ...M })) {
    console.log(`${k.padEnd(14)} lHand ${fmt(m.lHand)} rHand ${fmt(m.rHand)} lElbow ${fmt(m.lElbow)} head ${fmt(m.head)}`);
  }
}

// ── ① 源同步：符号与顺序约定必须与源一致（防副本漂移）─────────────────────
const SRC = readFileSync(SRC_TS, "utf-8");
const SRC_RIGGED = readFileSync(SRC_RIG, "utf-8");
check("源已去躯干/头 X 轴 neg（前倾符号修正）",
      /applyBoneDelta\(abdomenBone, identity, "abdomen", p\.abdomenX,/.test(SRC_RIGGED));
check(`源肢体用 YXZ 顺序（源内 ${(SRC_RIGGED.match(/"YXZ"/g) || []).length} 处，≥12）`,
      (SRC_RIGGED.match(/"YXZ"/g) || []).length >= 12);
check("源 lArm / lHip 调用带 YXZ",
      /"lArm",\s*\n?\s*neg\(p\.lShoulderX\), p\.lShoulderY, p\.lShoulderZ, "YXZ"/.test(SRC_RIGGED) &&
      /"lHip", neg\(p\.lHipX\), p\.lHipY, p\.lHipZ, "YXZ"/.test(SRC_RIGGED));
check("源 applyBoneDelta 提供 order 参数（默认 XYZ，肢体传 YXZ）",
      /order: "XYZ" \| "YXZ" = "XYZ",/.test(SRC_RIGGED));
check("riggedHumanoid 保留 re-export（既有导入方零改动）",
      /export \{ JOINT_LABELS, POSE_PRESETS, defaultPose \};/.test(SRC_RIGGED) &&
      /import \{ defaultPose, JOINT_LABELS, POSE_PRESETS \} from "\.\/stage3dPoseLibrary";/.test(SRC_RIGGED));
check("源 JointPose 含 6 个 Y 轴字段", (SRC.match(/^  [lr](Shoulder|Elbow|Hip)Y: number;/gm) || []).length === 6);
check("源肩部 Z 下限已放宽（lShoulderZ min -60 / rShoulderZ max 60）",
      /lShoulderZ", label: "左臂侧举", min: -60/.test(SRC) && /rShoulderZ", label: "右臂侧举", min: -170, max: 60/.test(SRC));

// ── ② 躯干符号：+spineX 必须让头**前移**（+Z）──────────────────────────────
const leanF = measure(pose({ spineX: 30 }));
const leanB = measure(pose({ spineX: -30 }));
check("躯干前倾符号：spineX=+30 → 头前移（Δz>0）",
      leanF.head.z - rest.head.z > 0.05, (leanF.head.z - rest.head.z).toFixed(3));
check("躯干后仰符号：spineX=-30 → 头后移（Δz<0）",
      leanB.head.z - rest.head.z < -0.05, (leanB.head.z - rest.head.z).toFixed(3));

// ── ③ 「鞠躬」外观：头必须前移且下降 ───────────────────────────────────────
const bow = M.bow;
check("鞠躬：头前移（修好「鞠躬变后仰」）", bow.head.z - rest.head.z > 0.1,
      (bow.head.z - rest.head.z).toFixed(3));
check("鞠躬：头下降", rest.head.y - bow.head.y > 0.05, (rest.head.y - bow.head.y).toFixed(3));

// ── ④ 内旋轴生效：Y≠0 必须显著改变手/肘位置 ───────────────────────────────
const noTwist = measure(pose({ lShoulderX: 5, lShoulderZ: -30, lElbowX: 100 }));
const dHand = dist(noTwist.lHand, M.hands_hips.lHand);
check(`内旋轴生效（叉腰手部位移 ${dHand.toFixed(3)} > 0.03）`, dHand > 0.03, dHand.toFixed(4));

// ── ⑤ 叉腰：手落在腰侧 + **肘在身后**（判别性不变式）─────────────────────
const hh = M.hands_hips;
const dHip = dist(hh.lHand, hh.lHipJ);
check(`叉腰：左手落在大腿根附近（距 ${dHip.toFixed(3)} < 0.25）`, dHip < 0.25, dHip.toFixed(4));
check(`叉腰：肘在手的后方（肘z ${hh.lElbow.z.toFixed(3)} < 手z ${hh.lHand.z.toFixed(3)}）`,
      hh.lElbow.z < hh.lHand.z, [hh.lElbow.z.toFixed(3), hh.lHand.z.toFixed(3)]);
check("叉腰：手高于髋、低于肩（在腰际）", hh.lHand.y > hh.hips.y && hh.lHand.y < hh.neck.y,
      [hh.lHand.y.toFixed(3), hh.hips.y.toFixed(3)]);

// ── ⑥ 抱臂：双手抬到胸腹之间、不穿脖子 ─────────────────────────────────────
const ca = M.cross_arms;
check("抱臂：双手高于髋", ca.lHand.y > ca.hips.y && ca.rHand.y > ca.hips.y);
check("抱臂：双手低于颈部（未穿脖子）", ca.lHand.y < ca.neck.y && ca.rHand.y < ca.neck.y,
      [ca.lHand.y.toFixed(3), ca.neck.y.toFixed(3)]);

// ── ⑦ 背手：双手在髋后方（+Z=前 ⇒ 后方 = z 更大）─────────────────────────
const hb = M.hands_behind;
check("背手：双手位于髋后方（z 更大）", hb.lHand.z > hb.hips.z && hb.rHand.z > hb.hips.z,
      [hb.lHand.z.toFixed(3), hb.hips.z.toFixed(3)]);
check("背手：手在臀高附近（|y-髋y| < 0.2）", Math.abs(hb.lHand.y - hb.hips.y) < 0.2,
      Math.abs(hb.lHand.y - hb.hips.y).toFixed(3));

// ── ⑧ 自然站姿：手臂内收贴体（不再 A 字张开）─────────────────────────────
const sn = M.stand_natural;
const dThigh = dist(sn.lHand, sn.lHipJ);
check(`自然站姿：手贴大腿外侧（距大腿根 ${dThigh.toFixed(3)} < 0.15）`, dThigh < 0.15, dThigh.toFixed(4));
check("自然站姿：手横距显著小于静止态",
      Math.abs(sn.lHand.x - sn.hips.x) < Math.abs(rest.lHand.x - rest.hips.x) - 0.2,
      [sn.lHand.x.toFixed(3), rest.lHand.x.toFixed(3)]);

// ── ⑨ 看手机 / 握手：右手抬到髋颈之间、且靠前（+Z）──────────────────────
const hp = M.hold_phone;
check("看手机：右手高于髋且低于头顶", hp.rHand.y > hp.hips.y && hp.rHand.y < hp.head.y,
      [hp.rHand.y.toFixed(3), hp.hips.y.toFixed(3)]);
check("看手机：右手在身体前方（z > 髋z）", hp.rHand.z > hp.hips.z,
      [hp.rHand.z.toFixed(3), hp.hips.z.toFixed(3)]);
const hs = M.handshake;
check("握手：右手前伸且在胸前高度", hs.rHand.z > hs.hips.z + 0.2 && hs.rHand.y > hs.hips.y,
      [hs.rHand.z.toFixed(3), hs.rHand.y.toFixed(3)]);

// ── ⑩ 万向节：侧举扫描连续性，YXZ 不得劣于 XYZ（非回归）─────────────────
function maxStep(order) {
  let prev = null, maxD = 0;
  for (let z = 0; z <= 90; z += 5) {
    const m = measure(pose({ lShoulderZ: z, lShoulderY: 30 }), order);
    if (prev) maxD = Math.max(maxD, dist(prev.lHand, m.lHand));
    prev = m;
  }
  return maxD;
}
const stepXYZ = maxStep("XYZ");
const stepYXZ = maxStep("YXZ");
check(`万向节非回归：YXZ 最大步进 ${stepYXZ.toFixed(4)} ≤ XYZ ${stepXYZ.toFixed(4)}`, stepYXZ <= stepXYZ + 1e-9);

// ── ⑪ 无 IK 时的接地保证：膝/髋为 0 的站立类预设脚不得漂移 ────────────────
check(`站立类预设脚不位移（漂移 ${Math.abs(sn.lFoot.y - rest.lFoot.y).toFixed(4)} < 0.02）`,
      Math.abs(sn.lFoot.y - rest.lFoot.y) < 0.02);

console.log(`\n${fail === 0 ? "OK Stage3D 姿势自由度几何验证全部通过" : "✗ 失败 " + fail + " 项"}（${pass} 项）`);
if (fail > 0) process.exit(1);
