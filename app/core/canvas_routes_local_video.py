# -*- coding: utf-8 -*-
"""画布桥 · 本地视频端点（V4.46.6 · 2026-10-24）

`POST /host/local-video-generate` —— **本机** diffusers 视频生成（SVD 图生视频）。

为什么外开 mixin：`canvas_routes_post.py` 已顶 2,000 行规模守卫（按 dub/roughcut/
digital_human 先例外开）。路由注册方式与既有 mixin 完全一致（`@_route_post`）。

首帧输入链路（2026-10-24 修）：画布节点的首帧常是 `/inbox_file/<name>`（图片节点产物
落画布 inbox 后就是这个 URL），此前只认 data URL ⇒ 本地 SVD 永远拿不到图。
现统一走 `local_video_infer.resolve_image_path`：data URL / inbox URL / 本地路径三态通吃。
"""

from __future__ import annotations

import json
import logging
import os

from app.core.canvas_route_registry import _route_post

logger = logging.getLogger(__name__)


def _cs():
    from app.core import canvas_server

    return canvas_server


def _family_of_model_id(model_id: str) -> str:
    """model_id → 模型族名。复用 ③ 的关键词表（_guess_model_kind），
    不另造第二套映射 —— 否则又是一处「同一件事两套实现」的漂移源。"""
    try:
        from app.core.local_video_infer import _guess_model_kind

        return _guess_model_kind(model_id or "") or ""
    except Exception:
        logger.debug("[/host/local-video-generate] 族名解析失败", exc_info=True)
        return ""


def _model_modes(model_id: str) -> dict[str, bool]:
    """模型能吃什么输入（**唯一真源 = `video_gen.available_models()` 的 `modes`**）。

    ★ 2026-11-15 修：此前「谁需要首帧图」有两套说法 —— 前端一份硬编码 Set、
      各族 `_infer_*` 各自校验（wan 明确拒绝，cogvideox/hunyuan/ltx 收下参数后
      **静默忽略**，等于假装支持）。这里收口成一处，且用**模型 id** 判而非族名：
      同族不同能力（wan21 只有 t2v，wan22 是 t2v+i2v）⇒ 按族名推断必错。

    查不到条目时两边都 True：**不代判**，交给各族的 `_infer_*` 如实拒绝。
    """
    try:
        from app.core.neural import video_gen as vg

        for m in vg.available_models() or []:
            if str(m.get("id") or "") != model_id:
                continue
            modes = [str(x) for x in (m.get("modes") or [])]
            if modes:
                return {"t2v": "t2v" in modes, "i2v": "i2v" in modes}
            break
    except Exception:
        logger.debug("[/host/local-video-generate] 模型能力读取失败（%s）", model_id, exc_info=True)
    return {"t2v": True, "i2v": True}


def _delegate_local_video_infer(body: dict, image_path: str, fam: str) -> dict:
    """按注册表声明委托 ③ generate_video_local（非 svd 族的统一出口）。

    诚实边界：③ 的签名不接 seed（不静默假装支持 —— 传了 seed 就在 warnings 里说明）。
    """
    # ── 能力前置判定（2026-11-15）：把「模型不吃图」变成一句可操作的话，而不是
    #    让请求跑到各族里被拒绝（wan）或静默忽略（cogvideox/hunyuan/ltx）。
    model_id = str(body.get("model_id") or fam)
    cap = _model_modes(model_id)
    if image_path and not cap["i2v"]:
        return {
            "ok": False,
            "model": model_id,
            "message": f"「{model_id}」是纯文生视频模型，不支持参考图 / 首帧图。"
            "请移除首帧图后重试，或改选支持图生视频的模型（如 svd-xt-i2v、wan22-ti2v-5b）",
        }
    if not image_path and not cap["t2v"]:
        return {
            "ok": False,
            "model": model_id,
            "message": f"「{model_id}」是图生视频模型，需要首帧图。"
            "请先给节点配一张首帧图，或改选纯文生视频模型（如 wan21-t2v-1.3b）",
        }
    try:
        from app.core.local_video_infer import generate_video_local
    except Exception as e:
        return {"ok": False, "message": f"local_video_infer 不可用: {e}"}
    # ★ 2026-11-01 修：尾帧此前在路由层就被丢掉（body 里有 last_frame 却从不往下传）
    #   ⇒ CogVideoX 的「首尾帧」分支永远只有首帧。这里与首帧同一条归一化通道解析。
    _last = str(body.get("last_frame") or "").strip()
    if _last:
        try:
            from app.core.local_video_infer import resolve_image_path

            _last = (
                resolve_image_path(
                    _last,
                    dest_dir=os.path.join("短剧AI剪辑输出", "_video_input"),
                    name_hint="canvas_last",
                )
                or ""
            )
        except Exception:
            logger.debug("[/host/local-video-generate] 尾帧解析失败", exc_info=True)
            _last = ""
    try:
        res = generate_video_local(
            prompt=str(body.get("prompt") or ""),
            model=str(body.get("model_id") or fam),
            duration=float(body.get("seconds") or 2.0),
            size=str(body.get("size") or "1280x720"),
            first_frame=image_path,
            reference_image=image_path,
            last_frame=_last,
            steps=(int(body["steps"]) if body.get("steps") else None),
        )
    except Exception as e:
        logger.exception("[/host/local-video-generate] 委托 ③ 失败")
        return {"ok": False, "message": f"{fam} 生成失败: {type(e).__name__}: {e}"}
    if body.get("seed") and isinstance(res, dict):
        res.setdefault(
            "warnings",
            list(res.get("warnings") or [])
            + [f"seed 参数在 {fam} 族的本地通道（local_video_infer）暂不支持，本次已忽略"],
        )
    return res


