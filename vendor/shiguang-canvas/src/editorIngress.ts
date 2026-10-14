/**
 * editorIngress.ts — 画布节点 → 剪辑时间线的**入轨编排**（Wave 0 #13 抽模块）
 * ============================================================================
 * 为什么要抽出来
 * --------------------------------------------------------------------------------
 * `App.tsx` 已1999 行 / 阈值 2000（`check_file_size.py` 存量冻结，只减不增）。
 * 入轨编排原本是一坨 60 行的循环塞在 App.tsx 里，任何加法都会撞棘轮。
 * 按项目纪律「超容差必须拆模块，**不得放宽基线**」——把编排搬到这里，
 * App.tsx 只留一次调用。这是本轮解冻理由（2026-10-15，用户授权 Wave 0）。
 *
 * 单一通道纪律（重要）
 * --------------------------------------------------------------------------------
 * 本模块是**节点 → 时间线**的唯一编排入口。批量作业走
 * `pushBatchToTimeline`（`hostBatchOps.ts`，后端快通道：直接用 `local_path`，
 * 不必经前端 fetch blob 回传），普通节点走 `sendBlobToEditor`。
 * **两条分支共用同一个对外函数 `ingestNodes`**，由 `batchJobId` 是否存在自动分流，
 * 不新增第二个 UI 按钮、不新增第二条通道 —— 遵守「禁止造第二套」铁律。
 *
 * 真相源与纪律
 * --------------------------------------------------------------------------------
 * · 时间线真相源 = `EditorModule._clips`；入轨**改用户时间线**，必须用户显式点击，
 *   本模块**不自动执行**（遵守既有「生成 / 写时间线动作需显式批准」纪律，
 *   与 `repair-image` 局部重绘的处理一致）。
 * · 画布是 WebView，加载不了 `D://...` 本地路径，只认 `/inbox_file/<name>`。
 */
import type { Node } from "@xyflow/react";
import type { NodeData } from "./store";
import { dataUrlToBlob, sendBlobToEditor, type BridgePrefs } from "./bridge";
import { pushBatchToTimeline, pickDoneIndices } from "./hostBatchOps";
import type { BatchStatusResult } from "./bridge";

/**
 * 从节点数据取「可用于入轨的图」。
 *
 * ⚠️ 本函数原为 `App.tsx` 内的私有局部常量（`App.tsx:1310`），因入轨编排抽模块
 * 一并搬出。**单一真相源**：不保留 App.tsx 侧的副本，否则又是「同一语义两条链路」。
 */
export function nodeImageUrl(data: NodeData): string {
  if (
    data.kind === "shot" ||
    data.kind === "image" ||
    data.kind === "director" ||
    data.kind === "panorama" ||
    data.kind === "digitalHuman"
  ) {
    return data.imageUrl || "";
  }
  if (data.kind === "animation") return data.sheetUrl || "";
  if (data.kind === "source") return data.imageUrl || "";
  if (data.kind === "video") return data.posterUrl || data.firstFrameUrl || "";
  return "";
}

/** 入轨的外部依赖（由 App.tsx 注入，避免本模块反向依赖 store）。 */
export type IngestDeps = {
  nodes: Node[];
  setStatus: (s: string) => void;
  setGenerating: (b: boolean) => void;
  prefs: BridgePrefs;
};

/** 从节点数据里取「可入轨的产物」三元组；无可入轨产物返回 null。 */
function resolveArtifact(d: NodeData):
  | { kind: "video"; url: string; duration: number }
  | { kind: "audio"; url: string; duration: number }
  | { kind: "image"; url: string; duration: number }
  | null {
  if (d.kind === "video" && d.videoUrl) {
    return { kind: "video", url: d.videoUrl, duration: Number(d.duration) || 0 };
  }
  if (d.kind === "digitalHuman") {
    // 数字人节点按音频优先（图 + 音频分两条轨，由调用方拆开处理）
    // ⚠️ `DigitalHumanData` 无 `duration` 字段（TS2339）—— 时长按 0 传，
    //   由剪辑侧从音频/视频产物自身读取，不猜。
    if (d.audioUrl) return { kind: "audio", url: d.audioUrl, duration: 0 };
    if (d.videoUrl) return { kind: "video", url: d.videoUrl, duration: 0 };
    if (d.imageUrl) return { kind: "image", url: d.imageUrl, duration: 0 };
    return null;
  }
  if ((d.kind === "audio" || d.kind === "music") && d.audioUrl) {
    return { kind: "audio", url: d.audioUrl, duration: Number(d.duration) || 0 };
  }
  const imageUrl = nodeImageUrl(d);
  if (imageUrl) {
    return { kind: "image", url: imageUrl, duration: d.kind === "shot" ? Number(d.duration) || 0 : 0 };
  }
  return null;
}

