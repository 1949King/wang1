/**
 * 数字人「口型成片」客户端（V4.46.4 · 2026-10-22）
 *
 * 后端契约：POST /host/digital-human/talking-video
 *   body = { image, audio, name? }  —— 二者都接受 dataURL / /inbox_file/… / inbox 裸名
 *   成功 = { ok:true, url:"/inbox_file/x.mp4", mouth_moved:false, note, lipsync_note }
 *   失败 = { ok:false, missing:[...], error, lipsync_note }
 *
 * 诚实契约（与后端同纪律）：
 *  - mouth_moved **恒为 false**（本管线是「静态形象+配音」，不是对口型）；
 *    调用方必须据此标注产物，绝不用静帧视频冒充口型同步成片。
 *  - 失败透传 missing / lipsync_note，不吞原因、不返回假 URL。
 *
 * 独立成模块：bridge.ts 已 1897/2000 行（体积基线），且「直接 fetch /host/*
 * 的前端模块必须登记进 _verify/check_canvas_routes.py CLIENTS」——已同步登记。
 */
import { BRIDGE, authHeaders } from "./bridge";

export const TALKING_VIDEO_PATH = "/host/digital-human/talking-video";

export type TalkingVideoResult = {
  ok: boolean;
  /** 成功时的可播放 URL（/inbox_file/…，WebView 只认这个形态） */
  url?: string;
  /** 恒 false：静态形象+配音，口型未动 —— 调用方必须如实标注，不得冒充对口型 */
  mouth_moved?: boolean;
  /** 合成路径：still_video / unavailable */
  path?: string;
  bytes?: number;
  note?: string;
  /** 真·口型同步引擎的可用性说明（诚实转告用户，不代做判断） */
  lipsync_note?: string;
  /** 失败时缺什么（形象图 / 配音） */
  missing?: string[];
  message?: string;
  error?: string;
};

/**
 * 合成「数字人成片」（静态形象 + 配音 → mp4，口型不动）。
 *
 * 长耗时操作（ffmpeg 秒级到分钟级）：调用方需自行置 generating 态，
 * 且**不要**在失败时重试成假成功。
 */
export async function makeTalkingVideoViaHost(opts: {
  image: string;
  audio: string;
  name?: string;
}): Promise<TalkingVideoResult> {
  const image = (opts.image || "").trim();
  const audio = (opts.audio || "").trim();
  // 前端先挡一层空输入：省一次往返，且错误文案更贴近用户操作
  const missing: string[] = [];
  if (!image) missing.push("形象图（上传或绑定镜头/图片节点）");
  if (!audio) missing.push("配音（先点「生成配音」）");
  if (missing.length) {
    return { ok: false, mouth_moved: false, missing, message: "输入不齐备，未合成" };
  }
  try {
    const res = await fetch(`${BRIDGE}${TALKING_VIDEO_PATH}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ image, audio, name: opts.name || "" }),
    });
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const out: TalkingVideoResult = {
      ok: Boolean(data?.ok) && res.ok,
      mouth_moved: false, // 后端已标，这里再钉一次：本管线永不动口型
      path: String(data?.path || ""),
      url: typeof data?.url === "string" ? data.url : undefined,
      bytes: typeof data?.bytes === "number" ? data.bytes : undefined,
      note: typeof data?.note === "string" ? data.note : undefined,
      lipsync_note: typeof data?.lipsync_note === "string" ? data.lipsync_note : undefined,
      missing: Array.isArray(data?.missing) ? (data.missing as string[]) : undefined,
      message:
        (typeof data?.message === "string" && data.message) ||
        (typeof data?.error === "string" && data.error) ||
        (res.ok ? "" : `HTTP ${res.status}`),
    };
    // 成功但没 URL = 后端行为异常 ⇒ 降级为失败，绝不返回空成功
    if (out.ok && !out.url) {
      return { ...out, ok: false, message: "合成成功但未返回可播放 URL（异常，未当作成功）" };
    }
    return out;
  } catch (e: any) {
    return {
      ok: false,
      mouth_moved: false,
      message: `请求失败：${e?.message || e}`,
    };
  }
}

/** 产物标注文案（节点/状态栏共用，避免两处各写一套口径）。 */
export function talkingVideoLabel(r: TalkingVideoResult): string {
  if (!r.ok) return r.message || "合成失败";
  return r.note || "已合成（静态形象+配音，口型未动）";
}
