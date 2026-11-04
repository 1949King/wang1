import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { isComfyWorkflowJson, isComfyWorkflowText, generateImageViaHost, generateVideoViaHost } from "./bridge";
import type { GenJob } from "./generationQueue";

describe("ComfyUI workflow 识别（前端入口）", () => {
  it("识别 UI 格式（含 nodes 数组）", () => {
    expect(isComfyWorkflowJson({ nodes: [], links: [] })).toBe(true);
  });

  it("识别 graph 格式（class_type 对象）", () => {
    expect(
      isComfyWorkflowJson({ "1": { class_type: "KSampler", inputs: {} } }),
    ).toBe(true);
  });

  it("拒绝非 workflow JSON（数组 / 空对象 / null）", () => {
    expect(isComfyWorkflowJson([])).toBe(false);
    expect(isComfyWorkflowJson({})).toBe(false);
    expect(isComfyWorkflowJson(null)).toBe(false);
    expect(isComfyWorkflowJson("hello")).toBe(false);
  });

  it("isComfyWorkflowText 识别剪贴板 JSON 文本", () => {
    const ui = JSON.stringify({ nodes: [{ id: 1, type: "SaveImage" }] });
    expect(isComfyWorkflowText(ui)).toBe(true);
  });

  it("isComfyWorkflowText 拒绝普通文本 / 非 JSON / 非 workflow", () => {
    expect(isComfyWorkflowText("")).toBe(false);
    expect(isComfyWorkflowText("普通文字")).toBe(false);
    expect(isComfyWorkflowText('{"foo": 1}')).toBe(false);
    expect(isComfyWorkflowText("{ 无效 json")).toBe(false);
  });
});

// ── 异步任务化（generateForNode → runGeneration）接线测试 ──
// 契约：bridge 层 submit → 轮询 status → 终态映射回旧返回形状；
// 失败任务 → {ok:false, message}；AbortError → {ok:false, message:"已取消"}。

function makeJob(over: Partial<GenJob>): GenJob {
  return {
    job_id: "j1",
    kind: "image",
    label: "",
    status: "queued",
    stage: "queued",
    stage_label: "排队中",
    note: "",
    progress: null,
    attempts: 1,
    max_attempts: 1,
    error: "",
    created_at: 0,
    started_at: 0,
    finished_at: 0,
    updated_at: 0,
    elapsed_ms: 1234,
    queue_ms: 0,
    cancellable: true,
    result: null,
    meta: {},
    ...over,
  };
}

