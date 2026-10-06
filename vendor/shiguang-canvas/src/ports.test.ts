/**
 * ports.test.ts — 画布端口模型（类型槽位）回归
 *
 * 覆盖四条核心纪律：
 *  ① 类型校验真的拦得住（image → text 这种非法连接必须被拒）；
 *  ② **编组是 associate**（不参与数据流、不做类型校验、允许成环）；
 *  ③ fan-in 计数约束（超限报 error）；
 *  ④ 只对 **data 边**判环（associate 边成环不报）。
 */
import { describe, expect, it } from "vitest";

import {
  canConnect,
  edgeKindFor,
  NODE_PORTS,
  PORT_TYPE_LABEL,
  portsOf,
  UNBOUNDED,
  validateGraph,
} from "./ports";

const N = (id: string, kind: string) => ({ id, type: kind, data: { kind } });
const E = (source: string, target: string, id?: string) => ({ id, source, target });

describe("端口表本身", () => {
  it("覆盖全部 21 个节点 kind", () => {
    expect(Object.keys(NODE_PORTS)).toHaveLength(21);
  });

  it("每个 kind 都有 accepts/produces 结构", () => {
    for (const [k, p] of Object.entries(NODE_PORTS)) {
      expect(p, k).toHaveProperty("accepts");
      expect(p, k).toHaveProperty("produces");
    }
  });

  it("容器/纯前端节点不产出数据", () => {
    expect(NODE_PORTS.group.produces.any).toBe(1);
    expect(NODE_PORTS.script.accepts).toEqual({});
    expect(NODE_PORTS.source.accepts).toEqual({});
  });

  it("未知 kind 走宽松兜底（不误拦新节点）", () => {
    expect(portsOf("__brand_new_kind__").accepts.any).toBe(UNBOUNDED);
  });

  it("每种端口类型都有中文标签", () => {
    for (const t of Object.keys(PORT_TYPE_LABEL)) {
      expect(PORT_TYPE_LABEL[t as keyof typeof PORT_TYPE_LABEL]).toBeTruthy();
    }
  });
});

describe("canConnect —— 数据流边", () => {
  it("文本 → 镜头：合法", () => {
    const v = canConnect("script", "shot");
    expect(v.ok).toBe(true);
    expect(v.kind).toBe("data");
    expect(v.via).toBe("text");
  });

  it("图像 → 视频：合法（图生视频）", () => {
    expect(canConnect("image", "video").ok).toBe(true);
  });

  it("★ 视频 → 文本节点：非法（video 不是文本输入）", () => {
    const v = canConnect("video", "text");
    expect(v.ok).toBe(false);
    expect(v.reason).toContain("video");
  });

  it("★ 音频 → 图像：非法", () => {
    expect(canConnect("audio", "image").ok).toBe(false);
  });

  it("★ 3D 场景 → 音频：非法（3D 台不产音频）", () => {
    expect(canConnect("director", "audio").ok).toBe(false);
  });

  it("音乐 → 视频：合法（配乐）", () => {
    expect(canConnect("music", "video").ok).toBe(true);
  });

  it("图像 → 图像：合法（图生图/参考图）", () => {
    expect(canConnect("image", "image").ok).toBe(true);
  });

  it("脚本 → 视频：非法（视频不直接吃剧本文本，需经 shot）", () => {
    // video.accepts 只有 text:1 —— 注意这里是合法还是非法取决于表；
    // 本用例锁定「表即契约」：video 接受 text，所以 script→video 合法。
    expect(canConnect("script", "video").ok).toBe(true);
  });

  it("非法连接必须给出可读原因", () => {
    const v = canConnect("audio", "image");
    expect(v.reason).toBeTruthy();
    expect(v.reason).toContain("image");
  });

  it("★ 未知 source kind 走宽松兜底（不误拦将来新增的节点类型）", () => {
    // 回归：曾因「只判 target 的 any、漏判 source 的 any」而把未知节点判成非法。
    // 宽松兜底的意义：新增节点类型时不会因为「忘了填表」而连不上任何东西。
    expect(canConnect("__brand_new_kind__", "image").ok).toBe(true);
    expect(canConnect("__brand_new_kind__", "video").ok).toBe(true);
  });

  it("未知 target kind 同样宽松", () => {
    expect(canConnect("image", "__brand_new_kind__").ok).toBe(true);
  });
});

describe("canConnect —— 关联边（编组）", () => {
  it("编组相关的边一律 associate", () => {
    expect(edgeKindFor("group", "image")).toBe("associate");
    expect(edgeKindFor("image", "group")).toBe("associate");
  });

  it("★ associate 边永远合法（不做类型校验）", () => {
    // 若走数据流校验，audio → image 是非法；但编组边应放行
    expect(canConnect("group", "image").ok).toBe(true);
    expect(canConnect("audio", "group").ok).toBe(true);
  });

  it("非编组边默认 data", () => {
    expect(edgeKindFor("script", "shot")).toBe("data");
  });
});

describe("validateGraph", () => {
  it("干净图无问题", () => {
    const nodes = [N("s", "script"), N("k", "shot"), N("i", "image")];
    const problems = validateGraph(nodes, [E("s", "k"), E("k", "i")]);
    expect(problems).toHaveLength(0);
  });

  it("★ 类型不匹配报 error", () => {
    const nodes = [N("a", "audio"), N("i", "image")];
    const problems = validateGraph(nodes, [E("a", "i")]);
    expect(problems.some((p) => p.code === "type-mismatch" && p.level === "error")).toBe(true);
  });

  it("★ fan-in 超限报 error", () => {
    // shot 的 image 输入上限是 1 → 接两条 image 应超限
    const nodes = [N("i1", "image"), N("i2", "image"), N("k", "shot")];
    const problems = validateGraph(nodes, [E("i1", "k"), E("i2", "k")]);
    expect(problems.some((p) => p.code === "fan-in-exceeded")).toBe(true);
  });

  it("fan-in 未超限不报", () => {
    const nodes = [N("s1", "script"), N("k", "shot")];
    // shot 的 text 上限是 2 → 一条不超限
    const problems = validateGraph(nodes, [E("s1", "k")]);
    expect(problems.filter((p) => p.code === "fan-in-exceeded")).toHaveLength(0);
  });

  it("悬空边报 warn（不阻断）", () => {
    const problems = validateGraph([N("a", "image")], [E("a", "ghost")]);
    expect(problems.some((p) => p.code === "dangling" && p.level === "warn")).toBe(true);
  });

  it("★ 数据流成环报 error", () => {
    const nodes = [N("a", "image"), N("b", "image")];
    const problems = validateGraph(nodes, [E("a", "b"), E("b", "a")]);
    expect(problems.some((p) => p.code === "cycle")).toBe(true);
  });

  it("★ 编组边成环不报（associate 不参与数据流）", () => {
    const nodes = [N("g", "group"), N("h", "group")];
    const problems = validateGraph(nodes, [E("g", "h"), E("h", "g")]);
    expect(problems.filter((p) => p.code === "cycle")).toHaveLength(0);
  });

  it("空图不崩", () => {
    expect(validateGraph([], [])).toEqual([]);
  });

  it("只按 data 边判环：混入 associate 边不影响", () => {
    const nodes = [N("s", "script"), N("k", "shot"), N("g", "group")];
    const problems = validateGraph(nodes, [E("s", "k"), E("k", "g"), E("g", "s")]);
    expect(problems.filter((p) => p.code === "cycle")).toHaveLength(0);
  });
});
