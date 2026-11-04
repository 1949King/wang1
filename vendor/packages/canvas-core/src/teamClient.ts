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
/** 本机主人凭据（服务端随启动一起下发；`reused` = 沿用盘上那张令牌，没换新的）。 */
export type TeamOwnerCred = {
  member_id: string;
  name: string;
  role: string;
  token: string;
  reused?: boolean;
  created?: boolean;
  promoted?: boolean;
};

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
  owner?: TeamOwnerCred | null;
};

export function teamHostStatus(): Promise<TeamHostStatus> {
  return hostCall<TeamHostStatus>("/host/team/status");
}

/**
 * 启动本机团队服务。
 *
 * 🔴 2026-11-04：服务端在启动时就把「本机主人」认了（`ensure_owner`），凭据随响应回来
 * （`owner`）。这里顺手落盘 —— 否则用户还得「手填自己地址 → 点加入自己」才能出配对码，
 * 第一步就卡在 401 上。凭据无效/被删时服务端会重签，`reused` 只作诊断用。
 */
export async function teamHostStart(opts: { port?: number; name?: string; root?: string } = {}): Promise<TeamHostStatus> {
  const st = await hostCall<TeamHostStatus>("/host/team/start", {
    method: "POST",
    body: JSON.stringify(opts),
  });
  const o = st.owner;
  if (o?.token && o.member_id && st.address) {
    saveCred({ address: st.address, member_id: o.member_id, name: o.name, token: o.token });
  }
  return st;
}

export function teamHostStop(): Promise<TeamHostStatus> {
  return hostCall<TeamHostStatus>("/host/team/stop", { method: "POST", body: "{}" });
}

export async function teamDiscover(): Promise<DiscoveredServer[]> {
  const data = await hostCall<{ servers?: DiscoveredServer[] }>("/host/team/discover");
  return Array.isArray(data.servers) ? data.servers : [];
}

/**
 * 剪辑器 `clip.path`（本地绝对路径）→ 画布能 fetch 的 `/inbox_file/…`。
 *
 * 只做路径换算、**不传字节**：`canvas_server` 有 30 秒请求上限，一条 200MB 成片
 * 由后端代传必然超时；换算完交给前端同源直传才稳。`outside` 是不在素材库里的
 * 路径（用户从别处拖进来的），界面上要如实说它们同步不了。
 */
export function teamInboxMap(paths: string[]): Promise<{ map: Record<string, string>; outside: string[] }> {
  return hostCall<{ map?: Record<string, string>; outside?: string[] }>("/host/team/inbox-map", {
    method: "POST",
    body: JSON.stringify({ paths: Array.isArray(paths) ? paths.slice(0, 500) : [] }),
  }).then((d) => ({ map: d.map || {}, outside: Array.isArray(d.outside) ? d.outside : [] }));
}

/**
 * 让本机后端从视频里抽一帧当封面，返回 `data:image/jpeg;base64,…`（失败回空串）。
 *
 * ## 为什么不是浏览器自己截
 *
 * 画布跑在 Qt WebEngine 上，实测 `canPlayType('video/mp4; codecs="avc1.42E01E"')`
 * 是空串、`<video>` 报 `error.code=4`（webm 正常）—— 这个内核**没有 H.264**，
 * 而本产品渲染出来的成片就是 h264。所以 `video + canvas.drawImage` 那条路
 * 对 mp4 不存在，只能回到本机的 ffmpeg。
 *
 * 失败一律回空串：封面是锦上添花，不能因为它抽不出来就把视频也传不上去。
 */
export async function teamPoster(path: string, at = 0.35): Promise<string> {
  if (!path) return "";
  try {
    const d = await hostCall<{ data_url?: string }>("/host/team/poster", {
      method: "POST",
      body: JSON.stringify({ path, at }),
    });
    return String(d.data_url || "");
  } catch {
    return "";
  }
}

