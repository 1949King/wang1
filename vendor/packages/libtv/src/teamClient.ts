/**
 * 团队协作客户端（2026-10-31 · V4.49.1）
 *
 * ## 这里有两套完全不同的鉴权，别混
 *
 * | 面 | 基址 | 凭据 |
 * |---|---|---|
 * | 本机管理面 | canvas bridge（127.0.0.1:18765） | host token（authHeaders） |
 * | 团队服务面 | 用户填的 http://<内网IP>:18770 | 团队 Bearer 令牌（join 换取） |
 *
 * 混用的后果：把 host token 发给同事的服务器 = 泄露本机控制权。
 * 所以这里刻意分成 hostCall / teamCall 两个内部函数，**没有统一的 base**。
 */
import { BRIDGE, authHeaders } from "./bridge";

/** 团队服务里的项目条目（与 team_hub.list_projects 对齐）。 */
export type TeamProject = {
  project_id: string;
  name: string;
  rev: number;
  owner: string;
  updated_at: number;
  claimed_by: string;
  claim_expires_at: number;
};

/** join 之后持久化的凭据。 */
export type TeamCred = {
  address: string;
  member_id: string;
  name: string;
  token: string;
};

/** 局域网扫描结果。 */
export type DiscoveredServer = { name: string; address: string; port: number; host: string };

/** 带 code 的团队错误（面板据此给不同提示）。 */
export class TeamError extends Error {
  code: string;
  extra: Record<string, unknown>;

  constructor(code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message || code);
    this.name = "TeamError";
    this.code = code;
    this.extra = extra;
  }
}

const LS_ADDRESS = "shiguang:team:address";
const LS_CRED = "shiguang:team:cred";

/** 地址归一化：补协议、去尾斜杠、去空格。空串返回空串。 */
export function normalizeAddress(raw: string): string {
  const s = String(raw || "").trim();
  if (!s) return "";
  const withProto = /^https?:\/\//i.test(s) ? s : "http://" + s;
  return withProto.replace(/\/+$/, "");
}

export function teamAddress(): string {
  try {
    return normalizeAddress(window.localStorage.getItem(LS_ADDRESS) || "");
  } catch {
    return "";
  }
}

export function teamCred(): TeamCred | null {
  try {
    const raw = window.localStorage.getItem(LS_CRED);
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (!p || !p.token || !p.address) return null;
    return p as TeamCred;
  } catch {
    return null;
  }
}

function saveCred(cred: TeamCred): void {
  try {
    window.localStorage.setItem(LS_ADDRESS, cred.address);
    window.localStorage.setItem(LS_CRED, JSON.stringify(cred));
  } catch (e) {
    console.warn("[team] 凭据写盘失败（localStorage 不可用）:", e);
  }
}

export function teamLeave(): void {
  try {
    window.localStorage.removeItem(LS_CRED);
  } catch {
    /* localStorage 禁用时无需清理 */
  }
}

// ── 内部：两种调用面 ────────────────────────────────

/**
 * Windows 套接字错误码 → 能照做的一句话。
 *
 * 🔴 2026-11-02 用户实机反馈：面板上只显示
 * `[WinError 10038] 在一个非套接字上尝试了一个操作。` —— 使用者拿到这行字做不了任何事。
 * 纪律：**技术细节进 console，界面只给下一步动作**（后端 `team_discovery` 同一套口径）。
 */
const WIN_HINTS: Record<string, string> = {
  "10013": "权限不足：端口被系统策略或防火墙挡住，换端口或放行程序",
  "10038": "套接字已关闭：团队服务刚被停掉，重新启动一次就好",
  "10048": "端口已占用：这台机器上已有一个团队服务在跑（或换台机器当服务器）",
  "10049": "地址不可用：IP 不在本机网段，检查地址里的 IP 段",
  "10053": "连接被对方中断：对方服务刚停，重试一次",
  "10060": "连接超时：两台机器不在同一网段，或被防火墙拦住",
  "10061": "拒绝连接：对方没启动团队服务，或端口不是 18770",
  "10065": "网络不可达：两台机器没连到同一台路由器",
};

/** 把 fetch 抛出来的东西翻成 TeamError（原始异常只进 console，不上界面）。 */
function netError(addr: string, e: unknown, where: "host" | "team"): TeamError {
  const raw = e instanceof Error ? e.message : String(e);
  try {
    console.warn(`[team] ${where} 调用失败：${addr}`, e);
  } catch {
    /* console 不可用时无需处理 */
  }
  const win = /\[WinError (\d+)\]/.exec(raw)?.[1];
  const hint = win ? WIN_HINTS[win] : undefined;
  if (hint) return new TeamError(`net_${win}`, `${hint}（WinError ${win}）`, { raw });
  if (/Failed to fetch|NetworkError|Load failed|fetch failed/i.test(raw)) {
    return new TeamError("net_down", where === "host"
      ? "连不上本机画布桥（127.0.0.1:18765）：主程序可能刚重启，刷新画布再试一次"
      : `连不上 ${addr}：确认对方已点「启动团队服务」、地址和端口填对（默认 18770）、两台机器连的是同一个 Wi-Fi`,
      { raw });
  }
  return new TeamError("net_error", raw, { raw });
}

