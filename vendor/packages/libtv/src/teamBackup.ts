/**
 * 「拉取前先另存一份」—— 防「一拉就没了」（2026-11-04 · 画布 0.3.47）
 *
 * 为什么需要：拉取是**覆盖式**的，`loadProjectBundle()` 会把当前画布整个换掉，
 * 而自动保存在几秒后就把同一个工程 id 的本机存档也写成了新内容 —— 用户手上那一版
 * 从此不存在任何地方。二次确认弹窗只能拦住「手滑」，拦不住「我以为我上传过了」。
 *
 * 为什么不做自造的「快照格式 + 恢复面板」：本地工程本来就是 localStorage 里的
 * bundle，另存一份就是「复制成新 id + 改个名字」——走的就是「我的画布」那条现成
 * 链路。用户能自己找到、能打开、也能删；不需要为「备份」再学一套恢复 UI。
 *
 * 🔴 两条纪律：
 *   1. **失败必须说出来**（配额不足 / 读不到源工程），让调用方决定要不要硬上，
 *      不许静默当成功 —— 备份失败却照拉，比没有备份更坏（人以为有）。
 *   2. 备份的是**内存里现在的画布**，不是「上次自动保存的存档」：自动保存有延迟，
 *      拿存档当备份＝少存最后几秒的改动，而那几秒常常就是用户真正心疼的部分。
 */
import { useCanvasStore, type CanvasSnapshot, type ProjectBundle, type ProjectMeta } from "./store";
import {
  ensureProjectCanvases,
  readProjectBundle,
  readProjectsIndex,
  uid,
  writeProjectBundle,
  writeProjectsIndex,
} from "./stores/project-storage";

export type BackupOutcome = {
  /** 备份是否落盘成功。`skipped` 时也是 true（空画布没什么可备份，不算失败） */
  ok: boolean;
  /** 空画布/没内容 ⇒ 没生成备份，但不算失败 */
  skipped?: boolean;
  /** 新工程的 id（能在「我的画布」里打开它） */
  id?: string;
  /** 新工程的名字，形如「第三集（覆盖前 11-04 15:20）」 */
  name?: string;
  /** ok=false 时的原因（直接给人看） */
  why?: string;
};

const pad2 = (n: number) => String(n).padStart(2, "0");

/**
 * 备份工程的名字。带上「覆盖前 + 时间」，因为用户事后要找的是**那一刻**的版本；
 * 只写「副本」会攒出三个「副本 (2)」「副本 (3)」，谁也分不清哪个是想要的。
 */
export function backupName(srcName: string, at: Date): string {
  const stamp = `${pad2(at.getMonth() + 1)}-${pad2(at.getDate())} ${pad2(at.getHours())}:${pad2(at.getMinutes())}`;
  return `${srcName || "未命名工作区"}（覆盖前 ${stamp}）`;
}

/** 把当前画布另存为一个新的本地工程，返回它是谁。副作用只碰 localStorage。 */
export function backupBeforePull(now: Date = new Date()): BackupOutcome {
  const s = useCanvasStore.getState();
  const nodes = s.nodes || [];
  const edges = s.edges || [];
  if (!nodes.length && !edges.length) {
    return { ok: true, skipped: true, why: "当前画布是空的，没有会被覆盖的东西" };
  }

  const srcId = s.activeProjectId || "";
  const src = srcId ? readProjectBundle(srcId) : null;
  const savedAt = now.toISOString();
  const canvasId = s.activeCanvasId || src?.activeCanvasId || uid("canvas");
  const snapshot: CanvasSnapshot = {
    id: canvasId,
    name: s.activeCanvasName || "画布 1",
    nodes,
    edges,
    savedAt,
  };
  // 源工程若有多画布，备份里全都留着 —— 只把「当前这张」换成内存里的现状。
  const others = (src ? ensureProjectCanvases(src) : []).filter((c) => c.id !== canvasId);

  const copyId = uid("proj");
  const name = backupName(src?.name || s.activeProjectName || "", now);
  const bundle: ProjectBundle = {
    schemaVersion: src?.schemaVersion,
    version: src?.version,
    id: copyId,
    name,
    dramaTitle: s.dramaTitle || "",
    episode: s.episode || "",
    nodes,
    edges,
    savedAt,
    stage3d: s.getStage3dSnapshot?.(),
    canvases: [snapshot, ...others],
    activeCanvasId: canvasId,
    tier: src?.tier,
    aiVersions: src?.aiVersions,
  };

  try {
    writeProjectBundle(bundle);
  } catch (e) {
    // 配额不足最常见：工程里嵌了大图（data: URL）。原话回给用户，别翻译成「失败」。
    return { ok: false, why: e instanceof Error ? e.message : String(e) };
  }

  const meta: ProjectMeta = {
    id: copyId,
    name,
    savedAt,
    nodeCount: nodes.length,
    tier: src?.tier,
  };
  writeProjectsIndex([meta, ...readProjectsIndex().filter((m) => m.id !== copyId)]);
  return { ok: true, id: copyId, name };
}