function jsonRes(data: unknown): Response {
  return { status: 200, json: async () => data } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// node 环境下 bridgeToken() 直接引用 window/localStorage，补最小桩
beforeEach(() => {
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
});

describe("generateImageViaHost 异步任务化", () => {
  it("submit → status(done) → 映射回旧返回形状，payload 键与旧同步端点一致", async () => {
    const calls: { url: string; body?: any }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: any) => {
      if (url.includes("/host/generation/submit")) {
        const body = JSON.parse(init.body);
        calls.push({ url, body });
        return jsonRes({ ok: true, job: makeJob({ status: "queued" }) });
      }
      if (url.includes("/host/generation/status")) {
        return jsonRes({
          ok: true,
          job: makeJob({
            status: "done",
            progress: 100,
            result: { ok: true, image_data_url: "data:image/png;base64,AAA", model: "m1" },
          }),
        });
      }
      throw new Error(`意外请求: ${url}`);
    }));

    const progressStages: string[] = [];
    const res = await generateImageViaHost({
      prompt: "竖屏漫剧分镜",
      model: "m1",
      channel_id: "c1",
      awaitOpts: {
        maxAttempts: 1,
        onProgress: (j) => progressStages.push(j.stage_label),
      },
    });

    expect(res.ok).toBe(true);
    expect(res.image_data_url).toBe("data:image/png;base64,AAA");
    expect(res.model).toBe("m1");
    // submit 的 payload 必须与旧 /host/generate-image 逐键一致（服务端白名单）
    expect(calls).toHaveLength(1);
    expect(calls[0].body.kind).toBe("image");
    expect(Object.keys(calls[0].body.payload).sort()).toEqual(
      ["aspect", "channel_id", "model", "prompt", "quality", "reference_image", "size", "strength"].sort(),
    );
    expect(calls[0].body.payload.prompt).toBe("竖屏漫剧分镜");
    // 画幅缺省为空串 → 由后端按 portrait（竖屏短剧）推导
    expect(calls[0].body.payload.aspect).toBe("");
    expect(progressStages.length).toBeGreaterThan(0);
  });

  it("画幅透传（V4.40.10）：显式 aspect 进 payload", async () => {
    const calls: { url: string; body?: any }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: any) => {
      if (url.includes("/host/generation/submit")) {
        calls.push({ url, body: JSON.parse(init.body) });
        return jsonRes({ ok: true, job: makeJob({ status: "queued" }) });
      }
      if (url.includes("/host/generation/status")) {
        return jsonRes({ ok: true, job: makeJob({ status: "done", progress: 100, result: { ok: true, image_data_url: "data:image/png;base64,AAA" } }) });
      }
      throw new Error(`意外请求: ${url}`);
    }));

    await generateImageViaHost({
      prompt: "横屏封面",
      model: "m1",
      channel_id: "c1",
      aspect: "landscape",
      awaitOpts: { maxAttempts: 1 },
    });

    expect(calls[0].body.payload.aspect).toBe("landscape");
  });

  it("种子贯通（P0a）：显式 seed 进 payload 并回显；缺省不进 payload，由后端生成", async () => {
    const calls: { url: string; body?: any }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: any) => {
      if (url.includes("/host/generation/submit")) {
        calls.push({ url, body: JSON.parse(init.body) });
        return jsonRes({ ok: true, job: makeJob({ status: "queued" }) });
      }
      if (url.includes("/host/generation/status")) {
        return jsonRes({
          ok: true,
          job: makeJob({
            status: "done",
            progress: 100,
            result: {
              ok: true,
              image_data_url: "data:image/png;base64,AAA",
              seed: 42,
              seed_sent: true,
            },
          }),
        });
      }
      throw new Error(`意外请求: ${url}`);
    }));

    // 显式 seed → 进 payload（抽卡复现 / 账本 best_seed），返回值原样带回
    const res = await generateImageViaHost({
      prompt: "复现",
      seed: 42,
      awaitOpts: { maxAttempts: 1 },
    });
    expect(res.ok).toBe(true);
    expect(res.seed).toBe(42);
    expect(res.seed_sent).toBe(true);
    expect(calls[0].body.payload.seed).toBe(42);

    // 缺省 → payload 不含 seed 键（保持旧形状），由后端自动生成并回显
    const res2 = await generateImageViaHost({
      prompt: "自动",
      awaitOpts: { maxAttempts: 1 },
    });
    expect(res2.ok).toBe(true);
    expect("seed" in calls[1].body.payload).toBe(false);
    expect(res2.seed).toBe(42); // 后端回显的自动种子
  });

  it("批量抽卡剥掉显式 seed：多候选共用同一种子会产出雷同图，违背抽卡语义", async () => {
    const calls: { url: string; body?: any }[] = [];
    let autoSeed = 100;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: any) => {
      if (url.includes("/host/generation/submit")) {
        calls.push({ url, body: JSON.parse(init.body) });
        return jsonRes({ ok: true, job: makeJob({ status: "queued" }) });
      }
      if (url.includes("/host/generation/status")) {
        autoSeed += 1;
        return jsonRes({
          ok: true,
          job: makeJob({
            status: "done",
            progress: 100,
            result: {
              ok: true,
              image_data_url: `data:image/png;base64,S${autoSeed}`,
              seed: autoSeed,
              seed_sent: true,
            },
          }),
        });
      }
      throw new Error(`意外请求: ${url}`);
    }));

    const res = await generateImageViaHost({
      prompt: "批量",
      seed: 42, // 显式传入也必须在批量模式被剥掉
      n: 2,
      awaitOpts: { maxAttempts: 1 },
    });
    expect(res.ok).toBe(true);
    expect(calls).toHaveLength(2);
    expect("seed" in calls[0].body.payload).toBe(false);
    expect("seed" in calls[1].body.payload).toBe(false);
    expect(res.seeds).toEqual([101, 102]); // 每张各自的种子，供账本记录
  });

  it("任务失败 → {ok:false, message:上游原文, fallback_placeholder:true}", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/host/generation/submit")) {
        return jsonRes({ ok: true, job: makeJob({ status: "queued" }) });
      }
      return jsonRes({
        ok: true,
        job: makeJob({ status: "failed", error: "上游限流，请稍后重试" }),
      });
    }));

    const res = await generateImageViaHost({ prompt: "x" });
    expect(res.ok).toBe(false);
    expect(res.message).toBe("上游限流，请稍后重试");
    expect(res.fallback_placeholder).toBe(true);
  });

  it("signal 取消 → {ok:false, message:'已取消'}，并调用后端 cancel", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(url);
      if (url.includes("/host/generation/submit")) {
        return jsonRes({ ok: true, job: makeJob({ status: "queued" }) });
      }
      if (url.includes("/host/generation/cancel")) {
        return jsonRes({ ok: true, message: "已取消" });
      }
      return jsonRes({ ok: true, job: makeJob({ status: "running" }) });
    }));

    const ctrl = new AbortController();
    ctrl.abort();
    const res = await generateImageViaHost({
      prompt: "x",
      awaitOpts: { signal: ctrl.signal, maxAttempts: 1 },
    });
    expect(res.ok).toBe(false);
    expect(res.message).toBe("已取消");
    expect(urls.some((u) => u.includes("/host/generation/cancel"))).toBe(true);
  });
});

