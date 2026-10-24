/* SVG 查看器节点插件（builtin:svg-viewer）
 *
 * 零 import（Blob URL 动态加载），React 取自 rt.React。
 * 安全：SVG 源码放进 **sandbox=""** 的 iframe（禁脚本、禁同源），
 * 不用 innerHTML 直接注入 —— 用户粘贴的 SVG 可能带 <script>/onload，落进宿主 DOM 就是 XSS。
 * 缩放走容器 transform，不重写源码。
 */
export default function createSvgViewerPlugin(rt) {
  const React = rt.React;
  const h = React.createElement;
  const { useState, useCallback } = React;

  const SAMPLE =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120" width="200" height="120">' +
    '<rect x="4" y="4" width="192" height="112" rx="10" fill="#1f2937" stroke="#60a5fa" stroke-width="2"/>' +
    '<circle cx="70" cy="60" r="26" fill="#fbbf24"/>' +
    '<text x="105" y="66" fill="#e5e7eb" font-size="16" font-family="sans-serif">SVG</text>' +
    "</svg>";

  const MONO = "ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace";
  const ZOOMS = [0.5, 0.75, 1, 1.5, 2, 3];

  function svgDoc(source) {
    return (
      '<!doctype html><html><head><meta charset="utf-8">' +
      '<style>html,body{margin:0;height:100%;display:flex;align-items:center;justify-content:center;background:transparent}</style>' +
      "</head><body>" +
      String(source || "") +
      "</body></html>"
    );
  }

  function SvgViewerNode(ctx) {
    const data = ctx.node.data || {};
    const source = data.svg != null ? String(data.svg) : SAMPLE;
    const title = data.title || "SVG";
    const [editing, setEditing] = useState(false);
    const [zoom, setZoom] = useState(data.zoom || 1);

    const applyZoom = useCallback(
      (z) => {
        setZoom(z);
        ctx.updateMetadata({ zoom: z });
      },
      [ctx]
    );

    const commit = useCallback(
      (value) => {
        setEditing(false);
        ctx.updateMetadata({ svg: String(value || "") });
      },
      [ctx]
    );

    const frame = h("iframe", {
      // sandbox="" ⇒ 禁脚本、禁表单、禁同源；SVG 仅作静态渲染
      sandbox: "",
      srcDoc: svgDoc(source),
      title: "svg-preview",
      style: { width: "100%", height: "100%", border: "none", background: "transparent", display: "block" },
    });

    return h(
      "div",
      {
        style: {
          width: 320,
          minHeight: 190,
          padding: 8,
          borderRadius: 8,
          border: "1px solid rgba(127,127,127,0.28)",
          background: "rgba(127,127,127,0.07)",
          color: "inherit",
          fontSize: 12,
        },
      },
      h(
        "div",
        { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 6 } },
        h("span", { style: { fontWeight: 700 } }, "🎨 " + title),
        h("span", { style: { flex: 1 } }),
        ZOOMS.map((z) =>
          h(
            "button",
            {
              key: z,
              onClick: (e) => {
                e.stopPropagation();
                applyZoom(z);
              },
              style: {
                fontSize: 10,
                padding: "1px 5px",
                borderRadius: 4,
                border: "1px solid rgba(127,127,127,0.4)",
                background: z === zoom ? "rgba(96,165,250,0.28)" : "transparent",
                color: "inherit",
                cursor: "pointer",
              },
            },
            Math.round(z * 100) + "%"
          )
        ),
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
            style: { width: "100%", minHeight: 200, fontFamily: MONO, fontSize: 11, lineHeight: 1.45, color: "inherit", background: "rgba(127,127,127,0.1)", border: "1px solid rgba(127,127,127,0.25)", borderRadius: 6, padding: 8, resize: "vertical" },
          })
        : h(
            "div",
            { style: { height: 170, overflow: "auto", borderRadius: 6, background: "rgba(127,127,127,0.06)" } },
            h("div", { style: { width: "100%", height: "100%", transform: "scale(" + zoom + ")", transformOrigin: "top left", transition: "transform 120ms ease" } }, frame)
          )
    );
  }

  return {
    id: "builtin:svg-viewer",
    name: "SVG 查看器",
    version: "0.1.0",
    description: "嵌入 SVG 图形，支持缩放和导出",
    nodes: [
      {
        type: "builtin:svg-viewer",
        title: "SVG",
        icon: "🎨",
        description: "粘贴 SVG 源码即可预览（sandbox iframe 渲染，禁脚本）",
        defaultSize: { width: 340, height: 240 },
        defaultMetadata: { title: "SVG", svg: SAMPLE, zoom: 1 },
        Content: SvgViewerNode,
        hasSourceHandle: false,
      },
    ],
  };
}
