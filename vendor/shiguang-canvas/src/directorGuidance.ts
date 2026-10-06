/**
 * directorGuidance.ts — 导演指导（2026-10-06，对标 LibTV「导演指导模式」的缺口）。
 *
 * 与既有能力的边界（**别重复造**）
 * ==============================
 * · 后端已有 `breakdown` 等动作：**剧本 → 分镜拆解**（从无到有）。
 * · 本模块解决的是**另一件事**：分镜**已经有了**，但"拍得平" —— 需要**诊断 + 具体改法**，
 *   并且改完能**一键写回**。这正是 LibTV「导演指导」的位置。
 *
 * ⚠️ 诚实说明：本模块是**规则驱动的导演手法库**，**不调用大模型**。
 * 它的价值在于「**诊断出缺什么，并给出影视里真的成立的改法**」，而不是假装成 AI 导演。
 * （后续要接 LLM 的话，接口就是 `diagnose()` 的返回值，不必推翻这里。）
 *
 * 为什么要有"诊断"这一步
 * ====================
 * 直接往提示词里塞「推近、特写、高对比」是**无脑堆词**：镜头本来就有景别时会被写冲突。
 * 所以先看提示词**缺什么**（景别/运镜/构图/光线/情绪/节奏），再**只补缺的那几项**。
 */
export type MoveCategory = "景别" | "运镜" | "构图" | "光线" | "情绪" | "节奏";

export interface ShotContext {
  /** 镜头提示词 */
  prompt: string;
  /** 可选的镜头名（有些流程写"镜号/镜头名"） */
  title?: string;
}

export interface DirectorMove {
  id: string;
  name: string;
  category: MoveCategory;
  /** 为什么这么改（给用户看的理由） */
  why: string;
  /** 追加到提示词的片语（**受管**：每条招式带自己的标记，见 MOVES 说明） */
  phrase: string;
}

/** 招式片语用 `〔...〕` 包裹并带 id，便于"撤销本次指导"精确移除。 */
function mark(phrase: string): string {
  return `〔${phrase}〕`;
}

export const DIRECTOR_MOVES: DirectorMove[] = [
  // 景别
  { id: "cu", name: "推到特写", category: "景别", why: "情绪要落在脸上时，特写比中景有效得多", phrase: mark("特写，面部占画面主体，浅景深") },
  { id: "ms", name: "收到中景", category: "景别", why: "交代人物关系与动作，是最耐看的常规景别", phrase: mark("中景，人物过膝或过腰入画") },
  { id: "ws", name: "拉开全景", category: "景别", why: "环境也是信息；先给全景再切入，观众才不迷糊", phrase: mark("全景，人物在环境中占比较小，交代空间") },
  { id: "ots", name: "过肩构图", category: "构图", why: "带出对话感与空间关系，比正面平铺有戏", phrase: mark("过肩视角，前景肩线虚化遮挡") },
  { id: "fore", name: "加前景遮挡", category: "构图", why: "前景一挡就有纵深，画面立刻不「平」", phrase: mark("前景有遮挡物（窗框/枝叶/门缝），形成纵深层次") },
  { id: "low", name: "降低机位", category: "构图", why: "低机位显强势/压迫，人物气场不一样", phrase: mark("低机位微仰拍，强化人物气场") },
  { id: "high", name: "抬高机位", category: "构图", why: "高机位显渺小/交代环境", phrase: mark("高机位俯拍，人物显得渺小") },
  // 运镜
  { id: "push", name: "缓慢推近", category: "运镜", why: "推 = 走近情绪，是最省力的「有戏」运镜", phrase: mark("镜头缓慢推近（dolly in），速度均匀") },
  { id: "pull", name: "缓慢拉远", category: "运镜", why: "拉 = 抽离/收尾，适合段末", phrase: mark("镜头缓慢拉远（dolly out），落幅停在环境") },
  { id: "pan", name: "横向摇移", category: "运镜", why: "交代相邻空间关系，接得自然", phrase: mark("横向匀速摇移，落幅在主体") },
  { id: "follow", name: "跟随移动", category: "运镜", why: "带出运动的连续性", phrase: mark("镜头跟随人物移动，保持主体在画面同一位置") },
  { id: "static", name: "固定机位", category: "运镜", why: "静止不是没有设计：让动作本身说话", phrase: mark("固定机位，画面构图稳定，无镜头运动") },
  // 光线
  { id: "contrast", name: "加大明暗对比", category: "光线", why: "平光最没情绪；有明暗才有体积", phrase: mark("强明暗对比，大面积暗部保留少量细节") },
  { id: "rim", name: "补轮廓光", category: "光线", why: "人物从背景里「跳」出来", phrase: mark("侧后方轮廓光勾勒边缘，主体与背景分离") },
  // 情绪
  { id: "react", name: "加反应镜头", category: "情绪", why: "只有动作没有反应，戏是「单」的 —— 反应镜头才有呼吸", phrase: mark("加入旁观者的反应镜头，给出情绪落点") },
  { id: "still", name: "静场一拍", category: "节奏", why: "该停的地方停一下，节奏才有起伏", phrase: mark("画面静止一拍，留出呼吸感") },
  { id: "fast", name: "加快剪辑点", category: "节奏", why: "紧张段靠短镜头堆出来", phrase: mark("镜头时长收紧，动作接点前置，节奏加快") },
];

