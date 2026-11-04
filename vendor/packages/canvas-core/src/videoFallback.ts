/**
 * videoFallback.ts — 视频放不出画面时的「兜底素材」与文案（2026-11-02）
 *
 * ## 为什么需要这个模块
 *
 * 画布跑在 Qt WebEngine 上，**这个内核没有 H.264/AAC**（2026-11-02 真机实测）：
 *
 * | 探测 | 结果 |
 * |---|---|
 * | `canPlayType('video/mp4; codecs="avc1.42E01E"')` | `""`（空串） |
 * | `<video src="x.mp4">` | `error.code = 4`（SRC_NOT_SUPPORTED） |
 * | `<video src="x.webm">` | 正常（`readyState = 4`） |
 *
 * 而产品自己渲染的成片正是 h264/avc1 ⇒ 视频节点原来一直是一块黑。改不了内核，
 * 但可以让它**别装作在播**：退回一张首帧图 + 一句说清原因的话。
 *
 * 纯函数单独放这里（不碰 React）：vitest 环境没有 jsdom，组件里的 effect/事件
 * 测不到，能守的就是「该选哪张图」这类判断。
 */

/** 拿来当替身封面时优先用哪张：显式封面 > 首帧 > 尾帧。 */
export function pickVideoPoster(
  posterUrl?: string | null,
  firstFrameUrl?: string | null,
  lastFrameUrl?: string | null,
): string {
  for (const u of [posterUrl, firstFrameUrl, lastFrameUrl]) {
    const s = String(u || "").trim();
    if (s && !s.startsWith("blob:")) return s;   // blob: 只在当次会话有效，存下来就是死链
  }
  return "";
}

/** 统一文案：**说清不是文件坏了**，否则用户会反复重传。 */
export const VIDEO_UNPLAYABLE_TITLE = "这台机器放不出这个 mp4 的画面";

export const VIDEO_UNPLAYABLE_HINT =
  "画布内核（Qt WebEngine）没带 H.264 解码器，不是文件坏了 —— 用剪辑器（系统播放器）打开能正常预览。";