async function hostCall<T>(path: string, init?: RequestInit): Promise<T> {
  // 请求头在 try 之外算：`authHeaders()` 抛的是**本地装配错误**，不能被误报成「连不上桥」。
  const headers = { ...authHeaders(true), ...(init?.headers || {}) };
  let res: Response;
  try {
    res = await fetch(BRIDGE + path, { ...init, headers });
  } catch (e) {
    throw netError(BRIDGE, e, "host");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.ok === false) {
    throw new TeamError(String(data?.code || "host_" + res.status),
      String(data?.message || "本机接口失败"), { status: res.status });
  }
  return data as T;
}

async function teamCall<T>(
  path: string,
  opts: { method?: string; body?: unknown; address?: string; token?: string } = {},
): Promise<T> {
  const address = normalizeAddress(opts.address || teamCred()?.address || teamAddress());
  if (!address) throw new TeamError("no_address", "还没填团队服务地址");
  const token = opts.token ?? teamCred()?.token ?? "";
  let res: Response;
  try {
    res = await fetch(address + path, {
      method: opts.method || (opts.body ? "POST" : "GET"),
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: "Bearer " + token } : {}),
      },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch (e) {
    throw netError(address, e, "team");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data?.ok === false) {
    throw new TeamError(String(data?.code || "team_" + res.status),
      String(data?.message || "团队服务返回错误"), { status: res.status, ...data });
  }
  return data as T;
}

// ── 本机管理面 ──────────────────────────────────────
export type TeamHostStatus = {
  ok: boolean;
  running: boolean;
  address: string;
  lan_ip: string;
  port: number;
  name?: string;
  root?: string;
  stats: { projects?: number; members?: number; pending_handoffs?: number };
  hint?: string;
};

export function teamHostStatus(): Promise<TeamHostStatus> {
  return hostCall<TeamHostStatus>("/host/team/status");
}

export function teamHostStart(opts: { port?: number; name?: string; root?: string } = {}): Promise<TeamHostStatus> {
  return hostCall<TeamHostStatus>("/host/team/start", {
    method: "POST",
    body: JSON.stringify(opts),
  });
}

export function teamHostStop(): Promise<TeamHostStatus> {
  return hostCall<TeamHostStatus>("/host/team/stop", { method: "POST", body: "{}" });
}

export async function teamDiscover(): Promise<DiscoveredServer[]> {
  const data = await hostCall<{ servers?: DiscoveredServer[] }>("/host/team/discover");
  return Array.isArray(data.servers) ? data.servers : [];
}

// ── 团队服务面 ──────────────────────────────────────
export async function teamJoin(address: string, name: string, role = "editor"): Promise<TeamCred> {
  const addr = normalizeAddress(address);
  if (!addr) throw new TeamError("no_address", "请先填团队服务地址");
  const data = await teamCall<{ member_id: string; name: string; token: string }>("/team/join",
    { body: { name, role }, address: addr });
  const cred: TeamCred = { address: addr, member_id: data.member_id, name: data.name, token: data.token };
  saveCred(cred);
  return cred;
}

export function teamListProjects(): Promise<TeamProject[]> {
  return teamCall<{ projects: TeamProject[] }>("/team/projects").then((d) =>
    Array.isArray(d.projects) ? d.projects : []);
}

export function teamMembers(): Promise<Array<{ id: string; name: string; role: string }>> {
  return teamCall<{ members: Array<{ id: string; name: string; role: string }> }>("/team/members")
    .then((d) => (Array.isArray(d.members) ? d.members : []));
}

export function teamCreateProject(name: string, bundle: unknown): Promise<{ project_id: string; rev: number }> {
  return teamCall("/team/projects", { body: { name, bundle } });
}

export function teamPull(projectId: string, rev = 0): Promise<{ rev: number; latest_rev: number; bundle: unknown; name: string }> {
  const q = rev ? "?rev=" + rev : "";
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + q);
}

export function teamPush(projectId: string, bundle: unknown, baseRev: number, message = ""): Promise<{ rev: number }> {
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + "/push",
    { body: { bundle, base_rev: baseRev, message } });
}

export function teamClaim(projectId: string, ttl = 600): Promise<{ expires_at: number }> {
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + "/claim", { body: { ttl } });
}

export function teamRelease(projectId: string): Promise<{ released: boolean }> {
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + "/release", { body: {} });
}

export function teamHandoff(projectId: string, to: string, message = ""): Promise<{ handoff_id: string }> {
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + "/handoff",
    { body: { to, message } });
}

export type TeamHandoffItem = {
  handoff_id: string;
  project_id: string;
  project_name: string;
  from: string;
  message: string;
  created_at: number;
};

export function teamInbox(): Promise<TeamHandoffItem[]> {
  return teamCall<{ items: TeamHandoffItem[] }>("/team/inbox").then((d) =>
    Array.isArray(d.items) ? d.items : []);
}

export function teamAck(handoffId: string): Promise<{ status: string }> {
  return teamCall("/team/inbox/" + encodeURIComponent(handoffId) + "/ack", { body: {} });
}
