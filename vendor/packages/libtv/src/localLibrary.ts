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

// ════════════════════════════════════════════════════════════════════════
//  资产自动分类（类型 + 语义细分，确定性规则、零随机）
// ════════════════════════════════════════════════════════════════════════

export type AssetTypeKind = LocalAsset["kind"]; // "image" | "video" | "text"

export const ASSET_TYPE_LABEL: Record<AssetTypeKind, string> = {
  image: "图片",
  video: "视频",
  text: "文本",
};

export type AssetSemantic = "character" | "scene" | "storyboard" | "cover" | "other";

export const ASSET_SEMANTIC_LABEL: Record<AssetSemantic, string> = {
  character: "角色",
  scene: "场景",
  storyboard: "分镜",
  cover: "封面",
  other: "未分类",
};

/** 语义分类规则：按优先级命中（角色 > 场景 > 分镜 > 封面），
 *  文本匹配 title + prompt，规则可读、可预期，无随机。 */
const SEMANTIC_RULES: { id: AssetSemantic; re: RegExp }[] = [
  { id: "character", re: /角色|人物|人像|肖像|character|portrait|person|面部|脸部/i },
  { id: "scene", re: /场景|环境|背景|风景|scene|environment|landscape|室内|室外/i },
  { id: "storyboard", re: /分镜|storyboard|shot|镜头|运镜|中景|全景|特写|近景|镜\s*\d/i },
  { id: "cover", re: /封面|海报|cover|poster|标题卡|片头/i },
];

export function semanticOfAsset(a: LocalAsset): AssetSemantic {
  const text = `${a.title || ""} ${a.prompt || ""}`;
  for (const r of SEMANTIC_RULES) if (r.re.test(text)) return r.id;
  return "other";
}

export type AssetFolder = {
  /** 叶子文件夹唯一键，如 "image/character"；文本为 "text" */
  id: string;
  kind: AssetTypeKind;
  /** 文本类型没有语义层，为 null */
  semantic: AssetSemantic | null;
  label: string;
  count: number;
  items: LocalAsset[];
};

export type AssetTypeFolder = {
  kind: AssetTypeKind;
  label: string;
  count: number;
};

const SEMANTIC_ORDER: AssetSemantic[] = ["character", "scene", "storyboard", "cover", "other"];

/** 构建资产树：类型 → 语义（文本仅一层）。只返回 count > 0 的文件夹，避免空文件夹。 */
export function buildAssetTree(assets: LocalAsset[]): {
  types: AssetTypeFolder[];
  folders: AssetFolder[];
  foldersOfType: (kind: AssetTypeKind) => AssetFolder[];
} {
  const byKind: Record<AssetTypeKind, LocalAsset[]> = { image: [], video: [], text: [] };
  for (const a of assets) byKind[a.kind].push(a);

  const folders: AssetFolder[] = [];
  for (const kind of ["image", "video", "text"] as AssetTypeKind[]) {
    const list = byKind[kind];
    if (kind === "text") {
      if (list.length) {
        folders.push({ id: "text", kind: "text", semantic: null, label: "文本", count: list.length, items: list });
      }
      continue;
    }
    const semMap = new Map<AssetSemantic, LocalAsset[]>();
    for (const a of list) {
      const s = semanticOfAsset(a);
      if (!semMap.has(s)) semMap.set(s, []);
      semMap.get(s)!.push(a);
    }
    for (const s of SEMANTIC_ORDER) {
      const items = semMap.get(s) || [];
      if (items.length) {
        folders.push({
          id: `${kind}/${s}`,
          kind,
          semantic: s,
          label: ASSET_SEMANTIC_LABEL[s],
          count: items.length,
          items,
        });
      }
    }
  }

  const types: AssetTypeFolder[] = (["image", "video", "text"] as AssetTypeKind[])
    .map((kind) => ({ kind, label: ASSET_TYPE_LABEL[kind], count: byKind[kind].length }))
    .filter((t) => t.count > 0);

  return {
    types,
    folders,
    foldersOfType: (kind: AssetTypeKind) => folders.filter((f) => f.kind === kind),
  };
}
