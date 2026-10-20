import { describe, expect, it } from "vitest";

import {
  DEFAULT_FACE_PARAMS,
  normalizeFaceParams,
  serializeFaceParams,
} from "./faceParams";
import {
  OFFICIAL_FACE_TEMPLATES,
  applyFaceTemplate,
  describeFace,
  findFaceTemplate,
} from "./faceTemplates";

describe("faceTemplates（官方模板库）", () => {
  it("提供 8 套官方模板，id 唯一且字段齐全", () => {
    expect(OFFICIAL_FACE_TEMPLATES).toHaveLength(8);
    const ids = OFFICIAL_FACE_TEMPLATES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of OFFICIAL_FACE_TEMPLATES) {
      expect(t.name.length).toBeGreaterThan(0);
      expect(t.tagline.length).toBeGreaterThan(0);
      expect(t.accent).toMatch(/^#[0-9a-fA-F]{6}$/);
      expect(Object.keys(t.params).length).toBeGreaterThan(0);
    }
  });

  it("应用模板 = 从 DEFAULT 起算的完整脸（不是在当前脸上打补丁）", () => {
    const cold = findFaceTemplate("cold-elegant");
    expect(cold).toBeTruthy();
    const p = applyFaceTemplate(cold!);
    expect(p.browStyle).toBe("thin");
    expect(p.eyeStyle).toBe("cat");
    expect(p.hairAccessory).toBe("glasses");
    // 模板没覆盖的字段必须保持默认（而不是继承用户上一次的选择）
    expect(p.headHeight).toBe(DEFAULT_FACE_PARAMS.headHeight);
    expect(p.eyeColorRight).toBe(DEFAULT_FACE_PARAMS.eyeColorRight);
  });

  it("应用结果是 normalize 后的稳定值（幂等、可序列化）", () => {
    for (const t of OFFICIAL_FACE_TEMPLATES) {
      const once = applyFaceTemplate(t);
      const twice = normalizeFaceParams(once);
      expect(serializeFaceParams(once)).toBe(serializeFaceParams(twice));
      expect(applyFaceTemplate(t)).toEqual(once);
    }
  });

  it("描述摘要覆盖眉/眼/唇/发饰/肤色五项且都有中文", () => {
    for (const t of OFFICIAL_FACE_TEMPLATES) {
      const traits = describeFace(applyFaceTemplate(t));
      expect(traits.map((x) => x.key)).toEqual(["brow", "eye", "lip", "accessory", "skin"]);
      for (const trait of traits) {
        expect(trait.label.length).toBeGreaterThan(0);
        expect(trait.label).not.toBe(undefined);
      }
    }
    // 未登记肤色回落「自定义肤色」，不抛错
    const custom = describeFace({ ...DEFAULT_FACE_PARAMS, skinTone: "#123456" });
    expect(custom.find((x) => x.key === "skin")!.label).toBe("自定义肤色");
  });

  it("findFaceTemplate 对空/未知 id 返回 undefined（诚实不猜）", () => {
    expect(findFaceTemplate(null)).toBeUndefined();
    expect(findFaceTemplate(undefined)).toBeUndefined();
    expect(findFaceTemplate("")).toBeUndefined();
    expect(findFaceTemplate("no-such-template")).toBeUndefined();
    expect(findFaceTemplate("fox-spirit")?.name).toBe("神秘狐仙");
  });
});
