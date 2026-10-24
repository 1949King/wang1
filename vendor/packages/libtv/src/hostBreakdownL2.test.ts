/**
 * hostBreakdownL2 纯函数回归锁（Wave 0 #13 第 4 条，2026-10-15）
 *
 * 本文件的核心是**诚实边界**的回归锁：
 * 后端 reference_breakdown.py:14 明写「宁可空着，不编」，
 * 前端若把空串填成「中景」「固定」就是把「没测出来」说成「测出来了」。
 * 所以这批用例大量是「空必须是空」的反例锁。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  judgeL2Shot,
  mapL2ShotsToRows,
  pullDepthBreakdown,
  summarizeL2Pull,
  type L2PullSummary,
} from "./hostBreakdownL2";
import type { ReferenceBreakdownL2Shot } from "./bridgeStoryboard";

vi.mock("./bridgeStoryboard", () => ({
  referenceBreakdownL2: vi.fn(),
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
import { referenceBreakdownL2 } from "./bridgeStoryboard";
const mockL2 = vi.mocked(referenceBreakdownL2);

/** 后端真实形状的一行（字段名是中文键，见 reference_breakdown.py:702） */
function makeShot(over: Partial<ReferenceBreakdownL2Shot> = {}): ReferenceBreakdownL2Shot {
  return {
    index: 1,
    start: 0,
    end: 3,
    duration: 3,
    景别: "",
    运镜: "",
    keyframe: ".workbuddy/tmp/breakdown_l2/shot_001.jpg",
    motion: 0.12,
    brightness: 0.5,
    contrast: 0.42,
    camera_move: { move: "unknown", reason: "深度模块不可用" },
    camera_move_trusted: false,
    ...over,
  };
}

describe("hostBreakdownL2 · 诚实判读（没测出来就是没测出来）", () => {
  it("空串一律算「没测出来」—— 绝不把空当固定/中景", () => {
    const v = judgeL2Shot(makeShot({ 景别: "", 运镜: "" }));
    expect(v.hasShotSize).toBe(false);
    expect(v.hasCamera).toBe(false);
  });

  it("纯空白串与 undefined 同样算没测出来", () => {
    const v = judgeL2Shot(makeShot({ 景别: "   ", 运镜: undefined }));
    expect(v.hasShotSize).toBe(false);
    expect(v.hasCamera).toBe(false);
  });

  it("后端 move=unknown 表示深度不可用，不是「固定机位」结论", () => {
    const v = judgeL2Shot(makeShot({ camera_move: { move: "unknown", reason: "深度模块不可用" } }));
    expect(v.depthAvailable).toBe(false);
    // 关键：hasCamera 必须 false —— 空运镜 ≠ 推断出「固定」
    expect(v.hasCamera).toBe(false);
  });

  it("置信度不足时后端不写「运镜」⇒ 前端也认hasCamera=false，但记下置信度", () => {
    const v = judgeL2Shot(
      makeShot({ 运镜: "", camera_move: { move: "push_in", confidence: 0.31 }, camera_move_trusted: false }),
    );
    expect(v.hasCamera).toBe(false);
    expect(v.depthAvailable).toBe(true);
    expect(v.confidence).toBeCloseTo(0.31);
  });

  it("过了门槛：景别/运镜都有值 ⇒ 两个 has 都 true", () => {
    const v = judgeL2Shot(
      makeShot({ 景别: "中景", 运镜: "推", camera_move: { move: "push_in", confidence: 0.88 } }),
    );
    expect(v.hasShotSize).toBe(true);
    expect(v.hasCamera).toBe(true);
    expect(v.confidence).toBeCloseTo(0.88);
  });

  it("index 缺失时按位置序号兜底（后端一定有 index，这是防御）", () => {
    expect(judgeL2Shot({} as ReferenceBreakdownL2Shot, 4).index).toBe(5);
    expect(judgeL2Shot({ index: 7 } as ReferenceBreakdownL2Shot, 4).index).toBe(7);
  });
});

describe("hostBreakdownL2 · 行映射", () => {
  it("实测值原样落进 ShotlistRow，空串保持空（不填默认审美）", () => {
    const rows = mapL2ShotsToRows([
      makeShot({ index: 1, duration: 3, 景别: "中景", 运镜: "推", 描述: "雨夜街口" }),
      makeShot({ index: 2, duration: 2.5, 景别: "", 运镜: "" }),
    ]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      shotNo: "01",
      shotSize: "中景",
      camera: "推",
      content: "雨夜街口",
      duration: 3,
    });
    // 第 2 镜：三个字段必须都是空串 —— 这是本文件最重要的一条
    expect(rows[1].shotSize).toBe("");
    expect(rows[1].camera).toBe("");
    expect(rows[1].content).toBe("");
  });

  it("id 用 index 派生而非随机（本项目禁随机效果，且 L2 有稳定 index）", () => {
    const rows = mapL2ShotsToRows([makeShot({ index: 3 }), makeShot({ index: 4 })]);
    expect(rows.map((r) => r.id)).toEqual(["l2_3", "l2_4"]);
    // 两次映射必须产出同一批 id（可重现）
    const again = mapL2ShotsToRows([makeShot({ index: 3 }), makeShot({ index: 4 })]);
    expect(again.map((r) => r.id)).toEqual(rows.map((r) => r.id));
  });

  it("note 如实带出实测指标 + 深度不可用原因（不编解读）", () => {
    const row = mapL2ShotsToRows([
      makeShot({ motion: 0.1234, brightness: 0.5, contrast: 0.42, camera_move: { move: "unknown", reason: "深度模块不可用" } }),
    ])[0];
    expect(row.note).toContain("运动量0.12");
    expect(row.note).toContain("亮度50%");
    expect(row.note).toContain("对比42%");
    expect(row.note).toContain("深度模块不可用");
  });

  it("keyframe 是磁盘绝对路径 ⇒ **不塞进 frameUrl**（画布只认 /inbox_file/）", () => {
    const rows = mapL2ShotsToRows([makeShot({ keyframe: "D:/somewhere/shot_001.jpg" })]);
    // 这是最容易踩的坑：WebView 加载不了 D:\ 路径，塞进去就是坏图
    expect(rows[0].frameUrl).toBeUndefined();
    expect(rows[0].frameNodeId).toBeUndefined();
  });

  it("duration 非法（0/负/NaN）⇒ 落 0，不猜 3 秒", () => {
    const rows = mapL2ShotsToRows([
      makeShot({ index: 1, duration: 0 }),
      makeShot({ index: 2, duration: -5 }),
      makeShot({ index: 3, duration: Number.NaN }),
    ]);
    expect(rows.map((r) => r.duration)).toEqual([0, 0, 0]);
  });

  it("空/未定义输入返回空数组，不抛", () => {
    expect(mapL2ShotsToRows(undefined)).toEqual([]);
    expect(mapL2ShotsToRows([])).toEqual([]);
  });
});

