/**
 * 分镜/拉片族薄封装（2026-10-14 自 bridge.ts 拆出）
 * ======================================================
 * 背景：bridge.ts 已顶单文件规模守卫基线（check_file_size 只许减不许增）。
 * 本文件承接**拉片/分镜/机位/记忆规划**四个方向的 fetch 薄封装，
 * 只依赖 bridge.ts 的三个底层符号（BRIDGE / bridgeToken / authHeaders），
 * 零业务逻辑。bridge.ts 以 re-export 保持既有 import 路径不变。
 */
import { BRIDGE, bridgeToken, authHeaders } from "./bridge";

export type StoryboardShot = {
  id?: number;
  duration?: number;
  shot?: string;
  description?: string;
  dialogue?: string;
  /**
   * 这一镜在故事里的作用（2026-11-15 加）。
   * 后端 `canvas_aigc.storyboard_breakdown` 产出，取值 setup/advance/turn/close；
   * 也可能缺失或为中文（LLM 不确定），前端用 `normalizeShotPurpose` 归一。
   */
  purpose?: string;
};

/** 一键拉片：剧本 → 分镜表（宿主 LLM，失败用启发式） */
export async function breakdownStoryboard(script: string): Promise<{
  ok: boolean;
  shots: StoryboardShot[];
  fallback?: boolean;
  message?: string;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/storyboard-breakdown?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ script }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, shots: [], message: `HTTP ${res.status}` };
  }
}

/** 相机路径规划结果：镜像后端 StageCamera 结构 + 运镜 pathPoints */
export type CameraPlanShot = {
  id: string;
  name: string;
  position: [number, number, number];
  lookAt: [number, number, number];
  fov: number;
  shotSize?: string;
  movement?: string;
  pathPoints?: { pos: [number, number, number]; look: [number, number, number] }[];
  pathDuration?: number;
};

/** 一键拉片（视频）单镜：镜像后端 /host/video-storyboard 的 shots 行 */
export type VideoStoryboardShot = {
  id?: number;
  start?: number;
  end?: number;
  duration?: number;
  shot?: string;
  camera?: string;
  description?: string;
  dialogue?: string;
  tone?: string;
  brightness?: number;
  frame?: string | null;
};

/** 一键拉片：参考视频 → 可编辑分镜表（后端检测镜头边界 + 抽帧 + 色调/景别） */
export async function videoStoryboard(input: {
  path?: string;
  url?: string;
  max_shots?: number;
  use_llm?: boolean;
  vision_model?: string;
}): Promise<{
  ok: boolean;
  shots: VideoStoryboardShot[];
  fallback?: boolean;
  scene_source?: string;
  duration?: number;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/video-storyboard?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          path: input.path || "",
          url: input.url || "",
          max_shots: input.max_shots || 30,
          use_llm: !!input.use_llm,
          vision_model: input.vision_model || "",
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, shots: [], message: "网络异常" };
  }
}

/** 逐帧拉片 L2 单镜：镜像后端 /host/reference-breakdown-l2 的 shots 行 */
export type ReferenceBreakdownL2Shot = {
  index?: number;
  start?: number;
  end?: number;
  duration?: number;
  /** 景别（仅 use_vision=true 且云端视觉解析成功时才有值，否则空串——后端不编造） */
  景别?: string;
  /** 运镜中文词（推/拉/摇）；置信度不足或视觉结论为「固定」时为空串 */
  运镜?: string;
  /** 画面描述（云端视觉 enrich 时截断到 60 字） */
  描述?: string;
  keyframe?: string;
  motion?: number | null;
  brightness?: number | null;
  contrast?: number | null;
  /** 深度运镜推断详情（CV 术语 + 置信度，与「运镜」列互不覆盖） */
  camera_move?: { move?: string; confidence?: number; reason?: string };
  camera_move_trusted?: boolean;
  /** 该镜是否被云端视觉 enrich 命中 */
  vision?: boolean;
};

/** 逐帧拉片 L2：参考片 → 镜头表 + 运镜深度推断（可选云端视觉景别 enrich）
 *
 * 与 videoStoryboard 的边界：本函数是「拉片镜头表」线（景别/运镜中文键，
 * app/core/reference_breakdown.py 单一真源）；videoStoryboard 是前端分镜表线
 * （shot/camera/description 英文键）。use_vision=true 时素材会出域（云端视觉模型），
 * 需用户显式开启；后端不可用时如实回 vision_used=false + vision_message。
 */
