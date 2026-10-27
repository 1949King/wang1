/**
 * localVideo.test.ts — 本地视频生成桥接层回归（2026-10-01）
 *
 * 锁定 `bridge.ts` 新增的两个函数与后端的**请求契约**：
 *   ① `listLocalVideoModels` → POST `/host/local-video-generate` {action:"models"}
 *   ② `generateVideoLocalViaHost` → POST 同端点 {action:"generate", model_id, image}
 *
 * 为什么只测桥接层：真正的路由分支在 `App.tsx` 的 `generateVideoUnified` 内部
 * （组件内、未导出）。桥接层是**契约边界**——端点写错/字段名写错，组件侧再对也没用，
 * 所以把契约钉在这里性价比最高。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
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

  it("SVD 缺首帧时诚实失败，不发无效请求", async () => {
    const fetchMock = vi.fn();
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
    expect(fetchMock).not.toHaveBeenCalled();
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
