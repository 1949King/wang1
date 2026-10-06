/**
 * outputHistory.test.ts — 「输出历史」回归（2026-10-06）。
 *
 * 判据错的话，用户会**搜不到自己做过的东西**（比没有面板更糟），所以这里把
 * 分类映射 / 收集判据 / 搜索范围 / 计数 / 配方文本逐条钉住。
 *
 * 另锁：搜索范围必须覆盖「提示词 · 输出内容 · 模型」（对标参考产品）+ **种子**（我们的兑现口）。
 */
import { describe, expect, it } from "vitest";

import {
  CATEGORY_LABEL,
  categoryOf,
  collectHistory,
  countByCategory,
  filterHistory,
  matchesQuery,
  recipeOf,
} from "./outputHistory";

const N = (id: string, data: Record<string, unknown>) => ({ id, data });

describe("分类映射", () => {
  it("图像/视频/音频/文本 各归其位", () => {
    expect(categoryOf("image")).toBe("image");
    expect(categoryOf("shot")).toBe("image");
    expect(categoryOf("video")).toBe("video");
    expect(categoryOf("music")).toBe("audio");
    expect(categoryOf("script")).toBe("text");
    expect(categoryOf("storyboard")).toBe("text");
  });

  it("非产物类（group/generator）不进历史", () => {
    expect(categoryOf("group")).toBeNull();
    expect(categoryOf("generator")).toBeNull();
  });

  it("四类都有中文名（tab 用）", () => {
    for (const k of ["text", "image", "video", "audio"] as const) {
      expect(CATEGORY_LABEL[k]).toBeTruthy();
    }
  });
});

describe("collectHistory 收集判据", () => {
  it("只收**有产物**的节点（没产物的不进历史）", () => {
    const rows = collectHistory([
      N("a", { kind: "image", prompt: "猫", imageUrl: "data:x" }),
      N("b", { kind: "image", prompt: "尚未生成" }),
      N("c", { kind: "video", prompt: "街", videoUrl: "file://v.mp4" }),
      N("d", { kind: "text", content: "剧本正文" }),
      N("e", { kind: "group" }),
    ]);
    expect(rows.map((r) => r.id)).toEqual(["a", "c", "d"]);
  });

  it("视频节点产物优先成片，退化到首帧/封面", () => {
    const [r] = collectHistory([N("v", { kind: "video", posterUrl: "p.png" })]);
    expect(r.assetUrl).toBe("p.png");
  });

  it("带出种子/评分/模型元信息（用于复现与筛选）", () => {
    const [r] = collectHistory([
      N("i", {
        kind: "image",
        prompt: "少女",
        imageUrl: "data:y",
        lastSeed: 4242,
        lastSeedSent: true,
        proxyScore: 0.71,
        model: "sd-xl",
      }),
    ]);
    expect(r.seed).toBe(4242);
    expect(r.seedSent).toBe(true);
    expect(r.score).toBeCloseTo(0.71);
    expect(r.model).toBe("sd-xl");
  });

  it("标题退化：没 title 就用提示词前 24 字", () => {
    const [r] = collectHistory([
      N("i", { kind: "image", prompt: "一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十", imageUrl: "d" }),
    ]);
    expect(r.title.length).toBeLessThanOrEqual(24);
  });

  it("空输入不炸", () => {
    expect(collectHistory([])).toEqual([]);
    expect(collectHistory(undefined as never)).toEqual([]);
  });
});

describe("搜索与过滤", () => {
  const rows = collectHistory([
    N("1", { kind: "image", prompt: "赛博朋克少女", imageUrl: "d1", model: "sd15", lastSeed: 777 }),
    N("2", { kind: "video", prompt: "城市街景", videoUrl: "v1", model: "seedance" }),
    N("3", { kind: "text", content: "第一集剧本：雨夜相遇" }),
  ]);

  it("按分类过滤", () => {
    expect(filterHistory(rows, { category: "image" }).map((r) => r.id)).toEqual(["1"]);
    expect(filterHistory(rows, { category: "all" })).toHaveLength(3);
  });

  it("搜索覆盖 提示词 / 输出内容 / 模型 / 种子", () => {
    expect(filterHistory(rows, { query: "赛博" }).map((r) => r.id)).toEqual(["1"]);
    expect(filterHistory(rows, { query: "雨夜" }).map((r) => r.id)).toEqual(["3"]);
    expect(filterHistory(rows, { query: "seedance" }).map((r) => r.id)).toEqual(["2"]);
    expect(filterHistory(rows, { query: "777" }).map((r) => r.id)).toEqual(["1"]);
  });

  it("空查询返回全部；大小写不敏感", () => {
    expect(filterHistory(rows, { query: "  " })).toHaveLength(3);
    expect(matchesQuery(rows[1], "SEEDANCE")).toBe(true);
  });

  it("分类 + 搜索是交集", () => {
    expect(filterHistory(rows, { category: "video", query: "赛博" })).toHaveLength(0);
  });

  it("计数含 all 与四类", () => {
    const c = countByCategory(rows);
    expect(c.all).toBe(3);
    expect(c.image).toBe(1);
    expect(c.text).toBe(1);
    expect(c.audio).toBe(0);
  });
});

describe("配方文本（抽卡闭环的兑现口）", () => {
  it("含提示词 + 种子 + 模型", () => {
    const [r] = collectHistory([
      N("1", { kind: "image", prompt: "少女", imageUrl: "d", lastSeed: 9, lastSeedSent: true, model: "sd15" }),
    ]);
    const t = recipeOf(r);
    expect(t).toContain("少女");
    expect(t).toContain("seed=9");
    expect(t).toContain("model=sd15");
  });

  it("渠道没收到种子时**如实标注**不可复现（不假装可复现）", () => {
    const [r] = collectHistory([
      N("1", { kind: "image", prompt: "少女", imageUrl: "d", lastSeed: 9, lastSeedSent: false }),
    ]);
    expect(recipeOf(r)).toContain("渠道未透传");
  });

  it("没有种子就不写种子（绝不编造）", () => {
    const [r] = collectHistory([N("1", { kind: "image", prompt: "少女", imageUrl: "d" })]);
    expect(recipeOf(r)).not.toContain("seed=");
  });
});
