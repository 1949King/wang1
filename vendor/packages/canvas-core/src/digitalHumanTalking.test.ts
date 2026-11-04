/**
 * digitalHumanTalking 客户端单测（V4.46.4）。
 * 只测纯逻辑与 fetch 契约（stub fetch），不起真桥。
 *
 * bridge.ts 模块顶层触碰 window（node 环境会炸）⇒ 整模块 mock，
 * 本模块对 bridge 的依赖只有 BRIDGE / authHeaders 两个符号。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./bridge", () => ({
  BRIDGE: "http://127.0.0.1:18765",
  authHeaders: (json = false) =>
    json ? { "Content-Type": "application/json", "X-Shiguang-Token": "t" }
         : { "X-Shiguang-Token": "t" },
}));

import { makeTalkingVideoViaHost, talkingVideoLabel } from "./digitalHumanTalking";

function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => vi.unstubAllGlobals());

describe("makeTalkingVideoViaHost", () => {
  it("空输入前端先挡：不发请求、mouth_moved 恒 false", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const r = await makeTalkingVideoViaHost({ image: "", audio: "" });
    expect(spy).not.toHaveBeenCalled();
    expect(r.ok).toBe(false);
    expect(r.mouth_moved).toBe(false);
    expect(r.missing).toHaveLength(2);
  });

  it("成功响应透传 url 并强制 mouth_moved=false", async () => {
    stubFetch(async () =>
      new Response(
        JSON.stringify({
          ok: true, path: "still_video", url: "/inbox_file/t.mp4",
          bytes: 2048, mouth_moved: false, note: "静态形象+配音（口型未动）",
          lipsync_note: "引擎未装",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const r = await makeTalkingVideoViaHost({ image: "a.png", audio: "b.wav" });
    expect(r.ok).toBe(true);
    expect(r.url).toBe("/inbox_file/t.mp4");
    expect(r.mouth_moved).toBe(false);
    expect(r.lipsync_note).toBe("引擎未装");
  });

  it("后端谎称 mouth_moved=true 也被前端钉回 false（双保险）", async () => {
    stubFetch(async () =>
      new Response(
        JSON.stringify({ ok: true, url: "/inbox_file/x.mp4", mouth_moved: true }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const r = await makeTalkingVideoViaHost({ image: "a", audio: "b" });
    expect(r.mouth_moved).toBe(false);
  });

  it("ok 但无 url ⇒ 降级为失败（不返回空成功）", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { "Content-Type": "application/json" },
      }),
    );
    const r = await makeTalkingVideoViaHost({ image: "a", audio: "b" });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("未返回可播放 URL");
  });

  it("网络异常诚实报错不抛", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("boom"); }));
    const r = await makeTalkingVideoViaHost({ image: "a", audio: "b" });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("boom");
    expect(r.mouth_moved).toBe(false);
  });
});

describe("talkingVideoLabel", () => {
  it("成功用后端 note；失败用 message", () => {
    expect(talkingVideoLabel({ ok: true, mouth_moved: false, note: "N" })).toBe("N");
    expect(talkingVideoLabel({ ok: false, message: "缺配音" })).toBe("缺配音");
    expect(talkingVideoLabel({ ok: false })).toBe("合成失败");
  });
});
