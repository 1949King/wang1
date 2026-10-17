/**
 * 捏脸几何层：把 FaceParams「长成」可挂在 head 骨骼上的 THREE 对象。
 *
 * 为什么必须独立成文件（而非写进 riggedHumanoid.ts）：
 *  1. riggedHumanoid.ts 已 3159/3189 行，体积守卫余量只剩 30 行 ⇒ 新逻辑一律另开文件。
 *  2. 本模块是**纯几何生产**（输入 FaceParams → 输出 THREE.Object3D），可被独立单测；
 *     riggedHumanoid 只留「1 行调用」，符合项目的「单一真源 + 薄委托」惯例。
 *
 * 三条硬约束（来源：GLB 实测 + 项目既有约定）：
 *  - **GLB 素体无五官、无 morpheye/face 骨骼**（只有 Head/Neck）⇒ 表情/五官只能靠程序化附件贴上去。
 *  - **GLB 只有一个 default 材质、无贴图**（baseColor ≈ #e8e0ff）⇒ 妆容靠「材质色 + 附件色块」实现，
 *    改色不会破坏任何贴图（也正因无贴图，无法做真实唇纹/眼影纹理 —— 这是 80-90 分档的价位）。
 *  - **零随机**：所有形态由 FaceParams 确定性推导，同参数恒等输出。
 */
import * as THREE from "three";
import type { FaceParams } from "./faceParams";
import { EYE_COLOR_HEX, blendEmotion } from "./faceParams";

/**
 * 头部几何参考尺寸。
 *
 * 实测来源（.workbuddy/tmp/glb_head_bbox.py 直接读 GLB accessor min/max）：
 *   bodykun 头 mesh = `body-kun.000`，包围盒 x±0.087 / y 1.461~1.688 / z -0.05~0.168
 *   bodychan 头 mesh = `Mesh.018`，     包围盒 x±0.085 / y 1.479~1.695 / z -0.061~0.147
 *   ⇒ 头宽（面宽）≈ 0.085~0.087，头高 ≈ 0.216~0.227，面法线 +Z，头中心 y ≈ 1.574
 *   ⇒ 挂到 head 骨骼后以「头中心」为原点，故下面用面宽半径 R 做比例基准。
 *
 * ⚠️ 不要沿用胶囊头的 skullW=0.22（那是被隐藏的几何素模，见 riggedHumanoid:1592）；
 *    GLB 头比胶囊头小一半，用错会让五官浮在体外。
 */
const HEAD_R = 0.086;
/** 头 mesh 在父节点(Head 骨骼)下的中心 y 偏移：头中心 1.574 − Head 骨骼 1.462 ≈ +0.112 */
const HEAD_CENTER_Y = 0.112;
/**
 * 肤色壳三轴半径 = 实测 GLB 头 bbox 半轴（x 0.087 / y 0.1135 / z 0.109）外扩 1.2%。
 * P0 修复：此前壳是 (R, R*1.06, R*0.98) ≈ (0.087, 0.092, 0.085)，比真实头 mesh 还小一圈，
 * 挂到 GLB 头上会被不透明头部整个深度遮挡 ⇒ 肤色层实际不可见。
 */
const SKIN_RX = HEAD_R * 1.012; // ≈0.087
const SKIN_RY = HEAD_R * 1.335; // ≈0.115
const SKIN_RZ = HEAD_R * 1.29;  // ≈0.111
/**
 * 眼中心 x 占面宽比例。
 * 实测校准：真人两眼中心间距 ≈ 面宽的 25~30%（单眼中心距中线 ≈ 12.5~15%）。
 * 初版取 0.42 实测会做出「外星人脸」（眼距占面宽 42%），故下调到 0.30。
 */
const EYE_X_RATIO = 0.30;

/**
 * 椭球面 z（头中心局部系，+Z 为正面）：把附件沿面部曲面贴合排布，
 * 避免平面排布在两侧浮空（P1）。margin 让附件略微凸出皮肤表面。
 */
function faceZ(x: number, y: number, margin = 0.0015): number {
  const k = 1 - (x * x) / (SKIN_RX * SKIN_RX) - (y * y) / (SKIN_RY * SKIN_RY);
  return k <= 0 ? SKIN_RZ + margin : SKIN_RZ * Math.sqrt(k) + margin;
}

/**
 * 椭球在点 (x,y,z) 处的**精确外向法线**（用于腮红/眼影/面纹朝向）。
 * 椭球方程 x²/a² + y²/b² + z²/c² = 1 的梯度即法线；归一化后更稳。
 */
function faceNormal(x: number, y: number, z: number): THREE.Vector3 {
  const n = new THREE.Vector3(
    x / (SKIN_RX * SKIN_RX),
    y / (SKIN_RY * SKIN_RY),
    z / (SKIN_RZ * SKIN_RZ),
  ).normalize();
  if (n.lengthSq() < 1e-12) n.set(0, 0, 1);
  return n;
}

/** 头型滑杆是否全为零（零 = 无形变，走快路径不碰顶点） */
export function hasShapeDeform(p: FaceParams): boolean {
  return !!(p.headWidth || p.headHeight || p.jawWidth || p.cheekbone || p.chin);
}

