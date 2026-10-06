/**
 * DirectorPanel.tsx — 导演指导面板（2026-10-06）。
 *
 * 流程（**先诊断 → 再建议 → 预览全文 → 才写回**）：
 *   1. 读选中节点的提示词；
 *   2. `diagnose()` 诊断缺哪几维（已写的维度不再建议 —— 这是"指导"与"堆词"的分界）；
 *   3. 勾选招式（默认勾选建议的那几条）；
 *   4. **预览修改后的完整提示词**（用户看到的就是将要写进去的）；
 *   5. 「应用到该节点」写回；「撤销本次指导」把招式片语全部摘掉。
 *
 * ⚠️ 只改**提示词文本**，不触发生成 ⇒ **不花钱**；因此"批量应用到所有分镜"是安全的，
 * 但仍会**先告知数量**再执行（不让用户在不知情下被改一大片）。
 */
import { useMemo, useState } from "react";

import {
  appliedMoves,
  composePrompt,
  DIRECTOR_MOVES,
  diagnose,
  stripAllMoves,
  suggestMoves,
  type MoveCategory,
} from "./directorGuidance";
import { useCanvasStore } from "./store";
import "./directorPanel.css";

const CATEGORIES: MoveCategory[] = ["景别", "运镜", "构图", "光线", "情绪", "节奏"];

export default function DirectorPanel({ onClose }: { onClose: () => void }) {
  const selectedId = useCanvasStore((s) => s.selectedId);
  const sel = useCanvasStore((s) => s.nodes.find((n) => n.id === s.selectedId));
  const allNodes = useCanvasStore((s) => s.nodes);
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);

  const prompt = String((sel?.data as Record<string, unknown> | undefined)?.prompt || "");
  const title = String((sel?.data as Record<string, unknown> | undefined)?.title || "");
  const shot = { prompt, title };
  const diag = useMemo(() => diagnose(shot), [prompt, title]);
  const suggested = useMemo(() => suggestMoves(shot), [prompt, title]);
  const [picked, setPicked] = useState<string[]>(() => suggested);
  const [msg, setMsg] = useState("");
  const [prev, setPrev] = useState<string>("");

  const preview = useMemo(() => composePrompt(prompt, picked), [prompt, picked]);
  const already = useMemo(() => appliedMoves(prompt), [prompt]);
  const shotCount = allNodes.filter((n) => String((n.data as { kind?: unknown })?.kind) === "shot").length;

  const toggle = (id: string) => {
    setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  };

  const apply = () => {
    if (!selectedId) {
      setMsg("请先在画布上选中一个镜头节点");
      return;
    }
    if (preview === prompt) {
      setMsg("提示词没有变化");
      return;
    }
    setPrev(prompt);
    updateNodeData(selectedId, { prompt: preview } as never);
    setMsg("已写回该节点（可用下面的「撤销本次指导」还原）");
  };

  const undo = () => {
    if (!selectedId) return;
    if (prev) {
      updateNodeData(selectedId, { prompt: prev } as never);
      setMsg("已还原到指导前");
      setPrev("");
      return;
    }
    if (!already.length) {
      setMsg("该节点没有本面板写入的招式");
      return;
    }
    updateNodeData(selectedId, { prompt: stripAllMoves(prompt) } as never);
    setMsg("已摘除本面板写入的招式片语");
  };

  const applyAll = () => {
    const shots = allNodes.filter((n) => String((n.data as { kind?: unknown })?.kind) === "shot");
    if (!shots.length) {
      setMsg("画布上没有分镜（shot）节点");
      return;
    }
    if (!window.confirm(`将把选中的 ${picked.length} 条招式应用到画布上全部 ${shots.length} 个分镜？\n（只改提示词文本，不会触发生成、不消耗额度）`)) {
      return;
    }
    let n = 0;
    for (const s of shots) {
      const p = String((s.data as Record<string, unknown>)?.prompt || "");
      updateNodeData(s.id, { prompt: composePrompt(p, picked) } as never);
      n += 1;
    }
    setMsg(`已应用到 ${n} 个分镜`);
  };

  return (
    <div className="dp-panel">
      <header className="dp-head">
        <span className="dp-title">导演指导</span>
        <span className="dp-sub">规则驱动的分镜改进（非大模型）</span>
        <span className="dp-spacer" />
        <button type="button" className="dp-x" onClick={onClose} title="关闭">
          ×
        </button>
      </header>

      <div className="dp-body">
        <div className="dp-diag">
          <div className="dp-sec-title">诊断</div>
          <p className="dp-diag-text">{diag.summary}</p>
          <div className="dp-current">
            <div className="dp-sec-title">当前提示词</div>
            <div className="dp-quote">{prompt || "（空）"}</div>
          </div>
        </div>

        <div className="dp-moves">
          {CATEGORIES.map((cat) => {
            const list = DIRECTOR_MOVES.filter((m) => m.category === cat);
            if (!list.length) return null;
            return (
              <div key={cat} className="dp-cat">
                <div className="dp-sec-title">
                  {cat}
                  {diag.missing.includes(cat) ? <i className="dp-miss">缺</i> : null}
                </div>
                <div className="dp-chips">
                  {list.map((m) => (
                    <button
                      type="button"
                      key={m.id}
                      className={`dp-chip${picked.includes(m.id) ? " on" : ""}`}
                      title={m.why}
                      onClick={() => toggle(m.id)}
                    >
                      {m.name}
                      {already.includes(m.id) ? " ·" : ""}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          <div className="dp-hint">
            建议项已按诊断默认勾选；已写的维度不会再建议（避免把镜头写冲突）。
          </div>
        </div>

        <div className="dp-preview">
          <div className="dp-sec-title">预览（将写回的完整提示词）</div>
          <div className="dp-quote dp-quote-preview">{preview || "（空）"}</div>
          <div className="dp-actions">
            <button type="button" className="dp-apply" onClick={apply}>
              应用到该节点
            </button>
            <button type="button" className="dp-undo" onClick={undo}>
              撤销本次指导
            </button>
            <button type="button" className="dp-all" onClick={applyAll}>
              应用到全部 {shotCount} 个分镜
            </button>
          </div>
          <div className="dp-msg">{msg}</div>
        </div>
      </div>
    </div>
  );
}
