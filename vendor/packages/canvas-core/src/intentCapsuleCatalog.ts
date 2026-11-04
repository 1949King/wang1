/**
 * 意图胶囊目录（2026-10-20 · 画布「全能」第一刀）
 *
 * 用户的判断：**画布的全能来自「节点」与「意图胶囊节点」**。
 * 节点回答「系统能做什么」，胶囊回答「人想做什么」——本文件把两者接在一张表上：
 *
 *   IntentCapsule（surface / semantic / implementation 三层）
 *      ├─ nodeKinds    → 复用专业节点（数据模型与专业模式同一份 node.data）
 *      └─ capabilities → 后端能力 id（Agent / 面板可调）
 *
 * 纪律：
 * - **纯数据 + 纯函数**，零 React / 零 store / 零副作用；
 * - 不复制节点组件，不复制能力实现；capability id 必须存在于后端能力目录
 *   （由 `_verify/check_canvas_capsule_catalog.py` 静态对账）；
 * - 新增胶囊 = 加一行；改能力先改后端目录，再回来对账。
 */

export type CapsuleStage = "idea" | "script" | "storyboard" | "generate" | "edit" | "deliver" | "govern";

export interface IntentCapsule {
  /** 稳定 id（localStorage / Agent 事件引用） */
  id: string;
  title: string;
  stage: CapsuleStage;
  /** 复用哪些专业节点 kind（与 ports.ts 的节点 kind 对齐） */
  nodeKinds: string[];
  /** 可调用的后端能力 id（必须存在于 agent_capability_catalog） */
  capabilities: string[];
  /** 表面层：用户看到的 */
  surface: string;
  /** 语义层：用户的意图 */
  semantic: string;
  /** 实现层：系统的事 */
  implementation: string;
}

export const STAGE_LABELS: Record<CapsuleStage, string> = {
  idea: "选题立意",
  script: "剧本分镜",
  storyboard: "分镜美术",
  generate: "生成抽卡",
  edit: "精剪",
  deliver: "成片交付",
  govern: "质检治理",
};

export const INTENT_CAPSULES: IntentCapsule[] = [
  {
    id: "capsule.idea",
    title: "立意卡",
    stage: "idea",
    nodeKinds: ["script", "note"],
    capabilities: ["pipeline.generate_script", "pipeline.script_write"],
    surface: "写一句立意，拿到可拍的选题方向",
    semantic: "题材 / 受众 / 情绪 / 合规预判",
    implementation: "LLM 生成 + 合规启发式；不直接成片",
  },
  {
    id: "capsule.script",
    title: "剧本分镜卡",
    stage: "script",
    nodeKinds: ["script", "shotlist", "storyboard", "directorCard"],
    capabilities: ["pipeline.director_breakdown", "canvas.breakdown", "canvas.fill_storyboard_cell"],
    surface: "一段剧本 → 可编辑的分镜表",
    semantic: "场次 / 镜头 / 景别 / 运镜 / 时长",
    implementation: "导演拆解 + 分镜表节点；缺时长不猜",
  },
  {
    id: "capsule.character",
    title: "角色卡",
    stage: "storyboard",
    nodeKinds: ["character", "image"],
    capabilities: ["pipeline.character_anchor", "canvas.generate_image"],
    surface: "角色设定 + 三视图/参考图",
    semantic: "人物一致性 / 形象锚点",
    implementation: "角色库 + character_anchor；跨镜复用",
  },
  {
    id: "capsule.scene",
    title: "场景卡",
    stage: "storyboard",
    nodeKinds: ["image", "shot"],
    capabilities: ["canvas.generate_image", "canvas.reference_breakdown_l2"],
    surface: "场景参考图与镜头构图",
    semantic: "地点 / 光线 / 景别",
    implementation: "生图 + 深度拉片（测不出给空串）",
  },
  {
    id: "capsule.image",
    title: "生图卡",
    stage: "generate",
    nodeKinds: ["image", "generator", "prompt"],
    capabilities: ["canvas.generate_image", "canvas.best_of_draw", "canvas.repair_image", "canvas.ai_upscale"],
    surface: "一句话 / 参考图 → 候选图",
    semantic: "画面、风格、比例、质量档",
    implementation: "抽卡选优 + 局部重绘 + 超分；全量入账",
  },
  {
    id: "capsule.video",
    title: "生视频卡",
    stage: "generate",
    nodeKinds: ["video", "generator"],
    capabilities: ["canvas.generate_video", "canvas.image_to_video", "canvas.segment_retake", "canvas.video_edit"],
    surface: "首帧 / 参考 → 视频片段",
    semantic: "运动、时长、镜头语言",
    implementation: "i2v 硬约束（无首帧诚实报错）+ 局部重拍 + 指令编辑",
  },
  {
    id: "capsule.audio",
    title: "配音音乐卡",
    stage: "generate",
    nodeKinds: ["audio", "music"],
    capabilities: ["canvas.dub_orchestrate", "canvas.yue_render", "pipeline.tts_polish"],
    surface: "台词 → 配音；歌词 → 音乐",
    semantic: "音色 / 情绪 / 节奏",
    implementation: "TTS 正音切段 + YuE/Suno；无配置诚实失败",
  },
  {
    id: "capsule.digitalHuman",
    title: "数字人卡",
    stage: "generate",
    nodeKinds: ["digitalHuman", "audio"],
    capabilities: ["canvas.dub_orchestrate", "editor.set_clip_volume"],
    surface: "形象 + 台词 → 数字人口播",
    semantic: "形象 / 姿态 / 口型",
    implementation: "TTS + 形象；口型无模型不假成功",
  },
  {
    id: "capsule.stage3d",
    title: "导演台卡",
    stage: "storyboard",
    nodeKinds: ["director", "directorCard"],
    capabilities: ["canvas.stage3d_text_plan", "pipeline.director_camera_plan"],
    surface: "3D 摆位 / 机位 / 截图回写",
    semantic: "机位、运镜、灯光、构图",
    implementation: "Stage3D 场景 + 截图回写镜头卡",
  },
  {
    id: "capsule.edit",
    title: "精剪卡",
    stage: "edit",
    nodeKinds: ["video", "audio", "shot", "shotlist"],
    capabilities: [
      "editor.precision_audit",
      "editor.precision_align_plan",
      "editor.rough_cut_plan",
      "editor.burn_subtitles",
    ],
    surface: "时间线精修：切、移、帧对齐、字幕",
    semantic: "节奏 / 帧级对齐 / 音画关系",
    implementation: "store 写回 + 可撤销；审计只报测到的",
  },
  {
    id: "capsule.deliver",
    title: "交付卡",
    stage: "deliver",
    nodeKinds: ["video", "shotlist"],
    capabilities: ["editor.rough_cut_export", "pipeline.code_video_plan", "pipeline.code_video_render"],
    surface: "导出成片 / 代码成片",
    semantic: "平台、画幅、时长、字幕",
    implementation: "RenderManager / 代码×扩散渲染；失败带 stage",
  },
  {
    id: "capsule.govern",
    title: "质检卡",
    stage: "govern",
    nodeKinds: ["shot", "video"],
    capabilities: ["pipeline.score", "pipeline.aesthetic_gate", "pipeline.route_problem"],
    surface: "五维评分 + 闸门结论",
    semantic: "能不能进下游 / 要不要重拍",
    implementation: "评分 → 闸门 pass/review/block → 问题路由",
  },
];

