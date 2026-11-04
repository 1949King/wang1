/**
 * Stage3D 姿势数据源（JointPose / 滑杆定义 / 静态姿势库）
 * ========================================================
 * 2026-10-05 自 `riggedHumanoid.ts` **整块抽出**，原因有二：
 *   ① 单文件规模棘轮（`_verify/check_file_size.py`，riggedHumanoid 3707 行基线，
 *      本次加「内旋轴 + 新预设」超容差）——按项目规矩**拆模块，而不是放宽基线**；
 *   ② 姿势数据（类型 / 滑杆范围 / 预设值）本就是独立的一类资产，
 *      与「骨骼搭建 + GLB 加载 + 渲染」职责不同，抽出来便于单独演进与校验。
 *
 * 本文件**零依赖**（纯数据 + 一个纯函数 defaultPose），不 import 任何东西 ⇒ 无环。
 * `riggedHumanoid.ts` 保留 re-export，既有导入方（Stage3D.tsx /
 * stage3dPoseRetarget.ts / magnetic/poseThumbCache.ts）**零改动**。
 *
 * 关节轴约定（2026-10-05 实测校准，勿凭直觉改）：
 *   - 坐标：**脚趾朝 +Z ⇒ +Z = 人体前方**（用 bodykun.glb 脚趾骨实测判定）；
 *   - 躯干 / 头 X：**正 = 前倾**（曾因符号相反，导致「鞠躬」预设表现为后仰）；
 *   - 肩 X：**负 = 前摆 / 上举**（实测；滑杆文案已标注「负=前上」）；
 *   - 髋 / 膝 / 踝 X：正 = 前摆 / 屈曲（实测正确，未改）；
 *   - 肩 / 髋 Z：正 = 外展（右侧镜像取负即对称）；
 *   - 肩 / 髋 / 肘 Y：**2026-10-05 新增的内旋轴**——人体肩是 3 自由度球窝关节，
 *     缺此轴则肘弯曲平面被锁死，「叉腰 / 抱臂 / 握手 / 背手」在数学上无法表达；
 *   - 静止态（全 0）是 **A 字型**（手在体外约 0.47 单位）⇒ 自然垂手需 lShoulderZ ≈ -48，
 *     因此肩 Z 下限由 -20 放宽到 -60。
 *
 * 配套校验：`_verify/check_stage3d_pose_dof.mjs`（真 GLB + 真变换算关节世界坐标）。
 */
/** 关节角（度）——导演摆姿，非完整 IK */
export type JointPose = {
  spineX: number;
  spineY: number;
  spineZ: number;
  abdomenX: number;
  abdomenY: number;
  abdomenZ: number;
  headX: number;
  headY: number;
  headZ: number;
  lShoulderX: number;
  /** ★ 上臂内旋/外旋（2026-10-05 补）：人体肩是 3 自由度球窝关节，缺此轴则肘弯曲平面被锁死，
   *  「叉腰/抱臂/握手/背手」在数学上无法表达。正 = 内旋（拇指转向身体中线）。 */
  lShoulderY: number;
  lShoulderZ: number;
  lElbowX: number;
  /** ★ 前臂旋前/旋后：端杯、看手机、握持等自然手势必需。正 = 旋前（掌心向下）。 */
  lElbowY: number;
  lWristX: number;
  rShoulderX: number;
  /** ★ 上臂内旋/外旋（镜像约定：与左侧同向数值取负即为对称内旋）。 */
  rShoulderY: number;
  rShoulderZ: number;
  rElbowX: number;
  /** ★ 前臂旋前/旋后（镜像：与左侧取负为对称）。 */
  rElbowY: number;
  rWristX: number;
  lHipX: number;
  /** ★ 大腿内旋/外旋（2026-10-05 补）：走路时脚尖方向、站姿「外八/内八」需要此轴。 */
  lHipY: number;
  lHipZ: number;
  lKneeX: number;
  lAnkleX: number;
  rHipX: number;
  /** ★ 大腿内旋/外旋（镜像：与左侧取负为对称）。 */
  rHipY: number;
  rHipZ: number;
  rKneeX: number;
  rAnkleX: number;
};

