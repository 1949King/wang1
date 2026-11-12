/**
 * 首屏「从一句话开始」预设（G5 · 2026-11-12）。
 *
 * 目标：陌生人打开软件 10 分钟内走完"选模板 → 写一句 → 出图/出片"，
 * 而不是面对一张空画布。三条预设对应三类最常用产出。
 *
 * 设计取舍：
 * - 只产出**骨架 DAG**（剧本/分镜/图/视频/成片），不预填生成结果 —— 生成仍由用户点；
 * - 预设里的 kind 必须是 ports.ts 登记过的类型，否则布局层会拒；
 * - 纯函数（不碰 store），便于单测。
 */
import type { BlueprintSpec } from "./blueprintLayout";

export type StarterPresetId = "drama" | "talk" | "product";

export interface StarterPreset {
  id: StarterPresetId;
  title: string;
  desc: string;
  build: (idea: string) => BlueprintSpec;
}

export const STARTER_PRESETS: StarterPreset[] = [
  {
    id: "drama",
    title: "竖屏短剧",
    desc: "一句梗概 → 剧本 → 分镜 → 关键画面 → 镜头视频",
    build: (idea) => ({
      goal: idea,
      nodes: [
        { key: "script", kind: "script", title: "剧本", prompt: idea },
        { key: "story", kind: "storyboard", title: "分镜表" },
        { key: "img", kind: "image", title: "关键画面", prompt: "" },
        { key: "vid", kind: "video", title: "镜头视频" },
        { key: "cut", kind: "finalcut", title: "成片" },
      ],
      edges: [
        { from: "script", to: "story" },
        { from: "story", to: "img" },
        { from: "img", to: "vid" },
        { from: "vid", to: "cut" },
      ],
    }),
  },
  {
    id: "talk",
    title: "口播视频",
    desc: "一句主题 → 文案 → 图片素材 → 配音 → 成片",
    build: (idea) => ({
      goal: idea,
      nodes: [
        { key: "text", kind: "text", title: "口播文案", prompt: idea },
        { key: "img", kind: "image", title: "配图" },
        { key: "vid", kind: "video", title: "口播画面" },
        { key: "cut", kind: "finalcut", title: "成片" },
      ],
      edges: [
        { from: "text", to: "img" },
        { from: "img", to: "vid" },
        { from: "vid", to: "cut" },
      ],
    }),
  },
  {
    id: "product",
    title: "产品/带货",
    desc: "一句卖点 → 文案 → 主图 → 展示视频 → 成片",
    build: (idea) => ({
      goal: idea,
      nodes: [
        { key: "text", kind: "text", title: "卖点文案", prompt: idea },
        { key: "img", kind: "image", title: "产品主图" },
        { key: "vid", kind: "video", title: "展示视频" },
        { key: "cut", kind: "finalcut", title: "成片" },
      ],
      edges: [
        { from: "text", to: "img" },
        { from: "img", to: "vid" },
        { from: "vid", to: "cut" },
      ],
    }),
  },
];

export function getPreset(id: string): StarterPreset {
  return STARTER_PRESETS.find((p) => p.id === id) || STARTER_PRESETS[0];
}

/** 预设骨架是否自洽（供单测与运行时兜底）：节点 key 唯一、边两端都存在。 */
export function validateSpec(spec: BlueprintSpec): string[] {
  const problems: string[] = [];
  const keys = new Set<string>();
  for (const n of spec.nodes || []) {
    if (!n.key) problems.push("节点缺少 key");
    if (keys.has(n.key)) problems.push("重复 key: " + n.key);
    keys.add(n.key);
    if (!n.kind) problems.push("节点缺少 kind: " + n.key);
  }
  for (const e of spec.edges || []) {
    if (!keys.has(e.from)) problems.push("边起点不存在: " + e.from);
    if (!keys.has(e.to)) problems.push("边终点不存在: " + e.to);
  }
  return problems;
}