/**
 * Ruth2 式 shape sliders：头型位移场（头中心局部系，米制）。
 * 肤色壳顶点与五官附件落点**共用同一函数** ⇒ 拉宽脸时眼睛跟着走，不脱节。
 * 分区权重设计：
 *  - headWidth/headHeight：全头均匀横/纵缩放
 *  - jawWidth：仅下半脸（ny<0），越往下越强 → 下颌宽窄
 *  - cheekbone：面中两侧（|ny|≈0.05、|nx|>0.5）横推 + 前隆
 *  - chin：下极（ny<-0.55）纵向拉伸 + 前端前突
 */
export function deformFacePoint(x: number, y: number, z: number, p: FaceParams): [number, number, number] {
  if (!hasShapeDeform(p)) return [x, y, z];
  const nx = x / SKIN_RX;
  const ny = y / SKIN_RY;
  let sx = 1 + 0.16 * p.headWidth;
  let sy = 1 + 0.13 * p.headHeight;
  // 下颌：只作用下半脸
  sx *= 1 + 0.14 * p.jawWidth * Math.max(0, -ny);
  let dx = 0;
  let dz = 0;
  // 颧骨：面中两侧隆起
  if (p.cheekbone) {
    const cw = Math.max(0, 1 - Math.abs(ny + 0.05) / 0.35) * Math.min(1, Math.abs(nx) / 0.5);
    dx += HEAD_R * 0.10 * p.cheekbone * cw * (nx >= 0 ? 1 : -1);
    dz += HEAD_R * 0.06 * p.cheekbone * cw * Math.max(0, z / SKIN_RZ);
  }
  // 下巴：纵向拉伸 + 前突
  if (p.chin) {
    sy *= 1 + 0.10 * p.chin * Math.max(0, -ny);
    const chinW = Math.max(0, -ny - 0.55) / 0.45;
    dz += HEAD_R * 0.10 * p.chin * chinW * Math.max(0, z / SKIN_RZ);
  }
  return [x * sx + dx, y * sy, z * sx + dz];
}

/** 把位移场应用到已定标的 BufferGeometry（肤色壳用；同步重算法线保证光照正确） */
function applyShapeDeform(geo: THREE.BufferGeometry, p: FaceParams): void {
  if (!hasShapeDeform(p)) return;
  const pos = geo.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < pos.count; i++) {
    const [x, y, z] = deformFacePoint(pos.getX(i), pos.getY(i), pos.getZ(i), p);
    pos.setXYZ(i, x, y, z);
  }
  pos.needsUpdate = true;
  geo.computeVertexNormals();
}
/** 附件统一打标：便于 setHelpersVisible / 主题切换 / 清理时精准定位（只动自己加的东西） */
export const FACE_PART_FLAG = "facePart";

function mark<T extends THREE.Object3D>(o: T): T {
  o.userData[FACE_PART_FLAG] = true;
  o.traverse((ch) => { ch.userData[FACE_PART_FLAG] = true; });
  return o;
}

function mat(color: string, opts?: { rough?: number; metal?: number; emissive?: string; opacity?: number; side?: THREE.Side }) {
  const m = new THREE.MeshStandardMaterial({
    color,
    roughness: opts?.rough ?? 0.55,
    metalness: opts?.metal ?? 0.05,
    flatShading: false,
  });
  if (opts?.emissive) { m.emissive = new THREE.Color(opts.emissive); m.emissiveIntensity = 0.25; }
  if (opts?.opacity !== undefined && opts.opacity < 1) {
    m.transparent = true;
    m.opacity = opts.opacity;
    m.depthWrite = false;
  }
  if (opts?.side !== undefined) m.side = opts.side;
  return m;
}

/* ──────────────────────────── 五官 ──────────────────────────── */

