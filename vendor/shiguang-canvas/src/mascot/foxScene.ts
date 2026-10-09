/**
 * Q 版拟人狐狸 —— 程序化几何（Three.js），零外部资源。
 *
 * 为什么程序化而不是用生成图的贴图
 * ================================
 * 参考开源画布（`vendor/AI-Canvas-tauri/src/components/shared/mascot/Mascot.tsx`）的桌宠是**程序化**的：
 * 一个球 + 一坨壳状毛发 + 贴片眼睛，靠渲染循环里的**参数化驱动**（呼吸、眨眼、视线跟随、歪头、
 * 弹跳/摇头、状态色边缘光）活起来。这条路的好处是每一帧都由真实状态算出来，而不是循环播放一段动画
 * （用户明确否定过「随机效果」）。我们沿用同一条路：狐狸由基础几何搭出来，动作全部参数化。
 *
 * 与参考实现的差异（有意为之）
 * ==========================
 * - 参考是**球体**贴片眼；狐狸要做「2 头身 Q 版拟人」，所以是「大头 + 小身 + 尖耳 + 吻 + 围巾 + 手 + 尾」，
 *   眼睛用「眼白球 + 瞳孔球」结构 —— 瞳孔能独立位移，视线跟随才有真实感（贴片眼只能整体转）。
 * - 参考有 48 层壳状毛发（48 次绘制）；狐狸是光面卡通风格，省掉这层：8GB 显存的机器上桌宠不该抢资源。
 * - 新增 `armL/armR`（实现「举手等你确认」）与 `tail`（摆幅反映实时能量）。
 *
 * 坐标系：Y 向上，狐狸面向 +Z（朝观众），整体高度约 2.5 个世界单位（≈ 2 头身）。
 */

import {
  AmbientLight,
  CanvasTexture,
  CapsuleGeometry,
  CircleGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  Group,
  HemisphereLight,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  Scene,
  SphereGeometry,
  type BufferGeometry,
  type Material,
  type Object3D,
} from "three";

export type FoxTheme = "dark" | "light";

interface FoxPalette {
  fur: number;
  furShade: number;
  cream: number;
  eyeWhite: number;
  pupil: number;
  nose: number;
  blush: number;
  /** 围巾 —— 品牌蓝，接企划形象「拾岚」的深蓝主调 */
  scarf: number;
  /** 额顶挑染 —— 青绿，接企划形象的发丝挑染 */
  streak: number;
  rimIntensity: number;
  keyIntensity: number;
  shadowOpacity: number;
}

/**
 * 配色口径
 * ========
 * 毛色用橘白（与用户认可的 Q 版狐狸形象一致），**品牌色只出现在两处点缀**：围巾（品牌蓝 #3b82f6）
 * 与额顶一撮青绿挑染（#2dd4bf）。这两笔都直接对应企划形象「拾岚」的既有特征
 * （深蓝主调 + 品牌蓝挑染，见 `vendor/AI-Canvas-tauri/public/prompts/shiguang-mascot.json`），
 * 这样桌宠是「拾岚的桌面形态」，而不是一只和项目无关的狐狸。
 *
 * 我们画布恒为暗色（`styles.css :root --bg #0a0e14`）；亮色档保留给未来主题切换。
 */
export const FOX_PALETTE: Record<FoxTheme, FoxPalette> = {
  dark: {
    fur: 0xe8833a,
    furShade: 0xc4661f,
    cream: 0xfdf3e6,
    eyeWhite: 0xfffaf4,
    pupil: 0x2a1a16,
    nose: 0x3a2620,
    blush: 0xef7a5c,
    scarf: 0x3b82f6,
    streak: 0x2dd4bf,
    rimIntensity: 0.55,
    keyIntensity: 1.25,
    shadowOpacity: 0.36,
  },
  light: {
    fur: 0xd9762f,
    furShade: 0xb85a1c,
    cream: 0xfffaf2,
    eyeWhite: 0xffffff,
    pupil: 0x231610,
    nose: 0x33211c,
    blush: 0xe06a4e,
    scarf: 0x2563eb,
    streak: 0x14b8a6,
    rimIntensity: 0.3,
    keyIntensity: 1.1,
    shadowOpacity: 0.2,
  },
};

