"""
速度编辑系统 (SpeedRamping)
============================
对标 Shotcut/OpenShot 的 Time Remap + Speed Ramping 功能。

特性:
- 速度关键帧曲线: 任意时间点的速度倍率
- 5 种内置缓动曲线 (linear, ease_in, ease_out, ease_in_out, step)
- 冻结帧: 任意时间点冻结画面
- 倒放: 单个片段或整段倒放
- 速度预设: 0.25x, 0.5x, 1x, 2x, 4x, 8x 快捷
"""
import os
import logging
import subprocess
import json
import tempfile
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger("AI短剧编辑器.speed_ramping")


class SpeedEasing(str, Enum):
    """速度缓动类型"""
    LINEAR = "linear"
    EASE_IN = "ease_in"           # 慢→快
    EASE_OUT = "ease_out"         # 快→慢
    EASE_IN_OUT = "ease_in_out"   # 慢→快→慢
    STEP = "step"                 # 阶梯 (阶跃)


def apply_easing(ratio: float, easing: "SpeedEasing") -> float:
    """把线性插值比例 ratio∈[0,1] 按 easing 曲线重映射。"""
    r = max(0.0, min(1.0, float(ratio)))
    if easing == SpeedEasing.EASE_IN:
        return r * r
    if easing == SpeedEasing.EASE_OUT:
        return 1.0 - (1.0 - r) * (1.0 - r)
    if easing == SpeedEasing.EASE_IN_OUT:
        return r * r * (3 - 2 * r)  # smoothstep
    if easing == SpeedEasing.STEP:
        return 0.0 if r < 0.5 else 1.0
    return r


@dataclass
class SpeedKeyframe:
    """速度关键帧"""
    time: float           # 关键帧时间 (片段内的相对时间, 秒)
    speed: float          # 速度倍率 (1.0=正常, 0.5=半速, 2.0=2倍速)
    easing: SpeedEasing = SpeedEasing.LINEAR

    def to_dict(self):
        return {"time": self.time, "speed": self.speed, "easing": self.easing.value}

    @classmethod
    def from_dict(cls, d: dict) -> "SpeedKeyframe":
        return cls(
            time=d.get("time", 0),
            speed=d.get("speed", 1.0),
            easing=SpeedEasing(d.get("easing", "linear")),
        )


