# -*- coding: utf-8 -*-
"""诊断事件与诊断包 —— 让用户发回来的日志能直接定位到「改哪一行」（P0 · 2026-11-04）

为什么要这个文件
================
用户报「我这边卡住了」，这句话对开发者零价值。要定位，日志里必须同时有三样：

    **哪一类问题**（码）· **哪一行**（site）· **当时的现场**（ctx）

本项目已有 ``exceptions.ErrorCode``（60 个码，按故障域分），但全库只用了 23 处，
且集中在 7 个基础设施模块 —— ``neural`` / ``team`` / ``canvas`` / ``editor`` 一条业务链都没接。
原因不是码不够细，是**接入成本太高**：要求每个 except 手写一行，几千个点，一定半途而废。

所以本文件的设计原则是**三层拆开、各按各的成本模型**：

    码   ``E0201`` 等 30 个   —— 手写，**按故障域分，不按功能分**。功能会加会删，故障域稳定。
    site ``module.func:123``  —— **自动**，从 traceback / inspect 取。数量无限但零维护。
    ctx  ``{"vram_gb": 8, ...}`` —— **自动**，调用方只传业务字段。

「每个功能都有覆盖」靠**全局钩子**实现，不是靠逐点手写：

    ``install_hooks()`` 一装，任何未捕获异常（主线程 / 子线程 / Qt 槽 / logger.error）
    自动带 site + ctx 落盘。业务代码一行不用改。

真正需要手写的只有**钩子抓不到的「状态事件」**（不是异常，是状态转移）：

    diag.event("E0202", msg="显存不足已降级", vram_gb=8, need_gb=12)

落盘格式与位置（这两个坑必须先避开，见 ``_default_log_dir``）
============================================================
· **JSONL 而不是文本行** —— 只有结构化才能做「同一 site 一周出现几次」的聚合。
· **%LOCALAPPDATA% 而不是 cwd** —— 打包成 exe 后 cwd 可能是 ``C:\\Program Files\\...``，
  没有写权限，``log_manager.py:128`` 现在就是 ``Path.cwd() / "logs"``，日志会静默丢失。
· **没有敏感内容** —— 诊断包要能直接发给开发者，所以路径脱敏、提示词只留长度与哈希、
  素材内容一律不进包。这条是硬约束，见 ``_scrub``。

诚实说明
========
· 本模块**不猜**：拿不到的现场信息一律写 ``"unknown"``，不填默认值。填了默认值比没有更坏，
  因为它会让人以为「测出来了」。
· ``make_bundle`` 只打包**已经落盘的东西**，不做任何"补采"。收不到就是收不到，如实反映。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import sys
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 码表 —— 按故障域分，不按功能分（30 个封顶）
# 每条：(码, 用户能看懂的一句话, 开发者该先看哪里)
# ═══════════════════════════════════════════════════════════════════

CODES: Dict[str, Dict[str, str]] = {
    # ── E01x 启动与环境 ──
    "E0101": {"user": "缺少运行库或依赖，软件没起来", "dev": "检查 requirements / 打包是否漏收模块"},
    "E0102": {"user": "显卡驱动或 CUDA 版本对不上", "dev": "核对驱动版本与 torch 编译版本"},
    "E0103": {"user": "模型文件缺失或损坏", "dev": "校验模型清单与文件哈希"},
    "E0104": {"user": "没有权限读写数据目录", "dev": "检查安装路径是否在 Program Files"},
    "E0105": {"user": "软件启动过程中意外退出", "dev": "看 boot 阶段最后一条 site"},
    # ── E02x 显存与算力 ──
    "E0201": {"user": "显存不够，这个任务跑不了", "dev": "看 ctx.vram_gb / need_gb，决定降档还是拒绝"},
    "E0202": {"user": "显存紧张，已自动降级", "dev": "降级是否影响画质，考虑提示用户"},
    "E0203": {"user": "这张显卡不支持这个功能", "dev": "核对 compute capability 与后端要求"},
    "E0204": {"user": "算力被别的程序占满了", "dev": "看 ctx 里同时运行的模型数"},
    # ── E03x 模型与推理 ──
    "E0301": {"user": "模型加载失败", "dev": "看 ctx.model / 量化格式是否匹配"},
    "E0302": {"user": "生成结果是坏的（全黑/花屏/NaN）", "dev": "先查量化配方与 PSNR，见 vram_ledger 台账"},
    "E0303": {"user": "生成超时了", "dev": "看 ctx.steps / 分辨率 / 实际耗时"},
    "E0304": {"user": "提示词或参数不被这个模型接受", "dev": "核对参数白名单"},
    # ── E04x 画布与前端 ──
    "E0401": {"user": "画布页面没加载出来", "dev": "查静态服务兜底是否返回了 HTML 而非 JS"},
    "E0402": {"user": "界面和后台断开了", "dev": "查桥接端口与心跳"},
    "E0403": {"user": "有个资源找不到了", "dev": "查 404 的实际 URL，注意 SPA 兜底会返 200+HTML"},
    "E0404": {"user": "界面上的操作没生效", "dev": "查前端异常与 SSE 通道"},
    # ── E05x 生成任务 ──
    "E0501": {"user": "任务排队太久", "dev": "看并发数与队列深度"},
    "E0502": {"user": "任务中途被打断了", "dev": "区分用户取消 / 崩溃 / 被抢占"},
    "E0503": {"user": "生成的文件打不开", "dev": "查封装容器与编码器"},
    # ── E06x 团队协作 ──
    "E0601": {"user": "连不上团队服务器", "dev": "错误码翻人话见 friendly_socket_error，先排除防火墙"},
    "E0602": {"user": "你的改动和别人的撞了", "dev": "正常冲突，看 base_rev 与 diff"},
    "E0603": {"user": "你没有这个权限", "dev": "核对 role 与 allow_role"},
    "E0604": {"user": "团队人数已满", "dev": "看席位上限与 viewer 是否豁免"},
    # ── E07x 导出与文件 ──
    "E0701": {"user": "导出编码失败", "dev": "查 ffmpeg 可用性与参数"},
    "E0702": {"user": "磁盘空间不够了", "dev": "看 ctx.free_gb 与预计大小"},
    "E0703": {"user": "保存路径不合法", "dev": "查路径长度、非法字符、只读介质"},
}


# ═══════════════════════════════════════════════════════════════════
# 落盘位置
# ═══════════════════════════════════════════════════════════════════

def _default_log_dir() -> Path:
    """诊断日志目录（**绝不用 cwd**）。

    打包成 exe 后被双击时 cwd 可能是 ``C:\\Program Files\\...``，不可写 ——
    ``log_manager.py:128`` 的 ``Path.cwd() / "logs"`` 就是这个坑。
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "ShiguangJianying" / "logs"
    return Path.home() / ".shiguang_jianying" / "logs"


