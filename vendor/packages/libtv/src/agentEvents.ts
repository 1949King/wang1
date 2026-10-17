/**
 * Agent ↔ Canvas SSE 订阅（自 bridge.ts 拆出，模块规模守卫 2026-10-14）。
 *
 * 与 bridge.ts 存在「延迟引用」循环 import（双方模块顶层均不触碰对方绑定，
 * 仅在函数调用时使用），ESM 下安全 —— 与 generationQueue 同模式。
 */

import { BRIDGE, bridgeToken } from "./bridge";

export type AgentEventEnvelope = {
  id: string;
  ts: number;
  from: string;
  to: string;
  type: string;
  correlation_id: string;
  payload: any;
  ack_required: boolean;
};

export type SubscribeOpts = {
  onEvent: (evt: AgentEventEnvelope) => void;
  onError?: (err: string) => void;
  /** 连接建立（含每次自动重连成功）时回调，供调用方重置断线计数。 */
  onOpen?: () => void;
  sinceId?: string;
};

/**
 * 订阅剪辑 Agent 推过来的 SSE 事件（/host/agent/events）。
 * 浏览器 EventSource 自带断线自动重连。
 * 返回一个取消订阅函数（调 es.close()）。
 */
export function subscribeAgentEvents(opts: SubscribeOpts): () => void {
  const token = bridgeToken();
  const params = new URLSearchParams({ token });
  if (opts.sinceId) params.set("since_id", opts.sinceId);
  const url = `${BRIDGE}/host/agent/events?${params.toString()}`;

  let es: EventSource | null = null;
  try {
    es = new EventSource(url);
  } catch (e: any) {
    opts.onError?.(`SSE 创建失败: ${e?.message || e}`);
    return () => {};
  }

  let lastId = opts.sinceId || "";
  es.addEventListener("agent", (ev) => {
    const msg = ev as MessageEvent;
    try {
      const data = JSON.parse(String(msg.data || "{}"));
      const env: AgentEventEnvelope = {
        id: String(data.id || ""),
        ts: Number(data.ts || 0),
        from: String(data.from || ""),
        to: String(data.to || ""),
        type: String(data.type || ""),
        correlation_id: String(data.correlation_id || ""),
        payload: data.payload,
        ack_required: Boolean(data.ack_required),
      };
      if (env.id) lastId = env.id;
      opts.onEvent(env);
    } catch (e: any) {
      opts.onError?.(`SSE 消息解析失败: ${e?.message || e}`);
    }
  });

  // 连接建立（含自动重连成功）时通知调用方，用于重置断线计数与收敛提示。
  es.onopen = () => opts.onOpen?.();

  es.onerror = () => {
    // EventSource 会自动重连，这里只做通知（去重/退避由调用方负责）
    opts.onError?.("SSE 连接异常（正在自动重连）");
  };

  return () => {
    try {
      es?.close();
    } catch {
      /* ignore */
    }
  };
}