@dataclass
class SpeedRamp:
    """速度曲线"""
    enabled: bool = False
    keyframes: List[SpeedKeyframe] = field(default_factory=list)

    def add_keyframe(self, time: float, speed: float, easing: SpeedEasing = SpeedEasing.LINEAR):
        """添加关键帧"""
        kf = SpeedKeyframe(time=time, speed=speed, easing=easing)
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.time)
        return kf

    def remove_keyframe(self, time: float) -> bool:
        """移除关键帧"""
        before = len(self.keyframes)
        self.keyframes = [k for k in self.keyframes if abs(k.time - time) > 0.001]
        return len(self.keyframes) < before

    def get_speed_at(self, time: float, total_duration: float = 0) -> float:
        """
        获取指定时间的速度倍率（按目标关键帧的 easing 曲线插值，而非纯线性）。

        Args:
            time: 关键帧时间
            total_duration: 片段总时长, 用于边界外推
        """
        if not self.keyframes:
            return 1.0
        sorted_kf = sorted(self.keyframes, key=lambda k: k.time)

        # 边界外推
        if time <= sorted_kf[0].time:
            return sorted_kf[0].speed
        if time >= sorted_kf[-1].time:
            return sorted_kf[-1].speed

        for i in range(len(sorted_kf) - 1):
            if sorted_kf[i].time <= time <= sorted_kf[i + 1].time:
                t0, t1 = sorted_kf[i].time, sorted_kf[i + 1].time
                s0, s1 = sorted_kf[i].speed, sorted_kf[i + 1].speed
                ratio = (time - t0) / (t1 - t0) if t1 > t0 else 0
                ratio = apply_easing(ratio, sorted_kf[i + 1].easing)
                return s0 + ratio * (s1 - s0)
        return 1.0

    def get_source_time(self, target_time: float) -> float:
        """
        给定输出/播放时间 target_time，估算源素材时间。

        关键帧时间轴为源时间；段内用梯形平均速度：
          d(out) = d(source) / avg_speed
          source 在段内按比例推进。
        """
        if not self.keyframes or target_time <= 0:
            return 0.0
        sorted_kf = sorted(self.keyframes, key=lambda k: k.time)
        if len(sorted_kf) == 1:
            return float(target_time) * max(1e-6, float(sorted_kf[0].speed))

        out_elapsed = 0.0
        for i in range(len(sorted_kf) - 1):
            seg_start = float(sorted_kf[i].time)
            seg_end = float(sorted_kf[i + 1].time)
            if seg_end <= seg_start + 1e-9:
                continue
            avg_speed = max(
                1e-6,
                (float(sorted_kf[i].speed) + float(sorted_kf[i + 1].speed)) / 2.0,
            )
            seg_out_dur = (seg_end - seg_start) / avg_speed
            if target_time <= out_elapsed + seg_out_dur + 1e-9:
                ratio = (target_time - out_elapsed) / seg_out_dur if seg_out_dur > 0 else 0.0
                ratio = max(0.0, min(1.0, ratio))
                return seg_start + ratio * (seg_end - seg_start)
            out_elapsed += seg_out_dur

        last = sorted_kf[-1]
        remaining = max(0.0, float(target_time) - out_elapsed)
        return float(last.time) + remaining * max(1e-6, float(last.speed))

    def segment_speeds(self, duration: float = 0.0) -> List[Tuple[float, float, float]]:
        """
        展开为分段常量速度 (src_in, src_out, speed)。

        非线性 easing 的关键帧对会按曲线拆成多个细分段（而非单一平均值），
        让「缓动」下拉真正影响渲染出的速度曲线；线性/单关键帧保持原有单段行为。
        """
        if not self.keyframes:
            return []
        kfs = sorted(self.keyframes, key=lambda k: k.time)
        if duration and duration > float(kfs[-1].time) + 1e-3:
            kfs = list(kfs) + [
                SpeedKeyframe(float(duration), float(kfs[-1].speed), kfs[-1].easing)
            ]
        if len(kfs) == 1:
            end = float(duration) if duration > 0 else float(kfs[0].time)
            if end <= float(kfs[0].time):
                end = float(kfs[0].time) + 1.0
            return [(float(kfs[0].time), end, max(1e-6, float(kfs[0].speed)))]
        segs: List[Tuple[float, float, float]] = []
        for i in range(len(kfs) - 1):
            t0, t1 = float(kfs[i].time), float(kfs[i + 1].time)
            if t1 <= t0 + 1e-6:
                continue
            s0, s1 = float(kfs[i].speed), float(kfs[i + 1].speed)
            easing = kfs[i + 1].easing
            if easing == SpeedEasing.LINEAR or abs(s1 - s0) < 1e-6:
                sp = max(1e-6, (s0 + s1) / 2.0)
                segs.append((t0, t1, sp))
                continue
            # 非线性：细分 N 段，逐段取该子区间的平均速度（近似曲线）
            n = 8
            for k in range(n):
                a, b = t0 + (t1 - t0) * k / n, t0 + (t1 - t0) * (k + 1) / n
                ra = apply_easing(k / n, easing)
                rb = apply_easing((k + 1) / n, easing)
                sp = max(1e-6, ((s0 + ra * (s1 - s0)) + (s0 + rb * (s1 - s0))) / 2.0)
                segs.append((a, b, sp))
        return segs

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "keyframes": [k.to_dict() for k in self.keyframes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpeedRamp":
        ramp = cls(enabled=d.get("enabled", False))
        ramp.keyframes = [SpeedKeyframe.from_dict(k) for k in d.get("keyframes", [])]
        return ramp

    @classmethod
    def preset_preset(cls, preset: str) -> "SpeedRamp":
        """常用预设"""
        ramp = cls(enabled=True)
        if preset == "bullet_time":
            ramp.add_keyframe(0, 1.0)
            ramp.add_keyframe(0.4, 0.2)
            ramp.add_keyframe(0.6, 0.2)
            ramp.add_keyframe(1.0, 1.0)
        elif preset == "ramp_in":
            ramp.add_keyframe(0, 0.5)
            ramp.add_keyframe(1.0, 1.0, SpeedEasing.EASE_IN)
        elif preset == "ramp_out":
            ramp.add_keyframe(0, 1.0)
            ramp.add_keyframe(1.0, 0.5, SpeedEasing.EASE_OUT)
        elif preset == "fast_slow_fast":
            ramp.add_keyframe(0, 2.0)
            ramp.add_keyframe(0.5, 0.5)
            ramp.add_keyframe(1.0, 2.0)
        elif preset == "slow_motion":
            ramp.add_keyframe(0, 0.5)
            ramp.add_keyframe(1.0, 0.5)
        return ramp


# ============================================================
# 倒放和冻结帧
# ============================================================

def reverse_clip_ffmpeg(input_path: str, output_path: str,
                         progress_cb=None) -> bool:
    """
    倒放片段 (使用 FFmpeg reverse 滤镜)

    Args:
        input_path: 输入视频路径
        output_path: 输出视频路径
        progress_cb: 进度回调

    Returns:
        是否成功
    """
    try:
        from app.core.render_manager import FFmpegTool

        # 使用 video/audio reverse 滤镜
        filter_complex = "[0:v]reverse[v];[0:a]areverse[a]"
        args = [
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
        ]

        # 进度回调
        def cb(pct, spd, eta):
            if progress_cb:
                progress_cb(pct, f"倒放: {pct:.0f}%")

        # 获取时长
        try:
            from app.core.video_processing.pyav_engine import PyAVEngine
            info = PyAVEngine.get_video_info(input_path)
            duration = info.get("duration", 0)
        except Exception:
            duration = 0

        success, err = FFmpegTool.run(args, progress_cb=cb, duration=duration)
        # 输出文件由 FFmpeg 写入
        if success:
            return True
        # 简化版 fallback
        cmd = [
            FFmpegTool.find_ffmpeg(),
            "-y", "-i", input_path,
            "-vf", "reverse",
            "-af", "areverse",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"倒放失败: {e}")
        return False


def freeze_frame_ffmpeg(input_path: str, output_path: str,
                        freeze_time: float, freeze_duration: float = 3.0) -> bool:
    """
    冻结帧: 在指定时间点冻结画面, 持续 freeze_duration 秒

    Args:
        input_path: 输入视频
        output_path: 输出视频
        freeze_time: 冻结时间点 (秒)
        freeze_duration: 冻结持续时长 (秒)

    Returns:
        是否成功
    """
    try:
        from app.core.render_manager import FFmpegTool

        # 简化: 使用 tpad 滤镜
        cmd = [
            FFmpegTool.find_ffmpeg(),
            "-y", "-i", input_path,
            "-vf", f"select='eq(n,{int(freeze_time * 30)})',setpts=N/30/TB,tpad=stop_mode=clone:stop_duration={freeze_duration}",
            "-af", f"atrim=0:{freeze_time},tpad=stop_mode=clone:stop_duration={freeze_duration}",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"冻结帧失败: {e}")
        return False


def chain_atempo_filters(speed: float) -> str:
    """将任意正速度拆成 FFmpeg atempo 链（单级仅支持 0.5–2.0）。"""
    s = max(0.01, float(speed))
    parts: List[str] = []
    while s > 2.0 + 1e-9:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.6f}")
    return ",".join(parts)