export const JOINT_LABELS: { key: keyof JointPose; label: string; min: number; max: number }[] = [
  { key: "abdomenX", label: "身体前倾", min: -35, max: 35 },
  { key: "abdomenY", label: "身体转身", min: -60, max: 60 },
  { key: "abdomenZ", label: "身体侧倾", min: -40, max: 40 },
  { key: "spineX", label: "躯干前倾", min: -40, max: 40 },
  { key: "spineY", label: "躯干扭转", min: -50, max: 50 },
  { key: "spineZ", label: "躯干侧倾", min: -40, max: 40 },
  { key: "headX", label: "头部前倾", min: -45, max: 45 },
  { key: "headY", label: "头部转身", min: -70, max: 70 },
  { key: "headZ", label: "头部侧倾", min: -40, max: 40 },
  { key: "lShoulderX", label: "左臂前后（负=前上）", min: -170, max: 80 },
  { key: "lShoulderY", label: "左臂内旋", min: -90, max: 90 },
  // ★ 2026-10-05 放宽下限 -20 → -60：GLB 静止态是 **A 字型**（手在体外约 0.55 单位），
  //   要做出「手臂自然下垂」必须能内收约 -45°，旧下限把手臂永久钳在体外 ⇒ 站姿像假人。
  { key: "lShoulderZ", label: "左臂侧举", min: -60, max: 170 },
  { key: "lElbowX", label: "左肘", min: 0, max: 145 },
  { key: "lElbowY", label: "左前臂旋前", min: -90, max: 90 },
  { key: "lWristX", label: "左腕", min: -60, max: 60 },
  { key: "rShoulderX", label: "右臂前后（负=前上）", min: -170, max: 80 },
  { key: "rShoulderY", label: "右臂内旋", min: -90, max: 90 },
  { key: "rShoulderZ", label: "右臂侧举", min: -170, max: 60 },
  { key: "rElbowX", label: "右肘", min: 0, max: 145 },
  { key: "rElbowY", label: "右前臂旋前", min: -90, max: 90 },
  { key: "rWristX", label: "右腕", min: -60, max: 60 },
  { key: "lHipX", label: "左腿前后", min: -100, max: 90 },
  { key: "lHipY", label: "左腿内旋", min: -45, max: 45 },
  { key: "lHipZ", label: "左腿侧展", min: -20, max: 80 },
  { key: "lKneeX", label: "左膝", min: 0, max: 140 },
  { key: "lAnkleX", label: "左踝", min: -40, max: 40 },
  { key: "rHipX", label: "右腿前后", min: -100, max: 90 },
  { key: "rHipY", label: "右腿内旋", min: -45, max: 45 },
  { key: "rHipZ", label: "右腿侧展", min: -80, max: 20 },
  { key: "rKneeX", label: "右膝", min: 0, max: 140 },
  { key: "rAnkleX", label: "右踝", min: -40, max: 40 },
];

/** 默认（中立）姿态：32 个关节角全 0。链式联动 / 姿势预设都以此为基线。 */
const DEFAULT_POSE: JointPose = {
  spineX: 0,
  spineY: 0,
  spineZ: 0,
  abdomenX: 0,
  abdomenY: 0,
  abdomenZ: 0,
  headX: 0,
  headY: 0,
  headZ: 0,
  lShoulderX: 0,
  lShoulderY: 0,
  lShoulderZ: 0,
  lElbowX: 0,
  lElbowY: 0,
  lWristX: 0,
  rShoulderX: 0,
  rShoulderY: 0,
  rShoulderZ: 0,
  rElbowX: 0,
  rElbowY: 0,
  rWristX: 0,
  lHipX: 0,
  lHipY: 0,
  lHipZ: 0,
  lKneeX: 0,
  lAnkleX: 0,
  rHipX: 0,
  rHipY: 0,
  rHipZ: 0,
  rKneeX: 0,
  rAnkleX: 0,
};

export function defaultPose(): JointPose {
  return { ...DEFAULT_POSE };
}

export type PosePresetId =
  | "idle"
  | "wave"
  | "think"
  | "point"
  | "hands_hips"
  | "cross_arms"
  | "sit"
  | "fight"
  | "bow"
  | "jump_kick"
  | "sword_up"
  | "aim"
  | "staff"
  | "phone"
  | "lean_wall"
  | "hands_pockets"
  | "stretch"
  | "yawn"
  | "cheer"
  | "sad"
  | "surprised"
  | "punch"
  | "block"
  | "throw"
  | "crouch"
  | "step_turn"
  | "tpose"
  | "walk"
  | "kneel"
  // ★ 2026-10-05 新增（补内旋后才做得出的自然手势）
  | "stand_natural"
  | "hands_behind"
  | "hold_phone"
  | "handshake";

