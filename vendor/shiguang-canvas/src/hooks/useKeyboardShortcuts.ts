/**
 * useKeyboardShortcuts — 画布全局键盘快捷键 hook（tenney95 风格融合）
 *
 * 从 CanvasShell 抽离所有键盘逻辑，新增：
 * - 1-7 数字键快速创建节点
 * - Alt+1-6 快速创建源节点
 * - M 键切换小地图
 */
import { useEffect, useCallback } from "react";
import type { ReactFlowInstance } from "@xyflow/react";
import { useCanvasStore, type NodeData } from "../store";

/** 数字键 → 内置节点类型映射 */
const NUM_TO_NODE: Record<string, NodeData["kind"]> = {
  "1": "script",
  "2": "shot",
  "3": "prompt",
  "4": "config",
  "5": "generator",
  "6": "text",
  "7": "markdown",
};

/** Alt+数字键 → 源节点类型映射 */
const ALT_NUM_TO_NODE: Record<string, NodeData["kind"]> = {
  "1": "image",
  "2": "video",
  "3": "audio",
  "4": "music",
  "5": "shotlist",
  "6": "director",
};

interface ShortcutDeps {
  viewMode: string;
  paletteOpen: boolean;
  cmdOpen: boolean;
  rfRef: React.RefObject<ReactFlowInstance | null>;
  lastPointerRef: React.RefObject<{ clientX: number; clientY: number }>;
  openPaletteAt: (x: number, y: number) => void;
  setCmdOpen: (v: boolean) => void;
  setCtxMenu: (v: unknown) => void;
  setAutoSavedAt: (t: string) => void;
  /** 关闭所有弹出面板（palette + cmd） */
  closeAllPanels: () => void;
  onGroupSelected: () => void;
  onGenerate: () => void;
  onSendToEditor: () => void;
  onBreakdown: () => void;
}

