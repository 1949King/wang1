/**
 * 粗剪审核卡（小白审核卡 · 画布壳层）—— §6.9-P2 画布消费接线，2026-10-17。
 *
 * 职责边界（分层纪律）：
 *  - 纯渲染层：消费 rough_cut_chain 经 SSE 推来的 `rough_cut.review` 事件
 *    （判读逻辑全部在 hostRoughCut.parseRoughCutEvent，本组件不复制任何判定规则）。
 *  - 「确认后执行」闸门：确认按钮 → POST /host/rough-cut/apply（confirmed=True
 *    由后端端点钉死）；导出仅在写回成功后开放（顺序纪律后端把关）。
 *  - 状态自管 React state，**不进 store.ts**（该文件已逼近规模守卫上限）。
 *
 * 挂载位置：CanvasShell 壳层（非 AgentPanel 内）—— 面板不开也要能收到提案。
 * SSE 断线治理沿用 AgentPanel 纪律：连续失败第 3 次触发凭据自愈
 * （refreshBridgeTokenFromInject），凭据确有变化才按 epoch 重订阅。
 */
import { useEffect, useRef, useState } from "react";
import { bridgeToken, refreshBridgeTokenFromInject } from "./bridge";
import { subscribeAgentEvents } from "./agentEvents";
import {
  applyRoughCutPlan,
  exportRoughCutPlan,
  parseRoughCutEvent,
  type RoughCutPlanReady,
} from "./hostRoughCut";

/** 卡片状态机：待审 → 写回中 → 已写回 → 导出中 → 完成；任一环节出错进 error */
type DockPhase = "pending" | "applying" | "applied" | "exporting" | "done" | "error";

const KIND_LABEL: Record<string, string> = {
  filler: "水词",
  silence: "长静音",
};

function fmtSec(v: number): string {
  return `${v.toFixed(2)}s`;
}

