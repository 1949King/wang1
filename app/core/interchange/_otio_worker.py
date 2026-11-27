"""OTIO 转换子进程 worker（**主进程不得 import 本模块**）。

为什么必须独立进程（2026-10-11 PyQt6 时代实测）
------------------------------------
``import PyQt6.QtCore, opentimelineio`` → **段错误**（access violation）；
``import opentimelineio, PyQt6.QtCore``（反序）→ 正常。
即 opentimelineio 的 C 扩展在 Qt 之后加载会崩。迁移 PySide6 后未据此假设冲突消失，
所有 OTIO 读写仍在**无 Qt 的子进程**里完成（本项目一贯做法：wmic / ffmpeg 同理隔离）。

用法::

    python -m app.core.interchange._otio_worker export <canonical.json> <out> [adapter]
    python -m app.core.interchange._otio_worker import <in_path> <canonical.json> [adapter]
    python -m app.core.interchange._otio_worker formats
"""
from __future__ import annotations

import json
import sys


def _usage() -> int:
    print(  # stability-gate: allow-print（子进程 worker：用法错误走 stderr，主进程按 rc 判失败）
        "usage: export <canonical.json> <out> [adapter] | "
        "import <in> <canonical.json> | formats",
        file=sys.stderr,
    )
    return 2


def main(argv) -> int:
    if len(argv) < 2:
        return _usage()
    mode = argv[1]

    # 本进程无 Qt，先 import otio 是安全的（且必须在使用前完成）
    import opentimelineio as otio

    from app.core.interchange import otio_adapter as adapter_mod
    from app.core.timeline_dsl import Timeline

    if mode == "formats":
        payload = json.dumps(sorted(otio.adapters.available_adapter_names()))
        print(payload)  # stability-gate: allow-print（stdout 即主进程返回通道）
        return 0

    if mode == "export":
        if len(argv) < 4:
            return _usage()
        src, dst = argv[2], argv[3]
        name = argv[4] if len(argv) > 4 else None
        with open(src, "r", encoding="utf-8") as fh:
            timeline = Timeline.from_json(fh.read())
        adapter_mod.write_inprocess(timeline, dst, adapter=name)
        return 0

    if mode == "import":
        if len(argv) < 4:
            return _usage()
        src, dst = argv[2], argv[3]
        name = argv[4] if len(argv) > 4 else None
        timeline = adapter_mod.read_inprocess(src, adapter=name)
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(timeline.to_json())
        return 0

    print(f"unknown mode: {mode}", file=sys.stderr)  # stability-gate: allow-print（stderr 报错通道）
    return _usage()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