export function useKeyboardShortcuts(deps: ShortcutDeps) {
  const {
    viewMode,
    paletteOpen,
    cmdOpen,
    rfRef,
    lastPointerRef,
    openPaletteAt,
    setCmdOpen,
    setCtxMenu,
    setAutoSavedAt,
    closeAllPanels,
    onGroupSelected,
    onGenerate,
    onSendToEditor,
    onBreakdown,
  } = deps;

  // 从 store 获取操作
  const removeSelected = useCanvasStore((s) => s.removeSelected);
  const duplicateSelected = useCanvasStore((s) => s.duplicateSelected);
  const copySelected = useCanvasStore((s) => s.copySelected);
  const pasteClipboard = useCanvasStore((s) => s.pasteClipboard);
  const selectAll = useCanvasStore((s) => s.selectAll);
  const undoGraph = useCanvasStore((s) => s.undoGraph);
  const redoGraph = useCanvasStore((s) => s.redoGraph);
  const clearSelection = useCanvasStore((s) => s.clearSelection);
  const saveProject = useCanvasStore((s) => s.saveProject);
  const addNode = useCanvasStore((s) => s.addNode);
  const setStatus = useCanvasStore((s) => s.setStatus);
  const theme = useCanvasStore((s) => s.theme);
  const setTheme = useCanvasStore((s) => s.setTheme);

  const onKey = useCallback(
    (ev: KeyboardEvent) => {
      if (viewMode !== "canvas") return;
      const t = ev.target as HTMLElement | null;
      const typing = Boolean(t?.closest?.("input, textarea, select, [contenteditable='true']"));
      const key = ev.key;
      const mod = ev.ctrlKey || ev.metaKey;
      const alt = ev.altKey;

      // 面板/指令打开时，只处理 Escape
      if (paletteOpen || cmdOpen) {
        if (key === "Escape") {
          ev.preventDefault();
          closeAllPanels();
        }
        return;
      }

      // Ctrl+K / Ctrl+P 打开指令面板
      if (mod && (key.toLowerCase() === "k" || key.toLowerCase() === "p") && !ev.shiftKey) {
        ev.preventDefault();
        setCmdOpen(true);
        return;
      }

      if (typing) return;

      // ── 单键快捷键 ──
      switch (key) {
        case "Escape":
          ev.preventDefault();
          clearSelection();
          setCtxMenu(null);
          return;
        case "F":
        case "f":
          if (!mod) {
            ev.preventDefault();
            rfRef.current?.fitView({ padding: 0.18, duration: 220 });
            return;
          }
          break;
        case "Delete":
        case "Backspace":
          ev.preventDefault();
          removeSelected();
          setCtxMenu(null);
          return;
        case "/":
        case "Tab":
          ev.preventDefault();
          openPaletteAt(lastPointerRef.current.clientX, lastPointerRef.current.clientY);
          return;
        case "?":
        case "H":
        case "h":
          if (!mod) {
            ev.preventDefault();
            setCmdOpen(true);
            return;
          }
          break;
        case "M":
        case "m":
          if (!mod && !alt) {
            ev.preventDefault();
            // 触发小地图切换：通过 CustomEvent 通知 CanvasShell
            window.dispatchEvent(new CustomEvent("shiguang:toggle-minimap"));
            return;
          }
          break;
      }

      // ── 数字键快速创建节点（非输入状态）──
      if (key >= "1" && key <= "9" && !mod && !alt) {
        const kind = NUM_TO_NODE[key];
        if (kind) {
          ev.preventDefault();
          const flow = rfRef.current?.screenToFlowPosition({
            x: lastPointerRef.current.clientX,
            y: lastPointerRef.current.clientY,
          });
          addNode(kind, flow);
          setStatus(`已添加「${kind}」节点`);
          return;
        }
      }

      // ── Alt+数字键快速创建源节点 ──
      if (alt && key >= "1" && key <= "9") {
        const kind = ALT_NUM_TO_NODE[key];
        if (kind) {
          ev.preventDefault();
          const flow = rfRef.current?.screenToFlowPosition({
            x: lastPointerRef.current.clientX,
            y: lastPointerRef.current.clientY,
          });
          addNode(kind, flow);
          setStatus(`已添加「${kind}」节点`);
          return;
        }
      }

      // ── Ctrl+ 快捷键 ──
      if (!mod) return;

      switch (key.toLowerCase()) {
        case "d":
          ev.preventDefault();
          duplicateSelected();
          break;
        case "c":
          ev.preventDefault();
          copySelected();
          break;
        case "v":
          ev.preventDefault();
          const flow = rfRef.current?.screenToFlowPosition({
            x: lastPointerRef.current.clientX,
            y: lastPointerRef.current.clientY,
          }) || undefined;
          pasteClipboard(flow);
          break;
        case "a":
          ev.preventDefault();
          selectAll();
          break;
        case "s":
          ev.preventDefault();
          saveProject();
          setAutoSavedAt(new Date().toLocaleTimeString());
          break;
        case "z":
          ev.preventDefault();
          if (ev.shiftKey) {
            redoGraph();
          } else {
            undoGraph();
          }
          break;
        case "y":
          ev.preventDefault();
          redoGraph();
          break;
        case "g":
          ev.preventDefault();
          onGroupSelected();
          break;
        case "enter":
          ev.preventDefault();
          onGenerate();
          break;
        case "e":
          ev.preventDefault();
          onSendToEditor();
          break;
        case "b":
          ev.preventDefault();
          onBreakdown();
          break;
      }

      // ── Ctrl/Cmd + Shift 组合键 ──
      if (!mod || !ev.shiftKey) return;
      switch (key.toLowerCase()) {
        case "t":
          // Ctrl+Shift+T 切换主题（V4.41.22 引入）
          ev.preventDefault();
          setTheme(theme === "dark" ? "light" : "dark");
          setStatus(`已切换到${theme === "dark" ? "浅色" : "暗色"}主题`);
          break;
      }
    },
    [
      viewMode,
      paletteOpen,
      cmdOpen,
      rfRef,
      lastPointerRef,
      openPaletteAt,
      setCmdOpen,
      setCtxMenu,
      setAutoSavedAt,
      closeAllPanels,
      onGroupSelected,
      onGenerate,
      onSendToEditor,
      onBreakdown,
      removeSelected,
      duplicateSelected,
      copySelected,
      pasteClipboard,
      selectAll,
      undoGraph,
      redoGraph,
      clearSelection,
      saveProject,
      addNode,
      setStatus,
      theme,
      setTheme,
    ],
  );

  // 注册/注销快捷键
  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);
}