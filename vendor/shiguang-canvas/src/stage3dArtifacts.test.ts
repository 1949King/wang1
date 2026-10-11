/**
 * 回归：3D 导演台产物 → 剪辑时间线（stage3dArtifacts.ts）
 *
 * 覆盖三类容易悄悄坏掉的行为：
 *   1. **发布/去重/上限** —— 同路径重复发布必须只留一条并移到队首（否则重录白模视频会堆重复条目）；
 *   2. **诚实失败** —— 空路径 / 后端 success=false / 网络异常，一律 ok:false 且**不谎报已发送**；
 *   3. **唯一通道的请求形状** —— 必须打到 `/ingest_path` 且 `send_to_editor: true`
 *      （少了它产物只会落 inbox、不进时间线，且**后端不会报错**，是纯静默失效）。
 *
 * 期望值全部从源码行为推导，不凭直觉。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  __resetStage3dArtifacts,
  dataUrlToBlob,
  getArtifactsSnapshot,
  getLatestArtifact,
  publishStage3dArtifact,
  registerControlNetArtifacts,
  sendArtifactToTimeline,
  sendLatestArtifactToTimeline,
  type Stage3dArtifact,
} from "./stage3dArtifacts";

function mk(path: string, title = "t"): Omit<Stage3dArtifact, "id" | "createdAt"> {
  return { path, title, kind: "video", source: "stage3d_pose_video" };
}

beforeEach(() => {
  __resetStage3dArtifacts();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("产物登记", () => {
  it("初始为空，发布后 getLatestArtifact 取到它", () => {
    expect(getLatestArtifact()).toBeNull();
    const a = publishStage3dArtifact(mk("D:/x/a.mp4"));
    expect(a.path).toBe("D:/x/a.mp4");
    expect(getLatestArtifact()?.path).toBe("D:/x/a.mp4");
  });

  it("快照是同一引用（useSyncExternalStore 靠它防空转），发布后才换引用", () => {
    const before = getArtifactsSnapshot();
    publishStage3dArtifact(mk("D:/x/a.mp4"));
    const after = getArtifactsSnapshot();
    expect(after).not.toBe(before);
    expect(getArtifactsSnapshot()).toBe(after);
  });

  it("同路径重复发布：只留一条，且移到队首并更新标题", () => {
    publishStage3dArtifact(mk("D:/x/a.mp4", "旧"));
    publishStage3dArtifact(mk("D:/x/b.mp4", "b"));
    publishStage3dArtifact(mk("D:/x/a.mp4", "新"));
    const list = getArtifactsSnapshot();
    expect(list.filter((x) => x.path === "D:/x/a.mp4").length).toBe(1);
    expect(list.length).toBe(2);
    expect(list[0].path).toBe("D:/x/a.mp4");
    expect(list[0].title).toBe("新");
  });

  it("保留上限 = 8 条（只回溯最近几次导出，不无限增长）", () => {
    for (let i = 0; i < 12; i++) publishStage3dArtifact(mk(`D:/x/${i}.mp4`));
    const list = getArtifactsSnapshot();
    expect(list.length).toBe(8);
    // 队首是最后发布的第 11 号，队尾是被挤剩下的第 4 号
    expect(list[0].path).toBe("D:/x/11.mp4");
    expect(list[list.length - 1].path).toBe("D:/x/4.mp4");
  });

  it("id 稳定：同一路径重复发布得到同一个 id", () => {
    const a = publishStage3dArtifact(mk("D:/x/a.mp4"));
    const b = publishStage3dArtifact(mk("D:/x/a.mp4"));
    expect(b.id).toBe(a.id);
  });
});

describe("送入时间线 · 请求形状", () => {
  it("打到 /ingest_path，且必须带 send_to_editor:true（少了它就是静默失效）", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, message: "已发送到剪辑：a.mp4" }),
    } as unknown as Response);

    const a = publishStage3dArtifact({ ...mk("D:/x/a.mp4", "白模动作"), durationSec: 3.6 });
    const r = await sendArtifactToTimeline(a);

    expect(r.ok).toBe(true);
    expect(r.message).toContain("已发送到剪辑");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(String(url)).toContain("/ingest_path");
    const body = JSON.parse(String(init.body));
    expect(body.path).toBe("D:/x/a.mp4");
    expect(body.send_to_editor).toBe(true);
    expect(body.title).toBe("白模动作");
    expect(body.kind).toBe("video");
    expect(body.duration_sec).toBe(3.6);
  });

  it("空路径：本地就挡住，不发起请求", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const r = await sendArtifactToTimeline({ ...mk(""), id: "x", createdAt: 0 });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("路径为空");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("后端 success=false：透传后端原因，不谎报成功", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ success: false, message: "文件不存在: D:/x/gone.mp4" }),
    } as unknown as Response);

    const a = publishStage3dArtifact(mk("D:/x/gone.mp4"));
    const r = await sendArtifactToTimeline(a);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("文件不存在");
  });

  it("HTTP 200 但 success 缺失：仍判失败（不认「没明说成功」为成功）", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    } as unknown as Response);

    const a = publishStage3dArtifact(mk("D:/x/a.mp4"));
    const r = await sendArtifactToTimeline(a);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("200");
  });

  it("网络异常：返回 ok:false 且带原因", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("ECONNREFUSED"));
    const a = publishStage3dArtifact(mk("D:/x/a.mp4"));
    const r = await sendArtifactToTimeline(a);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("ECONNREFUSED");
  });
});

describe("一键送「最近产物」", () => {
  it("没有产物时：本地挡住，不发起请求", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const r = await sendLatestArtifactToTimeline();
    expect(r.ok).toBe(false);
    expect(r.message).toContain("还没有可发送的产物");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("有产物时：发送的是队首那一条", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true, message: "ok" }),
    } as unknown as Response);

    publishStage3dArtifact(mk("D:/x/old.mp4"));
    publishStage3dArtifact(mk("D:/x/new.mp4"));
    await sendLatestArtifactToTimeline();

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).path).toBe("D:/x/new.mp4");
  });
});

// ── 刀2：data URL 形态产物（ControlNet 三通道） ──────────────────────────────
// 注意：uploadAssetToHost → bridgeToken() 会读 window/localStorage，
// node 环境必须 stub 掉，否则 ReferenceError 被 publishUploadedArtifact 吞成 null。
const PNG_DATA_URL = "data:image/png;base64," + btoa("fake-png-bytes");

function stubBrowserGlobals() {
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", { getItem: () => null });
}

describe("dataUrlToBlob", () => {
  it("base64 data URL → 同 mime 的 Blob", async () => {
    const b = dataUrlToBlob(PNG_DATA_URL);
    expect(b).not.toBeNull();
    expect(b!.type).toBe("image/png");
    expect(await b!.text()).toBe("fake-png-bytes");
  });

  it("非 data URL ⇒ null（不抛）", () => {
    expect(dataUrlToBlob("https://x/y.png")).toBeNull();
    expect(dataUrlToBlob("")).toBeNull();
    expect(dataUrlToBlob(undefined as unknown as string)).toBeNull();
  });
});

describe("registerControlNetArtifacts（上传换路径 → 登记）", () => {
  it("两个通道：各上传一次 /host/upload-asset，并登记两条（path 来自后端返回值）", async () => {
    stubBrowserGlobals();
    let n = 0;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      n += 1;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, path: `D:/inbox/cn_${n}.png`, url: `http://x/inbox_file/cn_${n}.png` }),
      } as unknown as Response;
    });

    const okCount = await registerControlNetArtifacts([
      { name: "controlnet_depth.png", data: PNG_DATA_URL },
      { name: "controlnet_normal.png", data: PNG_DATA_URL },
    ]);

    expect(okCount).toBe(2);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    for (const [url] of fetchSpy.mock.calls as [string, RequestInit][]) {
      expect(String(url)).toContain("/host/upload-asset");
    }
    const list = getArtifactsSnapshot();
    expect(list.length).toBe(2);
    expect(list.map((a) => a.path).sort()).toEqual(["D:/inbox/cn_1.png", "D:/inbox/cn_2.png"]);
    expect(list.every((a) => a.source === "stage3d_controlnet" && a.kind === "image")).toBe(true);
    // 标题剥掉 .png 后缀，作为时间线片段名
    expect(list.map((a) => a.title).sort()).toEqual(["controlnet_depth", "controlnet_normal"]);
  });

  it("上传失败（后端没回 path）⇒ 不登记半成品，返回 0", async () => {
    stubBrowserGlobals();
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ ok: false, message: "磁盘满" }),
    } as unknown as Response);

    const okCount = await registerControlNetArtifacts([{ name: "a.png", data: PNG_DATA_URL }]);
    expect(okCount).toBe(0);
    expect(getArtifactsSnapshot().length).toBe(0);
  });

  it("坏 data URL 会被跳过，不影响其余通道", async () => {
    stubBrowserGlobals();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, path: "D:/inbox/only.png" }),
    } as unknown as Response);

    const okCount = await registerControlNetArtifacts([
      { name: "bad.png", data: "not-a-data-url" },
      { name: "good.png", data: PNG_DATA_URL },
    ]);
    expect(okCount).toBe(1);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(getArtifactsSnapshot()[0].path).toBe("D:/inbox/only.png");
  });
});