/**
 * 把一个团队附件下载到本机素材库，返回本地路径。
 *
 * **一次只传一个 URL**：`canvas_server` 有 30 秒请求上限，十来个片段叠在一个请求里
 * 必然超时并留下半截文件。调用方串行循环即可（局域网单文件 2~5 秒）。
 *
 * 后端只放行 `…/team/projects/{id}/assets/{sha}` 形式（SSRF 闸门），
 * 别的地址会回 `bad_url`。
 */
export function teamMaterialize(
  url: string,
  name: string,
): Promise<{ ok: boolean; path?: string; bytes?: number; cached?: boolean; message?: string }> {
  return hostCall<{ ok: boolean; path?: string; bytes?: number; cached?: boolean; message?: string }>(
    "/host/team/materialize",
    { method: "POST", body: JSON.stringify({ url, name }) },
  );
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

/** 成员列表。`last_seen` 是「最后一次活跃」的秒级时间戳（老服务端没有 ⇒ undefined）。 */
export function teamMembers(): Promise<TeamMember[]> {
  return teamCall<{ members: TeamMember[] }>("/team/members")
    .then((d) => (Array.isArray(d.members) ? d.members : []));
}

/** 角色（2026-11-04 起真正参与鉴权）。 */
export type TeamRole = "owner" | "editor" | "viewer";

/**
 * 改某个成员的角色。**只有 owner 能调**，服务端会挡（403）。
 *
 * 为什么需要它：给甲方看完一轮就该收回权限。踢出去再重加一遍会丢掉他提过的
 * 批注归属，降级才是对的做法。
 */
export function teamSetRole(memberId: string, role: TeamRole): Promise<TeamMember> {
  return teamCall<{ member: TeamMember }>(
    "/team/members/" + encodeURIComponent(memberId) + "/role",
    { body: { role } },
  ).then((d) => d.member);
}

export type TeamMember = {
  id: string;
  name: string;
  role: string;
  /** 最后一次活跃（秒）。0/undefined = 从来没动过（老库补列后就是这样）。 */
  last_seen?: number;
};

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

// ── 版本差异（「同事到底改了哪」）────────────────────

/** 两份版本的摘要差异（与 `team_hub.diff_bundle` 对齐）。 */
export type TeamDiff = {
  project_id: string;
  from_rev: number;
  to_rev: number;
  /** 落后几版 */
  revisions: number;
  same: boolean;
  nodes?: {
    added: number;
    removed: number;
    changed: number;
    added_titles?: string[];
    removed_titles?: string[];
    changed_titles?: string[];
  };
  edges?: { added: number; removed: number };
  timeline?: { before: number; after: number; added: number; removed: number; changed: number };
  title?: { before: string; after: string; changed: boolean };
};

/** `from`/`to` 传 0 表示「不指定」：都传 0 服务端自动取最近两版。 */
export function teamDiff(projectId: string, fromRev = 0, toRev = 0): Promise<TeamDiff> {  const qs: string[] = [];
  if (fromRev) qs.push("from=" + fromRev);
  if (toRev) qs.push("to=" + toRev);
  return teamCall(
    "/team/projects/" + encodeURIComponent(projectId) + "/diff" + (qs.length ? "?" + qs.join("&") : ""),
  );
}

// ── 历史版本与回滚 ──────────────────────────────────

/** 一版的历史条目（服务端 `/versions` 原样下发）。 */
export type TeamVersion = {
  rev: number;
  sha256: string;
  bytes: number;
  author: string;
  message: string;
  created_at: number;
};

export function teamVersions(projectId: string): Promise<TeamVersion[]> {
  return teamCall<{ versions: TeamVersion[] }>(
    "/team/projects/" + encodeURIComponent(projectId) + "/versions",
  ).then((d) => (Array.isArray(d.versions) ? d.versions : []));
}

/**
 * 回滚 = 把 `toRev` 的内容**重新提交成最新版**（历史只增不删）。
 * `baseRev` 传当前看到的 rev：中途有人提交过就 Conflict，不会连他那一版一起盖掉。
 */
export function teamRollback(
  projectId: string,
  toRev: number,
  baseRev = 0,
): Promise<{ rev: number; rolled_back_to: number }> {
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + "/rollback",
    { body: { to_rev: toRev, base_rev: baseRev } });
}

