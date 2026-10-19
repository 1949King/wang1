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
    from app.core.code_video.spec import compile_spec, from_storyboard
except ImportError:  # 兼容 `core.*` 旧导入路径
    from core.capability_dispatcher import CapabilityRequest, CapabilityResult  # type: ignore
    from core.code_video.spec import compile_spec, from_storyboard  # type: ignore


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