# ═══════════════════════════════════════════════════════════════════
# 脱敏 —— 诊断包要能直接发给开发者
# ═══════════════════════════════════════════════════════════════════

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._\-]{10,}"
    r"|api[_-]?key\s*[=:]\s*\S+|token\s*[=:]\s*\S+)",
    re.IGNORECASE,
)
_WIN_USER_RE = re.compile(r"([A-Za-z]:\\Users\\)([^\\]+)", re.IGNORECASE)
_POSIX_USER_RE = re.compile(r"(/home/)([^/]+)")


def _scrub(text: str) -> str:
    """擦掉密钥 + 把用户名换成 <user>。路径只保留形态，不保留身份。"""
    if not text:
        return text
    out = _SECRET_RE.sub("<redacted>", text)
    out = _WIN_USER_RE.sub(r"\1<user>", out)
    out = _POSIX_USER_RE.sub(r"\1<user>", out)
    return out


def prompt_fingerprint(prompt: str) -> Dict[str, Any]:
    """提示词不进日志，只留「长度 + 哈希前 8 位」。

    提示词里常有未公开的商业信息（甲方 NDA），原文绝不能进诊断包；
    但「是不是同一条提示词反复失败」需要能比对 —— 哈希就够。
    """
    if not prompt:
        return {"len": 0, "sha8": ""}
    return {"len": len(prompt), "sha8": hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]}


