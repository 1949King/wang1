/**
 * lightingPresets.ts — 电影级灯位库（2026-10-06，对标 LibTV「24 主光位 + 9 轮廓光」）。
 *
 * 设计来源（为什么要这么定"24"与"9"）
 * ==================================
 * · **主光 24 位** = 以被摄主体为中心，**每 15° 一个方位**绕一圈（360 / 15 = 24）。
 *   这不是凑数：灯位本来就是方位角，15° 步进是够用的经典粒度（45°/90°/135°/180° 等
 *   有名有姓的灯位都落在整数格上：45°=伦勃朗、90°=侧光、135°=侧逆、180°=正逆）。
 * · **轮廓光 9 组** = 逆侧方向的 9 种勾勒方式（后上方 30/45/60、正后 180、
 *   双侧轮廓、顶轮廓、底补轮廓、发丝光、环境轮廓）。
 *
 * 用法（**真实通道**，不做装饰）
 * ============================
 * 选中的灯位会被写成一段**受管提示词块**追加到节点提示词里：
 *
 *     〔光照：伦勃朗光（主光 45°/高度 45°/色温 3200K）+ 侧后轮廓光 45°〕
 *
 * ⚠️ 为什么写进**提示词**而不是只存一个字段：提示词是**真的会送到模型**的输入；
 * 只存字段而没人读它，就是"看着有、实际没用"的装饰（本项目明确反对）。
 * 块是**受管的**：`applyLightingBlock()` 会**替换**旧块而不是叠加，
 * `stripLightingBlock()` 可整块移除 ⇒ 反复换灯位不会越写越长。
 *
 * 诚实说明
 * ========
 * 这些角度/色温是**摄影术语的常规取值**，不是某个具体影片的实测参数；
 * 它们的价值在于**给模型一个明确的光位约束**（比"打光好看点"有效得多）。
 */

export interface KeyLight {
  /** 相对镜头轴的方位角：0 = 正前方（机位方向），顺时针增大 */
  azimuth: number;
  /** 高度角：0 = 与主体同高，90 = 正上方 */
  height: number;
  /** 强度权重 0~1（仅用于描述，不是物理量） */
  intensity: number;
  /** 色温 K */
  kelvin: number;
  name: string;
  /** 什么时候用它（给用户看的一句话） */
  note: string;
}

const KEY_NAMES: Record<number, { name: string; note: string }> = {
  0: { name: "正前光", note: "平顺无阴影，适合证件感、产品正面" },
  15: { name: "前侧微偏", note: "几乎无阴影的柔和正面" },
  30: { name: "环型光（Loop）", note: "鼻影小巧，最通用的美人光" },
  45: { name: "伦勃朗光", note: "颊部三角光，戏剧感与立体感兼备" },
  60: { name: "开角侧光", note: "面部明暗分明，仍有细节" },
  75: { name: "近侧光", note: "接近半阴，强调轮廓转折" },
  90: { name: "正侧光（Split）", note: "一半亮一半暗，强烈对峙感" },
  105: { name: "侧后前压", note: "大面积暗部，压出神秘" },
  120: { name: "侧逆光", note: "边缘起亮，人物从背景里跳出来" },
  135: { name: "强侧逆", note: "半剪影，轮廓为主" },
  150: { name: "逆侧", note: "近剪影，交代环境为主" },
  165: { name: "逆光微偏", note: "发丝与肩线起亮" },
  180: { name: "正逆光", note: "剪影；配合补光可做光环" },
  195: { name: "逆光微偏（右侧）", note: "同 165°，方向相反" },
  210: { name: "逆侧（右侧）", note: "同 150°，方向相反" },
  225: { name: "强侧逆（右侧）", note: "同 135°，方向相反" },
  240: { name: "侧逆光（右侧）", note: "同 120°，方向相反" },
  255: { name: "侧后前压（右侧）", note: "同 105°，方向相反" },
  270: { name: "正侧光（右侧）", note: "同 90° 的镜像" },
  285: { name: "近侧光（右侧）", note: "同 75° 的镜像" },
  300: { name: "开角侧光（右侧）", note: "同 60° 的镜像" },
  315: { name: "伦勃朗光（右侧）", note: "同 45° 的镜像" },
  330: { name: "环型光（右侧）", note: "同 30° 的镜像" },
  345: { name: "前侧微偏（右侧）", note: "同 15° 的镜像" },
};

