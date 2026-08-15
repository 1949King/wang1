#!/usr/bin/env python3
"""OpenShot FFmpegReader bridge — 独立子进程，用 libopenshot FFmpegReader 解码视频帧。

父进程（项目 venv Python 3.12）通过 stdin/stdout JSON line 协议发命令，
本进程 FFmpegReader 解码出 openshot.Frame，用 JPEG 导出到临时文件交付。

协议：
  {"cmd":"open", "path":"D:/foo.mp4"}
  -> {"ok":true, "info":{"width":1920,"height":1080,"fps":30.0,
                         "duration":12.3,"frame_count":369}}

  {"cmd":"read_frame", "frame_num":42, "scale":1.0, "fmt":"JPEG", "quality":85}
  -> {"ok":true, "frame_num":42, "path":"C:/tmp/osh_xxx.jpg",
      "width":1920, "height":1080}

  {"cmd":"close"} / {"cmd":"quit"} / EOF
  -> {"ok":true} 后退出

默认 JPEG quality=85 + scale=1.0：1280x720 约 100-200KB/帧，远快于 PNG。
"""

import json
import os
import sys
import tempfile
import traceback

_bin_in = sys.stdin.buffer
_bin_out = sys.stdout.buffer


def _resp(obj):
    line = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
    _bin_out.write(line)
    _bin_out.flush()


for _p in (
    "/ucrt64/python",
    "C:/msys64/ucrt64/python",
    r"C:\msys64\ucrt64\python",
):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
        break

try:
    import openshot
except Exception as e:
    _resp({"fatal": f"import openshot failed: {e}"})
    sys.exit(1)

_TMP_DIR = tempfile.gettempdir()
_PID = os.getpid()
_PREFIX = f"osh_{_PID}_"
_reader = None
_video_info = {}
_last_frame_path = None


def _cleanup_last():
    """删除上一帧临时文件，避免磁盘堆积。"""
    global _last_frame_path
    if _last_frame_path and os.path.exists(_last_frame_path):
        try:
            os.remove(_last_frame_path)
        except OSError:
            pass
    _last_frame_path = None


def _extract_info(reader):
    info = reader.info
    fps_num = info.fps.num if hasattr(info.fps, "num") else 30
    fps_den = info.fps.den if hasattr(info.fps, "den") else 1
    fps = float(fps_num) / float(fps_den) if fps_den else 30.0
    return {
        "width": info.width,
        "height": info.height,
        "fps": fps,
        "duration": info.duration,
        "frame_count": int(getattr(info, "video_length", 0)) or int(getattr(info, "file_length", 0)),
        "has_audio": bool(info.has_audio),
        "codec": getattr(info, "vcodec", "") or "",
    }


def _handle_open(path):
    global _reader, _video_info
    try:
        if _reader is not None:
            try:
                _reader.Close()
            except Exception:
                pass
        _reader = openshot.FFmpegReader(path, 0)
        _reader.Open()
        if not _reader.IsOpen():
            _reader = None
            _resp({"ok": False, "error": f"FFmpegReader.Open failed: {path}"})
            return
        _video_info = _extract_info(_reader)
        _resp({"ok": True, "info": _video_info})
    except Exception as e:
        _reader = None
        _resp({"ok": False, "error": str(e), "trace": traceback.format_exc()})


def _handle_read_frame(frame_num, scale=1.0, fmt="JPEG", quality=85):
    global _reader, _last_frame_path
    try:
        if _reader is None:
            _resp({"ok": False, "error": "reader not opened"})
            return
        if frame_num < 0:
            frame_num = 0
        fc = _video_info.get("frame_count", 0)
        if fc > 0 and frame_num >= fc:
            frame_num = fc - 1
        frame = _reader.GetFrame(frame_num)
        if frame is None:
            _resp({"ok": False, "error": f"GetFrame returned None at {frame_num}"})
            return

        _cleanup_last()
        ext = "jpg" if fmt.upper() in ("JPEG", "JPG") else "png"
        fname = f"{_PREFIX}{frame_num}.{ext}"
        fpath = os.path.join(_TMP_DIR, fname)
        frame.Save(fpath, float(scale), fmt.upper(), int(quality))
        _last_frame_path = fpath

        w = int(frame.GetWidth() * scale)
        h = int(frame.GetHeight() * scale)
        _resp({
            "ok": True,
            "frame_num": frame_num,
            "path": fpath,
            "width": w,
            "height": h,
        })
    except Exception as e:
        _resp({"ok": False, "error": str(e), "trace": traceback.format_exc()})


def _handle_close():
    global _reader, _video_info
    try:
        if _reader is not None:
            _reader.Close()
    except Exception:
        pass
    _reader = None
    _video_info = {}
    _cleanup_last()
    _resp({"ok": True})


def main():
    _resp({"hello": True, "openshot_version": openshot.OPENSHOT_VERSION_FULL, "pid": _PID})
    for raw in _bin_in:
        try:
            line = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            _resp({"ok": False, "error": f"invalid JSON: {line[:80]}"})
            continue
        cmd = msg.get("cmd", "")
        if cmd == "ping":
            _resp({"ok": True, "pong": True})
        elif cmd == "open":
            _handle_open(msg.get("path", ""))
        elif cmd == "read_frame":
            _handle_read_frame(
                int(msg.get("frame_num", 0)),
                float(msg.get("scale", 1.0)),
                str(msg.get("fmt", "JPEG")),
                int(msg.get("quality", 85)),
            )
        elif cmd == "close":
            _handle_close()
        elif cmd in ("quit", "exit"):
            _handle_close()
            _resp({"ok": True, "bye": True})
            break
        elif cmd == "info":
            _resp({"ok": True, "info": _video_info})
        else:
            _resp({"ok": False, "error": f"unknown cmd: {cmd}"})


if __name__ == "__main__":
    main()
