/**
 * NoviceSequenceBar — 小白模式的「序列总览条」（2026-11-15 加）
 *
 * 为什么需要：实测摆卡时会连续丢掉三个信息 ——
 *   ① 不知道**总长**（每张卡写着 3s，但加起来多少没人知道）
 *   ② 不知道**还缺什么**（摆完十张，仍有几张没出画面，肉眼看不出来）
 *   ③ 不知道自己离「30 秒」还差多远（于是要么摆不够、要么摆过头）
 *
 * 这三个"不知道"才是"信息量不足"的真实含义 —— 不是字段不够，是缺**汇总视角**。
 *
 * 设计约束（必须遵守）：
 * - **不在画布上引入顺序**：只读统计，不排序、不编号、不要求用户排列。
 *   顺序仍然完全自由，这里只回答"现在这一堆加起来是多少"。
 * - **不新增数据字段**：镜头数与时长为已有字段的派生值，零改数据模型。
 * - **防 React #185**：selector 只返回 store 里的稳定引用（`s.nodes`），
 *   派生计算放在 useMemo，绝不在 selector 里 filter/map 出新数组。
 */
import { memo, useMemo } from "react";
import { useCanvasStore } from "../store";
import "./novice-sequence-bar.css";

/** 只读关心的几个字段，避免把整个 NodeData 联合类型拖进来 */
type ShotLike = { kind?: string; duration?: number; imageUrl?: string };

/** 目标时长（秒）：30 秒漫剧。18-36 视为合理区间，超出给提示 */
const TARGET_SEC = 30;
const LOW = 18;
const HIGH = 36;

export const NoviceSequenceBar = memo(function NoviceSequenceBar() {
  // ⚠️ 只订阅稳定引用；filter/累加全部放 useMemo（防 #185 无限重渲染）
  const nodes = useCanvasStore((s) => s.nodes);

  const stats = useMemo(() => {
    let count = 0;
    let total = 0;
    let noImage = 0;
    for (const n of nodes) {
      const d = n.data as ShotLike | undefined;
      if (!d || d.kind !== "shot") continue;
      count += 1;
      total += Number(d.duration) || 0;
      if (!d.imageUrl) noImage += 1;
    }
    return { count, total, noImage };
  }, [nodes]);

  if (stats.count === 0) return null;

  const tone = stats.total < LOW ? "short" : stats.total > HIGH ? "long" : "ok";
  const gap = Math.abs(TARGET_SEC - stats.total).toFixed(1);

  return (
    <div
      className={`nv-seqbar nv-seqbar--${tone}`}
      title={
        `当前画布上的镜头汇总：${stats.count} 个镜头，共 ${stats.total.toFixed(1)} 秒。` +
        `\n这只是统计，不会改变卡片的摆放顺序。`
      }
    >
      <span className="nv-seqbar-main">
        🎬 {stats.count} 镜 · {stats.total.toFixed(1)} 秒
      </span>
      {stats.noImage > 0 ? (
        <span className="nv-seqbar-warn">{stats.noImage} 张还没出画面</span>
      ) : (
        <span className="nv-seqbar-done">画面齐了</span>
      )}
      {tone === "short" ? (
        <span className="nv-seqbar-hint">离 {TARGET_SEC} 秒还差 {gap}s</span>
      ) : null}
      {tone === "long" ? (
        <span className="nv-seqbar-hint">超出 {TARGET_SEC} 秒 {gap}s</span>
      ) : null}
    </div>
  );
});
