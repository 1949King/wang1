/**
 * teamAssets.ts — 团队同步里的**媒体层**：本机文件 ↔ 团队附件库（2026-11-02）
 *
 * ## 为什么需要这一层
 *
 * 画布 bundle 是 JSON，媒体只有两条路能进去，两条都不通：
 *   - base64（`data:`）：1 张 512² 图约 300~500KB，200 张就撞 `MAX_BUNDLE_BYTES`
 *     （100MB）⇒ 同事收到「工程过大」；
 *   - 本地路径（`/inbox_file/x.mp4`）：**同事机上根本不存在这个文件** ⇒ 打开是 404。
 *
 * 所以成片视频、生成图、音频统一走团队附件库（按 sha256 存字节），bundle 里
 * 只换成「指向附件的 URL」。**内容哈希做键**，同一份素材传两遍不会占两份盘。
 *
 * ## 三条纪律
 *
 * 1. **令牌绝不进 bundle**：push 前 `stripAssetTokens()` 剥掉 `?token=`。
 *    否则同事的令牌会被写进服务器的 bundle JSON，谁都能读出来。
 * 2. **渲染层零侵入**：在 `loadProjectBundle` 之前把 URL 换好，所有节点组件
 *    （`CanvasShell` / `codeVideoNode` / 时间线预览…）都不用改。
 * 3. **失败如实报**：某个文件传不上去（太大 / 404 / 网络断）就记进 `failed`，
 *    由调用方在界面上说清楚是哪一条，**绝不静默跳过让同事看空白**。
 */
import { teamAssetUrl, teamPoster, teamUploadAsset, type TeamAssetKind } from "./teamClient";

/** 一个待上传的媒体引用。 */
export type MediaRef = {
  /** bundle 里出现的原始 URL（本地路径 / data: / 已是团队 URL） */
  url: string;
  kind: TeamAssetKind;
  /** 上传时用的文件名（带正确后缀，后端据此定 mime 与扩展名） */
  name: string;
  /** 归属提示（`镜 03`）：附件列表靠它说清「这条是哪个镜的产出」 */
  owner?: string;
};

/** 判定「值得上传」的 data: 体积门槛：小图标内联即可，不必为它跑一次 HTTP。 */
export const DATA_UPLOAD_THRESHOLD = 256 * 1024;

