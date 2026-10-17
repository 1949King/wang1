/**
 * ComfyUI workflow JSON → 画布节点 / 连线 映射（前端纯函数，零 DOM 依赖，可 vitest 直测）。
 *
 * 目标：把用户在 ComfyUI 里复制的工作流，粘贴后自动铺成小白模式 / 专业模式共用的画布节点，
 *       让「粘贴 workflow → 解析 → 自动映射回画布」形成闭环，而不是只弹一句 dry-run 提示。
 *
 * 支持两种输入（与后端 workflow_importer 对齐）：
 *   - UI workflow JSON：{ nodes: [{ id, type, inputs, outputs, widgets_values, title }], links: [...] }
 *   - graph 格式：{ "1": { class_type, inputs }, "2": { class_type, inputs } }
 *
 * 节点映射策略（class_type → 画布节点 kind + 摘要）：
 *   文本/提示词类 → prompt   （CLIPTextEncode 提取 text widget 作 prompt）
 *   模型/采样/分辨率 → config  （CheckpointLoader / LoraLoader / KSampler / EmptyLatentImage / VAE*）
 *   输出图片类 → image       （SaveImage / PreviewImage）
 *   输入图片类 → source      （LoadImage）
 *   其他未知 → text          （保底，标注 class_type，不丢节点）
 *
 * 连线映射：UI links 数组 [link_id, src_node, src_slot, dst_node, dst_slot, type] → edges。
 *            graph 格式 inputs 里的 [src_node_id, slot] 引用 → edges。
 */

import type { Edge } from "@xyflow/react";

/** 单个映射后的画布节点描述（kind 与 store 的 NodeData["kind"] 对齐） */
export type ComfyCanvasNode = {
  kind: "prompt" | "config" | "image" | "source" | "text";
  title: string;
  data: Record<string, unknown>;
  comfyId: string; // 原 workflow 节点 id，用于连线映射
};

/** 映射结果：节点列表 + 连线列表（comfyId 内部引用，调用方再换成真实 node.id） */
export type ComfyCanvasResult = {
  nodes: ComfyCanvasNode[];
  edges: { source: string; target: string }[]; // source/target 均为 comfyId
  classTypes: string[];
  warnings: string[];
};

/** class_type → 画布节点 kind */
function kindForClassType(classType: string): ComfyCanvasNode["kind"] {
  const c = classType.toLowerCase();
  if (c.includes("textencode") || c.includes("cliptext") || c.includes("text")) return "prompt";
  if (
    c.includes("checkpoint") ||
    c.includes("lora") ||
    c.includes("sampler") ||
    c.includes("latent") ||
    c.includes("vae") ||
    c.includes("unet") ||
    c.includes("controlnet") ||
    c.includes("model") ||
    c.includes("loader") ||
    c.includes("upscale")
  ) {
    return "config";
  }
  if (c.includes("saveimage") || c.includes("previewimage") || c.includes("save")) return "image";
  if (c.includes("loadimage") || c.includes("load")) return "source";
  return "text";
}

