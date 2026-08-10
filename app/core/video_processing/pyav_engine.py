"""
PyAV 轻量视频引擎 (PyAVVideoEngine)
===================================
基于 PyAV (Python FFmpeg bindings) 的轻量级视频处理内核。
特点：极快的帧级精确访问，流式处理低内存占用，直连 FFmpeg C 库无 subprocess 开销。

与 C++ 引擎共享同一 FFmpeg 底层库，形成完整的性能梯度：
  PyAV 轻量引擎 → C++ 混合引擎 → FFmpeg CLI 回退
"""
import os
import time
import logging
from typing import Dict, List, Optional, Tuple, Callable, Generator
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger("AI短剧编辑器.pyav_engine")

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class VideoMeta:
    """视频元数据"""
    path: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: int = 0
    codec: str = ""
    has_audio: bool = False
    audio_codec: str = ""
    nb_frames: int = 0
    file_size: int = 0


@dataclass
class FrameData:
    """帧数据"""
    image: np.ndarray           # RGB24 numpy array (H, W, 3)
    timestamp: float = 0.0
    frame_index: int = 0


# ---------------------------------------------------------------------------
# PyAV 引擎
# ---------------------------------------------------------------------------

class PyAVVideoEngine:
    """PyAV 轻量级视频处理引擎"""

    def __init__(self):
        self._gpu_encoder: str = ""
        self._available_encoders: List[str] = []
        self._init_encoders()

    # -- 编码器检测 --

    def _init_encoders(self):
        """检测可用硬件编码器"""
        try:
            import av
            supported = []
            for name in ("h264_nvenc", "h264_qsv", "h264_amf", "hevc_nvenc", "hevc_qsv", "hevc_amf", "libx264"):
                try:
                    av.Codec(name, "w")
                    supported.append(name)
                except Exception as e:
                    logger.debug(f"[PyAVEngine] 检测编码器 {name} 失败: {e}")
            self._available_encoders = supported
            hw = [e for e in supported if e != "libx264"]
            self._gpu_encoder = hw[0] if hw else "libx264"
            logger.debug(f"编码器: GPU={self._gpu_encoder}, 可用={supported}")
        except Exception as e:
            logger.warning(f"编码器检测失败: {e}")
            self._gpu_encoder = "libx264"
            self._available_encoders = ["libx264"]

    @property
    def gpu_encoder(self) -> str:
        return self._gpu_encoder

    # -- 视频信息 --

    def probe(self, path: str) -> Optional[VideoMeta]:
        """快速获取视频元数据 (不解码)"""
        try:
            import av
            with av.open(path, metadata_errors="ignore") as container:
                video = container.streams.video[0] if container.streams.video else None
                audio = container.streams.audio[0] if container.streams.audio else None
                if not video:
                    return None

                meta = VideoMeta(
                    path=path,
                    duration=float(container.duration / av.time_base) if container.duration else 0,
                    width=video.width,
                    height=video.height,
                    fps=float(video.average_rate) if video.average_rate else 0,
                    codec=video.codec_context.name if video.codec_context else "",
                    has_audio=audio is not None,
                    audio_codec=audio.codec_context.name if audio and audio.codec_context else "",
                    nb_frames=video.frames if video.frames else 0,
                    bitrate=int(video.bit_rate) if video.bit_rate else 0,
                    file_size=os.path.getsize(path) if os.path.exists(path) else 0,
                )
                return meta
        except Exception as e:
            logger.warning(f"probe 失败 ({path}): {e}")
            return None

    # -- 帧操作 --

    def _seek_to_time(self, container, video_stream, target_sec: float):
        """Seek 到指定时间点"""
        import av
        pts = int(target_sec / video_stream.time_base)
        container.seek(pts, stream=video_stream)

    def extract_frame(self, path: str, timestamp: float = 0.0) -> Optional[FrameData]:
        """提取指定时间点的一帧 (返回 RGB numpy)"""
        try:
            import av
            with av.open(path, metadata_errors="ignore") as c:
                video = c.streams.video[0]
                # 禁用 B 帧参考以获得精确 seek
                video.thread_type = "AUTO"
                self._seek_to_time(c, video, timestamp)

                for frame in c.decode(video):
                    img = frame.to_ndarray(format="rgb24")
                    ts = float(frame.pts * video.time_base) if frame.pts else timestamp
                    return FrameData(image=img, timestamp=ts, frame_index=frame.index)
        except Exception as e:
            logger.warning(f"extract_frame 失败: {e}")
        return None

    def extract_frame_to_file(self, path: str, timestamp: float,
                              output_path: str, width: int = 0, height: int = 0) -> bool:
        """提取帧并保存为图片文件"""
        fd = self.extract_frame(path, timestamp)
        if fd is None:
            return False

        try:
            from PIL import Image
            img = Image.fromarray(fd.image)
            if width > 0 and height > 0:
                img = img.resize((width, height), Image.LANCZOS)
            img.save(output_path)
            return True
        except Exception as e:
            logger.warning(f"保存帧失败: {e}")
            return False

    def extract_thumbnails(self, path: str, count: int,
                           output_dir: str = "", width: int = 160, height: int = 90) -> List[str]:
        """均匀采样缩略图"""
        meta = self.probe(path)
        if not meta or meta.duration <= 0:
            return []

        import av
        results = []
        interval = meta.duration / count

        for i in range(count):
            ts = i * interval
            out_name = os.path.join(output_dir, f"thumb_{i:03d}.jpg") if output_dir else f"thumb_{i:03d}.jpg"
            os.makedirs(os.path.dirname(out_name) or ".", exist_ok=True)
            if self.extract_frame_to_file(path, ts, out_name, width, height):
                results.append(out_name)

        return results

    # -- 帧迭代器 (流式，低内存) --

    def iter_frames(self, path: str, step: int = 1,
                    start: float = 0, end: float = 0) -> Generator[FrameData, None, None]:
        """流式迭代视频帧 (不一次性加载到内存)"""
        import av
        with av.open(path, metadata_errors="ignore") as c:
            video = c.streams.video[0]
            count = 0
            for frame in c.decode(video):
                ts = float(frame.pts * video.time_base) if frame.pts else 0
                if start > 0 and ts < start:
                    continue
                if end > 0 and ts > end:
                    break
                if count % step == 0:
                    img = frame.to_ndarray(format="rgb24")
                    yield FrameData(image=img, timestamp=ts, frame_index=frame.index)
                count += 1

    # -- 视频剪辑 (重新编码) --

    def trim(self, input_path: str, output_path: str,
             start: float = 0, duration: float = 0,
             width: int = 0, height: int = 0,
             fps: float = 0, codec: str = "",
             progress_cb: Callable = None) -> bool:
        """剪辑视频 (逐帧解码+编码，精度最高)"""
        import av

        meta = self.probe(input_path)
        if not meta:
            return False

        end = start + duration if duration > 0 else meta.duration
        out_w = width or meta.width
        out_h = height or meta.height
        out_fps = fps or meta.fps
        out_codec = codec or self._gpu_encoder

        try:
            i_container = av.open(input_path, metadata_errors="ignore")
            i_video = i_container.streams.video[0]
            i_video.thread_type = "AUTO"

            o_container = av.open(output_path, "w")
            o_stream = o_container.add_stream(out_codec, rate=int(out_fps))
            o_stream.width = out_w
            o_stream.height = out_h
            o_stream.pix_fmt = "yuv420p"
            if hasattr(o_stream, "options"):
                o_stream.options = {"preset": "fast"}

            # 音频直通 (如果存在)
            audio_in = None
            audio_out = None
            if meta.has_audio:
                audio_in = i_container.streams.audio[0]
                audio_out = o_container.add_stream(template=audio_in)

            self._seek_to_time(i_container, i_video, start)
            frame_count = 0
            total = int((end - start) * out_fps) if duration > 0 else 0

            # 分别 demux 视频和音频
            for packet in i_container.demux(i_video, audio_in):
                if packet.stream == i_video:
                    for frame in packet.decode():
                        ts = float(frame.pts * i_video.time_base) if frame.pts else 0
                        if ts < start:
                            continue
                        if ts > end:
                            break
                        if out_w != meta.width or out_h != meta.height:
                            frame = frame.reformat(out_w, out_h, "yuv420p")
                        for opacket in o_stream.encode(frame):
                            o_container.mux(opacket)
                        frame_count += 1
                        if progress_cb and total > 0 and frame_count % 10 == 0:
                            progress_cb(min(99, frame_count / total * 100), 0, 0)
                    if ts > end:
                        break
                elif audio_out and packet.stream == audio_in:
                    ts = float(packet.pts * audio_in.time_base) if packet and packet.pts else 0
                    if ts < start:
                        continue
                    if ts > end:
                        break
                    for aframe in packet.decode():
                        for opacket in audio_out.encode(aframe):
                            o_container.mux(opacket)

            # Flush video
            for opacket in o_stream.encode():
                o_container.mux(opacket)
            # Flush audio
            if audio_out:
                for opacket in audio_out.encode():
                    o_container.mux(opacket)

            i_container.close()
            o_container.close()

            if progress_cb:
                progress_cb(100, 0, 0)

            return os.path.exists(output_path) and os.path.getsize(output_path) > 0

        except Exception as e:
            logger.error(f"trim 失败: {e}")
            return False

    # -- 视频合并 --

    def merge(self, paths: List[str], output_path: str,
              codec: str = "", progress_cb: Callable = None) -> bool:
        """合并多个视频 (含音频，自动统一分辨率)"""
        if not paths:
            return False

        import av
        first_meta = self.probe(paths[0])
        if not first_meta:
            return False

        out_codec = codec or self._gpu_encoder

        try:
            o_container = av.open(output_path, "w")
            o_stream = o_container.add_stream(out_codec, rate=int(first_meta.fps))
            o_stream.width = first_meta.width
            o_stream.height = first_meta.height
            o_stream.pix_fmt = "yuv420p"
            if hasattr(o_stream, "options"):
                o_stream.options = {"preset": "fast"}

            # 音频输出流（取第一个视频的音频参数）
            audio_out = None
            if first_meta.has_audio:
                audio_out = o_container.add_stream("aac", rate=first_meta.fps)
                if hasattr(audio_out, "options"):
                    audio_out.options = {"b": "128k"}

            total_clips = len(paths)
            for idx, path in enumerate(paths):
                i_container = av.open(path, metadata_errors="ignore")
                i_video = i_container.streams.video[0]
                i_video.thread_type = "AUTO"
                i_audio = i_container.streams.audio[0] if i_container.streams.audio else None

                for packet in i_container.demux(list(filter(None, [i_video, i_audio]))):
                    if packet.stream == i_video:
                        for frame in packet.decode():
                            if frame.width != first_meta.width or frame.height != first_meta.height:
                                frame = frame.reformat(first_meta.width, first_meta.height, "yuv420p")
                            for opacket in o_stream.encode(frame):
                                o_container.mux(opacket)
                    elif audio_out and packet.stream == i_audio:
                        for aframe in packet.decode():
                            for opacket in audio_out.encode(aframe):
                                o_container.mux(opacket)

                for opacket in o_stream.encode():
                    o_container.mux(opacket)
                if audio_out:
                    for opacket in audio_out.encode():
                        o_container.mux(opacket)

                i_container.close()
                if progress_cb:
                    progress_cb((idx + 1) / total_clips * 100, 0, 0)

            o_container.close()
            return os.path.exists(output_path) and os.path.getsize(output_path) > 0

        except Exception as e:
            logger.error(f"merge 失败: {e}")
            return False

    # -- 帧级快照 (用于预览模块) --

    def get_frame_at(self, path: str, timestamp: float = 0) -> Optional[np.ndarray]:
        """获取指定时间的帧 (返回 numpy RGB 数组, 用于 QImage/QPixmap)"""
        fd = self.extract_frame(path, timestamp)
        return fd.image if fd else None

    def get_duration(self, path: str) -> float:
        """快速获取视频时长"""
        meta = self.probe(path)
        return meta.duration if meta else 0.0

    def get_resolution(self, path: str) -> Tuple[int, int]:
        """快速获取分辨率"""
        meta = self.probe(path)
        return (meta.width, meta.height) if meta else (0, 0)


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_pyav_instance: Optional[PyAVVideoEngine] = None


def get_pyav_engine() -> PyAVVideoEngine:
    global _pyav_instance
    if _pyav_instance is None:
        _pyav_instance = PyAVVideoEngine()
    return _pyav_instance


def is_pyav_available() -> bool:
    try:
        import av
        return True
    except ImportError:
        return False