describe("generateVideoViaHost 异步任务化", () => {
  it("submit 键与旧同步端点一致，done 结果（含 postprocess_job_id）原样透传", async () => {
    let submitted: any = null;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: any) => {
      if (url.includes("/host/generation/submit")) {
        submitted = JSON.parse(init.body);
        return jsonRes({ ok: true, job: makeJob({ kind: "video", status: "queued" }) });
      }
      return jsonRes({
        ok: true,
        job: makeJob({
          kind: "video",
          status: "done",
          progress: 100,
          result: {
            ok: true,
            video_url: "http://127.0.0.1:18765/inbox_file/a.mp4",
            postprocessing: true,
            postprocess_job_id: "pp1",
          },
        }),
      });
    }));

    const res = await generateVideoViaHost({
      prompt: "电影感运镜",
      duration: 6,
      reference_image: "data:image/png;base64,BBB",
      quality: "high",
    });
    expect(res.ok).toBe(true);
    expect(res.video_url).toContain("a.mp4");
    expect(res.postprocess_job_id).toBe("pp1");
    expect(submitted.kind).toBe("video");
    expect(submitted.payload.duration).toBe(6);
    expect(submitted.payload.quality).toBe("high");
    expect(Object.keys(submitted.payload).sort()).toEqual(
      ["channel_id", "duration", "first_frame", "last_frame", "model", "prompt", "quality", "reference_image", "reference_video", "size"].sort(),
    );
  });

  it("视频任务失败 → {ok:false, message}", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/host/generation/submit")) {
        return jsonRes({ ok: true, job: makeJob({ kind: "video", status: "queued" }) });
      }
      return jsonRes({ ok: true, job: makeJob({ kind: "video", status: "failed", error: "生视频超时" }) });
    }));
    const res = await generateVideoViaHost({ prompt: "x" });
    expect(res.ok).toBe(false);
    expect(res.message).toBe("生视频超时");
  });
});
