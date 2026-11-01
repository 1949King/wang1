/**
 * 人物卡 · 顶栏入口（2026-11-01）
 * 与团队入口同款做法：组件单独成文件，挂到 WorkspaceCanvasMenus，CanvasShell 零改动。
 */
import { useState } from "react";

import { PersonCardPanel } from "./PersonCardPanel";

export function PersonCardTopBarButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={`libtv-icon-btn${open ? " on" : ""}`}
        title="人物卡：发型/服装/场景等字段 → 自动拼英文提示词（保证角色一致）"
        onClick={() => setOpen((v) => !v)}
      >
        🧑
      </button>
      {open ? <PersonCardPanel onClose={() => setOpen(false)} /> : null}
    </>
  );
}
