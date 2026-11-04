/** 插件运行时 — 暴露给插件的宿主能力
 *
 * 目的：避免每个插件 bundle 自己打包一份 React，同时统一宿主事件/AI 能力入口。
 * runtime 是单例，首次 getPluginRuntime() 时构造，挂到 window 便于调试。
 */
import React from "react";
import type { PluginRuntime } from "./types";
import { emitCanvasEvent, onCanvasEvent } from "./event-bus";
import { PLUGIN_SDK_VERSION } from "../infiniteCoreNodes";

let runtime: PluginRuntime | null = null;

function injectCSS(css: string, key?: string): () => void {
  const id = key ? `shiguang-plugin-style-${key}` : undefined;
  if (id) document.getElementById(id)?.remove();
  const style = document.createElement("style");
  if (id) style.id = id;
  style.dataset.shiguangPluginStyle = "true";
  style.textContent = css;
  document.head.appendChild(style);
  return () => style.remove();
}

export function getPluginRuntime(): PluginRuntime {
  if (!runtime) {
    runtime = {
      React,
      injectCSS,
      emit: emitCanvasEvent,
      on: onCanvasEvent,
      version: PLUGIN_SDK_VERSION,
      // ai 字段在 App 挂载后通过 setPluginRuntimeAI 注入
    };
    (window as unknown as { ShiguangCanvasRuntime?: PluginRuntime }).ShiguangCanvasRuntime = runtime;
  }
  return runtime;
}

/** App 挂载后注入宿主 AI 桥 */
export function setPluginRuntimeAI(ai: PluginRuntime["ai"]) {
  const r = getPluginRuntime();
  r.ai = ai;
}
