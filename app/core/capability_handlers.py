"""
能力 handlers —— 三大模块 + 多任务的具体实现
======================================================
所有 handler 都通过 lazy 引用既有单例，不重新实现业务逻辑。

handler 分类：
  - EditorCapabilityHandlers: 剪辑模块（split/filter/transition/timeline_context/ripple_delete_range/suggest_cleanup）
  - ModelCapabilityHandlers: 模型模块（chat/chat_with_fallback/list_models）
  - ExtensionCapabilityHandlers: 拓展模块（run_extension/run_skill/list_tools）
  - WorkflowCapabilityHandlers: 多任务调度（submit_batch）
"""
from __future__ import annotations
import logging
from typing import Any, Callable, Dict, List, Optional

from app.core.capability_dispatcher import (
    CapabilityDispatcher, CapabilityRequest, CapabilityResult, CapabilityCategory,
)

logger = logging.getLogger(__name__)


# ────────────── 画布能力 handlers ──────────────
class CanvasCapabilityHandlers:
    """AI 画布：打开模块 / 同步模型池（走 EventBus + bridge 侧刷新）。"""

    def open(self, req: CapabilityRequest) -> CapabilityResult:
        try:
            from app.modules.lego.core import EventBus, EventType
        except ImportError:
            from modules.lego.core import EventBus, EventType  # type: ignore
        bus = EventBus.get_instance()
        bus.emit(
            EventType.MODULE_ACTIVATED,
            {"target": "characters", "hint": "Agent 请求打开画布", "source": "agent"},
            source="agent",
        )
        return CapabilityResult(req.request_id, True, output={"module": "characters"}, error=None)

    def sync_models(self, req: CapabilityRequest) -> CapabilityResult:
        try:
            from app.core.canvas_bridge import build_host_ai_config_patch
        except ImportError:
            from core.canvas_bridge import build_host_ai_config_patch  # type: ignore
        patch = build_host_ai_config_patch()
        try:
            from app.modules.lego.core import EventBus, EventType
        except ImportError:
            from modules.lego.core import EventBus, EventType  # type: ignore
        bus = EventBus.get_instance()
        bus.emit(
            EventType.MODULE_ACTIVATED,
            {
                "target": "characters",
                "hint": "Agent 请求同步模型池",
                "source": "agent",
                "sync_models": True,
            },
            source="agent",
        )
        warns = patch.get("warnings") or []
        msg = (
            f"已请求同步：渠道 {len(patch.get('channels') or [])}，"
            f"生图={'有' if patch.get('has_image_models') else '无'}，"
            f"激活 {patch.get('active_provider_label') or '无'}"
        )
        if warns:
            msg += "；" + str(warns[0])
        return CapabilityResult(
            req.request_id,
            True,
            output={
                "channels": len(patch.get("channels") or []),
                "has_image_models": patch.get("has_image_models"),
                "warnings": warns,
                "message": msg,
            },
            error=None,
        )

    def list_actions(self, req: CapabilityRequest) -> CapabilityResult:
        """输出统一画布动作清单（单一事实来源，供前端 AgentPanel 消费）。"""
        from app.core.agent_action_registry import build_canvas_actions_list
        return CapabilityResult(
            req.request_id,
            True,
            output={"actions": build_canvas_actions_list()},
            error=None,
        )

    def node_action(self, req: CapabilityRequest) -> CapabilityResult:
        """画布节点级操作（canvas_tools 后端化，2026-09-15）。

        节点状态存在前端 Zustand store，后端无法直接改；唯一通道是
        push_to_canvas("task.create") → 前端 executeRemoteTask → POST /host/agent/reply。
        capability_id 形如 canvas.add_node，反查回前端 action（addNode）后推送并同步等回执。
        策略/预算/记忆/脑神经元已由 dispatcher 统一处理，这里只做「桥接 + 等待回执」，
        不重复 decide / begin_tool_call（避免双重计费）。
        """
        from app.core.agent_action_registry import canvas_capability_to_action

        action_name = canvas_capability_to_action().get(req.capability_id or "")
        if not action_name:
            return CapabilityResult(
                req.request_id, False, error=f"未知画布节点能力: {req.capability_id}"
            )
        try:
            from app.core.project_agent_host import push_to_canvas, wait_for_canvas_reply
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"画布桥接不可用: {e}")

        evt = push_to_canvas(
            "task.create",
            {"action": action_name, "params": req.params or {}},
            ack_required=True,
        )
        reply = wait_for_canvas_reply(str(evt.get("id") or ""), timeout=20.0)
        payload = (reply or {}).get("payload") if isinstance(reply, dict) else None
        ok = bool(payload and payload.get("ok")) if payload is not None else False
        if reply is None:
            err = "画布未回执（超时）"
        elif not ok:
            err = str((payload or {}).get("error") or "执行失败")
        else:
            err = None
        return CapabilityResult(req.request_id, ok, output=payload, error=err)

    # ── 画布生成能力（Agent 亲手驱动后端 /host/* 生成链路，2026-09-15）──
    # 复用 /host/generate-image / generate-video / comfyui/run / video-concat /
    # still-video 背后的同一批纯 Python 函数，让 AgentLoop（走 dispatcher）也能
    # 直接驱动，而不再只依赖前端 canvas_tools 的 runGenerate 触发。

    def generate_image(self, req: CapabilityRequest) -> CapabilityResult:
        """画布生图：复用 /host/generate-image 的 generate_image_openai_compatible。"""
        try:
            from app.core.canvas_aigc import generate_image_openai_compatible
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"生图依赖不可用: {e}")
        p = req.params or {}
        # seed 贯通（2026-09-27 深度求索 DEFECT B）：Agent 侧此前不吃 seed，
        # 导致对话驱动生图不可复现。此处透传，与画布 /host/generate-image 对齐。
        _seed_raw = p.get("seed")
        try:
            seed_arg = int(_seed_raw) if _seed_raw not in (None, "") else None
        except Exception:
            seed_arg = None
        try:
            res = generate_image_openai_compatible(
                prompt=str(p.get("prompt") or ""),
                model=str(p.get("model") or ""),
                size=str(p.get("size") or ""),
                channel_id=str(p.get("channel_id") or ""),
                reference_image=str(p.get("reference_image") or ""),
                strength=float(p.get("strength") or 0.65),
                quality=str(p.get("quality") or "standard"),
                seed=seed_arg,
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"生图失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or res.get("error") or "生图失败"),
        )

    def generate_video(self, req: CapabilityRequest) -> CapabilityResult:
        """画布生视频：复用 /host/generate-video 的 generate_video_via_host。"""
        try:
            from app.core.canvas_aigc import generate_video_via_host
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"生视频依赖不可用: {e}")
        p = req.params or {}
        try:
            res = generate_video_via_host(
                prompt=str(p.get("prompt") or ""),
                model=str(p.get("model") or ""),
                channel_id=str(p.get("channel_id") or ""),
                duration=float(p.get("duration") or 5.0),
                size=str(p.get("size") or ""),
                reference_image=str(p.get("reference_image") or ""),
                reference_video=str(p.get("reference_video") or p.get("referenceVideo") or ""),
                first_frame=str(p.get("first_frame") or p.get("firstFrame") or ""),
                last_frame=str(p.get("last_frame") or p.get("lastFrame") or ""),
                quality=str(p.get("quality") or "standard"),
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"生视频失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or res.get("error") or "生视频失败"),
        )

    def local_generate_image(self, req: CapabilityRequest) -> CapabilityResult:
        """本地生图（刀 A1）：分派同 /host/local-image-generate（R9 降级可见）。
        params: model_id / prompt / negative_prompt / image_path / width / height /
        seed / steps / cfg / quality / preset / engine。
        """
        try:
            from app.core.ai.execution_decider import resolve_local_image_engine
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"本地生图依赖不可用: {e}")
        p = req.params or {}
        sel = resolve_local_image_engine(prefer=str(p.get("engine") or ""))
        if not sel.get("ok"):
            return CapabilityResult(
                req.request_id, False,
                output={"reasons": sel.get("reasons")},
                error=sel.get("message") or "本地图像引擎不可用",
            )
        # P0b（2026-10-10）：seed 归一化 —— 与云路径同语义（draw_ledger.normalize_seed）。
        # 本地引擎必然收到 seed（不存在"渠道没收"问题）⇒ seed_sent 恒 True；
        # 缺省/非法给密码学随机，保证每次抽卡可复现可入账。
        from app.core.ai.draw_ledger import normalize_seed

        seed_used, _seed_explicit = normalize_seed(p.get("seed"))
        model_id = str(p.get("model_id") or "sd15-t2i")
        from app.core.ai import local_image_plan as LP

        _prec = str(p.get("precision") or "").strip()
        if _prec and hasattr(sel["backend"], "request_precision"):
            sel["backend"].request_precision(_prec)

        kw = LP.generate_kwargs(
            backend=sel["backend"], model_id=model_id,
            quality=str(p.get("quality") or ""), preset=str(p.get("preset") or ""),
            prompt=str(p.get("prompt") or ""), negative_prompt=str(p.get("negative_prompt") or ""),
            image_path=str(p.get("image_path") or ""), width=int(p.get("width") or 0),
            height=int(p.get("height") or 0), seed=seed_used,
            steps=int(p.get("steps") or 0), cfg=float(p.get("cfg") or 0.0))
        try:
            res = sel["backend"].generate(model_id, **kw)
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"本地生图失败: {e}")
        res["engine"] = sel["engine"]
        res["engine_is_fallback"] = sel.get("is_fallback", False)
        res["preset"] = kw.get("preset", "")
        ok = bool(res.get("ok"))
        if ok:
            # P0b：本地生图收尾入闭环（代理分 + draw_book 账本 + 推荐回传）。
            # 接线层内部吞异常，入账失败绝不影响生成结果。
            from app.core.ai.draw_ledger import feed_draw_ledger_local

            feed_draw_ledger_local(
                res, prompt=str(p.get("prompt") or ""), model_id=model_id,
                engine=sel["engine"], seed=seed_used,
                elapsed_ms=float(res.get("seconds_elapsed") or 0) * 1000.0)
            res["seed"] = seed_used        # P0a 同款回显：本地生成必可复现
            res["seed_sent"] = True
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "本地生图失败"),
        )

    def best_of_draw(self, req: CapabilityRequest) -> CapabilityResult:
        """抽卡选优（刀 A2，2026-10-05）：一次生成 n 张 → 代理分选最优。

        编排在 `ai/draw_orchestrator.py`（纯调用，零 HTTP）；n 张在各自生成收尾
        **已自动入账**（draw_ledger），此处**绝不重复记账**。
        params：prompt / n（≤6）/ model / size / channel_id / reference_image /
        strength / quality / aspect / base_seed（给了即 base_seed+i，可复现）。
        """
        try:
            from app.core.ai.draw_orchestrator import best_of_n
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"选优依赖不可用: {e}")
        p = req.params or {}
        try:
            res = best_of_n(
                prompt=str(p.get("prompt") or ""),
                n=p.get("n", 4),
                model=str(p.get("model") or ""),
                size=str(p.get("size") or ""),
                channel_id=str(p.get("channel_id") or ""),
                reference_image=str(p.get("reference_image") or ""),
                strength=float(p.get("strength") or 0.65),
                quality=str(p.get("quality") or "standard"),
                aspect=str(p.get("aspect") or ""),
                base_seed=p.get("base_seed"),
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"抽卡选优失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "抽卡选优失败"),
        )

    def repair_image(self, req: CapabilityRequest) -> CapabilityResult:
        """局部重绘（刀 A2，2026-10-05）：复用 `/host/repair-image` 背后的同一函数。

        与 `canvas.generate_image` 的区别：**不重抽整张**，只重画坏区（坏区外逐字节保留）。
        无坏区时不发任何请求（不烧钱）。会花一次额度 ⇒ media_write + paid。
        params：image（data URL）/ prompt / model / channel_id / size。
        """
        try:
            from app.core.ai.inpaint_retry import repair_image as _repair
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"局部重绘依赖不可用: {e}")
        p = req.params or {}
        image = str(p.get("image") or p.get("image_data_url") or "")
        if not image:
            return CapabilityResult(req.request_id, False, error="缺少 image（原图 data URL）")
        try:
            res = _repair(
                image,
                prompt=str(p.get("prompt") or ""),
                model=str(p.get("model") or ""),
                channel_id=str(p.get("channel_id") or ""),
                size=str(p.get("size") or "768x1344"),
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"局部重绘失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "局部重绘失败"),
        )

    def comfyui_run(self, req: CapabilityRequest) -> CapabilityResult:
        """运行 ComfyUI 工作流：复用 /host/comfyui/run 的 comfy_provider 入口。"""
        import json as _json

        p = req.params or {}
        wf = p.get("workflow_json") or p.get("workflow")
        if isinstance(wf, str):
            try:
                wf = _json.loads(wf)
            except Exception:
                return CapabilityResult(req.request_id, False, error="workflow_json 不是合法 JSON")
        if not isinstance(wf, dict):
            return CapabilityResult(req.request_id, False, error="缺少 workflow_json（对象或 JSON 字符串）")
        dry_run = bool(p.get("dry_run", False))
        try:
            from app.core.ai.comfy_provider import comfy_provider
            res = comfy_provider.run_workflow_from_json(wf, dry_run=dry_run)
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"ComfyUI 执行失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("error") or res.get("message") or "ComfyUI 执行失败"),
        )

    # ── YuE（乐）全曲生成：符号规划 / 渲染整曲 / 翻唱转录（2026-09-28）──
    # 三层分工对齐画布「意图分层」：plan 出可编辑谱（意图）→ render 出整曲（实现）；
    # transcribe 是翻唱前置。执行端未配置时**诚实失败**（回传安装指引，不造假产物）。
    def yue_plan(self, req: CapabilityRequest) -> CapabilityResult:
        """YuE 符号规划：歌词+风格 → 可编辑的旋律+和弦乐谱（不出音频、不花钱）。"""
        p = req.params or {}
        try:
            from app.core.ai.yue_music import plan_song
            res = plan_song(
                lyrics=str(p.get("lyrics") or ""),
                style=str(p.get("style") or p.get("prompt") or ""),
                cot=str(p.get("cot") or "full"),
                seed=p.get("seed"),
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"YuE 规划失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "YuE 规划失败"),
        )

    def yue_render(self, req: CapabilityRequest) -> CapabilityResult:
        """YuE 渲染整曲：乐谱（可为用户编辑过的）→ 48kHz 完整歌曲。"""
        p = req.params or {}
        try:
            from app.core.ai.yue_music import render_song
            res = render_song(
                lyrics=str(p.get("lyrics") or ""),
                style=str(p.get("style") or p.get("prompt") or ""),
                abc=str(p.get("abc") or ""),
                cot=str(p.get("cot") or "full"),
                seed=p.get("seed"),
                title=str(p.get("title") or ""),
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"YuE 渲染失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "YuE 渲染失败"),
        )

    def yue_transcribe(self, req: CapabilityRequest) -> CapabilityResult:
        """翻唱前置：参考曲 → 旋律乐谱（SheetSage2 独立环境，只留旋律去和弦）。"""
        p = req.params or {}
        audio = str(p.get("audio") or p.get("audio_url") or p.get("reference") or "")
        if not audio:
            return CapabilityResult(req.request_id, False, error="缺少参考曲（audio）")
        try:
            from app.core.ai.yue_music import transcribe_reference
            res = transcribe_reference(
                audio=audio,
                melody_only=bool(p.get("melody_only", True)),
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"转录失败: {e}")
        ok = bool(res.get("ok"))
        return CapabilityResult(
            req.request_id, ok, output=res,
            error=None if ok else (res.get("message") or "转录失败"),
        )

    def concat_videos(self, req: CapabilityRequest) -> CapabilityResult:
        """拼接多段视频成片：复用 /host/video-concat 的 FFmpeg 拼接链路。"""
        import os
        import time as _time

        p = req.params or {}
        paths = [str(x) for x in (p.get("paths") or p.get("video_paths") or []) if str(x)]
        transition = float(p.get("transition_sec") or 0)
        if len(paths) < 2:
            return CapabilityResult(req.request_id, False, error="至少需要 2 个视频路径才能拼接")
        missing = [x for x in paths if not os.path.isfile(x)]
        if missing:
            return CapabilityResult(req.request_id, False, error=f"路径不存在: {missing[:3]}")
        try:
            from app.core.canvas_bridge import (
                _run_concat_demuxer, _run_concat_xfade, canvas_inbox_dir, _probe_duration,
            )
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"拼接依赖不可用: {e}")
        out = os.path.join(canvas_inbox_dir(), f"concat_{int(_time.time())}_{len(paths)}segs.mp4")
        try:
            result = _run_concat_xfade(paths, out, transition) if transition > 0 else _run_concat_demuxer(paths, out)
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"FFmpeg 拼接异常: {e}")
        if not result:
            return CapabilityResult(req.request_id, False, error="FFmpeg 拼接失败，请检查 ffmpeg 安装与输入文件")
        total_dur = sum(_probe_duration(x) for x in paths)
        return CapabilityResult(req.request_id, True, output={
            "ok": True,
            "output_path": result,
            "video_url": f"/inbox_file/{os.path.basename(result)}",
            "segment_count": len(paths),
            "total_duration": round(total_dur, 2),
            "transition_sec": transition,
        })

    def image_to_video(self, req: CapabilityRequest) -> CapabilityResult:
        """静帧图 → 伪视频：复用 /host/still-video 的单图链路（成片闭环用）。"""
        import base64 as _b64
        import os
        import time as _time
        import uuid as _uuid

        p = req.params or {}
        src = str(p.get("image_path") or p.get("image_url") or p.get("path") or p.get("url") or "").strip()
        if not src:
            return CapabilityResult(req.request_id, False, error="缺少 image_path / image_url")
        try:
            duration = float(p.get("duration") or 3.0)
        except (TypeError, ValueError):
            duration = 3.0
        try:
            from app.core.canvas_bridge import _image_to_still_video, canvas_inbox_dir, _safe_filename
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=f"图转视频依赖不可用: {e}")

        local_path = ""
        if "/inbox_file/" in src:
            local_path = os.path.join(canvas_inbox_dir(), _safe_filename(src.split("/inbox_file/", 1)[-1]))
        elif src.startswith("data:image/") and ";base64," in src:
            try:
                head, b64 = src.split(";base64,", 1)
                ext = "png"
                if "jpeg" in head or "jpg" in head:
                    ext = "jpg"
                elif "webp" in head:
                    ext = "webp"
                payload = _b64.b64decode(b64)
                name = f"{int(_time.time())}_{_uuid.uuid4().hex[:8]}.{ext}"
                dest = os.path.join(canvas_inbox_dir(), name)
                with open(dest, "wb") as f:
                    f.write(payload)
                local_path = dest
            except Exception as exc:
                return CapabilityResult(req.request_id, False, error=f"data URL 落盘失败: {exc}")
        else:
            local_path = src

        if not os.path.isfile(local_path):
            return CapabilityResult(req.request_id, False, error=f"图片不存在: {local_path}")
        ext = os.path.splitext(local_path)[1].lower()
        if ext in (".mp4", ".mov", ".webm", ".m4v", ".mkv"):
            return CapabilityResult(req.request_id, True, output={
                "ok": True, "path": os.path.abspath(local_path), "kind": "video",
            })
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            return CapabilityResult(req.request_id, False, error=f"不支持的图片格式: {ext}")
        out = _image_to_still_video(local_path, duration_sec=duration)
        if not out:
            return CapabilityResult(req.request_id, False, error="图转视频失败")
        return CapabilityResult(req.request_id, True, output={
            "ok": True, "path": os.path.abspath(out), "kind": "still",
            "video_url": f"/inbox_file/{os.path.basename(out)}", "duration": duration,
        })


