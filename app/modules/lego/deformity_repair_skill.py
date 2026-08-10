"""
畸形根治闭环 Skill（四层全链路）
================================
封装定稿方案「畸形/穿模/动作错乱根治方案」的四层闭环：
    L1 前置标准化约束 → L2 生成过程实时管控 → L3 插帧补偿 → L4 AI 自动质检&局部修复
外加「技能库联动」入库步骤，形成自闭环。

设计原则：
    - 骨架型 + fallback：当前项目 OpenPose/SMPL/骨骼约束库尚未实现，
      每步优先调真实能力（ai_interpolation / ai_engine），不可用时降级到
      LLM 判断或占位模板，保证 Skill 能跑通且为未来真实能力留接入点。
    - 最小侵入：只复用 ai_engine / ai_interpolation 现有接口，不改其符号。
    - 异常安全：每步 try/except，单步失败不阻断闭环。

复用来源：
    - app.core.ai_engine.AIEngine.chat_with_fallback (L533) 三级降级
    - app.core.ai_interpolation.SceneChangeDetector (L64) 帧差检测
    - app.modules.lego.skill_engine.Skill 基类 (L87)
"""

import json
import os
import time
from typing import Dict, Any, List

from .skill_engine import Skill, StepResult


# ────────────────────────────────────────────────────────────────────
# 默认骨骼约束模板（占位，未来接真实约束库）
# 锁定肩/肘/腕/腰/膝最大旋转角度，手部专项规则
# ────────────────────────────────────────────────────────────────────
DEFAULT_SKELETON_CONSTRAINTS = {
    "joints": {
        "shoulder": {"max_rotation": 90, "axis": "xyz"},
        "elbow": {"max_rotation": 150, "axis": "xy"},
        "wrist": {"max_rotation": 180, "axis": "xyz"},
        "waist": {"max_rotation": 45, "axis": "z"},
        "knee": {"max_rotation": 135, "axis": "xy"},
    },
    "hand_rules": {
        "fingers_fixed": 5,
        "phalanges_distinct": True,
        "no_penetration_face": True,
        "no_penetration_body": True,
    },
    "safe_transitions": ["fade", "motion_match", "camera_push"],
}


