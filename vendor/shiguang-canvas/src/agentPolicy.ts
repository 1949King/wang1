/** 与 app/core/agent_policy.py 对齐的前端策略（画布本地写操作不绕过确认）。 */

export type AgentMode = "plan" | "collaborative" | "autonomous";
export type ToolEffect = "read" | "canvas_write" | "file_write" | "media_write" | "memory_write";
export type PolicyAction = "allow" | "require_approval" | "deny";

const WRITE: Set<ToolEffect> = new Set([
  "canvas_write",
  "file_write",
  "media_write",
  "memory_write",
]);

const CANVAS: Record<string, { effect: ToolEffect; paid: boolean }> = {
  queryNodes: { effect: "read", paid: false },
  canvas_query: { effect: "read", paid: false },
  queryTimeline: { effect: "read", paid: false },
  selectNode: { effect: "read", paid: false },
  canvas_select: { effect: "read", paid: false },
  addNode: { effect: "canvas_write", paid: false },
  updateNode: { effect: "canvas_write", paid: false },
  connectNodes: { effect: "canvas_write", paid: false },
  deleteNode: { effect: "canvas_write", paid: false },
  setNodeImage: { effect: "canvas_write", paid: false },
  setNodeVideo: { effect: "canvas_write", paid: false },
  importImage: { effect: "canvas_write", paid: false },
  duplicateNode: { effect: "canvas_write", paid: false },
  canvas_duplicate_node: { effect: "canvas_write", paid: false },
  groupNodes: { effect: "canvas_write", paid: false },
  canvas_group: { effect: "canvas_write", paid: false },
  bindShotlistFrame: { effect: "canvas_write", paid: false },
  canvas_bind_shotlist_frame: { effect: "canvas_write", paid: false },
  undo: { effect: "canvas_write", paid: false },
  canvas_undo: { effect: "canvas_write", paid: false },
  redo: { effect: "canvas_write", paid: false },
  canvas_redo: { effect: "canvas_write", paid: false },
  runGenerate: { effect: "media_write", paid: true },
  batchGenerate: { effect: "media_write", paid: true },
  runBatchGenerate: { effect: "media_write", paid: true },
  canvas_batch_generate: { effect: "media_write", paid: true },
  breakdown: { effect: "canvas_write", paid: false },
  applyStoryboard: { effect: "canvas_write", paid: false },
  storyboardBreakdown: { effect: "canvas_write", paid: false },
  canvas_breakdown: { effect: "canvas_write", paid: false },
  fillStoryboardCell: { effect: "canvas_write", paid: false },
  canvas_fill_storyboard_cell: { effect: "canvas_write", paid: false },
};

const MODE_KEY = "shiguang-canvas:agent-mode";

export function loadAgentMode(): AgentMode {
  try {
    const v = localStorage.getItem(MODE_KEY);
    if (v === "plan" || v === "collaborative" || v === "autonomous") return v;
  } catch {
    /* ignore */
  }
  return "collaborative";
}

export function saveAgentMode(mode: AgentMode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    /* ignore */
  }
}

export function lookupCanvasTool(action: string): { effect: ToolEffect; paid: boolean } {
  return CANVAS[action] || { effect: "file_write", paid: false };
}

export function decideCanvasTool(
  action: string,
  mode: AgentMode,
  approved = false,
): { action: PolicyAction; effect: ToolEffect; paid: boolean; reason: string } {
  const { effect, paid } = lookupCanvasTool(action);
  if (mode === "plan" && effect !== "read") {
    return { action: "deny", effect, paid, reason: "Plan 模式禁止改画布/生成" };
  }
  if (mode === "autonomous" || effect === "read") {
    return { action: "allow", effect, paid, reason: "允许" };
  }
  if (approved) {
    return { action: "allow", effect, paid, reason: "已确认" };
  }
  return { action: "require_approval", effect, paid, reason: "协作模式需确认后再改画布" };
}

export function isWriteEffect(effect: ToolEffect): boolean {
  return WRITE.has(effect);
}
