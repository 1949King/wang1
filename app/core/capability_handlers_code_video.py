# -*- coding: utf-8 -*-
"""「代码 × 扩散」混合视频能力处理器 —— V4.44 契约刀 · 2026-10-19

为什么独立成文件：`capability_handlers.py` 已 1,985/2,000 行（体积守卫上限只剩 15 行），
按既有惯例（`capability_handlers_media.py` / `capability_handlers_recipe.py`）拆出。

V4.44 只落地 `code_video_plan`（计划态）：
    分镜表 → CodeVideoSpec 草案 → compile_spec 契约编译 → 交调用方确认。
**不渲染、不广播、不碰画布** —— 渲染引擎在 V4.45（render_host），
画布接线在 V4.46；本刀只把「契约能立住」这件事做实。

诚实失败语义（与 spec.py 铁律一致）：
    * 没给分镜表 ⇒ success=False，不猜
    * 分镜表转出的草案过不了 compile_spec ⇒ success=False，
      **绝不把烂草案包装成「计划态」交付**
    * from_storyboard 的非致命 errors（如个别镜头缺 duration 被跳过）
      原样进 output.warnings —— 报告，不静默
"""
from typing import Any, Dict, List

try:
    from app.core.capability_dispatcher import CapabilityRequest, CapabilityResult
    from app.core.code_video.spec import (
        CodeVideoSpec,
        compile_spec,
        from_storyboard,
        validate_spec,
    )
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.capability_dispatcher import CapabilityRequest, CapabilityResult  # type: ignore
    from core.code_video.spec import (  # type: ignore
        CodeVideoSpec,
        compile_spec,
        from_storyboard,
        validate_spec,
    )


def _opt_int(p: Dict[str, Any], key: str, default: int) -> int:
    """宽松取整型参数：非数字/缺失 ⇒ 保持默认；**不做范围钳制**
    （越界由 compile_spec 的 limits 校验诚实报错，不在这里偷偷改）。"""
    raw = p.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


class CodeVideoCapabilityHandlers:
    """Agent 侧混合视频入口：分镜表 → 契约草案（计划态）。"""

    def code_video_plan(self, req: CapabilityRequest) -> CapabilityResult:
        p: Dict[str, Any] = req.params or {}
        storyboard = p.get("storyboard")

        # 没给分镜表 = 调用方没说清要排什么片 ⇒ 诚实失败，不猜
        if storyboard is None:
            return CapabilityResult(
                req.request_id,
                False,
                error="需要提供 storyboard（分镜表数组，元素含 shot/description/duration）",
            )
        if not isinstance(storyboard, list):
            return CapabilityResult(
                req.request_id, False, error=f"storyboard 必须是数组，收到 {type(storyboard).__name__}"
            )

        spec, draft_errors = from_storyboard(
            storyboard,
            width=_opt_int(p, "width", 1080),
            height=_opt_int(p, "height", 1920),
            fps=_opt_int(p, "fps", 30),
            spec_id=str(p.get("spec_id") or ""),
        )
        if spec is None:
            return CapabilityResult(
                req.request_id,
                False,
                error="分镜表无法转成 spec 草案：" + "; ".join(draft_errors or ["未知原因"]),
            )

        # 草案必须过契约编译才算「计划态」——过不了就诚实失败，
        # 不把编译不过的 spec 交到 V4.45 渲染面才炸
        compiled, compile_errors = compile_spec(spec)
        if compiled is None:
            return CapabilityResult(
                req.request_id,
                False,
                error="spec 草案未通过契约编译：" + "; ".join(compile_errors),
            )

        warnings: List[str] = list(draft_errors)
        return CapabilityResult(
            req.request_id,
            True,
            output={
                "spec": spec.to_dict(),
                "compiled": compiled,
                "warnings": warnings,
                "clip_count": spec.total_clips(),
                "note": "计划态：spec 草案已通过契约编译，确认后由 code_video_render（V4.45）落地渲染",
            },
            error=None,
        )

    def code_video_render(self, req: CapabilityRequest) -> CapabilityResult:
        """渲染入口：spec 或 storyboard 二选一 → 契约编译 → render_host 出片。

        诚实失败：没输入 / spec 不合法 / 编译不过 / 渲染任一步失败 ⇒ success=False，
        错误带 stage（不交付半成品，也不把渲染失败包装成「计划态」）。
        """
        p: Dict[str, Any] = req.params or {}
        spec_data = p.get("spec")
        storyboard = p.get("storyboard")
        warnings: List[str] = []

        if spec_data is None and storyboard is None:
            return CapabilityResult(
                req.request_id, False,
                error="需要 spec（CodeVideoSpec JSON）或 storyboard（分镜表数组）二选一",
            )

        if spec_data is not None:
            if not isinstance(spec_data, dict):
                return CapabilityResult(
                    req.request_id, False,
                    error=f"spec 必须是对象，收到 {type(spec_data).__name__}",
                )
            struct_errors = validate_spec(spec_data)
            if struct_errors:
                return CapabilityResult(
                    req.request_id, False,
                    error="spec 结构校验失败：" + "; ".join(struct_errors),
                )
            try:
                spec = CodeVideoSpec.from_dict(spec_data)
            except (TypeError, ValueError, KeyError) as exc:
                return CapabilityResult(
                    req.request_id, False, error=f"spec 无法反序列化：{exc}"
                )
        else:
            if not isinstance(storyboard, list):
                return CapabilityResult(
                    req.request_id, False,
                    error=f"storyboard 必须是数组，收到 {type(storyboard).__name__}",
                )
            spec, draft_errors = from_storyboard(
                storyboard,
                width=_opt_int(p, "width", 1080),
                height=_opt_int(p, "height", 1920),
                fps=_opt_int(p, "fps", 30),
                spec_id=str(p.get("spec_id") or ""),
            )
            if spec is None:
                return CapabilityResult(
                    req.request_id, False,
                    error="分镜表无法转成 spec 草案：" + "; ".join(draft_errors or ["未知原因"]),
                )
            warnings.extend(draft_errors)

        compiled, compile_errors = compile_spec(spec)
        if compiled is None:
            return CapabilityResult(
                req.request_id, False,
                error="spec 未通过契约编译：" + "; ".join(compile_errors),
            )

        try:
            from app.core.code_video.render_host import render
        except ImportError:  # 兼容 `core.*` 旧导入路径
            from core.code_video.render_host import render  # type: ignore

        result = render(
            compiled=compiled,
            output_name=str(p.get("output_name") or ""),
            qc=bool(p.get("qc", True)),
        )
        if not result.get("ok"):
            return CapabilityResult(
                req.request_id, False,
                error=f"{result.get('stage') or 'render'}: {result.get('error') or '未知错误'}",
            )
        output = dict(result)
        output["warnings"] = list(result.get("warnings") or []) + warnings
        output["note"] = "渲染完成：产物已落画布 inbox；这是本地产物，未经人工审核"
        return CapabilityResult(req.request_id, True, output=output, error=None)


def register_code_video_handlers(dispatcher, category) -> None:
    """注册代码×扩散能力（注册细节留本模块）。"""
    h = CodeVideoCapabilityHandlers()
    dispatcher.register("pipeline.code_video_plan", category, h.code_video_plan,
                        "分镜表→CodeVideoSpec 草案（契约编译；计划态，不渲染）")
    dispatcher.register("pipeline.code_video_render", category, h.code_video_render,
                        "CodeVideoSpec → Chromium 逐帧 + ffmpeg 编码（落 inbox；诚实失败）")
