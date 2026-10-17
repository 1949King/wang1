/**
 * hostEnhanceIntents 纯函数 + 端点回归锁（Wave 0 #13，2026-10-15）
 *
 * 重点锁两件事：
 *  ① 语义红线 —— 本端点的 quality_tiers 绝不与前端 QUALITY_TIERS 混用（见源文件头注）。
 *  ② 诚实纪律 —— heal / style 不得被渲染成「点了必然失败」或「静默套默认审美」的死按钮。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  DIRECT_INTENTS,
  excludedIntents,
  fetchEnhanceIntents,
  intentButtonLabel,
  selectDirectIntents,
  type EnhanceIntentCatalog,
} from "./hostEnhanceIntents";

/** 与后端 app/core/canvas_enhance.py:54 ENHANCE_INTENTS 同形的目录 */
const BACKEND_CATALOG: EnhanceIntentCatalog = {
  ok: true,
  intents: [
    { id: "face", label: "修复人脸", hint: "让面部更清晰自然" },
    { id: "cutout", label: "抠像换背景", hint: "把主体从背景里分离出来" },
    { id: "sharpen", label: "超分放大", hint: "放大画面并补细节" },
    { id: "style", label: "风格迁移", hint: "按指定的画风重绘" },
    { id: "heal", label: "局部修图", hint: "只重绘你框选的区域" },
  ],
};

describe("hostEnhanceIntents · 意图筛选（诚实纪律）", () => {
  it("只收face/cutout/sharpen —— heal 缺遮罩、style 无风格选择器，一律不渲染死按钮", () => {
    const got = selectDirectIntents(BACKEND_CATALOG);
    expect(got.map((i) => i.id)).toEqual(["face", "cutout", "sharpen"]);
  });

  it("保持后端目录顺序，前端不重排（后端声明顺序即推荐序）", () => {
    const shuffled: EnhanceIntentCatalog = {
      ok: true,
      intents: [
        { id: "sharpen", label: "超分放大", hint: "" },
        { id: "face", label: "修复人脸", hint: "" },
        { id: "cutout", label: "抠像换背景", hint: "" },
      ],
    };
    expect(selectDirectIntents(shuffled).map((i) => i.id)).toEqual([
      "sharpen",
      "face",
      "cutout",
    ]);
  });

  it("未知 id（后端新增了前端没适配的）被排除，不硬渲染", () => {
    const cat: EnhanceIntentCatalog = {
      ok: true,
      intents: [
        { id: "sharpen", label: "超分放大", hint: "" },
        { id: "upscale_x4", label: "4 倍放大", hint: "未来意图" },
      ],
    };
    expect(selectDirectIntents(cat).map((i) => i.id)).toEqual(["sharpen"]);
  });

  it("后端删了某意图 → 前端不自己补齐（不假装还支持）", () => {
    const cat: EnhanceIntentCatalog = {
      ok: true,
      intents: [{ id: "cutout", label: "抠像换背景", hint: "" }],
    };
    expect(selectDirectIntents(cat).map((i) => i.id)).toEqual(["cutout"]);
  });

  it("目录拿不到（空/缺字段/失败）→ 返回空数组，调用方回落硬编码 UI，不白屏", () => {
    expect(selectDirectIntents({ ok: false, message: "boom" })).toEqual([]);
    expect(selectDirectIntents({ ok: true, intents: [] })).toEqual([]);
    expect(selectDirectIntents({ ok: true })).toEqual([]);
    expect(selectDirectIntents(null)).toEqual([]);
    expect(selectDirectIntents(undefined)).toEqual([]);
  });

  it("excludedIntents 如实列出被排除项（UI 要能解释为什么没这个按钮）", () => {
    expect(excludedIntents(BACKEND_CATALOG).map((i) => i.id)).toEqual(["style", "heal"]);
    expect(excludedIntents({ ok: true, intents: [] })).toEqual([]);
  });

  it("DIRECT_INTENTS 就是三项 —— 改这个白名单必须同步改源文件的判据注释", () => {
    expect([...DIRECT_INTENTS]).toEqual(["face", "cutout", "sharpen"]);
  });

  it("按钮文案优先后端 label（单一真源），缺失才回落 id", () => {
    expect(intentButtonLabel({ id: "sharpen", label: "超分放大", hint: "" })).toBe("超分放大");
    expect(intentButtonLabel({ id: "sharpen", label: "", hint: "" })).toBe("sharpen");
    expect(intentButtonLabel({ id: "sharpen", label: "  ", hint: "" })).toBe("sharpen");
  });
});

describe("hostEnhanceIntents · 语义红线（quality_tiers 不许混用）", () => {
  it("本模块不导出任何 quality_tiers 相关符号（防止后来者误接）", async () => {
    const mod = await import("./hostEnhanceIntents");
    const keys = Object.keys(mod);
    expect(keys.some((k) => /quality|tier/i.test(k))).toBe(false);
  });

  it("返回的 catalog 只承诺 intents —— 故意不声明 quality_tiers 字段类型", () => {
    // 后端确实也返回 quality_tiers（fast/standard/high），但它与前端
    // novice/types.ts:80 的 QUALITY_TIERS（draft/standard/fine/cinema）是两套语义，
    // 本模块刻意不暴露该字段，防止误传。类型层面即无此键。
    const cat: EnhanceIntentCatalog = { ok: true, intents: [] };
    expect("quality_tiers" in cat).toBe(false);
  });
});

describe("hostEnhanceIntents · HTTP 封装", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    // node 环境无 jsdom：bridgeToken() 摸window/localStorage，补最小桩（样板 bridge.test.ts:74）
    vi.stubGlobal("window", { __SHIGUANG_BRIDGE_TOKEN: "test-token" });
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GET enhance-intents且带 token", async () => {
    fetchMock.mockResolvedValue({ json: async () => BACKEND_CATALOG });
    const res = await fetchEnhanceIntents();
    expect(res.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/host/enhance-intents");
    expect(String(url)).toContain("token=");
    expect(init.method).toBeUndefined(); // GET
  });

  it("网络异常不抛：返回 ok=false +空目录（UI 回落，不白屏）", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await fetchEnhanceIntents();
    expect(res.ok).toBe(false);
    expect(res.intents).toEqual([]);
    expect(res.message).toContain("意图目录拉取失败");
  });
});