/** 眼睛：眼白椭球 + 虹膜盘 + 瞳孔 + 高光（四层，避免「黑豆眼」） */
function makeEye(side: -1 | 1, p: FaceParams): THREE.Group {
  const g = new THREE.Group();
  const style = p.eyeStyle;
  // 眼型 → (半宽, 半高)，单位为 HEAD_R 的比例。
  // 真人校准：单眼宽 ≈ 面宽 20%（半宽 = HEAD_R*0.19），眼高 ≈ 面宽 10~12%（整睑高度）
  const shape = {
    round:    { w: 0.155, h: 0.185 },
    almond:   { w: 0.185, h: 0.140 },
    narrow:   { w: 0.195, h: 0.095 },
    upturned: { w: 0.185, h: 0.132 },
    droopy:   { w: 0.185, h: 0.132 },
    big:      { w: 0.215, h: 0.205 },
    // A 类扩展（2026-10-13）
    cat:      { w: 0.190, h: 0.120 },
    sleepy:   { w: 0.180, h: 0.080 },
  }[style];

  // 眼白
  const scleraGeo = new THREE.SphereGeometry(HEAD_R * shape.w, 20, 14);
  scleraGeo.scale(1.0, Math.max(0.06, shape.h / shape.w), 0.72);
  const sclera = new THREE.Mesh(scleraGeo, mat("#fbfaf8", { rough: 0.3 }));
  g.add(sclera);

  // 虹膜（异色瞳：右眼独立取色）
  const isRight = side === 1;
  const colId = isRight && p.eyeColorRight ? p.eyeColorRight : p.eyeColor;
  // P1 修复（2026-10-13 审查实锤）：旧值 0.55/0.57/0.58 全部 < 眼白 z 半轴 0.72
  // ⇒ 虹膜/瞳孔/高光整体埋在不透明眼白内部，6/6 眼型全不可见（真 three Box3 验证）。
  // 提到 0.74/0.76/0.78，全部浮出表面（0.72 中心 + 边缘曲率 0.64 之上），读作角膜凸起。
  const iris = new THREE.Mesh(
    new THREE.CircleGeometry(HEAD_R * shape.w * 0.46, 20),
    mat(EYE_COLOR_HEX[colId] ?? "#111111", { rough: 0.25, emissive: EYE_COLOR_HEX[colId] }),
  );
  iris.position.z = HEAD_R * shape.w * 0.74;
  g.add(iris);
  // 瞳（居中小黑圆，让虹膜有层次）
  const pupil = new THREE.Mesh(new THREE.CircleGeometry(HEAD_R * shape.w * 0.2, 16), mat("#050505", { rough: 0.2 }));
  pupil.position.z = HEAD_R * shape.w * 0.76;
  g.add(pupil);
  // 高光
  const spec = new THREE.Mesh(new THREE.CircleGeometry(HEAD_R * shape.w * 0.1, 10), mat("#ffffff", { rough: 0.1 }));
  spec.position.set(-HEAD_R * shape.w * 0.16, HEAD_R * shape.w * 0.18, HEAD_R * shape.w * 0.78);
  g.add(spec);

  // P1：眼开合用整组纵向缩放（虹膜/瞳/高光随眼白一起收缩，不会戳出半闭的眼眶）
  g.scale.y = Math.max(0.08, Math.min(2, p.eyeOpen));
  // 供预览眨眼动画定位眼组 + 记录基准开合（不靠 name，避免破坏既有测试的 children 筛选）
  g.userData.eyeSide = side;
  g.userData.baseOpenScale = g.scale.y;
  // 眼型微调：上挑/下垂 = 整体绕 z 微旋；猫眼下勾；困倦更垂
  if (style === "upturned") g.rotation.z = side * 0.16;
  if (style === "droopy") g.rotation.z = -side * 0.14;
  if (style === "cat") g.rotation.z = side * 0.22;
  if (style === "sleepy") g.rotation.z = -side * 0.10;
  return g;
}

/** 眉：一段弯曲的薄盒（用 TubeGeometry 沿二次曲线，比盒更像眉） */
function makeBrow(side: -1 | 1, p: FaceParams): THREE.Group {
  const g = new THREE.Group();
  const style = p.browStyle;
  const cfg = {
    flat:  { len: 0.24, thick: 0.024, arch: 0.02, tilt: 0.00 },
    arch:  { len: 0.25, thick: 0.024, arch: 0.07, tilt: 0.00 },
    angry: { len: 0.24, thick: 0.028, arch: 0.01, tilt: -0.22 },
    sad:   { len: 0.24, thick: 0.024, arch: 0.03, tilt: 0.20 },
    thin:  { len: 0.24, thick: 0.014, arch: 0.03, tilt: 0.00 },
    thick: { len: 0.25, thick: 0.038, arch: 0.03, tilt: 0.00 },
    // A 类扩展
    round: { len: 0.22, thick: 0.026, arch: 0.04, tilt: 0.00 },
    short: { len: 0.18, thick: 0.024, arch: 0.02, tilt: 0.00 },
  }[style];
  const L = HEAD_R * cfg.len;
  // 二次曲线：内端(靠鼻) → 弓顶 → 外端
  const lift = cfg.arch * HEAD_R + p.browLift * HEAD_R * 0.32;
  const curve = new THREE.QuadraticBezierCurve3(
    new THREE.Vector3(-L / 2, 0, 0),
    new THREE.Vector3(0, lift, 0),
    new THREE.Vector3(L / 2, -lift * 0.35, 0),
  );
  const tube = new THREE.Mesh(
    new THREE.TubeGeometry(curve, 14, HEAD_R * cfg.thick, 7, false),
    // P1：眉色跟随 browColor（卡片可联动发色），默认深棕
    mat(p.browColor ?? "#2b1a12", { rough: 0.75 }),
  );
  g.add(tube);
  g.rotation.z = side * cfg.tilt * -1;
  return g;
}

