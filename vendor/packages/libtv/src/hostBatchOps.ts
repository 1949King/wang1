/**
 * hostBatchOps.ts — 批量作业的画布侧接线（Wave 0 #13 孤儿端点回收·第1 条）
 * ============================================================================
 * 背景（孤儿端点差集实测，非推测）
 * --------------------------------------------------------------------------------
 * 后端 `/host/batch-to-timeline`（`app/core/canvas_routes_post.py:1036`）已完整实现：
 * 按 `job_id` 把**已完成分段逐条** `emit_canvas_to_editor(...)` 入时间线，
 * 支持 `indices` 精确指定分镜序号，失败分段单独收集在 `errors` 里不中断整批。
 *
 * 但前端**零调用**（差集：后端 57 个 `/host/*` vs 前端引用 53 个，本条在孤儿侧）。
 * 缺口后果（读 `App.tsx:1943` 确认）：批量任务跑完后，前端只走`concatVideos`
 * **拼成一个整片**塞进画布 —— 逐段入轨、逐段二次编辑、逐段重拍的能力后端全有了，
 * 前端却拿不到，只能拿回一个不可拆的大块。
 *
 * 为什么单独成文件（铁律）
 * --------------------------------------------------------------------------------
 * `bridge.ts` 已1868 行 / 基线 2046 行 —— 体积棘轮顶格。**不得**往里加新桥函数。
 * 范式照抄本轮已验证的样板 `storeIdempotent.ts`：判定/接线逻辑落独立文件，
 * 母文件只留 import。
 *
 * 接线纪律
 * --------------------------------------------------------------------------------
 * · 画布是 WebView，加载不了 `D://...` 本地路径，只认 `/inbox_file/<name>`
 *   ⇒ 拿到的 `path` 一律不能直接塞进节点 `videoUrl`，必须由后端给出 `video_url`。
 * · 本模块**不自动入轨**：入轨会改用户时间线（真相源 `EditorModule._clips`），
 *   必须用户显式点击，遵守既有「生成动作需显式批准」纪律（同repair-image 的处理）。
 */
import { BRIDGE, bridgeToken } from "./bridge";

/** 单段入轨结果（与后端 `pushed` 元素同形）。 */
export type BatchTimelineItem = {
  index?: number;
  path?: string;
  title?: string;
};

/** 单段入轨失败（与后端 `errors` 元素同形）。 */
export type BatchTimelineError = {
  index?: number;
  path?: string;
  message?: string;
};

export type BatchToTimelineResult = {
  ok: boolean;
  /** 分段总数（成功 + 失败）。 */
  pushed: number;
  failed: number;
  items: BatchTimelineItem[];
  errors: BatchTimelineError[];
  job_id?: string;
  message?: string;
};

/**
 * 把批量作业里已完成的分段逐条入剪辑时间线。
 *
 * @param jobId  `POST /host/video-batch` 返回的 job_id（前端 `startVideoBatch` 产物）
 * @param indices 可选，只入轨指定分镜序号（`number[]`，缺省 = 全部已完成分段）
 *
 * 后端语义（勿臆测）：只入轨 `status === "done"` **且** 有 `local_path` 的分段；
 * 没有任何可入轨分段时返回 400 +「无已完成片段可入轨」。
 */
export async function pushBatchToTimeline(
  jobId: string,
  indices?: number[],
): Promise<BatchToTimelineResult> {
  if (!jobId) {
    return { ok: false, pushed: 0, failed: 0, items: [], errors: [], message: "job_id 为空" };
  }
  try {
    const res = await fetch(`${BRIDGE}/host/batch-to-timeline`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shiguang-Token": bridgeToken(),
      },
      body: JSON.stringify(indices?.length ? { job_id: jobId, indices } : { job_id: jobId }),
    });
    const json = await res.json();
    return {
      ok: Boolean(json?.ok),
      pushed: Number(json?.pushed || 0),
      failed: Number(json?.failed || 0),
      items: Array.isArray(json?.items) ? json.items : [],
      errors: Array.isArray(json?.errors) ? json.errors : [],
      job_id: json?.job_id,
      message: json?.message,
    };
  } catch (e: unknown) {
    return {
      ok: false,
      pushed: 0,
      failed: 0,
      items: [],
      errors: [],
      message: e instanceof Error ? e.message : String(e),
    };
  }
}

/**
 * 把入轨结果整理成一句人话状态（给 `setStatus` 用）。
 *
 * 刻意把失败数也说出来 —— 部分入轨成功时最容易被静默吞掉，用户会以为全进去了。
 */
export function summarizeBatchPush(res: BatchToTimelineResult): string {
  if (!res.ok) {
    return `❌ 逐段入轨失败：${res.message || "未知错误"}`;
  }
  if (res.pushed === 0) {
    return `⚠️ 没有分段成功入轨${res.failed ? `（${res.failed} 段失败）` : ""}`;
  }
  const tail = res.failed ? ` ·⚠️ ${res.failed} 段失败` : "";
  return `✅ ${res.pushed} 段已入剪辑时间线${tail}`;
}

/**
 * 从批量状态里挑出「已完成且有产物」的分段序号（供用户勾选部分入轨）。
 *
 * 口径与后端入轨判据**保持一致**：`status === "done"` 且有可播放 url。
 * 这里只做筛选，不发起任何写操作。
 */
export function pickDoneIndices(
  segments: { status?: string; video_url?: string; path?: string }[] | undefined,
): number[] {
  if (!segments?.length) return [];
  const out: number[] = [];
  segments.forEach((s, i) => {
    if (s?.status === "done" && (s.video_url || s.path)) out.push(i);
  });
  return out;
}