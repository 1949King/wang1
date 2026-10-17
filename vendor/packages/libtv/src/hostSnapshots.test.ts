/**
 * hostSnapshots 纯函数回归锁（Wave 0 #13 第 5 条，2026-10-15）
 *
 * 重点锁三条诚实边界：
 *  ① 空栈是真实状态（后端只有 import 会长栈），不是 bug ⇒ UI 必须如实说。
 *  ② 无效日期回落到原串，**绝不显示 Invalid Date**（也不编造时间）。
 *  ③ 0 片段的回滚点会**清空整条时间线** ⇒ 必须拦下并二次确认。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  listSnapshots,
  restoreSnapshot,
  snapshotRestoreBlocker,
  snapshotRestoreHeadline,
  snapshotRestoreNeedsConfirm,
  snapshotRowLabel,
  type SnapshotRow,
} from "./hostSnapshots";

const ROWS: SnapshotRow[] = [
  { id: "snap_a", label: "导入前自动快照", taken_at: "2026-10-15T10:00:00Z", clip_count: 12 },
  { id: "snap_b", label: "", taken_at: "不是时间戳", clip_count: 0 },
  { id: "snap_c", label: "只有标签" },
];

describe("hostSnapshots · 行文案（不编造）", () => {
  it("标签 + 片段数 + 本地化时间", () => {
    const s = snapshotRowLabel(ROWS[0]);
    expect(s).toContain("导入前自动快照");
    expect(s).toContain("12 片段");
    expect(s).not.toContain("Invalid Date");
  });

  it("空标签回落「未命名快照」（不显示空白行）", () => {
    expect(snapshotRowLabel(ROWS[1])).toContain("未命名快照");
  });

  it("🔴 无效日期回落到原串，绝不显示 Invalid Date", () => {
    const s = snapshotRowLabel(ROWS[1]);
    expect(s).toContain("不是时间戳");
    expect(s).not.toContain("Invalid Date");
    expect(s).not.toContain("NaN");
  });

  it("字段缺失只拼已有的部分，不补 0/空串占位", () => {
    expect(snapshotRowLabel(ROWS[2])).toBe("只有标签");
    expect(snapshotRowLabel({ id: "x", label: "" })).toBe("未命名快照");
  });
});

describe("hostSnapshots · 回滚红线自检", () => {
  it("空栈 ⇒ 拦下，并说明怎么产生回滚点", () => {
    const b = snapshotRestoreBlocker([], "snap_a");
    expect(b).toBeTruthy();
    expect(b).toContain("暂无回滚点");
    expect(b).toContain("导入");
  });

  it("未选回滚点 ⇒ 拦下", () => {
    expect(snapshotRestoreBlocker(ROWS, "")).toContain("未选择");
    expect(snapshotRestoreBlocker(ROWS, "   ")).toContain("未选择");
  });

  it("id 不在栈里 ⇒ 拦下并说明可能被栈上限裁掉", () => {
    const b = snapshotRestoreBlocker(ROWS, "snap_zzz");
    expect(b).toContain("已不在栈中");
    expect(b).toContain("裁");
  });

  it("🔴 0 片段的回滚点 ⇒ 拦下并警告会清空时间线", () => {
    const b = snapshotRestoreBlocker(ROWS, "snap_b");
    expect(b).toBeTruthy();
    expect(b).toContain("0 片段");
    expect(b).toContain("清空");
    expect(b).toContain("⚠️"); // UI 据此加重提示
  });

  it("正常回滚点 ⇒ 不拦（null）且需确认", () => {
    expect(snapshotRestoreBlocker(ROWS, "snap_a")).toBeNull();
    expect(snapshotRestoreNeedsConfirm(ROWS, "snap_a")).toBe(true);
  });

  it("有 blocker ⇒ 不进确认流程（先拦下，别让人白确认）", () => {
    expect(snapshotRestoreNeedsConfirm([], "snap_a")).toBe(false);
    expect(snapshotRestoreNeedsConfirm(ROWS, "snap_b")).toBe(false);
    expect(snapshotRestoreNeedsConfirm(ROWS, "")).toBe(false);
  });

  it("clip_count 缺失（undefined）不当作 0", () => {
    // snap_c 没有 clip_count ⇒ 不能判定为「清空时间线」
    expect(snapshotRestoreBlocker(ROWS, "snap_c")).toBeNull();
  });
});

describe("hostSnapshots · 回滚结果文案", () => {
  it("成功逐字用后端 message", () => {
    const s = snapshotRestoreHeadline({
      ok: true,
      message: '已回滚到快照「导入前自动快照」（12 片段）',
      restored: 12,
    });
    expect(s).toBe('已回滚到快照「导入前自动快照」（12 片段）');
  });

  it("失败回传 message，不吞", () => {
    expect(snapshotRestoreHeadline({ ok: false, message: "快照不存在" })).toBe("快照不存在");
  });

  it("message 缺失 ⇒ 兜底文案而非空串", () => {
    expect(snapshotRestoreHeadline({ ok: true, restored: 5 })).toContain("5 片段");
    expect(snapshotRestoreHeadline({ ok: true })).toBe("已回滚");
    expect(snapshotRestoreHeadline({ ok: false })).toBe("回滚失败");
    expect(snapshotRestoreHeadline(null)).toBe("");
  });
});

describe("hostSnapshots · HTTP 封装", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("window", { __SHIGUANG_BRIDGE_TOKEN: "test-token" });
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {}, removeItem: () => {} });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("GET history 且带 token", async () => {
    fetchMock.mockResolvedValue({ json: async () => ({ ok: true, snapshots: ROWS }) });
    const r = await listSnapshots();
    expect(r.ok).toBe(true);
    expect(r.snapshots).toHaveLength(3);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/host/project-snapshot/history");
    expect(String(url)).toContain("token=");
    expect(init.method).toBeUndefined();
  });

  it("后端改成直接返回数组也能吃（形态兼容）", async () => {
    fetchMock.mockResolvedValue({ json: async () => ROWS });
    const r = await listSnapshots();
    expect(r.snapshots).toHaveLength(3);
  });

  it("畸形数据被过滤掉（无 id 的行不进栈）", async () => {
    fetchMock.mockResolvedValue({
      json: async () => ({ ok: true, snapshots: [{ label: "没有 id" }, null, ROWS[0]] }),
    });
    const r = await listSnapshots();
    expect(r.snapshots).toHaveLength(1);
    expect(r.snapshots[0].id).toBe("snap_a");
  });

  it("网络异常不抛：返回空栈 + message（UI 回落到「暂无回滚点」）", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));
    const r = await listSnapshots();
    expect(r.ok).toBe(false);
    expect(r.snapshots).toEqual([]);
    expect(r.message).toContain("回滚栈拉取失败");
  });

  it("POST restore 带 snapshot_id", async () => {
    fetchMock.mockResolvedValue({
      json: async () => ({ ok: true, message: "已回滚", restored: 12 }),
    });
    const r = await restoreSnapshot("snap_a");
    expect(r.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/host/project-snapshot/restore");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ snapshot_id: "snap_a" });
  });

  it("空 id ⇒ 不打网络直接失败", async () => {
    const r = await restoreSnapshot("");
    expect(r.ok).toBe(false);
    expect(r.message).toContain("snapshot_id");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("网络异常不抛：回传可展示 message", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNRESET"));
    const r = await restoreSnapshot("snap_a");
    expect(r.ok).toBe(false);
    expect(r.message).toContain("回滚失败");
  });
});