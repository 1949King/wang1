/**
 * 指令式视频编辑 → 画布结果映射（P1-2 步骤 4，2026-10-15）
 * ======================================================
 * 后端契约在 `app/core/canvas_routes_post.py` 的 `/host/video-edit` 与
 * `app/core/ai/video_edit_client.py` 的 `edit_video`，本层只做**诚实映射**：
 *   - original_kept / channel_used / cost_note / errors **逐字透传**，不美化、不合并；
 *   - 失败时 clip_path 是**原片段**（后端「失败保原镜」语义），绝不显示成新结果；
 *   - url 是后端把结果**复制**进 inbox 后的可播放 `/inbox_file/` 路径；
 *     空 url（复制失败或失败响应）时只展示磁盘路径文本，不拼假地址。
 *
 * ⚠️ 出域纪律：两个编辑渠道都是云端（Seedance Base64 直传 / Kling 公网 URL），
 * 素材必然出域 ⇒ UI 必须显式勾选同意，本层做二次校验（egressAck，未勾不打网络）。
 */
import { videoEdit } from "./bridgeStoryboard";

export type VideoEditChannel = "auto" | "seedance" | "kling";

export type VideoEditOutcome = {
  ok: boolean;
  /** 成功=新片段磁盘路径；失败=原片段路径（原镜保留） */
  clipPath: string;
  /** 可播放 URL（/inbox_file/…）。仅成功且后端 inbox 复制成功时非空 */
  url: string;
  originalKept: boolean;
  channelUsed: string;
  costNote: string;
  /** 各渠道失败原因，逐字透传 */
  errors: string[];
  message: string;
};

/** 纯函数：后端响应 → UI 结果。缺字段按诚实兜底，不美化。 */
export function summarizeVideoEdit(res: {
  ok: boolean;
  clip_path?: string;
  url?: string;
  original_kept?: boolean;
  channel_used?: string;
  cost_note?: string;
  errors?: string[];
  message?: string;
}): VideoEditOutcome {
  return {
    ok: Boolean(res.ok),
    clipPath: String(res.clip_path || ""),
    // 失败响应即便带了 url 也不显示 —— 没有结果就没有可播放地址
    url: res.ok ? String(res.url || "") : "",
    // 后端一定回 original_kept；缺失时保守兜底：失败=原镜保留，成功=出了新片段
    originalKept:
      res.original_kept === undefined ? !res.ok : Boolean(res.original_kept),
    channelUsed: String(res.channel_used || ""),
    costNote: String(res.cost_note || ""),
    errors: Array.isArray(res.errors) ? res.errors.map(String) : [],
    message: String(res.message || (res.ok ? "" : "指令式编辑失败")),
  };
}

/**
 * 执行一次指令式编辑（画布「编辑指令卡」的唯一入口）。
 * 本地预检不过（空指令/无素材/未勾出域/Kling 无公网 URL）⇒ 直接失败回文案，不打网络。
 */
export async function runVideoEdit(input: {
  clipPath: string;
  instruction: string;
  channel?: VideoEditChannel;
  videoUrl?: string;
  model?: string;
  /** 素材出域显式同意（两个渠道都是云端，未勾选一律拒绝） */
  egressAck: boolean;
}): Promise<VideoEditOutcome> {
  const fail = (message: string): VideoEditOutcome => ({
    ok: false,
    clipPath: input.clipPath || "",
    url: "",
    originalKept: true,
    channelUsed: "",
    costNote: "",
    errors: [],
    message,
  });
  if (!input.instruction.trim()) return fail("请先填写编辑指令");
  if (!input.clipPath && !(input.videoUrl || "").trim()) {
    return fail("需要本地片段或公网视频 URL 至少其一");
  }
  if (!input.egressAck) {
    return fail("编辑渠道均为云端处理，素材会出域；请先勾选允许发送到云端");
  }
  if ((input.channel || "auto") === "kling" && !(input.videoUrl || "").trim()) {
    return fail("可灵编辑需公网视频 URL（素材出域，需显式提供）");
  }
  try {
    const res = await videoEdit({
      clip_path: input.clipPath,
      instruction: input.instruction.trim(),
      channel: input.channel || "auto",
      video_url: (input.videoUrl || "").trim(),
      model: input.model || "",
    });
    return summarizeVideoEdit(res);
  } catch (e) {
    return fail(`指令式编辑异常: ${e}`);
  }
}
