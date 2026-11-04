/**
 * CodeVideoSpec 前端契约镜像单测（2026-10-20）。
 * 只测纯函数；不加载 React/store/后端。
 */
import { describe, expect, it } from "vitest";
import {
  ALLOWED_FPS,
  MAX_CLIPS,
  MAX_DURATION,
  SPEC_VERSION,
  TEXT_KINDS,
  assetKeys,
  htmlSources,
  isValidAssetPath,
  isValidHtmlName,
  textLayerWarnings,
  toBackendPayload,
  totalClips,
  validateSpec,
  type CodeVideoSpecData,
} from "./codeVideoSpec";

function spec(): CodeVideoSpecData {
  return {
    version: SPEC_VERSION,
    canvas: { width: 1080, height: 1920, fps: 30, duration: 6 },
    tracks: [
      {
        id: "v1",
        kind: "video",
        clips: [
          { id: "c1", source: "asset://shot_1.mp4", range: [0, 3], kind: "video" },
          { id: "c2", source: "asset://shot_2.mp4", range: [3, 6], kind: "video" },
        ],
      },
      {
        id: "s1",
        kind: "subtitle",
        clips: [{ id: "sub", source: "html://subtitle.html", range: [0, 6], kind: "subtitle" }],
      },
    ],
    assets: {
      "shot_1.mp4": { kind: "video", duration: 3 },
      "shot_2.mp4": { kind: "video", duration: 3 },
    },
  };
}

describe("常量镜像", () => {
  it("与后端常量一致", () => {
    expect(SPEC_VERSION).toBe("1.0");
    expect(ALLOWED_FPS).toEqual([24, 30]);
    expect(TEXT_KINDS).toEqual(["text", "subtitle"]);
    expect(MAX_DURATION).toBe(60);
    expect(MAX_CLIPS).toBe(12);
  });
});

describe("validateSpec", () => {
  it("合法 spec 通过", () => {
    expect(validateSpec(spec())).toEqual([]);
  });

  it("非对象 / 版本错误 / 缺 canvas", () => {
    expect(validateSpec(null)[0]).toContain("不是对象");
    expect(validateSpec({ ...spec(), version: "2.0" }).join()).toContain("version");
    expect(validateSpec({ version: SPEC_VERSION }).join()).toContain("canvas");
  });

  it("重复 track/clip id 被拒", () => {
    const s = spec();
    s.tracks.push({ id: "v1", kind: "video", clips: [] });
    expect(validateSpec(s).join()).toContain("tracks id 重复");
    const s2 = spec();
    s2.tracks[1].clips[0].id = "c1";
    expect(validateSpec(s2).join()).toContain("clip id 重复");
  });

  it("range 与 source 前缀被校验", () => {
    const s = spec();
    s.tracks[0].clips[0].range = [0] as unknown as [number, number];
    s.tracks[0].clips[1].source = "file:///etc/passwd";
    const errors = validateSpec(s).join();
    expect(errors).toContain("range");
    expect(errors).toContain("source");
  });
});

describe("路径与统计", () => {
  it("html 文件名白名单", () => {
    expect(isValidHtmlName("title.html")).toBe(true);
    expect(isValidHtmlName("Title.html")).toBe(false);
    expect(isValidHtmlName("../x.html")).toBe(false);
  });

  it("asset 路径白名单", () => {
    expect(isValidAssetPath("shot_1.mp4")).toBe(true);
    expect(isValidAssetPath("inbox/a.mp4")).toBe(true);
    expect(isValidAssetPath("../a.mp4")).toBe(false);
    expect(isValidAssetPath("C:/a.mp4")).toBe(false); // 盘符含 ':' ⇒ 白名单直接拒绝
    expect(isValidAssetPath("/abs/a.mp4")).toBe(false);
  });

  it("统计与提取", () => {
    const s = spec();
    expect(totalClips(s)).toBe(3);
    expect(htmlSources(s)).toEqual(["html://subtitle.html"]);
    expect(assetKeys(s)).toEqual(["shot_1.mp4", "shot_2.mp4"]);
  });

  it("文字层提示（最终以后端为准）", () => {
    const s = spec();
    s.tracks[1].clips[0].source = "asset://x.mp4";
    expect(textLayerWarnings(s).join()).toContain("文字层必须 html://");
  });

  it("后端载荷原样透传", () => {
    const s = spec();
    expect(toBackendPayload(s)).toEqual({ spec: s });
  });
});
