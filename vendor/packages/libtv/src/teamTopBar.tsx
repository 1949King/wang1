/**
 * 团队协作 · 顶栏入口（2026-10-31 · V4.49.1）
 *
 * 为什么单独成文件：`CanvasShell.tsx` 长期贴着体积守卫上限（基线 3251 行 / 容差 30），
 * 项目既有先例就是这么处理的（`canvasTierSeg.tsx` 注释原文：
 * 「组件单独成文件以避开本文件的体积守卫上限」）。
 *
 * 状态也一起搬进来：`open` 只服务于这个入口，放在 CanvasShell 里等于
 * 让每加一个入口都去挤那 30 行容差。
 */
import { useState } from "react";

import { TeamPanel } from "./TeamPanel";

export function TeamTopBarButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={`libtv-agent-btn${open ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="团队协作：启动服务 / 连接 / 上传画布 / 交接给同事"
      >
        👥 团队
      </button>
      {open ? <TeamPanel onClose={() => setOpen(false)} /> : null}
    </>
  );
}

export default TeamTopBarButton;
