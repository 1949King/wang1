/**
 * 3D 导演台 · 机位可视化「电影级视锥」（Stage3D 配套，2026-10-07 V4.40.55 新增）
 *
 * 为什么单独成模块：`Stage3D.tsx` 已在「单文件规模棘轮」基线上（4660 行 / 容差 30），
 * 机位的几何 + 标签 + 状态逻辑整块外移，让 Stage3D 只留一行接线
 * （与 `stage3dPoseLibrary.ts` 同一手法，属守卫指引里的正当解法）。
 *
 * ── 改的是「突兀」这件事 ─────────────────────────────────────────────
 * 旧实现（Stage3D 内联）= 高饱和琥珀实心圆锥(#fbbf24) + 实心方块(#f59e0b)。
 * 问题不是"丑"，是**和场景不在同一个语言里**：
 *   ① 两个**实心受光体**在素模场景里比角色还抢眼（角色才是主体，机位是辅助物）；
 *   ② 体量硬编码 0.18/0.4/0.28，**完全忽略 fov / 景别** ⇒ 18° 长焦和 90° 广角长得一模一样，
 *      "这台机位拍出来是什么样"在 3D 视图里读不出来 —— 而这正是机位可视化唯一的价值；
 *   ③ 恒定橙 = 没有状态位，看不出哪台是当前机位。
 *
 * 新实现 = 影院机「机身 + 视锥」：
 *   · 机身/镜头走**线框**（1px，不吃光照、不产生阴影），默认中性灰 —— 辅助物就该是辅助物；
 *   · 视锥**真由 fov 推**：广角短而胖、长焦长而窄，半透明，一眼看出景别；
 *   · 镜头座**随焦段伸长**（长焦枪管更长），给"焦距"第二个可读信号；
 *   · 「名称 · 景别 · mm」做成面向镜头的标签（Sprite 恒定朝向），mm 复用 `fovToFocalLength`
 *     ⇒ 与截图元数据同源，不另算一套系数；
 *   · 颜色只表达状态：默认中性灰 / 当前机位品牌蓝 #2563eb；
 *   · 地面投点环 + 竖直定位线，给视锥一个空间锚（否则半透明锥体"飘在空中"）。
 *
 * ── 附带修掉的一个功能缺陷 ───────────────────────────────────────────
 * 所有 helper 一律打 `userData.isHelper = true`（`setHelpersVisible` 据此开关）：
 *   · `stage3dControlNet` 的 Depth / Normal 通道**整场景重渲染**，
 *     旧实现会把机位实体**烘进 ControlNet 图**（AI 会把"一个橙色圆锥"当成场景内容）；
 *   · `capture()` 按机位截图同理 —— 该拍进画布的是角色，不该是别的机位。
 */
import * as THREE from "three";

/** 机位（结构化子集：只用可视化真正需要的字段，避免与 Stage3D 循环引用） */
export type GizmoCamera = {
  id: string;
  name: string;
  position: [number, number, number];
  lookAt: [number, number, number];
  fov: number;
  /** 镜头景别（中景/特写/全景…），由 CAM_PRESETS 带入 */
  shotSize?: string;
};

/** 只依赖 camHelpers 这一个 api 面（结构化类型，勿改宽 —— 改宽即破坏"零解冻"边界） */
export type CamGizmoApi = {
  scene: THREE.Scene;
  camHelpers: Map<string, THREE.Object3D>;
};

/**
 * 全画幅近似：f = 43.27 / (2 * tan(fov° / 2))，再吸附到常见焦段。
 * 原先内联在 Stage3D.tsx，迁到这里共享 —— 标签上的 mm 与截图元数据的 mm 必须同一个来源。
 */