/** 招式库自检（测试与守卫共用）：id/name 唯一、片语非空。 */
export function movesAreConsistent(): boolean {
  const ids = new Set<string>();
  for (const m of DIRECTOR_MOVES) {
    if (!m.id || !m.name || !m.phrase || ids.has(m.id)) return false;
    ids.add(m.id);
  }
  return true;
}

const HAS_SHOT_SIZE = /(特写|近景|中景|全景|远景|大特写|景别)/;
const HAS_CAMERA_MOVE = /(推近|拉远|摇移|跟随|移动镜头|固定机位|镜头运动|dolly|摇镜|移镜)/;
const HAS_LIGHT = /(光|明暗|逆光|侧光|伦勃朗|轮廓光|色温)/;
const HAS_EMOTION = /(情绪|表情|反应|泪|笑|怒|惊恐|沉默)/;
const HAS_DEPTH = /(前景|遮挡|纵深|过肩|层次)/;

export interface Diagnosis {
  /** 缺失的维度（按优先级） */
  missing: MoveCategory[];
  /** 已有的维度（让用户知道"这些你已经写了"，不是无脑补） */
  present: MoveCategory[];
  /** 一句总评（给用户看） */
  summary: string;
}

/**
 * 诊断一个镜头缺什么。**这是"指导"与"堆词"的分界线**：已经写了的维度不会再建议。
 */
export function diagnose(shot: ShotContext): Diagnosis {
  const p = (shot.prompt || "") + " " + (shot.title || "");
  const present: MoveCategory[] = [];
  const missing: MoveCategory[] = [];
  const check = (cat: MoveCategory, re: RegExp) => (re.test(p) ? present : missing).push(cat);
  check("景别", HAS_SHOT_SIZE);
  check("运镜", HAS_CAMERA_MOVE);
  check("构图", HAS_DEPTH);
  check("光线", HAS_LIGHT);
  check("情绪", HAS_EMOTION);
  if (!p.trim()) {
    return { missing: ["景别", "运镜", "构图", "光线", "情绪"], present: [],
             summary: "这个镜头还没有提示词 —— 先写一句「谁在哪做什么」，再用下面的招式补细。" };
  }
  const summary = missing.length
    ? `缺少：${missing.join(" · ")}（已写：${present.join(" · ") || "无"}）`
    : "六个维度都写到了 —— 现在要做的不是继续加词，而是删到只留最想说的那一句。";
  return { missing, present, summary };
}

/** 按诊断结果给出**建议招式**（只建议缺失维度里的），returns 建议的 move id 列表。 */
export function suggestMoves(shot: ShotContext): string[] {
  const d = diagnose(shot);
  const byCat = (c: MoveCategory) => DIRECTOR_MOVES.filter((m) => m.category === c);
  const out: string[] = [];
  const pick = (c: MoveCategory, id: string) => {
    if (!d.missing.includes(c)) return;
    const m = byCat(c).find((x) => x.id === id) || byCat(c)[0];
    if (m) out.push(m.id);
  };
  pick("景别", "ms");
  pick("运镜", "push");
  pick("构图", "fore");
  pick("光线", "contrast");
  pick("情绪", "react");
  return out;
}

export function moveById(id: string): DirectorMove | undefined {
  return DIRECTOR_MOVES.find((m) => m.id === id);
}

/** 从提示词里移除**某一条**我们的招式片语（撤销单条）。 */
export function stripMove(prompt: string, moveId: string): string {
  const m = moveById(moveId);
  if (!m) return prompt;
  return (prompt || "").replace(m.phrase, "").replace(/\s{2,}/g, " ").trim();
}

/** 移除**所有**我们的招式片语（"撤销本次指导"）。用户自己的文字不受影响。 */
export function stripAllMoves(prompt: string): string {
  let out = prompt || "";
  for (const m of DIRECTOR_MOVES) out = out.split(m.phrase).join("");
  return out.replace(/\s{2,}/g, " ").trim();
}

/** 当前提示词里已应用了哪些招式（用于面板回显与撤销）。 */
export function appliedMoves(prompt: string): string[] {
  const p = prompt || "";
  return DIRECTOR_MOVES.filter((m) => p.includes(m.phrase)).map((m) => m.id);
}

/**
 * 组合出**应用这些招式后的完整提示词**（先把旧招式去掉再加，保证**幂等**、不叠加）。
 */
export function composePrompt(prompt: string, moveIds: string[]): string {
  const base = stripAllMoves(prompt);
  const phrases = moveIds
    .map((id) => moveById(id)?.phrase)
    .filter((x): x is string => Boolean(x));
  if (!phrases.length) return base;
  return base ? `${base} ${phrases.join("")}` : phrases.join("");
}
