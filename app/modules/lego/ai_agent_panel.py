"""
ai_agent_panel.py
=================
AiAgentPanelMixin：从 editor_module.py 抽出的 AI 相关方法（Mixin 模式）。

设计目标（遵循 .trae/rules/2.md §三 架构分层）：
- **最小侵入**：方法体完全照搬，self 访问不变，符合 §二.3 不破坏原有功能
- **零回归风险**：方法签名/实现不变，只是文件位置改变
- **单一职责**：本 Mixin 只承载 AI 相关方法，被 EditorModule 继承
- **不独立实例化**：Mixin 模式，必须混入宿主类使用

迁移的方法（共 6 个，约 242 行）：
1. _on_ai_clip：智能剪辑入口（LLM + 传统算法双路径）
2. _on_ai_clip_fallback：传统算法回退路径
3. _on_ai_fail：AI 字幕失败回调
4. _on_ai_progress：AI 进度更新回调
5. _apply_agent_commands_to_editor：批量执行 Agent 指令
6. _apply_agent_command：执行单条 Agent 指令

使用方式：
    class EditorModule(BaseModule, AiAgentPanelMixin):
        ...

迁移后 EditorModule 实例通过 self 访问这些方法，MRO 解析到本 Mixin。
所有 self.xxx 属性访问由 EditorModule.__init__ 提供，不会断裂。
"""

import os
import threading
import logging
from typing import Any, Dict, List

from PyQt6.QtWidgets import QMessageBox, QApplication

logger = logging.getLogger("AI短剧编辑器.editor")

# 修复：本文件多处调用 show_clear_messagebox（空时间线/文件不存在等提示），
# 但从未 import 过它——点「LLM 智能裁剪」等按钮在这些提前返回分支上必
# NameError 崩溃。真实定义在 modules.py，但不能在模块顶层 import：
# main_window 懒加载时是直接 `import .editor_module`（不经过 modules.py），
# 而 editor_module 又混入本 Mixin；若这里顶层 `from .modules import ...`，
# modules.py 执行到文件末尾的 `from .editor_module import EditorModule` 时
# editor_module 还在初始化中，会形成循环导入 ImportError。改用函数内局部
# import（和 editor_export_panel.py 里同样场景的写法一致），只在真正调用
# 时才触发，此时两个模块都已完整加载，不会循环。
def _clear_msgbox(title: str, message: str, parent=None):
    from .modules import show_clear_messagebox
    return show_clear_messagebox(title, message, parent)

# A：对话指令白名单 —— 单一事实来源见 agent_action_registry（防提示词漂移）
from app.core.agent_action_registry import (
    get_allowed_actions,
    get_dangerous_actions,
    get_safe_actions,
)

_AGENT_SAFE_ACTIONS = get_safe_actions()
_AGENT_DANGEROUS_ACTIONS = get_dangerous_actions()
_AGENT_ALLOWED_ACTIONS = get_allowed_actions()
# 对话 action ↔ capability：见 agent_action_registry.ACTION_TO_CAPABILITY


