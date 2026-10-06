"""YuE（乐）全曲生成适配层 —— 符号规划 → 可编辑谱 → 渲染整曲。

为什么值得接进画布
------------------
YuE2 的三段式（`plan() → generate_semantic() → synthesize() → decode()`）与画布
「意图磁吸卡片」天生契合：**卡片先给出意图（可编辑的旋律+和弦 ABC 谱），
用户改完再渲染成 48kHz 整曲**。这把「音乐生成」从黑盒抽卡，变成
「可编辑的乐谱规划」——正好落在本项目「语义层 / 实现层」的分层上。

执行端（按优先级探测，均可通过环境变量指定）
--------------------------------------------
1) **远程 HTTP** —— `SHIGUANG_YUE_ENDPOINT`（指向自建的 YuE 服务，见 docs）
   协议：`POST {endpoint}/plan` → `{"abc": ...}`；`POST {endpoint}/render` → `{"audio_b64": ...}`（或 audio_url）
2) **本地 CLI** —— `SHIGUANG_YUE_HOME` → `thirdparty/YuE` → `yue/`
   用 YuE 自带解释器跑 driver 脚本（调 `yue2.YuE2Pipeline`）。

⚠️ 官方硬要求：**Linux + Python 3.12 + NVIDIA GPU（≥24GB VRAM，BF16）**。
本机 RTX 4060（8GB）装不下 3B 模型 ⇒ 未配置时**诚实失败并给出配置指引**，
绝不返回占位/静音音频（与本项目「不做假效果」纪律一致）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ENV_ENDPOINT = "SHIGUANG_YUE_ENDPOINT"
_ENV_HOME = "SHIGUANG_YUE_HOME"
_DEFAULT_MODEL = "m-a-p/YuE2-3B"
# cot 取值（官方语义）：full=生成可编辑旋律+和弦；melody=旋律规划+自由伴奏（翻唱）；
# off=直接由歌词与风格生成。
COT_MODES = ("full", "melody", "off")
COT_DEFAULT = "full"


def _project_root() -> str:
    """项目根（本文件在 app/core/ai/ 下，上溯 3 层）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def _install_hint() -> str:
    """引擎不可用时的安装/配置指引（供 UI 直接展示，不猜测）。"""
    root = _project_root()
    return (
        "未检测到可用的 YuE 执行端。二选一：\n"
        "① 远程（推荐，本机显卡跑不动 3B）：自建 YuE 服务后设环境变量 "
        f"{_ENV_ENDPOINT}=http://<host>:<port>；\n"
        "② 本地：把 YuE 源码放到 "
        + " 或 ".join([
            os.path.join(root, "thirdparty", "YuE"),
            os.path.join(root, "yue"),
        ])
        + f"（或设 {_ENV_HOME} 指向引擎目录），目录下需含 examples/generate.py。\n"
        "官方要求：Linux + Python 3.12 + NVIDIA GPU ≥24GB VRAM（BF16）。"
    )


def _find_engine_home() -> Optional[str]:
    """探测本地 YuE 引擎目录（含 examples/generate.py）。"""
    root = _project_root()
    candidates = []
    env_home = os.environ.get(_ENV_HOME)
    if env_home:
        candidates.append(env_home)
    candidates += [
        os.path.join(root, "thirdparty", "YuE"),
        os.path.join(root, "yue"),
        os.path.join(os.path.expanduser("~"), "YuE"),
    ]
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "examples", "generate.py")):
            logger.info("YuE 引擎目录: %s", d)
            return d
    return None


# ── 翻唱前置：SheetSage2 旋律转录 ─────────────────────────────────────
# 官方 covers.md 的确切做法（不臆造）：
#   1) SheetSage2 与 YuE2 依赖版本不同 ⇒ **独立环境**（Python 3.10/3.11 + FFmpeg 6.1）
#   2) 转录：`.venv-sheetsage2/bin/python models/SheetSage2/infer.py source.wav
#             --output cover-score --melody-only`
#      产出 `cover-score/score.abc`：保留人声/伴奏旋律、**去掉和弦符号**
#   3) 翻唱：`.venv/bin/python examples/generate.py --request cover-request.json
#             --abc-file cover-score/score.abc --cot melody --output outputs/cover`
# 之所以 melody-only：给伴奏留出适应新风格的自由度（官方原文）。
_ENV_SHEETSAGE2 = "SHIGUANG_SHEETSAGE2_HOME"
_ENV_SHEETSAGE2_PY = "SHIGUANG_SHEETSAGE2_PYTHON"