export const POSE_PRESETS: { id: PosePresetId; label: string; pose: Partial<JointPose> }[] = [
  { id: "idle", label: "站立", pose: defaultPose() },
  {
    id: "wave",
    label: "挥手",
    pose: {
      ...defaultPose(),
      rShoulderZ: -95,
      rShoulderX: -35,
      rElbowX: 42,
      headY: -10,
      spineY: 6,
    },
  },
  {
    id: "think",
    label: "思考",
    pose: {
      ...defaultPose(),
      rShoulderX: -70,
      rShoulderZ: -25,
      rElbowX: 100,
      rWristX: 15,
      headX: 12,
      headY: 18,
      spineX: 4,
    },
  },
  {
    id: "point",
    label: "指向",
    pose: {
      ...defaultPose(),
      rShoulderX: -80,
      rShoulderZ: -22,
      rElbowX: 12,
      headY: -12,
      spineY: -6,
    },
  },
  {
    id: "hands_hips",
    label: "叉腰",
    pose: {
      ...defaultPose(),
      // ★ 2026-10-05 重调（几何实测，见 _verify/check_stage3d_pose_dof.mjs）：
      //   内旋 50° + 轻微前摆 5° + 内收 -30° + 屈肘 100° ⇒ 手落在腰侧、**肘朝后外**。
      //   判别性不变式：肘的 z 必须小于手的 z（肘在身后）——旧的「无内旋」版本做不到这一点。
      lShoulderX: 5,
      lShoulderY: 50,
      lShoulderZ: -30,
      lElbowX: 100,
      lElbowY: 20,
      rShoulderX: 5,
      rShoulderY: -50,
      rShoulderZ: 30,
      rElbowX: 100,
      rElbowY: -20,
      spineX: 2,
    },
  },
  {
    id: "cross_arms",
    label: "抱臂",
    pose: {
      ...defaultPose(),
      // ★ 2026-10-05 修复：补内旋 + 前臂旋前——没有内旋时前臂会在错误的平面里交叉，
      //   导致「前臂穿脖子」；内旋后上臂贴胸、前臂水平横抱，才是真人抱臂形态。
      lShoulderX: -28,
      lShoulderY: 58,
      lShoulderZ: 26,
      lElbowX: 112,
      lElbowY: 26,
      rShoulderX: -34,
      rShoulderY: -62,
      rShoulderZ: -22,
      rElbowX: 118,
      rElbowY: -26,
      spineX: 3,
      headX: 2,
    },
  },
  // ── ★ 2026-10-05 新增预设（均为「补内旋后才成立」的自然人姿）──
  {
    id: "stand_natural",
    label: "自然站姿",
    pose: {
      ...defaultPose(),
      // ★ 2026-10-05 几何实测定值：GLB 静止态是 A 字型（手在体外 0.47），
      //   内收 -48° 后手落到大腿外侧（横向 0.165、髋高 0.889），才是真人自然垂手。
      lShoulderY: 12,
      lShoulderZ: -48,
      lElbowX: 8,
      rShoulderY: -12,
      rShoulderZ: 48,
      rElbowX: 8,
      lHipY: -4,
      rHipY: 4,
      spineX: 1,
      headX: 1,
    },
  },
  {
    id: "hands_behind",
    label: "背手",
    pose: {
      ...defaultPose(),
      // ★ 2026-10-05 几何实测定值：内旋 60° + 内收 -20° + 屈肘 70° ⇒ 手落在**臀后**
      //   （hand.z 0.093 > 髋 z -0.033），肘微屈——手臂在身后交叠的自然形态。
      lShoulderX: -20,
      lShoulderY: 60,
      lShoulderZ: -20,
      lElbowX: 70,
      lElbowY: -20,
      rShoulderX: -20,
      rShoulderY: -60,
      rShoulderZ: 20,
      rElbowX: 70,
      rElbowY: 20,
      spineX: -1,
    },
  },
  {
    id: "hold_phone",
    label: "看手机",
    pose: {
      ...defaultPose(),
      // 右手举到胸前 + 前臂强旋前（掌心朝下）——旋前是「端/看/握」类手势的必需轴
      rShoulderX: -22,
      rShoulderY: -34,
      rShoulderZ: -26,
      rElbowX: 104,
      rElbowY: 62,
      lShoulderY: 10,
      lElbowX: 6,
      headX: 14,
      spineX: 4,
    },
  },
  {
    id: "handshake",
    label: "握手",
    pose: {
      ...defaultPose(),
      // 右手前伸握手：前伸 + 适度内旋让掌心朝侧（握手姿势），微屈肘
      rShoulderX: -64,
      rShoulderY: -22,
      rShoulderZ: -14,
      rElbowX: 48,
      rElbowY: 12,
      lShoulderY: 10,
      lElbowX: 6,
      spineY: -6,
      headY: 8,
    },
  },
  {
    id: "sit",
    label: "坐姿",
    pose: {
      ...defaultPose(),
      abdomenX: 8,
      spineX: 4,
      lHipX: 70,
      lKneeX: 98,
      rHipX: 70,
      rKneeX: 98,
      lAnkleX: 10,
      rAnkleX: 10,
      lShoulderX: -14,
      rShoulderX: -14,
      lElbowX: 28,
      rElbowX: 28,
    },
  },
  {
    id: "fight",
    label: "戒备",
    pose: {
      ...defaultPose(),
      spineX: -4,
      spineY: 10,
      lShoulderX: -85,
      lShoulderZ: 28,
      lElbowX: 70,
      rShoulderX: -65,
      rShoulderZ: -22,
      rElbowX: 55,
      lHipX: 22,
      rHipX: -12,
      lKneeX: 18,
      rKneeX: 12,
      headX: -2,
      headY: 8,
    },
  },
  {
    id: "bow",
    label: "鞠躬",
    pose: {
      ...defaultPose(),
      abdomenX: 32,
      spineX: 22,
      headX: 18,
      lShoulderX: 8,
      rShoulderX: 8,
      lHipX: 8,
      rHipX: 8,
    },
  },
  {
    id: "jump_kick",
    label: "飞踢",
    pose: {
      ...defaultPose(),
      spineX: -8,
      abdomenX: -4,
      lShoulderX: -35,
      lShoulderZ: 40,
      rShoulderX: -70,
      rElbowX: 35,
      lHipX: -12,
      lKneeX: 70,
      rHipX: 62,
      rKneeX: 28,
      headX: -6,
    },
  },
  {
    id: "sword_up",
    label: "举剑",
    pose: {
      ...defaultPose(),
      rShoulderX: -150,
      rShoulderZ: -35,
      rElbowX: 20,
      lShoulderX: -40,
      lElbowX: 50,
      spineY: -10,
      lHipX: 15,
      rHipX: -10,
    },
  },
  {
    id: "aim",
    label: "瞄准",
    pose: {
      ...defaultPose(),
      lShoulderX: -85,
      lElbowX: 15,
      rShoulderX: -85,
      rElbowX: 15,
      spineY: 18,
      lHipX: 35,
      rHipX: -25,
      headY: 10,
    },
  },
  {
    id: "staff",
    label: "持杖",
    pose: {
      ...defaultPose(),
      lShoulderX: -55,
      lElbowX: 70,
      rShoulderX: -70,
      rElbowX: 55,
      spineY: -8,
      lHipX: 12,
      rHipX: -8,
    },
  },
  // —— 日常类 ——
  {
    id: "phone",
    label: "看手机",
    pose: {
      ...defaultPose(),
      rShoulderX: -48,
      rShoulderZ: -12,
      rElbowX: 115,
      lShoulderX: -12,
      headX: 16,
      spineX: 8,
    },
  },
  {
    id: "lean_wall",
    label: "靠墙",
    pose: {
      ...defaultPose(),
      // 背靠墙：轻度后仰 + 一腿承重一腿虚点，一手撑墙
      spineX: -12,
      abdomenX: -6,
      spineZ: 8,
      abdomenZ: 6,
      rHipX: 4,
      rHipZ: -8,
      lHipX: 16,
      lHipZ: 6,
      lKneeX: 22,
      rKneeX: 6,
      rShoulderX: -22,
      rShoulderZ: -30,
      rElbowX: 70,
      lShoulderX: 6,
      lElbowX: 18,
      headX: 4,
      headY: 6,
    },
  },
  {
    id: "hands_pockets",
    label: "手插兜",
    pose: {
      ...defaultPose(),
      lShoulderX: 4,
      lShoulderZ: 22,
      lElbowX: 45,
      rShoulderX: 4,
      rShoulderZ: -22,
      rElbowX: 45,
      abdomenX: 6,
    },
  },
  {
    id: "stretch",
    label: "伸懒腰",
    pose: {
      ...defaultPose(),
      lShoulderX: -155,
      lShoulderZ: 42,
      lElbowX: 10,
      rShoulderX: -155,
      rShoulderZ: -42,
      rElbowX: 10,
      spineX: -14,
      headX: -12,
    },
  },
  {
    id: "yawn",
    label: "打哈欠",
    pose: {
      ...defaultPose(),
      lShoulderX: -120,
      lElbowX: 55,
      rShoulderX: -120,
      rElbowX: 55,
      headX: 28,
      headY: -18,
      spineX: 10,
    },
  },
  // —— 情绪类 ——
  {
    id: "cheer",
    label: "欢呼",
    pose: {
      ...defaultPose(),
      lShoulderX: -160,
      lShoulderZ: 60,
      lElbowX: 25,
      rShoulderX: -160,
      rShoulderZ: -60,
      rElbowX: 25,
      spineX: -6,
      headX: -6,
      lHipX: 10,
      rHipX: -10,
    },
  },
  {
    id: "sad",
    label: "垂头",
    pose: {
      ...defaultPose(),
      spineX: 18,
      abdomenX: 12,
      headX: 42,
      headY: -20,
      lShoulderX: 12,
      lShoulderZ: 10,
      rShoulderX: 12,
      rShoulderZ: -10,
    },
  },
  {
    id: "surprised",
    label: "惊讶",
    pose: {
      ...defaultPose(),
      headX: -14,
      headY: 6,
      lShoulderX: -38,
      lShoulderZ: 28,
      lElbowX: 58,
      rShoulderX: -38,
      rShoulderZ: -28,
      rElbowX: 58,
      spineX: -4,
    },
  },
  // —— 动作类 ——
  {
    id: "punch",
    label: "出拳",
    pose: {
      ...defaultPose(),
      spineY: 22,
      spineX: -6,
      rShoulderX: -10,
      rShoulderZ: -8,
      rElbowX: 6,
      lShoulderX: -95,
      lElbowX: 72,
      lHipX: 22,
      rHipX: -16,
      headY: 14,
    },
  },
  {
    id: "block",
    label: "格挡",
    pose: {
      ...defaultPose(),
      lShoulderX: -85,
      lShoulderZ: 32,
      lElbowX: 95,
      rShoulderX: -85,
      rShoulderZ: -32,
      rElbowX: 95,
      spineY: 8,
      lHipX: 18,
      rHipX: -12,
      headX: -6,
    },
  },
  {
    id: "throw",
    label: "投掷",
    pose: {
      ...defaultPose(),
      rShoulderX: -165,
      rShoulderZ: -40,
      rElbowX: 30,
      lShoulderX: 20,
      lShoulderZ: 12,
      rWristX: 18,
      spineY: -18,
      spineX: -8,
      lHipX: 22,
      rHipX: -14,
      headY: -10,
    },
  },
  // —— 姿态类 ——
  {
    id: "crouch",
    label: "蹲姿",
    pose: {
      ...defaultPose(),
      lHipX: 72,
      lKneeX: 110,
      rHipX: 72,
      rKneeX: 110,
      lAnkleX: 22,
      rAnkleX: 22,
      abdomenX: 18,
      spineX: 12,
      headX: 4,
      lShoulderX: -30,
      rShoulderX: -30,
      lShoulderZ: 14,
      rShoulderZ: -14,
      lElbowX: 42,
      rElbowX: 42,
    },
  },
  {
    id: "step_turn",
    label: "转身回头",
    pose: {
      ...defaultPose(),
      spineY: -32,
      headY: 42,
      spineX: 6,
      lShoulderX: -22,
      lShoulderZ: 18,
      rShoulderX: -22,
      rShoulderZ: -18,
      lHipX: 14,
      rHipX: -10,
    },
  },
  {
    id: "tpose",
    label: "T型",
    pose: {
      ...defaultPose(),
      lShoulderZ: 90,
      rShoulderZ: -90,
      lElbowX: 0,
      rElbowX: 0,
    },
  },
  {
    id: "kneel",
    label: "单膝跪",
    pose: {
      ...defaultPose(),
      lHipX: 55,
      lKneeX: 105,
      lAnkleX: -8,
      rHipX: 12,
      rKneeX: 95,
      rAnkleX: 5,
      abdomenX: 6,
      spineX: 4,
      lShoulderX: -10,
      rShoulderX: -10,
      headX: 2,
    },
  },
  {
    id: "walk",
    label: "行走",
    pose: {
      ...defaultPose(),
      lHipX: 24,
      rHipX: -18,
      lKneeX: 14,
      rKneeX: 32,
      lShoulderX: -18,
      rShoulderX: 14,
      lElbowX: 18,
      rElbowX: 18,
      spineX: 3,
      spineY: 4,
    },
  },
];
