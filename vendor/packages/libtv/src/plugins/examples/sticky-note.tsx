/** 便利贴（StickyNote）示例插件 — 验证插件 SDK 设计
 *
 * 这是最小可用节点插件模板：一个纯前端节点，不依赖宿主 AI bridge。
 * 在 App.tsx 启动时同步 import 注册到 node-registry，
 * 绕过动态加载链路（动态加载需要先 vite build 成纯 JS bundle）。
 *
 * 真实生产环境下应该打包成独立 .js bundle 放在 public/plugins/ 下，
 * 由 plugin-loader.ts 的 installPluginFromUrl() 动态加载。
 */
import { memo, useState, useCallback } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { CanvasNodeDefinition } from "../node-registry";

type StickyNodeData = {
  title?: string;
  content?: string;
  color?: string;
};

const STICKY_COLORS = ["#fef08a", "#bbf7d0", "#bfdbfe", "#fbcfe8", "#fed7aa", "#ddd6fe"];

function StickyNoteNode(props: NodeProps<Node<StickyNodeData>>) {
  const { id, data, selected } = props;
  const [editing, setEditing] = useState(false);
  const title = data.title ?? "便利贴";
  const content = data.content ?? "";
  const color = data.color ?? "#fef08a";

  const onDoubleClick = useCallback(() => setEditing(true), []);
  const onBlur = useCallback(() => setEditing(false), []);

  return (
    <div
      onDoubleClick={onDoubleClick}
      style={{
        width: 220,
        minHeight: 140,
        background: color,
        borderRadius: 6,
        padding: 12,
        boxShadow: selected
          ? "0 0 0 2px #7c3aed, 0 6px 20px rgba(0,0,0,0.25)"
          : "0 2px 10px rgba(0,0,0,0.15)",
        fontFamily: "'Comic Sans MS', cursive, sans-serif",
      }}
    >
      <Handle type="target" position={Position.Top} id="in" style={{ background: "#7c3aed" }} />

      {editing ? (
        <textarea
          autoFocus
          defaultValue={`${title}\n${content}`}
          onBlur={onBlur}
          style={{
            width: "100%",
            minHeight: 100,
            background: "transparent",
            border: "none",
            outline: "none",
            resize: "vertical",
            fontFamily: "inherit",
            fontSize: 12,
            lineHeight: 1.5,
          }}
        />
      ) : (
        <>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 4, color: "#333" }}>
            📌 {title}
          </div>
          <div style={{ fontSize: 12, color: "#444", whiteSpace: "pre-wrap", lineHeight: 1.4 }}>
            {content || "双击编辑内容..."}
          </div>
        </>
      )}

      <div style={{ marginTop: 8, display: "flex", gap: 4 }}>
        {STICKY_COLORS.map((c) => (
          <div
            key={c}
            title={c}
            style={{
              width: 14,
              height: 14,
              borderRadius: 3,
              background: c,
              border: c === color ? "2px solid #7c3aed" : "1px solid rgba(0,0,0,0.2)",
              cursor: "pointer",
            }}
            onClick={(e) => {
              e.stopPropagation();
              // 通过 store 更新颜色
              const store = (window as unknown as { __shiguangStore?: { getState: () => { updateNode: (id: string, patch: Partial<StickyNodeData>) => void } } }).__shiguangStore;
              store?.getState().updateNode(id, { color: c });
            }}
          />
        ))}
      </div>

      <Handle type="source" position={Position.Bottom} id="out" style={{ background: "#7c3aed" }} />
    </div>
  );
}

/** 插件定义 — 用 CanvasNodeDefinition 接口 */
export const STICKY_PLUGIN: CanvasNodeDefinition[] = [
  {
    type: "plugin:sticky-note",
    title: "便利贴",
    icon: "📌",
    description: "彩色便利贴，双击编辑内容",
    defaultSize: { width: 240, height: 160 },
    Component: memo(StickyNoteNode),
    showInCreateMenu: true,
  },
];

/** SDK 工厂函数 — 动态加载时会用这个入口 */
export function createStickyNotePlugin(runtime?: unknown) {
  return {
    id: "plugin:sticky-note",
    name: "便利贴插件",
    version: "0.1.0",
    description: "便利贴节点插件示例",
    nodes: STICKY_PLUGIN,
    setup: (rt: unknown) => {
      // 可选：setup 生命周期
      const r = rt as { injectCSS?: (css: string) => () => void };
      r?.injectCSS?.(`
        .xy-flow__node-plugin\\:sticky-note { transition: transform 0.15s ease; }
        .xy-flow__node-plugin\\:sticky-note:hover { transform: scale(1.02); }
      `);
      return () => {};
    },
  };
}