/** 嘴：上下唇两片椭球（P1：替代方盒，消除硬边），按 mouthCurve / mouthOpen / lipStyle 驱动 */
function makeMouth(p: FaceParams): THREE.Group {
  const g = new THREE.Group();
  // 真人校准：嘴宽 ≈ 面宽的 30~35%（= HEAD_R 的 0.60~0.70），初版 0.26 只到 13%，过小
  const cfg = {
    thin:    { w: 0.56, h: 0.036 },
    plump:   { w: 0.58, h: 0.066 },
    wide:    { w: 0.70, h: 0.044 },
    small:   { w: 0.44, h: 0.042 },
    cupid:   { w: 0.56, h: 0.056 },
    neutral: { w: 0.60, h: 0.046 },
    // A 类扩展
    pouty:   { w: 0.52, h: 0.070 },
    sharp:   { w: 0.55, h: 0.038 },
  }[p.lipStyle];
  const W = HEAD_R * cfg.w;
  const H = HEAD_R * cfg.h;
  const open = p.mouthOpen * HEAD_R * 0.16;
  const lipCol = p.lipColor ?? "#b8726b";
  const lipOpacity = p.lipColor ? p.lipAlpha : 1.0;

  // 上唇：椭球片（cupid 唇加中央双峰）
  const upper = new THREE.Mesh(
    new THREE.SphereGeometry(1, 18, 12),
    mat(lipCol, { rough: 0.35, opacity: lipOpacity }),
  );
  upper.scale.set(W / 2, H * 0.55 / 2, H * 0.6 / 2);
  upper.position.y = H * 0.45 + open / 2;
  upper.rotation.z = p.mouthCurve * -0.16;
  g.add(upper);
  if (p.lipStyle === "cupid") {
    // 唇珠双峰（cupid's bow 的识别度来源）
    for (const side of [-1, 1] as const) {
      const bump = new THREE.Mesh(new THREE.SphereGeometry(H * 0.3, 10, 8), mat(lipCol, { rough: 0.35, opacity: lipOpacity }));
      bump.position.set(side * W * 0.12, H * 0.55 + open / 2, H * 0.18);
      g.add(bump);
    }
  }
  // 下唇（更饱满，嘴角弧度更大）
  const lower = new THREE.Mesh(
    new THREE.SphereGeometry(1, 18, 12),
    mat(lipCol, { rough: 0.35, opacity: lipOpacity }),
  );
  lower.scale.set(W * 0.92 / 2, H * 0.62 / 2, H * 0.6 / 2);
  lower.position.y = -H * 0.35 - open / 2;
  lower.rotation.z = p.mouthCurve * 0.22;
  g.add(lower);

  // 张嘴时露出口腔暗面（避免「两片唇悬空」）
  if (open > HEAD_R * 0.012) {
    const cavity = new THREE.Mesh(
      new THREE.CircleGeometry(W * 0.42, 14),
      mat("#2a0f12", { rough: 0.9 }),
    );
    cavity.scale.set(1.0, Math.min(0.55, open / (W * 0.42)), 1.0);
    g.add(cavity);
  }
  return g;
}

/** 鼻：GLB 素体有鼻梁，这里只补一个可选的鼻头高光（避免抢戏，默认极淡） */
function makeNoseTip(): THREE.Mesh {
  const n = new THREE.Mesh(
    new THREE.SphereGeometry(HEAD_R * 0.036, 12, 8),
    mat("#c88a63", { rough: 0.6, opacity: 0.35 }),
  );
  n.name = "noseTip";
  return n;
}

/**
 * 生成完整五官组（挂在 head 骨骼下）。
 * 坐标约定与项目一致：局部 **+Z 为正面**、+Y 为上（见 riggedHumanoid `root.userData.frontAxis = "+z"`）。
 * P1：所有附件按 faceZ() 沿椭球面排布（含两侧眼/眉/腮红），不再平面贴附导致浮空。
 */