// ── 本地版本锚点 ────────────────────────────────────
//
// 不知道「我这份画布是基于服务器哪一版」就算不出差异。所以每次 push/pull/接手
// 成功后记一笔。**不记录也不影响协作** —— 算不出差异时退化成「服务器 rev N，
// 要不要拉」，只是不够具体。

const LS_REV_PREFIX = "shiguang:team:rev:";

export function localRevOf(projectId: string): number {
  if (!projectId) return 0;
  try {
    const v = Number(window.localStorage.getItem(LS_REV_PREFIX + projectId) || 0);
    return Number.isFinite(v) && v > 0 ? Math.floor(v) : 0;
  } catch {
    return 0;
  }
}

export function setLocalRev(projectId: string, rev: number): void {
  if (!projectId || !Number.isFinite(rev) || rev <= 0) return;
  try {
    window.localStorage.setItem(LS_REV_PREFIX + projectId, String(Math.floor(rev)));
  } catch (e) {
    // 记不住只是下次算不出差异，不该拦住协作本身
    console.warn("[team] 本地版本锚点写入失败:", e);
  }
}

// ── 附件（视频 / 图片 / 音频 —— 2026-11-02）──────────
//
// 为什么不复用 `teamCall`：它强制 `Content-Type: application/json` 并
// `JSON.stringify(body)`。成片是几十上百 MB 的二进制，走 JSON 等于先 base64
// 膨胀 33% 再一次性进内存 —— 8GB 机器会当场换页。所以附件单独两条通道：
// 上传用 XHR（fetch 没有上传进度事件），下载拼 `<video src>` 能直连的 URL。

/** 附件元信息（与 team_hub.list_assets 对齐）。 */
export type TeamAsset = {
  sha256: string;
  name: string;
  kind: string;
  mime: string;
  bytes: number;
  author: string;
  created_at: number;
  /** 归属提示（「镜 03」「剧本」），空串表示不知道 —— 老附件没有这个信息 */
  owner?: string;
  /** 封面附件的 sha256（视频首帧），空串表示没有 */
  poster?: string;
};

/** 附件类型：只这几个值后端认，其余落 `file`。 */
export type TeamAssetKind = "image" | "video" | "audio" | "text" | "file";

/** 当前团队服务基址（`http://192.168.x.x:18770`）。没配或没加入时为空串。 */
export function teamBaseUrl(): string {
  return normalizeAddress(teamCred()?.address || teamAddress());
}

/**
 * 拼一个**能直接塞进 `<video src>` / `<img src>` 的**附件地址。
 *
 * 为什么带 `?token=`：媒体元素发不了 `Authorization` 头。后端为此在字节流端点
 * 上额外接受查询参数令牌（`team_server._token()`）。**代价是令牌会出现在 URL 里**
 * ——内网 + 一次性成员令牌可以接受；密码类凭据绝不能这么走。
 * 没加入团队时返回空串，调用方据此保留原 URL，不要拿空串去覆盖。
 */
export function teamAssetUrl(projectId: string, sha: string): string {
  const base = teamBaseUrl();
  const token = teamCred()?.token || "";
  if (!base || !projectId || !sha) return "";
  const q = token ? "?token=" + encodeURIComponent(token) : "";
  return `${base}/team/projects/${encodeURIComponent(projectId)}/assets/${encodeURIComponent(sha)}${q}`;
}

export function teamListAssets(projectId: string): Promise<TeamAsset[]> {
  return teamCall<{ assets: TeamAsset[] }>(
    "/team/projects/" + encodeURIComponent(projectId) + "/assets",
  ).then((d) => (Array.isArray(d.assets) ? d.assets : []));
}