describe("hostBreakdownL2 · 一行结论（逐字透传后端 note）", () => {
  it("全部测出 ⇒ 不加补充说明（note 逐字带出）", () => {
    const s = summarizeL2Pull({
      ok: true,
      count: 2,
      duration: 8,
      shots: [
        makeShot({ index: 1, 景别: "中景", 运镜: "推" }),
        makeShot({ index: 2, 景别: "近景", 运镜: "拉" }),
      ],
      note: "L2 运动级已启用",
    });
    expect(s.ok).toBe(true);
    expect(s.count).toBe(2);
    expect(s.duration).toBe(8);
    expect(s.note).toBe("L2 运动级已启用");
    expect(s.message).toBeUndefined();
  });

  it("有留空 ⇒ **必须明说哪几项没测出**（不许含糊成「拉片完成」）", () => {
    const s = summarizeL2Pull({
      ok: true,
      count: 3,
      shots: [
        makeShot({ index: 1, 景别: "中景", 运镜: "" }), // 运镜没测出
        makeShot({ index: 2, 景别: "", 运镜: "" }),   // 两个都没测出
        makeShot({ index: 3, 景别: "", 运镜: "" }),
      ],
    });
    expect(s.shotSizeCount).toBe(1);
    expect(s.cameraCount).toBe(0);
    expect(s.message).toContain("景别 1/3");
    expect(s.message).toContain("运镜 0/3");
    expect(s.message).toContain("留空未猜");
  });

  it("失败：回传后端 message，不吞", () => {
    const s = summarizeL2Pull({ ok: false, message: "读不到视频" });
    expect(s.ok).toBe(false);
    expect(s.message).toBe("读不到视频");
    expect(s.count).toBe(0);
  });

  it("失败且无 message ⇒ 给兜底文案而非空串", () => {
    expect(summarizeL2Pull({ ok: false }).message).toBeTruthy();
  });

  it("视觉是否出域如实透传（用户关心素材有没有出机）", () => {
    const s = summarizeL2Pull({
      ok: true,
      count: 1,
      shots: [makeShot()],
      vision_used: true,
      vision_message: "云端视觉模型 XXX",
    });
    expect(s.visionUsed).toBe(true);
    expect(s.visionMessage).toBe("云端视觉模型 XXX");
  });
});

describe("hostBreakdownL2 · 端点调用", () => {
  beforeEach(() => {
    mockL2.mockReset();
    vi.stubGlobal("window", { __SHIGUANG_BRIDGE_TOKEN: "test-token" });
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("use_vision 默认 false —— 素材出域必须用户显式开启", async () => {
    mockL2.mockResolvedValue({ ok: true, count: 1, shots: [makeShot()] });
    await pullDepthBreakdown({ videoPath: "inbox_file/a.mp4" });
    const arg = mockL2.mock.calls[0][0];
    expect(arg.use_vision).toBe(false);
    expect(arg.video_path).toBe("inbox_file/a.mp4");
    expect(arg.threshold).toBeCloseTo(0.3);
  });

  it("显式 use_vision=true 才带 vision_model", async () => {
    mockL2.mockResolvedValue({ ok: true, count: 1, shots: [makeShot()] });
    await pullDepthBreakdown({ videoPath: "a.mp4", useVision: true, visionModel: "qwen2-vl" });
    expect(mockL2.mock.calls[0][0].use_vision).toBe(true);
    expect(mockL2.mock.calls[0][0].vision_model).toBe("qwen2-vl");
  });

  it("无路径：不打网络，直接失败", async () => {
    const r: L2PullSummary & { rows: unknown[] } = await pullDepthBreakdown({ videoPath: "" });
    expect(r.ok).toBe(false);
    expect(r.message).toBe("需要参考视频路径");
    expect(mockL2).not.toHaveBeenCalled();
  });

  it("端点抛异常：不外抛，返回可展示的 message", async () => {
    mockL2.mockRejectedValue(new Error("ECONNRESET"));
    const r = await pullDepthBreakdown({ videoPath: "a.mp4" });
    expect(r.ok).toBe(false);
    expect(r.message).toContain("深度拉片异常");
    expect(r.rows).toEqual([]);
  });

  it("端点 ok=false ⇒ rows 空（不给半截数据）", async () => {
    mockL2.mockResolvedValue({ ok: false, message: "视频读不到", shots: [makeShot()] });
    const r = await pullDepthBreakdown({ videoPath: "a.mp4" });
    expect(r.ok).toBe(false);
    expect(r.rows).toEqual([]);
  });
});