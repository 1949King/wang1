# -*- coding: utf-8 -*-
"""editor_agent_runtime_mixin.py
============================
EditorAgentRuntimeMixin: 从 editor_module.py 抽出的「Agent 面板运行时 UI + 任务控制」方法。

承载: Agent 标签页切换/定位、多集上下文持久化、进度卡/预览卡构建、
大脑状态刷新、消息追加、任务暂停/恢复/重规划/停止、模型/模式读取。
均为纯 UI/编排/持久化回调，不直接写 `_clips` 核心状态机，不触碰
playback-av / canvas-transform / clip-transform 冻结区。

与 EditorAgentPanelMixin 的区别：后者承载 Agent 面板构建与 pipeline 编排，
本 Mixin 承载面板发布后的运行时交互与任务启停控制。

迁移的方法（共 42 个, 约 736 行，含阶段映射常量 _PIPELINE_STAGES）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QListWidget,
    QProgressBar, QMessageBox, QListWidgetItem,
)

logger = logging.getLogger("AI短剧编辑器.editor")


class EditorAgentRuntimeMixin:
    """Agent 面板运行时 UI 与任务控制 Mixin。"""

    # 抽取自 editor_module.py L7522-7536
    # V4.40.50：Agent 不再是工具栏 Tab（只有上半区 ≈390px 高），改为最右侧独立竖栏
    def _toggle_edit_agent_panel(self, checked=None):
        """展开 / 收起剪辑 Agent 竖栏（LibTV 档：宽 360，贯穿到底）。"""
        if checked is False:
            self._hide_agent_dock()
            return
        if getattr(self, '_agent_dock', None) is None:
            # 布局尚未建好（早于 _setup_ui 的调用），延后重试一次
            QTimer.singleShot(100, lambda: self._toggle_edit_agent_panel(checked))
            return
        self._show_agent_dock()

    # 抽取自 editor_module.py L7538-7549
    def _close_agent_tab(self):
        """收起 Agent 竖栏（面板内「收起」按钮与兼容旧入口共用）。"""
        self._hide_agent_dock()

    # 注：原 _position_edit_agent_panel（浮动面板定位）已随 V4.40.50 删除 ——
    # 浮动面板早在 V4.34.1 就被嵌入工具栏取代，该方法是死代码。

    # 抽取自 editor_module.py L7592-7603
    def _load_agent_project_context_fields(self):
        try:
            from app.core.memory_store import memory_store
            ctx = memory_store.get_project_context() or {}
            if getattr(self, "_agent_drama_edit", None) is not None:
                self._agent_drama_edit.setText(str(ctx.get("drama_title") or ""))
            if getattr(self, "_agent_episode_edit", None) is not None:
                self._agent_episode_edit.setText(str(ctx.get("episode") or ""))
            if getattr(self, "_agent_platform_edit", None) is not None:
                self._agent_platform_edit.setText(str(ctx.get("platform") or ""))
        except Exception:
            logger.debug("忽略异常（原为 pass）: editor_agent_runtime_mixin.py", exc_info=True)

    # 抽取自 editor_module.py L7605-7622
    def _save_agent_project_context(self):
        try:
            from app.core.memory_store import memory_store
            title = self._agent_drama_edit.text().strip() if getattr(self, "_agent_drama_edit", None) else ""
            episode = self._agent_episode_edit.text().strip() if getattr(self, "_agent_episode_edit", None) else ""
            platform = self._agent_platform_edit.text().strip() if getattr(self, "_agent_platform_edit", None) else ""
            memory_store.set_project_context(
                drama_title=title,
                episode=episode,
                platform=platform,
                notes="",
            )
            self._append_agent_message(
                "系统",
                f"已保存多集上下文：{title or '（无剧名）'} / 第{episode or '?'}集 / {platform or '未指定平台'}",
            )
        except Exception as e:
            QMessageBox.warning(self, "多集上下文", f"保存失败: {e}")

    # 抽取自 editor_module.py L7624-7644
    def _persist_agent_project_context_silent(self):
        """发送指令前静默把输入框写入记忆，避免用户忘点保存。"""
        try:
            from app.core.memory_store import memory_store
            title = ""
            episode = ""
            platform = ""
            if getattr(self, "_agent_drama_edit", None) is not None:
                title = self._agent_drama_edit.text().strip()
            if getattr(self, "_agent_episode_edit", None) is not None:
                episode = self._agent_episode_edit.text().strip()
            if getattr(self, "_agent_platform_edit", None) is not None:
                platform = self._agent_platform_edit.text().strip()
            if title or episode or platform:
                memory_store.set_project_context(
                    drama_title=title,
                    episode=episode,
                    platform=platform,
                )
        except Exception:
            logger.debug("忽略异常（原为 pass）: editor_agent_runtime_mixin.py", exc_info=True)

    # 抽取自 editor_module.py L7666-7672
    def _append_agent_message(self, role: str, text: str):
        """向 Agent 对话框追加消息。"""
        chat = getattr(self, '_edit_agent_chat', None)
        if chat is None:
            return
        chat.append(f"{role}: {text}")
        chat.verticalScrollBar().setValue(chat.verticalScrollBar().maximum())

    # 抽取自 editor_module.py L7674-7712
    def _refresh_agent_brain_status(self):
        """刷新 🧠 大脑状态条：显示神经元总数、左右脑分布、突触数与最强链路。

        - 失败时静默降级为占位文本，不影响 Agent 面板其它功能
        - 数据来自 AgentBrain.get_brain_status()，无副作用
        """
        label = getattr(self, '_agent_brain_status_label', None)
        if label is None:
            return
        try:
            from app.core.agent_brain import agent_brain
            status = agent_brain.get_brain_status()
            total_n = status.get("total_neurons", 0)
            right_n = status.get("right_brain_count", 0)
            left_n = status.get("left_brain_count", 0)
            cc_n = status.get("cc_count", 0)
            total_s = status.get("total_synapses", 0)
            active = status.get("active_neurons", []) or []
            top_syns = status.get("top_synapses", []) or []

            # 拼装主状态行
            main = (f"🧠 神经元 {total_n} | 🌐 左脑 {left_n} / 右脑 {right_n} / 胼胝体 {cc_n}"
                    f" | 🔗 突触 {total_s} | ⚡ 激活 {len(active)}")
            # 拼装最强链路（最多 2 条，避免占屏）
            links = []
            for s in top_syns[:2]:
                pre = s.get("pre", "")
                post = s.get("post", "")
                w = s.get("weight", 0.0)
                try:
                    w_pct = int(float(w) * 100)
                except (TypeError, ValueError):
                    w_pct = 0
                links.append(f"{pre}→{post}({w_pct}%)")
            link_text = " | 强链路: " + " / ".join(links) if links else ""
            label.setText(main + link_text)
        except Exception as e:
            # 静默降级，避免阻塞 UI 刷新定时器
            label.setText(f"🧠 大脑状态不可用: {e}")

    # 抽取自 editor_module.py L7809-7847
    def _build_agent_progress_card(self, parent_layout: QVBoxLayout):
        """构造执行进度卡（阶段进度条 + stage 标签 + 细节）。"""
        card = QFrame()
        card.setObjectName("agentProgressCard")
        card.setStyleSheet("""
            QFrame#agentProgressCard{background:#0d1117;border:1px solid #21262d;border-radius:10px;}
            QProgressBar{background:#161b22;border:1px solid #30363d;border-radius:4px;text-align:center;height:8px;}
            QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1f6feb,stop:1 #7ee787);border-radius:4px;}
            QLabel#stageMain{color:#e6edf3;font-size:12px;font-weight:700;}
            QLabel#stageDetail{color:#8b949e;font-size:11px;}
        """)
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._agent_stage_label = QLabel("")
        self._agent_stage_label.setObjectName("stageMain")
        head.addWidget(self._agent_stage_label)
        head.addStretch()
        lay.addLayout(head)

        self._agent_stage_bar = QProgressBar()
        self._agent_stage_bar.setRange(0, 100)
        self._agent_stage_bar.setValue(0)
        self._agent_stage_bar.setTextVisible(False)
        self._agent_stage_bar.setFixedHeight(8)
        lay.addWidget(self._agent_stage_bar)

        self._agent_stage_detail = QLabel("")
        self._agent_stage_detail.setObjectName("stageDetail")
        self._agent_stage_detail.setWordWrap(True)
        self._agent_stage_detail.setMaximumHeight(40)
        lay.addWidget(self._agent_stage_detail)

        self._agent_progress_card = card
        parent_layout.addWidget(card)

    # 抽取自 editor_module.py L7897-7925
    def _build_agent_preview_card(self, parent_layout: QVBoxLayout):
        """构造预览问题卡（保守版：只显示失败片段 clip_id）。"""
        card = QFrame()
        card.setObjectName("agentPreviewCard")
        card.setStyleSheet("QFrame#agentPreviewCard{background:#1b1405;border:1px solid #8b6914;border-radius:10px;}")
        card.setVisible(False)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        t = QLabel("⏸ 预览问题片段")
        t.setStyleSheet("color:#f0b429;font-size:12px;font-weight:700;")
        head.addWidget(t)
        head.addStretch()
        self._agent_preview_count_lbl = QLabel("")
        self._agent_preview_count_lbl.setStyleSheet("color:#8b949e;font-size:10px;")
        head.addWidget(self._agent_preview_count_lbl)
        lay.addLayout(head)

        self._agent_preview_list = QListWidget()
        self._agent_preview_list.setFixedHeight(80)
        self._agent_preview_list.setStyleSheet(
            "QListWidget{background:#0f1117;color:#c9d1d9;border:1px solid #21262d;border-radius:6px;font-size:11px;}"
            "QListWidget::item{padding:3px 6px;}")
        lay.addWidget(self._agent_preview_list)

        self._agent_preview_card = card
        parent_layout.addWidget(card)

    # 抽取自 editor_module.py L8000-8007
    def _fill_edit_agent_prompt(self, text: str):
        """把快捷剪辑指令填入输入框，方便用户确认后发送。"""
        edit = getattr(self, '_edit_agent_input', None)
        if edit is None:
            return
        edit.setText(text)
        edit.setFocus()
        edit.selectAll()

    # 抽取自 editor_module.py L8010-8027
    def _pause_edit_agent_task(self):
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        agent_sessions.pause("editor")
        tid = getattr(self, "_edit_agent_task_id", "") or ""
        if tid:
            try:
                agent_tasks.transition(tid, "paused", pausedReason="user")
            except Exception:
                logger.debug("忽略异常（原为 pass）: editor_agent_runtime_mixin.py", exc_info=True)
        worker = getattr(self, "_edit_agent_worker", None)
        if worker and worker.isRunning():
            worker.request_stop()
        stop_btn = getattr(self, "_edit_agent_stop_btn", None)
        if stop_btn is not None:
            stop_btn.setEnabled(False)
        self._append_agent_message("系统", "任务已暂停。点「继续」解除暂停后再发送。")

    # 抽取自 editor_module.py L8029-8040
    def _resume_edit_agent_task(self):
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        agent_sessions.resume("editor")
        tid = getattr(self, "_edit_agent_task_id", "") or ""
        if tid:
            try:
                agent_tasks.transition(tid, "running")
            except Exception:
                logger.debug("忽略异常（原为 pass）: editor_agent_runtime_mixin.py", exc_info=True)
        self._append_agent_message("系统", "已继续。可以发送下一条或等待队列。")

    # 抽取自 editor_module.py L8042-8051
    def _replan_edit_agent_task(self):
        combo = getattr(self, "_agent_mode_combo", None)
        if combo is not None:
            idx = combo.findData("plan")
            if idx >= 0:
                combo.setCurrentIndex(idx)
        last = getattr(self, "_edit_agent_last_user_text", "") or ""
        if last:
            self._fill_edit_agent_prompt(last)
        self._append_agent_message("系统", "已切 Plan。确认输入后发送以重新规划。")

    # 抽取自 editor_module.py L8053-8071
    def _stop_edit_agent_message(self):
        """终止当前剪辑 Agent 输出。"""
        from app.core.agent_session import agent_sessions
        from app.core.agent_task_store import agent_tasks

        agent_sessions.stop("editor")
        tid = getattr(self, "_edit_agent_task_id", "") or ""
        if tid:
            try:
                agent_tasks.transition(tid, "stopped")
            except Exception:
                logger.debug("忽略异常（原为 pass）: editor_agent_runtime_mixin.py", exc_info=True)
        worker = getattr(self, '_edit_agent_worker', None)
        if worker and worker.isRunning():
            worker.request_stop()
            self._append_agent_message("系统", "已请求终止当前输出。")
        stop_btn = getattr(self, "_edit_agent_stop_btn", None)
        if stop_btn is not None:
            stop_btn.setEnabled(False)

    # 抽取自 editor_module.py L8073-8087
    def _get_selected_edit_agent_model(self):
        """获取当前 Agent 模型选择；空时回退到模型管理激活项。"""
        combo = getattr(self, '_edit_agent_model_combo', None)
        if combo is not None:
            data = combo.currentData()
            if isinstance(data, tuple) and len(data) == 2 and data[0]:
                return data
        try:
            from app.modules.lego.model_config import load_active_provider
            active = load_active_provider() or ""
            if active:
                return active, ""
        except Exception:
            logger.debug("忽略异常（原为 pass）: editor_agent_runtime_mixin.py", exc_info=True)
        return "", ""

    # 抽取自 editor_module.py L8090-8092
    def _is_agent_plan_mode(self) -> bool:
        """判断当前是否为 Plan 模式。"""
        return self._get_agent_session_mode() == "plan"

    # 抽取自 editor_module.py L8094-8100
    def _get_agent_session_mode(self) -> str:
        from app.core.agent_policy import normalize_mode

        combo = getattr(self, "_agent_mode_combo", None)
        if combo is None:
            return "collaborative"
        return normalize_mode(combo.currentData())


    # ───────────────── 阶段 1.3 追加：面板运行时任务控制 ─────────────────
    # 抽取自 editor_module.py L7529-7539
    def _subscribe_provider_activated(self):
        """模型管理激活变化时刷新 Agent 下拉。"""
        if getattr(self, "_provider_activated_hooked", False):
            return
        try:
            from .core import EventBus, EventType
            bus = EventBus.get_instance()
            bus.on(EventType.PROVIDER_ACTIVATED, self._on_provider_activated_event)
            self._provider_activated_hooked = True
        except Exception as e:
            logger.debug("[Agent] 订阅 PROVIDER_ACTIVATED 失败: %s", e)

    # 抽取自 editor_module.py L7541-7545
    def _on_provider_activated_event(self, event):
        try:
            self._refresh_edit_agent_models()
        except Exception as e:
            logger.debug("[Agent] 激活事件刷新模型失败: %s", e)

    # 抽取自 editor_module.py L7554-7571
    def _list_local_ollama_models(self) -> List[str]:
        """读取本地 Ollama 模型列表；失败时返回空列表并保留自动模式。

        走 model_config.discover_local_models()（300s TTL 缓存）而不是直连
        `client.list_models()`：本机 `/api/tags` 实测约 4s，旧写法每次刷新模型
        列表都会同步打一次 HTTP，是「首次打开 Agent 面板卡顿」的根因之一。
        """
        try:
            from app.modules.lego.model_config import discover_local_models
            return list(discover_local_models() or [])
        except Exception as e:
            logger.debug("[Agent] 读取本地 Ollama 模型失败: %s", e)
            return []

    # Agent 全链路 6+ 主阶段映射（用于进度条）
    _PIPELINE_STAGES = [
        ("routing",           "🔀", "智能业务分流",   5),
        ("generation",        "🎬", "AI 视频生成",    25),
        ("import_parsing",    "📥", "素材解析",        25),
        ("preview",           "🔍", "预览校验",        40),
        ("scoring",           "📊", "五维打分",        55),
        ("scripting",         "📝", "剪辑脚本",        70),
        ("editing",           "✂️", "精剪成片",        85),
        ("done",              "✅", "完成",           100),
    ]

    # 抽取自 editor_module.py L7593-7602
    def _stage_progress(self, stage: str) -> int:
        """把 stage 字符串映射到 0-100 进度槽位。"""
        for s, _, _, pct in self._PIPELINE_STAGES:
            if s == stage:
                return pct
        if stage == "waiting_for_preview_confirmation":
            return 40
        if stage == "error":
            return 0
        return 0

    # 抽取自 editor_module.py L7604-7613
    def _stage_label(self, stage: str) -> str:
        """把 stage 字符串映射为带 emoji 的标签文本。"""
        for s, emoji, label, _ in self._PIPELINE_STAGES:
            if s == stage:
                return f"{emoji} {label}"
        if stage == "waiting_for_preview_confirmation":
            return "⏸️ 等待预览确认"
        if stage == "error":
            return "❌ 执行失败"
        return "⚙️ 执行中"

    # 抽取自 editor_module.py L7618-7629
    def _get_pipeline_params(self) -> Dict[str, Any]:
        """从配置卡收集 pipeline.run_full 参数（UI 层只读）。"""
        p = getattr(self, "_agent_platform_combo", None)
        d = getattr(self, "_agent_duration_combo", None)
        c = getattr(self, "_agent_clip_duration_spin", None)
        pv = getattr(self, "_agent_provider_combo", None)
        return {
            "platform": p.currentData() if p else "douyin",
            "target_duration": float(d.currentData() if d else 30.0),
            "clip_duration": float(c.value() if c else 5.0),
            "provider": pv.currentData() if pv else "auto",
        }

    # 抽取自 editor_module.py L7631-7668；V4.36.0 起含 P1-1 报价 + P1-2 健康灯
    def _refresh_provider_status(self):
        """刷新 provider 状态标签（只读查询，不修改 client）。

        V4.36.0：
        - **P1-2 健康灯**：配了账号但无一健康（退避中/配额尽）或封装不可用的渠道，
          在 provider 下拉里**变灰禁选**；状态行给出人话原因。
        - **P1-1 报价**：按当前 UI 参数（时长/单段/渠道）预估「预计 ¥X」，只读预演。
        """
        lbl = getattr(self, "_agent_provider_status_lbl", None)
        if lbl is None:
            return
        # 主题感知的状态灯样式（样式工厂提供，不再硬编颜色）
        try:
            S = self._agent_panel_styles()
        except Exception:
            S = {}
        ok_css = S.get("status_ok", "color:#2dd4bf;font-size:10px;")
        warn_css = S.get("status_warn", "color:#fb7185;font-size:10px;font-weight:700;")
        dim_css = S.get("status_dim", "color:#aab6cc;font-size:10px;")
        try:
            from app.core.ai.video_generation_client import video_generation_client
            combo = getattr(self, "_agent_provider_combo", None)
            chosen = combo.currentData() if combo is not None else "auto"
            providers = video_generation_client.list_providers()

            def _row(pid: str) -> dict:
                return next((x for x in providers if x.get("id") == pid), {}) or {}

            def _dead(pid: str) -> bool:
                """死号 = 封装不可用，或配了账号但无一健康（退避/配额尽）。"""
                r = _row(pid)
                if not r.get("available", False):
                    return True
                h = r.get("health") or {}
                return h.get("accounts", 0) > 0 and h.get("healthy", 0) <= 0

            # ── P1-2：死号在下拉里变灰禁选（auto/local 永远可选）──
            if combo is not None:
                model = combo.model()
                for i in range(combo.count()):
                    pid = combo.itemData(i)
                    if pid in ("auto", "local", None):
                        continue
                    item = model.item(i) if hasattr(model, "item") else None
                    if item is not None:
                        item.setEnabled(not _dead(pid))

            # ── P1-1：按当前 UI 参数报价（只读预演，不消耗额度）──
            seg_n = 0
            q = {}
            try:
                p = self._get_pipeline_params()
                seg_n = max(1, int(float(p["target_duration"]) // float(p["clip_duration"])))
                q = video_generation_client.quote(
                    str(p["provider"]), count=seg_n,
                    duration=float(p["clip_duration"])) or {}
            except Exception:
                logger.debug("[Agent] 生成报价失败（不影响状态显示）", exc_info=True)
            cost = float(q.get("cost_estimate") or 0.0)
            if q.get("cloud_available"):
                acct = q.get("account_id") or ""
                quota = q.get("quota_remaining")
                cost_txt = f"预计 ¥{cost:.2f}（{q.get('count', seg_n)}段×{q.get('provider')}"
                if acct:
                    cost_txt += f"·{acct}"
                if isinstance(quota, int):
                    cost_txt += f"·配额余{quota}"
                cost_txt += "）"
            else:
                cost_txt = "本地占位（免费）"

            # ── 状态行（三档文案）──
            if chosen == "auto":
                cloud_names = [p.get("id", "").upper() for p in providers
                               if p.get("id") not in ("local",)
                               and p.get("available", False)
                               and not _dead(p.get("id", ""))]
                if cloud_names:
                    lbl.setText(f"✔ 云端可用: {', '.join(cloud_names)} · {cost_txt}")
                    lbl.setStyleSheet(ok_css)
                else:
                    lbl.setText(f"⚠ 云端渠道不可用/全死号 · {cost_txt}")
                    lbl.setStyleSheet(warn_css)
            elif chosen == "local":
                lbl.setText(f"使用本地占位色块生成（无需网络） · {cost_txt}")
                lbl.setStyleSheet(dim_css)
            else:
                if _dead(chosen):
                    reason = (q.get("reason") or "死号/封装不可用")
                    lbl.setText(f"⚠ {chosen.upper()} {reason}，将回退本地色块 · {cost_txt}")
                    lbl.setStyleSheet(warn_css)
                else:
                    h = _row(chosen).get("health") or {}
                    extra = f"·配额余{h.get('quota_remaining')}" \
                        if h.get("accounts", 0) > 0 else ""
                    lbl.setText(f"✔ {chosen.upper()} 可用{extra} · {cost_txt}")
                    lbl.setStyleSheet(ok_css)
        except Exception as e:
            logger.debug(f"[Agent] provider 状态刷新失败: {e}")
            lbl.setText("")

    # 抽取自 editor_module.py L7674-7690
    def _update_pipeline_stage(self, stage: str, message: str = ""):
        """根据 stage 更新进度卡（UI 层只渲染，不参与调度）。"""
        card = getattr(self, "_agent_progress_card", None)
        bar = getattr(self, "_agent_stage_bar", None)
        lbl = getattr(self, "_agent_stage_label", None)
        det = getattr(self, "_agent_stage_detail", None)
        if card is None or bar is None or lbl is None:
            return
        card.setVisible(True)
        pct = self._stage_progress(stage)
        if pct > 0:
            # 允许进度条只前进不回退
            if pct >= bar.value():
                bar.setValue(pct)
        lbl.setText(self._stage_label(stage))
        if det is not None and message:
            det.setText(message[:120])

    # 抽取自 editor_module.py L7692-7718
    def _finalize_pipeline_stage(self, success: bool, error: str = "", degraded: bool = False):
        """完成时把进度条置 100%（或失败为红色；降级为琥珀色文案）。"""
        bar = getattr(self, "_agent_stage_bar", None)
        lbl = getattr(self, "_agent_stage_label", None)
        det = getattr(self, "_agent_stage_detail", None)
        if bar is None:
            return
        if success and not degraded:
            bar.setValue(100)
            if lbl:
                lbl.setText("✅ 执行完成")
            if det:
                det.setText(error or "")
        elif success and degraded:
            bar.setValue(100)
            if lbl:
                lbl.setText("⚠️ 降级完成（无成片）")
            if det:
                det.setText((error or "仅有脚本/中间结果")[:120])
        else:
            bar.setStyleSheet("QProgressBar{background:#161b22;border:1px solid #30363d;border-radius:4px;height:8px;}"
                              "QProgressBar::chunk{background:#ff7b72;border-radius:4px;}")
            bar.setValue(100)
            if lbl:
                lbl.setText("❌ 执行失败")
            if det:
                det.setText(error[:120] if error else "")

    # 抽取自 editor_module.py L7724-7745
    def _render_preview_issues(self, failed_clips: List[Dict[str, Any]]):
        """渲染预览失败片段列表（保守版：clip_id）。"""
        lst = getattr(self, "_agent_preview_list", None)
        card = getattr(self, "_agent_preview_card", None)
        clbl = getattr(self, "_agent_preview_count_lbl", None)
        if lst is None or card is None:
            return
        lst.clear()
        if not failed_clips:
            card.setVisible(False)
            return
        for c in failed_clips:
            cid = c.get("clip_id") or c.get("id", "?")
            path = c.get("path", "")
            short_path = os.path.basename(path) if path else ""
            text = f"🔴 {cid}   {short_path}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, c)
            lst.addItem(it)
        if clbl:
            clbl.setText(f"共 {len(failed_clips)} 个片段")
        card.setVisible(True)

    # 抽取自 editor_module.py L7761-7793
    def _on_manual_edit_clicked(self):
        """一键手动精剪：调用既有 pipeline.execute_editing 能力。"""
        script = getattr(self, "_last_editing_script", None)
        if not script:
            QMessageBox.information(self, "手动精剪", "暂无可用的剪辑脚本。")
            return
        btn = getattr(self, "_agent_manual_edit_btn", None)
        if btn is not None:
            btn.setEnabled(False)
        try:
            self._append_agent_message("Agent", "▶ 开始手动精剪（应用转场/字幕/配乐）...")
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            res = capability_dispatcher.invoke(CapabilityRequest(
                capability_id="pipeline.execute_editing",
                params={"editing_script": script, "session_id": ""},
                caller="agent_manual_edit",
            ))
            if res.success:
                out = res.output or {}
                final = out.get("final_video_path", "")
                if final and os.path.exists(final):
                    self._append_agent_message("Agent", f"✅ 手动精剪完成！成片：\n{final}")
                else:
                    msg = out.get("message", "已执行精剪")
                    self._append_agent_message("Agent", f"✅ 精剪执行完成：{msg}")
            else:
                self._append_agent_message("Agent", f"❌ 精剪执行失败：{res.error}")
        except Exception as e:
            logger.exception("[Agent] 手动精剪按钮异常")
            self._append_agent_message("Agent", f"❌ 精剪执行异常: {e}")
        finally:
            if btn is not None:
                btn.setEnabled(True)

    # 抽取自 editor_module.py L7903-7912
    def _on_edit_agent_chunk(self, chunk: str):
        """缓存模型流式输出。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 本槽由 QThread.chunk_ready 信号高频触发（每个 token 一次），
        # 若 _edit_agent_stream_buffer 未初始化或主窗口切换中属性已销毁，
        # 会 AttributeError 穿透到信号分发器导致主线程崩溃。
        try:
            self._edit_agent_stream_buffer = getattr(self, '_edit_agent_stream_buffer', "") + chunk
        except Exception as e:
            logger.warning(f"[Agent] _on_edit_agent_chunk 处理失败: {e}")

    # 抽取自 editor_module.py L7997-8004
    def _show_agent_plan(self, plan_steps: List[str], commands: List[Any], user_text: str):
        """展示 Plan 模式规划，等待用户确认。"""
        self._pending_plan_commands = commands
        self._pending_plan_user_text = user_text
        # 格式化规划步骤
        plan_text = "\n".join([f"{i+1}. {step}" for i, step in enumerate(plan_steps)])
        self._agent_plan_view.setPlainText(plan_text)
        self._agent_plan_card.setVisible(True)

    # 抽取自 editor_module.py L8006-8019
    def _confirm_agent_plan(self):
        """用户确认执行 Plan 规划。"""
        commands = getattr(self, '_pending_plan_commands', [])
        if not commands:
            self._append_agent_message("系统", "没有可执行的指令。")
            self._agent_plan_card.setVisible(False)
            return
        self._append_agent_message("系统", "开始执行规划...")
        results = self._apply_agent_commands_to_editor(commands)
        summary = self._format_agent_command_summary(results)
        self._append_agent_message("系统", summary or "规划已处理。")
        self._agent_plan_card.setVisible(False)
        self._pending_plan_commands = []
        self._pending_plan_user_text = ""

    # 抽取自 editor_module.py L8021-8026
    def _cancel_agent_plan(self):
        """用户取消 Plan 规划。"""
        self._agent_plan_card.setVisible(False)
        self._pending_plan_commands = []
        self._pending_plan_user_text = ""
        self._append_agent_message("系统", "规划已取消。")

    # 抽取自 editor_module.py L8028-8032
    def _on_agent_feedback(self, event):
        """收到反馈时在 Agent 面板显示提示（非侵入）"""
        summary = (event.data or {}).get("summary", "")
        if summary:
            self._append_agent_message("系统", f"📦 收到新反馈: {summary}（下次指令将自动参考）")

    # 抽取自 editor_module.py L8071-8078
    def _on_edit_agent_stopped(self):
        """Agent 被用户终止。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # 用户点终止按钮触发，若 Agent 面板已销毁访问 QTextEdit 会 RuntimeError。
        try:
            self._append_agent_message("系统", "当前 Agent 输出已终止。")
        except Exception as e:
            logger.warning(f"[Agent] _on_edit_agent_stopped 处理失败: {e}")

    # 抽取自 editor_module.py L8080-8100
    def _on_edit_agent_finished(self):
        """恢复 Agent 按钮状态。"""
        # 顶层 try/except 兜底（P0 闪退修复）：
        # finished 是 QThread 内置信号，无论成功/失败/异常 100% 必触发。
        # 若用户已切换模块按钮可能已 deleteLater，访问会 RuntimeError 崩溃。
        try:
            send_btn = getattr(self, '_edit_agent_send_btn', None)
            stop_btn = getattr(self, '_edit_agent_stop_btn', None)
            if send_btn is not None:
                send_btn.setEnabled(True)
            if stop_btn is not None:
                stop_btn.setEnabled(False)
                stop_btn.setVisible(False)   # 任务结束 → 收回终止按钮（V4.34.1 输入区瘦身）
            inbox = getattr(self, "_edit_agent_inbox", None) or []
            if inbox:
                nxt = inbox.pop(0)
                self._edit_agent_inbox = inbox
                self._edit_agent_input.setText(nxt)
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, self._send_edit_agent_message)
        except Exception as e:
            logger.warning(f"[Agent] _on_edit_agent_finished 处理失败: {e}")

    # 抽取自 editor_module.py L8173-8189
    def _on_pipeline_event(self, event):
        """监听全链路相关事件，更新 Agent 面板状态。"""
        try:
            data = event.data if hasattr(event, "data") else event
            if not isinstance(data, dict):
                return
            subtype = data.get("subtype", "")
            if subtype == "pipeline_waiting_preview":
                self._handle_waiting_preview(data)
            elif subtype == "pipeline_progress":
                self._handle_pipeline_progress(data)
            elif subtype == "pipeline_done":
                self._handle_pipeline_done(data)
            elif subtype == "video_generation_done":
                self._handle_video_generation_done(data)
        except Exception as e:
            logger.debug(f"[Agent] 处理全链路事件失败: {e}")

    # 抽取自 editor_module.py L8191-8212
    def _handle_video_generation_done(self, data: Dict):
        """检测是否使用了本地占位色块回退，如有则提醒用户。"""
        lbl = getattr(self, "_agent_provider_status_lbl", None)
        if lbl is None:
            return
        try:
            paths = data.get("paths", []) or []
            if not paths:
                return
            # 判断文件名前缀是否为 gen_*（本地占位生成）
            import os as _os
            all_local = all(_os.path.basename(str(p)).startswith("gen_") for p in paths)
            if all_local:
                existing = lbl.text()
                note = "⚠ 本次生成使用了本地占位色块（云端 provider 不可用）"
                if note not in existing:
                    new_text = (existing + "\n" + note) if existing.strip() else note
                    lbl.setText(new_text)
                    lbl.setStyleSheet("color:#ff7b72;font-size:10px;font-weight:700;")
                self._append_agent_message("系统", note)
        except Exception as e:
            logger.debug(f"[Agent] 处理生成回退提示失败: {e}")

    # 抽取自 editor_module.py L8214-8252
    def _handle_waiting_preview(self, data: Dict):
        """处理等待预览确认事件：更新按钮状态、提示 + 渲染预览问题卡。"""
        status = data.get("status", {})
        failed_count = status.get("by_status", {}).get("failed", 0)
        total = status.get("total", 0)

        # ── 新增：渲染预览问题片段列表（保守版） ──
        try:
            from app.core.preview_validation_loop import (
                preview_validation_loop, PreviewStatus
            )
            failed_clips = preview_validation_loop.get_clips_by_status(
                PreviewStatus.FAILED
            )
            self._render_preview_issues(failed_clips)
        except Exception as e:
            logger.debug(f"[Agent] 渲染预览问题列表失败: {e}")

        # ── 新增：进度卡停在 waiting_for_preview_confirmation ──
        self._update_pipeline_stage(
            "waiting_for_preview_confirmation",
            f"{failed_count}/{total} 个片段需要人工确认"
        )

        self._append_agent_message(
            "Agent",
            f"⏸️ 全链路已暂停：预览发现 {failed_count}/{total} 个片段有问题。\n"
            f"请在时间线上调整后，点击下方【✅ 确认预览并继续】按钮继续执行。",
        )
        # 切换按钮状态
        pipeline_btn = getattr(self, "_edit_agent_pipeline_btn", None)
        if pipeline_btn:
            pipeline_btn.setText("✅ 确认预览并继续")
            pipeline_btn.setStyleSheet(
                "QPushButton{background:#1f6feb;color:#fff;border:1px solid #388bfd;"
                "border-radius:8px;padding:6px 12px;font-size:11px;font-weight:700;}"
                "QPushButton:hover{background:#388bfd;}"
            )
            pipeline_btn.setProperty("waiting_preview", True)

    # 抽取自 editor_module.py L8254-8278
    def _handle_pipeline_progress(self, data: Dict):
        """处理全链路进度更新事件。"""
        stage = data.get("stage", "")
        message = data.get("message", "")
        # ── 新增：刷新进度卡 ──
        self._update_pipeline_stage(stage, message)
        # 保留原有 emoji 消息追加逻辑
        if not message:
            return
        if stage == "routing":
            self._append_agent_message("Agent", f"🔀 {message}")
        elif stage == "generation":
            self._append_agent_message("Agent", f"🎬 {message}")
        elif stage == "import_parsing":
            self._append_agent_message("Agent", f"📥 {message}")
        elif stage == "preview":
            self._append_agent_message("Agent", f"🔍 {message}")
        elif stage == "scoring":
            self._append_agent_message("Agent", f"📊 {message}")
        elif stage == "scripting":
            self._append_agent_message("Agent", f"📝 {message}")
        elif stage == "editing":
            self._append_agent_message("Agent", f"✂️ {message}")
        elif stage == "done":
            self._append_agent_message("Agent", f"✅ {message}")

    # 抽取自 editor_module.py L8281-8291
    def _reset_pipeline_button(self):
        """重置全链路按钮状态。"""
        pipeline_btn = getattr(self, "_edit_agent_pipeline_btn", None)
        if pipeline_btn:
            pipeline_btn.setText("🚀 全链路执行（生成→预览→打分→精剪→成片）")
            pipeline_btn.setStyleSheet(
                "QPushButton{background:#1f2a3d;color:#7ee787;border:1px solid #2f5139;"
                "border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}"
                "QPushButton:hover{background:#238636;color:#fff;border-color:#238636;}"
            )
            pipeline_btn.setProperty("waiting_preview", False)

    # 抽取自 editor_module.py L8363-8392
    def _on_full_pipeline_done(self, result):
        """全链路执行完成回调（主线程刷新 UI）。"""
        send_btn = getattr(self, "_edit_agent_send_btn", None)
        if send_btn is not None:
            send_btn.setEnabled(True)
        if result.success:
            out = result.output or {}
            final_path = out.get("final_video_path", "")
            route = (out.get("route") or {}).get("route", "")
            scored = out.get("scored_count", 0)
            degraded = bool(out.get("degraded")) or (
                not final_path and bool(out.get("editing_script"))
            )
            if final_path and not degraded:
                msg = (f"✅ 全链路完成｜分流:{route} 打分镜头:{scored}｜成片:\n{final_path}")
            elif degraded:
                reason = out.get("error") or "未产出成片文件，仅有脚本/中间结果"
                msg = (
                    f"⚠️ 全链路降级完成（非成片成功）｜分流:{route} 打分:{scored}\n"
                    f"{reason}\n请用脚本卡【▶ 一键手动精剪】导出，勿当作已自动成片。"
                )
            else:
                msg = (
                    f"⚠️ 标记成功但无成片路径｜分流:{route} 打分:{scored}（请查日志）"
                )
            self._append_agent_message("Agent", msg)
        else:
            self._append_agent_message(
                "Agent", f"❌ 全链路失败（非假成功）: {result.error}"
            )