export function teamDeleteAsset(projectId: string, sha: string): Promise<{ removed: boolean }> {
  return teamCall("/team/projects/" + encodeURIComponent(projectId) + "/assets/" +
    encodeURIComponent(sha), { method: "DELETE" });
}

/**
 * 上传一个附件。**走 XHR** —— fetch 至今没有上传进度事件，几十 MB 的成片没有
 * 进度反馈，使用者会以为界面卡死然后反复点击。
 *
 * 失败语义：抛 `TeamError`，code 至少包含 `too_large` / `bad_asset` / `net_*`，
 * 中文 message 直接可显示（后端已翻译，`netError` 也翻译了连接类）。
 */
export function teamUploadAsset(
  projectId: string,
  blob: Blob,
  name: string,
  kind: TeamAssetKind,
  onProgress?: (loaded: number, total: number) => void,
  opts: { owner?: string; poster?: string } = {},
): Promise<TeamAsset> {
  const base = teamBaseUrl();
  const token = teamCred()?.token || "";
  if (!base) return Promise.reject(new TeamError("no_address", "还没加入团队，无法上传附件"));
  if (!blob || blob.size <= 0) {
    return Promise.reject(new TeamError("bad_asset", `「${name}」是空文件（0 字节），不传`));
  }
  let url = `${base}/team/projects/${encodeURIComponent(projectId)}/assets` +
    `?name=${encodeURIComponent(name)}&kind=${encodeURIComponent(kind)}`;
  // 归属与封面都是可选的：没有就不拼参数，别传空串让服务端以为「就是要清空」
  if (opts.owner) url += `&owner=${encodeURIComponent(opts.owner)}`;
  if (opts.poster) url += `&poster=${encodeURIComponent(opts.poster)}`;
  return new Promise<TeamAsset>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    if (token) xhr.setRequestHeader("Authorization", "Bearer " + token);
    // 显式给 mime：后端记下来，下载时原样回 Content-Type（否则 <video> 拒绝播）
    xhr.setRequestHeader("Content-Type", blob.type || "application/octet-stream");
    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) onProgress(ev.loaded, ev.total);
      };
    }
    xhr.onload = () => {
      let data: { ok?: boolean; code?: string; message?: string } & Partial<TeamAsset> = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        /* 非 JSON 响应（网关 502 之类）已由状态码兜住 */
      }
      if (xhr.status >= 200 && xhr.status < 300 && data.ok !== false && data.sha256) {
        resolve(data as TeamAsset);
      } else {
        reject(new TeamError(String(data.code || "upload_" + xhr.status),
          String(data.message || `上传「${name}」失败（HTTP ${xhr.status}）`), { status: xhr.status }));
      }
    };
    xhr.onerror = () => reject(netError(base, new Error("Failed to fetch"), "team"));
    xhr.onabort = () => reject(new TeamError("aborted", `已取消上传「${name}」`));
    xhr.send(blob);
  });
}

// ── 配对码 / 邀请链接（2026-11-02，2026-11-04 去掉二维码）──
//
// 手填 IP 是这套流程里最硬的一步：得有人去查「我这台的内网 IP 是多少」再一个字
// 一个字念给对方。配对码把它压成 6 位数字 —— 念一遍就够。
//
// 只留两条路（用户 2026-11-04 决定）：
//   ① **6 位数字码**：当面念、微信发数字都行，同事在面板里输进去
//   ② **邀请链接**：`http://ip:port/pair?code=…`，点开是一页能复制的说明
// 二维码砍掉 —— 它编的就是这条链接，只是换了个壳，还要多养一层 cv2。
//
// 三条路分工不同，别混：
//   · teamPairing()     主机侧：申请一张**一次性**码（附邀请链接），120 秒有效
//   · teamFindByCode()  同事侧第一步：靠码在局域网里找到主机地址（UDP 广播，
//                       浏览器发不出去 ⇒ 只能借本机桥代劳）
//   · teamPair()        同事侧第二步：拿码换令牌（**唯一不带令牌的团队端点**）

