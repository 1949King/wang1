/** 提示词库 — GitHub JSON 多源 + 细分类 + 成熟度 */

import {
  categoriesGrouped,
  isMinorUnsafe,
  maturityLabel,
  resolveCategory,
  resolveMaturity,
  type CategoryMeta,
  type Maturity,
} from "./promptTaxonomy";
import { fetchBundledPromptViaHost, fetchJsonViaHost } from "./bridge";

export type { Maturity, CategoryMeta };
export { categoriesGrouped, maturityLabel };

export type PromptSource = {
  id: string;
  name: string;
  url: string;
  /** 本地 bundled 404 时回退的远程 URL */
  fallbackUrl?: string;
  homepage: string;
  enabled: boolean;
  builtIn: boolean;
  /** 默认开启成人内容源时需用户显式打开 */
  adult?: boolean;
};

export type PromptItem = {
  id: string;
  title: string;
  prompt: string;
  description: string;
  coverUrl: string;
  referenceImageUrls: string[];
  tags: string[];
  sourceId: string;
  /** 细分类 id */
  categoryId: string;
  /** 展示用中文分类名 */
  category: string;
  categoryGroup: string;
  maturity: Maturity;
  githubUrl: string;
  favorite?: boolean;
};

export type PromptListResult = {
  items: PromptItem[];
  tags: string[];
  categories: string[];
  categoryIds: string[];
  total: number;
};

const PROMPT_REGISTRY_BASE =
  "https://raw.githubusercontent.com/yukkcat/image-prompts/main/dist/sources";
const SOURCE_STORE_KEY = "shiguang-canvas:prompt_sources_v6";
const CACHE_PREFIX = "shiguang-canvas:prompt_cache_v4:";
const FAV_STORE_KEY = "shiguang-canvas:prompt_favorites_v1";
const CACHE_TTL_MS = 60 * 60 * 1000;

type SourceCache = {
  items: PromptItem[];
  fetchedAt: number;
  lastSuccessAt: string;
  lastError: string;
  signature: string;
};

const memoryCache = new Map<string, SourceCache>();
const loading = new Map<string, Promise<PromptItem[]>>();

function canvasBaseUrl(): string {
  return typeof window !== "undefined" ? new URL("./", window.location.href).href : "./";
}

function registrySource(id: string, name: string, homepage: string, adult = false): PromptSource {
  const base = canvasBaseUrl();
  const remoteUrl = `${PROMPT_REGISTRY_BASE}/${id}.json`;
  return {
    id,
    name,
    url: new URL(`prompts/bundled/${id}.json`, base).href,
    fallbackUrl: remoteUrl,
    homepage,
    enabled: !adult,
    builtIn: true,
    adult,
  };
}

function remoteSource(
  id: string,
  name: string,
  url: string,
  homepage: string,
  opts?: { adult?: boolean; enabled?: boolean },
): PromptSource {
  return {
    id,
    name,
    url,
    homepage,
    enabled: opts?.enabled ?? !opts?.adult,
    builtIn: true,
    adult: opts?.adult,
  };
}

/** 本地打包提示词（public/prompts/）；成人包默认关 */
function localAssetSource(id: string, name: string, file: string, adult = false): PromptSource {
  const base = canvasBaseUrl();
  return {
    id,
    name,
    url: new URL(`prompts/${file}`, base).href,
    homepage: "local://shiguang-prompts",
    enabled: adult ? false : true,
    builtIn: true,
    adult,
  };
}

export const DEFAULT_PROMPT_SOURCES: PromptSource[] = [
  registrySource(
    "banana-prompt-quicker",
    "Banana Prompt Quicker",
    "https://glidea.github.io/banana-prompt-quicker/",
  ),
  registrySource(
    "davidwu-gpt-image2-prompts",
    "DavidWu GPT Image 2",
    "https://github.com/davidwuw0811-boop/awesome-gpt-image2-prompts",
  ),
  registrySource(
    "freestylefly-gpt-image-2",
    "Freestylefly GPT Image 2",
    "https://github.com/freestylefly/awesome-gpt-image-2",
  ),
  registrySource(
    "awesome-gpt-image",
    "Awesome GPT Image",
    "https://github.com/ZeroLu/awesome-gpt-image",
  ),
  registrySource(
    "awesome-gpt4o-image-prompts",
    "Awesome GPT-4o",
    "https://github.com/ImgEdify/Awesome-GPT4o-Image-Prompts",
  ),
  registrySource(
    "youmind-gpt-image-2",
    "YouMind GPT Image 2",
    "https://github.com/YouMind-OpenLab/awesome-gpt-image-2",
  ),
  registrySource(
    "youmind-nano-banana-pro",
    "YouMind Nano Banana Pro",
    "https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts",
  ),
  registrySource(
    "stimqq-gpt-image-2",
    "StimQQ GPT Image 2",
    "https://github.com/stimQQ/gpt-image-2-prompts",
  ),
  registrySource(
    "nexra-ai-image-prompts",
    "NeXra AI Image Prompts",
    "https://github.com/NeXra-AI/awesome-ai-image-prompts",
  ),
  localAssetSource(
    "shiguang-curated",
    "拾光·精选离线包",
    "shiguang-curated.json",
    false,
  ),
  localAssetSource(
    "shiguang-drama-pack",
    "拾光·短剧分镜包",
    "shiguang-drama.json",
    false,
  ),
  localAssetSource(
    "shiguang-genre-pack",
    "拾光·题材设定包",
    "shiguang-genre.json",
    false,
  ),
  localAssetSource(
    "shiguang-avatar-pack",
    "拾光·虚拟形象包",
    "shiguang-avatar.json",
    false,
  ),
  localAssetSource(
    "shiguang-mascot-pack",
    "拾光·狐耳形象包（拾岚）",
    "shiguang-mascot.json",
    false,
  ),
  localAssetSource(
    "shiguang-adult-18plus",
    "拾光·成人向 18+（细分类）",
    "shiguang-adult-18plus.json",
    true,
  ),
];

