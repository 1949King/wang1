# -*- coding: utf-8 -*-
"""画布桥 · 多角色配音编排路由（2026-10-15，配音一致性方案 P0②③）

为什么单开一个 mixin
====================
`canvas_routes_post.py` 已 1932 行、逼近 `_verify/check_file_size.py` 的 2000 阈值，
照「桥函数另开文件」的既有纪律，把配音编排端点独立成 `CanvasDubRoutesMixin`
（与 canvas_routes_get / canvas_routes_post 同构，由 canvas_server._BridgeHandler 继承）。

三条端点与分工
==============
- `POST /host/dub-plan`   ：dry-run，只解析/路由/预估时长，**不合成、不落盘**。
- `POST /host/dub-execute`：真跑，复用 `voice_generator.AIVoiceGenerator`（既有降级链，
  **不新建 TTS 引擎**）逐句合成 → 写 wav → 返回每句音频路径/真实时长 + 拼轨 + 反推镜头时长。
- `POST /host/dub-to-timeline`：把已生成的音频段落时间线。
  ⚠️ **不新建第二条画布→时间线链路**：复用 `canvas_server.emit_canvas_to_editor`
  （与 `/host/batch-to-timeline` 同一个 helper、同一个 `EventType.MATERIAL_TO_TIMELINE`
  事件），仅把 `kind="audio"` 告知编辑器侧 ⇒ 编辑器走 `_add_audio_clip_to_timeline()`
  纯音轨入轨（不产生「wav 当视频片段」的脏数据）。

诚实边界（红线）
================
- 查不到角色音色 ⇒ `route_voices()` 明确标 `degraded` 并用默认声线，**不伪造**。
- 逐句合成失败 ⇒ 该句 `success=False` + `error_message` 原样回传，**不静默丢弃**。
- 预估时长在 dry-run 中一律标 `duration_source="estimate"`；只有真音频才覆盖镜头时长。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)

# 配音音频统一输出目录（相对主程序 cwd；与既有 .workbuddy 临时区同族，不入源码库）
_DUB_OUT_DIR = os.path.join(".workbuddy", "tmp", "dub")


def _cs():
    """延迟取 canvas_server 模块（顶层导入会循环：canvas_server 要继承本 mixin）。"""
    from app.core import canvas_server

    return canvas_server


def _char_lookup(characters: Any) -> Dict[str, Dict[str, Any]]:
    """把请求里的角色数组转成 {名字: 角色 dict} 供 `route_voices()` 查询。

    容错：非 list / 无 name 的条目直接跳过（不猜、不留脏键）。
    """
    lookup: Dict[str, Dict[str, Any]] = {}
    if isinstance(characters, list):
        for c in characters:
            if isinstance(c, dict) and c.get("name"):
                lookup[str(c["name"]).strip()] = c
    return lookup


def _estimate_duration(text: str) -> float:
    """dry-run 用的**粗略**时长预估（标 estimate，非真相）。

    中文朗读约 0.22 秒/字，下限 0.8 秒 —— 只用于 dry-run 预览，真实时长以
    `/host/dub-execute` 回传的音频 duration 为准。
    """
    return round(max(0.8, len(text or "") * 0.22), 3)


def _write_wav(audio_data: Any, sample_rate: int, out_path: str) -> bool:
    """把 TTS 返回的 numpy 音频写成单声道 16bit PCM WAV（stdlib wave，零额外依赖）。

    返回是否成功；失败由调用方记日志，**不抛**（避免单句写盘失败拖垮整批）。
    """
    try:
        import wave

        import numpy as np

        arr = np.asarray(audio_data)
        if arr.ndim > 1:
            arr = arr.reshape(-1)
        if arr.size == 0:
            return False
        peak = float(np.max(np.abs(arr)))
        if peak > 1.0:  # 归一化，避免整型溢出削波
            arr = arr / peak
        pcm16 = (np.clip(arr.astype(np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(sample_rate or 22050))
            wf.writeframes(pcm16.tobytes())
        return True
    except Exception as exc:
        logger.error("[dub] 写 WAV 失败 path=%s: %s", out_path, exc)
        return False


class CanvasDubRoutesMixin:
    """多角色配音编排端点集合（由 `_BridgeHandler` 继承）。"""

    # ── POST: dry-run 编排预演（不合成、不落盘） ────────────────────
    @_route_post("/host/dub-plan")
    def _p_host_dub_plan(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return

        try:
            from app.core.ai.dub_pipeline import (
                assemble_dialogue_track,
                parse_dialogue_lines,
                route_voices,
            )
        except ImportError:
            from core.ai.dub_pipeline import (  # type: ignore
                assemble_dialogue_track,
                parse_dialogue_lines,
                route_voices,
            )

        script = str(body.get("script") or "")
        if not script.strip():
            self._json(400, {"ok": False, "message": "script 不能为空"})
            return

        lines = route_voices(parse_dialogue_lines(script), _char_lookup(body.get("characters")))
        # 预估时长（dry-run 无音频，明确标 estimate）
        planned: List[Dict[str, Any]] = []
        for ln in lines:
            item = dict(ln)
            item["estimated_duration"] = _estimate_duration(ln.get("text", ""))
            item["duration_source"] = "estimate"
            planned.append(item)
        track = assemble_dialogue_track(
            [{"order": p["order"], "duration": p["estimated_duration"], "audio_path": ""} for p in planned],
            gap=float(body.get("gap") or 0.0),
        )
        degraded = [
            {"order": p["order"], "speaker": p.get("speaker"), "reason": p.get("degrade_reason", "")}
            for p in planned if p.get("degraded")
        ]
        logger.info("[/host/dub-plan] 分句=%d 降级=%d 预估总时长=%.2fs",
                    len(planned), len(degraded), track.get("total", 0.0))
        self._json(200, {
            "ok": True,
            "lines": planned,
            "track": track,
            "degraded": degraded,
            "note": "dry-run：时长为预估（duration_source=estimate），真实时长以 /host/dub-execute 为准",
        })
        return

    # ── POST: 真跑批量配音（逐句 TTS → 写盘 → 拼轨 → 反推镜头时长） ──
    @_route_post("/host/dub-execute")
    def _p_host_dub_execute(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return

        try:
            from app.core.ai.dub_pipeline import (
                assemble_dialogue_track,
                parse_dialogue_lines,
                retime_shots_by_audio,
                route_voices,
            )
        except ImportError:
            from core.ai.dub_pipeline import (  # type: ignore
                assemble_dialogue_track,
                parse_dialogue_lines,
                retime_shots_by_audio,
                route_voices,
            )
        try:
            from app.core.voice_generator import AIVoiceGenerator, VoiceGenerationRequest
        except ImportError:
            from core.voice_generator import AIVoiceGenerator, VoiceGenerationRequest  # type: ignore
        try:
            from app.core.ai.dub_verify import transcribe_for_subtitles, verify_dubbing
        except ImportError:
            from core.ai.dub_verify import transcribe_for_subtitles, verify_dubbing  # type: ignore

        # P1：听写回环验证与字幕 ASR 对齐默认**关闭**（避免普通配音请求被动加载 Whisper 模型）；
        # 调用方显式 verify/subtitles=true 时才跑，且 ASR 不可用时如实降级、绝不伪造。
        do_verify = bool(body.get("verify"))
        do_subs = bool(body.get("subtitles"))

        script = str(body.get("script") or "")
        if not script.strip():
            self._json(400, {"ok": False, "message": "script 不能为空"})
            return

        lines = route_voices(parse_dialogue_lines(script), _char_lookup(body.get("characters")))
        if not lines:
            self._json(400, {"ok": False, "message": "剧本未解析出任何台词"})
            return

        out_dir = str(body.get("out_dir") or _DUB_OUT_DIR)
        out_dir = os.path.abspath(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        gen = AIVoiceGenerator()
        results: List[Dict[str, Any]] = []
        audio_for_track: List[Dict[str, Any]] = []
        for ln in lines:
            order = int(ln.get("order") or 0)
            req = VoiceGenerationRequest(
                text=str(ln.get("text") or ""),
                voice_profile_id=str(ln.get("voice_profile_id") or ""),
                output_format="wav",
            )
            res = gen.generate_voice(req)
            entry: Dict[str, Any] = {
                "order": order,
                "speaker": ln.get("speaker"),
                "text": ln.get("text"),
                "route": ln.get("route"),
                "degraded": bool(ln.get("degraded")),
                "degrade_reason": ln.get("degrade_reason", ""),
                "voice_profile_id": ln.get("voice_profile_id"),
                "success": bool(getattr(res, "success", False)),
                "is_placeholder": bool(getattr(res, "is_placeholder", False)),
                "duration": float(getattr(res, "duration", 0.0) or 0.0),
                "audio_path": "",
                "error_message": str(getattr(res, "error_message", "") or ""),
            }
            if entry["success"] and getattr(res, "audio_data", None) is not None:
                out_path = os.path.join(out_dir, f"dub_{order:03d}.wav")
                if _write_wav(res.audio_data, int(getattr(res, "sample_rate", 22050) or 22050), out_path):
                    entry["audio_path"] = out_path
                    audio_for_track.append({
                        "order": order,
                        "duration": entry["duration"],
                        "audio_path": out_path,
                    })
                    # P1②：听写回环验证 —— 相似度低于阈值一律红标（不静默放行）
                    if do_verify:
                        v = verify_dubbing(out_path, str(entry.get("text") or ""))
                        entry["verified_similarity"] = v.get("similarity")
                        entry["verify_verdict"] = v.get("verdict")
                        entry["red_flag"] = bool(v.get("red_flag"))
                        entry["verify_reason"] = v.get("reason", "")
                else:
                    entry["success"] = False
                    entry["error_message"] = "音频写盘失败（见日志）"
            results.append(entry)

        track = assemble_dialogue_track(audio_for_track, gap=float(body.get("gap") or 0.0))
        shots_in = body.get("shots")
        shots_out = None
        if isinstance(shots_in, list) and shots_in:
            # 只把**成功合成**的句子喂进反推，避免用 0 时长污染镜头
            evidence = [{"text": r["text"], "duration": r["duration"]} for r in results if r["success"]]
            shots_out = retime_shots_by_audio(shots_in, evidence)

        failed = [r for r in results if not r["success"]]
        degraded = [r for r in results if r.get("degraded")]

        # P1③：字幕时间轴来自**音频听写**（音→字），不用剧本回填（剧本是"意图"，音频才是"真相"）。
        # ASR 不可用 / 无音频 ⇒ subtitle_source="unavailable" 且返回空表，如实降级。
        subtitle_segments: List[Dict[str, Any]] = []
        subtitle_source = "unavailable"
        if do_subs:
            for seg in track.get("segments", []):
                path = seg.get("audio_path") or ""
                if not path:
                    continue
                for sub in transcribe_for_subtitles(path):
                    # 把该段音频的局部时间戳平移到整条配音轨的绝对时间轴
                    subtitle_segments.append({
                        "start": round(float(seg["start"]) + float(sub["start"]), 3),
                        "end": round(float(seg["start"]) + float(sub["end"]), 3),
                        "text": sub["text"],
                        "order": seg.get("order"),
                    })
            if subtitle_segments:
                subtitle_source = "asr"

        ok = len(failed) == 0
        logger.info("[/host/dub-execute] 句数=%d 成功=%d 失败=%d 降级=%d 字幕=%d(%s) 总时长=%.2fs",
                    len(results), len(results) - len(failed), len(failed), len(degraded),
                    len(subtitle_segments), subtitle_source, track.get("total", 0.0))
        self._json(200, {
            "ok": ok,
            "results": results,
            "track": track,
            "shots": shots_out,
            "failed": len(failed),
            "degraded": len(degraded),
            "verified": do_verify,
            "red_flags": len([r for r in results if r.get("red_flag")]),
            "subtitles": subtitle_segments,
            "subtitle_source": subtitle_source,
            "out_dir": out_dir,
            "message": ("全部配音生成成功" if ok else f"{len(failed)} 句配音失败（见 results.error_message）"),
        })
        return

    # ── POST: 配音轨落时间线（复用既有唯一入轨 helper，kind="audio"） ──
    @_route_post("/host/dub-to-timeline")
    def _p_host_dub_to_timeline(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()

        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return

        segments = body.get("segments")
        if not isinstance(segments, list) or not segments:
            self._json(400, {"ok": False, "message": "segments 不能为空"})
            return

        pushed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        # 按 order 排序，保证落轨顺序 = 台词顺序（编辑器按 _next_clip_start_time 顺推）
        for seg in sorted((s for s in segments if isinstance(s, dict)), key=lambda s: int(s.get("order") or 0)):
            path = str(seg.get("audio_path") or "")
            if not path or not os.path.isfile(path):
                failed.append({"order": seg.get("order"), "audio_path": path, "message": "音频文件不存在"})
                continue
            # ⚠️ 唯一入轨通道：emit_canvas_to_editor → MATERIAL_TO_TIMELINE（kind=audio）
            res = cs.emit_canvas_to_editor(
                path,
                title=str(seg.get("title") or f"配音{int(seg.get('order') or 0)}"),
                source="dub_orchestration",
                kind="audio",
                duration_sec=float(seg.get("duration") or 0.0),
            )
            if res.get("success"):
                pushed.append({"order": seg.get("order"), "audio_path": path})
            else:
                failed.append({"order": seg.get("order"), "audio_path": path,
                               "message": res.get("message", "入轨失败")})

        logger.info("[/host/dub-to-timeline] 入轨 pushed=%d failed=%d", len(pushed), len(failed))
        self._json(200, {
            "ok": len(failed) == 0,
            "pushed": len(pushed),
            "failed": len(failed),
            "items": pushed,
            "errors": failed,
        })
        return
