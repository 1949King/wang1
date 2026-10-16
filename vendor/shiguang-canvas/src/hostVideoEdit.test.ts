/**
 * hostVideoEdit 纯函数回归锁（P1-2 步骤 4，2026-10-15）
 *
 * 核心是**诚实边界**的回归锁（与 hostBreakdownL2.test.ts 同纪律）：
 * 后端「失败保原镜」（video_edit_client.py:362），前端若把失败响应的
 * clip_path 当新结果展示、或把缺 url 拼成假地址，就是把「没改成」说成「改成了」。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  runVideoEdit,
  summarizeVideoEdit,
  type VideoEditOutcome,
} from "./hostVideoEdit";
import { videoEdit } from "./bridgeStoryboard";

vi.mock("./bridgeStoryboard", () => ({
  videoEdit: vi.fn(),
}));

const mockEdit = vi.mocked(videoEdit);

describe("hostVideoEdit · 诚实映射（逐字透传，不美化）", () => {
  it("成功：channel_used/cost_note/url/errors 全部原样带出", () => {
    const s = summarizeVideoEdit({
      ok: true,
      clip_path: "D:/inbox/edit_seedance_1.mp4",
      url: "/inbox_file/edit_seedance_1.mp4",
      original_kept: false,
      channel_used: "seedance",
      cost_note: "按 token 计费（估算以账单为准）",
      errors: ["kling: 可灵编辑需公网 URL（素材出域），未显式提供 video_url"],
    });
    expect(s.ok).toBe(true);
    expect(s.channelUsed).toBe("seedance");
    expect(s.costNote).toBe("按 token 计费（估算以账单为准）");
    expect(s.url).toBe("/inbox_file/edit_seedance_1.mp4");
    expect(s.originalKept).toBe(false);
    // 顺延失败原因必须逐字保留，不许吞
    expect(s.errors).toHaveLength(1);
    expect(s.errors[0]).toContain("可灵编辑需公网 URL");
  });

  it("失败：clip_path=原片段、original_kept=true，且 url **强制为空**（不显示幽灵地址）", () => {
    const s = summarizeVideoEdit({
      ok: false,
      clip_path: "D:/inbox/a.mp4",
      url: "/inbox_file/ghost.mp4",
      original_kept: true,
      errors: [],
      message: "所有编辑渠道失败，原片段已保留（未产生任何改动）",
    });
    expect(s.url).toBe("");
    expect(s.clipPath).toBe("D:/inbox/a.mp4");
    expect(s.originalKept).toBe(true);
    expect(s.message).toBe("所有编辑渠道失败，原片段已保留（未产生任何改动）");
  });

  it("成功但 inbox 复制失败（url 空）⇒ 只有磁盘路径，可播放地址为空", () => {
    const s = summarizeVideoEdit({
      ok: true,
      clip_path: "D:/temp/video_edit/edit_kling_2.mp4",
      url: "",
      original_kept: false,
      channel_used: "kling",
      errors: ["结果复制 inbox 失败: 磁盘满"],
    });
    expect(s.url).toBe("");
    expect(s.clipPath).toBe("D:/temp/video_edit/edit_kling_2.mp4");
    expect(s.errors[0]).toContain("复制 inbox 失败");
  });

  it("缺字段兜底要保守：original_kept 缺失时 失败=true / 成功=false；errors 缺失=空数组", () => {
    const f = summarizeVideoEdit({ ok: false });
    expect(f.originalKept).toBe(true);
    expect(f.errors).toEqual([]);
    expect(f.message).toBe("指令式编辑失败");
    const t = summarizeVideoEdit({ ok: true, clip_path: "x" });
    expect(t.originalKept).toBe(false);
    expect(t.url).toBe("");
  });
});

describe("hostVideoEdit · 本地预检（不打网络）与端点调用", () => {
  beforeEach(() => {
    mockEdit.mockReset();
    vi.stubGlobal("window", { __SHIGUANG_BRIDGE_TOKEN: "test-token" });
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("空指令 / 无素材 / 未勾出域 / Kling 无 URL ⇒ 全部本地失败且不调桥", async () => {
    const base = { clipPath: "a.mp4", instruction: "去掉背景人物", egressAck: true };
    expect((await runVideoEdit({ ...base, instruction: "  " })).message).toContain("编辑指令");
    expect(
      (await runVideoEdit({ clipPath: "", instruction: "x", egressAck: true })).message,
    ).toContain("公网视频 URL");
    expect((await runVideoEdit({ ...base, egressAck: false })).message).toContain("云端");
    expect((await runVideoEdit({ ...base, channel: "kling" })).message).toContain("公网视频 URL");
    expect(mockEdit).not.toHaveBeenCalled();
  });

  it("预检全过 ⇒ 参数透传桥函数（指令去首尾空白、channel 默认 auto）", async () => {
    mockEdit.mockResolvedValue({
      ok: true,
      clip_path: "D:/i/new.mp4",
      url: "/inbox_file/new.mp4",
      original_kept: false,
      channel_used: "seedance",
      cost_note: "c",
      errors: [],
    });
    const r = await runVideoEdit({
      clipPath: "D:/i/old.mp4",
      instruction: " 去掉背景人物 ",
      egressAck: true,
    });
    expect(r.ok).toBe(true);
    expect(r.url).toBe("/inbox_file/new.mp4");
    const arg = mockEdit.mock.calls[0][0];
    expect(arg.instruction).toBe("去掉背景人物");
    expect(arg.channel).toBe("auto");
    expect(arg.clip_path).toBe("D:/i/old.mp4");
  });

  it("桥函数异常：不外抛，回可展示 message 且 originalKept=true", async () => {
    mockEdit.mockRejectedValue(new Error("ECONNRESET"));
    const r: VideoEditOutcome = await runVideoEdit({
      clipPath: "a.mp4",
      instruction: "x",
      egressAck: true,
    });
    expect(r.ok).toBe(false);
    expect(r.originalKept).toBe(true);
    expect(r.message).toContain("指令式编辑异常");
  });

  it("桥函数返回 ok=false ⇒ 原样映射（保原镜语义不丢）", async () => {
    mockEdit.mockResolvedValue({
      ok: false,
      clip_path: "a.mp4",
      original_kept: true,
      errors: ["seedance: 未配置火山方舟 Key（ARK_API_KEY），Seedance 编辑不可用"],
      message: "所有编辑渠道失败，原片段已保留（未产生任何改动）",
    });
    const r = await runVideoEdit({ clipPath: "a.mp4", instruction: "x", egressAck: true });
    expect(r.ok).toBe(false);
    expect(r.originalKept).toBe(true);
    expect(r.errors[0]).toContain("未配置火山方舟 Key");
  });
});
