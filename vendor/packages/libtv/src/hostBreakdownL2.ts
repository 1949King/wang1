/**
 * 逐帧拉片 L2 → 画布分镜表行 映射（Wave 0 #13 孤儿端点接线第 4 条，2026-10-15）
 * ======================================================
 * 缺口类型（与前几条不同，这条是「半成品」）：
 *   `bridgeStoryboard.ts:137` 的 `referenceBreakdownL2` **桥函数早就在**，
 *   `ReferenceBreakdownL2Shot` 类型、`bridge.ts` 的 re-export 也都在 ——
 *   但全库 **零 UI 调用者**（grep 只命中定义与导出）。
 *   ⇒ 前端比后端多走了一步，却停在半路：能力拿得到，界面入口没有。
 *
 * 补的正是那个入口 + 一层映射（后端 L2 的中文键 → 前端 `ShotlistRow` 的英文字段）。
 *
 * 为什么接 L2 而**不接 L1**（`/host/reference-breakdown`）：
 *   - L1 = `build_shot_table(video, with_depth=False)`，L2 = 同一个函数 `with_depth=True`
 *     （app/core/canvas_routes_post.py:1862 与 :1727 是同一个 `rb.build_shot_table`）。
 *   - L2 是 L1 的**超集**（多了运镜深度推断 + 可选视觉 enrich）⇒ 接 L1 等于造一条更弱的平行线。
 *   ⇒ 判：`/host/reference-breakdown`（L1）**不接**，它是 L2 的子集。
 *
 * 为什么不直接用已接的 `videoStoryboard`（`storyNodes.tsx:141` 的「📹 拉片」按钮）：
 *   那条线把 `shot`/`camera`/`description` 交给 **LLM 猜**；
 *   L2 这条线的景别/运镜是**深度图 + 置信度门槛实测**出来的（`infer_camera_move`），
 *   画面描述来自云端视觉模型 —— 两者的**证据等级不同**，不能互相替代。
 *   本文件是**并行的第二条拉片线**（不是替换）：用户在分镜表节点上显式点「深度拉片」才走。
 *
 * ⚠️ 诚实边界（后端 `reference_breakdown.py:14` 明写「宁可空着，不编」）：
 *   `景别` / `运镜` 在置信度不足或视觉未启用时是**空串**，不是默认值。
 *   本文件**原样保留空串**，绝不填「中景」「固定」—— 填了就是把「没测出来」说成「测出来了」。
 */
import {
  referenceBreakdownL2,
  type ReferenceBreakdownL2Shot,
} from "./bridgeStoryboard";
import type { ShotlistRow } from "./stores/node-factory";

/** L2 单镜的诚实状态：哪些是真测出来的，哪些是留空的。 */
export type L2ShotVerdict = {
  index: number;
  /** 景别有值= 视觉 enrich 成功 */
  hasShotSize: boolean;
  /** 运镜有值 = 深度推断过了置信度门槛 */
  hasCamera: boolean;
  /** 深度模块是否可用（不可用时后端留 camera_move.reason） */
  depthAvailable: boolean;
  /** camera_move 置信度（后端给了才有） */
  confidence?: number;
};

export type L2PullSummary = {
  ok: boolean;
  count: number;
  duration?: number;
  /** 实测出景别的镜数 / 总镜数 */
  shotSizeCount: number;
  /** 实测出运镜的镜数 / 总镜数 */
  cameraCount: number;
  /** 后端 note（诚实说明本轮哪些是真算的），逐字透传 */
  note?: string;
  /** 云端视觉是否真的用了（素材出域与否，用户关心） */
  visionUsed?: boolean;
  visionMessage?: string;
  message?: string;
};

/**
 * 一行 L2 单镜 → 哪些字段是真测的（纯函数）。
 * 判据与后端 `reference_breakdown.py:274` 一致：**绝不把「固定」当运镜结论**，
 * 所以 `运镜` 为空串时一律算「没测出来」，不做「空 = 固定」的推断。
 */
export function judgeL2Shot(shot: ReferenceBreakdownL2Shot, i = 0): L2ShotVerdict {
  const mv = String(shot?.运镜 || "").trim();
  const cm = shot?.camera_move || undefined;
  return {
    index: Number.isFinite(Number(shot?.index)) ? Number(shot?.index) : i + 1,
    hasShotSize: Boolean(String(shot?.景别 || "").trim()),
    hasCamera: mv.length > 0,
    // 后端在深度不可用时给 camera_move.move === "unknown" + reason
    depthAvailable: Boolean(cm && cm.move && cm.move !== "unknown"),
    confidence: typeof cm?.confidence === "number" ? cm.confidence : undefined,
  };
}

/**
 * 整批 L2 结果 → 分镜表行（纯函数）。
 * - `shotSize` / `camera` / `content` 取后端 L2 的实测值，**空就是空**（不填默认审美）。
 * - `duration` 用实测时长（不是猜的 3秒）。
 * - `frameUrl`：后端 `keyframe` 是**磁盘绝对路径**，而画布是 WebView，
 *   **只认 `/inbox_file/<name>`**（画布加载不了 `D:\...`）⇒ 这里不直接塞，
 *     由调用方走 `uploadAssetToHost` 或后端publish 后再填（见 storyNodes 的拉片实现）。
 */