export function fovToFocalLength(fovDeg: number): number {
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

/** 机身三围（米。素模量级 1.7m，机位略放大到 0.26m 宽以便 4m 外仍可辨认） */
const BODY_W = 0.26;
const BODY_H = 0.2;
const BODY_D = 0.34;
/** 视锥长度（米）：fov=45° 时远端约 1.55×0.87m，够读但不遮蔽角色 */
const FRUSTUM_LEN = 1.05;
/** 视锥张开用的画幅比（对齐 CAM_PRESETS 主流 16:9） */
const FRUSTUM_ASPECT = 16 / 9;
/** 标签世界高度（米） */
const LABEL_H = 0.13;
/** 镜头座基准长度（米），随焦段伸长 */
const LENS_LEN = 0.16;

const COLOR_IDLE = "#8ea3b8";
const COLOR_ACTIVE = "#2563eb";
const COLOR_HOVER = "#f97316";

const UP = new THREE.Vector3(0, 1, 0);

type GizmoParts = {
  head: THREE.Group;
  body: THREE.LineSegments;
  lens: THREE.LineSegments;
  cone: THREE.LineSegments;
  ring: THREE.Mesh;
  drop: THREE.Line;
  label: THREE.Sprite;
  /** 当前视锥对应的 fov（变了才重建几何） */
  coneFov: number;
  /** 标签文本指纹（名称/景别/焦段，变了才重绘贴图） */
  labelKey: string;
};

function tagHelper(o: THREE.Object3D): void {
  o.userData.isHelper = true;
}

/**
 * 显示 / 隐藏全部编辑辅助物（机位视锥、标签、地面环、坐标轴…）。
 * ControlNet 三通道导出与 `capture()` 截图前调用 —— **产物里不该有编辑辅助物**。
 * @returns 还原函数（务必在 finally 语义下调用，否则辅助物会永久消失）
 */
export function setHelpersVisible(root: THREE.Object3D, visible: boolean): () => void {
  const touched: THREE.Object3D[] = [];
  root.traverse((o) => {
    if (o.userData?.isHelper && o.visible !== visible) {
      o.visible = visible;
      touched.push(o);
    }
  });
  return () => {
    for (const o of touched) o.visible = true;
  };
}

/** 线框：EdgesGeometry 只画折边（BoxGeometry 自带 wireframe 会画面对角线，更乱） */
function makeEdges(geo: THREE.BufferGeometry, color: string): THREE.LineSegments {
  const line = new THREE.LineSegments(
    new THREE.EdgesGeometry(geo),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9 }),
  );
  tagHelper(line);
  return line;
}

/**
 * 视锥几何：从镜头口沿视线方向张开的 4 条棱 + 远端矩形 + 中心轴。
 * `fov` 是**竖直** FOV（与 THREE.PerspectiveCamera.fov 同义），水平张角按 FRUSTUM_ASPECT 换算。
 */
function coneGeometry(fov: number): THREE.BufferGeometry {
  const halfH = Math.tan((fov * Math.PI) / 360) * FRUSTUM_LEN;
  const halfW = halfH * FRUSTUM_ASPECT;
  const z0 = BODY_D / 2;
  const z1 = z0 + FRUSTUM_LEN;
  const corners: [number, number][] = [
    [-halfW, -halfH],
    [halfW, -halfH],
    [halfW, halfH],
    [-halfW, halfH],
  ];
  const pts: number[] = [];
  for (const [x, y] of corners) pts.push(0, 0, z0, x, y, z1);
  for (let i = 0; i < 4; i += 1) {
    const a = corners[i];
    const b = corners[(i + 1) % 4];
    pts.push(a[0], a[1], z1, b[0], b[1], z1);
  }
  pts.push(0, 0, z0, 0, 0, z1);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return geo;
}

/** 圆角矩形路径（不用 ctx.roundRect，避开 TS DOM lib 版本差异） */
function roundRectPath(ctx: CanvasRenderingContext2D, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(r, 0);
  ctx.lineTo(w - r, 0);
  ctx.quadraticCurveTo(w, 0, w, r);
  ctx.lineTo(w, h - r);
  ctx.quadraticCurveTo(w, h, w - r, h);
  ctx.lineTo(r, h);
  ctx.quadraticCurveTo(0, h, 0, h - r);
  ctx.lineTo(0, r);
  ctx.quadraticCurveTo(0, 0, r, 0);
  ctx.closePath();
}

