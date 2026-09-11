# -*- coding: utf-8 -*-
"""把 canvas_bridge.py 的 AIGC / 模型配置 / 分镜层抽到 canvas_aigc.py（大文件治理）。

从 canvas_bridge.py 三个连续区段抽出：
  - 关键词常量 VIDEO/AUDIO/IMAGE_KEYWORDS             (155-197)
  - guess_capability + build_host_ai_config_patch      (808-1073，模型广场渠道配置)
  - _data_url_to_b64 / 生图 / inpaint / 生音频 / 生视频 / 生音乐 / 分镜 (1145-2907)

依赖处理：
  - AIGC 生成函数把产物写到 canvas_bridge.canvas_inbox_dir()，但直接 import 会造成
    循环导入（canvas_bridge 顶部 re-export 本模块）。因此在本模块提供
    _canvas_inbox_dir() 惰性代理，调用时再 import canvas_bridge。

原文件 re-export 保持向后兼容；_BridgeHandler / CanvasBridgeServer 不动。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "core" / "canvas_bridge.py"
DST = ROOT / "app" / "core" / "canvas_aigc.py"

text = SRC.read_text(encoding="utf-8")
newline = "\r\n" if "\r\n" in text else "\n"
lines = text.splitlines(keepends=True)


def block(a: int, b: int):
    """1-based，闭区间。"""
    return lines[a - 1 : b]


kw = block(155, 197)       # VIDEO/AUDIO/IMAGE_KEYWORDS
config = block(808, 1073)  # guess_capability + build_host_ai_config_patch
aigc = block(1145, 2907)   # _data_url_to_b64 .. storyboard_breakdown

# 抽出的 AIGC 代码里引用 canvas_inbox_dir()，替换为本地惰性代理，避免循环导入
aigc_text = "".join(aigc)
aigc_text = aigc_text.replace("canvas_inbox_dir()", "_canvas_inbox_dir()")

header = (
    "# -*- coding: utf-8 -*-\n"
    '"""画布桥 AIGC 层：模型广场渠道配置、生图/生视频/生音频/生音乐、分镜拉片。\n'
    "\n"
    "从 canvas_bridge.py 拆分而来（大文件治理）。自研导演台 /host/* 暴露的所有 AI\n"
    "能力集中于此。画布 HTTP 服务（_BridgeHandler / CanvasBridgeServer）仍留在\n"
    "canvas_bridge.py，并通过 re-export 引用本模块。\n"
    "\n"
    "端口冻结约束（stage3d-core）仍以 canvas_bridge.py 为准：本模块 DEFAULT_PORT 仅作\n"
    "默认值镜像，不得单独改动端口 18765。\n"
    '"""\n'
    "from __future__ import annotations\n"
    "\n"
    "import json\n"
    "import logging\n"
    "import os\n"
    "import re\n"
    "import time\n"
    "from typing import Any, Dict, List, Optional, Tuple\n"
    "\n"
    'logger = logging.getLogger("AI短剧编辑器.canvas_bridge")\n'
    "\n"
    "# 与 canvas_bridge.DEFAULT_PORT 保持一致（stage3d-core 冻结：端口 18765 不得更改）\n"
    "DEFAULT_PORT = 18765\n"
    "\n"
    "\n"
    "def _canvas_inbox_dir() -> str:\n"
    '    """画布收件目录（惰性取 canvas_bridge.canvas_inbox_dir，拆模块后避免循环导入）。"""\n'
    "    from app.core.canvas_bridge import canvas_inbox_dir\n"
    "\n"
    "    return canvas_inbox_dir()\n"
    "\n"
    "\n"
).replace("\n", newline)

body = header + "".join(kw) + newline + newline + "".join(config) + newline + newline + aigc_text
DST.write_text(body, encoding="utf-8")

# 从 canvas_bridge.py 删除这三段
keep = []
removed = 0
for i, line in enumerate(lines, start=1):
    if 155 <= i <= 197 or 808 <= i <= 1073 or 1145 <= i <= 2907:
        removed += 1
        continue
    keep.append(line)

re_export = (
    "# AIGC / 模型配置 / 分镜层已拆到 canvas_aigc.py，此处 re-export 保持向后兼容\n"
    "from app.core.canvas_aigc import (\n"
    "    VIDEO_KEYWORDS,\n"
    "    AUDIO_KEYWORDS,\n"
    "    IMAGE_KEYWORDS,\n"
    "    guess_capability,\n"
    "    build_host_ai_config_patch,\n"
    "    _data_url_to_b64,\n"
    "    generate_image_openai_compatible,\n"
    "    inpaint_via_host,\n"
    "    _resolve_aigc_channel,\n"
    "    generate_audio_via_host,\n"
    "    agent_chat_proxy,\n"
    "    generate_video_via_host,\n"
    "    generate_music_via_host,\n"
    "    _parse_storyboard_json,\n"
    "    _heuristic_storyboard,\n"
    "    storyboard_breakdown,\n"
    ")\n"
    "\n"
).replace("\n", newline)

out = []
inserted = False
for line in keep:
    out.append(line)
    if not inserted and line.rstrip("\r\n") == "from urllib.parse import parse_qs, urlparse":
        out.append(re_export)
        inserted = True

SRC.write_text("".join(out), encoding="utf-8")
print(f"newline={newline!r}")
print(f"removed {removed} lines from canvas_bridge.py")
print(f"canvas_aigc.py written with {len(body.splitlines())} lines")