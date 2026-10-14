/**
 * 画布「剧本合规守护」桥（Wave 0 #13 孤儿端点接线第 2 条，2026-10-15）
 * ======================================================
 * 缺口证据：`app/core/canvas_routes_post.py:168` `@_route_post("/host/compliance-check")`
 * 已完整实现（token 校验 → JSON 解析 → 委托 `project_agent_host.script_compliance_check`
 * → 诚实状态码），但前端零调用。
 * 后果：AgentPanel 只能被动接后端推来的 `compliance.report` SSE（AgentPanel.tsx:277），
 * 用户在剧本卡片上**没有主动触发合规检查的入口** —— 漫剧合规是刚需
 * （提审前必查），被动等 SSE 等于「不点就不查」。
 *
 * 单一通道纪律：
 *  - 本文件**只做 fetch 薄封装 + 纯函数判读**，不做 UI、不做业务判定。
 *  - 后端 `script_compliance_check` 是唯一判定源（app/core/project_agent_host.py:741）；
 *    前端**不复制任何一条检查规则**，只按 level 着色展示。
 *  - 后端会同时 SSE 推 `compliance.report`（AgentPanel 已消费）⇒ 本端点
 *    **不新增第二条推送通道**，HTTP 返回只用于让用户当场看到结果。
 *
 * 判定分层（与后端 level 字段一一对应，见 project_agent_host.py:775）：
 *  warning = 需要改（漫剧提审会被打回的口径级问题）
 *  info    = 值得看一眼（遗留绑定、过度拆分等）
 */
import { BRIDGE, authHeaders, bridgeToken } from "./bridge";

/** 一条合规建议（镜像后端 suggestions 行） */
export type ComplianceSuggestion = {
  level?: string;
  category?: string;
  message?: string;
  action?: string;
  subject?: unknown[];
};

export type ComplianceResult = {
  ok: boolean;
  message?: string;
  suggestions?: ComplianceSuggestion[];
  summary?: string;
  ai_summary?: string;
  total_suggestions?: number;
  total_shots?: number;
  total_characters?: number;
};

/** 一条镜头（后端只读这几个字段，见 script_compliance_check 的 shots 用法） */
export type ComplianceShot = {
  title?: string;
  prompt?: string;
  shotSize?: string;
  duration?: number;
  characterName?: string;
};

export type ComplianceCharacter = { name?: string; appearance?: string };

/**
 * 剧本合规检查：POST /host/compliance-check。
 * 失败（网络/非 JSON）返回 `{ok:false, suggestions:[]}` —— **不抛**，
 * 让 UI 能直接把 message 展示出来，而不是掉进未捕获异常。
 */
export async function checkScriptCompliance(input: {
  script: string;
  shots?: ComplianceShot[];
  characters?: ComplianceCharacter[];
}): Promise<ComplianceResult> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/compliance-check?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        script: input.script || "",
        shots: input.shots || [],
        characters: input.characters || [],
      }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, suggestions: [], message: `合规检查异常: ${e}` };
  }
}

// ── 纯函数判读（vitest 无 jsdom，effect 零覆盖，逻辑必须抽出来测）────────

/** 按 level 分桶：warning 优先、info 其次、其余归 other。**不改顺序**（后端已按严重度排）。 */
export function bucketComplianceLevels(
  suggestions: ComplianceSuggestion[] | undefined,
): { warning: ComplianceSuggestion[]; info: ComplianceSuggestion[]; other: ComplianceSuggestion[] } {
  const warning: ComplianceSuggestion[] = [];
  const info: ComplianceSuggestion[] = [];
  const other: ComplianceSuggestion[] = [];
  for (const s of suggestions || []) {
    // trim + 小写：后端当前发的是干净小写枚举，但 SSE 侧（AgentPanel.tsx:277
    // 的 compliance.report）与将来新增的检查项都可能带空格/大写 ⇒ 前端兜住。
    const lv = String(s?.level || "").trim().toLowerCase();
    if (lv === "warning") warning.push(s);
    else if (lv === "info") info.push(s);
    else other.push(s);
  }
  return { warning, info, other };
}

/** 展示级计数：**只数真建议**，不给「0 条」发绿色通过徽章。
 *
 *  ⚠️ warningCount 优先于 suggestions.length 判据：`suggestions` 缺失/为undefined 时
 *  若warningCount>0 仍必须报 warning（保守侧：宁多报不漏报）。若反过来先判
 *  「长度为 0 ⇒ clean」，payload 截断时会静默显示「通过」—— 这正是合规检查最危险的失败模式。
 */
export function complianceSeverity(input: {
  suggestions?: ComplianceSuggestion[];
  warningCount: number;
}): "empty" | "clean" | "info" | "warning" {
  if (input.warningCount > 0) return "warning";
  const total = input.suggestions?.length ?? 0;
  if (total <= 0) return "clean";
  return "info";
}

/** 一句话结论：**逐字用后端 summary**（前端不自己编结论）。summary 缺失才兜底。 */
export function complianceHeadline(res: ComplianceResult | null): string {
  if (!res) return "";
  if (!res.ok) return res.message || "合规检查失败";
  const total = res.suggestions?.length ?? 0;
  if (total <= 0) {
    const shots = res.total_shots != null ? ` · ${res.total_shots} 分镜` : "";
    return `✅ 合规检查通过${shots}`;
  }
  return res.summary || `合规检查：${total} 条建议`;
}

/**
 * 收集画布上的镜头行喂给后端。
 * 判据：kind==="shot" 且有 prompt 或 title（空壳节点不参与，否则后端会误报「场景遗漏」）。
 */
export function collectComplianceShots(nodes: { data: unknown }[]): ComplianceShot[] {
  const out: ComplianceShot[] = [];
  for (const n of nodes || []) {
    const d = (n.data || {}) as Record<string, unknown>;
    if (d.kind !== "shot") continue;
    const title = String(d.title || "");
    const prompt = String(d.prompt || "");
    if (!title && !prompt) continue;
    const shot: ComplianceShot = { title, prompt };
    if (d.shotSize != null) shot.shotSize = String(d.shotSize);
    if (d.duration != null) shot.duration = Number(d.duration);
    if (d.characterName) shot.characterName = String(d.characterName);
    out.push(shot);
  }
  return out;
}

/**
 * 收集画布上的角色行喂给后端。
 * 判据（对齐 stores/node-factory.ts:487 `CharacterData` 真实字段）：
 *   kind==="character" 且 `characterName` 非空 —— 该字段是「绑定后自动同步显示」的角色名，
 *   后端 `known_names` 拿它做匹配。**空名必须跳过**：空名永远匹配不上，
 *   会把后端刷出一堆假「角色冲突」警告（宁可少报也不误报）。
 * `appearance` 在 CharacterData 里并不存在（角色外形在角色库侧），
 * 这里保留读取分支是为了后端将来加字段时不改前端；若节点上确实没有该键就不填。
 */
export function collectComplianceCharacters(nodes: { data: unknown }[]): ComplianceCharacter[] {
  const out: ComplianceCharacter[] = [];
  for (const n of nodes || []) {
    const d = (n.data || {}) as Record<string, unknown>;
    if (d.kind !== "character") continue;
    const name = String(d.characterName || d.name || "").trim();
    if (!name) continue;
    const c: ComplianceCharacter = { name };
    if (d.appearance) c.appearance = String(d.appearance);
    out.push(c);
  }
  return out;
}