def _find_infer_py(home: Optional[str]) -> Optional[str]:
    """在 YuE 目录下找 SheetSage2 的 infer.py（官方路径 models/SheetSage2/infer.py）。"""
    if not home:
        return None
    cand = os.path.join(home, "models", "SheetSage2", "infer.py")
    return cand if os.path.isfile(cand) else None


def _sheetsage2_python(home: Optional[str]) -> Optional[str]:
    """SheetSage2 用的解释器：优先专用环境变量 → `.venv-sheetsage2`（官方约定）。"""
    env_py = os.environ.get(_ENV_SHEETSAGE2_PY)
    if env_py and os.path.isfile(env_py):
        return env_py
    if home:
        for rel in (os.path.join(".venv-sheetsage2", "bin", "python"),
                    os.path.join(".venv-sheetsage2", "Scripts", "python.exe")):
            p = os.path.join(home, rel)
            if os.path.isfile(p):
                return p
    return None


def _transcribe_local_hint() -> str:
    root = _project_root()
    return (
        "未检测到 SheetSage2 转录环境（翻唱前置）。官方步骤：\n"
        f"① 在 YuE 目录下建独立环境：python3.11 -m venv .venv-sheetsage2\n"
        "② 下载模型到 models/SheetSage2（huggingface-cli download m-a-p/SheetSage2 --local-dir models/SheetSage2）\n"
        "③ 装依赖（torch 2.8.0/torchaudio + 该模型 requirements.txt）\n"
        f"④ 若目录不在默认位置，设 {_ENV_SHEETSAGE2_PY} 指向 .venv-sheetsage2 的 python。\n"
        f"YuE 引擎目录：{root}/thirdparty/YuE（或设 {_ENV_HOME}）"
    )


def _endpoint() -> str:
    return (os.environ.get(_ENV_ENDPOINT) or "").strip().rstrip("/")


def probe_engine() -> Dict[str, Any]:
    """探测可用执行端。返回 {available, mode, detail, transcribe, hint}，供 UI 诚实展示。

    ``transcribe`` 表示**翻唱前置**（SheetSage2 旋律转录）是否可用——与生成端独立探测，
    因为官方要求两者跑在**不同 Python 环境**，一方就绪不代表另一方就绪。
    """
    ep = _endpoint()
    if ep:
        # 远程执行端：假定同时提供 /plan /render /transcribe（由部署方实现）
        return {"available": True, "mode": "remote", "detail": ep,
                "transcribe": True, "hint": "", "transcribe_hint": ""}
    home = _find_engine_home()
    if home:
        has_tr = bool(_find_infer_py(home))
        return {"available": True, "mode": "local", "detail": home,
                "transcribe": has_tr,
                "hint": "",
                "transcribe_hint": "" if has_tr else _transcribe_local_hint()}
    return {"available": False, "mode": "", "detail": "",
            "transcribe": False,
            "hint": _install_hint(), "need": "YuE 执行端未配置",
            "transcribe_hint": _transcribe_local_hint()}


# ────────────────────────── HTTP 调用（远程执行端） ──────────────────────────

