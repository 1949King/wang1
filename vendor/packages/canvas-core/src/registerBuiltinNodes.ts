/** 内置节点注册到 node-registry
 *
 * 在 App.tsx 启动时调用 registerBuiltinNodes() 一次性注册，
 * React Flow 的 nodeTypes 从 registry 动态读（buildNodeTypes()）。
 * 插件节点后续动态 register/unregister 都会被自动纳入。
 *
 * 核心节点与 infinite-canvas 对齐：image/text/config/video/audio/group
 * 拾光扩展：shot/script/prompt/generator
 */
import type { ComponentType, ReactNode } from "react";
import type { Node, NodeProps } from "@xyflow/react";
import {
  ShotNode,
  ScriptNode,
  ImageNode,
  VideoNode,
  PromptNode,
  TextNode,
  ConfigNode,
  GeneratorNode,
  GroupNode,
  AudioNode,
  MusicNode,
} from "./nodes";
import { MarkdownNode, ShotlistNode, StoryboardNode } from "./storyNodes";
import { CodeVideoNode } from "./codeVideoNode";
import {
  DirectorNode,
  DirectorCardNode,
  DigitalHumanNode,
  AnimationNode,
  PanoramaNode,
  NoteNode,
  SourceNode,
  CharacterNode,
} from "./mediaExtraNodes";
import { registerNodeDefinitions, type CanvasNodeDefinition } from "./plugins/node-registry";

/** 内置节点 meta — 左侧节点面板展示用 */
export const BUILTIN_NODE_META: Record<string, { title: string; icon: ReactNode; desc?: string; defaultSize: { width: number; height: number } }> = {
  shot:      { title: "分镜头",   icon: "🎬", desc: "单个镜头卡，含景别/时长/运镜", defaultSize: { width: 280, height: 160 } },
  script:    { title: "剧本卡",   icon: "📝", desc: "剧本/故事梗概，生成分镜上游", defaultSize: { width: 360, height: 180 } },
  image:     { title: "图片节点", icon: "🖼️", desc: "上传或生成的图片",         defaultSize: { width: 280, height: 200 } },
  video:     { title: "视频节点", icon: "🎥", desc: "视频片段（可循环预览）",     defaultSize: { width: 300, height: 180 } },
  prompt:    { title: "提示词",   icon: "💬", desc: "上游文本汇聚 → 模型输入",    defaultSize: { width: 280, height: 120 } },
  text:      { title: "文本",     icon: "📄", desc: "infinite 对齐 · 可复用说明/提示", defaultSize: { width: 300, height: 140 } },
  config:    { title: "生成配置", icon: "⚙️", desc: "infinite 对齐 · 锁定模型/模式/数量", defaultSize: { width: 320, height: 180 } },
  generator: { title: "生成器",   icon: "🔧", desc: "汇聚上游批量生成（拾光扩展）", defaultSize: { width: 320, height: 200 } },
  group:     { title: "编组容器", icon: "📦", desc: "框住一组节点的容器",         defaultSize: { width: 420, height: 280 } },
  audio:     { title: "音频节点", icon: "🎵", desc: "TTS / 上传音频入轨",         defaultSize: { width: 280, height: 120 } },
  music:     { title: "音乐节点", icon: "🎶", desc: "Suno 生成原创音乐（后端需配置 API）", defaultSize: { width: 280, height: 140 } },
  markdown:  { title: "Markdown", icon: "📑", desc: "AI-Canvas 对齐 · 分镜说明/文档", defaultSize: { width: 360, height: 280 } },
  shotlist:  { title: "分镜表",   icon: "📋", desc: "AI-Canvas 对齐 · 可编辑镜号表", defaultSize: { width: 720, height: 360 } },
  storyboard:{ title: "宫格分镜", icon: "▦", desc: "AI-Canvas 对齐 · 交互宫格裁出", defaultSize: { width: 420, height: 360 } },
  director:  { title: "3D 导演台", icon: "🎥", desc: "自研 Stage3D · 截图回写本节点", defaultSize: { width: 320, height: 280 } },
  directorCard: { title: "导演卡", icon: "🎬", desc: "剧本输入 → 自动拆解分镜", defaultSize: { width: 320, height: 240 } },
  digitalHuman: { title: "数字人", icon: "🧑", desc: "形象 + 台词 TTS；口型成片未接模型则诚实失败", defaultSize: { width: 320, height: 360 } },
  animation: { title: "逐帧动画", icon: "🎞️", desc: "AI-Canvas 对齐 · Sprite Sheet", defaultSize: { width: 340, height: 300 } },
  panorama:  { title: "全景",     icon: "🌐", desc: "AI-Canvas 对齐 · 等距柱状环视", defaultSize: { width: 360, height: 260 } },
  note:      { title: "画布笔记", icon: "📌", desc: "AI-Canvas 对齐 · 文字/形状标注", defaultSize: { width: 240, height: 160 } },
  source:    { title: "源文件",   icon: "📂", desc: "AI-Canvas 对齐 · 本地素材入口", defaultSize: { width: 300, height: 220 } },
  character: { title: "角色",     icon: "🧑‍🎨", desc: "角色库条目 · 点卡片打开捏脸", defaultSize: { width: 260, height: 240 } },
  codeVideo: { title: "代码成片", icon: "🧩", desc: "分镜/契约 → Chromium+ffmpeg 成片（诚实失败）", defaultSize: { width: 340, height: 320 } },
};

type BuiltinNode = { type: string; Component: ComponentType<NodeProps<Node>> };

const BUILTIN_NODES: BuiltinNode[] = [
  { type: "shot",      Component: ShotNode },
  { type: "script",    Component: ScriptNode },
  { type: "image",     Component: ImageNode },
  { type: "video",     Component: VideoNode },
  { type: "prompt",    Component: PromptNode },
  { type: "text",      Component: TextNode },
  { type: "config",    Component: ConfigNode },
  { type: "generator", Component: GeneratorNode },
  { type: "group",     Component: GroupNode },
  { type: "audio",     Component: AudioNode },
  { type: "music",     Component: MusicNode },
  { type: "markdown",  Component: MarkdownNode },
  { type: "shotlist",  Component: ShotlistNode },
  { type: "storyboard", Component: StoryboardNode },
  { type: "director",  Component: DirectorNode },
  { type: "directorCard", Component: DirectorCardNode },
  { type: "digitalHuman", Component: DigitalHumanNode },
  { type: "animation", Component: AnimationNode },
  { type: "panorama",  Component: PanoramaNode },
  { type: "note",      Component: NoteNode },
  { type: "source",    Component: SourceNode },
  { type: "character", Component: CharacterNode },
  { type: "codeVideo", Component: CodeVideoNode },
];

/** 应用启动时一次性注册所有内置节点 */
export function registerBuiltinNodes() {
  const defs: CanvasNodeDefinition[] = BUILTIN_NODES.map(({ type, Component }) => {
    const meta = BUILTIN_NODE_META[type] || { title: type, icon: "⬜", defaultSize: { width: 280, height: 160 } };
    return {
      type,
      title: meta.title,
      icon: meta.icon,
      description: meta.desc,
      defaultSize: meta.defaultSize,
      Component,
      showInCreateMenu: true,
    };
  });
  registerNodeDefinitions(defs, "builtin");
}