class DeformityRepairSkill(Skill):
    """畸形根治闭环 Skill

    四层闭环 + 入库，输入待质检的剪辑片段/AI 生成素材描述，
    输出质检报告 + 修复决策 + 入库记录。

    输入参数（inputs）：
        - clips:        List  待质检片段列表，每项含 {id, description, duration, prev_end_desc}
        - project_type: str   "series"（连载漫剧，用长期记忆）/"short"（独立短片，用便签）
        - use_skeleton: bool  可选，True 时尝试调真实骨骼识别（占位）
    """

    skill_id = "deformity_repair"
    skill_name = "畸形根治闭环"
    skill_description = "四层全链路：前置约束→生成管控→插帧补偿→质检修复→案例入库，根治穿模/动作错乱"
    skill_category = "AI 质检"
    skill_icon = "🦴"
    skill_version = "1.0.0"

    def _setup_steps(self):
        """设置四层闭环 + 入库 + 报告共 7 步"""
        self.add_step(
            name="L1 前置标准化约束",
            handler=self._apply_pre_standardization
        ).add_step(
            name="L2 生成过程实时管控",
            handler=self._monitor_generation,
            dependencies=["L1 前置标准化约束"]
        ).add_step(
            name="L3 插帧补偿（双模式）",
            handler=self._interpolate_compensate,
            dependencies=["L2 生成过程实时管控"]
        ).add_step(
            name="L4a 三重巡检",
            handler=self._triple_inspection,
            dependencies=["L3 插帧补偿（双模式）"]
        ).add_step(
            name="L4b 分级修复",
            handler=self._grade_repair,
            dependencies=["L4a 三重巡检"]
        ).add_step(
            name="技能库联动入库",
            handler=self._archive_cases,
            dependencies=["L4b 分级修复"]
        ).add_step(
            name="合成闭环报告",
            handler=self._compose_report,
            dependencies=["L4b 分级修复", "技能库联动入库"]
        )

    # ════════════════════════════════════════════════════════════════
    # L1：前置标准化约束
    # ════════════════════════════════════════════════════════════════
    def _apply_pre_standardization(self, context) -> StepResult:
        """L1：骨骼约束加载 + 分镜文本规范化 + 首帧锚定"""
        self._report_progress(5, "L1 加载前置标准化约束...")

        # 1. 加载骨骼约束（连载→永久档案占位，独立→便签占位）
        project_type = context.get_input("project_type") or "short"
        constraints = self._load_skeleton_constraints(project_type)
        context.set_variable("skeleton_constraints", constraints)
        context.set_variable("project_type", project_type)

        # 2. 分镜文本规范化（LLM 改写模糊动作为标准化描述）
        clips = context.get_input("clips") or []
        normalized = self._normalize_storyboard(clips)
        context.set_variable("clips_normalized", normalized)

        # 3. 首帧锚定（每段首帧锁定前段尾帧特征）
        anchors = self._anchor_first_frame(normalized)
        context.set_variable("frame_anchors", anchors)

        return StepResult(success=True, output={
            "constraints_loaded": len(constraints.get("joints", {})),
            "clips_normalized": len(normalized),
            "anchors_set": len(anchors),
        })

    def _load_skeleton_constraints(self, project_type: str) -> Dict:
        """加载骨骼约束模板（占位：返回默认模板；未来接真实约束库）"""
        # TODO 未来：连载项目从全局永久档案读取，独立项目从便签读取
        # 当前：返回默认约束模板
        constraints = dict(DEFAULT_SKELETON_CONSTRAINTS)
        constraints["source"] = "default_template"
        constraints["project_type"] = project_type
        return constraints

    def _normalize_storyboard(self, clips: List[Dict]) -> List[Dict]:
        """LLM 规范化分镜文本（模糊动作→标准化描述）"""
        if not clips:
            return []

        self._report_progress(15, "L1 规范化分镜文本...")

        try:
            from app.core.ai_engine import AIEngine
            engine = AIEngine()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是分镜规范化师。把模糊动作描述改写为标准化动作脚本，"
                        "强制标注：镜头景别、运动轨迹、道具位置、关节动作。"
                        "示例：「男主抬手」→「画面右侧手臂沿弧线缓慢抬起，肘部先行，"
                        "手腕跟随，手掌自然张开，手部不接触脸部与躯干」。"
                        "输出 JSON 数组，每项含 id/standard_description/shot_type/trajectory。"
                    )
                },
                {
                    "role": "user",
                    "content": f"分镜列表：\n{json.dumps(clips, ensure_ascii=False)}\n\n请规范化。"
                }
            ]
            full = ""
            for chunk in engine.chat_with_fallback(
                messages,
                template=lambda: self._fallback_normalize(clips)
            ):
                full += chunk
            parsed = self._parse_json_array(full)
            return parsed if parsed else self._fallback_normalize(clips)
        except Exception:
            return self._fallback_normalize(clips)

    def _fallback_normalize(self, clips: List[Dict]) -> List[Dict]:
        """LLM 不可用时的占位规范化"""
        result = []
        for clip in clips:
            result.append({
                "id": clip.get("id"),
                "standard_description": clip.get("description", "") + "（动作沿弧线，关节不超限）",
                "shot_type": clip.get("shot_type", "中景"),
                "trajectory": clip.get("trajectory", "静止"),
            })
        return result

    def _anchor_first_frame(self, clips: List[Dict]) -> List[Dict]:
        """首帧锚定：每段首帧锁定前段尾帧特征（占位，未来接真实帧特征提取）"""
        anchors = []
        for i, clip in enumerate(clips):
            anchor = {
                "clip_id": clip.get("id"),
                "anchor_type": "first_frame",
                # TODO 未来：真实提取前段尾帧的人物样貌/体型/空间位置特征
                "anchor_features": {
                    "pose": "standing" if i == 0 else "from_prev_end",
                    "position": clip.get("position", [0, 0, 0]),
                },
            }
            anchors.append(anchor)
        return anchors

    # ════════════════════════════════════════════════════════════════
    # L2：生成过程实时管控
    # ════════════════════════════════════════════════════════════════
    def _monitor_generation(self, context) -> StepResult:
        """L2：骨骼识别 + 安全转场 + 拼接比对"""
        self._report_progress(30, "L2 生成过程实时管控...")

        clips = context.get_variable("clips_normalized", [])
        constraints = context.get_variable("skeleton_constraints", {})

        # 1. 骨骼关键点识别（占位，未来接 OpenPose/SMPL）
        skeletons = self._detect_skeletons(clips)
        context.set_variable("skeletons", skeletons)

        # 2. 拼接比对（相邻片段人物位置/动作差值）
        comparisons = self._compare_adjacent_clips(clips, skeletons)
        context.set_variable("clip_comparisons", comparisons)

        # 3. 安全转场模板检查
        unsafe_transitions = [
            c for c in comparisons
            if c.get("transition_type") not in constraints.get("safe_transitions", [])
            and c.get("transition_type") != "none"
        ]
        context.set_variable("unsafe_transitions", unsafe_transitions)

        return StepResult(success=True, output={
            "skeletons_detected": len(skeletons),
            "comparisons": len(comparisons),
            "unsafe_transitions": len(unsafe_transitions),
        })

    def _detect_skeletons(self, clips: List[Dict]) -> List[Dict]:
        """骨骼关键点识别（占位：返回 mock 关键点；未来接 OpenPose/SMPL）

        如实说明：keypoints/confidence/within_constraint 目前是固定占位值
        （未接入真实的 OpenPose/SMPL 姿态识别），不是对画面的真实检测结果。
        `source: "placeholder"` 标记供下游报告/UI 判断是否要提示用户。
        """
        # TODO 未来：调真实 OpenPose/SMPL 识别
        # 当前：为每段生成占位关键点
        skeletons = []
        for clip in clips:
            skeletons.append({
                "clip_id": clip.get("id"),
                "keypoints": "mock_17_points",  # OpenPose 17 关键点占位
                "confidence": 0.85,
                "within_constraint": True,  # 占位：默认在约束内
                "source": "placeholder",
            })
        return skeletons

    def _compare_adjacent_clips(self, clips: List[Dict], skeletons: List[Dict]) -> List[Dict]:
        """比对相邻片段人物位置/动作走向，差值超标预警"""
        comparisons = []
        for i in range(1, len(clips)):
            prev = clips[i - 1]
            curr = clips[i]
            # 占位差值计算（未来用真实关键点距离）
            position_diff = 0.3  # mock
            action_continuity = 0.7  # mock
            transition = curr.get("trajectory", "cut")

            warning = position_diff > 0.5 or action_continuity < 0.5
            comparisons.append({
                "from_clip": prev.get("id"),
                "to_clip": curr.get("id"),
                "position_diff": position_diff,
                "action_continuity": action_continuity,
                "transition_type": transition,
                "warning": warning,
            })
        return comparisons

    # ════════════════════════════════════════════════════════════════
    # L3：插帧补偿（双模式）
    # ════════════════════════════════════════════════════════════════
    def _interpolate_compensate(self, context) -> StepResult:
        """L3：双模式插帧（剪辑轻量顺滑 / AI 逻辑搭桥）"""
        self._report_progress(50, "L3 插帧补偿（双模式）...")

        comparisons = context.get_variable("clip_comparisons", [])
        clips = context.get_variable("clips_normalized", [])

        interpolation_plan = []
        for cmp in comparisons:
            if not cmp.get("warning"):
                continue
            # 判断模式：动作连续但跳变→轻量插帧；动作割裂→逻辑搭桥
            if cmp.get("action_continuity", 0) >= 0.5:
                mode = "lightweight"  # 模式1：5~15帧过渡
                frame_count = 10
            else:
                mode = "logic_bridge"  # 模式2：0.2~2s 过渡片段
                frame_count = 30

            plan = {
                "from_clip": cmp["from_clip"],
                "to_clip": cmp["to_clip"],
                "mode": mode,
                "frame_count": frame_count,
                "skeleton_check_passed": self._verify_interpolation_skeleton(),
            }
            interpolation_plan.append(plan)

        # 尝试调真实 ai_interpolation（可选，失败不阻断）
        real_result = self._try_real_interpolation(clips)

        context.set_variable("interpolation_plan", interpolation_plan)
        context.set_variable("real_interpolation", real_result)

        return StepResult(success=True, output={
            "interpolation_count": len(interpolation_plan),
            "modes": [p["mode"] for p in interpolation_plan],
            "real_engine_used": real_result.get("used", False),
        })

    def _verify_interpolation_skeleton(self) -> bool:
        """插帧画面骨骼校验（占位，未来接真实校验；不合格应丢弃重绘）"""
        # TODO 未来：强制校验骨骼/手部结构，不合格直接丢弃重绘
        return True  # 占位：默认通过

    def _try_real_interpolation(self, clips: List[Dict]) -> Dict:
        """尝试调真实 ai_interpolation.SceneChangeDetector（失败降级）"""
        try:
            from app.core.ai_interpolation import SceneChangeDetector, FrameDifferenceType
            # 真实调用需要帧数据，当前 clips 是描述无帧，故仅验证可导入
            detector = SceneChangeDetector()
            return {"used": False, "reason": "clips 无帧数据，仅验证引擎可用", "engine": "linear_blend"}
        except Exception as e:
            return {"used": False, "reason": f"ai_interpolation 不可用: {e}", "engine": "none"}

    # ════════════════════════════════════════════════════════════════
    # L4a：三重巡检
    # ════════════════════════════════════════════════════════════════
    def _triple_inspection(self, context) -> StepResult:
        """L4a：肢体巡检 + 逻辑巡检 + 时序巡检"""
        self._report_progress(70, "L4a 三重自动化巡检...")

        clips = context.get_variable("clips_normalized", [])
        skeletons = context.get_variable("skeletons", [])
        comparisons = context.get_variable("clip_comparisons", [])

        # 肢体巡检：手部畸形/肢体穿插/关节超限
        limb_issues = self._inspect_limb(skeletons)
        # 逻辑巡检：动作与剧本匹配度/道具空间物理常识
        logic_issues = self._inspect_logic(clips)
        # 时序巡检：镜头衔接/转场节奏
        timing_issues = self._inspect_timing(comparisons)

        all_issues = limb_issues + logic_issues + timing_issues
        context.set_variable("inspection_issues", all_issues)
        context.set_variable("issue_count", len(all_issues))

        return StepResult(success=True, output={
            "limb_issues": len(limb_issues),
            "logic_issues": len(logic_issues),
            "timing_issues": len(timing_issues),
            "total": len(all_issues),
        })

    def _inspect_limb(self, skeletons: List[Dict]) -> List[Dict]:
        """肢体巡检：手部畸形/肢体穿插/关节超限（占位，未来接真实检测）"""
        # TODO 未来：基于真实骨骼关键点判断
        issues = []
        for sk in skeletons:
            if not sk.get("within_constraint", True):
                issues.append({
                    "clip_id": sk.get("clip_id"),
                    "type": "limb",
                    "severity": "minor",
                    "detail": "关节超限（占位检测）",
                })
        return issues

    def _inspect_logic(self, clips: List[Dict]) -> List[Dict]:
        """逻辑巡检：调 LLM 判断动作与剧本匹配度 + 道具物理常识"""
        if not clips:
            return []
        try:
            from app.core.ai_engine import AIEngine
            engine = AIEngine()
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是动作逻辑质检员。检查分镜中是否存在："
                        "1)动作与描述不匹配 2)道具空间违反物理常识 3)人物位置跳跃。"
                        "输出 JSON 数组，每项含 clip_id/type/severity/detail。无问题返回 []。"
                    )
                },
                {
                    "role": "user",
                    "content": f"分镜：\n{json.dumps(clips, ensure_ascii=False)}"
                }
            ]
            full = ""
            for chunk in engine.chat_with_fallback(messages, template=lambda: "[]"):
                full += chunk
            parsed = self._parse_json_array(full)
            return parsed if parsed else []
        except Exception:
            return []

    def _inspect_timing(self, comparisons: List[Dict]) -> List[Dict]:
        """时序巡检：镜头衔接/转场节奏"""
        issues = []
        for cmp in comparisons:
            if cmp.get("warning"):
                issues.append({
                    "from_clip": cmp.get("from_clip"),
                    "to_clip": cmp.get("to_clip"),
                    "type": "timing",
                    "severity": "minor",
                    "detail": f"转场生硬（差值{cmp.get('position_diff', 0):.2f}）",
                })
        return issues

    # ════════════════════════════════════════════════════════════════
    # L4b：分级修复
    # ════════════════════════════════════════════════════════════════
    def _grade_repair(self, context) -> StepResult:
        """L4b：按严重度分级修复（局部重绘/整段重生成/调插帧）"""
        self._report_progress(85, "L4b 分级修复...")

        issues = context.get_variable("inspection_issues", [])
        interpolation_plan = context.get_variable("interpolation_plan", [])

        repairs = []
        for issue in issues:
            severity = issue.get("severity", "minor")
            if severity == "minor":
                action = "local_redraw"  # 局部重绘
            elif severity == "severe":
                action = "regenerate_segment"  # 整段重生成
            else:
                action = "call_interpolation"  # 调插帧

            repairs.append({
                "issue": issue,
                "action": action,
                "status": "planned",  # 占位：实际修复未来接真实引擎，当前只出方案不落地
            })

        # 转场生硬的自动调插帧
        # 如实说明：这里的 "applied" 只表示"生成了调用插帧的修复计划"，
        # L3 阶段 _try_real_interpolation 已确认当前 clips 只有描述、无帧
        # 数据，从未真正执行过插帧——不代表画面已经被处理过，避免调用方
        # 把 "applied" 误读成"已修复完成"。
        for plan in interpolation_plan:
            if plan["mode"] == "lightweight":
                repairs.append({
                    "issue": {"from_clip": plan["from_clip"], "type": "transition_stiff"},
                    "action": "call_interpolation",
                    "status": "planned",
                    "note": "仅生成修复计划，未真正执行插帧（无真实帧数据）",
                })

        context.set_variable("repairs", repairs)
        return StepResult(success=True, output={
            "total_repairs": len(repairs),
            "actions": [r["action"] for r in repairs],
        })

    # ════════════════════════════════════════════════════════════════
    # 技能库联动入库
    # ════════════════════════════════════════════════════════════════
    def _archive_cases(self, context) -> StepResult:
        """故障案例入库：畸形/翻车案例存入公共技能库，供后续规避"""
        self._report_progress(92, "技能库联动入库...")

        issues = context.get_variable("inspection_issues", [])
        repairs = context.get_variable("repairs", [])

        cases = []
        for issue, repair in zip(issues, repairs):
            if issue.get("type") in ("limb", "logic"):
                cases.append({
                    "case_id": f"case_{int(time.time())}_{len(cases)}",
                    "issue_type": issue.get("type"),
                    "detail": issue.get("detail", ""),
                    "repair_action": repair.get("action"),
                    "archived_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })

        # 写入公共技能库（占位：JSON 文件；未来接真实技能库存储）
        archive_path = self._write_case_archive(cases)
        context.set_variable("archived_cases", cases)
        context.set_variable("archive_path", archive_path)

        return StepResult(success=True, output={
            "cases_archived": len(cases),
            "archive_path": archive_path,
        })

    def _write_case_archive(self, cases: List[Dict]) -> str:
        """写入案例归档文件（占位，未来接公共技能库真实存储）"""
        if not cases:
            return ""
        try:
            archive_dir = os.path.join(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                "data", "skill_cases")
            os.makedirs(archive_dir, exist_ok=True)
            archive_file = os.path.join(archive_dir, f"deformity_cases_{int(time.time())}.json")
            with open(archive_file, "w", encoding="utf-8") as f:
                json.dump(cases, f, ensure_ascii=False, indent=2)
            return archive_file
        except Exception as e:
            return f"archive_failed: {e}"

    # ════════════════════════════════════════════════════════════════
    # 合成闭环报告
    # ════════════════════════════════════════════════════════════════
    def _compose_report(self, context) -> StepResult:
        """汇总四层闭环结果，输出完整报告"""
        self._report_progress(100, "合成闭环报告...")

        report = {
            "project_type": context.get_variable("project_type", "short"),
            "summary": {
                "L1_constraints_loaded": len(context.get_variable("skeleton_constraints", {}).get("joints", {})),
                "L1_clips_normalized": len(context.get_variable("clips_normalized", [])),
                "L1_anchors_set": len(context.get_variable("frame_anchors", [])),
                "L2_skeletons_detected": len(context.get_variable("skeletons", [])),
                "L2_unsafe_transitions": len(context.get_variable("unsafe_transitions", [])),
                "L3_interpolation_count": len(context.get_variable("interpolation_plan", [])),
                "L4a_total_issues": context.get_variable("issue_count", 0),
                "L4b_total_repairs": len(context.get_variable("repairs", [])),
                "archived_cases": len(context.get_variable("archived_cases", [])),
            },
            "issues": context.get_variable("inspection_issues", []),
            "repairs": context.get_variable("repairs", []),
            "archive_path": context.get_variable("archive_path", ""),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            # 如实标注：本 Skill 是四层闭环的骨架实现（见文件头文档），
            # L2 骨骼识别/L3 插帧校验/L4b 修复目前均为占位或仅出计划，
            # 尚未接入真实的 OpenPose/SMPL 姿态识别与插帧引擎，报告中的
            # "巡检发现的问题"主要来自 LLM 文本判断，不是对画面像素的
            # 真实视觉检测。调用方展示本报告时应提示用户这一点。
            "uses_placeholder_detection": True,
        }

        context.set_output("deformity_report", report)

        summary_text = (
            f"畸形根治闭环报告（骨架版，骨骼识别/插帧修复为占位，未接入真实视觉检测引擎）\n"
            f"  项目类型: {report['project_type']}\n"
            f"  L1 前置约束: 加载 {report['summary']['L1_constraints_loaded']} 关节约束，"
            f"规范化 {report['summary']['L1_clips_normalized']} 段，锚定 {report['summary']['L1_anchors_set']} 帧\n"
            f"  L2 生成管控: 识别 {report['summary']['L2_skeletons_detected']} 骨架（占位数据），"
            f"不安全转场 {report['summary']['L2_unsafe_transitions']} 处\n"
            f"  L3 插帧补偿: 规划 {report['summary']['L3_interpolation_count']} 处插帧（仅出计划，未真正执行）\n"
            f"  L4a 三重巡检: 发现 {report['summary']['L4a_total_issues']} 个问题（主要来自 LLM 文本判断）\n"
            f"  L4b 分级修复: 规划 {report['summary']['L4b_total_repairs']} 项修复（仅出计划，未真正修复画面）\n"
            f"  入库案例: {report['summary']['archived_cases']} 条 → {report['archive_path'] or '未入库'}"
        )
        return StepResult(success=True, output={"result": summary_text, "report": report})

    # ════════════════════════════════════════════════════════════════
    # 通用工具
    # ════════════════════════════════════════════════════════════════
    @staticmethod
    def _parse_json_array(text: str) -> List[Dict]:
        """从 LLM 输出提取 JSON 数组（兼容代码块包裹）"""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
                cleaned = cleaned.strip()
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                return json.loads(cleaned[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            pass
        return []