export function makeFacialFeatures(raw: FaceParams): THREE.Group {
  // emotionIntensity 的唯一消费点：表情滑杆 0~1 混合「平静 ↔ 当前表情」
  const p = blendEmotion(raw);
  const g = new THREE.Group();
  g.name = "faceFeatures";
  // 整个五官组整体抬到「头中心」（head 骨骼原点在颈根，头中心在其上方）
  g.position.y = HEAD_CENTER_Y;

  const eyeY = HEAD_R * 0.22;
  const eyeX = HEAD_R * EYE_X_RATIO;

  // 头型滑杆：附件落点过同一位移场（拉宽脸时五官跟着走，与肤色壳不脱节）
  const place = (o: THREE.Object3D, x: number, y: number, z: number) => {
    const [dx, dy, dz] = deformFacePoint(x, y, z, p);
    o.position.set(dx, dy, dz);
  };

  const eyeL = makeEye(-1, p);
  place(eyeL, -eyeX, eyeY, faceZ(-eyeX, eyeY));
  const eyeR = makeEye(1, p);
  place(eyeR, eyeX, eyeY, faceZ(eyeX, eyeY));
  g.add(eyeL, eyeR);

  // 妆容：眼线（沿眼眶上缘的细管；曲线左右对称，两侧同几何平移，不做负缩放镜像）
  if (p.eyeliner) {
    for (const side of [-1, 1] as const) {
      const ln = new THREE.Mesh(
        new THREE.TubeGeometry(
          new THREE.QuadraticBezierCurve3(
            new THREE.Vector3(-HEAD_R * 0.18, 0, 0),
            new THREE.Vector3(0, HEAD_R * 0.045, 0),
            new THREE.Vector3(HEAD_R * 0.18, 0, 0),
          ), 12, HEAD_R * 0.010, 6, false),
        mat(p.eyeliner, { rough: 0.4 }),
      );
      const lx = side * eyeX;
      const ly = eyeY + HEAD_R * 0.115;
      place(ln, lx, ly, faceZ(lx, ly, 0.004));
      g.add(ln);
    }
  }

  // 妆容：眼影（眼睑上方的淡色薄壳片，贴合曲面）
  if (p.eyeshadow) {
    for (const side of [-1, 1] as const) {
      const sh = new THREE.Mesh(
        new THREE.SphereGeometry(HEAD_R * 0.155, 16, 10),
        mat(p.eyeshadow, { rough: 0.7, opacity: p.eyeshadowAlpha, side: THREE.DoubleSide }),
      );
      sh.scale.set(1.0, 0.5, 0.35);
      const sx = side * eyeX;
      const sy = eyeY + HEAD_R * 0.145;
      place(sh, sx, sy, faceZ(sx, sy, -0.004));
      g.add(sh);
    }
  }

  // 妆容：腮红（两面颊色块，贴椭球面 + 法线朝向，避免平面圆盘边缘悬空）
  if (p.blush) {
    for (const side of [-1, 1] as const) {
      const bl = new THREE.Mesh(
        new THREE.CircleGeometry(HEAD_R * 0.13, 18),
        mat(p.blush, { rough: 0.85, opacity: p.blushAlpha, side: THREE.DoubleSide }),
      );
      const bx = side * HEAD_R * 0.5;
      const by = -HEAD_R * 0.12;
      place(bl, bx, by, faceZ(bx, by, 0.001));
      // P3 优化（2026-10-13）：用椭球真实法线朝向，取代启发式 lookAt(position*4,...)。
      const nBl = faceNormal(bl.position.x, bl.position.y, bl.position.z);
      bl.lookAt(bl.position.clone().add(nBl));
      g.add(bl);
    }
  }

  const browL = makeBrow(-1, p);
  const browY = eyeY + HEAD_R * 0.36;
  place(browL, -eyeX, browY, faceZ(-eyeX, browY, 0.002));
  const browR = makeBrow(1, p);
  place(browR, eyeX, browY, faceZ(eyeX, browY, 0.002));
  g.add(browL, browR);

  const mouth = makeMouth(p);
  const mouthY = -HEAD_R * 0.55;
  place(mouth, 0, mouthY, faceZ(0, mouthY, 0.002));
  g.add(mouth);

  const nose = makeNoseTip();
  const noseY = -HEAD_R * 0.2;
  place(nose, 0, noseY, faceZ(0, noseY, HEAD_R * 0.05));
  g.add(nose);

  // 面部纹饰（额饰以外的花纹，如面部刺青点）
  if (p.faceMark) {
    const mk = new THREE.Mesh(
      new THREE.CircleGeometry(HEAD_R * 0.08, 12),
      mat(p.faceMark, { rough: 0.5, opacity: 0.85, side: THREE.DoubleSide }),
    );
    const mx = HEAD_R * 0.34;
    const my = -HEAD_R * 0.02;
      place(mk, mx, my, faceZ(mx, my, 0.001));
      // P3 优化（2026-10-13）：真实椭球法线朝向。
      const nMk = faceNormal(mk.position.x, mk.position.y, mk.position.z);
      mk.lookAt(mk.position.clone().add(nMk));
      g.add(mk);
  }

  return mark(g);
}

/* ──────────────────────────── 发饰 ──────────────────────────── */

/**
 * 发饰几何（挂 head 骨骼，不参与关节）。全部由基础几何拼装，
 * 与既有 `makeHair` 同手法（riggedHumanoid.ts:1233），保证风格统一。
 */
