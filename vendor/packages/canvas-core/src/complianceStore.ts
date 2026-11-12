/**
 * 免责声明的"只出现一次"存储（2026-11-12）。
 *
 * 规则：
 * - 首次进入必须滑到底并确认；
 * - 确认后不再出现；
 * - **条款版本变化时会再次提示**（合规要求，不能让用户对着旧条款以为已同意新条款）。
 */
import { BRIDGE, authHeaders } from "./bridge";
import { COMPLIANCE_VERSION } from "./complianceDoc";

export const COMPLIANCE_KEY = "shiguang:compliance:accepted:v1";

export type ComplianceAcceptance = { version: string; at: string };

export function readAcceptance(): ComplianceAcceptance | null {
  try {
    const raw = window.localStorage.getItem(COMPLIANCE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw) as ComplianceAcceptance;
    if (!obj || typeof obj.version !== "string") return null;
    return obj;
  } catch {
    return null;
  }
}

export function acceptCompliance(version: string = COMPLIANCE_VERSION, now: string = new Date().toISOString()): boolean {
  try {
    const rec: ComplianceAcceptance = { version, at: now };
    window.localStorage.setItem(COMPLIANCE_KEY, JSON.stringify(rec));
    return true;
  } catch {
    return false;
  }
}

/** 是否需要弹首屏：没确认过，或确认的是旧版本。 */
export function needsCompliance(): boolean {
  const rec = readAcceptance();
  if (!rec) return true;
  return rec.version !== COMPLIANCE_VERSION;
}

/**
 * 滚动是否已到底（纯函数，便于单测）。
 * 留 4px 容差：高分屏/缩放会让 scrollTop 出现小数，严格相等会导致按钮永远不亮。
 */
export function isScrolledToBottom(scrollTop: number, clientHeight: number, scrollHeight: number, tolerance = 4): boolean {
  const top = Number(scrollTop) || 0;
  const client = Number(clientHeight) || 0;
  const height = Number(scrollHeight) || 0;
  if (height <= client) return true;          // 内容不够长，无需滚动
  return top + client >= height - tolerance;
}

/** 纯函数：决定要不要弹（远端优先，远端不可用才回落到本地）。 */
export function decideCompliance(
  remote: { accepted: boolean; version: string } | null,
  localAcceptedVersion: string | null,
  currentVersion: string = COMPLIANCE_VERSION,
): boolean {
  if (remote) return !remote.accepted || remote.version !== currentVersion;
  if (!localAcceptedVersion) return true;
  return localAcceptedVersion !== currentVersion;
}

/** 读服务端记录（跨 profile / 跨重启都在）。失败返回 null。 */
export async function fetchRemoteAcceptance(): Promise<{ accepted: boolean; version: string } | null> {
  try {
    const res = await fetch(BRIDGE + "/host/compliance/acceptance", { headers: authHeaders(true) });
    const data = (await res.json()) as { ok?: boolean; accepted?: boolean; version?: string };
    if (data && data.ok) return { accepted: Boolean(data.accepted), version: String(data.version || "") };
  } catch {
    /* 后端不可用 ⇒ 回落 localStorage */
  }
  return null;
}

/** 写服务端记录；失败返回 false（本地仍会写，最多下次再弹）。 */
export async function acceptComplianceRemote(version: string = COMPLIANCE_VERSION): Promise<boolean> {
  try {
    const res = await fetch(BRIDGE + "/host/compliance/accept", {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ version, at: new Date().toISOString() }),
    });
    const data = (await res.json()) as { ok?: boolean };
    return Boolean(data && data.ok);
  } catch {
    return false;
  }
}
