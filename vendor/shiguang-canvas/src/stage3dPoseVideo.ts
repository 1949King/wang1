/**
 * Stage3D 白模姿态视频采集（模式 B · 第四刀）
 * ============================================
 * 把 3D 导演台里「白模按 poseTrack 逐帧动」的过程，逐帧渲染并采集 PNG，
 * 交给后端 FFmpeg 合成 mp4 → 作为 `reference_video` 走第一刀通道。
 *
 * 架构位置：Stage3D.tsx（提供渲染/读像素回调） → 本模块（编排 + 诚实失败） → bridge.ts（上传）
 *
 * 为什么不在前端实时录制（`MediaRecorder`）：
 *   1. 录到的是「实时发生」的过程 —— 渲染一慢就掉帧，而运动参考视频恰恰最怕掉帧；
 *   2. 主画面 canvas 是 `preserveDrawingBuffer:false`（Stage3D.tsx 有注释说明原因），
 *      实时录制拿不到稳定像素；开 `preserveDrawingBuffer` 又要每帧复制全屏缓冲，代价大。
 *   逐帧导出则是「要哪帧渲染哪帧」，帧率精确，且复用既有的离屏 RenderTarget 读像素机制。
 *
 * 本模块刻意**不依赖 THREE**：渲染与读像素通过回调注入，
 * 于是「帧规划 / 诚实失败 / 上传」这些逻辑可以脱离 WebGL 单测。
 */

import { poseVideoEncodeViaHost } from "./bridge";

/** 帧数硬上限 —— 与后端 `pose_video_service.MAX_FRAMES` 及 `pose_worker --max-frames` 三者对齐 */
export const MAX_POSE_VIDEO_FRAMES = 900;

/** 默认帧率，与 `pose_test.json` 实测的 25fps 对齐 */
export const DEFAULT_POSE_VIDEO_FPS = 25;

export type PoseVideoPlan = {
  /** 实际要采集的轨迹帧下标（可能因超上限而抽稀） */
  indices: number[];
  /** 抽稀步长（1 = 逐帧） */
  step: number;
  /** 是否因超过上限而抽稀 */
  capped: boolean;
};

/**
 * 纯函数：按上限规划要采集哪些帧。
 *
 * 两个刻意的设计选择：
 *  1. **超上限时抽稀，不截断** —— 截断会丢掉动作后半段，白模"动到一半停住"，
 *     比抽稀更糟（抽稀至少保住整段动作的节奏）；
 *  2. **保首尾** —— 均匀取 `limit` 个下标，且**必含第 0 帧与最后一帧**。
 *     首帧是起始姿态、尾帧是收尾姿态，丢了任何一个都会让动作看起来被切掉一截。
 *
 * 注意不要用 `step = ceil(total / limit)` 那种写法：total=1000/limit=900 时
 * step=2 只能取到 500 帧（白白丢一半），而且 `i += step` 循环取不到最后一帧。
 */
export function planPoseVideoFrames(
  totalFrames: number,
  cap: number = MAX_POSE_VIDEO_FRAMES,
): PoseVideoPlan {
  const total = Math.max(0, Math.floor(totalFrames || 0));
  const limit = Math.max(1, Math.floor(cap || 1));
  if (total <= limit) {
    return { indices: Array.from({ length: total }, (_, i) => i), step: 1, capped: false };
  }
  if (limit === 1) {
    return { indices: [0], step: total, capped: true };
  }
  const indices: number[] = [];
  const span = total - 1;
  for (let k = 0; k < limit; k++) {
    indices.push(Math.round((k * span) / (limit - 1)));
  }
  return { indices, step: span / (limit - 1), capped: true };
}

/** 渲染源：由 Stage3D 注入（把姿态应用到角色 → 渲染到离屏 RT → 读像素） */
export type PoseFrameSource = {
  /** 应用第 i 帧姿态并渲染到离屏 RenderTarget */
  renderFrameToRT: (frameIndex: number) => void;
  /** 从离屏 RenderTarget 读像素，返回 `data:image/png;base64,...` */
  readRTAsDataUrl: () => string;
};

export type CaptureResult = {
  ok: boolean;
  message?: string;
  frames: string[];
  step: number;
  capped: boolean;
};

/**
 * 逐帧采集。每帧之间让出主线程（`setTimeout(0)`），避免长循环冻死 UI。
 *
 * 诚实失败：帧数为 0 / 回调抛错 / 某帧读出空白 → 返回 ok:false + 原因（不产半成品）。
 */
export async function capturePoseFrames(
  source: PoseFrameSource,
  totalFrames: number,
  opts: { cap?: number; onProgress?: (done: number, total: number) => void } = {},
): Promise<CaptureResult> {
  const plan = planPoseVideoFrames(totalFrames, opts.cap ?? MAX_POSE_VIDEO_FRAMES);
  if (!plan.indices.length) {
    return {
      ok: false,
      message: "没有可采集的帧（关键点轨迹为空，请先解析姿态）",
      frames: [],
      step: plan.step,
      capped: plan.capped,
    };
  }

  const frames: string[] = [];
  const total = plan.indices.length;
  for (let k = 0; k < total; k++) {
    const idx = plan.indices[k];
    try {
      source.renderFrameToRT(idx);
    } catch (e) {
      return {
        ok: false,
        message: `渲染第 ${idx + 1} 帧失败：${(e as Error)?.message || e}`,
        frames: [],
        step: plan.step,
        capped: plan.capped,
      };
    }
    let url = "";
    try {
      url = source.readRTAsDataUrl();
    } catch (e) {
      return {
        ok: false,
        message: `读取第 ${idx + 1} 帧像素失败：${(e as Error)?.message || e}`,
        frames: [],
        step: plan.step,
        capped: plan.capped,
      };
    }
    // WebGL 离屏读取偶尔会返回空 —— 不当成"成功但空帧"，直接诚实失败
    if (!url || !url.startsWith("data:image/")) {
      return {
        ok: false,
        message: `第 ${idx + 1} 帧读到空白画面（离屏渲染未就绪），已中止，不产出半成品视频`,
        frames: [],
        step: plan.step,
        capped: plan.capped,
      };
    }
    frames.push(url);
    if (opts.onProgress && (k % 5 === 0 || k === total - 1)) {
      opts.onProgress(k + 1, total);
    }
    // 让出主线程，避免长循环把界面冻住
    await new Promise((r) => setTimeout(r, 0));
  }

  return { ok: true, frames, step: plan.step, capped: plan.capped };
}

export type EncodeResult = {
  ok: boolean;
  message?: string;
  url?: string;
  /** 后端落盘后的本机绝对路径 —— 送剪辑时间线时回传它（画布是 WebView，读不了本地文件） */
  path?: string;
  frames?: number;
  fps?: number;
  duration?: number;
  bytes?: number;
};

/** 把采集到的帧交后端合成 mp4。失败原因原样透传（后端已给中文可读 message）。 */
export async function encodePoseVideo(
  frames: string[],
  fps: number = DEFAULT_POSE_VIDEO_FPS,
  name = "pose_motion",
): Promise<EncodeResult> {
  if (!frames?.length) {
    return { ok: false, message: "没有可合成的帧（请先采集白模动作）" };
  }
  try {
    return await poseVideoEncodeViaHost({ frames, fps, name });
  } catch (e) {
    return { ok: false, message: `上传帧序列失败：${(e as Error)?.message || e}` };
  }
}
