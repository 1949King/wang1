import type { Edge, Node } from "@xyflow/react";

/** LibTV 式 Skill 包 — 供 Agent / 外部工具复现画布工作流 */
export type WorkflowSkill = {
  schema: "shiguang-canvas/skill/v1";
  name: string;
  description: string;
  dramaTitle?: string;
  episode?: string;
  nodes: { id: string; type?: string; position: { x: number; y: number }; data: unknown }[];
  edges: { id: string; source: string; target: string; type?: string }[];
  agent_hints: string[];
  exported_at: string;
};

export function buildWorkflowSkill(opts: {
  name: string;
  description?: string;
  dramaTitle?: string;
  episode?: string;
  nodes: Node[];
  edges: Edge[];
}): WorkflowSkill {
  const shots = opts.nodes.filter((n) => (n.data as { kind?: string }).kind === "shot");
  return {
    schema: "shiguang-canvas/skill/v1",
    name: opts.name,
    description: opts.description || `拾光剪影画布工作流：${opts.dramaTitle || "未命名"}`,
    dramaTitle: opts.dramaTitle,
    episode: opts.episode,
    nodes: opts.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      position: n.position,
      data: n.data,
    })),
    edges: opts.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: (e.data as { type?: string } | undefined)?.type,
    })),
    agent_hints: [
      "在拾光 AI 画布中加载此 Skill JSON，可复现节点拓扑与分镜参数",
      `共 ${opts.nodes.length} 个节点、${opts.edges.length} 条连线、${shots.length} 个镜头节点`,
      "建议按 shot 节点顺序依次调用 /host/generate-image 生成分镜图",
      "机位字段 cameraYaw/cameraPitch/focalLength 应写入提示词前缀",
      "生成完成后用 MATERIAL_TO_TIMELINE 或画布「全部入轨」回流剪辑",
    ],
    exported_at: new Date().toISOString(),
  };
}

export function downloadWorkflowSkill(skill: WorkflowSkill) {
  const blob = new Blob([JSON.stringify(skill, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${skill.name.replace(/[^\w\u4e00-\u9fff-]+/g, "_")}_skill.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function parseWorkflowSkill(raw: unknown): WorkflowSkill {
  if (!raw || typeof raw !== "object") {
    throw new Error("Skill 文件不是有效 JSON 对象");
  }
  const o = raw as Record<string, unknown>;
  if (o.schema !== "shiguang-canvas/skill/v1") {
    throw new Error(`不支持的 Skill schema：${String(o.schema || "缺失")}`);
  }
  if (!Array.isArray(o.nodes)) {
    throw new Error("Skill 缺少 nodes 数组");
  }
  if (!Array.isArray(o.edges)) {
    throw new Error("Skill 缺少 edges 数组");
  }
  const name = String(o.name || "").trim();
  if (!name) throw new Error("Skill 缺少 name");
  return {
    schema: "shiguang-canvas/skill/v1",
    name,
    description: String(o.description || ""),
    dramaTitle: o.dramaTitle ? String(o.dramaTitle) : undefined,
    episode: o.episode ? String(o.episode) : undefined,
    nodes: o.nodes as WorkflowSkill["nodes"],
    edges: o.edges as WorkflowSkill["edges"],
    agent_hints: Array.isArray(o.agent_hints) ? (o.agent_hints as string[]) : [],
    exported_at: String(o.exported_at || new Date().toISOString()),
  };
}

/** Skill → 可 loadProjectBundle 的工程包 */
export function skillToProjectBundle(skill: WorkflowSkill) {
  const known = new Set([
    "shot",
    "script",
    "image",
    "video",
    "prompt",
    "generator",
    "group",
    "audio",
  ]);
  const nodes = skill.nodes
    .filter((n) => known.has(String(n.type || (n.data as { kind?: string })?.kind || "")))
    .map((n) => ({
      id: n.id,
      type: String(n.type || (n.data as { kind?: string }).kind || "shot"),
      position: n.position || { x: 0, y: 0 },
      data: n.data,
    }));
  const edges = skill.edges.map((e, i) => ({
    id: e.id || `e_skill_${i}`,
    source: e.source,
    target: e.target,
    ...(e.type ? { data: { type: e.type } } : {}),
  }));
  return {
    name: skill.name,
    dramaTitle: skill.dramaTitle || skill.name,
    episode: skill.episode || "",
    nodes,
    edges,
  };
}

export async function readWorkflowSkillFile(file: File): Promise<WorkflowSkill> {
  const text = await file.text();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("Skill 文件不是合法 JSON");
  }
  return parseWorkflowSkill(parsed);
}
