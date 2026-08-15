/** 已安装插件状态持久化 — Zustand + localStorage
 *
 * 与 plugin-loader 分离：store 只管"有哪些插件装过/启用过"，
 * loader 管"从 URL fetch bundle → evaluate → activate/deactivate"。
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type InstalledPlugin = {
  id: string;
  name: string;
  version: string;
  description?: string;
  /** 插件 bundle 的 URL（远程或本地 /plugins/xxx.js） */
  url: string;
  /** 最近一次成功加载的 bundle source code，启用时优先用缓存避免重复 fetch */
  source?: string;
  enabled: boolean;
  /** 是否官方（注册表列出的） */
  official?: boolean;
  /** 是否本地发现（public/plugins/index.json 扫出来的） */
  local?: boolean;
};

type Store = {
  plugins: InstalledPlugin[];
  setEnabled: (id: string, enabled: boolean) => void;
  upsert: (record: InstalledPlugin) => void;
  remove: (id: string) => void;
  clear: () => void;
};

export const usePluginStore = create<Store>()(
  persist(
    (set) => ({
      plugins: [],
      setEnabled: (id, enabled) =>
        set((s) => ({ plugins: s.plugins.map((p) => (p.id === id ? { ...p, enabled } : p)) })),
      upsert: (record) =>
        set((s) => {
          const others = s.plugins.filter((p) => p.id !== record.id);
          return { plugins: [record, ...others] };
        }),
      remove: (id) => set((s) => ({ plugins: s.plugins.filter((p) => p.id !== id) })),
      clear: () => set({ plugins: [] }),
    }),
    { name: "shiguang-canvas:plugins:v1" },
  ),
);
