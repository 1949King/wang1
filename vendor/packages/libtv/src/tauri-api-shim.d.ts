/**
 * @tauri-apps/api/core 的最小类型声明（shim）。
 *
 * bridge.ts 通过动态 import("@tauri-apps/api/core") 在 Tauri 桌面宿主下取 invoke；
 * Qt WebEngine 嵌入宿手下 isTauri 恒为 false、该 import 永不执行，故无需安装真源。
 * 本文件仅让 tsc 通过类型检查；运行时由 vite.config.ts 的 external 配置接管。
 */
declare module "@tauri-apps/api/core" {
  export function invoke<T>(
    cmd: string,
    args?: Record<string, unknown>,
  ): Promise<T>;
}