/** 狐狸关键部件句柄；渲染循环只按名取用，不关心几何怎么搭。 */
export interface FoxRig {
  root: Group;
  head: Group;
  earL: Group;
  earR: Group;
  eyeL: Group;
  eyeR: Group;
  pupilL: Group;
  pupilR: Group;
  armL: Group;
  armR: Group;
  tail: Group;
  tailSegments: Object3D[];
  shadow: Mesh;
  rimLight: DirectionalLight;
  setTheme: (theme: FoxTheme) => void;
  /** 释放全部几何/材质（WebView 里反复进出画布不漏显存）。 */
  dispose: () => void;
}

/** 径向衰减的接地阴影贴图，比纯色圆片自然。 */
function makeShadowTexture(): CanvasTexture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grad.addColorStop(0, "rgba(0,0,0,0.95)");
    grad.addColorStop(0.5, "rgba(0,0,0,0.42)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);
  }
  return new CanvasTexture(canvas);
}

/** 眼组基准高度（头局部坐标）。渲染循环里写 `position.y` 时必须基于它加偏移，
 *  否则会把这里定好的眼位覆盖掉（`EYE_POSES.offsetY` 是**相对**眼皮的这个基准的微调）。 */
export const FOX_EYE_BASE_Y = 0.08;

/**
 * 造一只 Q 版拟人狐狸，返回可直接驱动的部件句柄。
 *
 * @param theme  暗/亮档（只影响打光与阴影浓度，不改毛色 —— 避免切主题时形象「换了只狐狸」）
 * @param scene  所属场景（几何与材质会在 dispose() 时统一释放）
 */
