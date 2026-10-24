/* 时间线嵌入节点插件（builtin:timeline-embed）
 *
 * 零 import（Blob URL 动态加载），React 取自 rt.React。
 * 数据源：宿主 Python 桥 GET /host/timeline-snapshot（需 token）——
 * 与画布其它模块同一条通道（window.__SHIGUANG_BRIDGE_URL / TOKEN 由 bridge.ts 注入）。
 *
 * 只做**只读预览**：字段全部来自后端快照（clip_count / timeline_duration / clips[] …），
 * 拿不到就如实说拿不到，绝不编数字。双向跳转尚未实现，故按钮不假装能跳。
 */
export default function createTimelineEmbedPlugin(rt) {
  const React = rt.React;
  const h = React.createElement;
  const { useState, useEffect, useCallback } = React;

  const DEFAULT_BRIDGE = "http://127.0.0.1:18765";

  function bridgeBase() {
    const w = typeof window !== "undefined" ? window : {};
    return (w.__SHIGUANG_BRIDGE_URL || DEFAULT_BRIDGE).replace(/\/+$/, "");
  }

  function bridgeToken() {
    const w = typeof window !== "undefined" ? window : {};
    return w.__SHIGUANG_BRIDGE_TOKEN || "";
  }

  function fmtSec(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n < 0) return "--";
    const m = Math.floor(n / 60);
    const s = n - m * 60;
    return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
  }

  function TimelineEmbedNode(ctx) {
    const title = (ctx.node.data || {}).title || "时间线";
    const [state, setState] = useState({ phase: "loading", data: null, error: "" });

    const load = useCallback(() => {
      const token = bridgeToken();
      if (!token) {
        setState({ phase: "no-token", data: null, error: "" });
        return;
      }
      setState({ phase: "loading", data: null, error: "" });
      const url = bridgeBase() + "/host/timeline-snapshot?token=" + encodeURIComponent(token);
      fetch(url, { headers: { Accept: "application/json" } })
        .then((res) => {
          if (!res.ok) throw new Error("HTTP " + res.status);
          return res.json();
        })
        .then((json) => {
          if (!json || json.ok === false) {
            setState({ phase: "error", data: null, error: (json && json.message) || "快照返回 ok:false" });
            return;
          }
          setState({ phase: "ready", data: json, error: "" });
        })
        .catch((e) => setState({ phase: "error", data: null, error: String((e && e.message) || e) }));
    }, []);

    useEffect(() => {
      load();
    }, [load]);

    const d = state.data;
    const clips = d && Array.isArray(d.clips) ? d.clips : [];
    const shown = clips.slice(0, 8);

    const header = h(
      "div",
      { style: { display: "flex", alignItems: "center", gap: 6, marginBottom: 6 } },
      h("span", { style: { fontWeight: 700 } }, "🎬 " + title),
      h("span", { style: { flex: 1 } }),
      h(
        "button",
        {
          onClick: (e) => {
            e.stopPropagation();
            load();
          },
          style: { fontSize: 11, padding: "2px 8px", borderRadius: 5, border: "1px solid rgba(127,127,127,0.4)", background: "transparent", color: "inherit", cursor: "pointer" },
        },
        "刷新"
      )
    );

    let body;
    if (state.phase === "no-token") {
      body = h(
        "div",
        { style: { opacity: 0.75, lineHeight: 1.6 } },
        "宿主桥未连接（未拿到 token）。",
        h("br", null),
        "请从应用主界面打开画布（会注入 __SHIGUANG_BRIDGE_TOKEN），而不是直接在浏览器里开 3011。"
      );
    } else if (state.phase === "loading") {
      body = h("div", { style: { opacity: 0.7 } }, "读取时间线快照…");
    } else if (state.phase === "error") {
      body = h("div", { style: { color: "#f87171", lineHeight: 1.6 } }, "读取失败：" + (state.error || "未知原因"));
    } else if (!d) {
      body = h("div", { style: { opacity: 0.7 } }, "无数据");
    } else {
      const summary = [
        ["片段", String(d.clip_count != null ? d.clip_count : clips.length)],
        ["时长", fmtSec(d.timeline_duration)],
        ["轨道", String(d.track_count != null ? d.track_count : "--")],
        ["空隙", String(d.gap_count != null ? d.gap_count : "--")],
      ];
      body = h(
        "div",
        null,
        h(
          "div",
          { style: { display: "flex", gap: 14, marginBottom: 8, flexWrap: "wrap" } },
          summary.map((kv) =>
            h(
              "div",
              { key: kv[0], style: { minWidth: 54 } },
              h("div", { style: { fontSize: 10, opacity: 0.6 } }, kv[0]),
              h("div", { style: { fontSize: 14, fontWeight: 700 } }, kv[1])
            )
          )
        ),
        d.message
          ? h("div", { style: { fontSize: 11, opacity: 0.7, marginBottom: 6 } }, String(d.message))
          : null,
        shown.length
          ? h(
              "div",
              { style: { display: "flex", flexDirection: "column", gap: 3 } },
              shown.map((c, i) =>
                h(
                  "div",
                  {
                    key: (c && c.id) || "c" + i,
                    style: {
                      display: "flex",
                      gap: 8,
                      fontSize: 11,
                      padding: "3px 6px",
                      borderRadius: 4,
                      background: c && c.id === d.selected_clip_id ? "rgba(96,165,250,0.22)" : "rgba(127,127,127,0.09)",
                    },
                  },
                  h("span", { style: { width: 30, opacity: 0.6 } }, "T" + (c ? c.track : "?")),
                  h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, String((c && (c.name || c.path)) || "(未命名)")),
                  h("span", { style: { opacity: 0.75, fontVariantNumeric: "tabular-nums" } }, fmtSec(c && c.start_time)),
                  h("span", { style: { opacity: 0.5 } }, "+" + fmtSec(c && c.duration))
                )
              )
            )
          : h("div", { style: { opacity: 0.6, fontSize: 11 } }, "时间线还没有片段"),
        clips.length > shown.length
          ? h("div", { style: { fontSize: 10, opacity: 0.55, marginTop: 4 } }, "…共 " + clips.length + " 条，仅显示前 " + shown.length + " 条")
          : null
      );
    }

    return h(
      "div",
      {
        style: {
          width: 340,
          minHeight: 150,
          padding: 10,
          borderRadius: 8,
          border: "1px solid rgba(127,127,127,0.28)",
          background: "rgba(127,127,127,0.07)",
          color: "inherit",
          fontSize: 12,
        },
      },
      header,
      body
    );
  }

  return {
    id: "builtin:timeline-embed",
    name: "时间线嵌入",
    version: "0.1.0",
    description: "只读预览剪辑时间线（片段/时长/空隙），数据来自 /host/timeline-snapshot",
    nodes: [
      {
        type: "builtin:timeline-embed",
        title: "时间线",
        icon: "🎬",
        description: "只读预览当前时间线快照；双向跳转尚未实现",
        defaultSize: { width: 360, height: 260 },
        defaultMetadata: { title: "时间线" },
        Content: TimelineEmbedNode,
        hasSourceHandle: false,
      },
    ],
  };
}