/** 高度角按方位取一个常规值：越接近正侧越常用"略高于眼"。 */
export function heightFor(az: number): number {
  // 2026-10-09 优化：旧版是 4 点阶梯（0/90/180/270 特判 + 其余一律 45°），
  // 相邻档位之间会跳变（15° 方位是 45° 高度、0° 方位是 15° 高度，毫无过渡）。
  // 改为真实摄影口诀的**分段线性**：
  //   正前(0°)/正逆(180°) 低角度 15°（平光/剪影感）；正侧(90°/270°) 20°；
  //   斜侧(45°/135°/315°/225°) 伦勃朗区 45°；之间线性过渡。
  // 等价于把高度视为「方位离轴线角度」的函数 —— 轴线上低、斜侧高。
  const offAxis = Math.min(
    Math.abs(az), Math.abs(az - 180), Math.abs(az - 360),
  ); // 0..90：离最近轴线（前/后）的角度
  const side = 90 - offAxis; // 0..90：离正侧轴的角度
  // offAxis=0（正前/正后）→15°；offAxis=45（斜侧）→45°；offAxis=90（正侧）→20°
  if (offAxis <= 45) return 15 + (offAxis / 45) * 30;      // 15 → 45 线性
  return 45 - ((offAxis - 45) / 45) * 25;                   // 45 → 20 线性
}

function intensityFor(az: number): number {
  if (az === 0) return 0.9;
  if (az === 180) return 0.5;
  return 0.75;
}

/** **24 个主光位**（自 0° 起每 15°）。顺序固定 = 便于测试与"上一档/下一档"操作。 */
export const KEY_LIGHTS: KeyLight[] = Array.from({ length: 24 }, (_, i) => {
  const azimuth = i * 15;
  const meta = KEY_NAMES[azimuth] ?? { name: `${azimuth}° 主光`, note: "" };
  return {
    azimuth,
    height: heightFor(azimuth),
    intensity: intensityFor(azimuth),
    kelvin: azimuth >= 90 && azimuth <= 270 ? 3200 : 5600,
    name: meta.name,
    note: meta.note,
  };
});

export interface RimLight {
  name: string;
  /** 描述用（不参与计算）：从哪个方向勾勒 */
  from: string;
  note: string;
  /**
   * 俯视方位角（度，与 `KeyLight.azimuth` 同口径：0=镜头方向，顺时针）。
   * **可选**：缺省表示"这一档不点灯"（如「无轮廓光」「环境轮廓」只管提示词/交给环境光）。
   * 2026-10-12 新增：让 3D 导演台也能按同一个方位把轮廓灯摆到位（此前只能盲选）。
   */
  azimuth?: number;
  /** 高度角（度，0=与主体同高，90=正上方，负值=低于主体）。与 `azimuth` 成对出现。 */
  height?: number;
  /**
   * 需要**多盏**轮廓灯时的方位列表（如「双侧轮廓」= 左 120° + 右 240°）。
   * 给出时优先于 `azimuth`（`azimuth` 仍保留作单盏口径/测试锚点）。
   */
  azimuths?: number[];
}

/**
 * **9 组轮廓光**。
 *
 * `azimuth`/`height`（2026-10-12 新增，**可选**）是给 3D 导演台用的**结构化**摆位口径：
 * 只给「真的要打一盏灯」的档位填值；「无轮廓光」「环境轮廓」**不填** ⇒ 3D 侧不点灯
 * （前者是"什么也不要"、后者是"交给环境光/IBL"，都不是一盏具体方位的灯）。
 */
