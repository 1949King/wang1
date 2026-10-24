/**
 * 3D 导演台产物 → 剪辑时间线（模式 B · 收尾刀，2026-10-12 用户授权解冻 stage3d-core）
 * =================================================================================
 * 背景：3D 导演台能导出五类产物 —— 白模动作视频 / 首尾帧 / 批量分镜 / 三视图 /
 * ControlNet 三通道。它们以前全部止步于「落进画布 inbox」，人要自己去找、再手动
 * 导入剪辑。**「3D-BOX」这条线到产物落盘就断了**，本模块把最后一跳接上。
 *
 * 为什么复用 `/ingest_path` 而不是新增 `/host/stage3d-to-timeline`：
 *   `POST /ingest_path`（app/core/canvas_routes_post.py:274）本来就是
 *   「本地路径 → 落 inbox → 可选入轨」的端点，`send_to_editor` 已是它的原生参数。
 *   再写一条 `/host/stage3d-to-timeline` 就是同一件事的**第二条链路**——本项目反复
 *   出现的反模式（frozen_zones.json · canvas-magnetic-intent 的不变量写得明白：
 *   「分支只允许存在于一处 —— 云端/本地各写一条调用链是本项目反复出现的反模式」）。
 *   ⚠️ 现状核实：`/ingest_path` 在后端已存在但**前后端都没有调用者**（全库 grep 仅见
 *   定义与注释）。本条是它的第一个真实调用方。
 *
 * ⚠️ 唯一入轨入口 = `sendArtifactToTimeline()`。禁止在别处自己 fetch `/ingest_path`，
 *    否则又会退化成两条链路（这正是本模块存在的理由）。
 *
 * 本模块**不碰**任何 canvas_bridge.py 符号 ⇒ stage3d-core 的两条端口不变量
 * （bridge 18765 / 静态 3011·dev 3010）与「人模材质/骨名映射」等不变量全部未动。
 */
import { useSyncExternalStore } from "react";
import { BRIDGE, uploadAssetToHost } from "./bridge";

/** 产物类型（决定剪辑侧按视频还是静图处理） */
export type Stage3dArtifactKind = "video" | "image";

export type Stage3dArtifact = {
  /** 稳定 id（同一路径重复发布时复用） */
  id: string;
  /** 本机绝对路径。画布是 WebView，读不了本地文件，只能把这个路径**回传**给后端 */
  path: string;
  /** 显示名（同时作为入轨后的片段标题） */
  title: string;
  kind: Stage3dArtifactKind;
  /** 出处，作 /ingest_path 的 source（stage3d_pose_video / stage3d_frames / …） */
  source: string;
  /** 已知时长（秒）；0 / 缺省 = 未知，交给剪辑侧按素材实际时长处理 */
  durationSec?: number;
  /** 发布时刻（ms），用于「最近一条」排序 */
  createdAt: number;
};

/** 面板/按钮只需回溯最近几次导出，不做无限增长 */
const MAX_KEEP = 8;

let artifacts: Stage3dArtifact[] = [];
const listeners = new Set<() => void>();

/** 变更通知：只在自己发布时触发，不引入任何轮询 */
function notify(): void {
  for (const l of listeners) l();
}

/** 订阅产物列表变化（React 用 `useSyncExternalStore` 消费） */
export function subscribeArtifacts(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** 快照必须是**同一引用**直到下次发布，否则 useSyncExternalStore 会无限重渲染 */
export function getArtifactsSnapshot(): Stage3dArtifact[] {
  return artifacts;
}

/** 最近一条产物（无产物时 null） */
export function getLatestArtifact(): Stage3dArtifact | null {
  return artifacts.length > 0 ? artifacts[0] : null;
}

/**
 * 发布一件产物。导出函数在「文件真的落盘之后」调用这里。
 *
 * 同一路径重复发布 = **移到队首并更新元信息**（不新增一条）：白模视频重录、
 * 批量分镜重跑都会产出新路径，但用户回头再点「重发同一件」不该堆出重复条目。
 */
export function publishStage3dArtifact(
  input: Omit<Stage3dArtifact, "id" | "createdAt">,
): Stage3dArtifact {
  const entry: Stage3dArtifact = {
    ...input,
    id: `a3d_${Math.abs(hashPath(input.path))}_${input.source}`,
    createdAt: Date.now(),
  };
  artifacts = [entry, ...artifacts.filter((a) => a.path !== entry.path)].slice(0, MAX_KEEP);
  notify();
  return entry;
}

/** 仅测试与「清空历史」用 */
export function __resetStage3dArtifacts(): void {
  artifacts = [];
  notify();
}

/** 轻量字符串哈希（只为生成稳定 id，不做加密用途） */
function hashPath(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return h;
}

export type TimelineSendResult = { ok: boolean; message: string };

/**
 * 把产物的**本地路径**回传给后端入轨。这是全项目唯一的 3D 产物入轨通道。
 *
 * 诚实失败：网络异常 / HTTP 非 2xx / 后端 success=false 都返回 ok:false +
 * 中文可读原因，绝不谎报「已发送」。
 */
export async function sendArtifactToTimeline(a: Stage3dArtifact): Promise<TimelineSendResult> {
  if (!a || !a.path) {
    return { ok: false, message: "产物路径为空，未发送（请先导出产物）" };
  }
  try {
    const res = await fetch(`${BRIDGE}/ingest_path`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: a.path,
        title: a.title,
        source: a.source,
        // ★ 关键：后端 ingest_local_file(send_to_editor=True) → emit_canvas_to_editor 入轨
        send_to_editor: true,
        kind: a.kind,
        duration_sec: a.durationSec ?? 0,
      }),
    });
    let data: Record<string, unknown> | null = null;
    try {
      data = (await res.json()) as Record<string, unknown>;
    } catch {
      data = null;
    }
    if (!res.ok || !data || data.success !== true) {
      const msg = (data?.message as string) || `HTTP ${res.status}`;
      return { ok: false, message: `送入剪辑失败：${msg}` };
    }
    return { ok: true, message: String(data.message || `已送入剪辑：${a.title}`) };
  } catch (e) {
    return { ok: false, message: `送入剪辑异常：${(e as Error)?.message || e}` };
  }
}