/** 标签贴图：深藏蓝底 + 浅字（品牌色），Sprite 自动面向镜头 */
function makeLabelTexture(text: string): THREE.CanvasTexture | null {
  // 非浏览器环境（vitest 的 node environment）没有 canvas ⇒ 跳过标签，
  // 视锥/机身等几何仍可被断言（见 stage3dCamGizmo.test.ts）
  if (typeof document === "undefined") return null;
  const PAD = 14;
  const H = 60;
  const font = "600 34px 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif";
  const cv = document.createElement("canvas");
  const probe = cv.getContext("2d");
  if (!probe) return null;
  probe.font = font;
  const W = Math.ceil(probe.measureText(text).width) + PAD * 2;
  cv.width = W;
  cv.height = H;
  const ctx = cv.getContext("2d");
  if (!ctx) return null;
  ctx.font = font;
  ctx.textBaseline = "middle";
  ctx.fillStyle = "rgba(23,32,51,0.84)";
  roundRectPath(ctx, W, H, 14);
  ctx.fill();
  ctx.strokeStyle = "rgba(237,243,255,0.22)";
  ctx.lineWidth = 2;
  roundRectPath(ctx, W - 1, H - 1, 13);
  ctx.stroke();
  ctx.fillStyle = "#edf3ff";
  ctx.fillText(text, PAD, H / 2 + 1);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.minFilter = THREE.LinearFilter;
  return tex;
}

function labelKeyOf(c: GizmoCamera): string {
  return `${c.name}|${c.shotSize || "未定景别"}|${fovToFocalLength(c.fov)}`;
}

function replaceLabel(parts: GizmoParts, key: string): void {
  const [name, shot, mm] = key.split("|");
  const tex = makeLabelTexture(`${name} · ${shot} · ${mm}mm`);
  if (!tex) return;
  parts.label.material.map?.dispose();
  parts.label.material.map = tex;
  parts.label.material.needsUpdate = true;
  parts.label.scale.set((tex.image.width * LABEL_H) / tex.image.height, LABEL_H, 1);
  parts.labelKey = key;
}