export function makeHairAccessory(p: FaceParams): THREE.Group | null {
  const id = p.hairAccessory;
  if (id === "none") return null;
  const g = new THREE.Group();
  g.name = `accessory:${id}`;
  const c1 = p.accessoryColor;
  const c2 = p.accessoryColor2;
  const R = HEAD_R;
  const metal = { rough: 0.28, metal: 0.72 };
  const cloth = { rough: 0.72, metal: 0.02 };

  // 注意：top 以「头中心」为基准（head 骨骼原点在颈根，头中心在其上方 HEAD_CENTER_Y 处），
  // 组整体在 return 前统一抬到 HEAD_CENTER_Y，否则发饰会掉到鼻子高度横穿脸部。
  const top = R * 1.02;
  switch (id) {
    case "hairpin": {
      const pin = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.018, R * 0.018, R * 0.9, 8), mat(c1, metal));
      pin.rotation.z = Math.PI / 2.3;
      pin.position.set(-R * 0.35, top + R * 0.1, -R * 0.15);
      const bead = new THREE.Mesh(new THREE.SphereGeometry(R * 0.055, 12, 10), mat(c1, { ...metal, emissive: c1 }));
      bead.position.set(-R * 0.78, top + R * 0.32, -R * 0.15);
      g.add(pin, bead);
      break;
    }
    case "hairpin_dual": {
      for (const side of [-1, 1] as const) {
        const pin = new THREE.Mesh(new THREE.CylinderGeometry(R * 0.016, R * 0.016, R * 0.8, 8), mat(c1, metal));
        pin.rotation.z = Math.PI / 2.4;
        pin.position.set(side * R * 0.38, top + R * 0.08, -R * 0.12);
        const bead = new THREE.Mesh(new THREE.SphereGeometry(R * 0.048, 12, 10), mat(c1, { ...metal, emissive: c1 }));
        bead.position.set(side * R * 0.76, top + R * 0.28, -R * 0.12);
        g.add(pin, bead);
      }
      break;
    }
    case "ribbon": {
      // 蝴蝶结：中心结 + 两片翼
      const knot = new THREE.Mesh(new THREE.SphereGeometry(R * 0.06, 12, 10), mat(c1, cloth));
      knot.position.set(0, top + R * 0.1, -R * 0.3);
      g.add(knot);
      for (const side of [-1, 1] as const) {
        const wing = new THREE.Mesh(new THREE.SphereGeometry(R * 0.16, 14, 10), mat(c1, cloth));
        wing.scale.set(1.3, 0.75, 0.4);
        wing.position.set(side * R * 0.26, top + R * 0.12, -R * 0.3);
        wing.rotation.z = side * 0.35;
        g.add(wing);
      }
      // 缎带主体（绕头一圈）
      const band = new THREE.Mesh(new THREE.TorusGeometry(R * 0.92, R * 0.035, 8, 28), mat(c1, cloth));
      band.rotation.x = Math.PI / 2;
      band.position.y = top - R * 0.28;
      g.add(band);
      break;
    }
    case "ribbon_tail": {
      const band = new THREE.Mesh(new THREE.TorusGeometry(R * 0.95, R * 0.032, 8, 28), mat(c1, cloth));
      band.rotation.x = Math.PI / 2;
      band.position.y = top - R * 0.2;
      g.add(band);
      // 两条飘带（BoxGeometry 细长，向后垂下）
      for (const side of [-1, 1] as const) {
        const tail = new THREE.Mesh(new THREE.BoxGeometry(R * 0.16, R * 1.5, R * 0.04), mat(c2, cloth));
        tail.position.set(side * R * 0.5, top - R * 1.1, -R * 0.75);
        tail.rotation.x = -0.22;
        tail.rotation.z = side * 0.12;
        g.add(tail);
      }
      break;
    }
    case "tiara": {
      const base = new THREE.Mesh(new THREE.TorusGeometry(R * 0.86, R * 0.028, 8, 30, Math.PI), mat(c1, metal));
      base.rotation.set(-Math.PI / 2.35, 0, 0);
      base.position.set(0, top - R * 0.05, R * 0.12);
      g.add(base);
      // 三峰 + 宝石（中峰最高）
      for (const [i, xt] of [[-1, -0.45], [0, 0], [1, 0.45]] as [number, number][]) {
        const spike = new THREE.Mesh(new THREE.ConeGeometry(R * 0.06, R * 0.22, 6), mat(c1, metal));
        const h = i !== 0 ? R * 0.18 : 0;
        spike.position.set(xt * R, top + R * 0.02 + h, R * 0.1);
        g.add(spike);
        const gem = new THREE.Mesh(new THREE.OctahedronGeometry(R * 0.045, 0), mat(c2, { rough: 0.15, metal: 0.4, emissive: c2 }));
        gem.position.set(xt * R, top + R * 0.12 + h, R * 0.1);
        g.add(gem);
      }
      break;
    }
    case "flower": {
      // 花钿：五瓣 + 花心（用内层组定位，避免占用 g.position —— 外层要统一抬到 HEAD_CENTER_Y）
      const fl = new THREE.Group();
      for (let i = 0; i < 5; i++) {
        const a = (i / 5) * Math.PI * 2;
        const petal = new THREE.Mesh(new THREE.SphereGeometry(R * 0.075, 12, 10), mat(c1, cloth));
        petal.scale.set(1.0, 0.45, 0.5);
        petal.position.set(Math.cos(a) * R * 0.14, 0, Math.sin(a) * R * 0.14);
        fl.add(petal);
      }
      const core = new THREE.Mesh(new THREE.SphereGeometry(R * 0.05, 12, 10), mat(c2, { rough: 0.3, emissive: c2 }));
      fl.add(core);
      fl.position.set(R * 0.5, top - R * 0.18, -R * 0.2);
      g.add(fl);
      break;
    }
    case "earring": {
      for (const side of [-1, 1] as const) {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(R * 0.09, R * 0.02, 8, 18), mat(c1, metal));
        ring.position.set(side * R * 1.02, -R * 0.22, R * 0.05);
        ring.rotation.y = Math.PI / 2;
        const drop = new THREE.Mesh(new THREE.SphereGeometry(R * 0.05, 12, 10), mat(c1, { rough: 0.25, metal: 0.5 }));
        drop.position.set(side * R * 1.02, -R * 0.44, R * 0.05);
        g.add(ring, drop);
      }
      break;
    }
    case "forehead_mark": {
      const base = new THREE.Mesh(new THREE.TorusGeometry(R * 0.5, R * 0.02, 8, 24, Math.PI * 1.2), mat(c1, metal));
      base.position.set(0, top - R * 0.5, R * 0.5);
      base.rotation.set(0.5, 0, Math.PI * 0.9);
      g.add(base);
      const gem = new THREE.Mesh(new THREE.OctahedronGeometry(R * 0.06, 0), mat(c2, { rough: 0.12, metal: 0.5, emissive: c2 }));
      gem.position.set(0, top - R * 0.5, R * 0.56);
      gem.scale.set(1.0, 1.6, 0.6);
      g.add(gem);
      break;
    }
    case "veil": {
      const veil = new THREE.Mesh(
        new THREE.SphereGeometry(R * 1.5, 20, 14, 0, Math.PI * 2, Math.PI * 0.42, Math.PI * 0.42),
        mat(c1, { rough: 0.9, opacity: 0.42, side: THREE.DoubleSide }),
      );
      veil.position.set(0, top - R * 0.5, -R * 0.1);
      g.add(veil);
      const rim = new THREE.Mesh(new THREE.TorusGeometry(R * 1.05, R * 0.026, 8, 30), mat(c2, metal));
      rim.rotation.x = Math.PI / 2.15;
      rim.position.set(0, top - R * 0.32, 0);
      g.add(rim);
      break;
    }
    case "horns": {
      for (const side of [-1, 1] as const) {
        const horn = new THREE.Mesh(new THREE.ConeGeometry(R * 0.14, R * 0.62, 8), mat(c1, { rough: 0.4, metal: 0.15 }));
        horn.position.set(side * R * 0.55, top - R * 0.02, -R * 0.18);
        horn.rotation.z = side * -0.42;
        horn.rotation.x = -0.22;
        const tip = new THREE.Mesh(new THREE.SphereGeometry(R * 0.05, 10, 8), mat(c2, { rough: 0.3, emissive: c2 }));
        tip.position.set(side * R * 0.72, top + R * 0.44, -R * 0.3);
        g.add(horn, tip);
      }
      break;
    }
    // A 类扩展（2026-10-13）：轻量发饰
    case "glasses": {
      // 镜框：两个圆环 + 鼻梁桥
      for (const side of [-1, 1] as const) {
        const rim = new THREE.Mesh(new THREE.TorusGeometry(R * 0.17, R * 0.012, 6, 18), mat(c1, metal));
        rim.position.set(side * R * 0.22, top - R * 0.44, R * 0.44);
        g.add(rim);
      }
      const bridge = new THREE.Mesh(new THREE.BoxGeometry(R * 0.18, R * 0.018, R * 0.01), mat(c1, metal));
      bridge.position.set(0, top - R * 0.44, R * 0.44);
      g.add(bridge);
      const legL = new THREE.Mesh(new THREE.BoxGeometry(R * 0.012, R * 0.01, R * 0.45), mat(c1, metal));
      legL.position.set(-R * 0.39, top - R * 0.44, R * 0.22);
      legL.rotation.y = -0.18;
      const legR = new THREE.Mesh(new THREE.BoxGeometry(R * 0.012, R * 0.01, R * 0.45), mat(c1, metal));
      legR.position.set(R * 0.39, top - R * 0.44, R * 0.22);
      legR.rotation.y = 0.18;
      g.add(legL, legR);
      break;
    }
    case "flower_crown": {
      // 花冠：绕头顶一圈的小花
      const N = 7;
      for (let i = 0; i < N; i++) {
        const a = (i / N) * Math.PI * 2;
        const fl = new THREE.Group();
        for (let j = 0; j < 5; j++) {
          const fa = (j / 5) * Math.PI * 2;
          const petal = new THREE.Mesh(new THREE.SphereGeometry(R * 0.06, 10, 8), mat(c1, cloth));
          petal.scale.set(1.0, 0.4, 0.5);
          petal.position.set(Math.cos(fa) * R * 0.1, 0, Math.sin(fa) * R * 0.1);
          fl.add(petal);
        }
        const core = new THREE.Mesh(new THREE.SphereGeometry(R * 0.035, 8, 6), mat(c2, { rough: 0.3, emissive: c2 }));
        fl.add(core);
        fl.position.set(Math.cos(a) * R * 0.66, top - R * 0.08, Math.sin(a) * R * 0.45);
        fl.lookAt(0, top, 0);
        g.add(fl);
      }
      break;
    }
    default:
      return null;
  }
  // 统一抬到「头中心」基准（与 skinOverlay / faceFeatures 同一坐标系，P0 修复：
  // 此前发饰相对 head 骨骼原点=颈根计算，冠冕/发带会掉到鼻子高度横穿脸）
  g.position.y = HEAD_CENTER_Y;
  return mark(g);
}

