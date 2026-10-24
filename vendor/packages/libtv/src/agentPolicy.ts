/** Agent 工具策略 —— ★ 刀 A4（2026-10-05）：**改为消费后端下发**，本文件不再维护映射。
 *
 * **修的问题**：这里曾硬编码一份 `CANVAS` 映射（20+ 条 `effect`/`paid`），与后端
 * `agent_action_registry._CANVAS_ACTION_ROWS` 构成**两个真源** —— 后端新增一个工具、
 * 前端不知道 ⇒ 落到默认分支**静默错判**（轻则多问一次，重则少问一次）。
 * 项目纪律是「派生值一律后端下发，前端不要自己算」。
 *
 * **现在的分工**：
 *   · 真源 = 后端 `_CANVAS_ACTION_ROWS`（action / danger / effect / desc），
 *     经 `GET /host/agent-policy` 整体下发（含 `table_hash` 便于发现版本不一致）；
 *   · 本文件只保留「**怎么用**策略」的判定逻辑（mode → allow/require_approval/deny）。
 *
 * **保守兜底（重要）**：策略未就绪或遇到未知工具时，一律按
 * `{ effect: "media_write", paid: true, danger: "dangerous" }` 处理
 * ⇒ 协作模式必须确认、Plan 模式必须拦截。**绝不静默放行未知工具。**
 */
import { BRIDGE, bridgeToken } from "./bridge";

export type AgentMode = "plan" | "collaborative" | "autonomous";
export type ToolEffect =
  | "read"
  | "canvas_write"
  | "file_write"
  | "media_write"
  | "memory_write";
export type PolicyAction = "allow" | "require_approval" | "deny";
export type DangerLevel = "safe" | "dangerous";

export interface AgentToolPolicy {
  effect: ToolEffect;
  paid: boolean;
  danger: DangerLevel;
  desc?: string;
}

const WRITE: Set<ToolEffect> = new Set([
  "canvas_write",
  "file_write",
  "media_write",
  "memory_write",
]);

/** 未就绪/未知工具时的保守策略：当成「写 + 付费 + 危险」⇒ 必问必拦。 */
const CONSERVATIVE: AgentToolPolicy = {
  effect: "media_write",
  paid: true,
  danger: "dangerous",
};

let _tools: Record<string, AgentToolPolicy> | null = null;
let _tableHash = "";
let _primePromise: Promise<boolean> | null = null;

/**
 * 拉取并缓存后端策略（幂等，画布启动时调一次即可）。
 * 失败**不抛异常**：保持 `_tools=null` ⇒ 全部走保守兜底（宁多问，不静默放行）。
 */
export function primeAgentPolicy(): Promise<boolean> {
  if (_tools) return Promise.resolve(true);
  if (_primePromise) return _primePromise;
  _primePromise = (async () => {
    try {
      const res = await fetch(`${BRIDGE}/host/agent-policy`, {
        headers: { "X-Shiguang-Token": bridgeToken() },
      });
      const data = await res.json();
      if (data?.ok && data.tools && typeof data.tools === "object") {
        _tools = data.tools as Record<string, AgentToolPolicy>;
        _tableHash = String(data.table_hash || "");
        return true;
      }
      console.warn("[agentPolicy] 策略下发无效，改用保守兜底", data?.message);
      return false;
    } catch (e) {
      console.warn("[agentPolicy] 策略下发失败，改用保守兜底", e);
      return false;
    } finally {
      _primePromise = null;
    }
  })();
  return _primePromise;
}

/** 诊断/测试用：当前策略快照（是否已加载、条数、后端表哈希）。 */
export function getAgentPolicySnapshot(): {
  loaded: boolean;
  count: number;
  tableHash: string;
  tools: Record<string, AgentToolPolicy> | null;
} {
  return {
    loaded: _tools !== null,
    count: _tools ? Object.keys(_tools).length : 0,
    tableHash: _tableHash,
    tools: _tools,
  };
}

/** 仅测试用：重置缓存。 */
export function _resetAgentPolicyForTest(): void {
  _tools = null;
  _tableHash = "";
  _primePromise = null;
}

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

/** 查某画布 action 的策略；**未知/未就绪 ⇒ 保守兜底**（不静默放行）。 */
export function lookupCanvasTool(action: string): AgentToolPolicy {
  const hit = _tools?.[action];
  return hit ? { ...hit } : CONSERVATIVE;
}

export function decideCanvasTool(
  action: string,
  mode: AgentMode,
  approved = false,
): {
  action: PolicyAction;
  effect: ToolEffect;
  paid: boolean;
  danger: DangerLevel;
  reason: string;
} {
  const { effect, paid, danger } = lookupCanvasTool(action);
  if (mode === "plan" && effect !== "read") {
    return { action: "deny", effect, paid, danger, reason: "Plan 模式禁止改画布/生成" };
  }
  if (mode === "autonomous" || effect === "read") {
    return { action: "allow", effect, paid, danger, reason: "允许" };
  }
  if (approved) {
    return { action: "allow", effect, paid, danger, reason: "已确认" };
  }
  return {
    action: "require_approval",
    effect,
    paid,
    danger,
    reason: "协作模式需确认后再改画布",
  };
}

export function isWriteEffect(effect: ToolEffect): boolean {
  return WRITE.has(effect);
}