export function mapL2ShotsToRows(shots: ReferenceBreakdownL2Shot[] | undefined): ShotlistRow[] {
  const rows: ShotlistRow[] = [];
  (shots || []).forEach((s, i) => {
    const duration = Number(s?.duration);
    const row: ShotlistRow = {
      // id 用 index 派生（**不用随机** —— 本项目禁随机效果，且 L2 有稳定 index）
      id: `l2_${Number.isFinite(Number(s?.index)) ? Number(s?.index) : i + 1}`,
      shotNo: String(
        Number.isFinite(Number(s?.index)) ? Number(s?.index) : i + 1,
      ).padStart(2, "0"),
      // ⚠️ 三处都允许空串：后端「宁可空着，不编」
      shotSize: String(s?.景别 || "").trim(),
      camera: String(s?.运镜 || "").trim(),
      content: String(s?.描述 || "").trim(),
      dialogue: "",
      duration: Number.isFinite(duration) && duration > 0 ? duration : 0,
      note: l2RowNote(s),
      memoryType: "meaning",
    };
    rows.push(row);
  });
  return rows;
}

/** 一行的备注：把「实测指标」如实带出来，不编解读。 */
function l2RowNote(s: ReferenceBreakdownL2Shot): string {
  const bits: string[] = [];
  const mv = Number(s?.motion);
  if (Number.isFinite(mv)) bits.push(`运动量${mv.toFixed(2)}`);
  const br = Number(s?.brightness);
  if (Number.isFinite(br)) bits.push(`亮度${(br * 100).toFixed(0)}%`);
  const ct = Number(s?.contrast);
  if (Number.isFinite(ct)) bits.push(`对比${(ct * 100).toFixed(0)}%`);
  const cm = s?.camera_move;
  if (cm?.reason) bits.push(cm.reason);
  else if (typeof cm?.confidence === "number") bits.push(`运镜置信度${cm.confidence.toFixed(2)}`);
  if (s?.vision === false) bits.push("视觉未命中");
  return bits.join(" · ");
}

/**
 * 一行结论：**逐字透传后端 note**，前端只在「没测出来」时补一句诚实说明。
 * 不自造「拉片完成」这种含糊话（用户需要知道哪些是真算的、哪些是留空的）。
 */
export function summarizeL2Pull(res: {
  ok: boolean;
  count?: number;
  duration?: number;
  shots?: ReferenceBreakdownL2Shot[];
  note?: string;
  vision_used?: boolean;
  vision_message?: string;
  message?: string;
}): L2PullSummary {
  if (!res.ok) {
    return {
      ok: false,
      count: 0,
      shotSizeCount: 0,
      cameraCount: 0,
      message: res.message || "深度拉片失败",
    };
  }
  const shots = res.shots || [];
  const verdicts = shots.map((s, i) => judgeL2Shot(s, i));
  const shotSizeCount = verdicts.filter((v) => v.hasShotSize).length;
  const cameraCount = verdicts.filter((v) => v.hasCamera).length;
  const out: L2PullSummary = {
    ok: true,
    count: shots.length,
    shotSizeCount,
    cameraCount,
    note: res.note,
    visionUsed: Boolean(res.vision_used),
    visionMessage: res.vision_message,
  };
  if (typeof res.duration === "number") out.duration = res.duration;
  // 诚实补充：测出几镜就说几镜，没测出的**明说**，不假装全测出来了
  if (shotSizeCount < shots.length || cameraCount < shots.length) {
    const miss: string[] = [];
    if (shotSizeCount < shots.length) miss.push(`景别 ${shotSizeCount}/${shots.length}`);
    if (cameraCount < shots.length) miss.push(`运镜 ${cameraCount}/${shots.length}`);
    out.message = `深度拉片 ${shots.length} 镜（实测 ${miss.join(" · ")}，其余留空未猜）`;
  }
  return out;
}

/**
 * 深度拉片（Wave 0 #13 第 4 条接线）。
 * ⚠️ `use_vision=true` 会让**素材出域**（云端视觉模型）⇒ 单独参数暴露，
 * 由 UI 显式勾选，绝不默认开（项目既有纪律：素材出域须用户显式开启）。
 */
export async function pullDepthBreakdown(input: {
  videoPath: string;
  outDir?: string;
  threshold?: number;
  useVision?: boolean;
  visionModel?: string;
}): Promise<L2PullSummary & { rows: ShotlistRow[] }> {
  if (!input.videoPath) {
    return {
      ok: false,
      count: 0,
      shotSizeCount: 0,
      cameraCount: 0,
      rows: [],
      message: "需要参考视频路径",
    };
  }
  try {
    const res = await referenceBreakdownL2({
      video_path: input.videoPath,
      out_dir: input.outDir || ".workbuddy/tmp/breakdown_l2",
      threshold: input.threshold ?? 0.3,
      use_vision: Boolean(input.useVision),
      vision_model: input.visionModel || "",
    });
    const summary = summarizeL2Pull(res);
    return {
      ...summary,
      rows: res.ok ? mapL2ShotsToRows(res.shots) : [],
    };
  } catch (e) {
    return {
      ok: false,
      count: 0,
      shotSizeCount: 0,
      cameraCount: 0,
      rows: [],
      message: `深度拉片异常: ${e}`,
    };
  }
}