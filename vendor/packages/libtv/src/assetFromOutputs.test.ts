/**
 * assetFromOutputs 单测（2026-11-02 · 画布 0.3.37）
 *
 * 锁的是「右键加入我的资产」背后的**判断**：什么能存、存成哪个 kind、标题怎么裁、
 * 什么情况必须拒绝（宁可不存，也不在资产库里留一张点开是破图的卡片）。
 * 菜单本身是 UI，vitest 无 jsdom ⇒ 不在这里测。
 */
import { describe, expect, it } from "vitest";

import {
  ASSET_TITLE_MAX,
  assetFromGallery,
  assetFromHistory,
  whyNotSaveable,
} from "./assetFromOutputs";

describe("assetFromOutputs · 输出历史 → 资产", () => {
  it("图片条目：url 带过去，标题原样，prompt 保留", () => {
    const d = assetFromHistory({
      category: "image",
      title: "第 3 卡 特写",
      prompt: "cinematic portrait",
      assetUrl: "http://127.0.0.1:18765/media/a.png",
    });
    expect(d).toMatchObject({
      title: "第 3 卡 特写",
      kind: "image",
      url: "http://127.0.0.1:18765/media/a.png",
      prompt: "cinematic portrait",
    });
  });

  it("视频条目归到 video kind（不是当图片存）", () => {
    const d = assetFromHistory({ category: "video", title: "镜头1", assetUrl: "/m/v.mp4" });
    expect(d?.kind).toBe("video");
  });

  it("没有产物 URL（文本类）⇒ null，不造空资产", () => {
    expect(assetFromHistory({ category: "text", title: "分镜文案", assetUrl: "" })).toBeNull();
  });

  it("音频暂不支持 LocalAsset 的 kind ⇒ null", () => {
    expect(assetFromHistory({ category: "audio", title: "主题曲", assetUrl: "/m/a.mp3" })).toBeNull();
  });

  it("标题为空时按类型兜底", () => {
    expect(assetFromHistory({ category: "image", assetUrl: "/x.png" })?.title).toBe("图片");
    expect(assetFromHistory({ category: "video", assetUrl: "/x.mp4" })?.title).toBe("视频");
  });

  it("超长标题截断并加省略号（不让提示词把名字撑爆）", () => {
    const long = "a".repeat(80);
    const t = assetFromHistory({ category: "image", title: long, assetUrl: "/x.png" })!.title;
    expect(t.length).toBe(ASSET_TITLE_MAX + 1);
    expect(t.endsWith("…")).toBe(true);
  });

  it("空白 URL 视为没有产物（不能靠空格骗过检查）", () => {
    expect(assetFromHistory({ category: "image", assetUrl: "   " })).toBeNull();
  });
});

describe("assetFromOutputs · 图库缩略图 → 资产", () => {
  it("视频项用首帧封面当 url，但 kind 仍是 video", () => {
    const d = assetFromGallery({ kind: "video", title: "镜头2", thumb: "/poster.png" });
    expect(d).toMatchObject({ kind: "video", url: "/poster.png", title: "镜头2" });
  });

  it("没有缩略图（节点还没产物）⇒ null", () => {
    expect(assetFromGallery({ kind: "image", title: "空节点", thumb: "" })).toBeNull();
  });

  it("图库条目会带上提示词", () => {
    const d = assetFromGallery({ kind: "image", thumb: "/a.png", prompt: "雨天街道" });
    expect(d?.prompt).toBe("雨天街道");
    expect(d?.title).toBe("图片");
  });
});

describe("assetFromOutputs · 置灰理由", () => {
  it("能存时理由为空串", () => {
    expect(whyNotSaveable("image", "/a.png")).toBe("");
  });

  it("文本 / 音频 / 其它分别给出各自的原因（不写同一句万能话）", () => {
    expect(whyNotSaveable("text", "")).toContain("文本");
    expect(whyNotSaveable("audio", "")).toContain("音频");
    expect(whyNotSaveable("image", "")).toContain("还没有生成结果");
  });
});
