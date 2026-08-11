/** 与拾光剪影 canvas_bridge (:18765) 对接 */

export const BRIDGE = "http://127.0.0.1:18765";
const CONFIG_KEY = "infinite-canvas:ai_config_store";

export type BridgePrefs = {
  character_id?: string;
  character_name?: string;
  character_prompt?: string;
  enable_interpolation?: boolean;
  active_provider?: string;
  active_provider_label?: string;
};

export type ImageModelOption = {
  channel_id: string;
  channel_name: string;
  model: string;
  label: string;
};

function tokenFromQuery(): string {
  try {
    return new URLSearchParams(location.search).get("token") || "";
  } catch {
    return "";
  }
}

export function bridgeToken(): string {
  return (
    (window as any).__SHIGUANG_BRIDGE_TOKEN ||
    localStorage.getItem("__shiguang_bridge_token") ||
    tokenFromQuery() ||
    ""
  );
}

function authHeaders(json = false): HeadersInit {
  const h: Record<string, string> = {
    "X-Shiguang-Token": bridgeToken(),
  };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

export async function fetchPrefs(): Promise<BridgePrefs> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/prefs?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return {};
    return (await res.json()) as BridgePrefs;
  } catch {
    return {};
  }
}

export async function listImageModels(): Promise<{
  models: ImageModelOption[];
  default: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/image-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok) return { models: [], default: "" };
    return {
      models: (data.models || []) as ImageModelOption[],
      default: String(data.default || ""),
    };
  } catch {
    return { models: [], default: "" };
  }
}

export async function generateImageViaHost(opts: {
  prompt: string;
  model?: string;
  channel_id?: string;
  size?: string;
  reference_image?: string;
  strength?: number;
}): Promise<{
  ok: boolean;
  message?: string;
  image_data_url?: string;
  image_url?: string;
  model?: string;
  mode?: string;
  img2img_fallback?: boolean;
  fallback_placeholder?: boolean;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/generate-image?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        prompt: opts.prompt,
        model: opts.model || "",
        channel_id: opts.channel_id || "",
        size: opts.size || "1024x576",
        reference_image: opts.reference_image || "",
        strength: opts.strength ?? 0.65,
      }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, message: `HTTP ${res.status}`, fallback_placeholder: true };
  }
}

/** 展开 @角色 / @角色名；并可选自动注入当前角色一致性描述 */
export function expandCharacterMentions(
  text: string,
  prefs: BridgePrefs,
  opts?: { autoInject?: boolean },
): string {
  const name = (prefs.character_name || "").trim();
  const cp = (prefs.character_prompt || "").trim();
  const replacement = cp || (name ? `角色「${name}」` : "");
  let out = text || "";
  if (name && replacement) {
    const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    out = out.replace(new RegExp(`@${esc}`, "g"), replacement);
  }
  out = out.replace(/@角色/g, replacement || "@角色");
  if (opts?.autoInject && replacement && !out.includes(replacement) && !out.includes(`角色「${name}」`)) {
    out = `${replacement}；${out}`;
  }
  return out;
}

export type CanvasAssetRef = {
  id: string;
  title: string;
  kind: string;
  imageUrl?: string;
  promptSnippet?: string;
};

/** 即梦式 @素材 / @节点标题：展开文案，并返回优先参考图 */
export function expandAssetMentions(
  text: string,
  assets: CanvasAssetRef[],
): { text: string; referenceImage?: string } {
  let out = text || "";
  let referenceImage: string | undefined;
  const withImage = assets.filter((a) => a.imageUrl);
  if (/@素材/.test(out) && withImage.length) {
    const a = withImage[withImage.length - 1];
    const rep = a.promptSnippet || `参考素材「${a.title}」`;
    out = out.replace(/@素材/g, rep);
    referenceImage = a.imageUrl;
  }
  for (const a of assets) {
    const title = (a.title || "").trim();
    if (!title) continue;
    const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`@${esc}`, "g");
    if (re.test(out)) {
      const rep = a.promptSnippet || `参考「${title}」构图与风格`;
      out = out.replace(re, rep);
      if (a.imageUrl) referenceImage = a.imageUrl;
    }
  }
  return { text: out, referenceImage };
}