export function loadPromptSources(): PromptSource[] {
  try {
    const raw = localStorage.getItem(SOURCE_STORE_KEY);
    if (!raw) return DEFAULT_PROMPT_SOURCES.map((s) => ({ ...s }));
    const saved = JSON.parse(raw) as PromptSource[];
    const enabledById = new Map(saved.map((s) => [s.id, s.enabled]));
    const builtIn = DEFAULT_PROMPT_SOURCES.map((s) => ({
      ...s,
      enabled: enabledById.has(s.id) ? !!enabledById.get(s.id) : s.enabled,
    }));
    const builtInIds = new Set(builtIn.map((s) => s.id));
    const custom = saved.filter((s) => !s.builtIn && !builtInIds.has(s.id));
    return [...builtIn, ...custom];
  } catch {
    return DEFAULT_PROMPT_SOURCES.map((s) => ({ ...s }));
  }
}

export function savePromptSources(sources: PromptSource[]) {
  localStorage.setItem(SOURCE_STORE_KEY, JSON.stringify(sources));
}

function favKey(sourceId: string, id: string) {
  return `${sourceId}::${id}`;
}

export function loadFavoriteKeys(): string[] {
  try {
    const raw = localStorage.getItem(FAV_STORE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as string[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveFavoriteKeys(keys: string[]) {
  localStorage.setItem(FAV_STORE_KEY, JSON.stringify(keys));
}

export function isFavorite(sourceId: string, id: string): boolean {
  return loadFavoriteKeys().includes(favKey(sourceId, id));
}

export function toggleFavorite(sourceId: string, id: string): boolean {
  const keys = loadFavoriteKeys();
  const k = favKey(sourceId, id);
  const i = keys.indexOf(k);
  if (i >= 0) {
    keys.splice(i, 1);
    saveFavoriteKeys(keys);
    return false;
  }
  keys.push(k);
  saveFavoriteKeys(keys);
  return true;
}

export function addCustomPromptSource(partial: {
  name: string;
  url: string;
  homepage?: string;
  adult?: boolean;
}): PromptSource[] {
  const sources = loadPromptSources();
  const id = `custom-${Date.now().toString(36)}`;
  const next: PromptSource = {
    id,
    name: partial.name.trim() || id,
    url: partial.url.trim(),
    homepage: (partial.homepage || partial.url).trim(),
    enabled: true,
    builtIn: false,
    adult: !!partial.adult,
  };
  const merged = [...sources, next];
  savePromptSources(merged);
  return merged;
}

function sourceSignature(source: PromptSource): string {
  return `${source.name}|${source.url}|${source.homepage}|${source.adult ? 1 : 0}`;
}

function readCache(sourceId: string): SourceCache | null {
  if (memoryCache.has(sourceId)) return memoryCache.get(sourceId)!;
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + sourceId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SourceCache;
    memoryCache.set(sourceId, parsed);
    return parsed;
  } catch {
    return null;
  }
}

function writeCache(sourceId: string, cache: SourceCache) {
  memoryCache.set(sourceId, cache);
  try {
    localStorage.setItem(CACHE_PREFIX + sourceId, JSON.stringify(cache));
  } catch {
    /* 缓存过大时仅保留内存 */
  }
}

function asArray(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[];
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    for (const key of ["items", "prompts", "data", "list"]) {
      if (Array.isArray(obj[key])) return obj[key] as Record<string, unknown>[];
    }
  }
  throw new Error("根节点不是数组");
}

function pickStr(...vals: unknown[]): string {
  for (const v of vals) {
    const s = String(v ?? "").trim();
    if (s) return s;
  }
  return "";
}

function pickReferenceUrls(rec: Record<string, unknown>): string[] {
  const out: string[] = [];
  const push = (v: unknown) => {
    const s = String(v ?? "").trim();
    if (s) out.push(s);
  };
  for (const key of ["referenceImageUrls", "images", "reference_images", "referenceImages"]) {
    const raw = rec[key];
    if (Array.isArray(raw)) raw.forEach(push);
  }
  return out;
}

function pickCoverUrl(rec: Record<string, unknown>, refs: string[], base: string): string {
  const cover = pickStr(
    rec.coverUrl,
    rec.image_url,
    rec.image,
    rec.cover,
    rec.thumbnail_url,
    rec.thumbnail,
    rec.preview_url,
    rec.previewUrl,
    rec.imageUrl,
    rec.result_image,
    refs[0],
  );
  return cover ? absUrl(base, cover) : "";
}

function pickTags(rec: Record<string, unknown>): string[] {
  const raw = rec.tags ?? rec.seo_keywords;
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    const zh = o.zh;
    const en = o.en;
    return [...(Array.isArray(zh) ? zh : []), ...(Array.isArray(en) ? en : [])].map(String);
  }
  return [];
}

function normalizeRawItems(data: unknown, source: PromptSource): PromptItem[] {
  const rows = asArray(data);
  const seen = new Set<string>();
  const items: PromptItem[] = [];
  for (let i = 0; i < rows.length; i++) {
    const rec = rows[i] || {};
    const title = pickStr(rec.title, rec.title_zh, rec.name_zh, rec.name_en, rec.name, rec.id);
    const prompt = pickStr(rec.prompt, rec.prompt_zh, rec.prompt_en, rec.text, rec.content);
    if (!title || !prompt) continue;

    const blob = `${title}\n${prompt}\n${pickStr(rec.description)}`;
    const tags = pickTags(rec);
    const rawCat = pickStr(rec.category, rec.category_label, rec.category_raw, rec.type);
    const cat = resolveCategory(rawCat, tags, title, prompt);
    const maturity = resolveMaturity(cat, tags, blob);
    if (isMinorUnsafe(blob, maturity)) continue;

    const id = pickStr(rec.id) || `${source.id}-${String(i + 1).padStart(4, "0")}`;
    if (seen.has(id)) continue;
    seen.add(id);

    const refs = pickReferenceUrls(rec);
    const cover = pickCoverUrl(rec, refs, source.url);

    items.push({
      id,
      title,
      prompt,
      description: pickStr(rec.description, rec.desc),
      coverUrl: cover || (refs[0] ? absUrl(source.url, refs[0]) : ""),
      referenceImageUrls: refs.map((u) => absUrl(source.url, u)).filter(Boolean),
      tags,
      sourceId: source.id,
      categoryId: cat.id,
      category: cat.label,
      categoryGroup: cat.group,
      maturity,
      githubUrl: absUrl(source.url, pickStr(rec.sourceUrl, rec.source_url, rec.url)) || source.homepage,
    });
  }
  return items;
}

function absUrl(base: string, path: string): string {
  if (!path) return "";
  if (path.startsWith("data:") || path.startsWith("blob:")) return path;
  try {
    return new URL(path, base).toString();
  } catch {
    return path;
  }
}

function isLocalFastSource(source: PromptSource): boolean {
  const u = source.url || "";
  return (
    source.id.startsWith("shiguang-") ||
    u.includes("/prompts/") ||
    u.startsWith("./") ||
    (typeof window !== "undefined" && u.startsWith(window.location.origin))
  );
}

async function fetchJsonForUrl(url: string, local: boolean): Promise<unknown> {
  if (local) {
    const res = await fetch(url, { cache: "force-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }
  try {
    return await fetchJsonViaHost(url);
  } catch (bridgeErr) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw bridgeErr;
    return res.json();
  }
}

async function fetchSourceJson(source: PromptSource): Promise<PromptItem[]> {
  const urls = [source.url];
  if (source.fallbackUrl && source.fallbackUrl !== source.url) {
    urls.push(source.fallbackUrl);
  }
  let lastErr: unknown = null;
  for (const url of urls) {
    const local = isLocalFastSource({ ...source, url });
    try {
      const data = await fetchJsonForUrl(url, local);
      return normalizeRawItems(data, { ...source, url });
    } catch (e) {
      lastErr = e;
    }
  }
  if (source.builtIn && source.id) {
    try {
      const data = await fetchBundledPromptViaHost(source.id);
      return normalizeRawItems(data, source);
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr || "拉取失败"));
}

async function refreshSource(source: PromptSource): Promise<PromptItem[]> {
  const prev = readCache(source.id);
  try {
    const items = await fetchSourceJson(source);
    const cache: SourceCache = {
      items,
      fetchedAt: Date.now(),
      lastSuccessAt: new Date().toISOString(),
      lastError: "",
      signature: sourceSignature(source),
    };
    writeCache(source.id, cache);
    return items;
  } catch (e) {
    const err = e instanceof Error ? e.message : String(e);
    if (prev?.items.length) {
      writeCache(source.id, { ...prev, lastError: err });
      return prev.items;
    }
    throw new Error(`${source.name}：${err}`);
  }
}

/**
 * network=false：本地包 + 缓存（首屏秒开）
 * network=true / 默认：允许拉远程
 */
async function getSourcePrompts(
  source: PromptSource,
  opts?: { network?: boolean },
): Promise<PromptItem[]> {
  const network = opts?.network !== false;
  const cached = readCache(source.id);
  const sig = sourceSignature(source);
  if (cached && cached.signature === sig && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    if (network && Date.now() - cached.fetchedAt > CACHE_TTL_MS * 0.75) {
      void refreshSource(source).catch(() => undefined);
    }
    return cached.items;
  }
  if (opts?.network === false && !isLocalFastSource(source)) {
    return cached?.items || [];
  }
  if (loading.has(source.id)) return loading.get(source.id)!;
  const p = refreshSource(source).finally(() => loading.delete(source.id));
  loading.set(source.id, p);
  return p;
}

export async function refreshAllPromptSources(sources: PromptSource[]): Promise<{
  ok: number;
  fail: number;
  total: number;
  errors: string[];
}> {
  const enabled = sources.filter((s) => s.enabled && s.url.trim());
  const results: PromiseSettledResult<PromptItem[]>[] = [];
  const chunk = 3;
  for (let i = 0; i < enabled.length; i += chunk) {
    const slice = enabled.slice(i, i + chunk);
    const part = await Promise.allSettled(slice.map((s) => getSourcePrompts(s, { network: true })));
    results.push(...part);
  }
  let ok = 0;
  let fail = 0;
  let total = 0;
  const errors: string[] = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") {
      ok++;
      total += r.value.length;
    } else {
      fail++;
      errors.push(`${enabled[i]?.name}: ${r.reason}`);
    }
  });
  return { ok, fail, total, errors };
}

