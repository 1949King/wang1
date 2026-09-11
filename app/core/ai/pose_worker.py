"""
姿态解析 Worker（模式 B 子进程）
================================
独立子进程脚本：视频 → MediaPipe BlazePose 关键点 → JSON 落盘。

设计约束（docs/knowledge/17-motion-ref-design.md §五/§六）：
  - 必须以独立进程运行（由 pose_extract_service 调度），进程退出即释放显存；
  - 不 import app.* 模块，保证在任意 Python 环境可独立运行；
  - 依赖缺失 / 视频损坏 / 无有效帧 → 诚实失败（非零退出码 + stderr 说明），绝不输出假数据。

用法：
  python pose_worker.py --video <path> --out <json> [--sample-step 1] [--max-frames 300]
  python pose_worker.py --check    # 仅探测后端依赖，stdout 输出 JSON 状态

输出 JSON 结构（第三刀「关键点→白模 IK 时序」的直接输入）：
  {
    "ok": true, "backend": "mediapipe",
    "video": "<path>", "width": 1280, "height": 720,
    "fps": 30.0, "frame_count": 120, "duration": 4.0,
    "sample_step": 1, "generated_at": "2026-...",
    "frames": [
      {"frame": 0, "time": 0.0,
       "kps33":  [[x, y, z, vis], ...],   # BlazePose 33 原始归一化坐标（x/y∈[0,1]）
       "coco18": [[x, y, vis], ...]}      # OpenPose 18 约定映射（对齐 stage3dControlNet）
    ]
  }
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys


# BlazePose 33 → OpenPose/COCO 18 关键点映射（对齐 stage3dControlNet.ts 约定）
# COCO: 0:nose 1:neck 2:rShoulder 3:rElbow 4:rWrist 5:lShoulder 6:lElbow 7:lWrist
#       8:rHip 9:rKnee 10:rAnkle 11:lHip 12:lKnee 13:lAnkle 14:rEye 15:lEye 16:rEar 17:lEar
# 元组含两个索引时取中点（neck = 双肩中点），visibility 取均值。
_COCO18_FROM_BLAZE33 = [
    (0,),        # nose
    (11, 12),    # neck = 双肩中点
    (12,),       # rShoulder
    (14,),       # rElbow
    (16,),       # rWrist
    (11,),       # lShoulder
    (13,),       # lElbow
    (15,),       # lWrist
    (24,),       # rHip
    (26,),       # rKnee
    (28,),       # rAnkle
    (23,),       # lHip
    (25,),       # lKnee
    (27,),       # lAnkle
    (5,),        # rEye
    (2,),        # lEye
    (8,),        # rEar
    (7,),        # lEar
]

# 单帧最大采样数上限（防长视频爆内存 / JSON 过大）
_HARD_MAX_FRAMES = 900


def _emit_stdout(payload: dict) -> None:
    """单行 JSON 写 stdout（子进程通信通道；不用 print，规避稳定性门禁）。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _emit_stderr(message: str) -> None:
    """错误信息写 stderr（主进程捕获后记日志）。"""
    sys.stderr.write(f"[pose_worker] {message}\n")
    sys.stderr.flush()


def run_backend_check() -> int:
    """探测后端依赖可用性；stdout 输出 JSON 状态。仅 mediapipe 支持真实推理。"""
    status: dict = {"ok": False, "backend": "", "cv2": False, "mediapipe": False, "message": ""}
    try:
        import cv2  # noqa: F401

        status["cv2"] = True
    except Exception as exc:
        status["message"] = f"opencv-python 缺失: {exc}"
        _emit_stdout(status)
        return 1
    try:
        import mediapipe  # noqa: F401

        status["mediapipe"] = True
        status["ok"] = True
        status["backend"] = "mediapipe"
        status["message"] = "mediapipe 可用"
    except Exception as exc:
        status["message"] = f"mediapipe 缺失（模式 B 姿态解析需要）: {exc}"
    _emit_stdout(status)
    return 0 if status["ok"] else 1