def build_speed_ramp_filter_complex(
    ramp: SpeedRamp,
    duration: float = 0.0,
) -> Tuple[str, List[str], float]:
    """
    多段 trim + setpts/atempo + concat，近似速度曲线。

    返回 (filter_complex, map_args, avg_speed_fallback)。
    map_args 形如 ["-map", "[vout]", "-map", "[aout]"]。
    """
    segs = ramp.segment_speeds(duration)
    if not segs:
        return (
            "[0:v]null[vout];[0:a]anull[aout]",
            ["-map", "[vout]", "-map", "[aout]"],
            1.0,
        )

    weights = [(t1 - t0) for t0, t1, _ in segs]
    speeds = [sp for _, _, sp in segs]
    avg = (
        sum(w * s for w, s in zip(weights, speeds)) / sum(weights)
        if sum(weights) > 0
        else sum(speeds) / len(speeds)
    )

    if len(segs) == 1:
        sp = segs[0][2]
        fc = (
            f"[0:v]setpts=PTS/{sp:.6f}[vout];"
            f"[0:a]{chain_atempo_filters(sp)}[aout]"
        )
        return fc, ["-map", "[vout]", "-map", "[aout]"], float(avg)

    parts: List[str] = []
    v_labs: List[str] = []
    a_labs: List[str] = []
    for i, (t0, t1, sp) in enumerate(segs):
        parts.append(
            f"[0:v]trim=start={t0:.6f}:end={t1:.6f},setpts=PTS-STARTPTS,"
            f"setpts=PTS/{sp:.6f}[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={t0:.6f}:end={t1:.6f},asetpts=PTS-STARTPTS,"
            f"{chain_atempo_filters(sp)}[a{i}]"
        )
        v_labs.append(f"[v{i}]")
        a_labs.append(f"[a{i}]")
    n = len(segs)
    parts.append(f"{''.join(v_labs)}concat=n={n}:v=1:a=0[vout]")
    parts.append(f"{''.join(a_labs)}concat=n={n}:v=0:a=1[aout]")
    return ";".join(parts), ["-map", "[vout]", "-map", "[aout]"], float(avg)