/* ────────────────────── 肤色层（独立通道，不动 GLB 材质） ────────────────────── */

/**
 * 素体原始色（GLB default 材质 baseColor ≈ #e8e0ff）—— 用于「素颜还原」判定。
 * 注意：本模块**从不修改 GLB 材质**（冻结区不变量：loadGLBRiggedHumanoid 加载 GLB 后
 * 不做材质替换或颜色覆盖）。肤色走下面的独立叠加层实现。
 */
export const BASE_SKIN_COLOR = "#e8e0ff";

/**
 * 肤色叠加层（skin overlay）：包住头部**前侧**的椭球薄壳（前额→下巴），后脑留给发型。
 *
 * 为什么用叠加层而不是改材质：
 *  - 冻结区 `stage3d-core` 明写「loadGLBRiggedHumanoid 加载 GLB 后不做材质替换或颜色覆盖」，
 *    改 GLB 材质属明确违规；
 *  - bodykun 12 个 mesh / bodychan 25 个 mesh **共用同一个 default 材质实例**
 *    ⇒ 改材质等于全身改色，无法只改脸（语义上也不对）；
 *  - 叠加层是游戏业界做「面部 decal / 肤色贴片」的常规手法，且完全可逆、可单测。
 *
 * P0 修复（两处）：
 *  1. 半径按实测头 bbox 三轴（SKIN_RX/RY/RZ）定标 —— 旧版球壳比真实头小一圈，
 *     挂上去被不透明头部深度遮挡，肤色实际不可见；
 *  2. 用 phiStart/phiLength 裁成**前半球冠**（旧版注释写「只保留前半球」但实现是全球，
 *     后脑被肤色包住、与发型穿帮）。
 */