export async function referenceBreakdownL2(input: {
  video_path: string;
  out_dir?: string;
  threshold?: number;
  use_vision?: boolean;
  vision_model?: string;
}): Promise<{
  ok: boolean;
  count?: number;
  duration?: number;
  threshold?: number;
  shots: ReferenceBreakdownL2Shot[];
  table_markdown?: string;
  note?: string;
  vision_used?: boolean;
  vision_model?: string;
  vision_message?: string;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/reference-breakdown-l2?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          video_path: input.video_path,
          out_dir: input.out_dir || "",
          threshold: input.threshold ?? 0.3,
          use_vision: !!input.use_vision,
          vision_model: input.vision_model || "",
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, shots: [], message: "网络异常" };
  }
}

/** 指令式视频编辑：本地片段 + 指令 → Seedance/Kling 云端编辑（镜像后端 POST /host/video-edit）
 *
 * 边界（P1-2 步骤 4，2026-10-15）：
 *  - 两个渠道都是云端 ⇒ 素材必然出域，UI 必须让用户显式勾选同意后才调用；
 *  - 失败保原镜：后端回 original_kept=true 且 clip_path=原片段，前端不得当成新结果；
 *  - url 是后端把结果**复制**进 inbox 后的可播放 /inbox_file/ 路径（复制失败为空串，
 *    clip_path 仍是磁盘路径），空 url 时只展示路径文本、不拼假地址。
 */
export async function videoEdit(input: {
  clip_path: string;
  instruction: string;
  channel?: "auto" | "seedance" | "kling";
  video_url?: string;
  model?: string;
  out_dir?: string;
}): Promise<{
  ok: boolean;
  clip_path?: string;
  url?: string;
  original_kept?: boolean;
  channel_used?: string;
  cost_note?: string;
  errors?: string[];
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/video-edit?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          clip_path: input.clip_path || "",
          instruction: input.instruction || "",
          channel: input.channel || "auto",
          video_url: input.video_url || "",
          model: input.model || "",
          out_dir: input.out_dir || "",
        }),
      },
    );
    return await res.json();
  } catch {
    // 网络层失败同样保原镜语义：ok=false + original_kept=true，不静默
    return { ok: false, original_kept: true, message: "网络异常（编辑请求未发出或中断）" };
  }
}

/** 本机可用视觉模型（拉片用，素材不出机）：GET /host/local-vision-models */
export async function listLocalVisionModels(): Promise<{ name: string; size?: string }[]> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/local-vision-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    return data.models || [];
  } catch {
    return [];
  }
}

/** WS4#2 AI 分镜自动摆机位：分镜表 / 剧本 → 相机路径规划（经画布桥） */
export async function planStoryboardCameras(input: {
  shots?: StoryboardShot[];
  script?: string;
  use_llm?: boolean;
}): Promise<{
  ok: boolean;
  cameras: CameraPlanShot[];
  count?: number;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/storyboard-camera-plan?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          shots: input.shots,
          script: input.script || "",
          use_llm: input.use_llm || false,
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, cameras: [], message: "网络异常" };
  }
}

/** 记忆规划单行：镜像后端 app/core/ai/storyboard_memory.plan 的返回 */
export type MemoryPlanRow = {
  id: string;
  memoryType: "detail" | "meaning" | "emotion";
  label: string;
  /** t 小时后的基线保留率 0~1（后端按 memory_model 的 λ 算，前端不要自己算） */
  retention: number;
  currentDuration: number;
  suggestedDuration: number;
  delta: number;
};

/**
 * 分镜记忆规划：给定每镜的「观众记忆类型」，换算保留率与建议时长。
 *
 * 总时长守恒、按保留率加权再分配 —— 细节让位、情绪拿时长。
 * 理论依据：24h 基线保留率 细节 11.5% / 意义 61.9% / 情绪 82.5%。
 *
 * ⚠️ 保留率与分配一律由后端算（λ 的唯一真相源在 Python 侧），
 *    前端只负责选类型 + 展示回传的真值，避免两份 λ 漂移。
 */
export async function planStoryboardMemory(input: {
  rows: { id: string; memoryType?: string; duration?: number }[];
  t_hours?: number;
}): Promise<{
  ok: boolean;
  t_hours?: number;
  rows: MemoryPlanRow[];
  totalCurrent?: number;
  totalSuggested?: number;
  /**
   * 后端 `app/core/ai/storyboard_memory.py` 的 `warnings` 是 `List[str]`
   * （:162 初始化为 list、:208 原样返回），docstring 亦标`"warnings": [str]`。
   * ⚠️ 此前此处误声明为 `string`，导致前端 `setMemoryWarnings(warnings || [])`
   * 拿到 `string | never[]` 而报 TS2345（序列化字段不对称，tsc 基线 +1）。
   * 改成 string[] 与后端实际形状对齐 —— 只修类型声明，不改运行时行为。
   */
  warnings?: string[];
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/storyboard-memory-plan?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          rows: input.rows,
          ...(input.t_hours ? { t_hours: input.t_hours } : {}),
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, rows: [], message: "网络异常" };
  }
}