def _http_post_json(url: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    import urllib.error
    import urllib.request

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {"ok": False, "message": "远程返回非对象"}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # stability-gate: allow-swallow（读 HTTP 错误响应体只为附加诊断文本；读不到不得掩盖真正的 HTTPError）
            pass
        return {"ok": False, "message": f"远程 YuE HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"ok": False, "message": f"远程 YuE 请求失败: {e}"}


# ────────────────────────── 本地 CLI 执行端 ──────────────────────────

_PLAN_DRIVER = '''
import json, sys
from pathlib import Path
from yue2 import YuE2Pipeline
req = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
with YuE2Pipeline.from_pretrained({model!r}, device="cuda") as pipe:
    plan = pipe.plan(**req)
    plan.save(str(out))
print("YUE_OK")
'''

_RENDER_DRIVER = '''
import json, sys
from pathlib import Path
from yue2 import YuE2Pipeline
req = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
with YuE2Pipeline.from_pretrained({model!r}, device="cuda") as pipe:
    song = pipe(**req)
    song.save_artifacts(str(out))
print("YUE_OK")
'''


def _run_local(home: str, driver_tpl: str, request: Dict[str, Any],
               timeout: float) -> Dict[str, Any]:
    """在 YuE 引擎目录下跑 driver 脚本，返回输出目录内容摘要。"""
    py = sys.executable
    venv_py = os.path.join(home, ".venv", "bin", "python")
    if os.path.isfile(venv_py):
        py = venv_py
    tmp = tempfile.mkdtemp(prefix="yue_")
    req_path = os.path.join(tmp, "request.json")
    out_dir = os.path.join(tmp, "out")
    drv_path = os.path.join(tmp, "driver.py")
    with open(req_path, "w", encoding="utf-8") as f:
        json.dump(request, f, ensure_ascii=False)
    with open(drv_path, "w", encoding="utf-8") as f:
        f.write(driver_tpl.format(model=_DEFAULT_MODEL))
    try:
        r = subprocess.run(
            [py, drv_path, req_path, out_dir],
            cwd=home, capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", errors="replace")[-500:]
            return {"ok": False, "message": f"YuE 本地执行失败: {err}", "out_dir": out_dir}
        if b"YUE_OK" not in (r.stdout or b""):
            return {"ok": False, "message": "YuE 本地执行未报告成功标记", "out_dir": out_dir}
        return {"ok": True, "out_dir": out_dir}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"YuE 本地执行超时（>{int(timeout)}s）"}
    except Exception as e:
        return {"ok": False, "message": f"YuE 本地执行异常: {e}"}


def _read_abc(out_dir: str) -> str:
    """从输出目录读回 ABC 谱（score.abc，可能在子目录）。"""
    for root, _dirs, files in os.walk(out_dir):
        for fn in files:
            if fn.endswith(".abc"):
                try:
                    with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                        return f.read()
                except OSError:
                    continue
    return ""


def _read_audio(out_dir: str) -> Optional[str]:
    """从输出目录找到音频文件（flac/wav/mp3），返回路径。"""
    for root, _dirs, files in os.walk(out_dir):
        for fn in sorted(files):
            if fn.lower().endswith((".flac", ".wav", ".mp3")):
                return os.path.join(root, fn)
    return None


# ────────────────────────── 对外接口 ──────────────────────────

def _build_request(*, lyrics: str, style: str, abc: str = "",
                   cot: str = COT_DEFAULT, seed: Optional[int] = None) -> Dict[str, Any]:
    """组装 YuE 请求（字段即 YuE2 `pipe(**request)` 的关键字）。"""
    req: Dict[str, Any] = {
        "style": (style or "").strip(),
        "lyrics": (lyrics or "").strip(),
        "cot": cot if cot in COT_MODES else COT_DEFAULT,
    }
    if abc.strip():
        req["abc"] = abc
    if seed is not None:
        try:
            req["seed"] = int(seed)
        except (TypeError, ValueError):  # stability-gate: allow-swallow（seed 转 int 失败即视为「不指定种子」，请求本身仍然有效）
            pass
    return req


def plan_song(*, lyrics: str, style: str, cot: str = COT_DEFAULT,
              seed: Optional[int] = None, timeout: float = 900.0) -> Dict[str, Any]:
    """**符号规划**：歌词+风格 → 可编辑的旋律+和弦 ABC 谱（不出音频，快且省钱）。

    这正是「意图磁吸卡片」要展示的东西：先给你一张可改的谱，再谈渲染。
    """
    if not (lyrics or "").strip() and not (style or "").strip():
        return {"ok": False, "message": "歌词与风格至少填一个"}

    probe = probe_engine()
    if not probe["available"]:
        return {"ok": False, "message": probe["need"], "hint": probe["hint"],
                "engine": "yue", "unavailable": True}

    req = _build_request(lyrics=lyrics, style=style, cot=cot, seed=seed)
    if probe["mode"] == "remote":
        data = _http_post_json(f"{probe['detail']}/plan", req, timeout)
        if not data.get("ok"):
            return {"ok": False, "message": data.get("message") or "远程规划失败"}
        return {"ok": True, "abc": str(data.get("abc") or ""), "cot": req["cot"],
                "engine": "yue", "mode": "remote"}

    res = _run_local(probe["detail"], _PLAN_DRIVER, req, timeout)
    if not res.get("ok"):
        return res
    abc = _read_abc(res["out_dir"])
    if not abc:
        return {"ok": False, "message": "YuE 规划成功但未产出 score.abc"}
    return {"ok": True, "abc": abc, "cot": req["cot"], "engine": "yue", "mode": "local"}


def render_song(*, lyrics: str, style: str, abc: str = "", cot: str = COT_DEFAULT,
                seed: Optional[int] = None, title: str = "",
                bridge_port: int = 0, timeout: float = 1800.0) -> Dict[str, Any]:
    """**渲染整曲**：ABC 谱（可为用户编辑过的）→ 48kHz 立体声整曲。

    ``abc`` 为空则内部自规划；非空则按「编辑模式」渲染（YuE2 的 --abc-file 语义）。
    """
    if not (lyrics or "").strip() and not (style or "").strip():
        return {"ok": False, "message": "歌词与风格至少填一个"}

    probe = probe_engine()
    if not probe["available"]:
        return {"ok": False, "message": probe["need"], "hint": probe["hint"],
                "engine": "yue", "unavailable": True}

    req = _build_request(lyrics=lyrics, style=style, abc=abc, cot=cot, seed=seed)

    if probe["mode"] == "remote":
        data = _http_post_json(f"{probe['detail']}/render", req, timeout)
        if not data.get("ok"):
            return {"ok": False, "message": data.get("message") or "远程渲染失败"}
        audio_url = str(data.get("audio_url") or "")
        if not audio_url and data.get("audio_b64"):
            saved = _save_b64_audio(str(data["audio_b64"]), title, bridge_port)
            if not saved.get("ok"):
                return saved
            audio_url = saved["audio_url"]
        if not audio_url:
            return {"ok": False, "message": "远程渲染成功但未返回音频"}
        return {"ok": True, "audio_url": audio_url, "abc": str(data.get("abc") or abc),
                "engine": "yue", "mode": "remote"}

    res = _run_local(probe["detail"], _RENDER_DRIVER, req, timeout)
    if not res.get("ok"):
        return res
    src = _read_audio(res["out_dir"])
    if not src:
        return {"ok": False, "message": "YuE 渲染成功但未找到音频产物"}
    saved = _copy_audio_to_inbox(src, title, bridge_port)
    if not saved.get("ok"):
        return saved
    return {"ok": True, "audio_url": saved["audio_url"], "abc": _read_abc(res["out_dir"]) or abc,
            "engine": "yue", "mode": "local"}


# ────────────────────────── 翻唱前置：旋律转录 ──────────────────────────

_AUDIO_EXTS = (".wav", ".flac", ".mp3", ".m4a", ".ogg")


def _resolve_audio_input(audio: str, work_dir: str) -> Dict[str, Any]:
    """把参考曲统一成本地文件路径：data URL 落盘 / inbox URL 映射 / 本地路径校验。"""
    import base64 as _b64

    src = (audio or "").strip()
    if not src:
        return {"ok": False, "message": "缺少参考曲（audio）"}
    # 形态 1：data URL
    if src.startswith("data:"):
        try:
            blob = _b64.b64decode(src.split(",", 1)[-1], validate=False)
            if len(blob) < 1024:
                return {"ok": False, "message": "参考曲过小（疑似无效）"}
            from app.core.canvas_aigc import _canvas_inbox_dir
            inbox = _canvas_inbox_dir()
            os.makedirs(inbox, exist_ok=True)
            name = _safe_name("cover_src", ".wav")
            path = os.path.join(inbox, name)
            with open(path, "wb") as f:
                f.write(blob)
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "message": f"参考曲落盘失败: {e}"}
    # 形态 2：inbox URL（/inbox_file/<name>）→ 映射到本地
    if "/inbox_file/" in src:
        try:
            from app.core.canvas_aigc import _canvas_inbox_dir
            name = src.split("/inbox_file/", 1)[-1].split("?")[0]
            path = os.path.join(_canvas_inbox_dir(), name)
            if os.path.isfile(path):
                return {"ok": True, "path": path}
            return {"ok": False, "message": f"inbox 中找不到参考曲: {name}"}
        except Exception as e:
            return {"ok": False, "message": f"参考曲解析失败: {e}"}
    # 形态 3：本地路径
    if os.path.isfile(src):
        return {"ok": True, "path": src}
    if src.lower().endswith(_AUDIO_EXTS):
        return {"ok": False, "message": f"参考曲文件不存在: {src}"}
    return {"ok": False, "message": "参考曲需为本地路径、inbox URL 或 data URL"}


def transcribe_reference(*, audio: str, melody_only: bool = True,
                         timeout: float = 900.0) -> Dict[str, Any]:
    """**翻唱前置**：参考曲 → 旋律 ABC 谱（SheetSage2）。

    官方约定：SheetSage2 与 YuE2 依赖版本不同，跑在**独立环境**；输出 `score.abc`
    只保留旋律、**去掉和弦符号**，以便伴奏适配新风格（`melody_only=True`）。
    转录质量直接决定翻唱质量——返回的 abc 应让用户先审阅再渲染。
    """
    probe = probe_engine()
    if not probe["available"]:
        return {"ok": False, "message": probe["need"], "hint": probe["hint"],
                "engine": "yue", "unavailable": True}

    if probe["mode"] == "remote":
        data = _http_post_json(f"{probe['detail']}/transcribe",
                               {"audio": audio, "melody_only": bool(melody_only)}, timeout)
        if not data.get("ok"):
            return {"ok": False, "message": data.get("message") or "远程转录失败"}
        abc = str(data.get("abc") or "")
        if not abc:
            return {"ok": False, "message": "远程转录成功但未返回乐谱"}
        return {"ok": True, "abc": abc, "cot": "melody", "engine": "yue", "mode": "remote"}

    # 本地：需要 SheetSage2 独立环境
    home = probe["detail"]
    infer_py = _find_infer_py(home)
    if not infer_py:
        return {"ok": False, "message": "SheetSage2 转录环境未就绪",
                "hint": _transcribe_local_hint(), "unavailable": True, "engine": "yue"}
    py = _sheetsage2_python(home)
    if not py:
        return {"ok": False, "message": "未找到 SheetSage2 的 python（.venv-sheetsage2）",
                "hint": _transcribe_local_hint(), "unavailable": True, "engine": "yue"}

    tmp = tempfile.mkdtemp(prefix="yue_cover_")
    resolved = _resolve_audio_input(audio, tmp)
    if not resolved.get("ok"):
        return resolved
    out_dir = os.path.join(tmp, "cover-score")
    cmd = [py, infer_py, resolved["path"], "--output", out_dir]
    if melody_only:
        cmd.append("--melody-only")
    try:
        r = subprocess.run(
            cmd, cwd=home, capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if r.returncode != 0:
            err = (r.stderr or b"").decode("utf-8", errors="replace")[-500:]
            return {"ok": False, "message": f"SheetSage2 转录失败: {err}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"SheetSage2 转录超时（>{int(timeout)}s）"}
    except Exception as e:
        return {"ok": False, "message": f"SheetSage2 转录异常: {e}"}

    abc = _read_abc(out_dir)
    if not abc:
        return {"ok": False, "message": "转录完成但未产出 score.abc（请检查转录告警）"}
    return {"ok": True, "abc": abc, "cot": "melody", "engine": "yue", "mode": "local"}


# ────────────────────────── 音频落盘（复用画布 inbox） ──────────────────────────

def _inbox_url(name: str, bridge_port: int) -> str:
    from app.core.canvas_bridge import DEFAULT_PORT
    port = int(bridge_port) or int(DEFAULT_PORT)
    return f"http://127.0.0.1:{port}/inbox_file/{name}"


def _safe_name(title: str, ext: str) -> str:
    import hashlib
    import time as _t
    base = (title or "yue").strip().replace("/", "_").replace("\\", "_")[:40]
    stamp = _t.strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha1(f"{base}{stamp}{os.getpid()}".encode("utf-8")).hexdigest()[:6]
    return f"yue_{base}_{stamp}_{h}{ext}"


def _copy_audio_to_inbox(src_path: str, title: str, bridge_port: int) -> Dict[str, Any]:
    import shutil
    from app.core.canvas_aigc import _canvas_inbox_dir

    ext = os.path.splitext(src_path)[1].lower() or ".flac"
    name = _safe_name(title, ext)
    try:
        inbox = _canvas_inbox_dir()
        os.makedirs(inbox, exist_ok=True)
        dest = os.path.join(inbox, name)
        shutil.copy2(src_path, dest)
        if os.path.getsize(dest) < 1024:
            return {"ok": False, "message": "YuE 音频产物过小（疑似无效）"}
        return {"ok": True, "audio_url": _inbox_url(name, bridge_port), "path": dest}
    except Exception as e:
        return {"ok": False, "message": f"音频落盘失败: {e}"}


def _save_b64_audio(b64: str, title: str, bridge_port: int) -> Dict[str, Any]:
    from app.core.canvas_aigc import _canvas_inbox_dir

    name = _safe_name(title, ".flac")
    try:
        blob = base64.b64decode(b64.split(",")[-1], validate=False)
        if len(blob) < 1024:
            return {"ok": False, "message": "远程音频过小（疑似无效）"}
        inbox = _canvas_inbox_dir()
        os.makedirs(inbox, exist_ok=True)
        dest = os.path.join(inbox, name)
        with open(dest, "wb") as f:
            f.write(blob)
        return {"ok": True, "audio_url": _inbox_url(name, bridge_port), "path": dest}
    except Exception as e:
        return {"ok": False, "message": f"远程音频落盘失败: {e}"}