export function capsuleById(id: string): IntentCapsule | undefined {
  return INTENT_CAPSULES.find((c) => c.id === id);
}

export function capsulesForStage(stage: CapsuleStage): IntentCapsule[] {
  return INTENT_CAPSULES.filter((c) => c.stage === stage);
}

export function allNodeKinds(): string[] {
  const seen: string[] = [];
  for (const capsule of INTENT_CAPSULES) {
    for (const kind of capsule.nodeKinds) if (!seen.includes(kind)) seen.push(kind);
  }
  return seen;
}

export function allCapabilityIds(): string[] {
  const seen: string[] = [];
  for (const capsule of INTENT_CAPSULES) {
    for (const cap of capsule.capabilities) if (!seen.includes(cap)) seen.push(cap);
  }
  return seen;
}

/** 覆盖矩阵：每个阶段有多少胶囊 / 节点 / 能力（给能力面板与守卫用）。 */
export function stageCoverage(): Array<{
  stage: CapsuleStage;
  label: string;
  capsules: number;
  nodeKinds: number;
  capabilities: number;
}> {
  const stages = Object.keys(STAGE_LABELS) as CapsuleStage[];
  return stages.map((stage) => {
    const list = capsulesForStage(stage);
    const nodes = new Set<string>();
    const caps = new Set<string>();
    for (const c of list) {
      c.nodeKinds.forEach((k) => nodes.add(k));
      c.capabilities.forEach((cap) => caps.add(cap));
    }
    return {
      stage,
      label: STAGE_LABELS[stage],
      capsules: list.length,
      nodeKinds: nodes.size,
      capabilities: caps.size,
    };
  });
}

/** 节点覆盖矩阵：每个节点 kind 被哪些胶囊/能力覆盖（C6 缺口盘点的数据源）。 */
export interface NodeCoverageRow {
  kind: string;
  capsules: string[];
  capabilities: string[];
}

export function nodeCoverage(): NodeCoverageRow[] {
  const map = new Map<string, { capsules: string[]; capabilities: Set<string> }>();
  for (const capsule of INTENT_CAPSULES) {
    for (const kind of capsule.nodeKinds) {
      if (!map.has(kind)) map.set(kind, { capsules: [], capabilities: new Set() });
      const row = map.get(kind)!;
      if (!row.capsules.includes(capsule.id)) row.capsules.push(capsule.id);
      capsule.capabilities.forEach((cap) => row.capabilities.add(cap));
    }
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([kind, row]) => ({
      kind,
      capsules: row.capsules,
      capabilities: Array.from(row.capabilities).sort(),
    }));
}

/** 缺口盘点：给定全部节点 kind，返回**未被任何意图胶囊引用**的辅助节点。 */
export function uncoveredNodeKinds(allKinds: string[]): string[] {
  const covered = new Set(allNodeKinds());
  return allKinds.filter((kind) => !covered.has(kind)).sort();
}
