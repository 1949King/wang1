/**
 * V4.41.19 AI 画布重组：命令面板（Ctrl+K）扩展项生成器。
 * AgentOS S5 命令中枢雏形 —— 让 80% 的功能不需要直接暴露在界面上：
 * 搜得到节点分类（直接加）、搜得到 Agent 工具（跳面板运行）。
 *
 * 从 CanvasShell.tsx 拆出（规模守卫：CanvasShell 基线 3199 + 容差 30，本刀新增必须外置）。
 */
import { useEffect, useState } from "react";
import type { CommandItem } from "./CommandPalette";
import type { PaletteItem } from "./NodePalette";
import { listProjectTools, type ProjectTool } from "./bridge";

/** 由内置节点分类生成「添加 XX 节点」命令项（digitalHuman 已有专属项，去重） */
export function nodeCommandItems(
  items: PaletteItem[],
  pickNodeByType: (type: string) => void,
): CommandItem[] {
  return items
    .filter((it) => it.type !== "digitalHuman")
    .map((it) => ({
      id: `add-node:${it.type}`,
      label: `添加「${it.label}」节点`,
      hint: it.hint,
      keywords: it.keywords,
      run: () => pickNodeByType(it.type),
    }));
}

/** 由 Agent 工具表生成命令项（点击跳 Agent 面板，运行在工具 Tab 含确认流） */
export function agentToolCommandItems(
  tools: ProjectTool[],
  openAgent: () => void,
): CommandItem[] {
  return tools.map((t) => ({
    id: `agent-tool:${t.extension_id}:${t.tool_id}`,
    label: `🛠 ${t.tool_name || t.tool_id}`,
    hint: `${t.extension_type} · ${t.extension_name}`,
    keywords: `${t.tool_id} ${t.extension_id} ${t.description || ""} agent tool 工具`,
    run: () => openAgent(),
  }));
}

/** 挂载时拉一次 Agent 工具表（最多 60 条）供命令面板搜索；失败静默（AgentPanel 自己会再拉并提示） */
export function useAgentCmdTools(): ProjectTool[] {
  const [tools, setTools] = useState<ProjectTool[]>([]);
  useEffect(() => {
    let alive = true;
    listProjectTools()
      .then((r) => {
        if (alive && r.ok) setTools(r.tools.slice(0, 60));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  return tools;
}
