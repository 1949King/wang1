/**
 * 预装场景模板（BUILTIN_TEMPLATES）— 从 store.ts 拆分出的纯静态数据模块
 *
 * 只含类型 + 纯数据 + `_edge` 辅助函数，不依赖 zustand create() 闭包，
 * 因此抽离零运行时风险；store.ts 内部 import 后对外 re-export 保持兼容。
 */
import type { Edge, Node } from "@xyflow/react";

/** 内置模板类型：id 用 "builtin:xxx" 前缀区分，节点/边 id 固定供 edges 引用 */
export type BuiltinTemplate = {
  id: string;                     // "builtin:xxx" 前缀区分
  name: string;
  description: string;            // 一句话说明用途（降学习成本）
  nodes: Node[];
  edges: Edge[];
};

function _edge(src: string, tgt: string, type?: string): Edge {
  return {
    id: `e_${src}_${tgt}`,
    source: src,
    target: tgt,
    type: type || "default",
    animated: false,
    style: { stroke: "#64748b" },
  };
}

export const BUILTIN_TEMPLATES: BuiltinTemplate[] = [
  // ── 模板 1：竖屏短剧 3 场分镜 ──
  {
    id: "builtin:shorts-drama",
    name: "竖屏短剧 · 3 场分镜",
    description: "剧本 → 3 个镜头，一键填写 prompt 开始生图/生视频",
    nodes: [
      {
        id: "s1", type: "script", position: { x: 60, y: 160 },
        data: { kind: "script", title: "剧本 · 第一场", content: "主角推门进入空荡的房间……" } as any,
      },
      {
        id: "sh1", type: "shot", position: { x: 320, y: 60 },
        data: { kind: "shot", title: "镜 01 · 推门", shotSize: "中景", duration: 3, prompt: "竖屏 9:16，电影感推镜，冷色调" } as any,
      },
      {
        id: "sh2", type: "shot", position: { x: 320, y: 200 },
        data: { kind: "shot", title: "镜 02 · 环顾", shotSize: "全景", duration: 4, prompt: "竖屏 9:16，缓慢环视运镜" } as any,
      },
      {
        id: "sh3", type: "shot", position: { x: 320, y: 340 },
        data: { kind: "shot", title: "镜 03 · 特写", shotSize: "特写", duration: 2, prompt: "竖屏 9:16，人物面部特写，暖光" } as any,
      },
      {
        id: "cfg1", type: "config", position: { x: 620, y: 160 },
        data: { kind: "config", title: "生成配置", generationMode: "image", count: 4, prompt: "" } as any,
      },
    ],
    edges: [_edge("s1", "sh1"), _edge("s1", "sh2"), _edge("s1", "sh3"), _edge("sh1", "cfg1"), _edge("sh2", "cfg1"), _edge("sh3", "cfg1")],
  },

  // ── 模板 2：产品展示分镜 ──
  {
    id: "builtin:product-showcase",
    name: "产品展示 · 卖点 3 镜",
    description: "Prompt → 3 个产品角度镜头，突出卖点/质感/使用场景",
    nodes: [
      {
        id: "p1", type: "prompt", position: { x: 60, y: 180 },
        data: { kind: "prompt", title: "风格提示", text: "高端质感，浅景深，棚拍，4K" } as any,
      },
      {
        id: "ps1", type: "shot", position: { x: 320, y: 40 },
        data: { kind: "shot", title: "产品 · 正面特写", shotSize: "特写", duration: 3, prompt: "产品正面，微距，水滴细节" } as any,
      },
      {
        id: "ps2", type: "shot", position: { x: 320, y: 200 },
        data: { kind: "shot", title: "产品 · 侧面", shotSize: "中景", duration: 3, prompt: "产品 45° 侧面，阴影光" } as any,
      },
      {
        id: "ps3", type: "shot", position: { x: 320, y: 360 },
        data: { kind: "shot", title: "产品 · 使用场景", shotSize: "全景", duration: 5, prompt: "模特使用场景，生活化" } as any,
      },
      {
        id: "g1", type: "generator", position: { x: 620, y: 180 },
        data: { kind: "generator", title: "批量生成器", mode: "image", count: 6, prompt: "" } as any,
      },
    ],
    edges: [_edge("p1", "ps1"), _edge("p1", "ps2"), _edge("p1", "ps3"), _edge("ps1", "g1"), _edge("ps2", "g1"), _edge("ps3", "g1")],
  },

  // ── 模板 3：情绪板 / Moodboard ──
  {
    id: "builtin:moodboard",
    name: "情绪板 · 视觉预演",
    description: "4 张参考图 + 说明文字，快速对齐团队视觉调性",
    nodes: [
      {
        id: "gp", type: "group", position: { x: 40, y: 40 },
        data: { kind: "group", title: "情绪板 · 都市夜景" } as any,
        style: { width: 520, height: 380, zIndex: -1 },
      },
      {
        id: "m1", type: "image", position: { x: 70, y: 80 },
        data: { kind: "image", title: "参考 · 霓虹 1", prompt: "赛博朋克霓虹灯" } as any,
      },
      {
        id: "m2", type: "image", position: { x: 270, y: 80 },
        data: { kind: "image", title: "参考 · 霓虹 2", prompt: "雨夜城市街道" } as any,
      },
      {
        id: "m3", type: "image", position: { x: 70, y: 240 },
        data: { kind: "image", title: "参考 · 光影", prompt: "窗格光影投射" } as any,
      },
      {
        id: "m4", type: "image", position: { x: 270, y: 240 },
        data: { kind: "image", title: "参考 · 氛围", prompt: "烟雾 + 蓝光" } as any,
      },
      {
        id: "mt", type: "text", position: { x: 580, y: 160 },
        data: { kind: "text", title: "调性说明", content: "整体冷蓝调 + 霓虹粉点缀，雨夜氛围……", fontSize: 14 } as any,
      },
    ],
    edges: [],
  },

  // ── 模板 4：MV 节奏分镜 ──
  {
    id: "builtin:mv-beatboard",
    name: "MV · 7 拍节奏板",
    description: "7 个紧凑镜头（2-4s），贴合 BGM 节拍的情绪流",
    nodes: [
      {
        id: "mv1", type: "shot", position: { x: 40, y: 80 },
        data: { kind: "shot", title: "Beat 1 · 开场", shotSize: "特写", duration: 2, prompt: "歌手近景特写，聚光" } as any,
      },
      {
        id: "mv2", type: "shot", position: { x: 190, y: 80 },
        data: { kind: "shot", title: "Beat 2 · 转身", shotSize: "中景", duration: 3, prompt: "转身甩头，动感" } as any,
      },
      {
        id: "mv3", type: "shot", position: { x: 340, y: 80 },
        data: { kind: "shot", title: "Beat 3 · 全景", shotSize: "全景", duration: 4, prompt: "舞台全景，观众欢呼" } as any,
      },
      {
        id: "mv4", type: "shot", position: { x: 490, y: 80 },
        data: { kind: "shot", title: "Beat 4 · 乐器", shotSize: "特写", duration: 2, prompt: "吉他手手指特写" } as any,
      },
      {
        id: "mv5", type: "shot", position: { x: 640, y: 80 },
        data: { kind: "shot", title: "Beat 5 · 仰拍", shotSize: "仰拍", duration: 3, prompt: "从舞台向上仰拍歌手" } as any,
      },
      {
        id: "mv6", type: "shot", position: { x: 790, y: 80 },
        data: { kind: "shot", title: "Beat 6 · 甩镜", shotSize: "中景", duration: 3, prompt: "快速甩镜到主唱" } as any,
      },
      {
        id: "mv7", type: "shot", position: { x: 940, y: 80 },
        data: { kind: "shot", title: "Beat 7 · 高潮", shotSize: "特写", duration: 2, prompt: "副歌最高潮表情" } as any,
      },
      {
        id: "mva", type: "audio", position: { x: 490, y: 220 },
        data: { kind: "audio", title: "BGM · 导入音频文件" } as any,
      },
    ],
    edges: [_edge("mv1", "mv2"), _edge("mv2", "mv3"), _edge("mv3", "mv4"), _edge("mv4", "mv5"), _edge("mv5", "mv6"), _edge("mv6", "mv7")],
  },

  // ── 模板 5：AI 生图快速卡 ──
  {
    id: "builtin:quick-image-card",
    name: "快速生图卡",
    description: "配置 → Prompt → Image → Generator，最短路径跑通生图",
    nodes: [
      {
        id: "qc", type: "config", position: { x: 60, y: 180 },
        data: { kind: "config", title: "配置", generationMode: "image", count: 4, prompt: "" } as any,
      },
      {
        id: "qp", type: "prompt", position: { x: 300, y: 180 },
        data: { kind: "prompt", title: "Prompt", text: "一个戴帽子的女孩，站在秋天的枫叶树下" } as any,
      },
      {
        id: "qi", type: "image", position: { x: 540, y: 180 },
        data: { kind: "image", title: "预览图", prompt: "" } as any,
      },
      {
        id: "qg", type: "generator", position: { x: 780, y: 180 },
        data: { kind: "generator", title: "生成器", mode: "image", count: 4, prompt: "" } as any,
      },
    ],
    edges: [_edge("qc", "qp"), _edge("qp", "qi"), _edge("qi", "qg")],
  },
];