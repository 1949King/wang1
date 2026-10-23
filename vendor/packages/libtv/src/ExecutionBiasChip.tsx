/**
 * 画布浮层 · 混合算力滑块（2026-10-24）
 *
 * 用户需求：「把滑块也搬到画布界面上」。此前 compute_bias 只有后端 API / 无 UI，
 * 画布用户看不到也用不了。这里给一个**常驻小胶囊**：点开是 0~100 滑块 +
 * 当前本地/云端可用性 + 「试算视频双路」（调执行层计划，不执行生成）。
 *
 * 纪律：
 *   · 只读写已有的 /host/execution-status 与 /host/execution-bias，**不新增端点**；
 *   · 后端离线时静默降级（胶囊仍可点，保存/试算如实报错），不拖垮画布；
 *   · 样式内联在组件里（styles.css 属冻结区，不动它）。
 */
import { useCallback, useEffect, useState } from "react";

import { BRIDGE, authHeaders } from "./bridge";
import { biasModeHint, biasModeLabel } from "./executionBias";

type ExecStatus = {
  bias?: number;
  mode?: string;
  cloud_available?: boolean;
  hw_tier?: string;
  engine?: { engine?: string; available?: boolean };
};

type Plan = { route?: string; chain?: string[]; reasons?: string[] };

export default function ExecutionBiasChip() {
  const [open, setOpen] = useState(false);
  const [bias, setBias] = useState(50);
  const [status, setStatus] = useState<ExecStatus | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [msg, setMsg] = useState("");

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(BRIDGE + "/host/execution-status", {
        headers: authHeaders(),
        cache: "no-store",
      });
      const data = await res.json();
      if (data && data.ok) {
        setStatus(data as ExecStatus);
        setBias(Number(data.bias ?? 50));
      }
    } catch {
      /* 后端离线：保持占位，不打断画布 */
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = useCallback(async (next: number) => {
    try {
      const res = await fetch(BRIDGE + "/host/execution-bias", {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({ bias: next }),
      });
      const data = await res.json();
      if (data && data.ok) {
        setStatus(data as ExecStatus);
        setMsg("已保存：" + biasModeLabel(next));
      } else {
        setMsg(String((data && data.message) || "保存失败"));
      }
    } catch {
      setMsg("保存失败：无法连接本地服务");
    }
  }, []);

  const preview = useCallback(async () => {
    try {
      const res = await fetch(
        BRIDGE + "/host/execution-plan?capability=video&has_reference=1",
        { headers: authHeaders(), cache: "no-store" },
      );
      const data = await res.json();
      if (data && data.ok && data.plan) {
        setPlan(data.plan as Plan);
      } else {
        setPlan(null);
        setMsg(String((data && data.message) || "试算失败"));
      }
    } catch {
      setMsg("试算失败：无法连接本地服务");
    }
  }, []);

  return (
    <div className="exec-chip">
      <button
        type="button"
        className="exec-chip__btn"
        onClick={() => setOpen((v) => !v)}
        title="混合算力偏好（0=纯本地 … 100=纯云端）"
      >
        <span className="exec-chip__dot" data-mode={biasModeLabel(bias)} />
        <span>
          算力 {bias} · {biasModeLabel(bias)}
        </span>
      </button>
      {open ? (
        <div className="exec-chip__panel">
          <div className="exec-chip__row">
            <span className="exec-chip__side">本地</span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={bias}
              onChange={(e) => setBias(Number(e.target.value))}
              onPointerUp={() => void save(bias)}
              onKeyUp={() => void save(bias)}
            />
            <span className="exec-chip__side">云端</span>
          </div>
          <div className="exec-chip__hint">{biasModeHint(bias)}</div>
          <div className="exec-chip__meta">
            本地引擎 {status?.engine?.engine || "—"} · 云端{" "}
            {status?.cloud_available ? "可用" : "未配置"} · 硬件 {status?.hw_tier || "—"}
          </div>
          <button type="button" className="exec-chip__preview" onClick={() => void preview()}>
            试算视频双路
          </button>
          {plan ? (
            <div className="exec-chip__plan">
              视频：{plan.route || "?"} · {(plan.chain || []).join(" → ") || "无可用路径"}
              {plan.reasons && plan.reasons.length ? "（" + plan.reasons[plan.reasons.length - 1] + "）" : ""}
            </div>
          ) : null}
          {msg ? <div className="exec-chip__msg">{msg}</div> : null}
        </div>
      ) : null}
      <style>{CSS}</style>
    </div>
  );
}

const CSS = [
  ".exec-chip { position: fixed; left: 16px; bottom: 16px; z-index: 60; font-size: 12px; color: #d6dde8; }",
  ".exec-chip__btn { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; border: 1px solid #2a3342; background: rgba(16,22,32,.92); color: inherit; cursor: pointer; }",
  ".exec-chip__dot { width: 8px; height: 8px; border-radius: 50%; background: #6c9fff; }",
  ".exec-chip__dot[data-mode='本地优先'] { background: #4ade80; }",
  ".exec-chip__dot[data-mode='云端优先'] { background: #fbbf24; }",
  ".exec-chip__panel { position: absolute; left: 0; bottom: 42px; width: 262px; padding: 10px 12px; border-radius: 10px; border: 1px solid #2a3342; background: rgba(14,20,28,.96); display: flex; flex-direction: column; gap: 8px; }",
  ".exec-chip__row { display: flex; align-items: center; gap: 8px; }",
  ".exec-chip__side { font-size: 11px; color: #8b9bb0; }",
  ".exec-chip__row input[type='range'] { flex: 1; }",
  ".exec-chip__hint, .exec-chip__meta { font-size: 11px; color: #8b9bb0; line-height: 1.5; }",
  ".exec-chip__preview { padding: 5px 8px; border-radius: 7px; border: 1px solid #2a3342; background: #172033; color: #d6dde8; cursor: pointer; font-size: 11px; }",
  ".exec-chip__plan, .exec-chip__msg { font-size: 11px; color: #9aa4b2; line-height: 1.5; }",
  "html[data-theme='light'] .exec-chip__btn { border-color: #cdd5e3; background: #ffffff; color: #172033; }",
  "html[data-theme='light'] .exec-chip__panel { border-color: #cdd5e3; background: #ffffff; }",
  "html[data-theme='light'] .exec-chip__hint, html[data-theme='light'] .exec-chip__meta { color: #6b7790; }",
  "html[data-theme='light'] .exec-chip__preview { border-color: #cdd5e3; background: #f6f7fb; color: #172033; }",
].join("\n");