/** 建一台机位的可视化。container **不旋转**（地面环/定位线要留在世界坐标），朝向交给 head */
function buildGizmo(cam: GizmoCamera): THREE.Group {
  const container = new THREE.Group();

  const head = new THREE.Group();
  const body = makeEdges(new THREE.BoxGeometry(BODY_W, BODY_H, BODY_D), COLOR_IDLE);
  const lens = makeEdges(new THREE.CylinderGeometry(0.055, 0.07, LENS_LEN, 16), COLOR_IDLE);
  lens.rotation.x = Math.PI / 2; // 圆柱轴 +Y → +Z（视线方向）
  lens.position.z = BODY_D / 2 + 0.06;
  const cone = new THREE.LineSegments(
    coneGeometry(cam.fov),
    new THREE.LineBasicMaterial({ color: COLOR_IDLE, transparent: true, opacity: 0.42 }),
  );
  tagHelper(cone);
  head.add(body, lens, cone);
  container.add(head);

  const label = new THREE.Sprite(
    new THREE.SpriteMaterial({ transparent: true, depthWrite: false }),
  );
  tagHelper(label);
  label.position.y = 0.44;
  container.add(label);

  // 地面投点环：给视锥一个空间锚（半透明锥体不锚地会"飘"）
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.1, 0.14, 24),
    new THREE.MeshBasicMaterial({
      color: COLOR_IDLE,
      transparent: true,
      opacity: 0.5,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  tagHelper(ring);
  ring.rotation.x = -Math.PI / 2;
  container.add(ring);

  // 竖直定位线：固定几何 (0,-1,0)→(0,0,0)，靠 scale.y 拉到机位高度（零重建）
  const drop = new THREE.Line(
    new THREE.BufferGeometry().setAttribute(
      "position",
      new THREE.Float32BufferAttribute([0, -1, 0, 0, 0, 0], 3),
    ),
    new THREE.LineBasicMaterial({ color: COLOR_IDLE, transparent: true, opacity: 0.28 }),
  );
  tagHelper(drop);
  container.add(drop);

  tagHelper(container);
  const parts: GizmoParts = {
    head,
    body,
    lens,
    cone,
    ring,
    drop,
    label,
    coneFov: -1, // 强制首帧按真实 fov 建几何
    labelKey: "",
  };
  container.userData.parts = parts;
  replaceLabel(parts, labelKeyOf(cam));
  return container;
}

const _m4 = new THREE.Matrix4();
const _eye = new THREE.Vector3();
const _look = new THREE.Vector3();

/**
 * 让 head 的 +Z 指向 lookAt。
 * 不用 `Object3D.lookAt`：父物体旋转依赖 `parent.matrixWorld` 已刷新，
 * 而我们刚改完 container.position，会拿到上一帧的矩阵（朝向抖动一帧）。
 * 手动算基向量 ⇒ 无父矩阵依赖，且 roll 由世界 UP 校正（视锥不会斜）。
 */
function faceTarget(head: THREE.Object3D, cam: GizmoCamera): void {
  _eye.set(cam.position[0], cam.position[1], cam.position[2]);
  _look.set(cam.lookAt[0], cam.lookAt[1], cam.lookAt[2]);
  // Matrix4.lookAt(eye,target,up) 令 +Z = normalize(eye - target)；这里要 +Z 朝目标 ⇒ 交换
  _m4.lookAt(_look, _eye, UP);
  head.quaternion.setFromRotationMatrix(_m4);
}

function setColor(mat: THREE.Material & { color?: THREE.Color }, color: string): void {
  if (mat.color) mat.color.set(color);
}

/** 状态上色：默认中性灰（不抢戏），当前机位品牌蓝 + 视锥加浓 */
function paintGizmo(parts: GizmoParts, color: string, active: boolean): void {
  for (const o of [parts.body, parts.lens, parts.cone, parts.ring, parts.drop]) {
    const mat = o.material as THREE.Material & { color?: THREE.Color };
    setColor(mat, color);
  }
  (parts.cone.material as THREE.LineBasicMaterial).opacity = active ? 0.62 : 0.42;
}

function disposeGizmo(root: THREE.Object3D): void {
  root.traverse((o) => {
    const any = o as THREE.Mesh;
    any.geometry?.dispose?.();
    const mat = any.material as THREE.Material | THREE.Material[] | undefined;
    if (Array.isArray(mat)) {
      for (const m of mat) m.dispose();
    } else if (mat) {
      (mat as THREE.SpriteMaterial).map?.dispose?.();
      mat.dispose();
    }
  });
}

/**
 * 同步全部机位可视化：创建 / 位姿更新 / fov 重建 / 标签重绘 / 状态上色 / 回收。
 * 替代了原先内联在 Stage3D 里的 34 行 effect 主体。
 */
export function syncCameraGizmos(
  api: CamGizmoApi,
  cameras: GizmoCamera[],
  activeId?: string | null,
): void {
  const keep = new Set(cameras.map((c) => c.id));
  for (const [id, obj] of api.camHelpers) {
    if (keep.has(id)) continue;
    api.scene.remove(obj);
    disposeGizmo(obj);
    api.camHelpers.delete(id);
  }
  for (const c of cameras) {
    let g = api.camHelpers.get(c.id) as THREE.Group | undefined;
    if (!g) {
      g = buildGizmo(c);
      api.scene.add(g);
      api.camHelpers.set(c.id, g);
    }
    const parts = g.userData.parts as GizmoParts;
    g.position.set(c.position[0], c.position[1], c.position[2]);
    faceTarget(parts.head, c);

    // 视锥随 fov 重建（旧实现完全忽略 fov ⇒ 广角/长焦长得一样，读不出景别）
    if (Math.abs(parts.coneFov - c.fov) > 0.01) {
      parts.cone.geometry.dispose();
      parts.cone.geometry = coneGeometry(c.fov);
      parts.coneFov = c.fov;
      // 镜头座随焦段伸长：长焦枪管更长（"焦距"的第二个可读信号）
      const s = 0.75 + (0.5 * (fovToFocalLength(c.fov) - 14)) / 186;
      parts.lens.scale.y = s;
      parts.lens.position.z = BODY_D / 2 + (LENS_LEN / 2) * s - 0.02;
    }
    // 标签随「名称/景别/焦段」重绘（改了不刷 = 标签在撒谎）
    const key = labelKeyOf(c);
    if (parts.labelKey !== key) replaceLabel(parts, key);

    parts.ring.position.y = -c.position[1] + 0.02; // 落到世界 y≈0
    parts.drop.scale.y = Math.max(0.01, c.position[1]); // 原点到机位高度

    const active = Boolean(activeId) && c.id === activeId;
    paintGizmo(parts, active ? COLOR_ACTIVE : COLOR_IDLE, active);
  }
}

/** 供未来做悬停高亮时复用（当前 3D 视图未对机位做拾取，先留着配色常量避免散落） */
export const CAM_GIZMO_COLORS = { idle: COLOR_IDLE, active: COLOR_ACTIVE, hover: COLOR_HOVER };