export async function fetchPromptLibrary(opts: {
  sources: PromptSource[];
  keyword?: string;
  category?: string;
  categoryId?: string;
  tag?: string;
  maturity?: Maturity | "all";
  favoritesOnly?: boolean;
  page?: number;
  pageSize?: number;
  /**
   * true/默认：允许联网
   * false：仅本地+缓存（首屏）
   */
  network?: boolean;
}): Promise<PromptListResult> {
  const keyword = (opts.keyword || "").trim().toLowerCase();
  const category = opts.category || "all";
  const categoryId = opts.categoryId || "all";
  const tag = opts.tag || "";
  const maturity = opts.maturity || "all";
  const favoritesOnly = !!opts.favoritesOnly;
  const network = opts.network !== false;
  const page = Math.max(1, opts.page || 1);
  const pageSize = Math.max(1, Math.min(50, opts.pageSize || 12));
  const favSet = new Set(loadFavoriteKeys());
  const enabled = opts.sources.filter((s) => s.enabled && s.url.trim());
  const batches = await Promise.all(
    enabled.map(async (s) => {
      try {
        return await getSourcePrompts(s, { network });
      } catch {
        return [] as PromptItem[];
      }
    }),
  );
  const all = batches.flat().map((i) => ({
    ...i,
    favorite: favSet.has(favKey(i.sourceId, i.id)),
  }));
  const categoryIds = Array.from(new Set(all.map((i) => i.categoryId)));
  const categories = Array.from(new Set(all.map((i) => i.category)));
  const tags = Array.from(new Set(all.flatMap((i) => i.tags).filter((t) => t && !t.startsWith("@"))))
    .sort((a, b) => a.localeCompare(b, "zh"));

  let filtered = all;
  if (favoritesOnly) filtered = filtered.filter((i) => i.favorite);
  if (maturity && maturity !== "all") {
    filtered = filtered.filter((i) => i.maturity === maturity);
  }
  if (categoryId && categoryId !== "all") {
    filtered = filtered.filter((i) => i.categoryId === categoryId);
  } else if (category && category !== "all") {
    filtered = filtered.filter((i) => i.category === category || i.categoryGroup === category);
  }
  if (tag) filtered = filtered.filter((i) => i.tags.includes(tag));
  if (keyword) {
    filtered = filtered.filter((i) =>
      [i.title, i.prompt, i.description, i.category, i.categoryGroup, ...i.tags]
        .join(" ")
        .toLowerCase()
        .includes(keyword),
    );
  }
  const start = (page - 1) * pageSize;
  return {
    items: filtered.slice(start, start + pageSize),
    tags,
    categories,
    categoryIds,
    total: filtered.length,
  };
}
