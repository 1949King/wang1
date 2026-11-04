import { describe, it, expect } from "vitest";
import { CameraRecorder, thinRecordFrames } from "./cameraRecorder";

describe("thinRecordFrames 抽稀", () => {
  it("空帧返回空数组", () => {
    expect(thinRecordFrames([], 24)).toEqual([]);
  });

  it("保首尾，均匀抽到 maxPoints 个点", () => {
    const frames = Array.from({ length: 100 }, (_, i) => ({
      pos: [i, 0, 0] as [number, number, number],
      look: [0, 1, 0] as [number, number, number],
      t: i * 16,
    }));
    const out = thinRecordFrames(frames, 8);
    expect(out.length).toBe(8);
    expect(out[0].pos[0]).toBe(0);
    expect(out[7].pos[0]).toBe(99);
  });

  it("maxPoints 大于帧数时按实际帧数返回", () => {
    const frames = [
      { pos: [0, 0, 0] as [number, number, number], look: [0, 0, 0] as [number, number, number], t: 0 },
      { pos: [1, 0, 0] as [number, number, number], look: [0, 0, 0] as [number, number, number], t: 16 },
    ];
    expect(thinRecordFrames(frames, 24).length).toBe(2);
  });
});

describe("CameraRecorder 录制", () => {
  it("未录制时 record 不采样", () => {
    const r = new CameraRecorder();
    r.record([0, 0, 0], [0, 0, 0], 0);
    expect(r.count).toBe(0);
  });

  it("start → record → stop 产出路径点与时长", () => {
    const r = new CameraRecorder();
    r.start(0);
    r.record([0, 0, 4], [0, 1, 0], 0);
    r.record([0, 0, 3], [0, 1, 0], 100);
    r.record([0, 0, 2], [0, 1, 0], 200);
    r.record([1, 0, 1], [0, 1, 0], 300);
    const { durationMs, pathPoints } = r.stop(3);
    expect(durationMs).toBe(300);
    expect(pathPoints.length).toBe(3);
    expect(pathPoints[0].pos).toEqual([0, 0, 4]);
    expect(pathPoints[2].pos).toEqual([1, 0, 1]);
    expect(r.isRecording).toBe(false);
  });

  it("最小采样间隔内重复 record 只记一帧", () => {
    const r = new CameraRecorder();
    r.start(0);
    r.record([0, 0, 0], [0, 0, 0], 0);
    r.record([0, 0, 0], [0, 0, 0], 8); // < 16ms，被吞
    r.record([0, 0, 0], [0, 0, 0], 16);
    expect(r.count).toBe(2);
  });

  it("录制太短 stop 返回少于 2 点（调用方应拦截）", () => {
    const r = new CameraRecorder();
    r.start(0);
    r.record([0, 0, 0], [0, 0, 0], 0);
    const { pathPoints } = r.stop();
    expect(pathPoints.length).toBe(1);
  });
});
