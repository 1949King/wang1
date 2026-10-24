/**
 * YuE（乐）全曲生成桥 —— 符号规划 / 渲染整曲 / 执行端探测。
 *
 * 2026-09-28 适配进画布「音乐节点 + 意图磁吸卡片」。
 * 单独成模块的原因：bridge.ts 顶到规模守卫容差（存量文件只许减不许增），
 * 且 YuE 是内聚的独立能力（谱面规划 → 编辑 → 渲染），与 Suno 黑盒链路正交。
 *
 * 三段式与「意图卡片」的对应：
 *   yuePlanViaHost   → 产出可编辑的旋律+和弦 ABC 谱（卡片上「你的意图」）
 *   yueRenderViaHost → 把（可能被用户改过的）谱渲染成 48kHz 整曲（「系统的事」）
 *   yueProbeViaHost  → 探测执行端是否就绪，未就绪时 UI 诚实展示安装指引
 */

import { BRIDGE, authHeaders, bridgeToken } from "./bridge";

const YUE = {
  probe: "/host/yue/probe",
  plan: "/host/yue/plan",
  generate: "/host/yue/generate",
  transcribe: "/host/yue/transcribe",
} as const;

/** YuE 执行端探测结果（UI 据此决定是否启用 YuE 入口） */
export type YueProbe = {
  ok: boolean;
  available: boolean;
  mode?: "remote" | "local" | "";
  detail?: string;
  /** 翻唱前置（SheetSage2 转录）是否可用——与生成端分别探测（官方要求不同环境） */
  transcribe?: boolean;
  hint?: string;
  transcribe_hint?: string;
  need?: string;
};

/** cot 取值（对齐官方语义）：full=旋律+和弦可编辑；melody=旋律+自由伴奏（翻唱）；off=直接生成 */
export type YueCot = "full" | "melody" | "off";

async function postJson(path: string, body: Record<string, unknown>): Promise<any> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}${path}?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `YuE 请求异常: ${e}` };
  }
}

export async function yueProbeViaHost(): Promise<YueProbe> {
  return postJson(YUE.probe, {});
}

/** 符号规划：歌词 + 风格 → 可编辑的 ABC 谱（不出音频，快且省钱） */
export async function yuePlanViaHost(opts: {
  lyrics?: string; style?: string; cot?: YueCot; seed?: number;
}): Promise<{ ok: boolean; message?: string; abc?: string; cot?: string; hint?: string; unavailable?: boolean }> {
  return postJson(YUE.plan, {
    lyrics: opts.lyrics || "",
    style: opts.style || "",
    cot: opts.cot || "full",
    ...(typeof opts.seed === "number" ? { seed: opts.seed } : {}),
  });
}

/** 渲染整曲：abc 非空即「编辑模式」（按用户改过的谱渲染出全新录音） */
export async function yueRenderViaHost(opts: {
  lyrics?: string; style?: string; abc?: string; cot?: YueCot;
  seed?: number; title?: string;
}): Promise<{ ok: boolean; message?: string; audio_url?: string; abc?: string; hint?: string; unavailable?: boolean }> {
  return postJson(YUE.generate, {
    lyrics: opts.lyrics || "",
    style: opts.style || "",
    abc: opts.abc || "",
    cot: opts.cot || "full",
    title: opts.title || "",
    ...(typeof opts.seed === "number" ? { seed: opts.seed } : {}),
  });
}

/** 翻唱前置：参考曲 → 旋律乐谱（SheetSage2 独立环境，只留旋律去和弦）。
 *  ⚠️ 转录错误会带进翻唱 ⇒ 拿到的谱应让用户先审阅再渲染。 */
export async function yueTranscribeViaHost(opts: {
  audio: string; melodyOnly?: boolean;
}): Promise<{ ok: boolean; message?: string; abc?: string; cot?: string; hint?: string; unavailable?: boolean }> {
  return postJson(YUE.transcribe, {
    audio: opts.audio,
    melody_only: opts.melodyOnly !== false,
  });
}