def source_time_for_clip_at_timeline(clip: Dict[str, Any], timeline_pos: float) -> float:
    """
    时间线绝对时间 → 片段源时间（A3：优先读 speed_ramp，否则常数 speed）。

    不改播放主时钟；供 scrub / 静态预览 / 解冻后的播放取帧调用。
    """
    st = float((clip or {}).get("start_time", 0) or 0)
    in_p = float((clip or {}).get("in_point", 0) or 0)
    local = max(0.0, float(timeline_pos) - st)
    ramp_raw = (clip or {}).get("speed_ramp")
    if isinstance(ramp_raw, dict) and ramp_raw.get("enabled") and ramp_raw.get("keyframes"):
        try:
            ramp = SpeedRamp.from_dict(ramp_raw)
            if ramp.keyframes:
                return max(0.0, float(ramp.get_source_time(local)))
        except Exception as e:
            logger.debug("speed_ramp 源时间映射失败，回退常数 speed: %s", e)
    speed = max(0.05, float((clip or {}).get("speed", 1.0) or 1.0))
    return max(0.0, local * speed + in_p)


def instant_speed_for_clip_at_timeline(clip: Dict[str, Any], timeline_pos: float) -> float:
    """
    时间线位置处的瞬时播放倍率（供 QMediaPlayer.setPlaybackRate）。

    有 speed_ramp 时：取映射后的源时间上的 get_speed_at；否则用 clip["speed"]。
    """
    st = float((clip or {}).get("start_time", 0) or 0)
    local = max(0.0, float(timeline_pos) - st)
    ramp_raw = (clip or {}).get("speed_ramp")
    if isinstance(ramp_raw, dict) and ramp_raw.get("enabled") and ramp_raw.get("keyframes"):
        try:
            ramp = SpeedRamp.from_dict(ramp_raw)
            if ramp.keyframes:
                src_t = float(ramp.get_source_time(local))
                return max(0.05, float(ramp.get_speed_at(src_t)))
        except Exception as e:
            logger.debug("speed_ramp 瞬时倍率失败，回退常数 speed: %s", e)
    return max(0.05, float((clip or {}).get("speed", 1.0) or 1.0))


def apply_speed_ramp_ffmpeg(input_path: str, output_path: str,
                             ramp: SpeedRamp, total_duration: float = 0,
                             progress_cb=None) -> bool:
    """
    应用速度曲线渲染：多段 trim/setpts/atempo；失败回退平均倍率。
    """
    try:
        from app.core.render_manager import FFmpegTool
        import shutil

        if not ramp.enabled or not ramp.keyframes:
            if os.path.abspath(input_path) != os.path.abspath(output_path):
                shutil.copy2(input_path, output_path)
            return True

        dur = float(total_duration or 0)
        if dur <= 0:
            try:
                from app.core.video_processing.pyav_engine import PyAVEngine
                info = PyAVEngine.get_video_info(input_path)
                dur = float(info.get("duration", 0) or 0)
            except Exception:
                dur = 0.0

        fc, maps, avg_speed = build_speed_ramp_filter_complex(ramp, dur)

        def cb(pct, spd, eta):
            if progress_cb:
                progress_cb(pct, f"变速渲染: {pct:.0f}% (分段曲线)")

        args = [
            "-i", input_path,
            "-filter_complex", fc,
            *maps,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path,
        ]
        success, err = FFmpegTool.run(args, progress_cb=cb, duration=dur)
        if success and os.path.exists(output_path):
            return True

        logger.warning("分段曲线变速失败，回退平均倍率: %s", err)
        # 回退：平均倍率 + 显式输出路径
        at = chain_atempo_filters(avg_speed)
        args_fb = [
            "-i", input_path,
            "-filter:v", f"setpts=PTS/{avg_speed:.6f}",
            "-filter:a", at,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac",
            output_path,
        ]

        def cb2(pct, spd, eta):
            if progress_cb:
                progress_cb(pct, f"变速渲染: {pct:.0f}% (avg={avg_speed:.2f}x)")

        success2, err2 = FFmpegTool.run(args_fb, progress_cb=cb2, duration=dur)
        if not success2:
            logger.error("平均倍率变速仍失败: %s", err2)
        return bool(success2 and os.path.exists(output_path))
    except Exception as e:
        logger.error(f"应用速度曲线失败: {e}")
        return False


# ============================================================
# 预设速度
# ============================================================

SPEED_PRESETS: Dict[str, float] = {
    "极慢 (0.25x)": 0.25,
    "半速 (0.5x)": 0.5,
    "正常 (1x)": 1.0,
    "2 倍速 (2x)": 2.0,
    "4 倍速 (4x)": 4.0,
    "8 倍速 (8x)": 8.0,
}
