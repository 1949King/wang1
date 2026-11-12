/**
 * 首屏向导（G5 · 2026-11-12）：选模板 → 写一句 → 落骨架到画布。
 *
 * 只做三件事，不引入新的状态层：读预设 → applyBlueprint → 交给父组件切到画布。
 */
import { useState } from "react";

import { applyBlueprint } from "./applyBlueprint";
import { STARTER_PRESETS, getPreset, validateSpec } from "./firstRun";
import { useCanvasStore } from "./store";
import "./firstRunWizard.css";

export function FirstRunWizard({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [step, setStep] = useState<0 | 1>(0);
  const [presetId, setPresetId] = useState<string>(STARTER_PRESETS[0].id);
  const [idea, setIdea] = useState("");
  const [err, setErr] = useState("");

  const preset = getPreset(presetId);

  const start = () => {
    const text = idea.trim() || "一个普通人的一天";
    const spec = preset.build(text);
    const problems = validateSpec(spec);
    if (problems.length) {
      setErr(problems.join("；"));
      return;
    }
    const st = useCanvasStore.getState();
    const r = applyBlueprint(spec, {
      addNode: (kind, pos) => st.addNode(kind as never, pos),
      updateNodeData: (id, patch) => st.updateNodeData(id, patch as never),
      onConnect: (c) => st.onConnect(c as never),
      existingNodes: st.nodes.map((n) => ({ id: n.id, position: n.position })),
    });
    if (!r.ok || r.nodeIds.length === 0) {
      setErr(r.problems.slice(0, 3).join("；") || "骨架创建失败");
      return;
    }
    st.setStatus?.(`已为「${preset.title}」铺好 ${r.nodeIds.length} 个节点、${r.edgesApplied} 条连线；点节点上的生成按钮即可`);
    onDone();
  };

  return (
    <div className="sg-fr-mask" role="dialog" aria-label="快速开始">
      <div className="sg-fr">
        <div className="sg-fr-head">
          <b>3 分钟从一句话开始</b>
          <button type="button" className="sg-fr-x" onClick={onClose} title="关闭">×</button>
        </div>

        {step === 0 ? (
          <>
            <div className="sg-fr-tip">先选一个你想做的东西（之后可以随意改）：</div>
            <div className="sg-fr-cards">
              {STARTER_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`sg-fr-card${presetId === p.id ? " on" : ""}`}
                  onClick={() => setPresetId(p.id)}
                >
                  <b>{p.title}</b>
                  <span>{p.desc}</span>
                </button>
              ))}
            </div>
            <div className="sg-fr-actions">
              <button type="button" className="primary" onClick={() => setStep(1)}>下一步</button>
            </div>
          </>
        ) : (
          <>
            <div className="sg-fr-tip">用一句话说清你要做什么（越具体越好）：</div>
            <textarea
              className="sg-fr-input"
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="例：一个外卖员在雨夜捡到一只会说话的猫"
              rows={3}
            />
            <div className="sg-fr-hint">
              会为你铺好：{preset.desc}。生成仍由你点节点上的按钮，不会偷偷烧算力。
            </div>
            {err ? <div className="sg-fr-err">{err}</div> : null}
            <div className="sg-fr-actions">
              <button type="button" onClick={() => setStep(0)}>上一步</button>
              <button type="button" className="primary" onClick={start}>生成骨架并进入画布</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}