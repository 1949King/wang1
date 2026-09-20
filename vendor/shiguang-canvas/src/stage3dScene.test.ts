import { describe, it, expect } from "vitest";
import {
  sceneToJSON,
  sceneStateFromJSON,
  diffScenes,
  type SceneState,
} from "./stage3dScene";

function makeScene(): SceneState {
  return {
    schemaVersion: 1,
    capturedAt: "2026-09-14T00:00:00.000Z",
    actors: [
      { id: "a1", name: "主角", kind: "actor", position: [0, 0, 0], rotation: [0, 0, 0], poseId: "idle" },
    ],
    cameras: [
      { id: "c1", name: "机位1", position: [0, 2, 5], lookAt: [0, 1, 0], fov: 35, shotSize: "中景", pathPoints: [] },
    ],
    selectedId: "a1",
    lightPreset: "neutral",
    groundPreset: "studio-dark",
    bgColor: "#141c28",
    fogColor: "#0c1220",
    viewport: { width: 1280, height: 720 },
    viewMode: "director",
  };
}

describe("stage3dScene 序列化", () => {
  it("sceneToJSON → sceneStateFromJSON 往返一致", () => {
    const s = makeScene();
    const json = sceneToJSON(s);
    const back = sceneStateFromJSON(json);
    expect(back.actors.length).toBe(1);
    expect(back.actors[0].name).toBe("主角");
    expect(back.cameras[0].fov).toBe(35);
    expect(back.viewport).toEqual({ width: 1280, height: 720 });
    expect(back.viewMode).toBe("director");
  });

  it("损坏输入不抛异常，回退到安全默认", () => {
    const back = sceneStateFromJSON(null);
    expect(back).toBeTruthy();
    expect(Array.isArray(back.actors)).toBe(true);
  });

  it("非法 hex 颜色回退默认", () => {
    const s = makeScene();
    s.bgColor = "not-a-color";
    const json = sceneToJSON(s);
    const back = sceneStateFromJSON(json);
    expect(back.bgColor).toMatch(/^#[0-9a-fA-F]{6}$/);
  });
});

describe("stage3dScene diffScenes", () => {
  it("检测新增/移除演员", () => {
    const before = makeScene();
    const after = makeScene();
    after.actors.push({ id: "a2", name: "配角", kind: "actor", position: [1, 0, 0], rotation: [0, 0, 0], poseId: "idle" });
    const d = diffScenes(before, after);
    expect(d.actorsAdded).toContain("a2");
    expect(d.actorsRemoved).toEqual([]);
  });

  it("检测灯光预设变化", () => {
    const before = makeScene();
    const after = makeScene();
    after.lightPreset = "golden-hour";
    const d = diffScenes(before, after);
    expect(d.presetChanged).toBe(true);
  });

  it("检测背景色变化", () => {
    const before = makeScene();
    const after = makeScene();
    after.bgColor = "#ffffff";
    const d = diffScenes(before, after);
    expect(d.bgColorChanged).toBe(true);
    expect(d.presetChanged).toBe(false);
  });
});
