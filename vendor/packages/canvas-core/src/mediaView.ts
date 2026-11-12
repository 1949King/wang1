/**
 * 双击媒体 → 大图/播放（2026-11-12）。
 *
 * 为什么用"事件委托"而不是改节点组件：
 * nodes.tsx / CanvasShell.tsx 在冻结区，未授权解冻不可改；
 * 在 App 挂一个 document 级 dblclick 监听即可覆盖所有节点（图片/视频/图库）。
 */
export type MediaView = { kind: "image" | "video"; src: string };

/** 纯函数：标签 + 地址 → 可展示的媒体（便于单测）。 */
export function classifyMedia(tagName: string, src: string | null | undefined): MediaView | null {
  const tag = String(tagName || "").toLowerCase();
  const url = String(src || "").trim();
  if (!url) return null;
  if (tag === "img") return { kind: "image", src: url };
  if (tag === "video") return { kind: "video", src: url };
  return null;
}
