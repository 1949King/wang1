import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { generateImageUnified, listLocalImageModels, mergeLocalImageModels } from "./localImage";

function jsonRes(obj: unknown) {
  return { ok: true, status: 200, json: async () => obj } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("localImage：本地图像模型接入", () => {
  it("读取 models 时走 local-image-generate，并按 id 去重双引擎重复项", async () => {
    let body: any = null;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: any) => {
      body = JSON.parse(init.body);
      return jsonRes({
        ok: true,
        engines: [
          { id: "diffsynth", available: true, models: [
            { id: "sd15-t2i", label: "SD1.5（主选）", download_gb: 3.97, vram_gb: 3, ram_gb: 4.5 },
            { id: "sdxl-t2i", label: "SDXL（主选）", download_gb: 6.46, vram_gb: 7, ram_gb: 9 },
          ] },
          { id: "builtin", available: true, models: [
            { id: "sd15-t2i", label: "SD1.5（自研）", download_gb: 3.97, vram_gb: 3, ram_gb: 4.5 },
          ] },
        ],
        downloaded: ["sd15-t2i", "sdxl-t2i"],
      });
    }));

    const res = await listLocalImageModels();
    expect(body.action).toBe("models");
    expect(res.models.map((m) => m.id)).toEqual(["sd15-t2i", "sdxl-t2i"]);
    expect(res.downloaded).toEqual(["sd15-t2i", "sdxl-t2i"]);
    expect(res.available).toBe(true);
  });

  it("合并后本地模型带「本地」前缀，云端选项不被覆盖", () => {
    const merged = mergeLocalImageModels(
      [{ channel_id: "cloud-a", channel_name: "云端", model: "m1", label: "云端 m1" }],
      { models: [{ id: "sd15-t2i", label: "SD1.5", download_gb: 3.97, vram_gb: 3 }], downloaded: ["sd15-t2i"] },
    );
    expect(merged[0].channel_id).toBe("cloud-a");
    expect(merged[1].channel_id).toBe("local");
    expect(merged[1].label).toContain("本地");
    expect(merged[1].label).toContain("已下载");
  });

  it("本地生成选择真正发到 local-image-generate，并携带 model_id", async () => {
    let captured: { url: string; body: any } | null = null;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: any) => {
      captured = { url, body: JSON.parse(init.body) };
      return jsonRes({ ok: true, image_url: "/inbox_file/a.png", message: "生成完成" });
    }));

    const res = await generateImageUnified({
      parsed: { channel_id: "local", model: "sdxl-t2i" },
      prompt: "竖屏电影感镜头",
      aspect: "9:16",
      n: 1,
      quality: "fine",
    });

    expect(captured!.url).toContain("/host/local-image-generate");
    expect(captured!.body.action).toBe("generate");
    expect(captured!.body.model_id).toBe("sdxl-t2i");
    expect(captured!.body.prompt).toBe("竖屏电影感镜头");
    // 分辨率总闸（2026-10-27）：竖屏 9:16 + fine 档 ⇒ 长边=1024、等比、对齐 64
    const w = captured!.body.width as number;
    const h = captured!.body.height as number;
    expect(Math.max(w, h)).toBe(1024);
    expect(h).toBeGreaterThan(w);
    expect(w % 64).toBe(0);
    expect(res.ok).toBe(true);
    expect(res.image_url).toBe("/inbox_file/a.png");
  });

  it("本地批量按抽卡语义逐张请求，不把第一张复制成多张", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      return jsonRes({ ok: true, image_url: `/inbox_file/${calls}.png` });
    }));

    const res = await generateImageUnified({
      parsed: { channel_id: "local", model: "sd15-t2i" },
      prompt: "test",
      n: 2,
    });

    expect(calls).toBe(2);
    expect(res.images).toEqual(["/inbox_file/1.png", "/inbox_file/2.png"]);
  });

  it("模型接口失败时返回空清单，不把异常抛给面板", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
    const res = await listLocalImageModels();
    expect(res.models).toEqual([]);
    expect(res.available).toBe(false);
    expect(res.unavailable_reason).toContain("无法连接");
  });
});