const LOCAL_FILE_RE = /^(?:https?:\/\/127\.0\.0\.1(:\d+)?)?\/(?:inbox_file|editor_file|editor_outbox)\//i;
const TEAM_ASSET_RE = /\/team\/projects\/([^/?#]+)\/assets\/([a-f0-9]{64})(\?[^"'\s]*)?/i;
const TEAM_ASSET_TOKEN_RE = /(\/team\/projects\/[^/?#]+\/assets\/[a-f0-9]{64})\?token=[^"'\s&]*/g;

/** 媒体字段名 → 类型（没有对应项就按后缀猜）。 */
const KEY_KINDS: Record<string, TeamAssetKind> = {
  videoUrl: "video",
  refVideoUrl: "video",
  imageUrl: "image",
  firstFrameUrl: "image",
  lastFrameUrl: "image",
  posterUrl: "image",
  sheetUrl: "image",
  audioUrl: "audio",
};

const EXT_KINDS: Record<string, TeamAssetKind> = {
  mp4: "video", webm: "video", mov: "video", mkv: "video", m4v: "video",
  png: "image", jpg: "image", jpeg: "image", webp: "image", gif: "image", bmp: "image",
  mp3: "audio", wav: "audio", m4a: "audio", flac: "audio", ogg: "audio", aac: "audio",
  srt: "text", txt: "text", md: "text", json: "text",
};

/** MIME 子类型 → 扩展名。**子类型不等于后缀**：`audio/mpeg` 是 mp3，`video/quicktime` 是 mov。 */
const MIME_EXT: Record<string, string> = {
  mpeg: "mp3", mp3: "mp3", "x-wav": "wav", wav: "wav", "x-m4a": "m4a", m4a: "m4a",
  "x-flac": "flac", flac: "flac", ogg: "ogg", aac: "aac",
  mp4: "mp4", quicktime: "mov", webm: "webm", "x-matroska": "mkv",
  jpeg: "jpg", jpg: "jpg", png: "png", webp: "webp", gif: "gif", bmp: "bmp", svg: "svg",
  plain: "txt", markdown: "md", json: "json",
};

/** 从 URL 取扩展名（无扩展名返回空串）。 */
export function extOf(url: string): string {
  const s = String(url || "");
  if (s.startsWith("data:")) {
    const m = /^data:([^;,]*)\//i.exec(s);
    const sub = (m?.[1] || "").toLowerCase().trim();
    if (MIME_EXT[sub]) return MIME_EXT[sub];
    const after = /^data:[^;,]*\/([a-z0-9.+-]+)/i.exec(s)?.[1]?.toLowerCase() || "";
    return MIME_EXT[after] || after;
  }
  const clean = s.split(/[?#]/)[0];
  const base = clean.slice(clean.lastIndexOf("/") + 1);
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
}

/** 按字段名 + 扩展名判定媒体类型；判不出就是 `file`。 */
export function kindOf(url: string, key = ""): TeamAssetKind {
  if (KEY_KINDS[key]) return KEY_KINDS[key];
  return EXT_KINDS[extOf(url)] || "file";
}

/**
 * 这个 URL 要不要上传？
 *
 * | 情形 | 结论 | 原因 |
 * |---|---|---|
 * | `data:` 且 ≤ 256KB | 不上传 | 内联已够，为小图跑 HTTP 不值 |
 * | `data:` 且 > 256KB | 上传 | 否则攒够 200 张就撞 bundle 上限 |
 * | `/inbox_file/…`（含 127.0.0.1 绝对地址） | 上传 | 同事机上没有这个文件 |
 * | `blob:` | 不上传 | 仅本会话内存，传出去也对不上 |
 * | 已是团队附件 URL / 远程 http | 不上传 | 同事本来就能访问 |
 */
export function shouldUpload(url: string): boolean {
  const s = String(url || "");
  if (!s) return false;
  if (s.startsWith("blob:")) return false;
  if (s.startsWith("data:")) return s.length > DATA_UPLOAD_THRESHOLD;
  if (LOCAL_FILE_RE.test(s)) return true;
  return false;
}

/** 上传时用的文件名：本地路径取 basename；data URL 现造一个。 */
export function nameFor(url: string, key = ""): string {
  const s = String(url || "");
  const kind = kindOf(s, key);
  const ext = extOf(s) || (kind === "video" ? "mp4" : kind === "audio" ? "mp3" : "png");
  if (s.startsWith("data:")) return `${key || "media"}.${ext}`;
  const clean = s.split(/[?#]/)[0];
  const tail = clean.slice(clean.lastIndexOf("/") + 1);
  let base = tail;
  try {
    base = decodeURIComponent(tail);      // 中文名在 URL 里是 percent-encoded
  } catch {
    base = tail;                          // 畸形 %序列：原样用，别让整次上传炸掉
  }
  return base || `${key || "media"}.${ext}`;
}

/**
 * 深度遍历，把每个**字符串叶子**过一遍 `fn`（返回同位置的新值）。
 *
 * 只对字符串做前缀/正则判断，普通提示词文本会立刻返回原值 —— 一个几百节点的
 * 画布 + 上千条时间线 clip 也在几十毫秒量级。`depth` 上限防环。
 */
export function mapStrings<T>(value: T, fn: (s: string) => string, depth = 0): T {
  if (depth > 14) return value;
  if (typeof value === "string") return fn(value) as unknown as T;
  if (Array.isArray(value)) return value.map((v) => mapStrings(v, fn, depth + 1)) as unknown as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      // 字段名要参与判定（imageUrl / videoUrl 决定 kind），这里用前缀标记带下去
      out[k] = typeof v === "string" ? fn(v) : mapStrings(v, fn, depth + 1);
    }
    return out as unknown as T;
  }
  return value;
}

/**
 * 从节点 / 片段对象上读一个「人话名字」当归属（`镜 03`、`剧本`）。
 *
 * 只认 `title` / `label`（以及节点 `data` 里的 `name`）：**不认顶层的 `name`**，
 * 时间线片段那个 `name` 通常是文件名（`成片.mp4`），照抄下来只是把附件名
 * 重复一遍，对「这是哪个镜」毫无帮助。
 */
function labelOf(obj: Record<string, unknown>): string {
  for (const k of ["title", "label"]) {
    const v = obj[k];
    if (typeof v === "string" && v.trim()) return v.trim().slice(0, 40);
  }
  const data = obj.data;
  if (data && typeof data === "object") {
    for (const k of ["title", "label", "name"]) {
      const v = (data as Record<string, unknown>)[k];
      if (typeof v === "string" && v.trim()) return v.trim().slice(0, 40);
    }
  }
  return "";
}

/**
 * 收集 bundle 里所有**需要上传**的媒体引用（已去重）。
 *
 * 覆盖范围刻意大于节点字段白名单：`timeline.clips` 里的片段、`stage3d` 里的贴图
 * 都会扫到 —— 成片视频正是挂在时间线上的，只认节点字段会漏掉最重要的那一条。
 *
 * 每个引用顺手带上**归属**（最近的 title/label 祖先）：同一份素材被多个节点引用时
 * 保留第一个有归属的，不让后来的空值把有用的信息盖掉。
 */
export function collectMediaRefs(bundle: unknown): MediaRef[] {
  const index = new Map<string, number>();
  const out: MediaRef[] = [];
  const visit = (s: string, key: string, owner: string) => {
    if (!shouldUpload(s)) return;
    const hit = index.get(s);
    if (hit !== undefined) {
      if (!out[hit].owner && owner) out[hit].owner = owner;
      return;
    }
    index.set(s, out.length);
    out.push({ url: s, kind: kindOf(s, key), name: nameFor(s, key), owner });
  };
  const walk = (v: unknown, depth = 0, key = "", owner = "") => {
    if (depth > 14) return;
    if (typeof v === "string") {
      visit(v, key, owner);
      return;
    }
    if (Array.isArray(v)) {
      v.forEach((x) => walk(x, depth + 1, key, owner));
      return;
    }
    if (v && typeof v === "object") {
      const obj = v as Record<string, unknown>;
      const own = labelOf(obj) || owner;
      for (const [k, x] of Object.entries(obj)) walk(x, depth + 1, k, own);
    }
  };
  walk(bundle);
  return out;
}

export type UploadResult = {
  /** 原始 URL → sha256（不含任何 host/token，可安全写进 bundle） */
  map: Record<string, string>;
  uploaded: number;
  /** 已经传过的（sha 命中，后端秒回） */
  reused: number;
  /** 顺手生成并上传的封面张数（视频才有） */
  posters: number;
  failed: Array<{ url: string; name: string; why: string }>;
};

async function fetchBlob(url: string): Promise<Blob> {
  if (url.startsWith("data:")) {
    const res = await fetch(url);
    return await res.blob();
  }
  // /inbox_file/… 是画布同源路径，直接 fetch 即可拿字节（不需要 host token）
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new Error(`取不到文件（HTTP ${res.status}）`);
  return await res.blob();
}

/** 只有画布给得出本机路径的素材才能抽帧（`data:` / `blob:` 后端读不到）。 */
const POSTER_SRC_RE = /^(?:https?:\/\/127\.0\.0\.1(?::\d+)?)?\/(?:inbox_file|editor_file)\//i;

/**
 * 给视频上传一张封面，返回封面附件的 sha256（失败回空串）。
 *
 * 顺序刻意是**先封面后本体**：视频那一行要带 `poster=<sha>` 才能让同事在列表里
 * 一眼看到是哪条；等视频传完再补封面，就得再发一次「更新」请求。
 *
 * 抽帧在本机后端做（浏览器没有 H.264 解码器，见 `teamPoster` 注释）；封面这份
 * 字节也照常进附件库，否则同事那边拿不到这张图。
 * 封面行会被 Hub 的 `list_assets` 过滤掉（谁的 sha 被别人 `poster` 引用就不列），
 * 所以列表不会变成「成片.mp4 / 成片.mp4.jpg」两倍长。
 */
async function uploadPosterFor(projectId: string, ref: MediaRef): Promise<string> {
  if (!POSTER_SRC_RE.test(ref.url)) return "";
  const dataUrl = await teamPoster(ref.url);
  if (!dataUrl) return "";
  try {
    const blob = await fetchBlob(dataUrl);
    const res = await teamUploadAsset(
      projectId, blob, `${ref.name.slice(0, 100)}.jpg`, "image", undefined, { owner: ref.owner },
    );
    return res.sha256;
  } catch {
    return "";      // 封面失败绝不能连累视频本体
  }
}

/**
 * 逐个上传。**一个失败不中断其余** —— 一条 200MB 成片失败不该让十张分镜图也传不上去；
 * 失败的逐条记进 `failed`，由调用方在面板上如实列出。
 *
 * `onBytes` 透传单文件的字节进度（大文件没有百分比，使用者会以为界面卡死）。
 */
export async function uploadMediaRefs(
  projectId: string,
  refs: MediaRef[],
  onStep?: (done: number, total: number, ref: MediaRef, phase: "upload" | "done" | "fail") => void,
  onBytes?: (loaded: number, total: number, ref: MediaRef) => void,
): Promise<UploadResult> {
  const map: Record<string, string> = {};
  const failed: UploadResult["failed"] = [];
  let uploaded = 0;
  let reused = 0;
  let posters = 0;
  for (let i = 0; i < refs.length; i++) {
    const ref = refs[i];
    onStep?.(i, refs.length, ref, "upload");
    try {
      const blob = await fetchBlob(ref.url);
      let poster = "";
      if (ref.kind === "video") {
        poster = await uploadPosterFor(projectId, ref);
        if (poster) posters++;
      }
      const res = await teamUploadAsset(
        projectId,
        blob,
        ref.name,
        ref.kind,
        onBytes ? (loaded, total) => onBytes(loaded, total, ref) : undefined,
        { owner: ref.owner, poster },
      );
      map[ref.url] = res.sha256;
      uploaded++;
      onStep?.(i + 1, refs.length, ref, "done");
    } catch (e) {
      const why = e instanceof Error ? e.message : String(e);
      // 内容哈希已存在时后端也回 200，所以走不到这里；这是真的失败
      if (/已存在|same/.test(why)) reused++;
      else failed.push({ url: ref.url, name: ref.name, why });
      onStep?.(i + 1, refs.length, ref, "fail");
    }
  }
  return { map, uploaded, reused, posters, failed };
}

/** 把 `map` 里的原始 URL 换成团队附件 URL（**不带 token**，push 用）。 */
export function applyMediaIndex<T>(bundle: T, projectId: string, map: Record<string, string>): T {
  const keys = Object.keys(map);
  if (!keys.length) return bundle;
  return mapStrings(bundle, (s) => {
    const sha = map[s];
    if (!sha) return s;
    return teamAssetUrl(projectId, sha) || s;
  });
}

/** push 前必做：剥掉 URL 里的 `?token=`（令牌只能存在本机）。 */
export function stripAssetTokens<T>(bundle: T): T {
  // 🔴 别写成「先用带 g 的正则 test 再 replace」—— test 会推进 lastIndex，
  // replace 就从中间开始匹配，得到半截 URL。直接 replace 再比对结果最安全
  // （String.replace 带 g 时会自己把 lastIndex 归零）。
  return mapStrings(bundle, (s) => {
    const out = s.replace(TEAM_ASSET_TOKEN_RE, "$1");
    return out === s ? s : out;
  });
}

/**
 * pull 后必做：把附件 URL 的 host 换成**当前**团队地址并注入令牌。
 *
 * 为什么连 host 一起换：服务器换了 IP（DHCP 续租、换 Wi-Fi）后 bundle 里存的旧
 * 地址就全废了；但 `/team/projects/<pid>/assets/<sha>` 这段是稳定的，换掉前缀即可复活。
 */
export function rebaseAssetUrls<T>(bundle: T): T {
  return mapStrings(bundle, (s) => {
    const m = TEAM_ASSET_RE.exec(s);
    if (!m) return s;
    const fresh = teamAssetUrl(m[1], m[2]);
    return fresh || s;
  });
}

/** 这条 URL 是否已经是团队附件（面板据此显示「已同步」）。 */
export function isTeamAsset(url: string): boolean {
  return TEAM_ASSET_RE.test(String(url || ""));
}

// ── 媒体索引缓存（2026-11-02 · 第二刀）──────────────────
//
// ## 为什么必须缓存
//
// 首版每次「上传到此」都把**全部**媒体重新 fetch + POST 一遍。服务端按 sha 去重、
// 不会重复占盘，但一条 200MB 成片 + 40 张图**每次都要在局域网重走一遍**，
// 用户点第二次上传会以为卡死。缓存「原始 URL → sha」，第二次只传新增的。
//
// ## 为什么还要「存活过滤」
//
// 缓存里的 sha 可能已经被人从服务器删掉（面板 ⑤ 有删除按钮）。直接复用会写进
// 一批死链接，而前端的 `shouldUpload` 又认为「已是团队 URL 不用传」⇒ 同事打开是
// 404 且没人报错。所以每次 push 前先拉一次服务端附件列表做交集。

const LS_MEDIA_PREFIX = "shiguang:team:media:";

/** 读某个项目的媒体索引缓存（读不到/坏了都回空对象，不抛）。 */
export function readMediaCache(projectId: string): Record<string, string> {
  if (!projectId) return {};
  try {
    const raw = window.localStorage.getItem(LS_MEDIA_PREFIX + projectId);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof k === "string" && typeof v === "string" && /^[a-f0-9]{64}$/i.test(v)) out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

/** 写缓存。**写失败不报错**：够不上缓存只是下次多传一遍，不该拦住上传本身。 */
export function writeMediaCache(projectId: string, map: Record<string, string>): void {
  if (!projectId) return;
  try {
    window.localStorage.setItem(LS_MEDIA_PREFIX + projectId, JSON.stringify(map));
  } catch (e) {
    try {
      console.warn("[team] 媒体索引缓存写盘失败（localStorage 满或禁用）:", e);
    } catch {
      /* console 不可用时无需处理 */
    }
  }
}

/**
 * 只保留服务端**确实还有**的 sha。
 *
 * 缓存命中的前提是「这个文件还在服务器上」；用户点了 ⑤ 段的删除之后，
 * 靠这个函数把死条目剔掉，否则会写出一批 404 链接且界面上看不出来。
 */
export function pruneMediaCache(
  cached: Record<string, string>,
  alive: Set<string>,
): { kept: Record<string, string>; dropped: number } {
  const kept: Record<string, string> = {};
  let dropped = 0;
  for (const [url, sha] of Object.entries(cached)) {
    if (alive.has(sha)) kept[url] = sha;
    else dropped++;
  }
  return { kept, dropped };
}
