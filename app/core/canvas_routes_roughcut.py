# -*- coding: utf-8 -*-
"""画布桥 · 粗剪审核卡回写路由（§6.9-P2 画布消费接线，2026-10-17）

为什么单开一个 mixin
====================
`canvas_routes_post.py` 已 1936 行、逼近 `_verify/check_file_size.py` 的 2000 阈值，
照 `canvas_routes_dub.py` 的「桥函数另开文件」既有纪律，把粗剪审核卡的两条回写
端点独立成 `CanvasRoughCutRoutesMixin`（与 get/post/dub 同构，由
canvas_server._BridgeHandler 继承）。

两条端点与分工
==============
- `POST /host/rough-cut/apply` ：审核卡「确认执行」→ `RoughCutChain.apply()` 写回
  `_clips`（排轨+波纹删除+合缝，一条 compound 撤销）。**confirmed=True 由本端点
  显式钉死**——用户点审核卡确认按钮就是「确认后执行」纪律的人工确认时刻；
  前端不传 confirmed，杜绝绕过闸门的可能。
- `POST /host/rough-cut/export`：写回完成后导出成片 → `RoughCutChain.export()`
  委托 `agent_execute_pipeline_editing` 既有出片入口（零新渲染路径）。

线程纪律
========
- apply 触碰 `_clips` 与 `_record_action`（Qt 撤销栈）⇒ 必须走
  `project_agent_host._run_on_ui` 回主线程执行（与 ext.run_skill 同一先例）。
- export 是长耗时渲染（FFmpeg 分钟级）⇒ **不进主线程**：ThreadingHTTPServer
  一请求一线程，与 pipeline_jobs worker 调 `pipeline.execute_editing` 的线程
  模式同纪律；`_run_on_ui` 的 5s 超时会把正常导出误报成失败。

诚实边界（红线）
================
- 提案不存在/已写回/时间线已变化 ⇒ `apply()` 原样回传 error，不重试不掩盖。
- 未写回就导出 ⇒ `export()` 拒绝（先 apply 后 export 的顺序纪律不可颠倒）。
"""
from __future__ import annotations

import json
import logging

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


class CanvasRoughCutRoutesMixin:
    """粗剪审核卡回写端点集合（由 `_BridgeHandler` 继承）。"""

    # ── POST /host/rough-cut/apply：审核卡确认后写回时间线 ──────────
    @_route_post("/host/rough-cut/apply")
    def _p_host_rough_cut_apply(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        plan_id = str(body.get("plan_id") or "")
        if not plan_id:
            self._json(400, {"ok": False, "message": "plan_id 不能为空"})
            return

        from app.core.project_agent_host import get_editor_module, _run_on_ui
        from app.core.rough_cut_chain import rough_cut_chain

        editor = get_editor_module()
        if editor is None:
            self._json(200, {"ok": False, "error": "EditorModule 未就绪，无法写回时间线"})
            return
        # confirmed=True 钉死在本端点：人工确认时刻 = 用户点审核卡「确认执行」
        ok, res, err = _run_on_ui(
            lambda: rough_cut_chain.apply(editor, plan_id, confirmed=True)
        )
        if not ok:
            self._json(500, {"ok": False, "error": err or "主线程执行失败"})
            return
        self._json(200, res if isinstance(res, dict) else {"ok": False, "error": "写回无返回"})
        return

    # ── POST /host/rough-cut/export：写回后导出粗剪成片（委托精剪入口）──
    @_route_post("/host/rough-cut/export")
    def _p_host_rough_cut_export(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return
        plan_id = str(body.get("plan_id") or "")
        if not plan_id:
            self._json(400, {"ok": False, "message": "plan_id 不能为空"})
            return

        from app.core.project_agent_host import get_editor_module
        from app.core.rough_cut_chain import rough_cut_chain

        editor = get_editor_module()
        if editor is None:
            self._json(200, {"ok": False, "error": "EditorModule 未就绪，无法导出成片"})
            return
        # 长耗时渲染：留在本 HTTP 线程（ThreadingHTTPServer 一请求一线程），
        # 不进主线程、不加超时——与 pipeline_jobs worker 调精剪同纪律。
        try:
            res = rough_cut_chain.export(
                editor, plan_id, session_id=str(body.get("session_id") or "")
            )
        except Exception as e:
            logger.exception("[/host/rough-cut/export] 导出异常")
            self._json(500, {"ok": False, "error": f"粗剪导出异常：{e}"})
            return
        self._json(200, res if isinstance(res, dict) else {"ok": False, "error": "导出无返回"})
        return
