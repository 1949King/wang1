"""
AI 导演技能模块（全功能型）
========================
直接调 LLM 从零生成剧本/分镜表/剪辑指令/字幕，
可选 Blender MCP 渲染 3D 片头，可选把素材按分镜顺序落地剪辑时间线。

设计原则：
    - 全功能型：不依赖现有 SmartClip/AutoSubtitle，独立完成导演全链路
    - 三级降级：云服务 → Ollama 本地 → 模板占位，保证离线可用
    - 最小侵入：只复用 ai_engine / mcp_client 现有接口，不改其符号
    - 异常安全：每步 try/except，LLM 失败不阻断主流程

复用来源：
    - app.core.ai_engine.AIEngine.chat_with_fallback (L533)
    - app.core.mcp_client.McpClientManager + BLENDER_MCP_CONFIG (L81/L454)
    - app.modules.lego.skill_engine.Skill 基类 (L87)
    - EventBus MATERIAL_TO_TIMELINE（与画布回流同一条「素材→时间线」总线事件，
      editor_module.py:582 订阅 _on_material_dropped 落到 EditorModule._clips）
"""

import json
import logging
import os
import time
from typing import Dict, List

from .skill_engine import Skill, StepResult

logger = logging.getLogger(__name__)


class DirectorSkill(Skill):
    """AI 导演技能 - 全功能型

    输入主题或素材，LLM 生成完整剧本→分镜表→剪辑指令→字幕，
    可选 Blender MCP 渲染 3D 片头，最终汇总导演报告。

    输入参数（inputs）：
        - topic:   str  主题/题材（如 "30秒科技产品介绍"）
        - script:  str  可选，直接提供剧本跳过生成
        - use_blender: bool 可选，True 时尝试连 Blender MCP 渲染 3D 片头
        - source_dir: str 可选，素材目录（含视频文件）。提供后新增「落地时间线」
            步骤：按分镜顺序把素材加入剪辑时间线（经 EventBus
            MATERIAL_TO_TIMELINE，与画布回流同一条总线）。
            不提供则保持只出导演报告（edit_instructions_applied_to_timeline=False）。
    """

    skill_id = "director"
    skill_name = "AI 导演（全功能）"
    skill_description = "输入主题，LLM 从零生成剧本→分镜表→剪辑指令→字幕，可选 Blender 3D 片头、可选素材落时间线"
    skill_category = "AI 导演"
    skill_icon = "🎬"
    skill_version = "1.1.0"

    def _setup_steps(self):
        """设置导演流程步骤（顺序执行，3D片头为条件步骤）"""
        self.add_step(
            name="生成剧本",
            handler=self._generate_script
        ).add_step(
            name="生成分镜表",
            handler=self._generate_storyboard,
            dependencies=["生成剧本"]
        ).add_step(
            name="生成剪辑指令",
            handler=self._generate_edit_instructions,
            dependencies=["生成分镜表"]
        ).add_step(
            name="提取字幕",
            handler=self._extract_subtitles,
            dependencies=["生成分镜表"]
        ).add_step(
            name="渲染3D片头",
            handler=self._render_3d_intro,
            condition=self._should_use_blender,
            dependencies=["生成剧本"]
        ).add_step(
            name="落地时间线",
            handler=self._apply_to_timeline,
            condition=self._should_apply_timeline,
            dependencies=["生成剪辑指令"]
        ).add_step(
            name="合成导演报告",
            handler=self._compose_final,
            dependencies=["生成剪辑指令", "提取字幕"]
        )

    # ────────────────────────────────────────────────────────────────
    # 步骤 1：生成剧本
    # ────────────────────────────────────────────────────────────────
    def _generate_script(self, context) -> StepResult:
        """调 LLM 生成完整剧本（场景/对白/动作）—— 薄委托 script_writer（单一真源）"""
        # 步骤1 是最早执行的，在此同步 use_blender 标志到 variables
        # 供步骤5的 _should_use_blender condition 读取（condition 在步骤执行前求值）
        context.set_variable("_use_blender", bool(context.get_input("use_blender", False)))
        # 同理同步 source_dir，供「落地时间线」步骤的 condition 读取
        context.set_variable(
            "_source_dir", str(context.get_input("source_dir") or "").strip())
        # 优先用用户提供的剧本
        user_script = context.get_input("script")
        if user_script and user_script.strip():
            context.set_variable("script", user_script)
            return StepResult(success=True, output={"script": user_script, "source": "user"})

        topic = context.get_input("topic") or "30秒短视频"
        self._report_progress(10, f"正在生成剧本: {topic}")

        # 单一真源：app/core/ai/script_writer.py（Agent 能力 pipeline.script_write 同源）
        from app.core.ai.script_writer import write_script
        res = write_script(topic)
        context.set_variable("script", res["script"])
        context.set_variable("topic", topic)
        context.set_variable("script_is_template", bool(res.get("fallback")))
        return StepResult(success=True, output={
            "script": res["script"], "fallback": bool(res.get("fallback"))})

    def _fallback_script(self, topic: str) -> str:
        """LLM 不可用时的占位剧本 —— 薄委托 script_writer（单一真源）"""
        from app.core.ai.script_writer import fallback_script
        return fallback_script(topic)

    # ────────────────────────────────────────────────────────────────
    # 步骤 2：生成分镜表
    # ────────────────────────────────────────────────────────────────
    def _generate_storyboard(self, context) -> StepResult:
        """调 LLM 把剧本拆成结构化分镜表（编号/时长/景别/对白）"""
        script = context.get_variable("script")
        if not script:
            return StepResult(success=False, error="剧本为空，无法拆分镜")

        self._report_progress(30, "正在生成分镜表...")

        try:
            from app.core.ai_engine import AIEngine
            engine = AIEngine()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是分镜师。把剧本拆成结构化分镜表，每镜一行 JSON："
                        '{"id":1,"duration":5,"shot":"特写/中景/远景",'
                        '"description":"画面描述","dialogue":"对白"}。'
                        "输出 JSON 数组，不要其他文字。"
                    )
                },
                {"role": "user", "content": f"剧本：\n{script}\n\n请输出分镜表 JSON。"}
            ]
            full = ""
            for chunk in engine.chat_with_fallback(
                messages,
                template=lambda: self._fallback_storyboard(script)
            ):
                full += chunk
            full = full.strip()

            # 尝试解析为 JSON，失败则用 fallback
            # 修复：此前 LLM 有输出但解析失败这条路径（未抛异常）不会标记
            # fallback，只有 except 分支才标记——实际上这里同样是模板占位，
            # 此前的 output/summary 会把它当成"LLM 真实生成"展示。
            storyboard = self._parse_storyboard_json(full)
            is_fallback = not storyboard
            if not storyboard:
                storyboard = self._fallback_storyboard(script)
            context.set_variable("storyboard_raw", full)
            context.set_variable("storyboard", storyboard)
            context.set_variable("storyboard_is_template", is_fallback)
            return StepResult(success=True, output={"storyboard": storyboard, "fallback": is_fallback})
        except Exception as e:
            storyboard = self._fallback_storyboard(script)
            context.set_variable("storyboard", storyboard)
            context.set_variable("storyboard_is_template", True)
            return StepResult(
                success=True,
                output={"storyboard": storyboard, "fallback": True, "error": str(e)}
            )

    def _parse_storyboard_json(self, text: str) -> List[Dict]:
        """从 LLM 输出中提取 JSON 数组（兼容代码块包裹）"""
        try:
            # 去除可能的 ```json 代码块标记
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                cleaned = cleaned.strip()
            # 找到第一个 [ 到最后一个 ]
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            logger.debug("分镜表 LLM 输出 JSON 解析失败，走启发式降级", exc_info=True)
        return []

    def _fallback_storyboard(self, script: str) -> List[Dict]:
        """LLM 不可用时的占位分镜表"""
        return [
            {"id": 1, "duration": 5, "shot": "远景",
             "description": "开场镜头推近", "dialogue": "今天，带你看一个不一样的故事。"},
            {"id": 2, "duration": 15, "shot": "特写",
             "description": "主体展示", "dialogue": "这就是主角，专注每一个细节。"},
            {"id": 3, "duration": 10, "shot": "中景",
             "description": "收尾定格", "dialogue": "感谢观看，期待下次相遇。"},
        ]

    # ────────────────────────────────────────────────────────────────
    # 步骤 3：生成剪辑指令
    # ────────────────────────────────────────────────────────────────
    def _generate_edit_instructions(self, context) -> StepResult:
        """调 LLM 生成分镜表对应的时间线剪辑指令 JSON"""
        storyboard = context.get_variable("storyboard")
        if not storyboard:
            return StepResult(success=False, error="分镜表为空，无法生成剪辑指令")

        self._report_progress(55, "正在生成剪辑指令...")

        try:
            from app.core.ai_engine import AIEngine
            engine = AIEngine()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是剪辑师。根据分镜表生成时间线剪辑指令 JSON："
                        '{"clips":[{"start":0,"end":5,"track":"video",'
                        '"source":"场景描述","transition":"cut"}]}。'
                        "输出纯 JSON，不要其他文字。"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"分镜表：\n{json.dumps(storyboard, ensure_ascii=False)}\n\n"
                        "请生成剪辑指令 JSON。"
                    )
                }
            ]
            full = ""
            for chunk in engine.chat_with_fallback(
                messages,
                template=lambda: self._fallback_edit_instructions(storyboard)
            ):
                full += chunk
            full = full.strip()

            instructions = self._parse_edit_json(full)
            is_fallback = not instructions
            if not instructions:
                instructions = self._fallback_edit_instructions(storyboard)

            context.set_variable("edit_instructions", instructions)
            context.set_variable("edit_instructions_is_template", is_fallback)
            return StepResult(success=True, output={"edit_instructions": instructions, "fallback": is_fallback})
        except Exception as e:
            instructions = self._fallback_edit_instructions(storyboard)
            context.set_variable("edit_instructions", instructions)
            context.set_variable("edit_instructions_is_template", True)
            return StepResult(
                success=True,
                output={"edit_instructions": instructions, "fallback": True, "error": str(e)}
            )

    def _parse_edit_json(self, text: str) -> Dict:
        """解析剪辑指令 JSON（兼容代码块）"""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                cleaned = cleaned.strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            logger.debug("剪辑指令 LLM 输出 JSON 解析失败，走模板降级", exc_info=True)
        return {}

    def _fallback_edit_instructions(self, storyboard: List[Dict]) -> Dict:
        """LLM 不可用时的占位剪辑指令"""
        clips = []
        cursor = 0.0
        for shot in storyboard:
            duration = float(shot.get("duration", 5))
            clips.append({
                "start": cursor,
                "end": cursor + duration,
                "track": "video",
                "source": shot.get("description", ""),
                "transition": "cut"
            })
            cursor += duration
        return {"clips": clips, "total_duration": cursor}

    # ────────────────────────────────────────────────────────────────
    # 步骤 4：提取字幕
    # ────────────────────────────────────────────────────────────────
    def _extract_subtitles(self, context) -> StepResult:
        """从分镜表对白提取 SRT 字幕（不依赖 LLM）"""
        storyboard = context.get_variable("storyboard")
        if not storyboard:
            return StepResult(success=False, error="分镜表为空，无法提取字幕")

        self._report_progress(75, "正在提取字幕...")

        try:
            srt_lines = []
            cursor = 0.0
            for i, shot in enumerate(storyboard, 1):
                duration = float(shot.get("duration", 5))
                dialogue = shot.get("dialogue", "").strip()
                if not dialogue:
                    cursor += duration
                    continue
                srt_lines.append(str(i))
                srt_lines.append(f"{self._format_srt_time(cursor)} --> {self._format_srt_time(cursor + duration)}")
                srt_lines.append(dialogue)
                srt_lines.append("")
                cursor += duration

            srt_content = "\n".join(srt_lines)
            context.set_variable("srt", srt_content)
            return StepResult(success=True, output={"srt": srt_content, "count": len(srt_lines) // 4})
        except Exception as e:
            return StepResult(success=False, error=f"提取字幕失败: {e}")

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """格式化 SRT 时间戳 HH:MM:SS,mmm"""
        ms = int((seconds % 1) * 1000)
        s = int(seconds % 60)
        m = int(seconds // 60 % 60)
        h = int(seconds // 3600)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    # ────────────────────────────────────────────────────────────────
    # 步骤 5：渲染 3D 片头（条件执行）
    # ────────────────────────────────────────────────────────────────
    def _should_use_blender(self, variables: Dict) -> bool:
        """条件：仅当用户 inputs 指定 use_blender=True 时执行"""
        # variables 是 context.variables，但 inputs 在 context.inputs
        # condition 回调签名是 (variables)，无法直接拿 inputs
        # 通过在 _generate_script 里把 use_blender 写入 variables 解决
        return bool(variables.get("_use_blender", False))

    def _render_3d_intro(self, context) -> StepResult:
        """调用 Blender MCP 渲染 3D 片头（连接失败则跳过）"""
        topic = context.get_variable("topic") or "片头"
        self._report_progress(85, f"正在渲染 3D 片头: {topic}")

        try:
            from app.core.mcp_client import McpClientManager, BLENDER_MCP_CONFIG
            client = McpClientManager()
            config = dict(BLENDER_MCP_CONFIG)
            config["name"] = "Blender MCP (Director)"

            if not client.connect(config):
                return StepResult(
                    success=False,
                    error=f"Blender MCP 连接失败: {client.last_error or '未知错误'}"
                )

            try:
                # 尝试调用 Blender MCP 创建一个简单片头场景
                # harveyxiacn 版默认 skill profile 含 create_object / render_scene
                create_result = client.call_tool("create_object", {
                    "type": "TEXT",
                    "name": f"片头_{topic[:10]}",
                    "location": [0, 0, 1]
                })
                render_result = client.call_tool("render_scene", {
                    "output_path": os.path.join(os.getcwd(), "director_intro.png")
                })
                intro_path = ""
                if isinstance(render_result, dict):
                    intro_path = render_result.get("result", {}).get("output_path", "")
                context.set_variable("intro_path", intro_path)
                return StepResult(
                    success=True,
                    output={"intro_path": intro_path, "create_result": str(create_result)}
                )
            finally:
                client.disconnect()
        except Exception as e:
            # Blender MCP 不可用不阻断主流程，仅标记本步骤失败
            return StepResult(success=False, error=f"3D 片头渲染失败: {e}")

    # ────────────────────────────────────────────────────────────────
    # 步骤 5.5：落地时间线（条件执行，2026-09-26 LibTV 对标 P0-1）
    # ────────────────────────────────────────────────────────────────
    # 视频扩展名白名单已迁至 app/core/ai/director_timeline.py::MEDIA_EXTS（单一真源）

    def _should_apply_timeline(self, variables: Dict) -> bool:
        """条件：inputs 给了 source_dir 且已有分镜表。"""
        return bool(variables.get("_source_dir") and variables.get("storyboard"))

    def _collect_media_files(self, source_dir: str, cap: int = 200) -> List[str]:
        """递归收集素材目录里的视频文件 —— 薄委托 director_timeline（单一真源）"""
        from app.core.ai.director_timeline import collect_media_files
        return collect_media_files(source_dir, cap=cap)

    def _apply_to_timeline(self, context) -> StepResult:
        """把素材按分镜顺序加入剪辑时间线 —— 薄委托 director_timeline（单一真源）。

        机制：发 EventBus ``MATERIAL_TO_TIMELINE`` 批量载荷 —— 与画布回流
        （canvas_bridge.push_to_timeline）用的是同一条总线事件，
        ``editor_module.py:582`` 订阅 ``_on_material_dropped`` 批量分支，
        最终落到 ``EditorModule._clips``（时间线真相源）。

        如实边界（详见 app/core/ai/director_timeline.py 模块注释）：
          - 加入的片段按**素材原始时长**排布；分镜表的精确裁剪点仍在
            剪辑指令里（可用「裁剪片段/重锚片段」能力二次调整）。
          - 若剪辑模块未打开（无订阅者），不落地，报告如实标注。
        """
        source_dir = context.get_variable("_source_dir") or ""
        storyboard = context.get_variable("storyboard") or []

        from app.core.ai.director_timeline import apply_storyboard_to_timeline
        res = apply_storyboard_to_timeline(source_dir, storyboard)

        applied = bool(res.get("applied"))
        note = str(res.get("note") or res.get("reason") or "")
        context.set_variable("timeline_applied", applied)
        context.set_variable("timeline_apply_note", note)
        if applied:
            self._report_progress(
                90, f"正在把 {res.get('clips')} 个素材按分镜顺序加入时间线...")
        return StepResult(success=True, output=res)

    # ────────────────────────────────────────────────────────────────
    # 步骤 6：合成导演报告
    # ────────────────────────────────────────────────────────────────
    def _compose_final(self, context) -> StepResult:
        """汇总所有产物，输出导演报告"""
        self._report_progress(95, "正在合成导演报告...")

        # 如实汇总各步骤是否用了模板占位（LLM 不可用/解析失败时的降级），
        # 此前这些信息只留在各步骤自己的 StepResult.output 里，
        # 最终报告/摘要完全没有体现，用户看到"生成完成"会以为都是真实
        # LLM 产物。
        script_is_template = bool(context.get_variable("script_is_template", False))
        storyboard_is_template = bool(context.get_variable("storyboard_is_template", False))
        edit_is_template = bool(context.get_variable("edit_instructions_is_template", False))
        any_template = script_is_template or storyboard_is_template or edit_is_template

        # 落地时间线结果（步骤「落地时间线」写入；条件未触发时为默认 False）
        timeline_applied = bool(context.get_variable("timeline_applied", False))
        timeline_apply_note = str(context.get_variable("timeline_apply_note", ""))

        report = {
            "topic": context.get_variable("topic", ""),
            "script": context.get_variable("script", ""),
            "storyboard": context.get_variable("storyboard", []),
            "edit_instructions": context.get_variable("edit_instructions", {}),
            "srt": context.get_variable("srt", ""),
            "intro_path": context.get_variable("intro_path", ""),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "script_is_template": script_is_template,
            "storyboard_is_template": storyboard_is_template,
            "edit_instructions_is_template": edit_is_template,
            # 素材是否已落地剪辑时间线：
            #   True  = 经 MATERIAL_TO_TIMELINE 总线按分镜顺序加入（需 source_dir）
            #   False = 只出报告（未提供 source_dir / 目录无素材 / 剪辑模块未打开）
            "edit_instructions_applied_to_timeline": timeline_applied,
            "timeline_apply_note": timeline_apply_note,
        }

        # 输出最终报告到 context.outputs
        context.set_output("director_report", report)
        context.set_output("script", report["script"])
        context.set_output("storyboard", report["storyboard"])
        context.set_output("edit_instructions", report["edit_instructions"])
        context.set_output("srt", report["srt"])

        template_note = ""
        if any_template:
            parts = []
            if script_is_template:
                parts.append("剧本")
            if storyboard_is_template:
                parts.append("分镜表")
            if edit_is_template:
                parts.append("剪辑指令")
            template_note = f"\n  ⚠️ LLM 不可用或解析失败，以下内容为本地模板占位（非真实生成）：{'/'.join(parts)}"

        timeline_note = (
            f"（{timeline_apply_note}）" if timeline_applied
            else (f"（未落地：{timeline_apply_note}）" if timeline_apply_note
                  else "（未提供素材目录 source_dir，仅出指令建议，可手动剪辑）")
        )
        summary = (
            f"导演报告生成完成\n"
            f"  主题: {report['topic']}\n"
            f"  剧本: {len(report['script'])} 字\n"
            f"  分镜: {len(report['storyboard'])} 镜\n"
            f"  剪辑指令: {len(report['edit_instructions'].get('clips', []))} 段"
            f"{timeline_note}\n"
            f"  字幕: {len(report['srt'].splitlines()) // 4} 条\n"
            f"  3D片头: {report['intro_path'] or '未渲染（use_blender未开启或连接失败）'}"
            f"{'\n  ✅ 素材已按分镜顺序加入剪辑时间线' if timeline_applied else ''}"
            f"{template_note}"
        )
        return StepResult(success=True, output={"result": summary, "report": report})
