#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模式 B 姿态解析端到端验证（verification 脚本，非严格单测）。

验证链路: PoseExtractService.extract → pose_worker 子进程 → BlazePose 关键点 JSON。
覆盖:
  - 后端探测（mediapipe/cv2 依赖就绪）
  - 视频文件不存在 → 诚实失败
  - 正常提取 → ok=True / frame_count>0 / kps33(33点) / coco18(18点) 结构正确
  - 结果 JSON 与 stdout 摘要双重一致

用法:
    .venv312\\Scripts\\python.exe tests\\verification\\verify_pose_extract.py
"""
from __future__ import annotations

import json
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _ROOT)

# 沙箱/CI 环境下 canvas inbox（用户目录）可能不可写：输出重定向到项目内 temp
from app.core.ai import pose_extract_service as pes

_TEMP_DIR = os.path.join(_ROOT, "app", "temp")


def _patched_output_path(video_path: str) -> str:
    """结果 JSON 写项目内 temp（仅验证脚本用，产品路径仍走 canvas inbox）。"""
    os.makedirs(_TEMP_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0][:40] or "video"
    return os.path.join(_TEMP_DIR, f"{int(time.time())}_{stem}_pose.json")


pes.PoseExtractService._make_output_path = staticmethod(_patched_output_path)


def main() -> int:
    failures = []

    # 1) 后端探测
    backend = pes.pose_extract_service.check_backend(force=True)
    print(f"[1] 后端探测: ok={backend.get('ok')} cv2={backend.get('cv2')} "
          f"mediapipe={backend.get('mediapipe')} msg={backend.get('message')}")
    if not backend.get("ok"):
        print("FAIL: 姿态解析后端未就绪（请先 pip install mediapipe opencv-python）")
        return 1

    # 2) 视频不存在 → 诚实失败
    miss = pes.pose_extract_service.extract(r"Z:\not\exists.mp4")
    print(f"[2] 缺失视频: ok={miss.get('ok')} msg={miss.get('message')}")
    if miss.get("ok") or not miss.get("message"):
        failures.append("缺失视频应诚实失败并给出 message")

    # 3) 正常提取（小采样快速验证）
    video = os.path.join(_ROOT, "app", "temp", "proxy_src.mp4")
    if not os.path.isfile(video):
        print(f"SKIP: 本地测试视频缺失 {video}")
        return 0 if not failures else 1

    res = pes.pose_extract_service.extract(
        video, sample_step=5, max_frames=20, timeout=120,
    )
    print(f"[3] 提取: ok={res.get('ok')} frames={res.get('frame_count')} "
          f"duration={res.get('duration')} fps={res.get('fps')}")
    if not res.get("ok"):
        failures.append(f"提取失败: {res.get('message')}")
    else:
        # 素材本身无人（纯色测试片）：这里只验证链路结构，检出能力由 [4] 合成人体覆盖
        if int(res.get("frame_count") or 0) <= 0:
            failures.append("frame_count 应 > 0")
        if not res.get("json_path") or not os.path.isfile(res["json_path"]):
            failures.append("结果 JSON 未落盘")
        else:
            data = json.load(open(res["json_path"], encoding="utf-8"))
            n_frames = len(data.get("frames") or [])
            has_meta = all(data.get(k) is not None for k in ("fps", "duration", "frame_count"))
            print(f"    JSON: frames={n_frames} meta完整={has_meta}")
            if n_frames != int(res["frame_count"]):
                failures.append("JSON 帧数与 stdout 摘要不一致")
            if not has_meta:
                failures.append("JSON 缺少 fps/duration/frame_count 元信息")

    # 4) 检出能力验证：素材无人时（如纯色测试片），合成人体剪影动画确证 worker 检出能力
    synth = os.path.join(_TEMP_DIR, "pose_synth_human.mp4")
    if not _synthesize_human_video(synth):
        print("WARN: 合成人体视频失败，跳过检出能力验证")
    else:
        res2 = pes.pose_extract_service.extract(
            synth, sample_step=2, max_frames=15, timeout=120,
        )
        data2 = {}
        if res2.get("ok") and res2.get("json_path") and os.path.isfile(res2["json_path"]):
            data2 = json.load(open(res2["json_path"], encoding="utf-8"))
        hits = sum(1 for f in data2.get("frames", []) if f.get("kps33"))
        print(f"[4] 合成人体: ok={res2.get('ok')} frames={res2.get('frame_count')} 检出={hits}")
        if hits <= 0:
            failures.append("合成人体视频 0 帧检出 → worker 检出逻辑可能有缺陷")
        else:
            f0 = next(f for f in data2["frames"] if f.get("kps33"))
            coco18 = f0.get("coco18") or []
            if len(coco18) != 18:
                failures.append(f"合成视频 coco18 应为 18 点，实际 {len(coco18)}")

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: 模式 B 姿态解析子进程链路验证通过")
    return 0


def _synthesize_human_video(path: str, frames: int = 24) -> bool:
    """用 OpenCV 合成摆臂人体剪影视频（白底黑色实心人形，BlazePose 可稳定检出）。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False

    w, h = 480, 640
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 12, (w, h))
    if not writer.isOpened():
        return False
    try:
        for i in range(frames):
            swing = 0.6 * abs(((i % 12) / 12.0) * 2 - 1)  # 0~1~0 摆动相位
            img = np.full((h, w, 3), 245, dtype=np.uint8)
            cx = w // 2
            # 头（圆）
            cv2.circle(img, (cx, 120), 42, (30, 30, 30), -1)
            # 躯干（粗线）
            cv2.line(img, (cx, 162), (cx, 360), (30, 30, 30), 52)
            # 双臂随相位摆动
            dx = int(80 * swing)
            cv2.line(img, (cx - 20, 200), (cx - 20 - dx, 300), (30, 30, 30), 22)
            cv2.line(img, (cx + 20, 200), (cx + 20 + dx, 300), (30, 30, 30), 22)
            # 双腿随相位反向摆动
            lx = int(50 * swing)
            cv2.line(img, (cx - 12, 360), (cx - 12 - lx, 540), (30, 30, 30), 26)
            cv2.line(img, (cx + 12, 360), (cx + 12 + lx, 540), (30, 30, 30), 26)
            writer.write(img)
    finally:
        writer.release()
    return os.path.isfile(path) and os.path.getsize(path) > 0


if __name__ == "__main__":
    sys.exit(main())