# ═══════════════════════════════════════════════════════════════════
# 会话与环境快照
# ═══════════════════════════════════════════════════════════════════

_SID = uuid.uuid4().hex[:12]
_MONO0 = time.monotonic()
_LOCK = threading.RLock()
_BUF: List[Dict[str, Any]] = []
_MEM_MAX = 500
_LOG_PATH: Optional[Path] = None
_ENV: Dict[str, Any] = {}


def _vram_probe() -> Any:
    """探测显存总量（GB）。拿不到就 ``"unknown"`` —— 不猜。"""
    try:
        # torch 故意延迟导入：顶层导入会拖慢启动，且沙箱/无卡机器上可能根本装不上
        import torch

        if not torch.cuda.is_available():
            return "unknown"
        total = torch.cuda.get_device_properties(0).total_memory
        return round(total / (1024 ** 3), 1)
    except Exception:
        # 诊断自身失败绝不能反过来把主程序搞崩 / 也绝不填默认值冒充"测到了"
        return "unknown"


def _gpu_name() -> str:
    try:
        import torch

        if not torch.cuda.is_available():
            return "unknown"
        return str(torch.cuda.get_device_name(0))
    except Exception:
        return "unknown"


def env_snapshot() -> Dict[str, Any]:
    """环境快照 —— 只采一次，之后每条事件引用同一个 sid。

    不采就不会知道「用户那边是什么环境」；一次一次采会把日志撑爆。
    """
    global _ENV
    with _LOCK:
        if _ENV:
            return _ENV
        info: Dict[str, Any] = {
            "sid": _SID,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "os": platform.platform(),
            "python": platform.python_version(),
            "arch": platform.machine(),
            "gpu": _gpu_name(),
            "vram_gb": _vram_probe(),
        }
        try:
            from app.version import __version__

            info["app_version"] = __version__
        except Exception:
            info["app_version"] = "unknown"
        _ENV = info
        return _ENV


# ═══════════════════════════════════════════════════════════════════
# 写事件
# ═══════════════════════════════════════════════════════════════════

def _ensure_log() -> Optional[Path]:
    """惰性打开当日日志。失败就返回 None（诊断不能反过来把主程序搞崩）。"""
    global _LOG_PATH
    if _LOG_PATH is not None:
        return _LOG_PATH
    try:
        d = _default_log_dir()
        d.mkdir(parents=True, exist_ok=True)
        _LOG_PATH = d / ("diag_%s.jsonl" % time.strftime("%Y%m%d"))
        return _LOG_PATH
    except Exception:
        logger.debug("诊断日志目录不可写：%s", _default_log_dir(), exc_info=True)
        return None


def _site_of(depth: int = 2) -> str:
    """自动取调用点 ``module.func:line`` —— 这是「定位到哪一行」的来源，零维护。"""
    try:
        frame = sys._getframe(depth)
        fn = frame.f_code.co_filename
        name = os.path.basename(fn)
        return "%s:%s:%d" % (os.path.splitext(name)[0], frame.f_code.co_name, frame.f_lineno)
    except Exception:
        return "unknown"


def _frame_site(tb: Any) -> Optional[str]:
    """从 traceback 里取**真正出错的那一帧**（最后一帧）。

    为什么不能直接用 ``_site_of``：钩子由异常触发，``_site_of`` 取到的是
    ``diagnostics:_thook:370`` —— 钩子自己的位置，对定位用户代码毫无用处。
    这里沿 ``tb_next`` 走到最后一帧，那才是真正抛异常的用户代码。
    """
    try:
        last = None
        while tb is not None:
            last = tb
            tb = tb.tb_next
        if last is None:
            return None
        fn = last.tb_frame.f_code
        return "%s:%s:%d" % (
            os.path.splitext(os.path.basename(fn.co_filename))[0],
            fn.co_name,
            last.tb_lineno,
        )
    except Exception:
        return None


