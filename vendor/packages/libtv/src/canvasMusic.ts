/**
 * 音乐节点生成编排 —— 从 App.tsx 抽出（2026-09-28）。
 *
 * 抽取理由：
 *  1. App.tsx 逼近规模守卫阈值（>2000 行）；音乐分支含 Suno / YuE 两条链路，
 *     内聚且与 App 的其余逻辑无关，适合独立。
 *  2. YuE 的「探测 → 渲染 → 回写谱面」三段逻辑需要一个明确归属，便于单测。
 *
 * 设计：本模块只做「网络调用 + 决定该写什么」，**不直接改 store**
 *   （副作用由 App.tsx 统一施加，保持单向数据流与可测性）。
 */

import { generateMusicViaHost } from "./bridge";
import { yueProbeViaHost, yueRenderViaHost } from "./canvasYue";

export type MusicGenOutcome = {
  ok: boolean;
  message: string;
  /** 失败时的安装/配置指引（YuE 未配置时由后端回传） */
  hint?: string;
  /** 成功后要写入节点的音频 URL */
  audioUrl?: string;
  /** 成功后要合并进节点数据的字段 */
  patch?: Record<string, unknown>;
};

type MusicDataLike = {
  engine?: string;
  prompt?: string;
  style?: string;
  lyrics?: string;
  abc?: string;
  cot?: "full" | "melody" | "off";
  seed?: number;
  title?: string;
  trackTitle?: string;
  instrumental?: boolean;
  model?: string;
};

export async function generateMusicForNode(opts: {
  data: MusicDataLike;
  /** 已解析的音乐模型渠道（Suno 链路用） */
  channelId: string;
  model: string;
  /** 可用音乐模型数（Suno 链路前置检查） */
  musicModelCount: number;
}): Promise<MusicGenOutcome> {
  const { data } = opts;

  // ── YuE 分支：符号规划 → 可编辑谱 → 渲染整曲 ──
  // 未配置执行端时**诚实失败**并回传安装指引（不造假音频）。
  if (data.engine === "yue") {
    const probe = await yueProbeViaHost();
    if (!probe.available) {
      return { ok: false, message: probe.need || "YuE 执行端未配置", hint: probe.hint };
    }
    const res = await yueRenderViaHost({
      lyrics: data.lyrics || "",
      style: data.style || data.prompt || "",
      abc: data.abc || "",
      cot: data.cot || "full",
      seed: data.seed,
      title: data.trackTitle || data.title || "",
    });
    if (res.ok && res.audio_url) {
      return {
        ok: true,
        message: res.message || "YuE 整曲渲染成功",
        audioUrl: res.audio_url,
        patch: {
          engine: "yue",
          // 回传（可能由规划改进过的）谱，让用户下次可继续编辑
          abc: res.abc || data.abc || "",
          yueExecutor: probe.mode || "",
          model: "YuE2-3B",
        },
      };
    }
    return { ok: false, message: res.message || "YuE 渲染失败", hint: res.hint };
  }

  // ── Suno 分支：黑盒文生音乐（原逻辑，行为不变）──
  if (!opts.musicModelCount) {
    return { ok: false, message: "无可用音乐模型，请在模型管理配置 Suno 渠道" };
  }
  const res = await generateMusicViaHost({
    prompt: data.prompt || "",
    style: data.style || "",
    lyrics: data.lyrics || "",
    title: data.trackTitle || data.title || "",
    instrumental: !!data.instrumental,
    model: opts.model,
    channel_id: opts.channelId,
  });
  if (res.ok && res.audio_url) {
    return {
      ok: true,
      message: res.message || "音乐生成成功",
      audioUrl: res.audio_url,
      patch: { title: res.title || data.title, model: res.model || opts.model },
    };
  }
  return { ok: false, message: res.message || "音乐生成失败" };
}
