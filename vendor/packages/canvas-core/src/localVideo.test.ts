/**
 * localVideo.test.ts — 本地视频生成桥接层回归（2026-10-01）
 *
 * 锁定 `bridge.ts` 新增的两个函数与后端的**请求契约**：
 *   ① `listLocalVideoModels` → POST `/host/local-video-generate` {action:"models"}
 *   ② `generateVideoLocalViaHost` → POST 同端点 {action:"generate", model_id, image}
 *
 * 为什么测到这一层：`generateVideoUnified` 早期在 `App.tsx` 组件内（未导出），
 * 现已迁到 `localVideo.ts` 并导出，所以可直接测。桥接层是**契约边界**——
 * 端点写错/字段名写错，上层再对也没用，所以把契约钉在这里性价比最高；
 * 纯函数（`buildVideoChain` / `localModelModes`）另在 `localVideo.route.test.ts` 直测。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { readFileSync } from "node:fs";
import { generateVideoLocalViaHost, generateVideoUnified, listLocalVideoModels } from "./localVideo";

function jsonRes(obj: unknown) {
  return { ok: true, status: 200, json: async () => obj } as unknown as Response;
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

describe("listLocalVideoModels：本地模型注册表（只读）", () => {
  it("POST 到 local-video-generate 且 action=models", async () => {
    let captured: { url: string; body: any; method?: string } | null = null;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: any) => {
      captured = { url, body: JSON.parse(init.body), method: init.method };
      return jsonRes({
        ok: true,
        models: [{ id: "svd-xt-i2v", label: "SVD img2vid-xt（图生视频）", params: "1.5B", modes: ["i2v"], download_gb: 4.2, vram_gb: 7, ram_gb: 8, note: "CLIP 编码器", license: "Stability" }],
        available: true,
        unavailable_reason: "",
        downloaded: ["svd-xt-i2v"],
      });
    }));

    const r = await listLocalVideoModels();
    expect(captured).not.toBeNull();
    expect(captured!.url).toContain("/host/local-video-generate");
    expect(captured!.method).toBe("POST");
    expect(captured!.body.action).toBe("models");
    expect(r.models.length).toBe(1);
    expect(r.models[0].id).toBe("svd-xt-i2v");
    expect(r.available).toBe(true);
    expect(r.downloaded).toEqual(["svd-xt-i2v"]);
  });

  it("接口报错时返回安全空值，不抛异常", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonRes({ ok: false, message: "boom" })));
    const r = await listLocalVideoModels();
    expect(r.models).toEqual([]);
    expect(r.available).toBe(false);
    expect(r.downloaded).toEqual([]);
  });

  it("网络异常时也返回安全空值（不把异常抛给渲染层）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
    const r = await listLocalVideoModels();
    expect(r.models).toEqual([]);
    expect(r.available).toBe(false);
    expect(r.unavailable_reason).toContain("无法连接");
  });
});

describe("generateVideoUnified：本地视频能力边界", () => {
  it("Wan2.1 T2V 无首帧也能走本地文生视频", async () => {
    let body: any = null;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: any) => {
      body = JSON.parse(init.body);
      return jsonRes({ ok: true, video_url: "/inbox_file/wan21.mp4" });
    }));
    const res = await generateVideoUnified({
      parsed: { channel_id: "local", model: "wan21-t2v-1.3b" },
      prompt: "夜色中的霓虹街道，镜头缓慢推进",
      referenceImage: "",
      duration: 2,
      quality: "standard",
    });
    expect(body.model_id).toBe("wan21-t2v-1.3b");
    expect(body.image).toBe("");
    expect(res.ok).toBe(true);
  });

  it("SVD 缺首帧：前端不代判，交后端按 modes 拒绝并给出可操作建议", async () => {
    const fetchMock = vi.fn(async () =>
      jsonRes({
        ok: false,
        message:
          "「svd-xt-i2v」是图生视频模型，需要首帧图。请先给节点配一张首帧图，或改选纯文生视频模型（如 wan21-t2v-1.3b）",
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await generateVideoUnified({
      parsed: { channel_id: "local", model: "svd-xt-i2v" },
      prompt: "test",
      referenceImage: "",
      duration: 2,
      quality: "standard",
    });
    expect(res.ok).toBe(false);
    expect(res.message).toContain("首帧");
    // ★ 2026-11-15 起前端不再自己维护「哪些本地模型要首帧」——
    //   那份硬编码 Set 与后端 video_gen.modes 必然漂移（wan21 只有 t2v、wan22 是 t2v+i2v），
    //   所以判定统一交给后端，这里断言请求确实发下去了（能力判定单源）。
    expect(fetchMock).toHaveBeenCalled();
  });
});

describe("generateVideoLocalViaHost：本地图生视频", () => {
  it("POST 到 local-video-generate 且 action=generate，带上 image / model_id", async () => {
    let captured: { url: string; body: any } | null = null;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: any) => {
      captured = { url, body: JSON.parse(init.body) };
      return jsonRes({
        ok: true,
        video_url: "http://127.0.0.1:18765/inbox_file/1_out.mp4",
        video_path: "短剧AI剪辑输出/_svd_test_out.mp4",
        frames: 10,
        message: "生成完成",
      });
    }));

    const r = await generateVideoLocalViaHost({
      image: "data:image/png;base64,AAAA",
      model: "svd-xt-i2v",
      seconds: 1.5,
      fps: 7,
      seed: 42,
    });

    expect(captured!.url).toContain("/host/local-video-generate");
    expect(captured!.body.action).toBe("generate");
    expect(captured!.body.model_id).toBe("svd-xt-i2v");
    expect(captured!.body.image).toBe("data:image/png;base64,AAAA");
    expect(captured!.body.fps).toBe(7);
    expect(captured!.body.seed).toBe(42);

    expect(r.ok).toBe(true);
    expect(r.video_url).toContain("/inbox_file/");
    expect(r.frames).toBe(10);
  });

  it("后端诚实失败时原样透传 message（不伪造成功）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonRes({
      ok: false,
      message: "模型未下载。请先拉取（目标目录: ...Wan2.2-TI2V-5B）",
    })));
    const r = await generateVideoLocalViaHost({ image: "data:image/png;base64,AAAA" });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("模型未下载");
    expect(r.video_url).toBe("");
  });

  it("video_path 兼容后端返回的 path 字段别名", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonRes({
      ok: true, path: "out/x.mp4", frames: 3,
    })));
    const r = await generateVideoLocalViaHost({ image: "data:image/png;base64,AAAA" });
    expect(r.video_path).toBe("out/x.mp4");
  });

  it("网络异常时返回 ok=false 且带原因", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("timeout"); }));
    const r = await generateVideoLocalViaHost({ image: "data:image/png;base64,AAAA" });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("本地视频生成请求失败");
  });

  it("未传 model 时 model_id 为空串（由后端按缺省模型处理）", async () => {
    let body: any = null;
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: any) => {
      body = JSON.parse(init.body);
      return jsonRes({ ok: true, frames: 1 });
    }));
    await generateVideoLocalViaHost({ image: "data:image/png;base64,AAAA" });
    expect(body.model_id).toBe("");
    expect(body.seconds).toBe(1.5);   // 缺省 1.5 秒（本机生成慢，刻意短）
    expect(body.fps).toBe(7);
  });
});

// ───────── 2026-11-01 修：本地视频丢提示词 / 尾帧全链路丢弃 ─────────
// 用户实测反馈：「要么提示没有给出首尾帧图片，要么提示没有给出提示词」。
// 真因不在用户：① generateVideoLocalViaHost 签名里根本没有 prompt ⇒ 后端
// body.get("prompt") 恒空；② 画布早就能选尾帧（CanvasShell 的 onPick 写
// lastFrameUrl），但生成请求从不带它 ⇒ 云端「首尾帧」永远只有首帧。

describe("视频参数透传（回归锁）", () => {
  it("本地请求体必须带 prompt 与 last_frame", async () => {
    let body: any = null;
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: any) => {
      body = JSON.parse(init.body);
      return jsonRes({ ok: true, frames: 1 });
    }));

    await generateVideoLocalViaHost({
      image: "data:image/png;base64,AAAA",
      prompt: "少女回眸，镜头缓慢推近",
      lastFrame: "data:image/png;base64,BBBB",
      model: "cogvideox-2b",
    });

    expect(body.prompt).toBe("少女回眸，镜头缓慢推近");
    expect(body.last_frame).toBe("data:image/png;base64,BBBB");
  });

  it("未给提示词/尾帧时传空串而不是 undefined（后端按缺省处理）", async () => {
    let body: any = null;
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: any) => {
      body = JSON.parse(init.body);
      return jsonRes({ ok: true, frames: 1 });
    }));

    await generateVideoLocalViaHost({ image: "data:image/png;base64,AAAA" });

    expect(body.prompt).toBe("");
    expect(body.last_frame).toBe("");
  });

  it("本地分支（channel=local）把 prompt 透传给桥接层", async () => {
    let body: any = null;
    vi.stubGlobal("fetch", vi.fn(async (_u: string, init: any) => {
      body = JSON.parse(init.body);
      return jsonRes({ ok: true, frames: 1 });
    }));

    await generateVideoUnified({
      parsed: { channel_id: "local", model: "cogvideox-2b" },
      prompt: "雨夜街头，霓虹反光",
      referenceImage: "data:image/png;base64,AAAA",
      duration: 2,
      quality: "standard",
    });

    expect(body.prompt).toBe("雨夜街头，霓虹反光");
  });

  it("云端分支必须能下发 first_frame/last_frame，且受 lastFrame 守卫", () => {
    // 云端走 runGeneration 异步任务化（submit + 轮询），行为测试成本高；
    // 这里锁结构：两个字段必须存在，且只在有尾帧时才进请求体
    // ——「无尾帧的调用方逐键与改动前一致」是本次改动的硬约束。
    const src = readFileSync(new URL("./localVideo.ts", import.meta.url), "utf8");
    expect(src).toContain("first_frame: opts.referenceImage");
    expect(src).toContain("last_frame: opts.lastFrame");
    // 两处云端调用（自动链 / 直连）都必须带守卫
    expect(src.match(/opts\.lastFrame\s*\n?\s*\?/g)?.length ?? 0).toBe(2);
  });
});
