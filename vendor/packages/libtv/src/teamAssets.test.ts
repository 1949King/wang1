/**
 * teamAssets 单测（2026-11-02）
 *
 * 只测**纯函数与映射纪律**：真上传要真服务，交给后端 pytest 与人工冒烟。
 * 这里守的是三件最容易回归的事：
 *   ① 什么该上传、什么不该（判断错了要么撑爆 bundle 要么同事 404）；
 *   ② 令牌必须能被剥干净，且剥完不能变成半截 URL（lastIndex 经典坑）；
 *   ③ 换 host 后旧地址能复活（服务器 IP 变了不能全废）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type FakeLS = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void };

const SHA = "a".repeat(64);
const SHA2 = "b".repeat(64);

function installFakes(): { store: Map<string, string> } {
  const store = new Map<string, string>();
  const ls: FakeLS = {
    getItem: (k) => (store.has(k) ? store.get(k)! : null),
    setItem: (k, v) => store.set(k, v),
    removeItem: (k) => store.delete(k),
  };
  (globalThis as unknown as { window: { localStorage: FakeLS } }).window = { localStorage: ls };
  (globalThis as unknown as { localStorage: FakeLS }).localStorage = ls;
  return { store };
}

async function joined(token = "tok-123", address = "192.168.1.4:18770") {
  (globalThis as unknown as { fetch: typeof fetch }).fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({ ok: true, member_id: "m_1", name: "张三", token }),
  })) as unknown as typeof fetch;
  vi.resetModules();
  const tc = await import("./teamClient");
  await tc.teamJoin(address, "张三");
  const ta = await import("./teamAssets");
  return { ta, tc };
}

describe("teamAssets · 什么该上传", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("本地落盘路径要上传（同事机上没有这个文件）", async () => {
    const m = await import("./teamAssets");
    expect(m.shouldUpload("/inbox_file/成片.mp4")).toBe(true);
    expect(m.shouldUpload("/editor_file/a.png")).toBe(true);
    expect(m.shouldUpload("http://127.0.0.1:18765/inbox_file/a.mp4")).toBe(true);
  });

  it("data URL 按体积分：小的内联、大的上传", async () => {
    const m = await import("./teamAssets");
    const small = "data:image/png;base64," + "A".repeat(1000);
    const big = "data:image/png;base64," + "A".repeat(m.DATA_UPLOAD_THRESHOLD + 100);
    expect(m.shouldUpload(small)).toBe(false);
    expect(m.shouldUpload(big)).toBe(true);
  });

  it("blob: 与本就能访问的 URL 不上传", async () => {
    const m = await import("./teamAssets");
    expect(m.shouldUpload("blob:http://x/abc")).toBe(false);
    expect(m.shouldUpload(`http://192.168.1.4:18770/team/projects/p_1/assets/${SHA}`)).toBe(false);
    expect(m.shouldUpload("https://cdn.example.com/a.png")).toBe(false);
    expect(m.shouldUpload("")).toBe(false);
  });
});

describe("teamAssets · 名称与类型", () => {
  it("字段名优先于后缀，后缀优先于类型名", async () => {
    const m = await import("./teamAssets");
    expect(m.kindOf("/inbox_file/a.mp4")).toBe("video");
    expect(m.kindOf("/inbox_file/a.PNG")).toBe("image");
    expect(m.kindOf("/inbox_file/noext", "posterUrl")).toBe("image");
    expect(m.kindOf("/inbox_file/x.unknownext")).toBe("file");
    expect(m.kindOf("data:audio/mpeg;base64,AA")).toBe("audio");
  });

  it("中文名会解百分号编码，畸形编码不抛", async () => {
    const m = await import("./teamAssets");
    expect(m.nameFor("/inbox_file/%E6%88%90%E7%89%87.mp4")).toBe("成片.mp4");
    expect(m.nameFor("/inbox_file/100%.mp4")).toBe("100%.mp4");
    expect(m.nameFor("/inbox_file/", "videoUrl")).toBe("videoUrl.mp4");
  });
});

describe("teamAssets · 收集要传的东西", () => {
  it("节点字段与时间线片段都能扫到，且去重", async () => {
    const m = await import("./teamAssets");
    const bundle = {
      nodes: [
        { id: "n1", data: { imageUrl: "/inbox_file/a.png", prompt: "下雨的街道" } },
        { id: "n2", data: { videoUrl: "/inbox_file/b.mp4", posterUrl: "/inbox_file/a.png" } },
        { id: "n3", data: { images: [{ url: "/inbox_file/c.webp" }] } },
      ],
      timeline: {
        clips: [
          { id: "c1", videoUrl: "/inbox_file/b.mp4" },
          { id: "c2", audioUrl: "/inbox_file/d.mp3" },
        ],
      },
    };
    const refs = m.collectMediaRefs(bundle);
    const urls = refs.map((r) => r.url).sort();
    expect(urls).toEqual(["/inbox_file/a.png", "/inbox_file/b.mp4", "/inbox_file/c.webp", "/inbox_file/d.mp3"]);
    expect(refs.find((r) => r.url === "/inbox_file/d.mp3")?.kind).toBe("audio");
    // 纯文本 prompt 不能被当媒体
    expect(refs.some((r) => r.url.includes("下雨"))).toBe(false);
  });

  it("空 bundle / 异常入参不炸", async () => {
    const m = await import("./teamAssets");
    expect(m.collectMediaRefs(null)).toEqual([]);
    expect(m.collectMediaRefs({})).toEqual([]);
    expect(m.collectMediaRefs("裸字符串")).toEqual([]);
  });
});

describe("teamAssets · URL 改写", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
  });

  it("applyMediaIndex 只换命中的 URL，其余原样", async () => {
    const { ta } = await joined();
    const bundle = {
      nodes: [
        { data: { imageUrl: "/inbox_file/a.png", title: "镜 01", prompt: "/inbox_file/not-a-url-in-map" } },
      ],
    };
    const out = ta.applyMediaIndex(bundle, "p_1", { "/inbox_file/a.png": SHA });
    const d = out.nodes[0].data;
    expect(d.imageUrl).toBe(`http://192.168.1.4:18770/team/projects/p_1/assets/${SHA}?token=tok-123`);
    expect(d.title).toBe("镜 01");
    expect(d.prompt).toBe("/inbox_file/not-a-url-in-map");
    // 未命中的映射表为空时原样返回同一个对象（不做无意义深拷贝）
    expect(ta.applyMediaIndex(bundle, "p_1", {})).toBe(bundle);
  });

  it("stripAssetTokens 剥掉令牌且**不产生半截 URL**（连续调用幂等）", async () => {
    const { ta } = await joined();
    const url = `http://192.168.1.4:18770/team/projects/p_1/assets/${SHA}?token=tok-123`;
    const bundle = { nodes: [{ data: { videoUrl: url } }, { data: { imageUrl: url } }] };
    const once = ta.stripAssetTokens(bundle);
    const clean = `http://192.168.1.4:18770/team/projects/p_1/assets/${SHA}`;
    expect(once.nodes[0].data.videoUrl).toBe(clean);
    expect(once.nodes[1].data.imageUrl).toBe(clean);
    // 再剥一次结果不变（回归：带 g 正则 test 推进 lastIndex 会切出半截 URL）
    expect(ta.stripAssetTokens(once).nodes[0].data.videoUrl).toBe(clean);
  });

  it("rebaseAssetUrls 换 host 并注入当前令牌：服务器换 IP 后旧地址能复活", async () => {
    const { ta } = await joined("new-token", "10.0.0.9:18770");
    const stale = `http://192.168.1.4:18770/team/projects/p_1/assets/${SHA}`;
    const bundle = { timeline: { clips: [{ videoUrl: stale }] } };
    const out = ta.rebaseAssetUrls(bundle);
    expect(out.timeline.clips[0].videoUrl).toBe(
      `http://10.0.0.9:18770/team/projects/p_1/assets/${SHA}?token=new-token`,
    );
    expect(ta.isTeamAsset(out.timeline.clips[0].videoUrl)).toBe(true);
    expect(ta.isTeamAsset("/inbox_file/a.png")).toBe(false);
  });

  it("没加入团队时不改写（避免把 URL 覆盖成空串）", async () => {
    installFakes();
    vi.resetModules();
    const ta = await import("./teamAssets");
    const stale = `http://192.168.1.4:18770/team/projects/p_1/assets/${SHA}`;
    const bundle = { u: stale };
    expect(ta.rebaseAssetUrls(bundle).u).toBe(stale);
    expect(ta.applyMediaIndex(bundle, "p_1", { u: SHA2 }).u).toBe(stale);
  });
});

describe("teamAssets · mapStrings", () => {
  it("深拷贝且不改原对象，深度超限不崩", async () => {
    const m = await import("./teamAssets");
    const src = { a: { b: { c: "x" } }, arr: ["y"] };
    const out = m.mapStrings(src, (s) => s.toUpperCase());
    expect(out).toEqual({ a: { b: { c: "X" } }, arr: ["Y"] });
    expect(src.a.b.c).toBe("x");
    let deep: Record<string, unknown> = { v: "end" };
    for (let i = 0; i < 30; i++) deep = { child: deep };
    expect(() => m.mapStrings(deep, (s) => s.toUpperCase())).not.toThrow();
  });
});

describe("teamAssets · 媒体索引缓存", () => {
  beforeEach(() => installFakes());
  afterEach(() => {
    vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).window;
    delete (globalThis as Record<string, unknown>).localStorage;
  });

  it("写完能读回，且按项目隔离", async () => {
    const m = await import("./teamAssets");
    m.writeMediaCache("p_1", { "/inbox_file/a.png": SHA });
    expect(m.readMediaCache("p_1")).toEqual({ "/inbox_file/a.png": SHA });
    expect(m.readMediaCache("p_2")).toEqual({});
    expect(m.readMediaCache("")).toEqual({});
  });

  it("坏数据不抛：非法 sha 被滤掉，坏 JSON 回空对象", async () => {
    const m = await import("./teamAssets");
    const ls = (globalThis as unknown as { window: { localStorage: { setItem(k: string, v: string): void } } }).window.localStorage;
    ls.setItem("shiguang:team:media:p_bad", JSON.stringify({ a: "tooshort", b: SHA, c: 123 }));
    expect(m.readMediaCache("p_bad")).toEqual({ b: SHA });
    ls.setItem("shiguang:team:media:p_json", "{not json");
    expect(m.readMediaCache("p_json")).toEqual({});
    ls.setItem("shiguang:team:media:p_arr", "[1,2,3]");
    expect(m.readMediaCache("p_arr")).toEqual({});
  });

  it("pruneMediaCache 剔掉服务端已删的并报数量", async () => {
    const m = await import("./teamAssets");
    const { kept, dropped } = m.pruneMediaCache(
      { a: SHA, b: SHA2, c: SHA2 },
      new Set([SHA]),
    );
    expect(kept).toEqual({ a: SHA });
    expect(dropped).toBe(2);
    // 全不在 ⇒ 全剔，调用方据此决定重传
    expect(m.pruneMediaCache({ a: SHA }, new Set()).kept).toEqual({});
  });

  it("localStorage 不可用时写入静默失败、读取回空（不拦住上传）", async () => {
    (globalThis as unknown as { window: { localStorage: unknown } }).window = {
      get localStorage(): never {
        throw new Error("SecurityError");
      },
    };
    const m = await import("./teamAssets");
    expect(() => m.writeMediaCache("p_1", { a: SHA })).not.toThrow();
    expect(m.readMediaCache("p_1")).toEqual({});
  });
});