class AiAgentPanelMixin:
    """AI 智能剪辑与 Agent 指令执行 Mixin。

    本 Mixin 从 editor_module.py 抽出，承载 AI 相关方法。被 EditorModule
    继承后，通过 self 访问 EditorModule 的所有属性和其他方法。

    A+C（2026-08）：白名单 + 危险操作确认；未知/失败诚实文案（非假成功）。
    """

    # ────────────── 智能剪辑入口 ──────────────

    def _on_ai_clip(self):
        """
        智能剪辑入口
        - 若 Ollama 可用 + 有提示词: LLM 智能裁剪 (FunClip 风格)
        - 否则: 明确提示原因后，询问是否回退传统算法
        """
        if not self._clips:
            _clear_msgbox("操作提示", "请先导入视频")
            return

        # 获取用户提示词（兼容 _prompt_edit 可能不存在的情况）
        try:
            prompt = self._prompt_edit.text().strip() if hasattr(self, '_prompt_edit') else ""
        except Exception:
            prompt = ""

        video_path = self._clips[0]['path']
        if not os.path.exists(video_path):
            _clear_msgbox("操作提示", "视频文件不存在")
            return

        # ---- LLM 路径 ----
        from app.core.ai.llm_clipper import is_llm_clip_available, get_llm_clipper, LLMClipper

        if not prompt:
            reply = QMessageBox.question(
                self,
                "LLM 智能裁剪",
                "未填写提示词，无法走 LLM 裁剪。\n\n是否改用传统算法（场景/音频分析）？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_ai_clip_fallback(video_path, prompt)
            return

        if not is_llm_clip_available():
            reason = LLMClipper.ollama_unavailable_reason()
            reply = QMessageBox.question(
                self,
                "LLM 不可用",
                f"{reason}\n\n是否改用传统算法？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._on_ai_clip_fallback(video_path, prompt)
            return

        logger.info(f'▶ [LLM] 开始智能剪辑, 提示词: {prompt}')
        if hasattr(self, "_ai_task_label"):
            self._ai_task_label.setText("任务: LLM 智能裁剪中...")
            self._ai_task_label.setStyleSheet("color:#f59e0b;font-size:10px;font-weight:600;")
        if hasattr(self, "_ai_progress"):
            self._ai_progress.setValue(10)
            self._ai_progress.show()

        def _ui_done(ok: bool, message: str, result_path: str = ""):
            def _apply():
                if hasattr(self, "_ai_progress"):
                    self._ai_progress.hide()
                if hasattr(self, "_ai_task_label"):
                    self._ai_task_label.setText("任务: 待机中")
                    self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
                if ok and result_path:
                    QMessageBox.information(self, "AI 智能剪辑完成", message)
                    try:
                        self._load_video(result_path)
                    except Exception as e:
                        logger.warning("加载 LLM 输出失败: %s", e)
                else:
                    reply = QMessageBox.question(
                        self,
                        "LLM 剪辑未完成",
                        f"{message}\n\n是否改用传统算法？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        self._on_ai_clip_fallback(video_path, prompt)
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, _apply)

        def _run_llm_clip():
            try:
                clipper = get_llm_clipper()
                result_path = clipper.smart_clip(video_path, prompt=prompt)
                if result_path and os.path.isfile(result_path):
                    _ui_done(True, f"LLM 剪辑完成!\n输出: {result_path}", result_path)
                else:
                    err = getattr(clipper, "last_error", "") or "LLM 未返回有效结果"
                    _ui_done(False, err)
            except Exception as e:
                _ui_done(False, f"失败: {e}")

        import threading
        threading.Thread(target=_run_llm_clip, daemon=True).start()

    def _on_ai_clip_fallback(self, video_path: str, prompt: str):
        """
        传统 AIClipAlgorithm 路径（cv2/audio 分析）
        当 Ollama 不可用或 prompt 为空时使用。
        """
        logger.info(f'▶ 开始智能剪辑(传统), 提示词: {prompt}')

        try:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("智能剪辑")
            msg_box.setText("正在分析视频...\n这可能需要几分钟时间")
            msg_box.setStandardButtons(QMessageBox.StandardButton.NoButton)
            msg_box.show()
            QApplication.processEvents()

            ai_clip_algorithm = self._ensure_ai_clip_algorithm()
            if ai_clip_algorithm is None:
                msg_box.close()
                QMessageBox.warning(self, "智能剪辑", "智能剪辑算法不可用（模块加载失败）")
                return
            result_path = ai_clip_algorithm.process_video(
                video_path, prompt, output_length=20
            )

            msg_box.close()
            if not result_path or not os.path.isfile(str(result_path)):
                QMessageBox.warning(
                    self, "智能剪辑",
                    "传统算法未产出有效文件（空结果）。请换素材或检查日志。",
                )
                return
            QMessageBox.information(self, "智能剪辑完成",
                                      f"剪辑完成!\n输出路径: {result_path}")
            self._load_video(result_path)

        except Exception as e:
            QMessageBox.warning(self, "处理失败", f"智能剪辑失败: {str(e)}")
            logger.error(f'智能剪辑失败: {e}')

    def _on_ai_fail(self, message: str):
        """主线程回调：字幕生成失败"""
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText("任务: 待机中")
            self._ai_task_label.setStyleSheet("color:#888;font-size:10px;")
        if hasattr(self, '_ai_progress'):
            self._ai_progress.hide()
        QMessageBox.warning(self, "AI字幕", message)

    def _on_ai_progress(self, value: int, msg: str):
        """主线程回调：更新进度条"""
        if hasattr(self, '_ai_progress'):
            self._ai_progress.setValue(value)
            self._ai_progress.show()
        if hasattr(self, '_ai_task_label'):
            self._ai_task_label.setText(f"任务: {msg}")

    # ────────────── Agent 指令执行 ──────────────

    @staticmethod
    def _format_agent_command_summary(results: List[Dict[str, Any]]) -> str:
        """C：汇总成功/跳过/失败，避免笼统「已执行」。"""
        ok = [r for r in results if r.get("success") and not r.get("skipped")]
        skipped = [r for r in results if r.get("skipped")]
        failed = [r for r in results if not r.get("success") and not r.get("skipped")]
        parts = [f"成功 {len(ok)}", f"跳过 {len(skipped)}", f"失败 {len(failed)}"]
        detail = "；".join(
            r.get("message", "") for r in results if r.get("message")
        )
        head = " / ".join(parts)
        return f"{head}。{detail}" if detail else head

    def _confirm_dangerous_agent_commands(self, commands: List[Any]) -> bool:
        """A：危险指令（删除/波纹删）一次性确认；自主 C 跳过；取消则整批危险指令跳过。"""
        try:
            from app.core.agent_policy import MODE_AUTONOMOUS, normalize_mode

            combo = getattr(self, "_agent_mode_combo", None)
            mode = normalize_mode(combo.currentData() if combo is not None else "collaborative")
            if mode == MODE_AUTONOMOUS:
                return True
        except Exception:
            pass
        dangers = [
            c for c in commands
            if getattr(c, "action", "") in _AGENT_DANGEROUS_ACTIONS
        ]
        if not dangers:
            return True
        lines = []
        for i, c in enumerate(dangers, 1):
            action = getattr(c, "action", "")
            params = getattr(c, "params", {}) or {}
            desc = getattr(c, "description", "") or action
            extra = ""
            if params.get("clip_index") == "all":
                extra = f"（将删除全部 {len(getattr(self, '_clips', []) or [])} 个片段）"
            elif params.get("t_in") is not None or params.get("start_time") is not None:
                t_in = params.get("t_in", params.get("start_time"))
                t_out = params.get("t_out", params.get("end_time"))
                extra = f"（区间 {t_in}–{t_out}）"
            lines.append(f"{i}. {action} — {desc}{extra}")
        body = (
            "以下操作会改写时间线（删除/波纹删除），确认后才会执行。\n"
            "可事后 Ctrl+Z 撤销（波纹删走 B1 时可整组回滚）。\n\n"
            + "\n".join(lines)
        )
        reply = QMessageBox.question(
            self,
            "确认危险操作",
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _select_agent_commands_for_apply(self, commands: List[Any]) -> List[Any]:
        """B：建议清单勾选后才改时间线；C 仍自动执行白名单；取消则不写轨。"""
        try:
            from app.core.agent_policy import MODE_AUTONOMOUS, normalize_mode
            from app.modules.lego.suggest_checklist import (
                format_agent_command_label,
                merge_checked_commands,
                partition_agent_commands,
                pick_checked_indices,
            )
        except Exception:
            return list(commands)
        combo = getattr(self, "_agent_mode_combo", None)
        mode = normalize_mode(combo.currentData() if combo is not None else "collaborative")
        if mode == MODE_AUTONOMOUS:
            return list(commands)
        reads, writes = partition_agent_commands(commands)
        if not writes:
            return list(reads)
        labels = [format_agent_command_label(c, i + 1) for i, c in enumerate(writes)]
        picked = pick_checked_indices(
            self,
            title="确认后写入时间线",
            hint=(
                f"Agent 建议 {len(writes)} 条会改时间线的指令。"
                "勾选后点「执行选中」才写入；未勾选的不会执行。可事后 Ctrl+Z 撤销。"
            ),
            labels=labels,
            default_checked=True,
            ok_text="执行选中",
        )
        if picked is None:
            return list(reads)
        return merge_checked_commands(reads, writes, picked)

    def _apply_agent_commands_to_editor(self, commands: List[Any]) -> List[Dict[str, Any]]:
        """将 Agent 指令落到当前剪辑模块的真实时间线数据上（白名单 + 勾选确认）。"""
        results: List[Dict[str, Any]] = []
        to_run = self._select_agent_commands_for_apply(commands)
        if not to_run:
            return [{
                "action": "suggest_list",
                "success": False,
                "skipped": True,
                "message": "已取消或未勾选，未改时间线",
            }]
        selected_ids = {id(c) for c in to_run}
        skipped_unselected = [c for c in commands if id(c) not in selected_ids]
        for command in skipped_unselected:
            action = getattr(command, "action", "unknown")
            if action in ("answer", "info"):
                continue
            results.append({
                "action": action,
                "success": False,
                "skipped": True,
                "message": f"未勾选，跳过「{action}」",
            })
        allow_dangerous = True

        for command in to_run:
            action = getattr(command, "action", "unknown")
            try:
                if action not in _AGENT_ALLOWED_ACTIONS:
                    allowed = ", ".join(sorted(_AGENT_ALLOWED_ACTIONS))
                    results.append({
                        "action": action,
                        "success": False,
                        "skipped": True,
                        "message": (
                            f"已拒绝未授权指令「{action}」（非假成功）。"
                            f"允许: {allowed}"
                        ),
                    })
                    continue
                if action in _AGENT_DANGEROUS_ACTIONS and not allow_dangerous:
                    results.append({
                        "action": action,
                        "success": False,
                        "skipped": True,
                        "message": f"用户取消，未执行危险指令「{action}」",
                    })
                    continue
                results.append(self._apply_agent_command(command))
            except Exception as e:
                results.append({
                    "action": action,
                    "success": False,
                    "message": f"执行异常（已中止该条，非整批假成功）: {e}",
                })
        try:
            self._sync_timeline_widget_state()
        except Exception as e:
            logger.warning(f"[Agent] _sync_timeline_widget_state 失败: {e}")
        try:
            self._refresh_preview_with_effects()
        except Exception as e:
            logger.warning(f"[Agent] _refresh_preview_with_effects 失败: {e}")
        return results

    def _agent_ripple_delete_range(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """M4：走公开包装 agent_ripple_delete_range（B1 + UI 同步，可撤销）。"""
        t_in = params.get("t_in", params.get("start_time"))
        t_out = params.get("t_out", params.get("end_time"))
        if t_in is None or t_out is None:
            return {
                "action": action,
                "success": False,
                "message": "ripple_delete 需要 t_in/t_out（或 start_time/end_time），未执行",
            }
        track = params.get("track")
        track_i = int(track) if track is not None else None
        res = self.agent_ripple_delete_range(float(t_in), float(t_out), track=track_i)
        if isinstance(res, dict):
            res = dict(res)
            res["action"] = action
            if res.get("success"):
                res["message"] = f"{res.get('message', '完成')}（可撤销）"
            return res
        return {"action": action, "success": False, "message": "波纹删除无结果"}

    def _agent_read_media(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """读素材元信息（get_media / inspect_media）：返回完整结构化信息，不截断。"""
        import json
        # clip_index / clip_id 均支持：解析为 clip_id 再交给 capability
        clip = self._resolve_agent_clip(params)
        p = dict(params)
        if clip and clip.get("id"):
            p.setdefault("clip_id", clip.get("id"))
        try:
            from app.core.capability_dispatcher import capability_dispatcher, CapabilityRequest
            result = capability_dispatcher.invoke(CapabilityRequest(
                capability_id="editor.inspect_media",
                params=p,
                caller="agent",
                agent_mode=self._get_agent_session_mode() if hasattr(self, "_get_agent_session_mode") else "",
                approved=True,
            ))
        except Exception as e:
            return {"action": action, "success": False, "message": f"读取素材失败: {e}"}
        if not result.success:
            return {"action": action, "success": False, "message": result.error or "读取素材失败"}
        payload = result.output or {}
        return {
            "action": action,
            "success": True,
            "message": f"素材元信息：{json.dumps(payload, ensure_ascii=False)}",
        }

    def _apply_agent_command(self, command) -> Dict[str, Any]:
        """执行单条 Agent 指令（调用方已做白名单/危险确认）。"""
        action = getattr(command, "action", "")
        params = getattr(command, "params", {}) or {}
        if action in ("answer", "info"):
            return {"action": action, "success": True, "message": params.get("message", getattr(command, "description", ""))}
        if action == "add_track":
            track_type = params.get("track_type", "video")
            name = params.get("name", "Agent 轨道")
            # 修复：此前用 hasattr 判断——属性不存在时静默跳过真实调用，
            # 却仍返回 success=True「已添加轨道」，时间线上其实什么都没变化。
            timeline_widget = getattr(self, "_timeline_widget", None)
            if timeline_widget is None:
                return {"action": action, "success": False,
                        "message": "时间线尚未就绪，无法添加轨道"}
            try:
                track = timeline_widget.add_track(name, track_type)
            except Exception as e:
                return {"action": action, "success": False, "message": f"添加轨道失败: {e}"}
            if not track:
                return {"action": action, "success": False, "message": "添加轨道失败：未知原因"}
            return {"action": action, "success": True, "message": f"已添加{track_type}轨道"}
        if action in ("ripple_delete", "ripple_delete_range"):
            # 有时间区间 → 公开包装（B1+UI）；ripple_delete 无区间时退化为按片段删
            if params.get("t_in") is not None or params.get("start_time") is not None:
                return self._agent_ripple_delete_range(action, params)
            if action == "ripple_delete_range":
                return {
                    "action": action,
                    "success": False,
                    "message": "ripple_delete_range 需要 t_in/t_out（或 start_time/end_time）",
                }
            action = "remove_clip"
        if action == "remove_clip":
            if params.get("clip_index") == "all":
                count = len(self._clips)
                if count == 0:
                    return {"action": action, "success": False, "message": "时间线无片段可删"}
                for clip in list(self._clips):
                    self._delete_clip_by_id(clip.get("id"))
                return {"action": action, "success": True, "message": f"已删除全部 {count} 个片段"}
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要删除的片段"}
            self._delete_clip_by_id(clip.get("id"))
            return {"action": action, "success": True, "message": "片段已删除"}
        if action == "duplicate_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要复制的片段"}
            self._copy_clip_data_to_timeline(clip, offset=params.get("offset", clip.get("duration", 1)))
            return {"action": action, "success": True, "message": "片段已复制到时间线"}
        if action == "trim_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要裁剪的片段"}
            duration = params.get("new_duration") or params.get("duration")
            if not duration and params.get("end_time") is not None:
                duration = float(params.get("end_time")) - float(params.get("start_time", clip.get("start_time", 0)))
            if not duration or float(duration) <= 0:
                return {"action": action, "success": False, "message": "裁剪时长无效"}
            clip["duration"] = float(duration)
            clip["out_point"] = clip.get("in_point", 0) + float(duration)
            return {"action": action, "success": True, "message": f"片段已裁剪为 {float(duration):.1f}s"}
        if action == "split_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要切分的片段"}
            split_time = float(params.get("split_time", getattr(self, '_playhead_position', 0)))
            res = self.agent_split_clip(clip, split_time)
            if isinstance(res, dict):
                res.setdefault("action", action)
                return res
            return {"action": action, "success": True, "message": str(res)}
        if action in ("add_transition", "transition"):
            clip = self._resolve_agent_clip(params) or getattr(self, '_current_clip', None)
            if not clip:
                return {"action": action, "success": False, "message": "请先选择片段再添加转场"}
            transition_type = params.get("transition_type", "fade")
            duration = float(params.get("duration", 0.5))
            self.agent_apply_transition(clip, transition_type, duration)
            return {"action": action, "success": True, "message": f"已应用 {transition_type} 转场"}
        if action in ("add_effect", "apply_filter"):
            clip = self._resolve_agent_clip(params) or getattr(self, '_current_clip', None)
            if not clip:
                return {"action": action, "success": False, "message": "请先选择片段再添加效果"}
            effect_type = params.get("effect_type", "filter")
            effect_params = params.get("params", params)
            if effect_type == "filter":
                filter_name = effect_params.get("filter_name", params.get("filter_name", "selected"))
                intensity = float(effect_params.get("intensity", params.get("intensity", 0.7)))
                self.agent_apply_filter(clip, filter_name, intensity)
                return {"action": action, "success": True, "message": f"已应用滤镜 {filter_name}"}
            self._apply_effect_to_clip(clip, effect_type, effect_params)
            return {"action": action, "success": True, "message": f"已应用效果 {effect_type}"}
        if action == "call_extension":
            return self._agent_call_extension(params)
        if action == "call_model":
            return self._agent_dispatch("model.chat_with_fallback", params)
        if action == "start_workflow":
            return self._agent_dispatch("workflow.start", params)
        if action == "account_optimize":
            return self._agent_dispatch("account.optimize_strategy", params)
        if action == "suggest_cleanup":
            open_ui = bool(params.get("open_ui", True))
            res = self.agent_suggest_cleanup(open_ui=open_ui)
            if isinstance(res, dict):
                res.setdefault("action", action)
                return res
            return {"action": action, "success": False, "message": str(res)}
        if action == "canvas_open":
            return self._agent_dispatch("canvas.open", params)
        if action == "canvas_sync_models":
            return self._agent_dispatch("canvas.sync_models", params)
        if action in ("get_media", "inspect_media"):
            return self._agent_read_media(action, params)
        if action == "move_clip":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要移动的片段"}
            if params.get("new_start_time") is None:
                return {"action": action, "success": False, "message": "move_clip 需要 new_start_time（秒）"}
            try:
                new_start = float(params["new_start_time"])
            except (TypeError, ValueError):
                return {"action": action, "success": False, "message": "new_start_time 参数无效"}
            if not self.move_clip(clip.get("id"), new_start):
                return {"action": action, "success": False, "message": "移动片段失败（片段可能不在时间线）"}
            return {"action": action, "success": True, "message": f"已移动片段到 {new_start:.2f}s"}
        if action == "change_speed":
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要变速的片段"}
            applied: Dict[str, Any] = {}
            if params.get("speed") is not None:
                try:
                    speed = float(params["speed"])
                except (TypeError, ValueError):
                    return {"action": action, "success": False, "message": "speed 参数无效"}
                if not self.set_clip_speed(clip.get("id"), speed):
                    return {"action": action, "success": False, "message": "设置速度失败（片段可能不在时间线）"}
                applied["speed"] = speed
            if "reverse" in params:
                clip["reverse"] = bool(params["reverse"])
                self._sync_kernel_timeline()
                self._refresh_preview_with_effects()
                applied["reverse"] = bool(params["reverse"])
            if not applied:
                return {"action": action, "success": False, "message": "change_speed 需要 speed 或 reverse 参数"}
            return {"action": action, "success": True, "message": "变速/倒放已应用"}
        if action in ("add_keyframe", "set_keyframes"):
            clip = self._resolve_agent_clip(params)
            if not clip:
                return {"action": action, "success": False, "message": "未找到要写关键帧的片段"}
            # 支持批量 list，也兼容单点（time/prop/value 直接挂 params）
            raw_keyframes = params.get("keyframes")
            if not isinstance(raw_keyframes, list):
                raw_keyframes = [params]
            normalized: List[Dict[str, Any]] = []
            try:
                for kf in raw_keyframes:
                    if not isinstance(kf, dict):
                        continue
                    prop = kf.get("prop") or kf.get("property") or kf.get("name")
                    if prop is None:
                        continue
                    normalized.append({
                        "prop": str(prop),
                        "time_offset": float(kf.get("time_offset", kf.get("time", 0.0))),
                        "value": kf.get("value", 0.0),
                        "easing": str(kf.get("easing") or kf.get("interpolation") or "linear"),
                    })
            except (TypeError, ValueError):
                return {"action": action, "success": False, "message": "关键帧参数无效：time/value 需为数值"}
            if not normalized:
                return {"action": action, "success": False, "message": "关键帧参数无效：缺少 prop/value"}
            if not self.add_keyframes_to_clip(clip.get("id"), normalized):
                return {"action": action, "success": False, "message": "写入关键帧失败（片段可能不在时间线）"}
            return {"action": action, "success": True, "message": f"已写入 {len(normalized)} 个关键帧"}
        # 正常不应到达（外层白名单）；仍给诚实文案
        return {
            "action": action,
            "success": False,
            "skipped": True,
            "message": f"未授权指令「{action}」（防御分支）",
        }
