/**
 * lighting.test.ts — 电影级灯位库回归（2026-10-06）。
 *
 * 这个功能的判据错会让**用户的提示词被写坏**（越写越长 / 把用户自己的文字删掉），
 * 所以重点锁三件：
 *  ① **数据完整性**：24 主光位（0–345°，每 15°）+ 9 轮廓光，编号唯一、名字非空；
 *  ② **受管块**：反复套用只保留**一个**光照块（替换而非叠加）；
 *  ③ **只动我们写的那一块**：`strip` 不得伤到用户自己的文字。
 */
import { describe, expect, it } from "vitest";

import {
  applyLightingBlock,
  buildLightingBlock,
  buildLightingText,
  KEY_LIGHTS,
  readLightingBlock,
  RIM_LIGHTS,
  stripLightingBlock,
} from "./lightingPresets";

describe("数据完整性", () => {
  it("主光位 24 个，方位角 0–345 每 15° 一档且唯一", () => {
    expect(KEY_LIGHTS).toHaveLength(24);
    const azs = KEY_LIGHTS.map((k) => k.azimuth);
    expect(azs[0]).toBe(0);
    expect(azs[23]).toBe(345);
    expect(new Set(azs).size).toBe(24);
    for (let i = 1; i < azs.length; i++) expect(azs[i] - azs[i - 1]).toBe(15);
  });

  it("每个主光位都有名字、高度、色温（无空字段）", () => {
    for (const k of KEY_LIGHTS) {
      expect(k.name.trim().length).toBeGreaterThan(0);
      expect(k.height).toBeGreaterThanOrEqual(0);
      expect(k.height).toBeLessThanOrEqual(90);
      expect(k.kelvin).toBeGreaterThan(1000);
      expect(k.intensity).toBeGreaterThan(0);
    }
  });

  it("经典灯位落在整数格上：45=伦勃朗 / 90=正侧 / 180=正逆", () => {
    const at = (a: number) => KEY_LIGHTS.find((k) => k.azimuth === a)?.name || "";
    expect(at(45)).toContain("伦勃朗");
    expect(at(90)).toContain("侧光");
    expect(at(180)).toContain("逆光");
  });

  it("轮廓光 9 组，名字唯一", () => {
    expect(RIM_LIGHTS).toHaveLength(9);
    const names = RIM_LIGHTS.map((r) => r.name);
    expect(new Set(names).size).toBe(9);
    expect(names).toContain("无轮廓光");
  });
});

describe("光照文本", () => {
  it("含灯名、角度、色温", () => {
    const t = buildLightingText({ keyAzimuth: 45, rimName: "后上 45° 轮廓" });
    expect(t).toContain("伦勃朗");
    expect(t).toContain("45°");
    expect(t).toContain("K");
  });

  it("选「无轮廓光」时不写轮廓", () => {
    const t = buildLightingText({ keyAzimuth: 45, rimName: "无轮廓光" });
    expect(t).not.toContain("轮廓");
  });

  it("未知方位也不炸（不编造灯名）", () => {
    const t = buildLightingText({ keyAzimuth: 999, rimName: "无轮廓光" });
    expect(t).toContain("999°");
  });
});

describe("受管块（★ 反复套用不许越写越长）", () => {
  it("空提示词 ⇒ 只写块", () => {
    const out = applyLightingBlock("", { keyAzimuth: 45, rimName: "无轮廓光" });
    expect(out).toBe(buildLightingBlock({ keyAzimuth: 45, rimName: "无轮廓光" }));
  });

  it("保留用户原文，块追加在末尾", () => {
    const out = applyLightingBlock("一个女孩在雨夜街头", { keyAzimuth: 90, rimName: "无轮廓光" });
    expect(out.startsWith("一个女孩在雨夜街头")).toBe(true);
    expect(out).toContain("〔光照：");
  });

  it("★ 套用两次不同灯位 ⇒ 仍只有一个块（替换而非叠加）", () => {
    let p = applyLightingBlock("主体描述", { keyAzimuth: 45, rimName: "无轮廓光" });
    p = applyLightingBlock(p, { keyAzimuth: 180, rimName: "双侧轮廓" });
    expect((p.match(/〔光照：/g) || []).length).toBe(1);
    expect(p).toContain("180°");
    expect(p).not.toContain("45°/高度");
  });

  it("套十次也不膨胀", () => {
    let p = "主体";
    for (let i = 0; i < 10; i++) {
      p = applyLightingBlock(p, { keyAzimuth: i * 15, rimName: "无轮廓光" });
    }
    expect((p.match(/〔光照：/g) || []).length).toBe(1);
    expect(p.length).toBeLessThan(120);
  });
});

describe("移除（只动我们那一块）", () => {
  it("strip 后回到用户原文", () => {
    const user = "一个女孩在雨夜街头，霓虹反射";
    const withLight = applyLightingBlock(user, { keyAzimuth: 45, rimName: "无轮廓光" });
    expect(stripLightingBlock(withLight)).toBe(user);
  });

  it("没有块时原样返回（幂等）", () => {
    expect(stripLightingBlock("纯用户文本")).toBe("纯用户文本");
    expect(stripLightingBlock("")).toBe("");
  });

  it("只有开符号（残缺）时不误删用户文字", () => {
    expect(stripLightingBlock("用户文本〔光照：没闭合")).toBe("用户文本〔光照：没闭合");
  });

  it("read 能读回当前块（往返一致）", () => {
    const choice = { keyAzimuth: 315, rimName: "顶轮廓" };
    const p = applyLightingBlock("x", choice);
    expect(readLightingBlock(p)).toBe(buildLightingBlock(choice));
  });
});
