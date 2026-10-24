/* 便利贴节点插件（builtin:sticky-note）
 *
 * 动态 bundle 铁律：**零 import**。
 * 宿主用 Blob URL + import() 加载本文件，任何相对/裸模块导入都会解析失败；
 * React 一律从 normalizeInfinitePlugin 传进来的 runtime 取（rt.React）。
 *
 * 宿主会为 Content 型节点自动画 target/source 连接点（infinite-compat.tsx
 * wrapContentComponent），故这里不需要（也无法）import @xyflow/react。
 */
export default function createStickyNotePlugin(rt) {
  const React = rt.React;
  const h = React.createElement;
  const { useState, useCallback, useMemo } = React;

  const COLORS = ["#fef08a", "#bbf7d0", "#bfdbfe", "#fbcfe8", "#fed7aa", "#ddd6fe", "#e5e7eb"];

  function StickyNote(ctx) {
    const data = ctx.node.data || {};
    const color = data.color || COLORS[0];
    const title = data.title || "便利贴";
    const content = data.content || "";
    const [editing, setEditing] = useState(false);

    const onDoubleClick = useCallback(() => setEditing(true), []);
    const onBlur = useCallback(
      (e) => {
        setEditing(false);
        const raw = String(e.target.value || "");
        ctx.updateMetadata({ content: raw });
      },
      [ctx]
    );

    const swatches = COLORS.map((c) =>
      h("span", {
        key: c,
        title: c,
        onClick: (e) => {
          e.stopPropagation();
          ctx.updateMetadata({ color: c });
        },
        style: {
          width: 13,
          height: 13,
          borderRadius: 3,
          display: "inline-block",
          background: c,
          border: c === color ? "2px solid #7c3aed" : "1px solid rgba(0,0,0,0.25)",
          cursor: "pointer",
        },
      })
    );

    const body = editing
      ? h("textarea", {
          autoFocus: true,
          defaultValue: content,
          onBlur,
          onKeyDown: (e) => {
            if (e.key === "Escape") setEditing(false);
          },
          style: {
            width: "100%",
            minHeight: 90,
            background: "rgba(0,0,0,0.06)",
            border: "none",
            outline: "none",
            resize: "vertical",
            fontSize: 12,
            lineHeight: 1.5,
            color: "#333",
            fontFamily: "inherit",
          },
        })
      : h(
          "div",
          {
            style: {
              fontSize: 12,
              color: "#444",
              whiteSpace: "pre-wrap",
              lineHeight: 1.45,
              minHeight: 60,
            },
          },
          content || "双击编辑内容…"
        );

    return h(
      "div",
      {
        onDoubleClick,
        style: {
          width: 220,
          minHeight: 130,
          background: color,
          borderRadius: 6,
          padding: 10,
          boxShadow: ctx.isSelected
            ? "0 0 0 2px #7c3aed, 0 6px 20px rgba(0,0,0,0.25)"
            : "0 2px 10px rgba(0,0,0,0.15)",
          fontFamily: "'Comic Sans MS', 'Microsoft YaHei', cursive",
        },
      },
      h("div", { style: { fontWeight: 700, fontSize: 13, marginBottom: 4, color: "#333" } }, "📌 " + title),
      body,
      h("div", { style: { marginTop: 8, display: "flex", gap: 4 } }, swatches)
    );
  }

  return {
    id: "builtin:sticky-note",
    name: "便利贴",
    version: "0.1.0",
    description: "彩色便利贴节点，双击编辑内容",
    nodes: [
      {
        type: "builtin:sticky-note",
        title: "便利贴",
        icon: "📌",
        description: "彩色便利贴，双击编辑内容并保存到节点数据",
        defaultSize: { width: 240, height: 160 },
        defaultMetadata: { title: "便利贴", content: "", color: COLORS[0] },
        Content: StickyNote,
        hasSourceHandle: false,
      },
    ],
  };
}
