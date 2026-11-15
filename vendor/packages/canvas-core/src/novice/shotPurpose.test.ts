/**
 * 镜头卡的叙事层 / 序列层字段（2026-11-15 加）
 *
 * 这两件事很容易在后续重构中悄悄坏掉，所以锁死：
 * 1. `shotPurpose` 默认必须是「推进」—— 短剧里最常见的功能；缺省值一改，
 *    所有老画布的镜头都会变成"无作用"，卡片上的标签会集体消失。
 * 2. `addNode("shot")` 必须自动递增镜号 —— 这是「序列存在数据里、不在画布位置上」
 *    的唯一实现；一旦失效，用户摆十张卡就全是没有编号的散卡。
 * 3. 非镜头卡**不得**带 shotNumber —— 否则「共 N 镜」的统计会把别的卡算进来。
 */
import { beforeEach, describe, expect, it } from "vitest";

import { useCanvasStore } from "../store";
import {
  SHOT_PURPOSE_META,
  SHOT_PURPOSE_ORDER,
  makeNode,
  normalizeShotPurpose,
} from "../stores/node-factory";

const resetGraph = () =>
  (useCanvasStore.setState as unknown as (p: Record<string, unknown>) => void)({
    nodes: [],
    edges: [],
    selectedId: null,
  });

const readShotNo = (id: string): number | undefined => {
  const n = useCanvasStore.getState().nodes.find((x) => x.id === id);
  return (n?.data as { shotNumber?: number } | undefined)?.shotNumber;
};

beforeEach(resetGraph);

describe("镜头作用（叙事层）", () => {
  it("makeNode 默认给「推进」", () => {
    const n = makeNode("shot", { x: 0, y: 0 });
    expect((n.data as { shotPurpose?: string }).shotPurpose).toBe("advance");
  });

  it("四档作用齐全，且标签是中文（不用工程枚举名给用户看）", () => {
    expect(SHOT_PURPOSE_ORDER).toHaveLength(4);
    for (const p of SHOT_PURPOSE_ORDER) {
      expect(SHOT_PURPOSE_META[p].label).toMatch(/[\u4e00-\u9fa5]/);
      expect(SHOT_PURPOSE_META[p].hint).toMatch(/[\u4e00-\u9fa5]/);
    }
  });

  it("调用方可以覆盖默认作用", () => {
    const n = makeNode("shot", { x: 0, y: 0 }, { shotPurpose: "turn" } as never);
    expect((n.data as { shotPurpose?: string }).shotPurpose).toBe("turn");
  });
});

describe("镜号（序列层）", () => {
  it("新建镜头自动编号 1、2", () => {
    const a = useCanvasStore.getState().addNode("shot");
    const b = useCanvasStore.getState().addNode("shot");
    expect(readShotNo(a)).toBe(1);
    expect(readShotNo(b)).toBe(2);
  });

  it("取的是「当前最大号 + 1」，不是「数量 + 1」（手改过号也不冲突）", () => {
    const a = useCanvasStore.getState().addNode("shot");
    // 用户把第 1 镜改成 7（插镜/调序）
    useCanvasStore.getState().updateNodeData(a, { shotNumber: 7 });
    const b = useCanvasStore.getState().addNode("shot");
    expect(readShotNo(b)).toBe(8);
  });

  it("非镜头卡不带镜号", () => {
    const id = useCanvasStore.getState().addNode("note");
    const n = useCanvasStore.getState().nodes.find((x) => x.id === id);
    expect((n?.data as { shotNumber?: number } | undefined)?.shotNumber).toBeUndefined();
  });
});

describe("拆镜时自动标作用（2026-11-15 加）", () => {
  it("normalizeShotPurpose 认中文别名", () => {
    expect(normalizeShotPurpose("转折")).toBe("turn");
    expect(normalizeShotPurpose("收尾")).toBe("close");
    expect(normalizeShotPurpose("铺垫")).toBe("setup");
  });

  it("normalizeShotPurpose 认英文 key，未知值回落 advance（不留空）", () => {
    expect(normalizeShotPurpose("close")).toBe("close");
    expect(normalizeShotPurpose("乱写")).toBe("advance");
    expect(normalizeShotPurpose(undefined)).toBe("advance");
  });

  it("applyStoryboard 把镜号与作用一次落地（不是只写进 title）", () => {
    resetGraph();
    useCanvasStore.getState().applyStoryboard(
      [
        { id: 1, shot: "远景", description: "雨夜街景", duration: 3, purpose: "setup" },
        { id: 2, shot: "中景", description: "她推门", duration: 3, purpose: "转折" },
        { id: 3, shot: "特写", description: "黑场", duration: 2, purpose: "close" },
      ],
      "测试剧本",
    );
    const shots = useCanvasStore
      .getState()
      .nodes.filter((n) => (n.data as { kind?: string }).kind === "shot");
    expect(shots).toHaveLength(3);
    // 关键：字段有值，卡片才显示「镜 N」；只写 title 的话卡面是空的
    expect(shots.map((s) => (s.data as { shotNumber?: number }).shotNumber)).toEqual([1, 2, 3]);
    expect(shots.map((s) => (s.data as { shotPurpose?: string }).shotPurpose)).toEqual([
      "setup",
      "turn",
      "close",
    ]);
  });
});
