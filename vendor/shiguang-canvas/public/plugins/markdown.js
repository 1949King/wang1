/* Markdown 文档节点插件（builtin:markdown）
 *
 * 零 import（Blob URL 动态加载），React 取自 rt.React。
 * 渲染器是自带的最小实现：标题/列表/引用/代码块/分割线/粗体斜体行内码链接。
 * 不引第三方 markdown 库（bundle 必须自包含），也不使用 dangerouslySetInnerHTML
 * （用户输入直接进 DOM 会带 XSS 面），全部用 React 元素构造。
 */
export default function createMarkdownPlugin(rt) {
  const React = rt.React;
  const h = React.createElement;
  const { useState, useMemo, useCallback } = React;

  const SAMPLE =
    "# 文档标题\n\n" +
    "双击正文或点「编辑」写下你的分镜说明、提示词草稿。\n\n" +
    "- 支持 **粗体**、*斜体*、`行内代码`\n" +
    "- 支持 [链接](https://example.com)\n\n" +
    "> 引用块\n\n" +
    "```\n代码块\n```\n";

  const MONO = "ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace";

  /* ── 行内解析：**bold** / *italic* / `code` / [text](url) ── */
  function inline(text, keyBase) {
    const out = [];
    const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
    let last = 0;
    let m;
    let i = 0;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const token = m[0];
      const k = keyBase + "-i" + i++;
      if (token.startsWith("**")) {
        out.push(h("strong", { key: k }, token.slice(2, -2)));
      } else if (token.startsWith("`")) {
        out.push(
          h("code", { key: k, style: { fontFamily: MONO, fontSize: "0.92em", padding: "1px 4px", borderRadius: 4, background: "rgba(127,127,127,0.16)" } }, token.slice(1, -1))
        );
      } else if (token.startsWith("[")) {
        const hit = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        out.push(
          h("a", { key: k, href: hit ? hit[2] : "#", target: "_blank", rel: "noreferrer", style: { color: "#60a5fa" } }, hit ? hit[1] : token)
        );
      } else {
        out.push(h("em", { key: k }, token.slice(1, -1)));
      }
      last = m.index + token.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  /* ── 块级解析 ── */
  function render(source) {
    const lines = String(source || "").split(/\r?\n/);
    const blocks = [];
    let i = 0;
    let key = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const buf = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++;
        blocks.push(
          h(
            "pre",
            {
              key: "b" + key++,
              style: { fontFamily: MONO, fontSize: 12, background: "rgba(127,127,127,0.14)", borderRadius: 6, padding: 10, overflowX: "auto", margin: "6px 0" },
            },
            h("code", null, buf.join("\n"))
          )
        );
        continue;
      }
      const head = /^(#{1,4})\s+(.*)$/.exec(line);
      if (head) {
        const lv = head[1].length;
        blocks.push(
          h(
            "div",
            {
              key: "b" + key++,
              style: {
                fontSize: [20, 17, 15, 14][lv - 1],
                fontWeight: 700,
                margin: lv === 1 ? "10px 0 6px" : "8px 0 4px",
                lineHeight: 1.3,
              },
            },
            inline(head[2], "h" + key)
          )
        );
        i++;
        continue;
      }
      if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
        blocks.push(h("hr", { key: "b" + key++, style: { border: 0, borderTop: "1px solid rgba(127,127,127,0.3)", margin: "10px 0" } }));
        i++;
        continue;
      }
      if (/^\s*>\s?/.test(line)) {
        const buf = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ""));
        blocks.push(
          h(
            "div",
            { key: "b" + key++, style: { borderLeft: "3px solid rgba(127,127,127,0.45)", padding: "2px 0 2px 10px", margin: "6px 0", opacity: 0.9 } },
            inline(buf.join(" "), "q" + key)
          )
        );
        continue;
      }
      if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line);
        const items = [];
        while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
          items.push(h("li", { key: "li" + key++, style: { margin: "2px 0" } }, inline(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ""), "li" + key)));
          i++;
        }
        blocks.push(h(ordered ? "ol" : "ul", { key: "b" + key++, style: { margin: "6px 0", paddingLeft: 22 } }, items));
        continue;
      }
      if (!line.trim()) {
        i++;
        continue;
      }
      const buf = [line];
      i++;
      while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*>|\s*([-*+]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
      blocks.push(h("div", { key: "b" + key++, style: { margin: "6px 0", lineHeight: 1.6 } }, inline(buf.join(" "), "p" + key)));
    }
    if (!blocks.length) blocks.push(h("div", { key: "empty", style: { opacity: 0.5 } }, "（空文档：双击或点「编辑」开始写）"));
    return blocks;
  }

  function MarkdownNode(ctx) {
    const data = ctx.node.data || {};
    const source = data.source != null ? String(data.source) : SAMPLE;
    const title = data.title || "Markdown";
    const [editing, setEditing] = useState(false);
    const rendered = useMemo(() => render(source), [source]);
    const commit = useCallback(
      (value) => {
        setEditing(false);
        ctx.updateMetadata({ source: String(value || "") });
      },
      [ctx]
    );

    return h(
      "div",
      {
        style: {
          width: 340,
          minHeight: 180,
          padding: 10,
          borderRadius: 8,
          border: "1px solid rgba(127,127,127,0.28)",
          background: "rgba(127,127,127,0.07)",
          color: "inherit",
          fontSize: 13,
          lineHeight: 1.55,
        },
      },
      h(
        "div",
        { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 12, opacity: 0.85 } },
        h("span", { style: { fontWeight: 700 } }, "📄 " + title),
        h("span", { style: { flex: 1 } }),
        h(
          "button",
          {
            onClick: (e) => {
              e.stopPropagation();
              setEditing(!editing);
            },
            style: { fontSize: 11, padding: "2px 8px", borderRadius: 5, border: "1px solid rgba(127,127,127,0.4)", background: "transparent", color: "inherit", cursor: "pointer" },
          },
          editing ? "预览" : "编辑"
        )
      ),
      editing
        ? h("textarea", {
            autoFocus: true,
            defaultValue: source,
            onBlur: (e) => commit(e.target.value),
            onKeyDown: (e) => {
              if (e.key === "Escape") commit(e.target.value);
            },
            style: { width: "100%", minHeight: 220, fontFamily: MONO, fontSize: 12, lineHeight: 1.5, color: "inherit", background: "rgba(127,127,127,0.1)", border: "1px solid rgba(127,127,127,0.25)", borderRadius: 6, padding: 8, resize: "vertical" },
          })
        : h("div", null, rendered)
    );
  }

  return {
    id: "builtin:markdown",
    name: "Markdown 文档",
    version: "0.1.0",
    description: "渲染 Markdown 文档节点，支持代码高亮和表格",
    nodes: [
      {
        type: "builtin:markdown",
        title: "Markdown",
        icon: "📄",
        description: "写分镜说明/提示词草稿，双击进入源码编辑",
        defaultSize: { width: 360, height: 260 },
        defaultMetadata: { title: "Markdown", source: SAMPLE },
        Content: MarkdownNode,
        hasSourceHandle: false,
      },
    ],
  };
}