export function buildFox(theme: FoxTheme, scene: Scene): FoxRig {
  const palette = FOX_PALETTE[theme];
  const geometries: BufferGeometry[] = [];
  const materials: Material[] = [];
  const textures: CanvasTexture[] = [];
  let disposed = false;

  /** 建 mesh 并顺手登记几何/材质，保证 dispose() 不漏。 */
  const meshOf = (geometry: BufferGeometry, material: Material, parent: Object3D): Mesh => {
    geometries.push(geometry);
    materials.push(material);
    const m = new Mesh(geometry, material);
    parent.add(m);
    return m;
  };
  const stdMat = (color: number, extra: Partial<MeshStandardMaterial> = {}): MeshStandardMaterial =>
    new MeshStandardMaterial({ color, roughness: 0.62, metalness: 0, ...extra });

  /* ── 灯光：半球光给柔和上下过渡，主光给高光，边缘光承载状态色 ── */
  const hemi = new HemisphereLight(0xdfe8ff, 0x1a1f2a, 1.0);
  scene.add(hemi);
  const ambient = new AmbientLight(0xffffff, 0.22);
  scene.add(ambient);
  const keyLight = new DirectionalLight(0xfff2e2, palette.keyIntensity);
  keyLight.position.set(-1.6, 2.4, 2.8);
  scene.add(keyLight);
  const rimLight = new DirectionalLight(0xf7a061, palette.rimIntensity);
  rimLight.position.set(2.2, 1.2, 2.4);
  scene.add(rimLight);

  /* ── 根组：呼吸/跳跃/拖拽倾斜都写在这里 ── */
  const root = new Group();
  root.position.y = -0.66; // 把视觉中心搬到原点，方便相机取景
  scene.add(root);

  /* ── 接地阴影：跳跃时缩小变淡、落地回满，是「跳起来了」的第二重线索。
        刻意挂在 **scene** 而不是 root 上 —— root 会做挤压拉伸（scale.y），
        阴影挂在里面会跟着被拉扁；挂在外面才能保持「地面不动、身体弹」的物理感。 ── */
  const shadowTex = makeShadowTexture();
  textures.push(shadowTex);
  const shadowMat = new MeshBasicMaterial({
    map: shadowTex,
    transparent: true,
    opacity: palette.shadowOpacity,
    depthWrite: false,
  });
  const shadow = meshOf(new PlaneGeometry(1.5, 0.62), shadowMat, scene);
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = -1.14; // 脚底世界坐标（root.y -0.66 + body 0.06 + 脚 -0.44 − 半径）

  /* ── 身体 ── */
  const body = new Group();
  body.position.y = 0.06;
  root.add(body);

  meshOf(new SphereGeometry(0.46, 40, 40), stdMat(palette.fur), body).scale.set(0.98, 0.94, 0.88);

  // 白前襟（拟人化：毛衣/围裙的白色胸口）—— 首版做得又大又圆，像企鹅肚子，收窄收薄
  const chest = meshOf(new SphereGeometry(0.3, 32, 32), stdMat(palette.cream, { roughness: 0.72 }), body);
  chest.scale.set(0.72, 0.88, 0.68);
  chest.position.set(0, -0.06, 0.28);

  // 围巾（品牌橙）+ 垂下的巾角 —— 拟人元素里最容易读出「人」的一笔。
  // 首版太细，读起来像项圈；加高加厚做成真正的「围巾」
  const scarf = meshOf(
    new CylinderGeometry(0.375, 0.395, 0.26, 32, 1, true),
    stdMat(palette.scarf, { roughness: 0.5, side: DoubleSide }),
    body,
  );
  scarf.position.y = 0.3;
  const scarfTail = meshOf(new CapsuleGeometry(0.09, 0.3, 6, 14), stdMat(palette.scarf), body);
  scarfTail.position.set(0.21, 0.15, 0.24);
  scarfTail.rotation.z = 0.36;

  // 手：肩为枢轴 —— idle 下垂、awaiting 上举（「举手等你确认」）
  const buildArm = (side: 1 | -1): Group => {
    const arm = new Group();
    arm.position.set(0.42 * side, 0.26, 0.06);
    const limb = meshOf(new CapsuleGeometry(0.072, 0.17, 6, 14), stdMat(palette.fur), arm);
    limb.position.y = -0.15;
    const paw = meshOf(new SphereGeometry(0.082, 20, 20), stdMat(palette.cream), arm);
    paw.position.y = -0.28;
    body.add(arm);
    return arm;
  };
  const armL = buildArm(-1);
  const armR = buildArm(1);

  // 脚
  for (const side of [-1, 1] as const) {
    const foot = meshOf(new SphereGeometry(0.13, 20, 20), stdMat(palette.furShade), body);
    foot.scale.set(1, 0.72, 1.35);
    foot.position.set(0.2 * side, -0.44, 0.1);
  }

  /* 尾巴：5 节球链，末两节奶白。狐狸尾的读法是「**大而蓬、从背后向上翘起**」。
     两次踩坑：① 首版贴在身后被身体完全挡住 → 看不到；② 改大横向张开后**穿到身前**（在围巾上打了个勾），
     因为 z 走的是正值（+z 是观众方向）。
     正解：根挂在身体**右后方**（x +0.3、z 负），整条尾向后仰（tail.rotation.x）、向右上卷，
     各节 z 只做很小的负向变化 —— 让尾尖从**右后上方**冒出头，而不是横穿胸前。 */
  const tail = new Group();
  tail.position.set(0.28, -0.02, -0.24);
  tail.rotation.set(-0.55, 0, -0.5); // 向后仰 + 向右上卷：尾尖从右后上方冒出
  body.add(tail);
  const tailSegments: Object3D[] = [];
  for (let i = 0; i < 5; i += 1) {
    const seg = meshOf(
      new SphereGeometry(0.21 - i * 0.026, 22, 22),
      stdMat(i >= 3 ? palette.cream : i >= 1 ? palette.fur : palette.furShade),
      tail,
    );
    // 沿尾轴向**上后方**延伸（局部 y 递增 = 世界空间的「向上翘起」）
    seg.position.set(0.02 * i, 0.17 * i, -0.05 * i + 0.01 * i * i);
    tailSegments.push(seg);
  }

  /* ── 头 ── */
  const head = new Group();
  head.position.y = 0.86;
  root.add(head);

  // 脸盘：狐狸的脸**上宽下窄**（狗是上下等宽圆脸）。用「上颚球 + 下颚收窄球」两层拼，
  // 单靠 scale 压扁一个球做不出这个锥度 —— 这是「狐不像狗」的第一笔。
  const skull = meshOf(new SphereGeometry(0.6, 44, 44), stdMat(palette.fur), head);
  skull.scale.set(1.0, 0.9, 0.9);
  const jaw = meshOf(new SphereGeometry(0.46, 36, 36), stdMat(palette.fur), head);
  jaw.scale.set(0.82, 0.72, 0.86);
  jaw.position.set(0, -0.22, 0.06);

  // 额顶呆毛：狐狸辨识点之一，也让「歪头」更容易被看出来。
  const tuft = meshOf(new ConeGeometry(0.15, 0.3, 12), stdMat(palette.fur), head);
  tuft.position.set(0.02, 0.5, 0.12);
  tuft.rotation.set(-0.32, 0, 0.16);
  // 青绿挑染 —— 把桌宠接在企划形象「拾岚」上的锚。首版太细，只露出一点点，加粗加长
  const streak = meshOf(new ConeGeometry(0.105, 0.42, 10), stdMat(palette.streak), head);
  streak.position.set(-0.13, 0.46, 0.19);
  streak.rotation.set(-0.4, 0, 0.5);

  /* 吻部：狐狸的核心识别特征是**尖而长、向下斜的窄吻**（狗是钝短的圆吻）。
     ⚠️ 关键：吻必须与颊**分离**才读得出「尖」。首版吻体和颊纹糊成一坨，
     所以这里把吻**收窄**（0.78 → 0.6）、**前推**（z 0.5 → 0.54），再用一道毛色鼻梁把两者切开。 */
  /* 吻部 + 颊：狐狸白脸的正确做法是**一整块白楔形**（从鼻梁下方向两侧后扫成八字），
     而不是「吻 + 两块独立颊斑」—— 后者无论怎么调都像贴在脸上的棉花球。
     这里用**一个横向拉宽的吻体**承担全部白色：中间是吻，两侧自然收进脸颊。 */
  const muzzle = meshOf(new SphereGeometry(0.28, 30, 30), stdMat(palette.cream, { roughness: 0.72 }), head);
  muzzle.scale.set(0.98, 0.62, 1.16);
  muzzle.position.set(0, -0.22, 0.42);
  // 鼻梁：从额头顺势斜下到吻尖的一道毛色棱 —— 在上面切出「尖吻」的轮廓（白色只在下半张脸）
  const bridge = meshOf(new SphereGeometry(0.2, 26, 26), stdMat(palette.fur), head);
  bridge.scale.set(0.58, 0.6, 1.18);
  bridge.position.set(0, -0.03, 0.4);

  // 鼻头：狐狸鼻**小、尖、略上翘**；坐在吻部**下缘**（首版偏上，像长在鼻梁上）
  const nose = meshOf(new SphereGeometry(0.052, 18, 18), stdMat(palette.nose, { roughness: 0.3 }), head);
  nose.scale.set(1.35, 0.88, 1.0);
  nose.position.set(0, -0.19, 0.62);
  // 腮红：朝前圆片，纯增色不做物理（颊斑已收窄，腮红外移到轮廓边缘才不被颊纹吃掉）
  for (const side of [-1, 1] as const) {
    const blush = meshOf(
      new CircleGeometry(0.095, 24),
      new MeshBasicMaterial({ color: palette.blush, transparent: true, opacity: 0.44, depthWrite: false }),
      head,
    );
    blush.position.set(0.42 * side, -0.13, 0.36);
    blush.rotation.y = 0.6 * side;
  }

  // 眼：眼白 + 瞳孔（可独立位移 → 真正的视线跟随）+ 高光
  // 眼白横向收窄成杏眼 —— 圆眼会读成「狗」，杏眼才是狐。
  // ⚠️ 不要给眼组加 rotation.z（试过 0.13rad 上挑，立刻变成「眯眼凶相」）；
  //    杏眼的「挑」靠**眼白上窄下宽**的比例做，不靠整体旋转。
  const buildEye = (side: 1 | -1): { group: Group; pupil: Group } => {
    const group = new Group();
    group.position.set(0.245 * side, FOX_EYE_BASE_Y, 0.47);
    head.add(group);

    const sclera = meshOf(new SphereGeometry(0.135, 26, 26), stdMat(palette.eyeWhite, { roughness: 0.28 }), group);
    sclera.scale.set(0.9, 1.16, 0.6);

    const pupil = new Group();
    group.add(pupil);
    const iris = meshOf(new SphereGeometry(0.088, 22, 22), stdMat(palette.pupil, { roughness: 0.22 }), pupil);
    iris.scale.set(1, 1, 0.55);
    iris.position.z = 0.055;
    const spark = meshOf(new SphereGeometry(0.03, 14, 14), stdMat(0xffffff, { roughness: 0.1 }), pupil);
    spark.position.set(-0.035 * side, 0.04, 0.1);

    return { group, pupil };
  };
  const leftEye = buildEye(-1);
  const rightEye = buildEye(1);

  /* ── 耳朵：狐狸耳的判据是**高、窄、尖、竖立**（首版是矮胖三角、间距过宽、外倾，读起来是柴犬耳）。
        用 4 面锥拉高收窄（0.24×0.5 → 0.19×0.72），并且把「基部咬合」做扎实：
        耳根略微埋进头骨，否则 Q 版大头会把耳朵挤成「贴在头顶的两片」。 ── */
  const buildEar = (side: 1 | -1): Group => {
    const ear = new Group();
    ear.position.set(0.26 * side, 0.46, -0.04);
    ear.rotation.z = 0.16 * side;
    head.add(ear);

    const outer = meshOf(new ConeGeometry(0.19, 0.72, 4), stdMat(palette.fur), ear);
    outer.rotation.y = Math.PI / 4;
    outer.position.y = 0.2;
    outer.scale.set(1, 1, 0.66); // 前后压薄 → 侧面看是「片状尖耳」而不是「圆锥」
    // 内耳：粉色内衬，前移 + 同比例拉高，让尖耳的粉色一路跟到尖端
    const inner = meshOf(new ConeGeometry(0.105, 0.5, 4), stdMat(palette.blush, { roughness: 0.8 }), ear);
    inner.rotation.y = Math.PI / 4;
    inner.position.set(0, 0.2, 0.07);
    inner.scale.set(1, 1, 0.66);
    return ear;
  };
  const earL = buildEar(-1);
  const earR = buildEar(1);

  const setTheme = (next: FoxTheme) => {
    const p = FOX_PALETTE[next];
    rimLight.intensity = p.rimIntensity;
    keyLight.intensity = p.keyIntensity;
    shadowMat.opacity = p.shadowOpacity;
  };

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    for (const g of geometries) g.dispose();
    for (const m of materials) m.dispose();
    for (const t of textures) t.dispose();
    scene.clear();
  };

  return {
    root,
    head,
    earL,
    earR,
    eyeL: leftEye.group,
    eyeR: rightEye.group,
    pupilL: leftEye.pupil,
    pupilR: rightEye.pupil,
    armL,
    armR,
    tail,
    tailSegments,
    shadow,
    rimLight,
    setTheme,
    dispose,
  };
}

/** 品牌色常量（气泡描边 / 光晕 CSS 变量复用；与上面 palette 里的围巾、挑染同源）。 */
export const FOX_BRAND = { blue: 0x3b82f6, teal: 0x2dd4bf, fur: 0xe8833a } as const;
export const foxColorToCss = (hex: number): string => `#${new Color(hex).getHexString()}`;