def event(code: str, msg: str = "", level: str = "info",
          _site: Optional[str] = None, **ctx: Any) -> Dict[str, Any]:
    """记一条诊断事件。**这是唯一入口**，不要在别处手写 json.dump。

    :param code: ``CODES`` 里的码（如 ``E0201``）。未登记的码照记，但会标 ``unknown_code``
                 —— 宁可留下原始信息，也不要因为码表没更新就丢掉现场。
    :param msg:  一句话说明。会脱敏。
    :param level: info / warn / error
    :param _site: 内部用：钩子从 traceback 算出的真实出错点。业务代码不要传。
    :param ctx:  业务现场字段（vram_gb / model / steps ...），自动脱敏
    """
    rec: Dict[str, Any] = {
        "t": round(time.monotonic() - _MONO0, 3),
        "ts": time.strftime("%H:%M:%S"),
        "sid": _SID,
        "lvl": level,
        "code": code,
        "site": _site or _site_of(2),
        "msg": _scrub(str(msg)),
    }
    if code not in CODES:
        rec["unknown_code"] = True
    if ctx:
        try:
            rec["ctx"] = json.loads(_scrub(json.dumps(ctx, ensure_ascii=False, default=str)))
        except Exception:
            rec["ctx"] = {"_unserializable": True}

    with _LOCK:
        _BUF.append(rec)
        if len(_BUF) > _MEM_MAX:
            del _BUF[: len(_BUF) - _MEM_MAX]
        path = _ensure_log()
        if path is not None:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                logger.debug("诊断事件落盘失败", exc_info=True)
    return rec


def recent(n: int = 100) -> List[Dict[str, Any]]:
    """取内存里最近 n 条（设置页「最近发生了什么」用它，不用读盘）。"""
    with _LOCK:
        return list(_BUF[-n:])


# ═══════════════════════════════════════════════════════════════════
# 全局钩子 —— 「每个功能都覆盖」靠这个，不靠逐点手写
# ═══════════════════════════════════════════════════════════════════