export default function RoughCutReviewDock() {
  const [plan, setPlan] = useState<RoughCutPlanReady | null>(null);
  const [phase, setPhase] = useState<DockPhase>("pending");
  const [notice, setNotice] = useState("");
  const [outPath, setOutPath] = useState("");
  // SSE 断线治理（AgentPanel.tsx:685 同纪律）
  const [bridgeEpoch, setBridgeEpoch] = useState(0);
  const sseFailRef = useRef(0);
  const sseHealedRef = useRef(false);
  // 防重复点击兜底：busy 期间按钮 disabled（见下方渲染）
  const busy = phase === "applying" || phase === "exporting";

  useEffect(() => {
    const unsub = subscribeAgentEvents({
      onOpen: () => {
        sseFailRef.current = 0;
        sseHealedRef.current = false;
      },
      onEvent: (env) => {
        const evt = parseRoughCutEvent(env);
        if (!evt) return;
        if (evt.subtype === "rough_cut_plan_ready") {
          // 新提案覆盖旧卡（与后端 _MAX_PLANS FIFO 一致）；重置全部展示状态
          setPlan(evt);
          setPhase("pending");
          setNotice("");
          setOutPath("");
        } else if (evt.subtype === "rough_cut_applied") {
          // 写回完成通知：可能来自剪辑侧栏（非本卡触发）⇒ 按 plan_id 对齐同步
          setPlan((cur) => {
            if (cur && cur.plan_id === evt.plan_id) {
              setPhase((p) => (p === "pending" || p === "applying" ? "applied" : p));
              setNotice(evt.message);
            }
            return cur;
          });
        }
      },
      onError: () => {
        sseFailRef.current += 1;
        if (sseFailRef.current === 3 && !sseHealedRef.current) {
          sseHealedRef.current = true;
          const before = bridgeToken();
          void refreshBridgeTokenFromInject().then((token) => {
            // 凭据确有变化才重订阅，避免无谓抖动
            if (token && token !== before) setBridgeEpoch((e) => e + 1);
          });
        }
      },
    });
    return () => {
      try {
        unsub();
      } catch {
        /* ignore */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bridgeEpoch]);

  const onConfirm = async () => {
    if (!plan || busy) return;
    setPhase("applying");
    setNotice("");
    const res = await applyRoughCutPlan(plan.plan_id);
    if (res.ok) {
      setPhase("applied");
      setNotice(res.message || "粗剪已写回（可撤销）");
    } else {
      setPhase("error");
      setNotice(res.error || res.message || "写回失败");
    }
  };

  const onExport = async () => {
    if (!plan || busy) return;
    setPhase("exporting");
    setNotice("");
    const res = await exportRoughCutPlan(plan.plan_id, plan.request_id);
    if (res.ok) {
      setPhase("done");
      setOutPath(res.final_video_path || res.output_path || "");
      setNotice("粗剪成片已导出");
    } else {
      setPhase("error");
      setNotice(res.error || "导出失败");
    }
  };

  const dismiss = () => {
    if (busy) return;
    setPlan(null);
    setNotice("");
    setOutPath("");
  };

  if (!plan) return null;

  return (
    <div className="sg-rc-dock" role="region" aria-label="粗剪审核卡">
      <div className="sg-rc-head">
        <span className="sg-rc-title">粗剪审核</span>
        <span className={`sg-rc-phase sg-rc-phase-${phase}`}>
          {phase === "pending" && "待确认"}
          {phase === "applying" && "写回中…"}
          {phase === "applied" && "已写回"}
          {phase === "exporting" && "导出中…"}
          {phase === "done" && "已完成"}
          {phase === "error" && "出错"}
        </span>
        <button type="button" className="sg-rc-close" onClick={dismiss} disabled={busy} aria-label="关闭">
          ×
        </button>
      </div>

      <div className="sg-rc-summary">
        <span>
          时长 <b>{fmtSec(plan.summary.original_duration)}</b> →{" "}
          <b>{fmtSec(plan.summary.predicted_duration)}</b>
        </span>
        <span>
          将删 <b>{fmtSec(plan.summary.deleted_duration)}</b>（{plan.summary.interval_count} 段）
        </span>
      </div>

      {plan.warnings.length > 0 && (
        <ul className="sg-rc-warnings">
          {plan.warnings.map((w, i) => (
            <li key={`w${i}`}>{w}</li>
          ))}
        </ul>
      )}

      {plan.intervals.length > 0 && (
        <details className="sg-rc-intervals">
          <summary>查看 {plan.intervals.length} 个待删区间</summary>
          <ul>
            {plan.intervals.map((iv, i) => (
              <li key={`iv${iv.clip_id}-${iv.timeline_in}-${i}`}>
                <span className="sg-rc-kind">{KIND_LABEL[iv.kind] || iv.kind || "区间"}</span>
                <span className="sg-rc-range">
                  {fmtSec(iv.timeline_in)} – {fmtSec(iv.timeline_out)}
                </span>
                {iv.text && <span className="sg-rc-text">{iv.text}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {notice && <div className={`sg-rc-notice${phase === "error" ? " sg-rc-notice-err" : ""}`}>{notice}</div>}
      {phase === "done" && outPath && <div className="sg-rc-path" title={outPath}>{outPath}</div>}

      <div className="sg-rc-actions">
        {phase === "pending" && (
          <>
            <button type="button" className="sg-rc-btn sg-rc-btn-primary" onClick={() => void onConfirm()}>
              确认执行
            </button>
            <button type="button" className="sg-rc-btn" onClick={dismiss}>
              忽略
            </button>
          </>
        )}
        {phase === "applying" && (
          <button type="button" className="sg-rc-btn sg-rc-btn-primary" disabled>
            写回中…
          </button>
        )}
        {phase === "applied" && (
          <>
            <button type="button" className="sg-rc-btn sg-rc-btn-primary" onClick={() => void onExport()}>
              导出成片
            </button>
            <button type="button" className="sg-rc-btn" onClick={dismiss}>
              稍后导出
            </button>
          </>
        )}
        {phase === "exporting" && (
          <button type="button" className="sg-rc-btn sg-rc-btn-primary" disabled>
            导出中…（渲染可能较慢）
          </button>
        )}
        {(phase === "done" || phase === "error") && (
          <button type="button" className="sg-rc-btn" onClick={dismiss}>
            关闭
          </button>
        )}
      </div>
    </div>
  );
}
