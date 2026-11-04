/**
 * 咬合侧隐形表回归 — bondedSidesMap 方向语义（2026-09-16）
 *
 * 核心约定：bond.side 描述「b 相对 a」；
 *   a 隐 side 边，b 隐反方向边。错一边 = 透明化出现在错误的一侧。
 */
import { describe, it, expect } from "vitest";
import type { Node } from "@xyflow/react";
import { bondedSidesMap } from "./bonds";

function node(id: string, x: number, y: number): Node {
  return { id, position: { x, y }, measured: { width: 240, height: 200 } } as Node;
}

describe("bonds.bondedSidesMap（咬合侧隐形表）", () => {
  it("B 贴在 A 右侧：A 隐右、B 隐左", () => {
    const map = bondedSidesMap([node("a", 0, 0), node("b", 240, 0)]);
    expect(map["a"]).toEqual(["right"]);
    expect(map["b"]).toEqual(["left"]);
  });

  it("B 贴在 A 下方：A 隐下、B 隐上", () => {
    const map = bondedSidesMap([node("a", 0, 0), node("b", 0, 200)]);
    expect(map["a"]).toEqual(["bottom"]);
    expect(map["b"]).toEqual(["top"]);
  });

  it("未咬合（投影重叠不足 40px）无隐形边", () => {
    const map = bondedSidesMap([node("a", 0, 0), node("b", 240, 170)]);
    expect(map["a"]).toBeUndefined();
    expect(map["b"]).toBeUndefined();
  });

  it("三卡横向连排：中间卡两侧都隐形", () => {
    const map = bondedSidesMap([
      node("a", 0, 0),
      node("b", 240, 0),
      node("c", 480, 0),
    ]);
    expect(map["a"]).toEqual(["right"]);
    expect(map["b"]).toEqual(["left", "right"]);
    expect(map["c"]).toEqual(["left"]);
  });

  it("上下左右混合：田字格四卡各自隐两边", () => {
    const map = bondedSidesMap([
      node("tl", 0, 0),
      node("tr", 240, 0),
      node("bl", 0, 200),
      node("br", 240, 200),
    ]);
    expect(map["tl"]?.sort()).toEqual(["bottom", "right"]);
    expect(map["tr"]?.sort()).toEqual(["bottom", "left"]);
    expect(map["bl"]?.sort()).toEqual(["right", "top"]);
    expect(map["br"]?.sort()).toEqual(["left", "top"]);
  });
});