# ────────────── 剪辑能力 handlers ──────────────
class EditorCapabilityHandlers:
    """剪辑能力 handlers —— 通过 EditorModule lazy 引用操作时间线"""

    def __init__(self, editor_module_ref: Callable[[], Any]):
        # lazy ref：调用时才取，避免 import 时拉起 UI
        self._get_editor = editor_module_ref

    def split_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """切分片段"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        split_time = float(req.params.get("split_time", 0))
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None)
        if not clip:
            return CapabilityResult(req.request_id, False, error=f"未找到片段 {clip_id}")
        res = editor.agent_split_clip(clip, split_time)
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(req.request_id, success="成功" in msg or "已" in msg,
                                output=res, error=None if "已" in msg else msg)

    def apply_filter(self, req: CapabilityRequest) -> CapabilityResult:
        """应用滤镜"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None) \
            or getattr(editor, "_current_clip", None)
        if not clip:
            return CapabilityResult(req.request_id, False, error="未选中片段")
        # 修复：agent_apply_filter 内部有 try/except，失败时返回
        # {"success": False, "message": ...}，此前这里完全不看返回值，
        # 无条件报 True——滤镜应用异常（比如片段数据损坏）也会被包装成成功。
        res = editor.agent_apply_filter(clip, req.params.get("filter_name", "电影"),
                                        float(req.params.get("intensity", 0.7)))
        ok = bool(isinstance(res, dict) and res.get("success"))
        return CapabilityResult(req.request_id, ok, output={"clip_id": clip.get("id"), **(res or {})},
                                error=None if ok else (res or {}).get("message", "应用滤镜失败"))

    def add_transition(self, req: CapabilityRequest) -> CapabilityResult:
        """添加转场"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None) \
            or getattr(editor, "_current_clip", None)
        if not clip:
            return CapabilityResult(req.request_id, False, error="未选中片段")
        # 修复：同 apply_filter，此前忽略 agent_apply_transition 的返回值，
        # 失败也无条件报 True
        res = editor.agent_apply_transition(clip, req.params.get("transition_type", "fade"),
                                            float(req.params.get("duration", 0.5)))
        ok = bool(isinstance(res, dict) and res.get("success"))
        return CapabilityResult(req.request_id, ok, output=res or {},
                                error=None if ok else (res or {}).get("message", "添加转场失败"))

    def get_timeline_context(self, req: CapabilityRequest) -> CapabilityResult:
        """获取时间线上下文"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        ctx = editor.agent_get_timeline_context()
        return CapabilityResult(req.request_id, True, output=ctx)

    def inspect_media(self, req: CapabilityRequest) -> CapabilityResult:
        """读取素材元信息：基础元数据（含分辨率/FPS）；deep=true 追加场景语义+音频情绪。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clips = list(getattr(editor, "_clips", []) or [])
        clip_id = req.params.get("clip_id") or req.params.get("id")
        if clip_id:
            clips = [c for c in clips if (c or {}).get("id") == clip_id]
            if not clips:
                return CapabilityResult(req.request_id, False, error=f"未找到片段 {clip_id}")
        if not clips:
            current = getattr(editor, "_current_clip", None)
            clips = [current] if isinstance(current, dict) else []
        if not clips:
            return CapabilityResult(req.request_id, False, error="时间线暂无片段")
        deep = bool(req.params.get("deep", False))
        media = [self._inspect_single_clip(c, deep) for c in clips if isinstance(c, dict)]
        return CapabilityResult(req.request_id, True, output={"count": len(media), "media": media})

    def _inspect_single_clip(self, clip: Dict[str, Any], deep: bool) -> Dict[str, Any]:
        """单片段元信息整理（不含 UI 写入，仅读）。"""
        import os
        path = clip.get("path") or clip.get("file_path") or ""
        info = {
            "id": clip.get("id"),
            "name": clip.get("name") or (os.path.basename(path) if path else ""),
            "path": path,
            "start_time": clip.get("start_time", 0),
            "duration": clip.get("duration", 0),
            "end_time": float(clip.get("start_time", 0) or 0) + float(clip.get("duration", 0) or 0),
            "track": clip.get("track", 0),
            "in_point": clip.get("in_point", 0),
            "out_point": clip.get("out_point"),
            "speed": clip.get("speed", 1.0),
            "has_keyframes": bool(clip.get("keyframes")),
            "keyframe_count": len(clip.get("keyframes") or []),
        }
        if path and os.path.isfile(path):
            resolution, fps = self._probe_resolution_fps(path)
            info["resolution"] = resolution
            info["fps"] = fps
        if deep and path and os.path.isfile(path):
            info["scenes"] = self._analyze_scenes(path)
            info["audio_emotion"] = self._analyze_audio_emotion(path)
        return info

    @staticmethod
    def _probe_resolution_fps(path: str) -> tuple:
        """用 ffprobe 读首条视频流的宽高与 FPS；失败返回 (None, None)。"""
        import os
        import subprocess
        import sys
        if not path or not os.path.isfile(path):
            return None, None
        try:
            from app.core.ffmpeg_utils import find_ffprobe
        except ImportError:
            from core.ffmpeg_utils import find_ffprobe  # type: ignore
        probe = find_ffprobe() or "ffprobe"
        try:
            r = subprocess.run(
                [probe, "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,avg_frame_rate",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception:
            return None, None
        if r.returncode != 0:
            return None, None
        fields = r.stdout.strip().split()
        if len(fields) < 3:
            return None, None
        try:
            width, height = int(fields[0]), int(fields[1])
        except (ValueError, IndexError):
            return None, None
        fps = None
        try:
            num, den = fields[2].split("/")
            den_f = float(den)
            fps = round(float(num) / den_f, 3) if den_f else None
        except (ValueError, ZeroDivisionError):
            fps = None
        return f"{width}x{height}", fps

    @staticmethod
    def _analyze_scenes(path: str) -> list:
        """用 SceneAnalyzer 做镜头/场景检测（PySceneDetect 优先，缺库降级）。"""
        try:
            from app.core.ai_editing_assistant import SceneAnalyzer
        except ImportError:
            from core.ai_editing_assistant import SceneAnalyzer  # type: ignore
        try:
            scenes = SceneAnalyzer().analyze_scenes(video_path=path)
        except Exception:
            return []
        out = []
        for s in scenes:
            out.append({
                "start_time": round(float(s.start_time), 3),
                "end_time": round(float(s.end_time), 3),
                "duration": round(float(s.end_time) - float(s.start_time), 3),
                "scene_type": getattr(s.scene_type, "value", str(s.scene_type)),
                "emotion": getattr(s.emotion, "value", str(s.emotion)),
                "confidence": round(float(getattr(s, "confidence", 0) or 0), 3),
                "description": getattr(s, "description", "") or "",
            })
        return out

    @staticmethod
    def _analyze_audio_emotion(path: str) -> dict:
        """用 AudioEmotionAnalyzer 提取音频情绪曲线摘要（librosa 缺失时诚实降级）。"""
        try:
            from app.core.ai.audio_emotion_analyzer import AudioEmotionAnalyzer, EMOTION_DIMS
        except ImportError:
            from core.ai.audio_emotion_analyzer import AudioEmotionAnalyzer, EMOTION_DIMS  # type: ignore
        try:
            analyzer = AudioEmotionAnalyzer()
            if not analyzer.available:
                return {"available": False, "reason": "librosa 未安装"}
            _times, vectors = analyzer.analyze_full_curve(path)
            if vectors is None or getattr(vectors, "size", 0) == 0:
                return {"available": True, "curve": []}
            mean = vectors.mean(axis=0)
            dominant = int(mean.argmax()) if mean.size else -1
            return {
                "available": True,
                "dims": list(EMOTION_DIMS),
                "average": {str(EMOTION_DIMS[i]): round(float(mean[i]), 3)
                            for i in range(min(len(EMOTION_DIMS), int(mean.size)))},
                "dominant": EMOTION_DIMS[dominant] if 0 <= dominant < len(EMOTION_DIMS) else None,
            }
        except Exception:
            return {"available": False, "reason": "音频情绪分析失败"}

    def ripple_delete_range(self, req: CapabilityRequest) -> CapabilityResult:
        """波纹删除时间线区间 [t_in, t_out)（接 B1，可撤销）"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        t_in = req.params.get("t_in", req.params.get("start_time"))
        t_out = req.params.get("t_out", req.params.get("end_time"))
        if t_in is None or t_out is None:
            return CapabilityResult(
                req.request_id, False,
                error="需要 t_in/t_out（或 start_time/end_time）",
            )
        track = req.params.get("track")
        track_i = int(track) if track is not None else None
        res = editor.agent_ripple_delete_range(
            float(t_in), float(t_out), track=track_i,
        )
        ok = bool(isinstance(res, dict) and res.get("success"))
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else msg,
        )

    def suggest_cleanup(self, req: CapabilityRequest) -> CapabilityResult:
        """M5：建议去水词/静音区间；默认弹勾选确认，不默认 run_full / 静默删除。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        open_ui = bool(req.params.get("open_ui", True))
        res = editor.agent_suggest_cleanup(open_ui=open_ui)
        ok = bool(isinstance(res, dict) and res.get("success"))
        # 仅建议（awaiting_confirm）也算成功交付建议
        if isinstance(res, dict) and res.get("awaiting_confirm") and res.get("intervals"):
            ok = True
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else msg,
        )

    def send_selected_to_canvas(self, req: CapabilityRequest) -> CapabilityResult:
        """选中片段 → 画布 outbox（确认后执行）。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = str(req.params.get("clip_id") or req.params.get("id") or "")
        res = editor.agent_send_selected_to_canvas(clip_id)
        ok = bool(isinstance(res, dict) and res.get("success"))
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else msg,
        )

    def suggest_canvas_roundtrip(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 建议哪些片送到画布；默认只出清单。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        open_ui = bool(req.params.get("open_ui", False))
        res = editor.agent_suggest_canvas_roundtrip(open_ui=open_ui)
        ok = bool(isinstance(res, dict) and res.get("success"))
        if isinstance(res, dict) and res.get("suggestions"):
            ok = True
        msg = res.get("message", "") if isinstance(res, dict) else str(res)
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else msg,
        )

    def set_clip_properties(self, req: CapabilityRequest) -> CapabilityResult:
        """设置片段标量属性：speed（变速）走 set_clip_speed，reverse（倒放）写片 dict 并同步。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None)
        if not clip:
            return CapabilityResult(req.request_id, False, error=f"未找到片段 {clip_id}")
        applied: Dict[str, Any] = {}
        # 变速：交给公开 set_clip_speed（含 clamp/撤销/预览刷新）
        if req.params.get("speed") is not None:
            try:
                editor.set_clip_speed(clip_id, float(req.params["speed"]))
                applied["speed"] = float(req.params["speed"])
            except (TypeError, ValueError) as e:
                return CapabilityResult(req.request_id, False, error=f"变速参数无效: {e}")
        # 倒放：写片段 dict，同步内核时间线并刷新预览
        if "reverse" in req.params:
            # 刀4：真相源字段写走 TimelineStore.set_fields（唯一字段写入口）
            editor._timeline_store.set_fields(clip_id, reverse=bool(req.params["reverse"]))
            applied["reverse"] = bool(req.params["reverse"])
            editor._sync_kernel_timeline()
            editor._refresh_preview_with_effects()
        return CapabilityResult(req.request_id, True, output={"clip_id": clip_id, **applied})

    def trim_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """裁剪片段：改时长 / 入点 / 出点（走 agent_trim_clip，可撤销 + 同步 UI）。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None)
        if not clip:
            return CapabilityResult(req.request_id, False, error=f"未找到片段 {clip_id}")
        # 兼容面板里的几种叫法：new_duration / duration / end_time
        duration = req.params.get("new_duration")
        if duration is None:
            duration = req.params.get("duration")
        if duration is None and req.params.get("end_time") is not None:
            try:
                duration = float(req.params["end_time"]) - float(clip.get("start_time", 0) or 0)
            except (TypeError, ValueError):
                return CapabilityResult(req.request_id, False, error="end_time 参数无效")
        res = editor.agent_trim_clip(
            clip_id,
            duration=duration,
            in_point=req.params.get("in_point"),
            out_point=req.params.get("out_point"),
        )
        ok = bool(isinstance(res, dict) and res.get("success"))
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else (res or {}).get("message", "裁剪失败"),
        )

    def move_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """移动片段到新时间点（走 agent_move_clip，可撤销 + 联动音画）。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        if not clip_id:
            return CapabilityResult(req.request_id, False, error="缺少 clip_id")
        if req.params.get("new_start_time") is None:
            return CapabilityResult(req.request_id, False, error="move_clip 需要 new_start_time（秒）")
        res = editor.agent_move_clip(clip_id, req.params.get("new_start_time"))
        ok = bool(isinstance(res, dict) and res.get("success"))
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else (res or {}).get("message", "移动片段失败"),
        )

    def reanchor_clips(self, req: CapabilityRequest) -> CapabilityResult:
        """词锚定重锚：文案改动后把片段重新对齐到新台词。

        **默认 dry_run=True —— 只出计划、不动时间线**。这是刻意的默认值：
        重锚会成批挪动片段，Agent 必须先让用户看到差异清单再落地。
        只在 ``params.dry_run=false`` 时才真正改写时间线。

        参数：
            dialogues: 新台词序列（可省略，回落 EditorModule._dialogues）
            dry_run:   默认 true
            threshold: 指纹相似度阈值，默认 0.75
            spread:    落地时是否按新词区间调整时长，默认 true
        """
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        # ⚠️ 默认 True：漏传 dry_run 时宁可只出计划，绝不静默改时间线
        dry_run = bool(req.params.get("dry_run", True))
        dialogues = req.params.get("dialogues")
        try:
            threshold = float(req.params.get("threshold", 0.75))
        except (TypeError, ValueError):
            return CapabilityResult(req.request_id, False, error="threshold 参数无效")
        res = editor.agent_reanchor_clips(
            dialogues,
            dry_run=dry_run,
            threshold=threshold,
            spread=bool(req.params.get("spread", True)),
        )
        ok = bool(isinstance(res, dict) and res.get("success"))
        if isinstance(res, dict) and res.get("applied"):
            ok = True
        return CapabilityResult(
            req.request_id, ok, output=res if isinstance(res, dict) else {"raw": res},
            error=None if ok else (res or {}).get("message", "重锚失败"),
        )

    def set_keyframes(self, req: CapabilityRequest) -> CapabilityResult:
        """批量写入关键帧（含插值/缓动），归一化字段后复用 EditorModule.add_keyframes_to_clip。"""
        editor = self._get_editor()
        if editor is None:
            return CapabilityResult(req.request_id, False, error="EditorModule 未就绪")
        clip_id = req.params.get("clip_id") or req.params.get("id")
        clip = next((c for c in editor._clips if c.get("id") == clip_id), None)
        if not clip:
            return CapabilityResult(req.request_id, False, error=f"未找到片段 {clip_id}")
        # 支持批量 list，也兼容单点（time/prop/value 直接挂 params）
        raw_keyframes = req.params.get("keyframes")
        if not isinstance(raw_keyframes, list):
            raw_keyframes = [req.params]
        normalized: List[Dict[str, Any]] = []
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
        if not normalized:
            return CapabilityResult(req.request_id, False, error="关键帧参数无效：缺少 prop/value")
        ok = editor.add_keyframes_to_clip(clip_id, normalized)
        if not ok:
            return CapabilityResult(req.request_id, False, error="写入关键帧失败（片段可能不在时间线）")
        return CapabilityResult(req.request_id, True, output={"clip_id": clip_id, "count": len(normalized)})


# ────────────── 模型能力 handlers ──────────────
class ModelCapabilityHandlers:
    """模型能力 handlers —— 封装 AIEngine"""

    def chat(self, req: CapabilityRequest) -> CapabilityResult:
        """调用指定 AI 提供者"""
        from app.core.ai_engine import ai_engine
        provider = req.params.get("provider", "")
        messages = req.params.get("messages", [])
        model = req.params.get("model")
        try:
            chunks = list(ai_engine.chat(provider, messages, model=model,
                                         stream=False, use_cache=req.params.get("use_cache", True)))
            text = "".join(chunks) if chunks else ""
            return CapabilityResult(req.request_id, True, output={"text": text})
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=str(e))

    def chat_with_fallback(self, req: CapabilityRequest) -> CapabilityResult:
        """智能降级调用 AI"""
        from app.core.ai_engine import ai_engine
        messages = req.params.get("messages", [])
        try:
            chunks = list(ai_engine.chat_with_fallback(
                messages=messages,
                providers=req.params.get("providers"),
                model=req.params.get("model"),
                template=req.params.get("template"),
            ))
            return CapabilityResult(req.request_id, True, output={"text": "".join(chunks)})
        except Exception as e:
            return CapabilityResult(req.request_id, False, error=str(e))

    def list_models(self, req: CapabilityRequest) -> CapabilityResult:
        """列出可用 AI 提供者"""
        from app.core.ai_engine import ai_engine
        providers = ai_engine.get_available_providers()
        return CapabilityResult(req.request_id, True, output={"providers": providers})


# ────────────── 拓展能力 handlers ──────────────
class ExtensionCapabilityHandlers:
    """拓展能力 handlers —— 统一 ExtensionsRegistry + SkillEngine"""

    def run_extension(self, req: CapabilityRequest) -> CapabilityResult:
        """
        运行扩展（三源统一：ExtensionsRegistry → SkillEngine → PluginManager）

        原先只走「注册表 → 技能」两源，**够不到 PluginManager 传统插件**
        （AI特效工坊等），Agent 调用会误报「未找到扩展」。现统一交给
        :func:`app.core.extension_facade.run_unified_tool`。
        """
        from app.core.extension_facade import run_unified_tool

        ext_id = req.params.get("extension_id") or req.params.get("ext_id")
        tool_id = req.params.get("tool_id") or ext_id
        call_params = req.params.get("params") or {}
        if not ext_id:
            return CapabilityResult(req.request_id, False, error="缺少 extension_id")

        out = run_unified_tool(ext_id, tool_id, call_params)
        if out.get("ok"):
            return CapabilityResult(req.request_id, True, output={"result": out.get("result")})
        return CapabilityResult(
            req.request_id, False,
            error=out.get("message") or f"未找到扩展: {ext_id}",
        )

    def run_skill(self, req: CapabilityRequest) -> CapabilityResult:
        """直接通过 SkillEngine 执行 Skill"""
        from app.modules.lego.skill_engine import skill_engine
        skill_id = req.params.get("skill_id")
        inputs = req.params.get("inputs") or {}
        if not skill_id:
            return CapabilityResult(req.request_id, False, error="缺少 skill_id")
        result = skill_engine.execute_skill(skill_id, inputs=inputs)
        return CapabilityResult(req.request_id, bool(result.get("success", False)),
                                output=result, error=result.get("error"))

    def list_tools(self, req: CapabilityRequest) -> CapabilityResult:
        """列出所有可用拓展工具（供 Agent 构建提示词）——三源统一。"""
        from app.core.extension_facade import list_unified_tools

        tools = list_unified_tools()
        return CapabilityResult(req.request_id, True, output={"tools": tools})


# ────────────── 多任务调度 handlers ──────────────
class WorkflowCapabilityHandlers:
    """多任务调度 handlers —— Flow/Workflow/Batch 三件套统一入口"""


    def submit_batch_task(self, req: CapabilityRequest) -> CapabilityResult:
        """提交批量任务"""
        from app.modules.lego.batch_task_manager import (
            BatchTaskManager, BatchTask, TaskPriority, TaskStatus,
        )
        from datetime import datetime
        manager = BatchTaskManager()
        task = BatchTask(
            task_id=req.params.get("task_id", req.request_id),
            name=req.params.get("name", "agent_batch"),
            task_type=req.params.get("task_type", "smart_clip"),
            params=req.params.get("params", {}),
            priority=TaskPriority[req.params.get("priority", "NORMAL").upper()],
            status=TaskStatus.PENDING,
            progress=0.0,
            created_at=datetime.now(),
        )
        # 兼容不同方法名
        if hasattr(manager, "submit_task"):
            manager.submit_task(task)
        elif hasattr(manager, "add_task"):
            manager.add_task(task)
        else:
            return CapabilityResult(req.request_id, False, error="BatchTaskManager 无入队接口")
        return CapabilityResult(req.request_id, True, output={"task_id": task.task_id})


# ────────────── Agent 全链路闭环 handlers ──────────────
class PipelineCapabilityHandlers:
    """
    Agent 全链路闭环能力 handlers —— 串联分流/生成/预览/打分/脚本/精剪/成片。
    精剪执行通过 editor_module_ref 回调 EditorModule（与剪辑能力一致）。
    """

    def __init__(self, editor_module_ref: Callable[[], Any]):
        self._get_editor = editor_module_ref

    def route(self, req: CapabilityRequest) -> CapabilityResult:
        """业务分流：判断走 AI生成业务线 or AI素材剪辑业务线"""
        from app.core.agent_pipeline_router import agent_pipeline_router
        result = agent_pipeline_router.route(
            materials=req.params.get("materials", []),
            creative_brief=req.params.get("creative_brief", ""),
            request_id=req.request_id,
        )
        return CapabilityResult(req.request_id, True, output=result.to_dict())

    def route_problem(self, req: CapabilityRequest) -> CapabilityResult:
        """问题路由（§6.9-P1 ROUTER 消费接线）：评分/标记 → 修复通道建议（只读、不执行）。

        参数：
            review: 五维评分 dict（ScoreResult.to_dict() 或 {"dimensions": {...}}），必填
            marks: 审核标记列表（如 ["subtitle_error"]），可选
            has_canvas_lineage: 片段是否有画布血缘，可选
            clip_id: 时间线片段 id；未显式给血缘时按片段自动推断
            features: 与 problem_router 口径一致的合并 dict，可选
        """
        from app.core.problem_router import route_problem
        review = req.params.get("review") or req.params.get("score")
        if not isinstance(review, dict):
            return CapabilityResult(
                req.request_id, False,
                error="需要 review（五维评分 dict：ScoreResult.to_dict() 或 dimensions 子 dict）")
        feats = dict(req.params.get("features") or {})
        if req.params.get("marks") is not None:
            feats["marks"] = req.params.get("marks")
        if req.params.get("has_canvas_lineage") is not None:
            feats["has_canvas_lineage"] = bool(req.params.get("has_canvas_lineage"))
        elif "has_canvas_lineage" not in feats:
            # 未显式给血缘 ⇒ 按时间线真相源自动推断（canvas_node_id 或非空 generation 块）
            clip_id = str(req.params.get("clip_id") or "")
            if clip_id:
                editor = self._get_editor()
                for c in (list(getattr(editor, "_clips", []) or []) if editor else []):
                    if c.get("id") == clip_id or c.get("clip_id") == clip_id:
                        feats["has_canvas_lineage"] = bool(
                            c.get("canvas_node_id") or c.get("generation"))
                        break
        result = route_problem(review, feats)
        return CapabilityResult(req.request_id, True, output=result)

    def generate(self, req: CapabilityRequest) -> CapabilityResult:
        """AI 视频生成业务线：创意拆解→生成→初检→回溯闭环

        可选传入 ``guards``（生成质量守护上下文）→ **管线自动**在生成前注入守护约束、
        生成后叠加守护质检（角色卡 / 道具结构 / 表情幅度 + 防漂移防畸形负面词）。
        """
        from app.core.ai_video_generation_pipeline import ai_video_generation_pipeline
        g = req.params.get("guards")
        # guards="auto"（或 {"auto": true, "character_name": "林晚", ...}）
        # → 从**角色库 / 参数自动装配**守护上下文，免去手填 {"character": {...}} 这类 JSON
        if g == "auto" or (isinstance(g, dict) and g.get("auto")):
            from app.core.ai.guard_pipeline import build_guards_from_context

            kw = dict(g) if isinstance(g, dict) else {}
            kw.pop("auto", None)
            # style_dna 未显式给时用平台当风格命名空间（评分簿按它隔离学习）
            if not kw.get("style_dna"):
                kw["style_dna"] = req.params.get("platform", "")
            g = build_guards_from_context(**kw)
        result = ai_video_generation_pipeline.execute(
            creative_brief=req.params.get("creative_brief", ""),
            platform=req.params.get("platform", "douyin"),
            target_duration=float(req.params.get("target_duration", 30.0)),
            clip_duration=float(req.params.get("clip_duration", 5.0)),
            provider=req.params.get("provider", "auto"),
            request_id=req.request_id,
            guards=g if isinstance(g, dict) else None,
        )
        return CapabilityResult(
            req.request_id, result.success,
            output={"clips": [c.to_dict() for c in result.clips],
                    "outline": result.outline, "error": result.error,
                    "cost_estimate": result.cost_estimate},
            error=result.error,
        )

    def quote(self, req: CapabilityRequest) -> CapabilityResult:
        """生成前报价（P1-1）：预计花费 + 谁接单 + 配额健康 —— 只读预演，不生成。

        参数（均可选）：
            provider:        auto/seedance/cogvideo/local（默认 auto）
            target_duration: 目标总时长（秒，默认 30）
            clip_duration:   单段时长（秒，默认 5）
            count:           段数（给了就直接用，否则按 target/clip 推算）
            spec:            能力需求（如 {"first_last_frame": true}）
        """
        from app.core.ai.video_generation_client import video_generation_client

        provider = req.params.get("provider", "auto")
        clip_duration = float(req.params.get("clip_duration", 5.0))
        count = req.params.get("count")
        if not count:
            target = float(req.params.get("target_duration", 30.0))
            count = max(1, int(target // clip_duration))
        q = video_generation_client.quote(
            str(provider), count=int(count), duration=clip_duration,
            spec=req.params.get("spec") or None)
        return CapabilityResult(
            req.request_id, True,
            output={
                "provider": q.get("provider"),
                "count": q.get("count"),
                "cost_estimate": q.get("cost_estimate", 0.0),
                "currency": q.get("currency", "CNY"),
                "price_per_clip": q.get("price_per_clip", 0.0),
                "account_id": q.get("account_id", ""),
                "quota_remaining": q.get("quota_remaining", 0),
                "cloud_available": q.get("cloud_available", False),
                "dead_providers": q.get("dead_providers", []),
                "reason": q.get("reason", ""),
                "note": q.get("note", ""),
            },
        )

    def llm_health(self, req: CapabilityRequest) -> CapabilityResult:
        """LLM 降级率查询（A4）：各 LLM 优先站点的近 24h 降级统计 —— 只读。

        降级 = LLM 不可用回退关键词/本地降级路径（功能没断但质量在暗处打折）。
        无参数；返回按站点汇总 + 最差站点。
        """
        from app.core.ai.llm_fallback_stats import summary

        data = summary() or {}
        worst = ""
        worst_rate = -1.0
        for site, info in data.items():
            rate = float(info.get("degradation_rate", 0.0))
            if rate > worst_rate:
                worst_rate, worst = rate, site
        return CapabilityResult(
            req.request_id, True,
            output={
                "sites": data,
                "site_count": len(data),
                "worst_site": worst,
                "worst_degradation_rate": round(max(worst_rate, 0.0), 1),
                "note": "降级=LLM不可用回退关键词匹配；持续高降级率应检查本地 Ollama/模型渠道",
            },
        )

    def submit_pipeline(self, req: CapabilityRequest) -> CapabilityResult:
        """全链路异步提交（P1-3）：立即返回任务号，进度可查、可取消、不阻塞。

        params 与 ``pipeline.run_full`` 一致（materials/creative_brief/platform/
        target_duration/clip_duration/provider/auto_preview_pass）。
        提交是**启动动作**（生成线可能花钱）——Agent 侧按危险动作走确认流。
        """
        from app.core.ai.pipeline_jobs import submit_full_pipeline

        params = {
            "materials": req.params.get("materials", []),
            "creative_brief": req.params.get("creative_brief", ""),
            "platform": req.params.get("platform", "douyin"),
            "target_duration": float(req.params.get("target_duration", 30.0)),
            "clip_duration": float(req.params.get("clip_duration", 5.0)),
            "provider": req.params.get("provider", "auto"),
            "auto_preview_pass": bool(req.params.get("auto_preview_pass", False)),
        }
        job = submit_full_pipeline(params)
        return CapabilityResult(req.request_id, bool(job.get("job_id")),
                                output=job,
                                error=None if job.get("job_id") else "任务提交失败")

    def job_status(self, req: CapabilityRequest) -> CapabilityResult:
        """管线任务状态查询（P1-3）：给 job_id 查单个（done 附完整结果 = fetch）；
        不给则列近期管线任务 + 队列统计。只读。"""
        from app.core.ai.pipeline_jobs import job_status as _js

        jid = str(req.params.get("job_id") or "").strip()
        out = _js(jid, limit=int(req.params.get("limit", 10) or 10))
        return CapabilityResult(req.request_id, bool(out.get("ok")), output=out,
                                error=None if out.get("ok") else str(out.get("message") or "任务不存在"))

    def job_cancel(self, req: CapabilityRequest) -> CapabilityResult:
        """取消管线任务（P1-3）：排队中真取消；运行中当前段跑完后生效、
        结果丢弃不落盘；终态幂等。"""
        from app.core.ai.pipeline_jobs import cancel_job

        jid = str(req.params.get("job_id") or "").strip()
        if not jid:
            return CapabilityResult(req.request_id, False, error="缺少 job_id")
        return CapabilityResult(req.request_id, True,
                                output=cancel_job(jid, str(req.params.get("reason") or "Agent 取消")))

    def preview_validate(self, req: CapabilityRequest) -> CapabilityResult:
        """预览校验：片段进入剪辑模块轨道 + AI自动核验

        修复两处假成功：
        1. `registered == 0`（没有任何片段真正登记到时间线）此前仍然
           `success=True`，只把错误信息塞进 error 字段——调用方按
           CapabilityResult.success 判断会误以为流程正常。
        2. `auto_preview_pass=True`（默认值）此前直接对每个片段调用
           `mark_preview_passed`，不做任何检查地无脑标记"预览通过"，
           `PreviewValidationLoop.ai_auto_inspect` 现成的路径为空/时长异常
           规则校验完全没被用上——所谓"AI自动核验"名不副实。改为调用
           `ai_auto_inspect` 真正跑一遍规则检查，只有通过的才标记通过。
        """
        from app.core.preview_validation_loop import preview_validation_loop
        clips = req.params.get("clips", [])
        auto_pass = req.params.get("auto_preview_pass", True)
        preview_validation_loop.clear()
        registered = preview_validation_loop.load_clips_to_timeline(
            clips, request_id=req.request_id)
        inspect_results = []
        if auto_pass:
            for c in clips:
                cid = c.get("clip_id") or c.get("id")
                if cid:
                    inspect_results.append(preview_validation_loop.ai_auto_inspect(cid))
        status = preview_validation_loop.get_preview_status()
        ok = registered > 0
        error = None if ok else "无片段登记"
        return CapabilityResult(req.request_id, ok,
                                output={**status, "inspect_results": inspect_results},
                                error=error)

    def regenerate_clip(self, req: CapabilityRequest) -> CapabilityResult:
        """局部重生成：预览发现问题后，重生成替换指定片段"""
        from app.core.preview_validation_loop import preview_validation_loop
        clip_id = req.params.get("clip_id")
        new_prompt = req.params.get("new_prompt", "")
        provider = req.params.get("provider", "auto")
        if not clip_id:
            return CapabilityResult(req.request_id, False, error="缺少 clip_id")
        new_clip = preview_validation_loop.request_regenerate(
            clip_id, new_prompt=new_prompt, provider=provider)
        if new_clip:
            return CapabilityResult(req.request_id, True, output=new_clip)
        return CapabilityResult(req.request_id, False, error="重生成失败或超上限")

    def score(self, req: CapabilityRequest) -> CapabilityResult:
        """五维量化打分：100分制 + S/A/B/C/D分级 + D级剔除"""
        from app.core.five_dimension_scorer import five_dimension_scorer
        clips = req.params.get("clips", [])
        features_list = [
            five_dimension_scorer.extract_features_from_clip({
                "id": c.get("clip_id") or c.get("id"),
                "path": c.get("path", ""),
                "duration": c.get("duration", 5.0),
                "quality_scores": c.get("quality_scores", {}),
            })
            for c in clips
        ]
        results = five_dimension_scorer.score_batch(features_list)
        # §6.9-P3 语义轨道：打分盖章进 clip 语义元数据（B4 形态；失败静默不影响返回）
        try:
            from app.core.clip_semantic import stamp_scored_results
            _cl = getattr(self._get_editor(), "_clips", None) or clips
            stamp_scored_results(_cl, [r.to_dict() for r in results])
        except Exception:
            logger.debug("[pipeline.score] 语义盖章失败（非关键）", exc_info=True)
        return CapabilityResult(req.request_id, True,
                                output={"results": [r.to_dict() for r in results]})

    def generate_script(self, req: CapabilityRequest) -> CapabilityResult:
        """剪辑创意脚本生成：根据打分结果生成最优剪辑脚本"""
        from app.core.editing_script_generator import editing_script_generator
        scored = req.params.get("scored_clips", [])
        script = editing_script_generator.generate(
            scored_clips=scored,
            target_duration=float(req.params.get("target_duration", 60.0)),
            platform=req.params.get("platform", "douyin"),
            request_id=req.request_id,
        )
        return CapabilityResult(req.request_id, True, output=script.to_dict())

    def director_breakdown(self, req: CapabilityRequest) -> CapabilityResult:
        """导演分身·拆分镜：剧本 → 结构化分镜表（LibTV 对标 P0-2，2026-09-26）。

        复用画布 ``/host/storyboard-breakdown`` 的同一实现
        （``canvas_aigc.storyboard_breakdown``）：默认启发式拆解（零成本、
        不改剧本原文），``use_llm=True`` 时走 LLM 结构化拆解。
        """
        from app.core.canvas_aigc import storyboard_breakdown
        script = str(req.params.get("script") or "")
        use_llm = bool(req.params.get("use_llm", False))
        res = storyboard_breakdown(script, use_llm=use_llm)
        ok = bool(res.get("ok"))
        return CapabilityResult(req.request_id, ok, output=res,
                                error=None if ok else str(res.get("message") or "拆分镜失败"))

    def director_camera_plan(self, req: CapabilityRequest) -> CapabilityResult:
        """导演分身·机位/运镜规划：分镜表（或剧本）→ 每镜机位 + 运镜路径。

        复用画布 ``/host/storyboard-camera-plan`` 的同一实现
        （``canvas_aigc.storyboard_to_camera_plan``）：景别 → 机位预设
        （position/lookAt/fov/shotSize）+ 运镜 pathPoints/pathDuration，
        可直接喂给画布 Stage3D 自动摆机位。
        """
        from app.core.canvas_aigc import storyboard_breakdown, storyboard_to_camera_plan
        shots = req.params.get("shots")
        if isinstance(shots, list) and shots:
            res = storyboard_to_camera_plan(shots)
        else:
            breakdown = storyboard_breakdown(
                str(req.params.get("script") or ""),
                use_llm=bool(req.params.get("use_llm", False)))
            res = storyboard_to_camera_plan(breakdown.get("shots") or [])
        ok = bool(res.get("ok"))
        return CapabilityResult(req.request_id, ok, output=res,
                                error=None if ok else str(res.get("message") or "机位规划失败"))

    def execute_editing(self, req: CapabilityRequest) -> CapabilityResult:
        """
        执行精修剪辑 + 成片输出
        调用 EditorModule 的精剪方法（步骤11新增），失败回退提示手动精剪。
        """
        editor = self._get_editor()
        editing_script = req.params.get("editing_script", {})
        if editor is None:
            return CapabilityResult(req.request_id, False,
                                    error="EditorModule 未就绪，请手动精剪")
        # 优先调用 EditorModule 新增的精剪入口
        handler = getattr(editor, "agent_execute_pipeline_editing", None)
        if not callable(handler):
            return CapabilityResult(req.request_id, False,
                                    error="EditorModule 暂未实现精剪入口，请手动精剪")
        try:
            output_path = handler(editing_script, req.params.get("session_id", ""))
            if output_path:
                # 修复：这里此前用的 key 是 "output_path"，但 UI 侧
                # （editor_module.py 手动精剪结果展示 / pipeline 结果卡片）
                # 全部统一读 "final_video_path"（其它 pipeline 结果 dict
                # 也都用这个 key）。key 对不上导致 UI 永远读到空字符串，
                # 即使精剪真的成功也只显示"已执行精剪"这种不带路径的模糊
                # 文案，看起来像没有产出成片。
                return CapabilityResult(req.request_id, True,
                                        output={"final_video_path": output_path,
                                                "output_path": output_path})
            return CapabilityResult(req.request_id, False,
                                    error="精剪未产出成片，请检查剪辑模块")
        except Exception as e:
            logger.exception("[pipeline.execute_editing] 执行异常")
            return CapabilityResult(req.request_id, False, error=str(e))

    def run_full(self, req: CapabilityRequest) -> CapabilityResult:
        """全链路一键执行：分流→生成/剪辑→预览→打分→脚本→精剪→成片"""
        from app.core.agent_pipeline_orchestrator import agent_pipeline_orchestrator
        session = agent_pipeline_orchestrator.execute(
            materials=req.params.get("materials", []),
            creative_brief=req.params.get("creative_brief", ""),
            platform=req.params.get("platform", "douyin"),
            target_duration=float(req.params.get("target_duration", 30.0)),
            clip_duration=float(req.params.get("clip_duration", 5.0)),
            provider=req.params.get("provider", "auto"),
            auto_preview_pass=req.params.get("auto_preview_pass", True),
            session_id=req.request_id,
        )
        return CapabilityResult(req.request_id, session.success,
                                output=session.to_dict(), error=session.error)

    # ── 生成质量守护 · 第一件：TTS 正音（治配音长文本漂移）──
    @staticmethod
    def _make_tts_llm():
        """把项目 ai_engine 包装成 tts_guard 需要的 (prompt)->str 回调。

        不可用时返回 None —— tts_guard 会降级为「只切段不注音」，绝不崩。
        """
        try:
            from app.core.ai_engine import ai_engine
        except Exception:
            logger.debug("[tts_polish] ai_engine 不可用，降级为只切段", exc_info=True)
            return None

        def _call(prompt: str) -> str:
            chunks = list(ai_engine.chat_with_fallback(
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            ))
            return "".join(chunks) if chunks else ""

        return _call

    def pinyin_lookup(self, req: CapabilityRequest) -> CapabilityResult:
        """汉字注音查询：逐字注音 + 多音字候选 + 生僻字（离线字典，不依赖 LLM）。

        只读查询（effect=read），不改任何数据。字典能力边界：CJK 扩展 B 区及
        以后（如 𠀋𠮷）标 `unknown` 并**不编造读音**；字典库缺失时诚实报错。

        params:
          text  要注音的字 / 词 / 句子（必填）
          mode  lookup（默认，逐字 + 多音字候选）| annotate（整段注音串）
                | ssml（按位置标注多音字的 SSML）| sapi（SAPI 数字式）
          style 注音风格：tone（默认，带声调符号）/ tone3 / normal
        """
        from app.core.ai import pinyin_dict

        text = str(req.params.get("text", "") or "")
        mode = str(req.params.get("mode", "lookup") or "lookup").lower()
        style = str(req.params.get("style", pinyin_dict.STYLE_TONE)
                    or pinyin_dict.STYLE_TONE)
        if not text:
            return CapabilityResult(req.request_id, False,
                                    output={"ok": False, "text": ""},
                                    error="text 不能为空")
        avail, reason = pinyin_dict.is_available()
        if not avail:
            return CapabilityResult(req.request_id, False,
                                    output={"ok": False, "text": text,
                                            "message": reason},
                                    error=reason)
        if mode == "annotate":
            out = pinyin_dict.annotate(text, style=style)
        elif mode == "ssml":
            out = pinyin_dict.to_ssml(text)
        elif mode == "sapi":
            out = pinyin_dict.to_sapi(text)
        else:
            out = pinyin_dict.lookup(text)
        return CapabilityResult(
            req.request_id, bool(out.get("ok")), output=out,
            error=None if out.get("ok") else str(out.get("message") or "注音失败"),
        )

    def tts_polish(self, req: CapabilityRequest) -> CapabilityResult:
        """TTS 正音：长台词切段 + 多音字注音（治「长视频后面发音错/与字幕不符」）。

        两道防线（本能力只出计划，effect=read，不改任何数据）：
          · 生成前：语义切段（每段回到 TTS 稳定长度）+ 多音字注音；
          · 生成后：传 asr_texts 时顺带跑回读质检，返回需**定向重生成**的段。

        params:
          text       台词原文（必填）
          max_chars  每段最大字数（默认 40）
          use_llm    是否接 LLM 做多音字消歧（默认 True；不可用时自动降级）
          asr_texts  可选，各段 ASR 回读文本 → 触发 verify_segments
          threshold  可选，回读相似度阈值（默认 0.9）
        """
        from app.core.ai.tts_guard import plan_tts, verify_segments

        text = req.params.get("text", "") or ""
        max_chars = int(req.params.get("max_chars", 40) or 40)
        llm = self._make_tts_llm() if req.params.get("use_llm", True) else None

        plan = plan_tts(text, max_chars=max_chars, llm=llm)

        asr_texts = req.params.get("asr_texts")
        if isinstance(asr_texts, list) and asr_texts and plan["segments"]:
            originals = [s["text"] for s in plan["segments"]]
            plan["readback"] = verify_segments(
                [str(x) for x in asr_texts],
                originals,
                threshold=float(req.params.get("threshold", 0.9) or 0.9),
            )

        return CapabilityResult(
            req.request_id, plan["ok"], output=plan,
            error=None if plan["ok"] else "台本为空，无可切分内容",
        )

    # ── 生成质量守护 · 第二件：角色一致性锚定（治人物跨镜头漂移）──
    def character_anchor(self, req: CapabilityRequest) -> CapabilityResult:
        """角色一致性锚定：跨镜头特征卡 + 漂移检测（治「人物形象漂移」）。

        只出计划（effect=read），不改任何数据：
          · 传 character          → 建立/复用锚定卡（特征指纹 + 防漂移负面词）
          · 再传 shot_prompts     → 校验各镜头 prompt 是否漏拼角色强特征
          · 传 anchor + character → 跑漂移检测（角色库被改动后定位变了哪几项）

        params:
          character        角色条目 dict（name/gender/appearance/… 对齐 CHARACTER_FIELD_SCHEMA）
          prompt           可选，已派生的角色 prompt（优先复用，保持派生单一来源）
          reference_image  可选，定妆照路径
          shot_prompts     可选，各镜头生成 prompt 列表 → 触发漏拼校验
          anchor           可选，已有锚定卡 → 与 character 做漂移比对
        """
        from app.core.ai.character_anchor import plan_anchor, plan_multi_anchor

        raw_chars = req.params.get("characters")
        # 多角色批量锚定（传 characters 列表时走批量路径：一次建多卡 + 跨角色冲突检查）
        if isinstance(raw_chars, list) and raw_chars:
            prompts = req.params.get("prompts")
            result = plan_multi_anchor(
                raw_chars, prompts=prompts if isinstance(prompts, dict) else None)
            return CapabilityResult(req.request_id, result["ok"], output=result)

        raw_char = req.params.get("character")
        shot_prompts = req.params.get("shot_prompts")
        raw_anchor = req.params.get("anchor")
        result = plan_anchor(
            raw_char if isinstance(raw_char, dict) else None,
            prompt=str(req.params.get("prompt") or ""),
            reference_image=str(req.params.get("reference_image") or ""),
            shot_prompts=list(shot_prompts) if isinstance(shot_prompts, list) else None,
            anchor=raw_anchor if isinstance(raw_anchor, dict) else None,
        )
        return CapabilityResult(
            req.request_id, result["ok"], output=result,
            error=None if result["ok"] else result["message"],
        )

    # ── 生成质量守护 · 第三件：表情幅度守护（治表情夸张）──
    def expression_clamp(self, req: CapabilityRequest) -> CapabilityResult:
        """表情幅度守护：权重钳制 + 帧间限幅 + 幅度质检（治「鼓腮等表情过于剧烈」）。

        只出计划（effect=read），不改任何数据：
          · 传 frames     → 生成前钳制（绝对幅度 + 帧间跳变）+ 生成后质检
          · 只传 emotion  → 仅出提示词约束（幅度克制描述 + 防夸张负面词）

        params:
          frames     可选，表情参数帧序列 [{arkit维度: 0~1}, …]（「鼓腮」= cheekPuff）
          emotion    可选，当前情绪（写进提示词片段）
          profile    可选，subtle / natural / intense（默认 natural）
          overrides  可选，覆盖个别维度上限 {维度: 上限}
          max_delta  可选，帧间最大变化（默认 0.25）
        """
        from app.core.ai.expression_guard import plan_expression

        frames = req.params.get("frames")
        ov = req.params.get("overrides")
        result = plan_expression(
            list(frames) if isinstance(frames, list) else None,
            emotion=str(req.params.get("emotion") or ""),
            profile=str(req.params.get("profile") or "natural"),
            overrides=ov if isinstance(ov, dict) else None,
            max_delta=float(req.params.get("max_delta", 0.25) or 0.25),
            sparse=bool(req.params.get("sparse", False)),
            sparse_min_delta=float(req.params.get("sparse_min_delta", 0.03) or 0.03),
        )
        return CapabilityResult(req.request_id, result["ok"], output=result)

    # ── 生成质量守护 · 第四件：手持道具守护（治武器结构畸形）──
    def prop_consistency(self, req: CapabilityRequest) -> CapabilityResult:
        """手持道具守护：结构约束 + 握持描述 + 道具漂移检测（治「武器结构畸形」）。

        实图诊断：手持长杆武器在握持处长出「一横一竖」的**三通 / T 形交叉结构**，
        本应是连续贯通、无分支的长杆 ⇒ 核心是**结构拓扑约束**，非握持一致性。

        只出计划（effect=read），不改任何数据。params:
          prop             可选，道具条目 dict（prop_type/prop_color/prop_material/…）
          prop_type        可选，道具类型键（spear/staff/sword/greatsword/axe/bow/staff_magic）
          grip             可选，握法（single_hand/two_hand/raised/shouldered/pointing）
          hand             可选，right/left/both
          custom_structure 可选，自定义结构描述（覆盖模板）
          anchor           可选，已有道具锚定卡 → 与 prop 做漂移比对
          hand_points      可选，21 点手部关键点 → 跑合理性规则
        """
        from app.core.ai.prop_guard import plan_prop

        prop = req.params.get("prop")
        anchor = req.params.get("anchor")
        hp = req.params.get("hand_points")
        result = plan_prop(
            prop if isinstance(prop, dict) else None,
            prop_type=str(req.params.get("prop_type") or ""),
            grip=str(req.params.get("grip") or "single_hand"),
            hand=str(req.params.get("hand") or "right"),
            custom_structure=str(req.params.get("custom_structure") or ""),
            off_prop_type=str(req.params.get("off_prop_type") or ""),
            anchor=anchor if isinstance(anchor, dict) else None,
            hand_points=list(hp) if isinstance(hp, list) else None,
        )
        return CapabilityResult(req.request_id, result["ok"], output=result)

    # ── 生成质量守护 · 总入口（多守护 + 全量负面词）──
    def guard_all(self, req: CapabilityRequest) -> CapabilityResult:
        """生成质量守护总入口：一次跑多个守护 + 合并全量负面词。

        只出计划（effect=read）。params:
          kinds   可选，要跑的守护列表（tts/character/expression/prop；缺省全跑）
          params  可选，{kind: {该守护入参}}，如
                  {"tts":{"text":"…"},"prop":{"prop_type":"spear","grip":"two_hand"}}
          不传 params 时仍会返回**全量负面词**（生成前一次拼齐约束）。
        """
        from app.core.ai.guards import plan_guards

        kinds = req.params.get("kinds")
        p = req.params.get("params")
        result = plan_guards(
            list(kinds) if isinstance(kinds, list) else None,
            params=p if isinstance(p, dict) else None,
        )
        return CapabilityResult(req.request_id, result["ok"], output=result)


# ────────────── 注册入口 ──────────────
def register_builtin_handlers(dispatcher: CapabilityDispatcher,
                              editor_module_ref: Optional[Callable[[], Any]] = None) -> None:
    """
    注册所有内置能力到 dispatcher

    参数：
        dispatcher: CapabilityDispatcher 实例
        editor_module_ref: 由 EditorModule 在面板创建时传入 lambda: self；
                          若为 None，则剪辑类能力返回 "未就绪"，但其他能力仍可用
    """
    if editor_module_ref is None:
        editor_module_ref = lambda: None

    ext_handlers = ExtensionCapabilityHandlers()
    model_handlers = ModelCapabilityHandlers()
    editor_handlers = EditorCapabilityHandlers(editor_module_ref)
    workflow_handlers = WorkflowCapabilityHandlers()
    pipeline_handlers = PipelineCapabilityHandlers(editor_module_ref)
    canvas_handlers = CanvasCapabilityHandlers()

    # 拓展模块
    dispatcher.register("ext.run_extension", CapabilityCategory.EXTENSION,
                        ext_handlers.run_extension, "运行拓展中心插件/Skill/MCP")
    dispatcher.register("ext.run_skill", CapabilityCategory.EXTENSION,
                        ext_handlers.run_skill, "通过 SkillEngine 执行 Skill")
    dispatcher.register("ext.list_tools", CapabilityCategory.EXTENSION,
                        ext_handlers.list_tools, "列出所有可用拓展工具")

    # 模型模块
    dispatcher.register("model.chat", CapabilityCategory.MODEL,
                        model_handlers.chat, "调用指定 AI 提供者")
    dispatcher.register("model.chat_with_fallback", CapabilityCategory.MODEL,
                        model_handlers.chat_with_fallback, "智能降级调用 AI")
    dispatcher.register("model.list_models", CapabilityCategory.MODEL,
                        model_handlers.list_models, "列出可用 AI 提供者")

    # 画布
    dispatcher.register("canvas.open", CapabilityCategory.CANVAS,
                        canvas_handlers.open, "打开 AI 画布模块")
    # 2026-10-19：配方（Agent 第一次能真正改画布，而不只是给建议）
    from app.core.capability_handlers_recipe import register_recipe_handlers
    register_recipe_handlers(dispatcher, CapabilityCategory.CANVAS)
    # V4.44/V4.45：代码×扩散（注册细节留能力模块；中央不再逐条堆，2026-10-20 拆分）
    from app.core.capability_handlers_code_video import register_code_video_handlers
    register_code_video_handlers(dispatcher, CapabilityCategory.PIPELINE)
    # 2026-10-20 精剪线：帧级审计 / 对齐计划（只读）
    from app.core.capability_handlers_precision import register_precision_handlers
    register_precision_handlers(dispatcher, editor_module_ref)
    # 2026-10-20 治理线：审美闸门（只读判定）
    from app.core.capability_handlers_gate import register_gate_handlers
    register_gate_handlers(dispatcher)
    dispatcher.register("canvas.sync_models", CapabilityCategory.CANVAS,
                        canvas_handlers.sync_models, "同步模型管理渠道到画布")
    dispatcher.register("canvas.list_actions", CapabilityCategory.CANVAS,
                        canvas_handlers.list_actions, "输出统一画布动作清单（单一事实来源）")
    # 画布生成（Agent 亲手驱动后端生成链路）
    dispatcher.register("canvas.generate_image", CapabilityCategory.CANVAS,
                        canvas_handlers.generate_image, "画布生图（模型广场 AIGC 渠道）")
    dispatcher.register("canvas.generate_video", CapabilityCategory.CANVAS,
                        canvas_handlers.generate_video, "画布生视频（模型广场 AIGC 渠道）")
    dispatcher.register("canvas.local_generate_image", CapabilityCategory.CANVAS,
                        canvas_handlers.local_generate_image, "本地生图（SD1.5/SDXL 双栈引擎）")
    # 刀 A2：抽卡选优 + 局部重绘能力化（此前只有端点/前端按钮，Agent 侧调不到）
    dispatcher.register("canvas.best_of_draw", CapabilityCategory.CANVAS,
                        canvas_handlers.best_of_draw, "抽卡选优（n 张 → 代理分取最优）")
    dispatcher.register("canvas.repair_image", CapabilityCategory.CANVAS,
                        canvas_handlers.repair_image, "局部重绘（只修坏区，不重抽）")
    dispatcher.register("canvas.comfyui_run", CapabilityCategory.CANVAS,
                        canvas_handlers.comfyui_run, "运行 ComfyUI 工作流（本地引擎）")
    dispatcher.register("canvas.concat_videos", CapabilityCategory.CANVAS,
                        canvas_handlers.concat_videos, "拼接多段视频成片（FFmpeg）")
    dispatcher.register("canvas.image_to_video", CapabilityCategory.CANVAS,
                        canvas_handlers.image_to_video, "静帧图转伪视频（成片闭环用）")
    # LibTV 对标补强（2026-10-12）：引擎就绪但此前 Agent 调不到；独立模块防本文件破 2000 行
    from app.core.capability_handlers_media import MediaCapabilityHandlers
    media_handlers = MediaCapabilityHandlers()
    # 剪辑 Skill 扩容（LibTV 对标第二刀）：把 EditorModule 既有能力接进能力目录
    from app.core.capability_handlers_editor_skills import EditorSkillHandlers
    editor_skill_handlers = EditorSkillHandlers(editor_module_ref)
    dispatcher.register("canvas.ai_upscale", CapabilityCategory.CANVAS,
                        media_handlers.ai_upscale, "AI 超分放大（ESPCN/RealESRGAN，如实回报引擎）")
    dispatcher.register("canvas.ai_matte", CapabilityCategory.CANVAS,
                        media_handlers.ai_matte, "AI 抠像换背景（降级必标注）")
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
                        media_handlers.director_apply_timeline, "导演结果落时间线（分镜+素材→入轨）")
    # YuE（乐）全曲生成：符号规划 / 渲染整曲 / 翻唱转录（本地或远程执行端，非云付费）
    dispatcher.register("canvas.yue_plan", CapabilityCategory.CANVAS,
                        canvas_handlers.yue_plan, "YuE 规划可编辑乐谱（不出音频）")
    dispatcher.register("canvas.yue_render", CapabilityCategory.CANVAS,
                        canvas_handlers.yue_render, "YuE 渲染完整歌曲（乐谱→48kHz 整曲）")
    dispatcher.register("canvas.yue_transcribe", CapabilityCategory.CANVAS,
                        canvas_handlers.yue_transcribe, "YuE 翻唱前置：参考曲转录旋律乐谱")
    # 画布节点级操作（canvas_tools 后端化）：由 _CANVAS_ACTION_ROWS 派生，统一走 dispatcher。
    # 节点状态在前端，handler 统一是 canvas_handlers.node_action（经 task.create 桥接回执）。
    from app.core.agent_action_registry import canvas_node_capabilities as _canvas_node_caps
    for _c in _canvas_node_caps():
        dispatcher.register(
            _c["capability_id"], CapabilityCategory.CANVAS,
            canvas_handlers.node_action, _c["description"],
        )

    # 剪辑模块
    dispatcher.register("editor.split_clip", CapabilityCategory.EDITOR,
                        editor_handlers.split_clip, "切分片段")
    dispatcher.register("editor.apply_filter", CapabilityCategory.EDITOR,
                        editor_handlers.apply_filter, "应用滤镜")
    dispatcher.register("editor.add_transition", CapabilityCategory.EDITOR,
                        editor_handlers.add_transition, "添加转场")
    dispatcher.register("editor.get_timeline_context", CapabilityCategory.EDITOR,
                        editor_handlers.get_timeline_context, "获取时间线上下文")
    dispatcher.register("editor.inspect_media", CapabilityCategory.EDITOR,
                        editor_handlers.inspect_media, "读取素材元信息（分辨率/场景/音频情绪）")
    dispatcher.register("editor.get_media", CapabilityCategory.EDITOR,
                        editor_handlers.inspect_media, "读取素材元信息（inspect_media 别名）")
    dispatcher.register("editor.set_clip_properties", CapabilityCategory.EDITOR,
                        editor_handlers.set_clip_properties, "设置片段属性（变速/倒放等）")
    dispatcher.register("editor.set_keyframes", CapabilityCategory.EDITOR,
                        editor_handlers.set_keyframes, "批量写入关键帧（含插值/缓动）")
    dispatcher.register("editor.ripple_delete_range", CapabilityCategory.EDITOR,
                        editor_handlers.ripple_delete_range, "波纹删除时间线区间")
    dispatcher.register("editor.trim_clip", CapabilityCategory.EDITOR,
                        editor_handlers.trim_clip, "裁剪片段（时长/入点/出点，可撤销）")
    dispatcher.register("editor.move_clip", CapabilityCategory.EDITOR,
                        editor_handlers.move_clip, "移动片段到新时间点（可撤销）")
    dispatcher.register("editor.suggest_cleanup", CapabilityCategory.EDITOR,
                        editor_handlers.suggest_cleanup, "建议去水词/静音并确认后执行")
    dispatcher.register("editor.send_selected_to_canvas", CapabilityCategory.EDITOR,
                        editor_handlers.send_selected_to_canvas, "选中片段推到 AI 画布")
    dispatcher.register("editor.suggest_canvas_roundtrip", CapabilityCategory.EDITOR,
                        editor_handlers.suggest_canvas_roundtrip, "建议哪些片送到画布做变体")
    dispatcher.register("editor.reanchor_clips", CapabilityCategory.EDITOR,
                        editor_handlers.reanchor_clips, "按新台词重锚片段（默认只出计划）")

    # 剪辑 Skill 扩容（LibTV 对标第二刀，2026-10-14）：
    # 全部为 EditorModule 既有能力的薄接线（删除/复制/音量/变速/静音/批量转场/
    # 卡点/场景切点/静音整理/字幕烧录/播放头/撤销重做/片段清单），零新算法。
    # 第三/四刀（字幕 6 项 + 序列 2 项）：复用 SubtitleManager 与 _ripple_delete_gaps。
    # 第五刀（关键帧 2 项）：复用 get_keyframes_for_clip / add_keyframe_at_playhead。
    for _cap_id, _method_name, _desc in (
        ("editor.delete_clip", "delete_clip", "删除片段（默认波纹，可撤销）"),
        ("editor.duplicate_clip", "duplicate_clip", "复制片段到新时间点"),
        ("editor.set_clip_volume", "set_clip_volume", "设置片段音量（0–200%）"),
        ("editor.set_clip_speed", "set_clip_speed", "设置片段速度（0.1–10x）"),
        ("editor.mute_clip", "mute_clip", "静音/取消静音片段"),
        ("editor.set_transition_all", "set_transition_all", "批量给相邻片段加转场"),
        ("editor.suggest_beat_cut", "suggest_beat_cut", "卡点切镜建议（确认后才切）"),
        ("editor.suggest_scene_cut", "suggest_scene_cut", "场景切换切点建议（确认后才切）"),
        ("editor.suggest_silence_trim", "suggest_silence_trim", "长静音整理建议（确认后才删）"),
        ("editor.burn_subtitles", "burn_subtitles", "字幕烧录（导出时自动烧）"),
        ("editor.get_playhead", "get_playhead", "读取播放头位置与选中片段"),
        ("editor.seek_playhead", "seek_playhead", "定位播放头到指定秒"),
        ("editor.undo_last", "undo_last", "撤销上一步"),
        ("editor.redo_last", "redo_last", "重做"),
        ("editor.list_timeline_clips", "list_timeline_clips", "列出时间线片段摘要"),
        ("editor.list_subtitles", "list_subtitles", "列出字幕条目（Agent 自省）"),
        ("editor.split_subtitle", "split_subtitle", "在指定时间点拆分字幕"),
        ("editor.merge_subtitles", "merge_subtitles", "合并两条字幕"),
        ("editor.set_subtitle_visible", "set_subtitle_visible", "显隐单条字幕"),
        ("editor.import_subtitles", "import_subtitles", "导入 SRT/VTT 字幕文件"),
        ("editor.export_subtitles", "export_subtitles", "导出字幕为 SRT"),
        ("editor.close_track_gaps", "close_track_gaps", "磁吸合缝：同轨片段贴齐（可撤销）"),
        ("editor.mark_sequence_in_out", "mark_sequence_in_out", "标记序列入点/出点/清除"),
        ("editor.get_keyframes", "get_keyframes", "读取片段关键帧列表"),
        ("editor.add_keyframe_at_playhead", "add_keyframe_at_playhead", "播放头处加关键帧"),
        # 血缘查询（智能时间线 P1 · Agent 接线，2026-10-17）：与 /host/clip-lineage 同一实现
        ("editor.get_clip_lineage", "get_clip_lineage", "片段血缘查询（clip↔画布节点+生成参数，只读）"),
        # 小白闭环自动粗剪合链（§6.9-P2 方案 1，2026-10-17）：委托 rough_cut_chain 单例
        ("editor.rough_cut_plan", "rough_cut_plan", "粗剪提案：排轨+水词/静音检测（只算不改）"),
        ("editor.rough_cut_apply", "rough_cut_apply", "粗剪写回：确认后波纹删除+合缝（可撤销）"),
        ("editor.rough_cut_export", "rough_cut_export", "粗剪导出成片（委托既有精剪出片入口）"),
        # 语义轨道原型（§6.9-P3 · 质量分/高光落 clip 元数据，2026-10-17）
        ("editor.get_clip_semantic", "get_clip_semantic", "查询片段语义元数据（质量分/高光，只读）"),
        ("editor.mark_clip_highlight", "mark_clip_highlight", "显式标记片段高光（覆盖自动判定）"),
    ):
        dispatcher.register(_cap_id, CapabilityCategory.EDITOR,
                            getattr(editor_skill_handlers, _method_name), _desc)

    # 多任务调度
    dispatcher.register("workflow.submit_batch", CapabilityCategory.WORKFLOW,
                        workflow_handlers.submit_batch_task, "提交批量任务")

    # Agent 全链路闭环
    dispatcher.register("pipeline.route", CapabilityCategory.PIPELINE,
                        pipeline_handlers.route, "业务分流：AI生成/素材剪辑")
    # 问题路由消费接线（§6.9-P1 ROUTER 后续刀，2026-10-17）：委托 route_problem 纯函数
    dispatcher.register("pipeline.route_problem", CapabilityCategory.PIPELINE,
                        pipeline_handlers.route_problem,
                        "问题路由：五维评分/标记→修复通道建议（只读不执行）")
    # 粗剪合链异步入口（§6.9-P2）：队列跑「入库→排轨→检测→审核卡」，确认后 apply+export
    dispatcher.register("pipeline.rough_cut_chain", CapabilityCategory.PIPELINE,
                        editor_skill_handlers.rough_cut_chain_submit,
                        "小白闭环粗剪合链：入库→排轨→水词检测→审核卡（异步队列）")
    dispatcher.register("pipeline.generate", CapabilityCategory.PIPELINE,
                        pipeline_handlers.generate, "AI视频生成业务线")
    dispatcher.register("pipeline.quote", CapabilityCategory.PIPELINE,
                        pipeline_handlers.quote, "生成前报价：预计花费+可用渠道+配额健康")
    dispatcher.register("pipeline.preview_validate", CapabilityCategory.PIPELINE,
                        pipeline_handlers.preview_validate, "预览校验：轨道排布+画面质检")
    dispatcher.register("pipeline.regenerate_clip", CapabilityCategory.PIPELINE,
                        pipeline_handlers.regenerate_clip, "局部重生成替换片段")
    dispatcher.register("pipeline.score", CapabilityCategory.PIPELINE,
                        pipeline_handlers.score, "五维量化打分+分级筛选")
    dispatcher.register("pipeline.generate_script", CapabilityCategory.PIPELINE,
                        pipeline_handlers.generate_script, "剪辑创意脚本生成")
    # 导演分身·可调用能力（LibTV 对标，2026-09-26）：拆分镜 / 机位规划，
    # 与画布 /host/storyboard-breakdown、/host/storyboard-camera-plan 同一实现。
    dispatcher.register("pipeline.director_breakdown", CapabilityCategory.PIPELINE,
                        pipeline_handlers.director_breakdown,
                        "导演分身·拆分镜：剧本→结构化分镜表（默认启发式零成本）")
    dispatcher.register("pipeline.director_camera_plan", CapabilityCategory.PIPELINE,
                        pipeline_handlers.director_camera_plan,
                        "导演分身·机位/运镜规划：分镜表→机位+运镜路径（可喂 Stage3D）")
    dispatcher.register("pipeline.execute_editing", CapabilityCategory.PIPELINE,
                        pipeline_handlers.execute_editing, "精修剪辑+成片输出")
    dispatcher.register("pipeline.run_full", CapabilityCategory.PIPELINE,
                        pipeline_handlers.run_full, "全链路一键执行")
    dispatcher.register("pipeline.submit", CapabilityCategory.PIPELINE,
                        pipeline_handlers.submit_pipeline,
                        "全链路异步提交：立即返回任务号，进度可查、可取消")
    dispatcher.register("pipeline.job_status", CapabilityCategory.PIPELINE,
                        pipeline_handlers.job_status,
                        "管线任务状态/进度/结果查询（无任务号则列近期任务）")
    dispatcher.register("pipeline.job_cancel", CapabilityCategory.PIPELINE,
                        pipeline_handlers.job_cancel,
                        "取消管线任务：排队真取消；运行中段间生效、结果丢弃")
    dispatcher.register("pipeline.llm_health", CapabilityCategory.PIPELINE,
                        pipeline_handlers.llm_health,
                        "LLM 降级率查询：各 LLM 站点近24h降级统计（只读）")
    dispatcher.register("pipeline.pinyin_lookup", CapabilityCategory.PIPELINE,
                        pipeline_handlers.pinyin_lookup,
                        "汉字注音查询：逐字注音 + 多音字候选 + 生僻字（离线字典）")
    dispatcher.register("pipeline.tts_polish", CapabilityCategory.PIPELINE,
                        pipeline_handlers.tts_polish,
                        "TTS 正音：长台词语义切段 + 多音字注音")
    dispatcher.register("pipeline.character_anchor", CapabilityCategory.PIPELINE,
                        pipeline_handlers.character_anchor,
                        "角色一致性锚定：跨镜头特征卡 + 漂移检测")
    dispatcher.register("pipeline.expression_clamp", CapabilityCategory.PIPELINE,
                        pipeline_handlers.expression_clamp,
                        "表情幅度守护：权重钳制 + 帧间限幅 + 幅度质检")
    dispatcher.register("pipeline.prop_consistency", CapabilityCategory.PIPELINE,
                        pipeline_handlers.prop_consistency,
                        "手持道具守护：结构约束 + 握持描述 + 道具漂移检测")
    dispatcher.register("pipeline.guard_all", CapabilityCategory.PIPELINE,
                        pipeline_handlers.guard_all,
                        "生成质量守护总入口：多守护 + 全量负面词")

    logger.info("[capability_handlers] 已注册内置能力（含画布）")
    from app.core.ai.execution_planner_handlers import register_execution_capabilities as _reg_exec
    _reg_exec(dispatcher)

    # ═══════════════════════════════════════════════════════════════
    # 启动自检（三项）——2026-09-19 加固
    #
    # 原实现的问题：三处自检全部只 logger.warning，且**自身异常降级为 logger.debug**，
    # 结果「守卫自己挂了也无人知晓」——正是它要防的那类静默缺陷（见
    # docs/_reports/2026-09-19-全库代码评价报告.md P1-3）。
    #
    # 现在：① 问题清单汇总成一条可见摘要（含计数，便于一眼扫到）
    #       ② 守卫自身异常升为 warning 并带 exc_info，不再吞
    #       ③ 结果写入模块级 _STARTUP_SELFCHECK，供启动面板 / _verify 脚本读取
    # ═══════════════════════════════════════════════════════════════
    _selfcheck = _run_startup_selfcheck(dispatcher)
    globals()["_STARTUP_SELFCHECK"] = _selfcheck

    if _selfcheck["total"]:
        logger.warning(
            "[capability_handlers] 启动自检发现 %d 项不一致（目录 %d / action映射 %d / 脑同步 %d），"
            "详见下方逐条告警；聚合结果见 capability_handlers._STARTUP_SELFCHECK",
            _selfcheck["total"],
            len(_selfcheck["catalog"]),
            len(_selfcheck["action_map"]),
            len(_selfcheck["brain_sync"]),
        )


def get_startup_selfcheck() -> Dict[str, Any]:
    """返回最近一次启动自检的聚合结果（供启动面板 / 回归脚本读取）。

    结构::

        {
          "catalog":     [...],   # 目录 ↔ 注册 双向不一致
          "action_map":  [...],   # 对话 action → capability 映射失效
          "brain_sync":  [...],   # AgentBrain 同步问题
          "guard_errors":[...],   # 守卫自身异常（原被 debug 吞掉）
          "total": int,
        }

    注意：``register_builtin_handlers`` 未被调用时返回空结构，不报错。
    """
    return globals().get("_STARTUP_SELFCHECK") or {
        "catalog": [], "action_map": [], "brain_sync": [],
        "guard_errors": [], "total": 0,
    }


def _run_startup_selfcheck(dispatcher) -> Dict[str, Any]:
    """执行三项启动自检，返回聚合结果；守卫自身异常不静默。"""
    result: Dict[str, Any] = {
        "catalog": [], "action_map": [], "brain_sync": [],
        "guard_errors": [], "total": 0,
    }

    # ── ① 目录一致性：目录 ↔ 真实注册 双向对齐 ──
    # 避免再次出现 editor.inspect_media 那种「注册了却漏 effect」的静默缺陷。
    try:
        from app.core.agent_capability_catalog import verify_catalog_consistency

        registered_ids = {e["capability_id"] for e in dispatcher.list_capabilities()}
        for problem in verify_catalog_consistency(registered_ids):
            result["catalog"].append(problem)
            logger.warning("[capability_catalog] 目录不一致：%s", problem)
    except Exception as e:
        msg = "一致性守卫自身失败: %r" % (e,)
        result["guard_errors"].append(msg)
        logger.warning("[capability_catalog] %s", msg, exc_info=True)

    # ── ② 对话 action → capability 映射一致性 ──
    try:
        from app.core.agent_action_registry import ACTION_TO_CAPABILITY

        known = {e["capability_id"] for e in dispatcher.list_capabilities()}
        for action, cap_id in ACTION_TO_CAPABILITY.items():
            if cap_id not in known:
                problem = "对话 action %r 映射到未注册 capability %r" % (action, cap_id)
                result["action_map"].append(problem)
                logger.warning("[capability_handlers] %s", problem)
    except Exception as e:
        msg = "action↔capability 自检自身失败: %r" % (e,)
        result["guard_errors"].append(msg)
        logger.warning("[capability_handlers] %s", msg, exc_info=True)

    # ── ③ 左右脑神经链接：让 AgentBrain 感知所有已注册 capability ──
    # 脑同步失败意味着 Agent 神经元表与实际能力脱节，不能再降为 debug。
    try:
        from app.core.agent_brain import agent_brain

        agent_brain.sync_from_dispatcher(dispatcher)
    except Exception as e:
        msg = "AgentBrain 同步 dispatcher 失败: %r" % (e,)
        result["brain_sync"].append(msg)
        logger.warning("[AgentBrain] %s", msg, exc_info=True)

    result["total"] = (
        len(result["catalog"]) + len(result["action_map"])
        + len(result["brain_sync"]) + len(result["guard_errors"])
    )
    return result
