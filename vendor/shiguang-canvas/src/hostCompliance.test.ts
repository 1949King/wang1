/**
 * hostCompliance 纯函数回归锁（Wave 0 #13 孤儿端点接线第 2 条，2026-10-15）
 *
 * vitest 是 node 环境、无 jsdom ⇒ useEffect / 组件渲染零覆盖，
 * 所有判定逻辑必须抽成纯函数放这里（项目既有做法：见 storeIdempotent.test.ts）。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  bucketComplianceLevels,
  checkScriptCompliance,
  collectComplianceCharacters,
  collectComplianceShots,
  complianceHeadline,
  complianceSeverity,
  type ComplianceResult,
  type ComplianceSuggestion,
} from "./hostCompliance";

const SUG_OK: ComplianceSuggestion = {
  level: "ok",
  category: "AI 建议",
  message: "整体一致",
};

describe("hostCompliance · 分桶与严重度", () => {
  it("按 level 分桶且不重排（后端已按严重度排序，前端不得改序）", () => {
    const input: ComplianceSuggestion[] = [
      { level: "info", message: "i1" },
      { level: "warning", message: "w1" },
      { level: "ok", message: "o1" },
      { level: "warning", message: "w2" },
    ];
    const b = bucketComplianceLevels(input);
    expect(b.warning.map((s) => s.message)).toEqual(["w1", "w2"]);
    expect(b.info.map((s) => s.message)).toEqual(["i1"]);
    expect(b.other.map((s) => s.message)).toEqual(["o1"]);
  });

  it("level 大小写不敏感（后端是 'warning'，但 SSE 侧可能带空格/大写）", () => {
    const b = bucketComplianceLevels([{ level: "WARNING" }, { level: " Info " }]);
    expect(b.warning).toHaveLength(1);
    expect(b.info).toHaveLength(1);
  });

  it("undefined / null 输入不抛，返回三个空桶", () => {
    expect(bucketComplianceLevels(undefined)).toEqual({ warning: [], info: [], other: [] });
    expect(bucketComplianceLevels(null as unknown as ComplianceSuggestion[])).toEqual({
      warning: [],
      info: [],
      other: [],
    });
  });

  it("严重度：warning 优先于 info，0 条是 clean（不发徽章）", () => {
    const sug = [{ level: "info" }, { level: "warning" }];
    expect(complianceSeverity({ suggestions: sug, warningCount: 1 })).toBe("warning");
    expect(complianceSeverity({ suggestions: [{ level: "info" }], warningCount: 0 })).toBe("info");
    expect(complianceSeverity({ suggestions: [], warningCount: 0 })).toBe("clean");
    // suggestions 缺失但 warningCount>0 也要报 warning（保守侧：宁多报不漏报）
    expect(complianceSeverity({ suggestions: undefined, warningCount: 2 })).toBe("warning");
  });

  it("Headline 逐字用后端 summary，前端不自己编结论", () => {
    const res: ComplianceResult = {
      ok: true,
      suggestions: [{ level: "warning", message: "角色冲突" }],
      summary: "合规守护：共 3 条建议（AI 审查发现 2 条建议）",
    };
    expect(complianceHeadline(res)).toBe("合规守护：共 3 条建议（AI 审查发现 2 条建议）");
  });

  it("Headline：0 条建议走通过态并带分镜数（后端给了才带）", () => {
    expect(complianceHeadline({ ok: true, suggestions: [], total_shots: 12 })).toBe(
      "✅ 合规检查通过 · 12 分镜",
    );
    // total_shots 缺失时不编数字
    expect(complianceHeadline({ ok: true, suggestions: [] })).toBe("✅ 合规检查通过");
  });

  it("Headline：失败时如实回message，null 输入回空串", () => {
    expect(complianceHeadline({ ok: false, message: "剧本为空" })).toBe("剧本为空");
    expect(complianceHeadline({ ok: false })).toBe("合规检查失败");
    expect(complianceHeadline(null)).toBe("");
  });

  it("Headline：建议非空但 summary 缺失才兜底（不自造 AI 结论）", () => {
    const res: ComplianceResult = { ok: true, suggestions: [{ level: "info" }, { level: "info" }] };
    expect(complianceHeadline(res)).toBe("合规检查：2 条建议");
  });
});

describe("hostCompliance · 收集镜头/角色", () => {
  it("只收 shot 节点，且跳过空壳（有title 无 prompt 也算空壳要看判据）", () => {
    const nodes = [
      { data: { kind: "shot", title: "镜01", prompt: "雨夜街口", shotSize: "中景", duration: 3 } },
      { data: { kind: "shot", title: "", prompt: "" } }, // 空壳 → 跳过
      { data: { kind: "shot", title: "镜02", prompt: "" } }, // 有 title → 收
      { data: { kind: "script", title: "剧本", content: "…" } }, // 非 shot → 跳过
    ];
    const shots = collectComplianceShots(nodes);
    expect(shots).toHaveLength(2);
    expect(shots[0]).toEqual({ title: "镜01", prompt: "雨夜街口", shotSize: "中景", duration: 3 });
    expect(shots[1].title).toBe("镜02");
  });

  it("镜头：characterName/空字段处理 —— 空字符串不写进 payload", () => {
    const shots = collectComplianceShots([
      { data: { kind: "shot", title: "A", prompt: "p", characterName: "" } },
      { data: { kind: "shot", title: "B", prompt: "p", characterName: "林小满" } },
    ]);
    expect(shots[0].characterName).toBeUndefined();
    expect(shots[1].characterName).toBe("林小满");
  });

  it("角色：只认 characterName（对齐 CharacterData），空名必须跳过", () => {
    const chars = collectComplianceCharacters([
      { data: { kind: "character", characterName: "林小满" } },
      { data: { kind: "character", characterName: "" } }, // 空名 → 跳过（否则后端刷假警告）
      { data: { kind: "character", characterName: "   " } }, // 纯空白 → 跳过
      { data: { kind: "character", title: "有人物但没绑角色" } },
      { data: { kind: "shot", characterName: "不是角色节点" } },
    ]);
    expect(chars).toEqual([{ name: "林小满" }]);
  });

  it("收集函数对 undefined 节点数组不抛", () => {
    expect(collectComplianceShots(undefined as unknown as { data: unknown }[])).toEqual([]);
    expect(collectComplianceCharacters(undefined as unknown as { data: unknown }[])).toEqual([]);
    //节点 data 为 null 也要安全
    expect(collectComplianceShots([{ data: null }])).toEqual([]);
    expect(collectComplianceCharacters([{ data: null }])).toEqual([]);
  });
});

describe("hostCompliance · HTTP 封装", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    // node 环境无 jsdom：bridgeToken() 直接摸 window/localStorage，补最小桩
    // （样板见 bridge.test.ts:74-82，不自创写法）
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

  it("POST 到 compliance-check 且带 token + 三段payload", async () => {
    fetchMock.mockResolvedValue({ json: async () => ({ ok: true, suggestions: [] }) });
    const res = await checkScriptCompliance({
      script: "剧本正文",
      shots: [{ title: "镜01", prompt: "p" }],
      characters: [{ name: "林小满" }],
    });
    expect(res.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/host/compliance-check");
    expect(String(url)).toContain("token=");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body).toEqual({
      script: "剧本正文",
      shots: [{ title: "镜01", prompt: "p" }],
      characters: [{ name: "林小满" }],
    });
  });

  it("缺省 shots/characters 传空数组（不是 undefined）——后端要求 list", async () => {
    fetchMock.mockResolvedValue({ json: async () => ({ ok: true, suggestions: [] }) });
    await checkScriptCompliance({ script: "只有正文" });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.shots).toEqual([]);
    expect(body.characters).toEqual([]);
    expect(body.script).toBe("只有正文");
  });

  it("网络异常：返回 ok=false 而不是抛（UI 能直接展示 message）", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));
    const res = await checkScriptCompliance({ script: "x" });
    expect(res.ok).toBe(false);
    expect(res.suggestions).toEqual([]);
    expect(res.message).toContain("合规检查异常");
  });

  it("后端 500 也走json 分支如实带回 message", async () => {
    fetchMock.mockResolvedValue({ json: async () => ({ ok: false, message: "剧本为空" }) });
    const res = await checkScriptCompliance({ script: "" });
    expect(res.ok).toBe(false);
    expect(complianceHeadline(res)).toBe("剧本为空");
  });
});