/** 从 node inputs/widgets_values 里抠出最像「提示词」的那段文本 */
function extractPrompt(inputs: unknown[], widgetsValues: unknown[]): string {
  // 优先 text / prompt 命名的 widget
  for (let i = 0; i < inputs.length; i++) {
    const inp = inputs[i] as Record<string, unknown>;
    const name = String(inp?.name || "").toLowerCase();
    if ((name === "text" || name === "prompt" || name.includes("text")) && typeof widgetsValues[i] === "string") {
      const v = (widgetsValues[i] as string).trim();
      if (v) return v;
    }
  }
  // 兜底：取第一个字符串 widget
  for (const v of widgetsValues) {
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

/** 从 graph 格式的 inputs 里抠提示词（text / prompt / positive 键） */
function extractGraphPrompt(inputs: Record<string, unknown>): string {
  const keys = ["text", "prompt", "positive", "clip_text", "conditioning_text"];
  for (const k of keys) {
    const v = inputs[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

/** 标题兜底：node.title 或 class_type */
function titleFor(classType: string, rawTitle?: unknown): string {
  if (typeof rawTitle === "string" && rawTitle.trim()) return rawTitle.trim();
  return classType;
}

/**
 * 解析 ComfyUI workflow JSON，映射成画布节点 + 连线。
 * 返回空 nodes 时说明不是合法的 workflow（调用方据此诚实失败）。
 */
export function comfyToCanvasNodes(json: unknown): ComfyCanvasResult {
  const empty: ComfyCanvasResult = { nodes: [], edges: [], classTypes: [], warnings: [] };
  if (!json || typeof json !== "object" || Array.isArray(json)) return empty;

  const o = json as Record<string, unknown>;

  // ── UI workflow 格式 ──
  if (Array.isArray(o.nodes)) {
    const rawNodes = o.nodes as Record<string, unknown>[];
    const rawLinks = Array.isArray(o.links) ? (o.links as unknown[][]) : [];
    const nodes: ComfyCanvasNode[] = [];
    const warnings: string[] = [];
    const classTypes: string[] = [];
    const edges: { source: string; target: string }[] = [];

    for (const raw of rawNodes) {
      const id = String(raw?.id ?? "");
      const classType = String(raw?.type || raw?.class_type || "");
      if (!classType) {
        warnings.push("跳过缺失 type 的节点");
        continue;
      }
      const inputs = Array.isArray(raw.inputs) ? (raw.inputs as unknown[]) : [];
      const widgets = Array.isArray(raw.widgets_values) ? (raw.widgets_values as unknown[]) : [];
      const kind = kindForClassType(classType);
      classTypes.push(classType);
      nodes.push({
        kind,
        title: titleFor(classType, raw.title),
        comfyId: id,
        data: { prompt: extractPrompt(inputs, widgets), comfyClassType: classType },
      });
    }

    // links → edges（links 格式 [link_id, src, src_slot, dst, dst_slot, type]）
    const byComfyId = new Map(nodes.map((n) => [n.comfyId, n]));
    const seenLinks = new Set<string>();
    for (const link of rawLinks) {
      if (!Array.isArray(link) || link.length < 5) continue;
      const src = String(link[1]);
      const dst = String(link[3]);
      if (!byComfyId.has(src) || !byComfyId.has(dst) || src === dst) continue;
      const key = `${src}->${dst}`;
      if (seenLinks.has(key)) continue;
      seenLinks.add(key);
      edges.push({ source: src, target: dst });
    }
    return { nodes, edges, classTypes, warnings };
  }

  // ── graph 格式 ──
  const nodes: ComfyCanvasNode[] = [];
  const warnings: string[] = [];
  const classTypes: string[] = [];
  const edges: { source: string; target: string }[] = [];
  const entries = Object.entries(o).filter(([, v]) => v && typeof v === "object");
  for (const [id, v] of entries) {
    const node = v as Record<string, unknown>;
    const classType = String(node.class_type || "");
    if (!classType) continue;
    const kind = kindForClassType(classType);
    classTypes.push(classType);
    const inputs = (node.inputs || {}) as Record<string, unknown>;
    nodes.push({
      kind,
      title: titleFor(classType, node.title),
      comfyId: id,
      data: { prompt: extractGraphPrompt(inputs), comfyClassType: classType },
    });
  }
  // inputs 里的 [src_id, slot] 引用 → edges（先收集合法节点 id，再去重，避免悬空边与重复边）
  const validIds = new Set(nodes.map((n) => n.comfyId));
  const seen = new Set<string>();
  for (const n of nodes) {
    const raw = entries.find(([eid]) => eid === n.comfyId)?.[1] as
      | Record<string, unknown>
      | undefined;
    const inputs = (raw?.inputs || {}) as Record<string, unknown>;
    for (const val of Object.values(inputs)) {
      if (!Array.isArray(val) || val.length !== 2 || typeof val[1] !== "number") continue;
      const src = String(val[0]);
      if (src === n.comfyId || !validIds.has(src)) continue;
      const key = `${src}->${n.comfyId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ source: src, target: n.comfyId });
    }
  }
  return { nodes, edges, classTypes, warnings };
}

/** 判断文本是否为 ComfyUI workflow（复用 bridge 判定，避免重复解析） */
export function isComfyWorkflowText(text: string): boolean {
  const t = (text || "").trim();
  if (!t || t[0] !== "{") return false;
  try {
    const json = JSON.parse(t);
    return comfyToCanvasNodes(json).nodes.length > 0;
  } catch {
    return false;
  }
}

/** 供测试 / 外部复用的空边类型（此处仅声明依赖，避免循环引用） */
export type { Edge };
