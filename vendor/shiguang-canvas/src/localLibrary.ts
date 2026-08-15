/** 本地提示词库 + 资产库（localStorage，离线可用） */

const PROMPTS_KEY = "shiguang-canvas:prompts:v1";
const ASSETS_KEY = "shiguang-canvas:assets:v1";

export type LocalPrompt = {
  id: string;
  title: string;
  text: string;
  tags: string[];
  updatedAt: string;
};

export type LocalAsset = {
  id: string;
  title: string;
  kind: "image" | "video" | "text";
  /** data URL 或桥接 URL */
  url: string;
  prompt?: string;
  createdAt: string;
};

function uid(p: string) {
  return `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function saveJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    console.warn("localLibrary save failed", e);
  }
}

export function listPrompts(): LocalPrompt[] {
  return loadJson<LocalPrompt[]>(PROMPTS_KEY, []).sort((a, b) =>
    b.updatedAt.localeCompare(a.updatedAt),
  );
}

export function upsertPrompt(input: {
  id?: string;
  title: string;
  text: string;
  tags?: string[];
}): LocalPrompt {
  const all = listPrompts();
  const now = new Date().toISOString();
  if (input.id) {
    const next = all.map((p) =>
      p.id === input.id
        ? {
            ...p,
            title: input.title,
            text: input.text,
            tags: input.tags || p.tags,
            updatedAt: now,
          }
        : p,
    );
    saveJson(PROMPTS_KEY, next);
    return next.find((p) => p.id === input.id)!;
  }
  const item: LocalPrompt = {
    id: uid("p"),
    title: input.title || "未命名提示词",
    text: input.text || "",
    tags: input.tags || [],
    updatedAt: now,
  };
  saveJson(PROMPTS_KEY, [item, ...all]);
  return item;
}

export function deletePrompt(id: string) {
  saveJson(
    PROMPTS_KEY,
    listPrompts().filter((p) => p.id !== id),
  );
}

/** 从社区库条目写入本地自建库（去重：同标题+正文则更新） */
export function upsertPromptFromCommunity(input: {
  title: string;
  prompt: string;
  tags?: string[];
}): LocalPrompt {
  const all = listPrompts();
  const existing = all.find((p) => p.title === input.title && p.text === input.prompt);
  return upsertPrompt({
    id: existing?.id,
    title: input.title,
    text: input.prompt,
    tags: input.tags || ["社区库"],
  });
}

export function listAssets(): LocalAsset[] {
  return loadJson<LocalAsset[]>(ASSETS_KEY, []).sort((a, b) =>
    b.createdAt.localeCompare(a.createdAt),
  );
}

export function addAsset(input: {
  title: string;
  kind: LocalAsset["kind"];
  url: string;
  prompt?: string;
}): LocalAsset {
  const item: LocalAsset = {
    id: uid("asset"),
    title: input.title || "未命名资产",
    kind: input.kind,
    url: input.url,
    prompt: input.prompt,
    createdAt: new Date().toISOString(),
  };
  const all = listAssets();
  // 控制体积：最多保留 80 条
  saveJson(ASSETS_KEY, [item, ...all].slice(0, 80));
  return item;
}

export function deleteAsset(id: string) {
  saveJson(
    ASSETS_KEY,
    listAssets().filter((a) => a.id !== id),
  );
}

export function showcaseFromLibrary(limit = 6): {
  id: string;
  title: string;
  prompt: string;
  coverUrl?: string;
  tags?: string[];
}[] {
  const assets = listAssets().filter((a) => a.kind === "image" && a.url);
  const prompts = listPrompts();
  const fromAssets = assets.slice(0, limit).map((a) => ({
    id: a.id,
    title: a.title,
    prompt: a.prompt || "",
    coverUrl: a.url,
    tags: [a.kind],
  }));
  if (fromAssets.length >= 2) return fromAssets;
  const fromPrompts = prompts.slice(0, limit - fromAssets.length).map((p) => ({
    id: p.id,
    title: p.title,
    prompt: p.text,
    tags: p.tags.length ? p.tags : ["提示词"],
  }));
  return [...fromAssets, ...fromPrompts];
}