/**
 * 发送「最近一条产物」。给「一键送时间线」按钮用 —— 按钮不关心是哪一件，
 * 关心的是「我刚导出的那件」。
 */
export async function sendLatestArtifactToTimeline(): Promise<TimelineSendResult> {
  const latest = getLatestArtifact();
  if (!latest) {
    return {
      ok: false,
      message: "还没有可发送的产物：请先导出白模动作视频 / 首尾帧 / 三视图 / ControlNet",
    };
  }
  return sendArtifactToTimeline(latest);
}

/** React 侧读「最近一条产物」（enabled/disabled 与按钮文案用） */
export function useLatestStage3dArtifact(): Stage3dArtifact | null {
  const list = useSyncExternalStore(subscribeArtifacts, getArtifactsSnapshot, getArtifactsSnapshot);
  return list.length > 0 ? list[0] : null;
}

// ─────────────────────────────────────────────────────────────────────────────
// data URL / Blob 形态的产物（缺口② 刀2）
// ─────────────────────────────────────────────────────────────────────────────

/** `data:image/png;base64,....` → Blob；不是合法 data URL 返回 null（不抛）。 */
export function dataUrlToBlob(dataUrl: string): Blob | null {
  if (typeof dataUrl !== "string") return null;
  const m = /^data:([^;,]*)(;base64)?,(.*)$/s.exec(dataUrl);
  if (!m) return null;
  const mime = m[1] || "application/octet-stream";
  const body = m[3] || "";
  try {
    if (m[2]) {
      const bin = atob(body);
      const buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      return new Blob([buf], { type: mime });
    }
    return new Blob([decodeURIComponent(body)], { type: mime });
  } catch {
    return null;
  }
}

/**
 * 上传一件「只在内存里」的产物，换到**本机路径**后登记。
 *
 * 为什么必须多这一步：ControlNet 三通道 / 三视图这类产物在画布这边是 data URL，
 * 而画布是 WebView —— **读不了本地文件、也没有路径**；能送剪辑的只有后端认得的
 * 本机路径。所以先经 `/host/upload-asset` 落进画布 inbox（顺带解决「只能浏览器
 * 另存为」的现状），再走统一的登记 + 送时间线通道。
 *
 * 诚实失败：上传失败 / 后端没回 `path` ⇒ 返回 null，**不登记半成品**。
 */
export async function publishUploadedArtifact(
  blob: Blob,
  opts: { title: string; source: string; kind: Stage3dArtifactKind; filename: string },
): Promise<Stage3dArtifact | null> {
  let up: { ok: boolean; path?: string; message?: string };
  try {
    up = await uploadAssetToHost(new File([blob], opts.filename, { type: blob.type || "application/octet-stream" }));
  } catch {
    return null;
  }
  if (!up?.ok || !up.path) return null;
  return publishStage3dArtifact({
    path: up.path,
    title: opts.title,
    kind: opts.kind,
    source: opts.source,
  });
}

/**
 * 把 ControlNet 三通道 data URL 批量入库并登记，返回**成功登记数**。
 *
 * 为什么只接这一类（2026-10-12 实测结论，别照抄「四类产物各加一行」）：
 *   · 首尾帧 / 批量分镜 = **生视频的输入**（走 `onExportFirstLast` / `onExportBatch`
 *     立刻去生成视频），登记成时间线片段是错的；
 *   · BVH = 骨骼动画文件，**剪辑时间线放不了**；
 *   · 三视图 = 已由父组件 `onCaptureActorViews` → `addCaptureToCanvas` 落成画布节点，
 *     画布节点自身已有「→ 剪辑」通道，重复登记只会出两份；
 *   · 相机截图 = 同上已有画布节点通道。
 *   ⇒ 真正「只能浏览器另存为、且本身是成品素材」的，只剩 ControlNet 三通道。
 */
export async function registerControlNetArtifacts(
  packs: { name: string; data: string }[],
): Promise<number> {
  let ok = 0;
  for (const p of packs) {
    const blob = dataUrlToBlob(p.data);
    if (!blob) continue;
    const a = await publishUploadedArtifact(blob, {
      title: p.name.replace(/\.png$/i, ""),
      source: "stage3d_controlnet",
      kind: "image",
      filename: p.name,
    });
    if (a) ok += 1;
  }
  return ok;
}
