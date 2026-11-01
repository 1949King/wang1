/**
 * 人物卡面板（2026-11-01 · C 项 UI）
 *
 * 三段式：
 *   ① 字段编辑（下拉 + 可自由输入）
 *   ② **英文预览**（调后端 /host/person-card/preview，显示"真正送进模型的那句话"）
 *   ③ 应用范围（默认卡 / 当前选中节点）
 *
 * 纪律：预览必须来自后端 —— 前端自己拼一遍英文就会和 prompt_template 漂移，
 * 用户看到"预览是一回事、出图是另一回事"，信任立刻崩。
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { BRIDGE, authHeaders } from "./bridge";
import { CARD_FIELDS, type PersonCard, hasCard, usePersonCardStore } from "./personCard";
import { useCanvasStore } from "./store";
import "./personCardPanel.css";

type Preview = { prompt: string; negative: string; genre: string };

export function PersonCardPanel({ onClose }: { onClose?: () => void }) {
  const card = usePersonCardStore((s) => s.card);
  const setField = usePersonCardStore((s) => s.setField);
  const replace = usePersonCardStore((s) => s.replace);
  const reset = usePersonCardStore((s) => s.reset);

  const selectedId = useCanvasStore((s) => s.selectedId);
  const selectedData = useCanvasStore((s) =>
    s.selectedId ? (s.nodes.find((n) => n.id === s.selectedId)?.data as { personCard?: PersonCard } | undefined) : undefined,
  );
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);

  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [line, setLine] = useState("");

  const nodeCard = (selectedData?.personCard || {}) as PersonCard;
  const editing: PersonCard = hasCard(nodeCard) ? nodeCard : card;
  const targetLabel = hasCard(nodeCard) ? "当前节点" : "默认卡（所有节点共用）";

  // 预览（防抖 350ms；空卡不请求，避免无意义后端调用）
  useEffect(() => {
    if (!hasCard(editing)) {
      setPreview(null);
      return;
    }
    const t = setTimeout(() => {
      void (async () => {
        try {
          const res = await fetch(BRIDGE + "/host/person-card/preview", {
            method: "POST",
            headers: authHeaders(true),
            body: JSON.stringify({ person_card: editing }),
          });
          const data = await res.json();
          if (data?.ok) setPreview({ prompt: String(data.prompt || ""), negative: String(data.negative || ""), genre: String(data.genre || "") });
        } catch {
          /* 预览失败不影响使用（生成时后端仍会渲染） */
        }
      })();
    }, 350);
    return () => clearTimeout(t);
  }, [editing]);

  const write = useCallback(
    (key: keyof PersonCard, value: string) => {
      if (hasCard(nodeCard) && selectedId) {
        const next = { ...nodeCard, [key]: value };
        if (!value) delete next[key];
        updateNodeData(selectedId, { personCard: next });
      } else {
        setField(key, value);
      }
    },
    [nodeCard, selectedId, setField, updateNodeData],
  );

  const applyToNode = () => {
    if (!selectedId) {
      setLine("先选中一个节点");
      return;
    }
    updateNodeData(selectedId, { personCard: { ...card } });
    setLine("已写入当前节点（该节点生成时优先用这份卡）");
  };

  const clearNode = () => {
    if (!selectedId) return;
    updateNodeData(selectedId, { personCard: undefined });
    setLine("已清空节点覆盖，回到默认卡");
  };

  const filled = useMemo(() => CARD_FIELDS.filter((f) => String(editing[f.key] || "").trim()).length, [editing]);

  return (
    <div className="sg-pc-panel" role="dialog" aria-label="人物卡">
      <div className="sg-pc-head">
        <b>🧑 人物卡</b>
        <span className="sg-pc-sub">{targetLabel} · 已填 {filled} 项</span>
        {onClose ? <button type="button" className="sg-pc-x" onClick={onClose} title="关闭">×</button> : null}
      </div>

      {line ? <div className="sg-pc-line">{line}</div> : null}

      <div className="sg-pc-fields">
        {CARD_FIELDS.map((f) => (
          <label key={f.key} className="sg-pc-field">
            <span>{f.label}</span>
            {f.free ? (
              <input
                list={"pc-" + f.key}
                value={String(editing[f.key] || "")}
                onChange={(e) => write(f.key, e.target.value)}
                placeholder="选或输入"
              />
            ) : (
              <select value={String(editing[f.key] || "")} onChange={(e) => write(f.key, e.target.value)}>
                <option value="">（不指定）</option>
                {f.options.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            )}
            {f.free ? (
              <datalist id={"pc-" + f.key}>
                {f.options.map((o) => <option key={o} value={o} />)}
              </datalist>
            ) : null}
          </label>
        ))}
      </div>

      <div className="sg-pc-actions">
        <button type="button" disabled={busy} onClick={() => { applyToNode(); }}>
          写到选中节点
        </button>
        <button type="button" onClick={() => { clearNode(); }}>清空节点覆盖</button>
        <button type="button" onClick={() => { reset(); setLine("默认卡已清空"); }}>清空默认卡</button>
        {selectedId ? null : (
          <button type="button" onClick={() => { void replace(editing); setLine("已设为默认卡"); }}>设为默认</button>
        )}
      </div>

      <div className="sg-pc-preview">
        <div className="sg-pc-preview-title">送进模型的就是这句（后端渲染，非前端拼）</div>
        <pre className="sg-pc-en">{preview?.prompt || (hasCard(editing) ? "渲染中…" : "先在上面选几项")}</pre>
        {preview?.genre ? <div className="sg-pc-genre">题材分档：{preview.genre}（负向词按档取）</div> : null}
      </div>
    </div>
  );
}
