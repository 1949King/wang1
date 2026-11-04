import { describe, it, expect, vi } from "vitest";
import {
  planPoseVideoFrames,
  capturePoseFrames,
  encodePoseVideo,
  MAX_POSE_VIDEO_FRAMES,
  DEFAULT_POSE_VIDEO_FPS,
  type PoseFrameSource,
} from "./stage3dPoseVideo";

const PNG = "data:image/png;base64,iVBORw0KGgo=";

describe("planPoseVideoFrames 帧规划", () => {
  it("0 帧返回空", () => {
    const p = planPoseVideoFrames(0);
    expect(p.indices).toEqual([]);
    expect(p.capped).toBe(false);
  });

  it("负数/非法输入按 0 处理", () => {
    expect(planPoseVideoFrames(-5).indices).toEqual([]);
    expect(planPoseVideoFrames(NaN).indices).toEqual([]);
  });

  it("未超上限：逐帧，step=1，不抽稀", () => {
    const p = planPoseVideoFrames(90);
    expect(p.indices.length).toBe(90);
    expect(p.indices[0]).toBe(0);
    expect(p.indices[89]).toBe(89);
    expect(p.step).toBe(1);
    expect(p.capped).toBe(false);
  });

  it("恰好等于上限：仍逐帧", () => {
    const p = planPoseVideoFrames(MAX_POSE_VIDEO_FRAMES);
    expect(p.indices.length).toBe(MAX_POSE_VIDEO_FRAMES);
    expect(p.capped).toBe(false);
  });

  it("超上限：抽稀到恰好 cap 个，且保首尾", () => {
    const total = 1000;
    const cap = 300;
    const p = planPoseVideoFrames(total, cap);
    expect(p.indices.length).toBe(cap);
    expect(p.indices[0]).toBe(0);
    expect(p.indices[cap - 1]).toBe(total - 1);
    expect(p.capped).toBe(true);
    // 严格递增、无重复
    for (let i = 1; i < p.indices.length; i++) {
      expect(p.indices[i]).toBeGreaterThan(p.indices[i - 1]);
    }
  });

  it("抽稀不能丢一半帧（防 step=ceil 的回退）", () => {
    // 1000/900 若用 step=ceil(1000/900)=2 只会取到 500 帧
    const p = planPoseVideoFrames(1000, 900);
    expect(p.indices.length).toBe(900);
  });

  it("cap=1 的边界：只取首帧，不除零", () => {
    const p = planPoseVideoFrames(50, 1);
    expect(p.indices).toEqual([0]);
  });

  it("抽稀后下标都在合法范围内", () => {
    const p = planPoseVideoFrames(12345, 900);
    expect(Math.min(...p.indices)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...p.indices)).toBeLessThan(12345);
  });
});

function makeSource(over: Partial<PoseFrameSource> = {}): {
  src: PoseFrameSource;
  rendered: number[];
} {
  const rendered: number[] = [];
  const src: PoseFrameSource = {
    renderFrameToRT: (i: number) => {
      rendered.push(i);
    },
    readRTAsDataUrl: () => PNG,
    ...over,
  };
  return { src, rendered };
}

describe("capturePoseFrames 逐帧采集", () => {
  it("正常采集：帧数与渲染次数一致", async () => {
    const { src, rendered } = makeSource();
    const r = await capturePoseFrames(src, 12);
    expect(r.ok).toBe(true);
    expect(r.frames.length).toBe(12);
    expect(rendered).toEqual(Array.from({ length: 12 }, (_, i) => i));
  });

  it("0 帧：诚实失败", async () => {
    const { src } = makeSource();
    const r = await capturePoseFrames(src, 0);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("没有可采集的帧");
    expect(r.frames).toEqual([]);
  });

  it("渲染抛错：诚实失败，不产半成品", async () => {
    const { src } = makeSource({
      renderFrameToRT: (i: number) => {
        if (i === 3) throw new Error("boom");
      },
    });
    const r = await capturePoseFrames(src, 10);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("渲染第 4 帧失败");
    expect(r.frames).toEqual([]);
  });

  it("读像素抛错：诚实失败", async () => {
    const { src } = makeSource({
      readRTAsDataUrl: () => {
        throw new Error("no rt");
      },
    });
    const r = await capturePoseFrames(src, 5);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("读取第 1 帧像素失败");
  });

  it("读到空白画面：诚实失败（不当成成功但空帧）", async () => {
    const { src } = makeSource({ readRTAsDataUrl: () => "" });
    const r = await capturePoseFrames(src, 5);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("空白画面");
  });

  it("非 data URL 也判为失败", async () => {
    const { src } = makeSource({ readRTAsDataUrl: () => "blob:xxx" });
    const r = await capturePoseFrames(src, 3);
    expect(r.ok).toBe(false);
  });

  it("进度回调被调用，且最后一帧必回调", async () => {
    const seen: number[] = [];
    const { src } = makeSource();
    const r = await capturePoseFrames(src, 23, {
      onProgress: (done) => seen.push(done),
    });
    expect(r.ok).toBe(true);
    expect(seen[seen.length - 1]).toBe(23);
  });

  it("超上限时采集数 = cap，且首尾帧都被渲染", async () => {
    const { src, rendered } = makeSource();
    const r = await capturePoseFrames(src, 1000, { cap: 50 });
    expect(r.ok).toBe(true);
    expect(r.frames.length).toBe(50);
    expect(r.capped).toBe(true);
    expect(rendered[0]).toBe(0);
    expect(rendered[rendered.length - 1]).toBe(999);
  });
});

describe("encodePoseVideo 上传", () => {
  it("空帧：本地就挡住，不发起请求", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const r = await encodePoseVideo([]);
    expect(r.ok).toBe(false);
    expect(r.message).toContain("没有可合成的帧");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("默认帧率与常量一致", () => {
    expect(DEFAULT_POSE_VIDEO_FPS).toBe(25);
  });
});
