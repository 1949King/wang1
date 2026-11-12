/**
 * 免责声明 / 合规说明首屏（2026-11-12）。
 *
 * 两种模式：
 * - mode="gate"：首次进入，必须滑到底，按钮才可用（按钮 = 我已阅读并同意）；
 * - mode="view"：从帮助里重新查看，随时可关闭。
 */
import { useEffect, useRef, useState } from "react";

import { COMPLIANCE_SECTIONS, COMPLIANCE_VERSION } from "./complianceDoc";
import { isScrolledToBottom } from "./complianceStore";
import "./complianceGate.css";

export function ComplianceGate({
  mode = "gate",
  onAccept,
  onClose,
}: {
  mode?: "gate" | "view";
  onAccept?: () => void;
  onClose?: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [atBottom, setAtBottom] = useState(mode === "view");

  const check = () => {
    const el = bodyRef.current;
    if (!el) return;
    setAtBottom(isScrolledToBottom(el.scrollTop, el.clientHeight, el.scrollHeight));
  };

  useEffect(() => {
    // 内容短于一屏时，直接允许继续（否则按钮永远不亮）
    const t = window.setTimeout(check, 30);
    return () => window.clearTimeout(t);
  }, []);

  return (
    <div className="sg-cg-mask" role="dialog" aria-modal="true" aria-label="免责声明与合规说明">
      <div className="sg-cg">
        <div className="sg-cg-head">
          <b>免责声明与合规说明</b>
          <span className="sg-cg-ver">v{COMPLIANCE_VERSION}</span>
        </div>

        <div className="sg-cg-body" ref={bodyRef} onScroll={check}>
          <p className="sg-cg-intro">
            首次使用前，请完整阅读以下内容。滑到底部后，「我已阅读并同意」按钮才可用。
          </p>
          {COMPLIANCE_SECTIONS.map((s) => (
            <section key={s.title} className="sg-cg-sec">
              <h4>{s.title}</h4>
              <p>{s.body}</p>
            </section>
          ))}
          <p className="sg-cg-end">—— 以上为全部内容 ——</p>
        </div>

        <div className="sg-cg-foot">
          {mode === "gate" ? (
            <>
              <span className="sg-cg-hint">{atBottom ? "已读完，可以继续" : "请滑动阅读至底部"}</span>
              <button
                type="button"
                className="primary"
                disabled={!atBottom}
                onClick={() => onAccept?.()}
                title={atBottom ? "同意并进入软件" : "请先滑到底部"}
              >
                我已阅读并同意
              </button>
            </>
          ) : (
            <button type="button" className="primary" onClick={() => onClose?.()}>关闭</button>
          )}
        </div>
      </div>
    </div>
  );
}