/** 汇聚指入当前节点的上游脚本/提示词/镜头描述（Comfy 向） */
export function collectUpstreamContext(
  nodeId: string,
  nodes: { id: string; data: any }[],
  edges: { source: string; target: string }[],
): string {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parts: string[] = [];
  const seen = new Set<string>();
  const queue = edges.filter((e) => e.target === nodeId).map((e) => e.source);
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    const n = byId.get(id);
    if (!n) continue;
    const d = n.data || {};
    if (d.kind === "script" && d.content) parts.push(`剧本:${String(d.content).slice(0, 200)}`);
    if (d.kind === "prompt" && d.text) parts.push(`风格:${String(d.text).slice(0, 160)}`);
    if (d.kind === "shot" && d.prompt) parts.push(`上游镜头:${String(d.prompt).slice(0, 120)}`);
    for (const e of edges) {
      if (e.target === id) queue.push(e.source);
    }
  }
  return parts.join("；");
}

export type StoryboardShot = {
  id?: number;
  duration?: number;
  shot?: string;
  description?: string;
  dialogue?: string;
};

/** 一键拉片：剧本 → 分镜表（宿主 LLM，失败用启发式） */
export async function breakdownStoryboard(script: string): Promise<{
  ok: boolean;
  shots: StoryboardShot[];
  fallback?: boolean;
  message?: string;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/storyboard-breakdown?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ script }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, shots: [], message: `HTTP ${res.status}` };
  }
}

export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || ""));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

export async function syncModelPool(): Promise<string> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/ai-config-patch?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok || !data.channels) return "同步失败：桥未就绪或无渠道";
    const raw = localStorage.getItem(CONFIG_KEY);
    const store = raw
      ? JSON.parse(raw)
      : { state: { config: { channels: [] } }, version: 0 };
    if (!store.state) store.state = {};
    if (!store.state.config) store.state.config = {};
    let channels = Array.isArray(store.state.config.channels)
      ? store.state.config.channels.slice()
      : [];
    data.channels.forEach((ch: any) => {
      const idx = channels.findIndex((c: any) => c && c.id === ch.id);
      if (idx >= 0) channels[idx] = Object.assign({}, channels[idx], ch);
      else channels.push(ch);
    });
    store.state.config.channels = channels;
    store.state.config.channelMode = "local";
    if (data.defaults) {
      Object.keys(data.defaults).forEach((k) => {
        if (data.defaults[k]) store.state.config[k] = data.defaults[k];
      });
    }
    localStorage.setItem(CONFIG_KEY, JSON.stringify(store));
    return `已同步 ${data.channels.length} 个渠道到本地`;
  } catch (e) {
    return `同步异常: ${e}`;
  }
}

export function installInjectScript() {
  if (document.getElementById("shiguang-bridge-inject")) return;
  const s = document.createElement("script");
  s.id = "shiguang-bridge-inject";
  s.src = `${BRIDGE}/inject.js?t=${Date.now()}`;
  s.async = true;
  document.documentElement.appendChild(s);
}

export async function sendBlobToEditor(
  blob: Blob,
  filename: string,
  prefs: BridgePrefs,
  opts?: { duration_sec?: number; title?: string },
): Promise<string> {
  const q = new URLSearchParams({
    filename,
    title: opts?.title || filename,
    send_to_editor: "1",
    enable_interpolation: prefs.enable_interpolation ? "1" : "0",
    character_id: prefs.character_id || "",
    character_name: prefs.character_name || "",
  });
  if (opts?.duration_sec && opts.duration_sec > 0) {
    q.set("duration_sec", String(opts.duration_sec));
  }
  const res = await fetch(`${BRIDGE}/ingest?${q}`, {
    method: "POST",
    body: blob,
    headers: { "Content-Type": blob.type || "application/octet-stream" },
  });
  const data = await res.json();
  return data.message || (data.success ? "已发送到剪辑" : "发送失败");
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return await res.blob();
}

export function placeholderImageDataUrl(prompt: string, w = 512, h = 288): string {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, "#1e3a5f");
  g.addColorStop(1, "#0f766e");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = "bold 18px sans-serif";
  ctx.fillText("拾光导演台 · 占位图", 24, 40);
  ctx.font = "14px sans-serif";
  const lines = wrapText(prompt || "(空提示词)", 28);
  lines.slice(0, 8).forEach((line, i) => ctx.fillText(line, 24, 80 + i * 22));
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "11px sans-serif";
  ctx.fillText("同步模型池并配置 AIGC Key 后可接真实生图", 24, h - 24);
  return c.toDataURL("image/png");
}

function wrapText(text: string, maxChars: number): string[] {
  const out: string[] = [];
  let cur = "";
  for (const ch of text) {
    cur += ch;
    if (cur.length >= maxChars) {
      out.push(cur);
      cur = "";
    }
  }
  if (cur) out.push(cur);
  return out;
}