/** 一张配对码（与 `team_server._pairing_payload` 对齐）。 */
export type TeamPairingInfo = {
  /** 6 位数字，空串表示「我手上现在没有活码」 */
  code: string;
  /** 发码那台机器的名字（多台服务器时用来确认没连错） */
  host_name?: string;
  /** 主机地址 `http://192.168.x.x:18770` */
  address: string;
  host_ip?: string;
  host_port?: number;
  /** 这张码一共能请几个人 */
  max_uses: number;
  /** 已经用掉几个名额 */
  uses: number;
  /** 还能请几个 */
  remaining: number;
  /** 到期时间戳（秒），0 表示没拿到码 */
  expires_at: number;
  /** 还剩几秒（服务端算好的，省得前端跟本机时钟较劲） */
  ttl: number;
  /** 现在能不能用 */
  alive: boolean;
  /** 名额用完了 */
  exhausted: boolean;
  /** 过期了 */
  expired: boolean;
  /** 被主人主动作废了（与「用完了」不同，要说清） */
  revoked: boolean;
  /** 复用了一张还没过期的码，不是新号码 */
  reused: boolean;
  /** 因为名额不够而废掉了旧码，重新发的 */
  replaced: boolean;
  /** 用这张码进来的人是什么角色 */
  role?: TeamRole;
  /** 邀请链接：`http://ip:port/pair?code=…`，点开是一页能复制地址和码的说明 */
  pair_url: string;
  message?: string;
};

/**
 * 主机侧：要一张配对码。**已经有未过期的会原样复用**（同一台机器连点两次不该
 * 得到两个号码 —— 那会让先前念出去的那个失效得更快）。
 *
 * `maxUses` = 这次要请几个人（1~9）。要得比现有码多时会**作废旧码**，返回
 * `replaced: true` —— 界面上得说一句，别让人以为旧码还能用。
 */
export function teamPairing(maxUses = 1, role: TeamRole = "editor"): Promise<TeamPairingInfo> {
  return teamCall<TeamPairingInfo>("/team/pairing", { body: { max_uses: maxUses, role } });
}

/**
 * 主机侧：**只读**查「我手上那张码现在什么状态」。
 *
 * 面板每 2 秒轮询一次用。这条绝不能新建码 —— 否则人还在念，号码就变了。
 * 没有活码时 `code` 是空串（不是报错）。
 */
export function teamPairingStatus(): Promise<TeamPairingInfo> {
  return teamCall<TeamPairingInfo>("/team/pairing");
}

/** 主机侧：立刻作废这张码（念给了错的人时，比干等 2 分钟强）。 */
export function teamRevokePairing(code: string): Promise<TeamPairingInfo> {
  return teamCall<TeamPairingInfo>("/team/pairing/revoke", { body: { code } });
}

// ── 批注（2026-11-04 · 设计评审）───────────────────────────
//
// 这是团队从「互相传文件」变成「一起做设计」的那一层。设计协作的真实循环是
// 做 → 给人看 → 收意见 → 改，以前最后两步只能走微信（截图 + 圈红框）。
//
// 两条约定：
//   · 批注**挂在节点上**（`node_id`），不挂坐标 —— 一改位置就漂走的批注等于没有；
//   · 提批注**不改版本**（不产生新 rev），否则每条意见都会变成一个「版本」，
//     把「谁改了什么」淹掉。

/** 一条批注（与 `team_hub._comment_public` 对齐）。 */
export type TeamComment = {
  id: string;
  project_id: string;
  /** 挂在哪个画布节点上；空串 = 针对整份画布 */
  node_id: string;
  /** 提这条时项目是第几版（0 = 不知道） */
  rev: number;
  author_id: string;
  /** 作者名字（服务端 join 好，前端不用自己查） */
  author: string;
  body: string;
  created_at: number;
  resolved: boolean;
  resolved_at: number;
  resolved_by: string;
  /** 解决者名字；未解决时是空串 */
  resolver: string;
};

