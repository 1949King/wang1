/**
 * 素材筛选（2026-11-04 · 画布 0.3.49）
 *
 * 重点锁两条**会让用户以为素材丢了**的行为：
 *   1. 搜 `owner`（出处「镜 03」）也要命中 —— 用户记得住的常常是哪一镜，不是文件名；
 *   2. 空结果不能只说「没有素材」—— 得说清「共 N 条还在，是筛选/搜索把它们藏了」。
 */
import { describe, expect, it } from "vitest";

import { assetCounts, bucketOf, emptyAssetHint, filterAssets, kindLabel } from "./assetFilter";
import type { TeamAsset } from "./teamClient";

const A = (patch: Partial<TeamAsset>): TeamAsset => ({
  sha256: "s",
  name: "x",
  kind: "file",
  mime: "",
  bytes: 1,
  author: "张三",
  created_at: 0,
  ...patch,
});

const LIST: TeamAsset[] = [
  A({ sha256: "1", name: "成片.mp4", kind: "video", owner: "镜 03" }),
  A({ sha256: "2", name: "封面.png", kind: "image", owner: "镜 03" }),
  A({ sha256: "3", name: "bgm.mp3", kind: "audio", owner: "" }),
  A({ sha256: "4", name: "剧本.txt", kind: "text", owner: "剧本" }),
];

describe("bucketOf / kindLabel", () => {
  it("后端的 text/file 都归到「其他」，其余原样", () => {
    expect(bucketOf("image")).toBe("image");
    expect(bucketOf("video")).toBe("video");
    expect(bucketOf("audio")).toBe("audio");
    expect(bucketOf("text")).toBe("other");
    expect(bucketOf("file")).toBe("other");
    expect(bucketOf("")).toBe("other");
  });

  it("筛选项都有中文标签（不出英文 key 给用户看）", () => {
    expect(kindLabel("all")).toBe("全部");
    expect(kindLabel("video")).toContain("视频");
    expect(kindLabel("other")).toContain("其他");
  });
});

describe("filterAssets", () => {
  it("按类型筛，不影响其他类型", () => {
    expect(filterAssets(LIST, "video").map((a) => a.name)).toEqual(["成片.mp4"]);
    expect(filterAssets(LIST, "other").map((a) => a.name)).toEqual(["剧本.txt"]);
    expect(filterAssets(LIST, "all")).toHaveLength(4);
  });

  it("搜索命中文件名、出处（镜 03）与作者", () => {
    expect(filterAssets(LIST, "all", "镜 03").map((a) => a.name)).toEqual(["成片.mp4", "封面.png"]);
    expect(filterAssets(LIST, "all", "BGM").map((a) => a.name)).toEqual(["bgm.mp3"]);
    expect(filterAssets(LIST, "all", "张三")).toHaveLength(4);
  });

  it("类型与搜索叠加，不是二选一", () => {
    expect(filterAssets(LIST, "video", "镜 03").map((a) => a.name)).toEqual(["成片.mp4"]);
    expect(filterAssets(LIST, "audio", "镜 03")).toEqual([]);
  });

  it("首尾空格不该让搜索空手而归", () => {
    expect(filterAssets(LIST, "all", "  成片  ")).toHaveLength(1);
  });
});

describe("assetCounts", () => {
  it("每一项都算上，all 等于总数", () => {
    const c = assetCounts(LIST);
    expect(c).toEqual({ all: 4, video: 1, image: 1, audio: 1, other: 1 });
  });

  it("空列表全 0（不出现 NaN）", () => {
    expect(assetCounts([])).toEqual({ all: 0, video: 0, image: 0, audio: 0, other: 0 });
  });
});

describe("emptyAssetHint", () => {
  it("项目真的没素材：说怎么传", () => {
    expect(emptyAssetHint(0, "all", "")).toContain("还没有素材");
  });

  it("是筛选把素材藏了：必须说「素材还在」", () => {
    const s = emptyAssetHint(23, "video", "镜 09");
    expect(s).toContain("23 条素材还在");
    expect(s).toContain("镜 09");
    expect(s).not.toContain("还没有素材");
  });
});
