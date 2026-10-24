/** 插件加载器 — URL fetch → Blob → import() → activate/deactivate
 *
 * 加载流程（installPluginFromUrl）：
 *   fetch(url) → evaluatePluginSource → activatePlugin → usePluginStore.upsert
 *
 * 启动流程（ensurePluginsLoaded）：
 *   rehydrate store → loadLocalPlugins → 并行 activate 所有 enabled 插件
 */
import { registerNodeDefinitions, unregisterPluginNodes } from "./node-registry";
import { getPluginRuntime } from "./plugin-runtime";
import { normalizeInfinitePlugin } from "./infinite-compat";
import { usePluginStore, type InstalledPlugin } from "./plugin-store";
import type { CanvasPlugin } from "./types";

const cleanupFns = new Map<string, () => void>();

/** 从 JS source 字符串动态 evaluate 出 CanvasPlugin */
async function evaluatePluginSource(source: string): Promise<CanvasPlugin> {
  const blob = new Blob([source], { type: "text/javascript" });
  const url = URL.createObjectURL(blob);
  try {
    // @vite-ignore 告诉 vite 不要尝试静态分析这个动态 import
    const mod = (await import(/* @vite-ignore */ url)) as { default?: unknown; plugin?: unknown };
    const exported = mod.default ?? mod.plugin;
    return normalizeInfinitePlugin(exported);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** 激活：注册节点 + 注入 CSS + 调 setup */
export function activatePlugin(plugin: CanvasPlugin) {
  // 先 deactivate 旧版本（防止 bundle 被覆盖更新时节点重复注册）
  deactivatePlugin(plugin.id);
  registerNodeDefinitions(plugin.nodes, plugin.id);
  const runtime = getPluginRuntime();
  const disposers: Array<() => void> = [];
  if (plugin.css) disposers.push(runtime.injectCSS(plugin.css, plugin.id));
  const cleanup = plugin.setup?.(runtime);
  if (typeof cleanup === "function") disposers.push(cleanup);
  if (disposers.length) {
    cleanupFns.set(plugin.id, () => disposers.forEach((f) => f()));
  }
}

/** 禁用/卸载：清理 CSS + cleanup + 注销节点 */
export function deactivatePlugin(pluginId: string) {
  cleanupFns.get(pluginId)?.();
  cleanupFns.delete(pluginId);
  unregisterPluginNodes(pluginId);
}

async function fetchPluginSource(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`下载插件失败 (HTTP ${res.status})`);
  return res.text();
}

/** 安装/更新插件（从 URL fetch + activate + 写入 store） */
export async function installPluginFromUrl(
  url: string,
  opts?: { official?: boolean; name?: string },
): Promise<CanvasPlugin> {
  const source = await fetchPluginSource(url);
  const plugin = await evaluatePluginSource(source);
  activatePlugin(plugin);
  usePluginStore.getState().upsert({
    id: plugin.id,
    name: plugin.name || opts?.name || plugin.id,
    version: plugin.version || "0.0.0",
    description: plugin.description,
    url,
    source,
    enabled: true,
    official: opts?.official,
  });
  return plugin;
}

/** 启用/禁用切换 — 重新 activate 会重新加载最新 source（local 插件强制 refetch） */
export async function setPluginEnabled(record: InstalledPlugin, enabled: boolean) {
  usePluginStore.getState().setEnabled(record.id, enabled);
  if (!enabled) {
    deactivatePlugin(record.id);
    return;
  }
  const source = record.local
    ? await fetchPluginSource(`${record.url}?t=${Date.now()}`)
    : record.source || (await fetchPluginSource(record.url));
  const plugin = await evaluatePluginSource(source);
  activatePlugin(plugin);
}

/** 卸载：deactivate + 从 store 移除 */
export function uninstallPlugin(id: string) {
  deactivatePlugin(id);
  usePluginStore.getState().remove(id);
}

let loaded = false;

/** 应用启动时调用 — 从 store 读已启用插件，并行 activate */
export async function ensurePluginsLoaded() {
  if (loaded) return;
  loaded = true;
  await usePluginStore.persist.rehydrate();
  // 本地发现：public/plugins/index.json 列出本地插件 bundle URL
  await loadLocalPlugins();
  const records = usePluginStore.getState().plugins.filter((p) => p.enabled);
  await Promise.all(
    records.map(async (record) => {
      try {
        const source = record.local
          ? await fetchPluginSource(`${record.url}?t=${Date.now()}`)
          : record.source || (await fetchPluginSource(record.url));
        const plugin = await evaluatePluginSource(source);
        activatePlugin(plugin);
      } catch (err) {
        console.error(`[plugin] 加载失败: ${record.id}`, err);
      }
    }),
  );
}

async function loadLocalPlugins() {
  let list: unknown;
  try {
    const res = await fetch("/plugins/index.json");
    if (!res.ok) return;
    list = await res.json();
  } catch {
    return;
  }
  if (!Array.isArray(list) || !list.length) return;
  const store = usePluginStore.getState();
  for (const url of list as string[]) {
    try {
      const source = await fetchPluginSource(url);
      const plugin = await evaluatePluginSource(source);
      const existing = store.plugins.find((p) => p.id === plugin.id);
      store.upsert({
        id: plugin.id,
        name: plugin.name || plugin.id,
        version: plugin.version || "0.0.0",
        description: plugin.description,
        url,
        source,
        enabled: existing?.enabled ?? false, // 保留用户开关
        local: true,
      });
    } catch (err) {
      console.error(`[plugin] 本地发现失败: ${url}`, err);
    }
  }
}
