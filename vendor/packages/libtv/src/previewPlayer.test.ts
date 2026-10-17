import { describe, expect, it } from "vitest";

import { previewOrder } from "./previewPlayer";

/** 位置辅助：排成一行（y 相同、x 递增）省得同层排序受 y 干扰。 */
const n = (id: string, x = 0, y = 0) => ({ id, x, y });
const e = (source: string, target: string) => ({ source, target });

describe("previewOrder 拓扑时序", () => {
  it("空画布返回空数组", () => {
    expect(previewOrder([], [])).toEqual([]);
  });

  it("无连线：按画布位置排序（y 主 x 辅）", () => {
    const nodes = [n("b", 100, 200), n("a", 0, 0), n("c", 0, 100)];
    expect(previewOrder(nodes, [])).toEqual(["a", "c", "b"]);
  });

  it("链式连线：上游在前下游在后", () => {
    const nodes = [n("c", 200, 0), n("a", 0, 0), n("b", 100, 0)];
    const edges = [e("a", "b"), e("b", "c")];
    expect(previewOrder(nodes, edges)).toEqual(["a", "b", "c"]);
  });

  it("分叉：共同上游只出现一次，下游按位置序", () => {
    const nodes = [n("root", 0, 0), n("right", 200, 100), n("left", 0, 100)];
    const edges = [e("root", "right"), e("root", "left")];
    expect(previewOrder(nodes, edges)).toEqual(["root", "left", "right"]);
  });

  it("菱形汇聚：汇聚点排在两条支路之后", () => {
    const nodes = [n("d", 300, 0), n("b", 100, 0), n("c", 200, 0), n("a", 0, 0)];
    const edges = [e("a", "b"), e("b", "c"), e("a", "d"), e("c", "d")];
    const order = previewOrder(nodes, edges);
    expect(order.indexOf("a")).toBeLessThan(order.indexOf("b"));
    expect(order.indexOf("b")).toBeLessThan(order.indexOf("c"));
    expect(order.indexOf("c")).toBeLessThan(order.indexOf("d"));
  });

  it("环：不丢弃，环上节点按位置序附在末尾", () => {
    const nodes = [n("head", 0, 0), n("x", 100, 0), n("y", 200, 0)];
    const edges = [e("head", "x"), e("x", "y"), e("y", "x")];
    const order = previewOrder(nodes, edges);
    expect(order[0]).toBe("head");
    expect(order.slice(1).sort()).toEqual(["x", "y"]);
    expect(order).toHaveLength(3);
  });

  it("坏边（自环 / 指向不存在节点）被忽略不炸", () => {
    const nodes = [n("a", 0, 0), n("b", 100, 0)];
    const edges = [e("a", "a"), e("a", "ghost"), e("a", "b")];
    expect(previewOrder(nodes, edges)).toEqual(["a", "b"]);
  });
});