class _CaptureHandler(logging.Handler):
    """把所有 ``logger.error/exception`` 也收进诊断流。

    为什么要它：本项目大量 ``except Exception: logger.debug(...)``，
    这些是「已知会失败」的点，不接进来就等于放弃了最有价值的现场。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING:
                return
            exc = ""
            if record.exc_info:
                exc = "".join(traceback.format_exception(*record.exc_info))[-1200:]
            event(
                "E0105" if record.levelno >= logging.ERROR else "E0404",
                msg="%s: %s" % (record.name, record.getMessage()),
                level="error" if record.levelno >= logging.ERROR else "warn",
                # 日志记录自带 pathname/lineno —— 那就是「谁打的这条」，比 _site_of 准
                _site="%s:%d" % (os.path.basename(record.pathname), record.lineno),
                logger=record.name,
                at="%s:%d" % (os.path.basename(record.pathname), record.lineno),
                exc=_scrub(exc) if exc else "",
            )
        except Exception:  # stability-gate: allow-swallow（钩子内再抛会变成「记日志引发记日志」的死循环）
            # 钩子里再抛会变成"记日志引发记日志"的死循环，必须吞
            pass


# 幂等标记：install_hooks 会被启动流程和设置页各调一次，不能重复挂钩子
_installed = False


def install_hooks() -> None:
    """安装全局钩子。幂等，重复调用无副作用。

    覆盖三条路：
      ① 主线程未捕获异常（``sys.excepthook``）
      ② 子线程未捕获异常（``threading.excepthook``，3.8+）
      ③ 已捕获但打到 WARNING 以上的日志（``_CaptureHandler``）
    """
    global _installed
    if _installed:
        return
    _installed = True

    env_snapshot()
    event("E0105", msg="进程启动", level="info", stage="boot")

    prev_hook = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            event(
                "E0105",
                msg="未捕获异常：%s" % getattr(exc, "__class__", exc_type).__name__,
                level="error",
                # 关键：site 要指向真正出错的那一帧，不能是钩子自己
                _site=_frame_site(tb),
                exc=_scrub("".join(traceback.format_exception(exc_type, exc, tb))[-2000:]),
            )
        except Exception:  # stability-gate: allow-swallow（诊断上报失败不能干扰原始异常继续传播）
            pass
        prev_hook(exc_type, exc, tb)

    sys.excepthook = _hook

    if hasattr(threading, "excepthook"):
        prev_t = threading.excepthook

        def _thook(args):  # type: ignore[no-untyped-def]
            try:
                event(
                    "E0502",
                    msg="子线程崩溃：%s" % getattr(args.exc_type, "__name__", args.exc_type),
                    level="error",
                    _site=_frame_site(args.exc_traceback),
                    thread=getattr(args.thread, "name", "unknown"),
                    exc=_scrub("".join(
                        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
                    )[-2000:]),
                )
            except Exception:  # stability-gate: allow-swallow（同上：threading excepthook 包装层不得二次抛出）
                pass
            prev_t(args)

        threading.excepthook = _thook

    root = logging.getLogger()
    if not any(isinstance(h, _CaptureHandler) for h in root.handlers):
        h = _CaptureHandler(level=logging.WARNING)
        root.addHandler(h)


# ═══════════════════════════════════════════════════════════════════
# 诊断包
# ═══════════════════════════════════════════════════════════════════

_MAX_BUNDLE_LOG = 3


def make_bundle(out_path: Optional[str | Path] = None, extra: Optional[Dict[str, Any]] = None) -> Path:
    """把「最近几份诊断日志 + 环境快照」打成一个 zip，用户直接发给你。

    :param extra: 允许调用方补一点上下文（如当前工程 id、画布版本）。
                  **不要放素材内容、提示词原文、完整路径** —— 会随包外发。

    只打包**已经落盘的东西**，不补采。收不到就是收不到。
    """
    d = _default_log_dir()
    if out_path is None:
        out_path = d / ("diag_bundle_%s.zip" % time.strftime("%Y%m%d_%H%M%S"))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    files: List[Path] = []
    try:
        files = sorted(d.glob("diag_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        files = []
    files = files[:_MAX_BUNDLE_LOG]

    manifest = {
        "sid": _SID,
        "env": env_snapshot(),
        "log_files": [p.name for p in files],
        "event_count_mem": len(recent(10 ** 6)),
        "made_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "extra": json.loads(_scrub(json.dumps(extra or {}, ensure_ascii=False, default=str))),
        "note": "不含素材内容 / 提示词原文；路径中的用户名已替换为 <user>",
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr("env.json", json.dumps(env_snapshot(), ensure_ascii=False, indent=2))
        for p in files:
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
                z.writestr("logs/" + p.name, _scrub(raw))
            except Exception:
                z.writestr("logs/%s.ERROR.txt" % p.name, "读取失败")
        if not files:
            z.writestr("logs/_EMPTY.txt", "没有找到诊断日志。可能是数据目录不可写，或本次没有事件。")

    event("E0105", msg="已生成诊断包", level="info", bundle=out.name, files=len(files))
    return out


def self_check() -> Dict[str, Any]:
    """给设置页/自测用：诊断系统自己是否在工作。"""
    p = _ensure_log()
    return {
        "log_dir": str(_default_log_dir()),
        "log_file": str(p) if p else None,
        "writable": p is not None and p.parent.exists(),
        "sid": _SID,
        "codes": len(CODES),
        "events_in_memory": len(recent(10 ** 6)),
        "hooks_installed": _installed,
    }