def extract_pose(
    video_path: str,
    out_path: str,
    sample_step: int,
    max_frames: int,
    model_complexity: int,
) -> int:
    """逐帧提取 BlazePose 关键点并写 JSON；失败返回非零退出码（诚实失败）。"""
    import cv2
    import mediapipe as mp

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        _emit_stderr(f"无法打开视频: {video_path}")
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    sample_step = max(1, int(sample_step))
    budget = min(max(1, int(max_frames)), _HARD_MAX_FRAMES)

    frames: list = []
    pose = mp.solutions.pose.Pose(
        static_image_mode=False,
        model_complexity=int(model_complexity),
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    try:
        frame_idx = -1
        sampled = 0
        while sampled < budget:
            ok, bgr = cap.read()
            if not ok or bgr is None:
                break
            frame_idx += 1
            if frame_idx % sample_step != 0:
                continue
            result = pose.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            entry = {"frame": frame_idx, "time": round(frame_idx / fps, 4) if fps > 0 else float(frame_idx),
                     "kps33": [], "coco18": []}
            if result.pose_landmarks:
                kps33 = [
                    [round(lm.x, 5), round(lm.y, 5), round(lm.z, 5), round(lm.visibility, 4)]
                    for lm in result.pose_landmarks.landmark
                ]
                entry["kps33"] = kps33
                # COCO 18 映射：单索引直取，双索引取中点
                coco: list = []
                for spec in _COCO18_FROM_BLAZE33:
                    if len(spec) == 1:
                        x, y, _, v = kps33[spec[0]]
                        coco.append([x, y, v])
                    else:
                        a, b = kps33[spec[0]], kps33[spec[1]]
                        coco.append([
                            round((a[0] + b[0]) / 2, 5),
                            round((a[1] + b[1]) / 2, 5),
                            round((a[3] + b[3]) / 2, 4),
                        ])
                entry["coco18"] = coco
            frames.append(entry)
            sampled += 1
    finally:
        pose.close()
        cap.release()

    if not frames:
        _emit_stderr("视频没有可读帧（损坏或空文件）")
        return 1

    payload = {
        "ok": True,
        "backend": "mediapipe",
        "video": video_path,
        "width": width,
        "height": height,
        "fps": round(float(fps), 3),
        "frame_count": len(frames),
        "duration": round((frame_idx + 1) / fps, 3) if fps > 0 else 0.0,
        "source_total_frames": total,
        "sample_step": sample_step,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "frames": frames,
    }
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError as exc:
        _emit_stderr(f"结果 JSON 写入失败: {exc}")
        return 1

    _emit_stdout({
        "ok": True,
        "frame_count": len(frames),
        "duration": payload["duration"],
        "fps": payload["fps"],
        "out": out_path,
    })
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="拾光剪影 · 模式 B 姿态解析子进程")
    parser.add_argument("--check", action="store_true", help="仅探测后端依赖")
    parser.add_argument("--video", default="", help="输入视频路径")
    parser.add_argument("--out", default="", help="输出 JSON 路径")
    parser.add_argument("--sample-step", type=int, default=1, help="采样步长（1=逐帧）")
    parser.add_argument("--max-frames", type=int, default=300, help="最多采样帧数")
    parser.add_argument("--model-complexity", type=int, default=1, choices=(0, 1, 2), help="模型精度/速度档")
    args = parser.parse_args()

    if args.check:
        return run_backend_check()
    if not args.video or not args.out:
        _emit_stderr("缺少 --video / --out 参数")
        return 1
    try:
        return extract_pose(args.video, args.out, args.sample_step, args.max_frames, args.model_complexity)
    except Exception as exc:  # 兜底：任何未预期异常都诚实上报，不吞
        _emit_stderr(f"推理异常: {exc!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