export function makeSkinOverlay(p: FaceParams): THREE.Mesh {
  // 球面参数：phi 从 +Z 正面起算，取正面 ±~100°（含侧脸过渡），后脑不覆盖
  const geo = new THREE.SphereGeometry(
    1, 32, 24,
    Math.PI / 2 - (Math.PI * 100) / 360, // phiStart：正面前方
    (Math.PI * 200) / 360,               // phiLength：正面 200°
    0, Math.PI,                            // theta：全高（前额→下巴由椭球三轴控制）
  );
  geo.scale(SKIN_RX, SKIN_RY, SKIN_RZ);
  // Ruth2 式头型滑杆：位移场直接作用到壳顶点（与五官附件同一 deformFacePoint）
  applyShapeDeform(geo, p);
  const m = new THREE.Mesh(
    geo,
    mat(p.skinTone, { rough: 0.62, opacity: 0.92, side: THREE.DoubleSide }),
  );
  m.name = "skinOverlay";
  m.position.y = HEAD_CENTER_Y;
  return mark(m);
}

/**
 * 全量组装「捏脸层」—— 返回一个 Group，调用方只需 `headBone.add(group)` 一行。
 *
 * 结构（全在 head 骨骼局部坐标系下，+Z 为正面）：
 *   faceLayer
 *     ├─ skinOverlay     肤色/底面（前侧椭球壳）
 *     ├─ faceFeatures    眉/眼/嘴/鼻头/眼线/眼影/腮红/面纹
 *     └─ accessory       发饰（几何附件）
 *
 * ⚠️ 本函数**不修改任何 GLB 既有对象**（不碰 GLB 材质、不碰 GLB 网格），
 *    只往 head 骨骼下新增节点 ⇒ 完全符合 stage3d-core 的两条材质不变量。
 */
export function buildFaceLayer(p: FaceParams): THREE.Group {
  const layer = new THREE.Group();
  layer.name = "faceLayer";
  layer.add(makeSkinOverlay(p));
  layer.add(makeFacialFeatures(p));
  const acc = makeHairAccessory(p);
  if (acc) layer.add(acc);
  return mark(layer);
}

/**
 * 清理：移除所有捏脸附件（重建/切角色时调用，避免附件累积）。
 * P0 修复：faceLayer 组本身此前被跳过 ⇒ 每次重建留一个空壳 Group 单调累积泄漏；
 * 现连同 faceLayer 一起移除并 dispose（mark() 已给整棵子树打过标，直接按标记收集即可）。
 */
export function disposeFaceParts(parent: THREE.Object3D): number {
  const victims: THREE.Object3D[] = [];
  parent.traverse((o) => {
    if (o.userData[FACE_PART_FLAG] && o.parent) victims.push(o);
  });
  // 只移除最顶层的受害者，避免 traverse 快照中子节点被父节点 dispose 后二次处理
  const top = victims.filter((v) => !victims.includes(v.parent as THREE.Object3D));
  for (const v of top) {
    v.parent?.remove(v);
    v.traverse((ch) => {
      const m = ch as THREE.Mesh;
      if (m.isMesh) {
        m.geometry?.dispose?.();
        const mats = Array.isArray(m.material) ? m.material : [m.material];
        for (const mm of mats) {
          const std = mm as THREE.MeshStandardMaterial;
          if (std && std.map) std.map.dispose?.();
          mm?.dispose?.();
        }
      }
    });
  }
  return top.length;
}
