/**
 * 「谁还在」—— 由 `member.last_seen` 推算在线状态（2026-11-04 · 画布 0.3.50）
 *
 * 背景：面板原来只知道「团队有几个人」，不知道**这几个人现在在不在**。所以你会
 * 对着一个已经关电脑的同事等上传，或者以为「他在改」而不敢动。
 *
 * 为什么用 last_seen 而不是「在线连接」：团队服务是无长连接的 HTTP，没有 WebSocket
 * 心跳 —— 造一套连接表就是新机制。而每次请求都会刷新 last_seen（服务端 `auth()` 里
 * 做了 20 秒节流），所以「最近一次动过» 本来就是现成的、诚实的证据。
 *
 * 🔴 窗口取 90 秒：客户端心跳 12 秒一次，容忍几次网络抖动；再短会在同事挂机看剧本时
 * 误报「离线」。**宁可说「刚刚」也不要谎报「离线」** —— 谎报离线会让人以为对方走了，
 * 然后两个人同时改同一版。
 */
import type { TeamMember } from "./teamClient";

/** 多久没动静算离线（秒）。 */
export const ONLINE_WINDOW = 90;

export function isOnline(lastSeen: number | undefined, nowSec: number): boolean {
  const t = Number(lastSeen) || 0;
  if (t <= 0) return false;                                   // 从来没动过
  return nowSec - t <= ONLINE_WINDOW;
}

/** 在线人数。 */
export function onlineCount(list: TeamMember[], nowSec: number): number {
  return (list || []).filter((m) => isOnline(m.last_seen, nowSec)).length;
}

/**
 * 给人看的一句话。**在线就是「在线」，不写「刚刚」** —— 后者会让人以为他是刚来的
 * 那一刻，而实际上他可能一直坐在那儿。
 */
export function seenText(lastSeen: number | undefined, nowSec: number): string {
  const t = Number(lastSeen) || 0;
  if (t <= 0) return "还没上线过";
  const gap = Math.max(0, nowSec - t);
  if (gap <= ONLINE_WINDOW) return "在线";
  if (gap < 3600) return `${Math.max(1, Math.round(gap / 60))} 分钟前`;
  if (gap < 86400) return `${Math.round(gap / 3600)} 小时前`;
  return `${Math.round(gap / 86400)} 天前`;
}

/** 连不上服务器时那句话（同一句文案只在这里拼，免得几处各写一版）。 */
export function linkText(link: "ok" | "down" | "", total: number, online: number): string {
  if (link === "down") return "⚠️ 和团队服务器断开了 —— 现在改的东西传不上去";
  if (link === "") return `团队 ${total} 人`;
  return `连接正常 · 团队 ${total} 人 · 在线 ${online}`;
}