export const RIM_LIGHTS: RimLight[] = [
  { name: "无轮廓光", from: "—", note: "只保留主光，最干净" },
  { name: "后上 30° 轮廓", from: "后上方 30°", note: "发丝与肩顶微微起亮", azimuth: 180, height: 30 },
  { name: "后上 45° 轮廓", from: "后上方 45°", note: "最通用的轮廓，人物从背景分离", azimuth: 180, height: 45 },
  { name: "后上 60° 轮廓", from: "后上方 60°", note: "更靠后，边缘更细更利", azimuth: 180, height: 60 },
  { name: "正后 180° 轮廓", from: "正后方", note: "对称双边亮线，仪式感", azimuth: 180, height: 15 },
  {
    name: "双侧轮廓",
    from: "左右各 120°",
    note: "两条边线，适合动作/对峙",
    azimuth: 120,
    height: 30,
    azimuths: [120, 240],
  },
  { name: "顶轮廓", from: "正上方", note: "只在头顶与肩线，压出帽檐感", azimuth: 0, height: 90 },
  { name: "底补轮廓", from: "下方 60°", note: "少见的地面反光感，适合惊悚", azimuth: 0, height: -60 },
  { name: "环境轮廓", from: "背景反射", note: "不指定方向，交给环境光" },
].map((r) => r as RimLight);

// ── 受管提示词块 ─────────────────────────────────────────────────────

export const BLOCK_OPEN = "〔光照：";
export const BLOCK_CLOSE = "〕";

export interface LightingChoice {
  /** 主光方位角（KEY_LIGHTS 里的一档） */
  keyAzimuth: number;
  /** 轮廓光名（RIM_LIGHTS 里的一项） */
  rimName: string;
}

export function keyLightAt(azimuth: number): KeyLight | undefined {
  return KEY_LIGHTS.find((k) => k.azimuth === azimuth);
}

export function rimLightNamed(name: string): RimLight | undefined {
  return RIM_LIGHTS.find((r) => r.name === name);
}

/** 生成**块内文本**（不含包裹符号），例如 `伦勃朗光（主光 45°/高度 45°/3200K）+ 后上 45° 轮廓`。 */
export function buildLightingText(choice: LightingChoice): string {
  const k = keyLightAt(choice.keyAzimuth);
  const r = rimLightNamed(choice.rimName);
  const parts: string[] = [];
  if (k) {
    parts.push(`${k.name}（主光 ${k.azimuth}°/高度 ${k.height}°/${k.kelvin}K）`);
  } else {
    parts.push(`主光 ${choice.keyAzimuth}°`);
  }
  if (r && r.name !== "无轮廓光") parts.push(r.from + "轮廓");
  return parts.join(" + ");
}

/** 生成完整块（含包裹符号）。 */
export function buildLightingBlock(choice: LightingChoice): string {
  return `${BLOCK_OPEN}${buildLightingText(choice)}${BLOCK_CLOSE}`;
}

/** 去掉提示词里**我们写过的**光照块（用户自己的文字不受影响）。 */
export function stripLightingBlock(prompt: string): string {
  const p = prompt || "";
  const i = p.indexOf(BLOCK_OPEN);
  if (i < 0) return p;
  const j = p.indexOf(BLOCK_CLOSE, i + BLOCK_OPEN.length);
  if (j < 0) return p;
  return (p.slice(0, i) + p.slice(j + BLOCK_CLOSE.length)).replace(/\s{2,}/g, " ").trim();
}

/**
 * 套用灯位块：**先移除旧块再追加新块**（受管 ⇒ 反复换灯位不会越写越长）。
 * 提示词为空时只写块本身。
 */
export function applyLightingBlock(prompt: string, choice: LightingChoice): string {
  const base = stripLightingBlock(prompt);
  const block = buildLightingBlock(choice);
  return base ? `${base} ${block}` : block;
}

/** 从提示词里读回当前灯位块（没有则空串）。 */
export function readLightingBlock(prompt: string): string {
  const p = prompt || "";
  const i = p.indexOf(BLOCK_OPEN);
  if (i < 0) return "";
  const j = p.indexOf(BLOCK_CLOSE, i + BLOCK_OPEN.length);
  return j < 0 ? "" : p.slice(i, j + BLOCK_CLOSE.length);
}
