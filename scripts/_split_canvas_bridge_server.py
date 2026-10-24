# -*- coding: utf-8 -*-
"""把 canvas_bridge.py 的 HTTP 服务层抽到 canvas_server.py（大文件治理）。

拆分边界（按 server / IO 职责）：
  - 保留在 canvas_bridge.py：状态全局 + IO/媒体层（canvas_inbox_dir / ingest_local_file /
    emit_canvas_to_editor / agent 事件总线 / 插件 manifest / 拼接等，L1-862）。
  - 迁到 canvas_server.py：`def _check_host_token` 起，含提示词 remote 代理、
    `_BridgeHandler`（do_GET/do_POST/_handle_ingest/SSE）、`_build_inject_js`、
    `CanvasBridgeServer`、`get_canvas_bridge`（L863-末尾）。

依赖方向严格单向：canvas_server → canvas_bridge + canvas_aigc。
  - canvas_server 顶部 `from app.core.canvas_bridge import (...)` 引用 IO 层符号；
    canvas_bridge 末尾再 re-export canvas_server，形成“文件尾部 re-export”闭包，
    避免循环导入（canvas_bridge 在其自身 import 尚未走到 re-export 行前，已将全部
    IO 符号定义完备，canvas_server 此刻 import 到的是已部分初始化但符号齐全的模块）。

端口冻结约束（stage3d-core）：DEFAULT_PORT 仍在 canvas_bridge.py（18765 不得更改），
本模块仅 import 该常量，不在 canvas_server.py 重新定义端口。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "core" / "canvas_bridge.py"
DST = ROOT / "app" / "core" / "canvas_server.py"

text = SRC.read_text(encoding="utf-8")
newline = "\r\n" if "\r\n" in text else "\n"
lines = text.splitlines(keepends=True)

# 定位 HTTP 服务层起点：def _check_host_token(...)
split_idx = None
for i, line in enumerate(lines):
    if line.lstrip().startswith("def _check_host_token("):
        split_idx = i
        break
if split_idx is None:
    raise SystemExit("未找到 def _check_host_token 边界，中止")

io_lines = lines[:split_idx]
server_body = "".join(lines[split_idx:])

# ── canvas_server.py 头部：标准库 + canvas_aigc + canvas_bridge（IO 层）引用 ──
header = (
    "# -*- coding: utf-8 -*-\n"
    '"""画布桥 HTTP 服务层：本地小 HTTP 桥（_BridgeHandler / CanvasBridgeServer）。\n'
    "\n"
    "从 canvas_bridge.py 拆分而来（大文件治理）。自研导演台 /host/*、/ingest、/ingest_path、\n"
    "/push_from_editor、/inbox_file、/editor_outbox、/inject.js 等 HTTP 端点与 SSE 事件流全部弘中于此。\n"
    "\n"
    "IO / 状态 / 媒体层（canvas_inbox_dir、ingest_local_file、emit_canvas_to_editor、agent 事件\n"
    "总线、插件 manifest、FFmpeg 拼接等）仍留在 canvas_bridge.py；AIGC 生成能力在 canvas_aigc.py。\n"
    "本模块顶部 import 引用它们，canvas_bridge.py 末尾 re-export 本模块以保持向后兼容。\n"
    "\n"
    "端口冻结约束（stage3d-core）：DEFAULT_PORT 以 canvas_bridge.py 为准（18765 不得更改），\n"
    "本模块仅引用该常量，不单独定义端口。\n"
    '"""\n'
    "from __future__ import annotations\n"
    "\n"
    "import hashlib\n"
    "import json\n"
    "import logging\n"
    "import os\n"
    "import queue\n"
    "import threading\n"
    "import threading as _threading\n"
    "import time\n"
    "import uuid\n"
    "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
    "from pathlib import Path\n"
    "from typing import Any, Dict, List, Optional, Tuple\n"
    "from urllib.parse import parse_qs, urlparse\n"
    "\n"
    "from app.core.canvas_aigc import (\n"
    "    agent_chat_proxy,\n"
    "    build_host_ai_config_patch,\n"
    "    generate_audio_via_host,\n"
    "    generate_image_openai_compatible,\n"
    "    generate_music_via_host,\n"
    "    generate_video_via_host,\n"
    "    inpaint_via_host,\n"
    "    storyboard_breakdown,\n"
    ")\n"
    "from app.core.canvas_bridge import (\n"
    "    DEFAULT_HOST,\n"
    "    DEFAULT_PORT,\n"
    "    _BUILTIN_PLUGIN_REGISTRY,\n"
    "    _BATCH_JOBS,\n"
    "    _BATCH_LOCK,\n"
    "    _BRIDGE_PREFS,\n"
    "    _EVT_REPLY_LOCK,\n"
    "    _EVT_REPLY_QUEUES,\n"
    "    _EVT_SUBS,\n"
    "    _EVT_SUBS_LOCK,\n"
    "    _SESSION_TOKEN,\n"
    "    _load_canvas_plugins_manifest,\n"
    "    _probe_duration,\n"
    "    _remove_canvas_plugin,\n"
    "    _run_concat_demuxer,\n"
    "    _run_concat_xfade,\n"
    "    _safe_filename,\n"
    "    _toggle_canvas_plugin_enabled,\n"
    "    _upsert_canvas_plugin,\n"
    "    broadcast_agent_event,\n"
    "    canvas_inbox_dir,\n"
    "    canvas_outbox_dir,\n"
    "    get_timeline_snapshot,\n"
    "    ingest_local_file,\n"
    "    list_editor_outbox,\n"
    "    make_agent_event,\n"
    "    push_editor_to_canvas,\n"
    "    replay_agent_events,\n"
    ")\n"
    "\n"
    'logger = logging.getLogger("AI短剧编辑器.canvas_bridge")\n'
)

canvas_server = header.replace("\n", newline) + newline + newline + server_body
DST.write_text(canvas_server, encoding="utf-8")

# ── canvas_bridge.py：保留 IO 层 + 末尾 re-export canvas_server ──
re_export = (
    "# HTTP 服务层（_BridgeHandler / CanvasBridgeServer / inject.js）已拆到 canvas_server.py，此处 re-export 保持向后兼容\n"
    "from app.core.canvas_server import (\n"
    "    _check_host_token,\n"
    "    _BridgeHandler,\n"
    "    _build_inject_js,\n"
    "    CanvasBridgeServer,\n"
    "    get_canvas_bridge,\n"
    ")\n"
)

io_text = "".join(io_lines).rstrip("\r\n")
new_canvas_bridge = io_text + newline + newline + re_export.replace("\n", newline) + newline
SRC.write_text(new_canvas_bridge, encoding="utf-8")

print(f"newline={newline!r}")
print(f"canvas_bridge.py: {len(lines)} -> {len(new_canvas_bridge.splitlines())} 行")
print(f"canvas_server.py: {len(canvas_server.splitlines())} 行")
print(f"迁移 {len(server_body.splitlines())} 行到 canvas_server.py")