/** 列出项目全部批注（未解决 + 已解决都给，前端自己分组）。任何角色都能读。 */
export function teamComments(projectId: string): Promise<TeamComment[]> {
  return teamCall<{ comments: TeamComment[] }>(
    "/team/projects/" + encodeURIComponent(projectId) + "/comments",
  ).then((d) => (Array.isArray(d.comments) ? d.comments : []));
}

/**
 * 提一条批注。**viewer 也能调** —— 这正是「甲方只看不改但必须能说话」的实现。
 */
export function teamAddComment(
  projectId: string, body: string, nodeId = "", rev = 0,
): Promise<TeamComment> {
  return teamCall<{ comment: TeamComment }>(
    "/team/projects/" + encodeURIComponent(projectId) + "/comments",
    { body: { body, node_id: nodeId, rev } },
  ).then((d) => d.comment);
}

/** 标记已解决 / 重新打开。要编辑权（解决是「干活的人」的动作）。 */
export function teamResolveComment(
  projectId: string, commentId: string, resolved = true,
): Promise<TeamComment> {
  return teamCall<{ comment: TeamComment }>(
    "/team/projects/" + encodeURIComponent(projectId) + "/comments/" + encodeURIComponent(commentId),
    { body: { resolved } },
  ).then((d) => d.comment);
}

/** 靠码找主机的探测结果；`address` 为空串 = 没找到（`message` 里有原因）。 */
export type PairProbe = { address: string; name: string; message: string };

/**
 * 同事侧：只凭 6 位码在局域网里找主机地址。
 *
 * 找不到**不抛错**（不是"失败"，是"这片网里没人拿着这张码"），把后端那句能照做
 * 的话原样带回去。只有码格式不对才抛 `bad_code`。
 */
export async function teamFindByCode(code: string): Promise<PairProbe> {
  const c = String(code || "").trim();
  if (!/^\d{4,10}$/.test(c)) {
    throw new TeamError("bad_code", "配对码是 6 位数字，检查一下再输");
  }
  const d = await hostCall<{ server?: DiscoveredServer | null; message?: string }>("/host/team/find-code", {
    method: "POST",
    body: JSON.stringify({ code: c }),
  });
  const s = d.server;
  return {
    address: s?.address ? normalizeAddress(s.address) : "",
    name: String(s?.name || ""),
    message: String(d.message || ""),
  };
}

/** `teamPair` 的结果：凭据 + 「这张码还剩几个名额」（界面据此提示「还能再加 N 人」）。 */
export type PairJoinResult = TeamCred & { remaining: number; max_uses: number; host_name: string };

/**
 * 同事侧：用配对码加入，返回并持久化凭据。
 *
 * `token: ""` 是**故意的**：其它团队端点都要令牌，这一条恰恰是拿码换令牌的那一条。
 * 不显式置空就会把本机残留的旧令牌带上，服务端虽然不看，但"带错东西"这种事
 * 不该只靠对端宽容。
 */
export async function teamPair(code: string, name: string, address?: string): Promise<PairJoinResult> {
  const addr = normalizeAddress(address || teamAddress());
  const c = String(code || "").trim();
  if (!addr) throw new TeamError("no_address", "还没找到主机地址 —— 先用配对码在局域网里找一下");
  if (!c) throw new TeamError("bad_code", "配对码是 6 位数字，别空着");
  const data = await teamCall<{
    member_id: string; name: string; token: string;
    remaining?: number; max_uses?: number; host_name?: string;
  }>("/team/pair", { body: { code: c, name: name || "同事" }, address: addr, token: "" });
  const cred: TeamCred = { address: addr, member_id: data.member_id, name: data.name, token: data.token };
  saveCred(cred);
  return {
    ...cred,
    remaining: Number(data.remaining ?? 0),
    max_uses: Number(data.max_uses ?? 1),
    host_name: String(data.host_name || ""),
  };
}
