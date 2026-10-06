import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { yueProbeViaHost, yuePlanViaHost, yueRenderViaHost, yueTranscribeViaHost } from "./canvasYue";

// YuE（乐）全曲生成桥回归（2026-09-28）
// 契约：三个函数分别打 /host/yue/{probe,plan,generate}，带 host token，
// 且**原样透传**用户编辑过的 abc —— 这是「可编辑乐谱」闭环的关键，
// 传丢了就退化成黑盒生成。

function jsonRes(obj: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => obj,
  } as unknown as Response;
}

// node 环境下 bridgeToken() 直接引用 window/localStorage，补最小桩（同 bridge.test.ts）
beforeEach(() => {
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(calls: { url: string; body?: any }[], reply: (url: string) => unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: any) => {
      calls.push({ url, body: init?.body ? JSON.parse(init.body) : undefined });
      return jsonRes(reply(url));
    }),
  );
}

describe("YuE 桥（canvasYue）", () => {
  it("probe 打 /host/yue/probe 并带 token", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: true, available: false, need: "未配置", hint: "装法…" }));

    const res = await yueProbeViaHost();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain("/host/yue/probe");
    expect(calls[0].url).toContain("token=");
    expect(res.available).toBe(false);
    expect(res.hint).toBe("装法…");
  });

  it("plan 透传 lyrics/style/cot，返回可编辑 abc", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: true, abc: "X:1\nK:C\nCDEF|", cot: "full" }));

    const res = await yuePlanViaHost({ lyrics: "你好", style: "city pop", cot: "melody" });
    expect(calls[0].url).toContain("/host/yue/plan");
    expect(calls[0].body.lyrics).toBe("你好");
    expect(calls[0].body.style).toBe("city pop");
    expect(calls[0].body.cot).toBe("melody");
    expect(res.abc).toContain("K:C");
  });

  it("render 原样透传用户编辑过的 abc（编辑模式关键契约）", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: true, audio_url: "http://127.0.0.1:18765/inbox_file/yue_x.flac" }));

    const edited = "X:1\nT:我改过的谱\nK:Am\nA2B2c2|";
    const res = await yueRenderViaHost({
      lyrics: "歌词",
      style: "rock",
      abc: edited,
      cot: "full",
      title: "主题曲",
    });
    expect(calls[0].url).toContain("/host/yue/generate");
    expect(calls[0].body.abc).toBe(edited);
    expect(calls[0].body.title).toBe("主题曲");
    expect(res.audio_url).toContain("/inbox_file/");
  });

  it("render 未配置执行端时诚实失败（不返回假音频）", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: false, unavailable: true, message: "YuE 执行端未配置", hint: "装法…" }));

    const res = await yueRenderViaHost({ lyrics: "x", style: "y" });
    expect(res.ok).toBe(false);
    expect(res.audio_url).toBeUndefined();
    expect(res.unavailable).toBe(true);
  });

  it("seed 缺省不进 payload（保持请求形状最小）", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: true, abc: "X:1" }));

    await yuePlanViaHost({ lyrics: "a", style: "b" });
    expect("seed" in calls[0].body).toBe(false);

    calls.length = 0;
    await yuePlanViaHost({ lyrics: "a", style: "b", seed: 42 });
    expect(calls[0].body.seed).toBe(42);
  });

  it("transcribe 打 /host/yue/transcribe 并默认 melody_only=true（翻唱前置）", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: true, abc: "X:1\nK:C\nCDEF|", cot: "melody" }));

    const res = await yueTranscribeViaHost({ audio: "D:/素材/原曲.wav" });
    expect(calls[0].url).toContain("/host/yue/transcribe");
    expect(calls[0].body.audio).toBe("D:/素材/原曲.wav");
    // 官方：翻唱用 melody-only（去和弦），默认必须是 true
    expect(calls[0].body.melody_only).toBe(true);
    expect(res.cot).toBe("melody");
  });

  it("transcribe 未配置转录环境时诚实失败（不返回假谱）", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({
      ok: false, unavailable: true, message: "SheetSage2 转录环境未就绪", hint: "装法…",
    }));

    const res = await yueTranscribeViaHost({ audio: "/tmp/a.wav" });
    expect(res.ok).toBe(false);
    expect(res.abc).toBeUndefined();
    expect(res.hint).toBe("装法…");
  });

  it("probe 报告翻唱前置可用性（transcribe 字段）", async () => {
    const calls: { url: string; body?: any }[] = [];
    stubFetch(calls, () => ({ ok: true, available: true, mode: "local", transcribe: false,
      transcribe_hint: "需装 SheetSage2" }));

    const res = await yueProbeViaHost();
    expect(res.transcribe).toBe(false);
    expect(res.transcribe_hint).toContain("SheetSage2");
  });
});