class CanvasLocalVideoRoutesMixin:
    """本地视频生成端点（由 `_BridgeHandler` 继承）。"""

    @_route_post("/host/local-video-generate")
    def _p_host_local_video_generate(self, parsed, raw: bytes, ctype: str) -> None:
        cs = _cs()
        if not cs._check_host_token(self):
            self._json(401, {"ok": False, "message": "unauthorized"})
            return
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._json(400, {"ok": False, "message": "invalid json"})
            return

        action = str(body.get("action") or "generate").strip().lower()
        try:
            from app.core.neural import video_gen as vg
        except Exception as e:
            self._json(500, {"ok": False, "message": f"视频模块加载失败: {e}"})
            return

        model_id = str(body.get("model_id") or "svd-xt-i2v").strip()

        # ── models：只读列出可选模型（含实测体积/显存/内存需求）──
        if action == "models":
            self._json(
                200,
                {
                    "ok": True,
                    "models": vg.available_models(),
                    "available": vg.VideoGenEngine.is_available(),
                    "unavailable_reason": vg.VideoGenEngine.unavailable_reason(),
                    "downloaded": [
                        m["id"]
                        for m in vg.available_models()
                        if vg.VideoGenEngine.is_downloaded(m["id"])
                    ],
                },
            )
            return

        # ── pull：下载模型（长耗时；前端应轮询或接受长请求）──
        if action == "pull":
            res = vg.get_video_engine().pull(model_id)
            logger.info("[/host/local-video-generate] pull %s ok=%s", model_id, res.get("ok"))
            self._json(200 if res.get("ok") else 400, res)
            return

        # ── generate：生成视频 ──
        image_path = str(body.get("image_path") or "").strip()
        image_data = str(
            body.get("image")
            or body.get("image_url")
            or body.get("first_frame")
            or body.get("reference_image")
            or ""
        ).strip()
        if not image_path and image_data:
            try:
                from app.core.local_video_infer import resolve_image_path

                image_path = (
                    resolve_image_path(
                        image_data,
                        dest_dir=os.path.join("短剧AI剪辑输出", "_video_input"),
                        name_hint="canvas",
                    )
                    or ""
                )
            except Exception:
                logger.debug("[/host/local-video-infer] 首帧解析失败", exc_info=True)
                image_path = ""
            if not image_path:
                self._json(
                    400,
                    {
                        "ok": False,
                        "message": "首帧图无法解析：支持 data URL / 本地路径 / /inbox_file/ URL",
                    },
                )
                return

        # ★ M4 入口合一（统一引擎，2026-10-24）：本端点从「video_gen 专属」升级为
        #   「本地视频统一入口」——族→后端的裁定交给 model_family 注册表：
        #   svd 族（本端点原生）走 ④；其余族按注册表声明委托 ③ generate_video_local。
        #   新模型接入 = 登记一条 spec，端点零改动（这正是合一的意义）。
        if not model_id.startswith("svd"):
            fam = _family_of_model_id(model_id)
            if fam:
                from app.core.neural import model_family as MF

                spec = MF.spec_of(fam)
                if spec is not None and MF.BACKEND_LOCAL_VIDEO in spec.backends:
                    res = _delegate_local_video_infer(body, image_path, fam)
                    logger.info(
                        "[/host/local-video-generate] M4 注册表路由 %s→local_video_infer ok=%s",
                        fam,
                        res.get("ok"),
                    )
                    self._json(200 if res.get("ok") else 400, res)
                    return
        if not image_path:
            self._json(
                400,
                {
                    "ok": False,
                    "message": "需要首帧图（image / image_url / first_frame / image_path 任一，SVD 是图生视频）",
                },
            )
            return
        try:
            res = vg.get_video_engine().generate(
                model_id,
                prompt=str(body.get("prompt") or ""),
                image_path=image_path,
                seconds=float(body.get("seconds") or 1.5),
                fps=int(body.get("fps") or 7),
                seed=int(body.get("seed") or 0),
                out_path=str(body.get("out_path") or ""),
            )
        except Exception as e:
            logger.exception("[/host/local-video-generate] 失败")
            self._json(500, {"ok": False, "message": str(e)})
            return
        # ★ 诚实边界（2026-11-01）：SVD 是**单首帧**图生视频，不吃尾帧。
        #   前端现在会把节点尾帧一起下发，这里必须如实说明「收到了但这一族用不上」——
        #   沉默会让用户以为首尾帧插值生效了。
        if str(body.get("last_frame") or "").strip() and isinstance(res, dict):
            res.setdefault("warnings", []).append(
                "SVD 族是单首帧图生视频，不支持尾帧 ⇒ 本次尾帧未生效（%s）" % model_id)
        logger.info("[/host/local-video-generate] generate %s ok=%s", model_id, res.get("ok"))
        self._json(200 if res.get("ok") else 400, res)
        return
