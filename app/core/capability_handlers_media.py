"""
媒体处理类能力 handlers —— LibTV 对标补强（2026-10-12）
======================================================
背景：对比 LibTV 功能清单时发现 7 个引擎**早已就绪、只差 Agent 接线**
（后端 + /host/* 端点 / Skill 步骤 + 测试都在，但 Agent 能力目录里没有）。

刀1（5 项，复用既有 /host/* 端点背后的同一实现）：
  - AI 超分（canvas_enhance 的 sharpen 意图）
  - AI 抠像（canvas_enhance 的 cutout 意图）
  - 深度视频提取（video_depth）
  - 逐帧拉片 L1（reference_breakdown）
  - 片段重拍（segment_retake）

刀2（2 项，从 DirectorSkill 抽出的单一真源引擎）：
  - 文本生剧本（script_writer，DirectorSkill 步骤1 同源）
  - 导演结果落时间线（director_timeline，DirectorSkill 步骤5.5 同源）

纪律：
  - 全部复用既有实现，不重写业务逻辑；DirectorSkill 改为薄委托（零行为变化）。
  - 权重/LLM 缺失时**诚实失败或如实标注降级**，绝不静默冒充
    （深度红线见 app/core/video_depth.py；剧本模板降级 fallback=True）。

独立成模块的原因：capability_handlers.py 已 1874 行，再塞 handler
会顶破 check_file_size 的 2000 行守卫 ⇒ 按守卫指引「拆模块」。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from app.core.capability_dispatcher import (
    CapabilityRequest, CapabilityResult,
)

logger = logging.getLogger(__name__)


class MediaCapabilityHandlers:
    """LibTV 对标补强：超分 / 抠像 / 深度 / 拉片 / 片段重拍。"""

    # ── 公共底座：canvas_enhance.apply_intents 的单意图封装（超分/抠像共用）──
    @staticmethod
    def _apply_enhance(req: CapabilityRequest, intent: str) -> CapabilityResult:
        try:
            from app.core import canvas_enhance as enhance
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"增强引擎不可用: {e}")
        p = req.params or {}
        image = str(p.get("image") or p.get("image_data_url") or "")
        if not image:
            return CapabilityResult(req.request_id, False, error="缺少 image（原图 data URL）")
        try:
            res = enhance.apply_intents(
                image,
                [intent],
                quality=str(p.get("quality") or "standard"),
                params=p.get("params") if isinstance(p.get("params"), dict) else {},
            )
        except Exception as e:
            logger.debug("[media] 意图 %s 执行异常", intent, exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"意图 {intent} 执行失败: {e}")
        ok = bool(res.get("ok")) and bool(res.get("changed"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else MediaCapabilityHandlers._skip_reason(res, intent),
        )

    @staticmethod
    def _skip_reason(res: Dict[str, Any], intent: str) -> str:
        """从诚实报告里提取「为什么没生效」（skipped 优先，兜底 message）。"""
        for s in res.get("skipped") or []:
            if s.get("intent") == intent:
                return str(s.get("reason") or "未生效")
        return str(res.get("message") or "未生效（原图返回）")

    def ai_upscale(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 超分（意图 sharpen）：fast/standard 走 OpenCV ESPCN **不下载**，
        high 档 RealESRGAN 首次需下载模型。复用 /host/canvas-enhance 同一实现。"""
        return self._apply_enhance(req, "sharpen")

    def ai_matte(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 抠像（意图 cutout）：主体分离 → 纯色底/透明底。
        如实回报实际使用的引擎，走降级路径时 degraded=True 必标注。"""
        return self._apply_enhance(req, "cutout")

    def ai_face_restore(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 修脸（意图 face）：检测人脸区域做增强，无人脸时诚实「原样返回」。
        复用 /host/canvas-enhance 同一实现（canvas_enhance.apply_intents）。"""
        return self._apply_enhance(req, "face")

    def ai_style(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 风格迁移（意图 style）：按画风重绘（style/strength 可传，缺省 cyberpunk/0.8）。
        复用 /host/canvas-enhance 同一实现；模型未就绪时如实标 degraded（CPU 回退）。"""
        return self._apply_enhance(req, "style")

    def video_depth(self, req: CapabilityRequest) -> CapabilityResult:
        """深度视频提取：复用 /host/video-depth 的 video_depth.extract_depth_video。

        ⚠️ 红线：深度必须来自真模型；模型缺失时诚实失败（返回 reason + 下载指引），
        **绝不用灰度/边缘冒充深度**。
        params：video_path / out_path(可选) / max_side(默认384) / limit_frames(0=全片)。
        """
        try:
            from app.core import video_depth as vd
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"深度模块不可用: {e}")
        p = req.params or {}
        src = str(p.get("video_path") or "")
        if not src:
            return CapabilityResult(req.request_id, False, error="缺少 video_path")
        dst = str(p.get("out_path") or "")
        if not dst:
            base = os.path.splitext(os.path.basename(src))[0]
            dst = os.path.join(".workbuddy", "tmp", f"{base}_depth.mp4")
        try:
            res = vd.extract_depth_video(
                src, dst,
                max_side=int(p.get("max_side") or 384),
                limit_frames=int(p.get("limit_frames") or 0),
            )
        except Exception as e:
            logger.debug("[media] 深度提取异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"深度提取失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (
                res.get("message") or res.get("reason") or "深度提取失败（模型缺失？）"),
        )

    def reference_breakdown(self, req: CapabilityRequest) -> CapabilityResult:
        """逐帧拉片 L1：复用 /host/reference-breakdown 的 build_shot_table。
        零权重（ffmpeg+OpenCV 启发式），参考片 → 结构化镜头表 + 关键帧落盘。
        params：video_path / out_dir(可选) / threshold(默认0.30)。
        """
        try:
            from app.core import reference_breakdown as rb
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"拉片模块不可用: {e}")
        p = req.params or {}
        video = str(p.get("video_path") or "")
        if not video:
            return CapabilityResult(req.request_id, False, error="缺少 video_path")
        try:
            res = rb.build_shot_table(
                video,
                out_dir=str(p.get("out_dir") or ".workbuddy/tmp/breakdown"),
                threshold=float(p.get("threshold") or 0.30),
            )
        except Exception as e:
            logger.debug("[media] 拉片异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"拉片失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "拉片失败"),
        )

    def reference_breakdown_l2(self, req: CapabilityRequest) -> CapabilityResult:
        """逐帧拉片 **L2 运动级**：复用 /host/reference-breakdown-l2 的 build_shot_table(with_depth=True)。

        在 L1 基础上取每段首/尾帧深度图推断运镜（推/拉/摇，中文词），
        置信度低于门槛的推断只留详情不进表格（camera_move_trusted=False）。
        可选开景别/描述 enrich：``use_vision=True`` 时调**云端视觉模型**
        （素材出域，需调用方显式开启；失败如实留空并标注，不编造）。
        params：video_path / out_dir(可选) / threshold(默认0.30) /
        use_vision(默认False) / vision_model(可选)。
        """
        try:
            from app.core import reference_breakdown as rb
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"拉片模块不可用: {e}")
        p = req.params or {}
        video = str(p.get("video_path") or "")
        if not video:
            return CapabilityResult(req.request_id, False, error="缺少 video_path")
        try:
            res = rb.build_shot_table(
                video,
                out_dir=str(p.get("out_dir") or ".workbuddy/tmp/breakdown_l2"),
                threshold=float(p.get("threshold") or 0.30),
                with_depth=True,
                use_vision=bool(p.get("use_vision")),
                vision_model=str(p.get("vision_model") or ""),
            )
        except Exception as e:
            logger.debug("[media] 拉片 L2 异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"拉片 L2 失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "拉片 L2 失败"),
        )

    def video_edit(self, req: CapabilityRequest) -> CapabilityResult:
        """指令式视频编辑：复用 /host/video-edit 的 edit_video（Seedance/Kling 双渠道）。

        与 segment_retake 的边界：**重拍=重新生成，编辑=改原片**。
        失败保原镜（original_kept=True，绝不产半成品冒充）；
        Kling 渠道需显式公网 video_url（素材出域要知情）；
        SHIGUANG_NO_EGRESS=1 时整个请求诚实拒绝。
        params：clip_path / instruction / channel(auto|seedance|kling 可选) /
        video_url(Kling 必需) / model(可选) / out_dir(可选)。
        """
        try:
            from app.core.ai.video_edit_client import edit_video
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"编辑模块不可用: {e}")
        p = req.params or {}
        instruction = str(p.get("instruction") or "")
        if not instruction:
            return CapabilityResult(req.request_id, False, error="缺少编辑指令（instruction）")
        try:
            res = edit_video(
                str(p.get("clip_path") or ""),
                instruction,
                channel=str(p.get("channel") or "auto"),
                video_url=str(p.get("video_url") or ""),
                model=str(p.get("model") or ""),
                out_dir=str(p.get("out_dir") or ""),
            )
        except Exception as e:
            logger.debug("[media] 视频编辑异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"视频编辑失败: {e}")
        ok = bool(res.get("ok"))
        # §6.9-P2 时长匹配约束：编辑产物与原片时长比对 —— 不符如实标记，不硬剪
        if ok:
            try:
                from app.core.segment_retake import probe_duration
                d_old = float(probe_duration(str(p.get("clip_path") or "")) or 0.0)
                d_new = float(probe_duration(str(res.get("clip_path") or "")) or 0.0)
                if d_old > 0 and d_new > 0:
                    res["original_duration"] = round(d_old, 3)
                    res["edited_duration"] = round(d_new, 3)
                    if abs(d_new - d_old) > 0.05:
                        res["duration_mismatch"] = True
                        res["duration_note"] = (
                            f"编辑产物 {d_new:.2f}s ≠ 原片 {d_old:.2f}s；"
                            "未硬剪，请确认是否调整时间线")
                else:
                    res["duration_mismatch"] = None
                    res["duration_note"] = "未能探测编辑产物时长，时长一致性未经校验"
            except Exception as e:
                logger.debug("[media] 时长一致性校验忽略: %s", e)
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "视频编辑失败（原片段已保留）"),
        )

    def segment_retake(self, req: CapabilityRequest) -> CapabilityResult:
        """片段重拍：复用 /host/segment-retake 的 splice_retake。
        只替换视频指定时间段（保音轨/时长对齐），接缝风险如实报告。
        params：original / replacement / out_path / start / end / cuts(可选) /
        conform(可选，默认 True；False=不硬剪，时长不符如实标记 mismatch)。
        """
        try:
            from app.core import segment_retake as sr
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"重拍模块不可用: {e}")
        p = req.params or {}
        original = str(p.get("original") or "")
        replacement = str(p.get("replacement") or "")
        out_path = str(p.get("out_path") or "")
        start = float(p.get("start") or 0.0)
        end = float(p.get("end") or 0.0)
        if not (original and replacement and out_path and end > start):
            return CapabilityResult(
                req.request_id, False,
                error="需要 original/replacement/out_path/start<end")
        try:
            res = sr.splice_retake(
                original, replacement, out_path,
                start=start, end=end,
                cuts=p.get("cuts") or [],
                # §6.9-P2 时长匹配约束：默认仍对齐原段时长；显式 conform=False 不硬剪
                conform=bool(p.get("conform", True)),
            )
        except Exception as e:
            logger.debug("[media] 片段重拍异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"片段重拍失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "片段重拍失败"),
        )

    # ── 刀2a：文本生剧本（DirectorSkill 步骤1 同源，LibTV「剧本原创」对标）──
    def script_write(self, req: CapabilityRequest) -> CapabilityResult:
        """主题/梗概 → LLM 完整剧本（script_writer.write_script 单一真源）。
        三级降级：云 → Ollama → 模板；模板降级 fallback=True 如实标注。
        params：topic / duration_seconds(默认30) / scene_count(可选) / style(可选)。
        """
        try:
            from app.core.ai.script_writer import write_script
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"剧本引擎不可用: {e}")
        p = req.params or {}
        topic = str(p.get("topic") or p.get("subject") or "").strip()
        if not topic:
            return CapabilityResult(req.request_id, False, error="缺少 topic（主题/梗概）")
        try:
            res = write_script(
                topic,
                duration_seconds=int(p.get("duration_seconds") or 30),
                scene_count=int(p["scene_count"]) if p.get("scene_count") else None,
                style=str(p.get("style") or ""),
            )
        except Exception as e:
            logger.debug("[media] 文本生剧本异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"剧本生成失败: {e}")
        ok = bool(res.get("ok")) and bool(str(res.get("script") or "").strip())
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else "剧本生成失败（空剧本）",
        )

    # ── 刀2b：导演结果落时间线（DirectorSkill 步骤5.5 同源）──
    def director_apply_timeline(self, req: CapabilityRequest) -> CapabilityResult:
        """分镜表 + 素材目录 → 按镜序入轨（director_timeline 单一真源）。

        与画布回流（canvas_bridge.push_to_timeline）同一条 EventBus
        MATERIAL_TO_TIMELINE 总线；剪辑模块未打开时不发事件、如实报告。
        params：source_dir / storyboard（列表；缺省时可用 script 启发式拆解补齐）。
        """
        try:
            from app.core.ai.director_timeline import apply_storyboard_to_timeline
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"落轨引擎不可用: {e}")
        p = req.params or {}
        source_dir = str(p.get("source_dir") or "").strip()
        if not source_dir:
            return CapabilityResult(req.request_id, False, error="缺少 source_dir（素材目录）")
        storyboard = p.get("storyboard")
        if not (isinstance(storyboard, list) and storyboard):
            # 没给分镜表但给了剧本 → 复用 director_breakdown 同一实现启发式拆解
            script = str(p.get("script") or "").strip()
            if not script:
                return CapabilityResult(
                    req.request_id, False,
                    error="缺少 storyboard（或给 script 由系统拆分镜）")
            try:
                from app.core.canvas_aigc import storyboard_breakdown
                breakdown = storyboard_breakdown(script, use_llm=False)
                storyboard = breakdown.get("shots") or []
            except Exception as e:
                logger.debug("[media] 拆分镜异常", exc_info=True)
                return CapabilityResult(req.request_id, False, error=f"拆分镜失败: {e}")
            if not storyboard:
                return CapabilityResult(req.request_id, False,
                                        error="剧本拆不出分镜（无法落轨）")
        try:
            res = apply_storyboard_to_timeline(
                source_dir, storyboard, source_tag="agent.director_apply_timeline")
        except Exception as e:
            logger.debug("[media] 落轨异常", exc_info=True)
            return CapabilityResult(req.request_id, False, error=f"落时间线失败: {e}")
        ok = bool(res.get("applied"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("reason") or "未落轨"),
        )


# ── media 族注册（2026-10-29 从 capability_handlers.py 迁入）────────────
# 为什么迁：capability_handlers.py 顶到 2005 行破 check_file_size 2000 行守卫，
# 按「只减不增」纪律本应拆文件；media 族注册语句内聚在本模块（handler 也在
# 本模块）⇒ 一并迁入，原处只留一行调用。能力目录真源仍是
# agent_capability_catalog.CAPABILITY_ROWS（注册语句只负责「handler 绑定」）。
def register_media_capabilities(dispatcher, media_handlers: "MediaCapabilityHandlers") -> None:
    """把 media 族 canvas 能力绑到 dispatcher（幂等语义由 dispatcher.register 保证）。"""
    from app.core.capability_dispatcher import CapabilityCategory

    dispatcher.register("canvas.ai_upscale", CapabilityCategory.CANVAS,
                        media_handlers.ai_upscale, "AI 超分放大（ESPCN/RealESRGAN，如实回报引擎）")
    dispatcher.register("canvas.ai_matte", CapabilityCategory.CANVAS,
                        media_handlers.ai_matte, "AI 抠像换背景（降级必标注）")
    # 刀 B 配套（2026-10-29）：face_restore / style_transfer 两个 library-only 引擎接画布入口
    dispatcher.register("canvas.ai_face_restore", CapabilityCategory.CANVAS,
                        media_handlers.ai_face_restore, "AI 修复人脸（无人脸原样返回，如实回报）")
    dispatcher.register("canvas.ai_style", CapabilityCategory.CANVAS,
                        media_handlers.ai_style, "AI 风格迁移（style/strength 可调，降级必标注）")
    dispatcher.register("canvas.video_depth", CapabilityCategory.CANVAS,
                        media_handlers.video_depth, "深度视频提取（模型缺失时诚实失败）")
    dispatcher.register("canvas.reference_breakdown", CapabilityCategory.CANVAS,
                        media_handlers.reference_breakdown, "逐帧拉片 L1（参考片→结构化镜头表）")
    # 拉片 L2（2026-10-14 补缺）：深度运镜推断 + 可选云端视觉景别 enrich（素材出域显式开启）
    dispatcher.register("canvas.reference_breakdown_l2", CapabilityCategory.CANVAS,
                        media_handlers.reference_breakdown_l2,
                        "逐帧拉片 L2（运镜深度推断+景别视觉 enrich，置信度门槛如实标注）")
    # 指令式视频编辑（2026-10-15）：Seedance Base64 / Kling 公网 URL 双渠道，失败保原镜
    dispatcher.register("canvas.video_edit", CapabilityCategory.CANVAS,
                        media_handlers.video_edit,
                        "指令式视频编辑（改原片不重生成；失败保原镜，诚实标注）")
    dispatcher.register("canvas.segment_retake", CapabilityCategory.CANVAS,
                        media_handlers.segment_retake, "片段重拍（保音轨/时长对齐）")
    # LibTV 对标补强 刀2（2026-10-12）：文本生剧本 / 导演结果落时间线
    # （DirectorSkill 同源薄委托 → script_writer / director_timeline 单一真源）
    dispatcher.register("pipeline.script_write", CapabilityCategory.PIPELINE,
                        media_handlers.script_write, "文本生剧本（主题→LLM 剧本，降级如实标注）")
    dispatcher.register("pipeline.director_apply_timeline", CapabilityCategory.PIPELINE,
                        media_handlers.director_apply_timeline,
                        "分镜表+素材目录按镜序入轨（DirectorSkill 步骤5.5 同源）")
