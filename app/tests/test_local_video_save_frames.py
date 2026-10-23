# -*- coding: utf-8 -*-
"""_save_video_frames 必须能吃 SVD 输出的 PIL.Image 帧（2026-10-24 真机暴露的既有 bug）。

背景：SVD 的 result.frames[0] 是 PIL.Image 列表；旧代码在 cv2 分支先读 frames[0].shape
取尺寸 ⇒ 'Image' object has no attribute 'shape' ⇒ 只要装了 cv2（本项目装了），
SVD 本地出片必崩，且下面能处理 PIL 的 imageio 分支永远走不到。
并行会话的 V4.46.6 测试只测 resolve_image_path（"不加载模型"），从没覆盖真编码链路，
所以这个 bug 一直潜伏。本测试直接喂 PIL 帧锁死它，不加载任何模型。
"""

import os


def test_save_video_frames_accepts_pil_images(tmp_path):
    """SVD 给的是 PIL.Image —— 编码必须成功产出 mp4，不能因缺 .shape 崩。"""
    from PIL import Image

    from app.core.local_video_infer import _save_video_frames

    frames = [Image.new("RGB", (32, 32), (c, 40, 60)) for c in (10, 90, 180)]
    r = _save_video_frames(frames, str(tmp_path), 18765)
    assert r.get("ok") is True, f"PIL 帧编码失败（回归）: {r.get('message')}"
    assert os.path.isfile(r.get("video_path") or ""), "应产出真实 mp4 文件"
    assert os.path.getsize(r["video_path"]) > 0, "mp4 不能是空文件"


def test_save_video_frames_accepts_numpy_images(tmp_path):
    """numpy 帧（其它模型可能给）也必须继续可用 —— 修复不能只顾 PIL 一头。"""
    import numpy as np

    from app.core.local_video_infer import _save_video_frames

    frames = [np.full((32, 32, 3), v, dtype=np.uint8) for v in (20, 120, 220)]
    r = _save_video_frames(frames, str(tmp_path), 18765)
    assert r.get("ok") is True, f"numpy 帧编码失败: {r.get('message')}"
    assert os.path.getsize(r["video_path"]) > 0
