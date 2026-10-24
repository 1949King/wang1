/** 画布级事件总线 — 插件 emit/on 的底层实现
 *
 * 支持宿主内 + 跨插件广播。用原生 Set + Map 实现，零依赖。
 */
type Handler = (payload: unknown) => void;
const handlers = new Map<string, Set<Handler>>();

export function emitCanvasEvent(event: string, payload?: unknown) {
  const set = handlers.get(event);
  if (!set) return;
  for (const h of set) {
    try { h(payload); } catch (e) { console.error("[canvas-event] handler error on", event, e); }
  }
}

export function onCanvasEvent(event: string, handler: Handler): () => void {
  if (!handlers.has(event)) handlers.set(event, new Set());
  handlers.get(event)!.add(handler);
  return () => handlers.get(event)?.delete(handler);
}

/** 一次性：首个 handler 注册时触发一次后取消 */
export function onceCanvasEvent(event: string, handler: Handler) {
  const off = onCanvasEvent(event, (p) => { handler(p); off(); });
}