/**
 * 节点集合 → 剪辑时间线。
 *
 * @param deps 注入的外部依赖（nodes / setStatus / setGenerating / prefs）
 * @param batchJobId 批量作业 job_id。**存在时走后端快通道**（逐段直接
 *   `emit_canvas_to_editor`，不经前端 blob 中转）；缺省走逐节点前端通道。
 * @returns 实际入轨条数；无产物时为 0（已 `setStatus` 说明原因）
 */
export async function ingestNodes(
  deps: IngestDeps,
  batchJobId?: string | null,
  batchSegments?: BatchStatusResult["segments"],
): Promise<number> {
  const { nodes, setStatus, setGenerating, prefs } = deps;

  // ── 快通道：批量作业走后端逐段入轨 ──
  if (batchJobId) {
    const indices = pickDoneIndices(batchSegments);
    setStatus(`⏬ 批量入轨中（${indices.length || "全部"} 段）…`);
    setGenerating(true);
    try {
      const res = await pushBatchToTimeline(batchJobId, indices.length ? indices : undefined);
      setStatus(
        res.ok && res.pushed > 0
          ? `✅ 批量入轨完成：${res.pushed} 段${res.failed ? ` · ⚠️ ${res.failed} 段失败` : ""}`
          : res.ok
            ? `⚠️ 没有分段成功入轨${res.failed ? `（${res.failed} 段失败）` : ""}`
            : `❌ 批量入轨失败：${res.message || "未知错误"}`,
      );
      return res.pushed;
    } finally {
      setGenerating(false);
    }
  }

  // ── 常规通道：逐节点入轨 ──
  const list = nodes.filter((n) => resolveArtifact(n.data as NodeData) !== null);
  if (!list.length) {
    setStatus("没有带图/视频的节点可入轨");
    return 0;
  }
  setGenerating(true);
  let ok = 0;
  for (let i = 0; i < list.length; i++) {
    const n = list[i];
    const d = n.data as NodeData;
    const art = resolveArtifact(d);
    if (!art) continue;
    setStatus(`入轨 ${i + 1}/${list.length}…`);
    try {
      const title = ("title" in d ? d.title : "") || `${d.kind}_${n.id}`;
      const prefix = String(i + 1).padStart(2, "0");
      const link = { node_id: n.id, kind: d.kind };
      if (art.kind === "video" || art.kind === "audio") {
        const resp = await fetch(art.url);
        const blob = await resp.blob();
        // 扩展名按真实 MIME 判定，别硬编码 —— 旧代码 audio 一律 mp3，
        // 但部分音频是 wav，落错扩展名会让剪辑侧解码异常。
        const ext =
          blob.type.includes("mpeg") || blob.type.includes("mp3")
            ? "mp3"
            : blob.type.includes("wav") || blob.type.includes("wave")
              ? "wav"
              : "mp4";
        await sendBlobToEditor(blob, `${prefix}_${title}.${ext}`, prefs, {
          title,
          duration_sec: art.duration,
          ...link,
        });
      } else {
        const blob = await dataUrlToBlob(art.url);
        await sendBlobToEditor(blob, `${prefix}_${title}.png`, prefs, {
          title,
          duration_sec: art.duration,
          ...link,
        });
      }
      // 数字人节点：音频入轨后再补一条形象图，形成双轨
      if (d.kind === "digitalHuman" && d.imageUrl && art.kind !== "image") {
        const imgBlob = await dataUrlToBlob(d.imageUrl);
        await sendBlobToEditor(imgBlob, `${prefix}_${title}.png`, prefs, {
          title: `${title}·形象`,
          ...link,
        });
      }
      ok += 1;
    } catch (e) {
      // 单条失败不中断整批 —— 但必须留痕（旧代码 `catch { /*continue */ }` 静默吞掉）
      setStatus(`入轨 ${i + 1} 失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }
  setStatus(`全部入轨完成：${ok}/${list.length}`);
  setGenerating(false);
  return ok;
}