# -*- coding: utf-8 -*-
"""P0 推理缓存三件套真机标定（V4.47.0 缓存套件的验收实验，2026-10-25）。

为什么有这个脚本
================
`app/core/neural/inference_cache.py`（V4.47.0）按「默认关、显式开」落地。
官方倍率（DeepCache SDXL 2.6×）是 A5000 无 offload 口径，**本项目结论一律本机
重测**（.workbuddy/memory 实测纪律）。本脚本就是那次重测：把三个组件的
开关代价 / 收益 / 画质 / 回退路径全部量出实数，作为 SHIGUANG_* 默认值决议的输入。

准入判据（设计稿 §12「优化准入判述」升格的书面标准）
==================================================
  ① 对照实验：同 prompt / 同 seed / 同预设，只动被测量的那个开关；
  ② n≥3：off/on **交替**执行（抵消笔记本 GPU 热漂移，杜绝分块排序偏差）；
  ③ 反例：门控拒例 / 环境钳制 / 缓存键敏感性——必须**真的**拒绝；
  ④ 回退路径：mock 注入缓存层故障 ⇒ 出图不受影响 + 状态留痕（fallback）；
  ⑤ 峰值显存同测（torch.cuda.max_memory_allocated）：收益不能以爆显存为代价；
  ⑥ 画质不口头：CLIP-L 对齐 + Laplacian 清晰度 + Haar 人脸，样图落盘供目视。

子命令
======
  gate      纯函数反例表（无 GPU，秒级）：门控拒例 / 环境钳制 / 缓存键敏感性
  step      DeepCache A/B：SHIGUANG_STEP_CACHE 开/关，端到端 + 峰显存 + 遥测 + 画质
  encoder   编码器缓存 A/B：同 prompt 连抽（off×N vs on×N）+ 编码段冷热直测
           + 像素一致性断言（零质量风险的硬证据）
  lowrank   低秩三档：0/0.125/0.25/0.5 同 seed，耗时 / 峰显存 / cached_bytes / 画质
  fallback  回退路径：mock 注入 encoder_cache / StepFeatureCache.attach 故障
           + final 档门控拒例（运行时证明，非纯函数）

用法（项目根目录，GPU 独占，勿并行）：
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py gate
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py step --model sdxl-t2i --preset fast --n 3
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py step --model sdxl-t2i --preset high --n 3
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py step --model sd15-t2i --preset fast --n 3 --promote 0
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py encoder --model sdxl-t2i --draws 4
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py lowrank --model sdxl-t2i --preset high
  .venv312/Scripts/python.exe -u _verify/bench_p0_cache.py fallback --model sd15-t2i

纪律说明
========
· SHIGUANG_HOT_PROMOTE 默认置 0：首图热提升是**另一个**已实测特性（-26% 稳态），
  混进来会污染 A/B；SDXL 在生产默认下也提升不了（6.46GB 装不进 8.585GB），
  SD15 另跑 --promote 1 一桌验证生产路径。
· fast 档（SDXL）首跑会触发 LCM-LoRA 装卸（unload+整卡装载+重开 offload，
  实测 ~1-2 分钟）⇒ 不计时预热 2 次后再进正赛。
· **抢卡防护**（2026-10-25 实测教训）：并行会话同机跑 bench 会让墙钟出现 3× 假
  异常值 ⇒ 每个 GPU 子命令启动前检测外部计算进程（python*/main_qt6/blender*），
  有则拒跑（rc=4）；每次计时也留痕 foreign_procs。宁停不污。
· 与并行会话的 `scripts/bench_p0_cache.py`（协议见
  `docs/_reports/2026-10-25-P0推理缓存真机标定协议.md`）分工：那侧出微标定数字
  （pool/encoder 记账/deepcache PSNR 墙钟），本台出**生产接线路径**标定
  （generate() 端到端 + offload 遥测 + 编码段冷热 + 像素一致性 + 回退 mock +
  load/unload 循环）。sd15 deepcache 墙钟那侧已出（1.36× / PSNR 13.75dB），
  本台不重复，直接引用。
· 输出：`.workbuddy/tmp/bench/p0/`（JSON + 样图 + 逐次日志）。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import re
import statistics
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

OUT_DIR = os.path.join(ROOT, ".workbuddy", "tmp", "bench", "p0")

# 与历史 bench（bench_quality.py / sweep_deepcache.py）同口径的提示词与种子
PROMPTS = [
    "a cinematic portrait of a woman in a red dress, soft rim light, 35mm",
    "a lone lighthouse on a cliff at dusk, storm clouds, dramatic sky",
]
NEG = "blurry, low quality, deformed, watermark"
SEED = 4242

_ENV_STEP = "SHIGUANG_STEP_CACHE"
_ENV_ENCODER = "SHIGUANG_ENCODER_CACHE"
_ENV_INTERVAL = "SHIGUANG_STEP_CACHE_INTERVAL"
_ENV_BRANCH = "SHIGUANG_STEP_CACHE_BRANCH"
_ENV_LOWRANK = "SHIGUANG_STEP_CACHE_LOWRANK"

log = logging.getLogger("bench")


# ══════════════════════════════ 基础设施 ══════════════════════════════

def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_out() -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    return OUT_DIR


def write_json(tag: str, data: Dict[str, Any]) -> str:
    path = os.path.join(_ensure_out(), "%s.json" % tag)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def med(vals: List[float]) -> float:
    return round(statistics.median(vals), 3) if vals else 0.0


@contextmanager
def env_set(**kw: Optional[str]) -> Iterator[None]:
    """临时设置/删除环境变量（value=None = 删除）。退出时原样恢复。"""
    saved: Dict[str, Optional[str]] = {}
    try:
        for k, v in kw.items():
            saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class LogTap(logging.Handler):
    """把引擎日志收进列表——遥测与状态机的唯一观测窗（零改生产代码）。"""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            log.debug("LogTap emit 失败", exc_info=True)

    def clear(self) -> None:
        self.lines.clear()


def install_log_tap() -> LogTap:
    tap = LogTap()
    tap.setFormatter(logging.Formatter("%(name)s|%(message)s"))
    for name in ("app.core.neural.diffusers_image", "app.core.neural.inference_cache"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        lg.addHandler(tap)
    return tap


_RX_STEP_TEL = re.compile(
    r"步缓存遥测：full=(\d+) reuse=(\d+) hits=(\d+) fallback=(\d+) "
    r"skip=([\d.]+) cached=([\d.]+)MB")
_RX_LOWRANK = re.compile(r"校准完成：C=(\d+) r=(\d+) energy=([\d.]+)")


def parse_run(tap: LogTap) -> Dict[str, Any]:
    """从一次 generate 的日志里榨出结构化状态（遥测/缓存态/门控决策）。"""
    out: Dict[str, Any] = {"step_tel": None, "enc": [], "lowrank": [], "flags": []}
    for ln in tap.lines:
        m = _RX_STEP_TEL.search(ln)
        if m:
            out["step_tel"] = {"full": int(m.group(1)), "reuse": int(m.group(2)),
                               "hits": int(m.group(3)), "fallback": int(m.group(4)),
                               "skip": float(m.group(5)),
                               "cached_mb": float(m.group(6))}
            continue
        if "编码器缓存命中" in ln:
            out["enc"].append("hit")
        elif "编码器缓存写入" in ln:
            out["enc"].append("miss")
        elif "编码器缓存路径失败" in ln:
            out["flags"].append("enc_fallback")
        elif "编码器缓存未启用" in ln:
            out["flags"].append("enc_off")
        elif "步缓存已激活" in ln:
            out["flags"].append("step_on")
        elif "步缓存未启用" in ln:
            out["flags"].append("step_off")
        elif "步缓存挂载异常" in ln or "步缓存挂载失败" in ln:
            out["flags"].append("step_attach_fail")
        else:
            m2 = _RX_LOWRANK.search(ln)
            if m2:
                out["lowrank"].append({"C": int(m2.group(1)), "r": int(m2.group(2)),
                                       "energy": float(m2.group(3))})
    return out


def setup_env(promote: str, tag: str) -> None:
    os.environ["SHIGUANG_HOT_PROMOTE"] = promote
    os.environ["SHIGUANG_ENGINE_TELEMETRY_PATH"] = os.path.join(
        _ensure_out(), "tel_%s.json" % tag)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    import torch

    torch.backends.cudnn.benchmark = True


def cuda_ctx() -> Dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        return {"cuda": False}
    free, total = torch.cuda.mem_get_info()
    props = torch.cuda.get_device_properties(0)
    return {"cuda": True, "gpu": props.name,
            "total_gb": round(total / 1024 ** 3, 2),
            "free_gb": round(free / 1024 ** 3, 2),
            "torch": torch.__version__}


def reset_peak() -> None:
    import torch

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()


def peak_mb() -> float:
    import torch

    if not torch.cuda.is_available():
        return 0.0
    return round(torch.cuda.max_memory_allocated() / 1048576.0, 1)


def load_engine(model_id: str) -> Tuple[Any, Dict[str, Any]]:
    """加载图像引擎，返回 (engine, load_info)。加载耗时/offload/精度全部留痕。"""
    import app.core.neural.diffusers_image as DIF

    eng = DIF.get_diffusers_image_engine()
    t0 = time.time()
    r = eng.load(model_id)
    info = {"ok": bool(r.get("ok")), "load_s": round(time.time() - t0, 1),
            "message": r.get("message"), "offload": getattr(eng, "_offload", "?"),
            "precision": getattr(eng, "_precision", "?")}
    return eng, info


def timed_generate(eng: Any, tap: LogTap, *, model_id: str, prompt: str,
                   seed: int, preset: str, out_path: str) -> Dict[str, Any]:
    """一次 generate 的全量留痕：墙钟 / 引擎秒 / 峰显存 / 模式 / 遥测 / 缓存态。"""
    tap.clear()
    reset_peak()
    rec_foreign = gpu_foreign_procs()
    rec_gpu = gpu_snapshot()
    assert_vram_headroom("出图(%s)" % model_id)
    t0 = time.time()
    r = eng.generate(model_id, prompt=prompt, negative_prompt=NEG, seed=seed,
                     out_path=out_path, preset=preset)
    wall = time.time() - t0
    # 出图**期间**再取一次外部占用：起跑前的快照可能正好撞上对方空档，
    # 只有"与我并行时对方在算"才是真争抢。
    post_foreign = gpu_foreign_procs()
    post_gpu = gpu_snapshot()
    all_foreign = rec_foreign + post_foreign
    # 只把「真对手」（另一个标定 / 未知 python）算作争抢；Qt 应用的 WebEngine
    # 合成空转不算（它吃显存由余量守卫负责）。
    rivals = [f for f in all_foreign if f.get("kind") in ("bench", "other")]
    foreign_sm = max([f.get("sm", 0.0) for f in rivals], default=0.0)
    qt_sm = max([f.get("sm", 0.0) for f in all_foreign
                 if f.get("kind") == "qt_app"], default=0.0)
    rec: Dict[str, Any] = {
        "wall_s": round(wall, 2), "engine_s": r.get("seconds_elapsed"),
        "ok": bool(r.get("ok")), "msg": r.get("message"),
        "mode": r.get("memory_mode"), "precision": r.get("precision"),
        "steps": r.get("steps"), "cfg": r.get("cfg"),
        "peak_mb": peak_mb(), "promote": eng.promote_status().get("state"),
        "foreign_procs": all_foreign, "foreign_max_sm": foreign_sm,
        "qt_app_sm": qt_sm, "rival_procs": rivals,
        "gpu_pre": rec_gpu, "gpu_post": post_gpu, "out": out_path,
        "parsed": parse_run(tap),
    }
    try:
        thr_sm = int(os.environ.get("BENCH_FOREIGN_SM_MAX", "15"))
    except ValueError:
        thr_sm = 15
    rec["contaminated"] = foreign_sm >= thr_sm
    if r.get("ok") and os.path.isfile(out_path):
        rec["sha"] = sha256_file(out_path)
    return rec


def _face_cascade() -> Any:
    """定位 Haar 级联：cv2.data → 已知备用路径；都没有 ⇒ None（宁缺勿假）。

    为什么需要（2026-10-25 实测）：.venv312 的 cv2/data 缺 frontalface 文件，
    detectMultiScale 直接抛 cv2.error 把整阶段炸掉（fast 阶段已中招 rc=1）。
    """
    import os

    import cv2

    name = "haarcascade_frontalface_default.xml"
    cands: List[str] = []
    if hasattr(cv2, "data") and getattr(cv2.data, "haarcascades", None):
        cands.append(os.path.join(cv2.data.haarcascades, name))
    cands.append(os.path.join(
        r"C:\Users\Administrator\.workbuddy\binaries\python\envs\default"
        r"\Lib\site-packages\cv2\data", name))
    for p in cands:
        c = cv2.CascadeClassifier(p)
        if not c.empty():
            return c
    return None


def image_quality(path: str) -> Dict[str, Any]:
    """Laplacian 清晰度 + Haar 人脸（CLIP 由 clip_score_all 批量补）。

    faces=-1 = 级联文件缺失未测（诚实缺口，不猜 0）。
    """
    import cv2
    import numpy as np
    from PIL import Image

    arr = np.asarray(Image.open(path).convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    cascade = _face_cascade()
    faces = int(len(cascade.detectMultiScale(gray, 1.1, 5))) if cascade else -1
    return {"laplacian": round(lap, 1), "faces": faces}


def clip_score_all(pairs: List[Tuple[str, str]],
                   device: str = "cuda") -> Dict[str, float]:
    """CLIP-L 图文余弦（logits_per_image 原值；与历史 bench 同口径）。

    调用前应先 unload 生成引擎（显存让位）。无本地权重 ⇒ 返回空 dict（宁缺勿假）。
    device 参数供离线补分走 CPU（不与 GPU 标定链抢卡）。
    """
    if not pairs:
        return {}
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor

    cands = glob.glob(os.path.join(ROOT, "app", "models", "cache",
                                   "clip-vit-large-patch14", "**", "config.json"),
                      recursive=True)
    if not cands:
        print("[bench] 无 CLIP 本地权重，跳过打分")
        return {}
    cdir = os.path.dirname(cands[0])
    cm = CLIPModel.from_pretrained(cdir, local_files_only=True).to(device).eval()
    cp = CLIPProcessor.from_pretrained(cdir, local_files_only=True)
    out: Dict[str, float] = {}
    for path, prompt in pairs:
        img = Image.open(path).convert("RGB")
        inp = cp(text=[prompt], images=[img], return_tensors="pt",
                 padding=True).to(device)
        with torch.no_grad():
            o = cm(**inp)
        out[path] = round(float(o.logits_per_image[0][0]), 3)
    del cm, cp
    return out


def unload_for_clip(eng: Any) -> None:
    import torch

    eng.unload()
    torch.cuda.empty_cache()
    time.sleep(1.0)


def _proc_cmdlines(pids: List[int]) -> Dict[int, str]:
    """取指定 PID 的完整命令行：区分「另一个标定」与「空闲 Qt 应用」。

    为什么必须分（2026-10-25 实测）：pmon 只给可执行名，两者都显示 python.exe；
    而 Qt 应用（app.main_qt6）只是 WebEngine 合成空转（15-28% sm），不构成
    计算争抢；把两者一锅端 ⇒ 正常数据被误判污染、等待逻辑反复横跳。
    """
    if not pids:
        return {}
    try:
        import subprocess

        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @(%s) }"
              " | ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
              % ",".join(str(p) for p in pids))
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=30)
        out: Dict[int, str] = {}
        for ln in (r.stdout or "").splitlines():
            if "|" not in ln:
                continue
            pid_s, _, cmd = ln.partition("|")
            try:
                out[int(pid_s.strip())] = cmd.strip()
            except ValueError:
                continue
        return out
    except Exception:
        log.debug("_proc_cmdlines 失败", exc_info=True)
        return {}


def gpu_foreign_procs() -> List[Dict[str, Any]]:
    """列出可能抢卡的**外部**计算进程（python* 除自身 / main_qt6 / blender*）。

    为什么需要（2026-10-25 实测教训）：并行会话同机跑标定是真实发生过的污染源——
    本轮首跑 rep1 出现 46.28s（同臂 rep0 仅 15.33s）的 3× 异常值，根因 = 另一会话
    同时跑 bench。只读探测、不杀进程；用于**阶段启动拒跑** + **逐次留痕**。
    """
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,name",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return []
    foreign: List[Dict[str, Any]] = []
    me = os.getpid()
    for line in (out.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == me:
            continue
        base = os.path.basename(parts[1]).lower()
        if base.startswith("python") or "main_qt6" in base or "blender" in base:
            foreign.append({"pid": pid, "name": parts[1]})
    sm = gpu_pmon()
    cmds = _proc_cmdlines([f["pid"] for f in foreign])
    for f in foreign:
        f["sm"] = sm.get(f["pid"], {}).get("sm", 0.0)
        cmd = cmds.get(f["pid"], "")
        f["cmd"] = cmd
        low = cmd.lower()
        if "bench" in low:
            f["kind"] = "bench"          # 另一个标定 = 真对手
        elif "main_qt6" in low:
            f["kind"] = "qt_app"         # WebEngine 合成空转 = 不算争抢（但吃显存）
        else:
            f["kind"] = "other"          # 未知 python = 保守当真对手
    return foreign


def gpu_pmon() -> Dict[int, Dict[str, Any]]:
    """按进程取 SM 占用（nvidia-smi pmon）。

    为什么必须有（2026-10-25 实测）：`utilization.gpu` 是**全卡**占用，
    把自己正在出图的负载也算成"外部进程在算" ⇒ 正常数据被误判污染
    （lowrank 阶段 3 次里 2 次被标污染，实为自伤）。
    pmon 按 PID 分列 sm%，只把**别人**的占用算作争抢。
    """
    import subprocess

    out: Dict[int, Dict[str, Any]] = {}
    try:
        r = subprocess.run(["nvidia-smi", "pmon", "-c", "1", "-s", "u"],
                           capture_output=True, text=True, timeout=20)
        for ln in (r.stdout or "").splitlines():
            parts = ln.split()
            if len(parts) < 10 or not parts[0].isdigit():
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            raw = parts[3]
            try:
                smv = float(raw)
            except ValueError:
                smv = 0.0
            out[pid] = {"pid": pid, "sm": smv, "cmd": parts[-1]}
    except Exception:
        log.debug("gpu_pmon 失败", exc_info=True)
    return out


def gpu_snapshot() -> Dict[str, Any]:
    """GPU 利用率 + 空闲显存快照（nvidia-smi 一次调用）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15)
        line = (out.stdout or "").splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        return {"util": int(float(parts[0])), "free_gb": round(float(parts[1]) / 1024, 2)}
    except Exception:
        return {"util": None, "free_gb": None}


def gpu_usable(phase: str) -> Dict[str, Any]:
    """阶段启动判读：外部进程**空闲**（util<15% 且显存宽裕）⇒ 放行但留痕；
    外部进程**在算**（util≥15%）或显存见底（<1.2GB）⇒ 拒跑（rc=4）。

    2026-10-25 实测：并行会话同时跑 bench 让墙钟出现 3× 假异常值（46.28s vs
    同臂 15.33s）；但并行会话拉起的空闲 Qt 应用只做 WebEngine 合成（util 30-40%、
    输出目录零新图）不产生计算争抢 ⇒ 按利用率区分，不搞「见 python 就拒」的一刀切。
    阈值可用 `BENCH_GPU_UTIL_MAX` 覆盖（操作者已用证据判定负载良性时显式调高，
    例：BENCH_GPU_UTIL_MAX=100）；逐次留痕不受覆盖影响，照记。
    """
    foreign = gpu_foreign_procs()
    snap = gpu_snapshot()
    try:
        thr = int(os.environ.get("BENCH_GPU_UTIL_MAX", "15"))
    except ValueError:
        thr = 15
    # 按进程判「谁在算」：只看真对手（另一个标定 / 未知 python），
    # Qt 应用的 WebEngine 合成空转不算争抢（它吃显存由余量守卫负责）。
    rivals = [f for f in foreign if f.get("kind") in ("bench", "other")]
    foreign_sm = max([f.get("sm", 0.0) for f in rivals], default=0.0)
    if rivals:
        busy = foreign_sm >= thr
        busy_by = "对手进程 sm=%d%%" % foreign_sm
    else:
        busy = False
        busy_by = "无对手进程（Qt 空转不计）"
    starved = snap["free_gb"] is not None and snap["free_gb"] < 1.2
    if busy or starved:
        names = ", ".join("%s(pid=%d)" % (os.path.basename(x["name"]), x["pid"])
                          for x in foreign) or "（无外部进程）"
        raise RuntimeError(
            "拒绝启动 %s 标定：%s（%s · 空闲 %sGB · 阈值 %d%%）。"
            "并发占卡/显存见底会制造假数据，等对方空闲后重跑。"
            % (phase, ("外部进程在算：" + names) if busy else "显存见底",
               busy_by, snap["free_gb"], thr))
    if foreign:
        names = ", ".join("%s(pid=%d)" % (os.path.basename(x["name"]), x["pid"])
                          for x in foreign)
        sms = ", ".join("pid=%d sm=%d%%" % (x["pid"], x.get("sm", 0))
                        for x in foreign)
        print("[bench] 注意：外部进程 %s 在位（%s · 全卡 util=%s%% · 空闲 %sGB）"
              "⇒ 放行，逐次留痕" % (names, sms, snap["util"], snap["free_gb"]))
    return {"foreign": foreign, "gpu": snap}


# 加载模型后本进程自身占掉大部分显存，剩余量是「瞬时搬模块」的空间。
# 2026-10-25 实测僵死事故：外部 Qt 应用中途抢走显存 ⇒ 空闲跌到 117MB，
# 下一张图在 offload 搬模块时**无报错挂死**（0/20 步、GPU util 0%）。
# ⇒ 每次出图前查余量，见底就干净退场（rc=4），不做假数据。
VRAM_HEADROOM_MIN_GB = 1.0


def assert_vram_headroom(phase: str) -> Dict[str, Any]:
    snap = gpu_snapshot()
    free = snap["free_gb"]
    if free is not None and free < VRAM_HEADROOM_MIN_GB:
        raise RuntimeError(
            "拒绝继续 %s：显存余量只剩 %sGB（阈值 %sGB），外部进程抢占会逼出"
            "无报错挂死（实测 117MB ⇒ 卡在 0/20 步）。先等对方释放。"
            % (phase, free, VRAM_HEADROOM_MIN_GB))
    return snap


# ══════════════════════════════ 子命令：gate ══════════════════════════════

def cmd_gate(_args: argparse.Namespace) -> int:
    """纯函数反例表：门控必须真的拒绝（不靠 GPU，秒级）。"""
    from app.core.neural.inference_cache import (
        ENCODER_CACHE_ARCHS, STEP_CACHE_ARCHS, STEP_CACHE_PRESETS, cache_gate,
        make_cache_key)

    print("=== 门控反例表（step_cache：arch × preset × 环境）===")
    print("  %-6s %-10s %-12s %-6s %s" % ("arch", "preset", "env", "期望", "实际"))
    rows: List[Dict[str, Any]] = []
    cases: List[Tuple[str, str, Optional[str], bool]] = [
        ("sd15", "fast", "deepcache", True),
        ("sdxl", "high", "deepcache", True),
        ("svd", "preview", "deepcache", True),
        ("sdxl", "final", "deepcache", False),      # final 永不开（抽卡对细节敏感）
        ("sdxl", "balanced", "deepcache", False),   # 默认档不进白名单
        ("sdxl", "", "deepcache", False),           # 空档 = 不干预
        ("wan", "fast", "deepcache", False),        # DiT 未核实（走 FBCache 探针）
        ("sdxl", "fast", None, False),              # 默认关
        ("sdxl", "fast", "banana", False),          # 非法值按关处理
    ]
    all_pass = True
    for arch, preset, envv, expect in cases:
        with env_set(**{_ENV_STEP: envv}):
            g = cache_gate(arch=arch, preset=preset, component="step_cache")
        ok = bool(g["ok"])
        good = ok == expect
        all_pass = all_pass and good
        rows.append({"component": "step_cache", "arch": arch, "preset": preset,
                     "env": envv, "expect": expect, "got": ok,
                     "pass": good, "reasons": g["reasons"]})
        print("  %-6s %-10s %-12s %-6s %-6s %s" % (
            arch, preset or '""', envv or '""', "PASS" if good else "FAIL",
            "开" if ok else "关",
            (g["reasons"][0][:60] if g["reasons"] else "(通过，无拒绝理由)")))

    print("\n=== 门控反例表（encoder_cache）===")
    enc_cases: List[Tuple[str, Optional[str], bool]] = [
        ("sd15", "1", True), ("sdxl", "1", True),
        ("svd", "1", False),      # 无公开 encode_prompt
        ("sd15", None, False),    # 默认关
        ("sd15", "0", False),
    ]
    for arch, envv, expect in enc_cases:
        with env_set(**{_ENV_ENCODER: envv}):
            g = cache_gate(arch=arch, preset="fast", component="encoder_cache")
        ok = bool(g["ok"])
        good = ok == expect
        all_pass = all_pass and good
        rows.append({"component": "encoder_cache", "arch": arch, "preset": "fast",
                     "env": envv, "expect": expect, "got": ok,
                     "pass": good, "reasons": g["reasons"]})
        print("  %-6s %-12s %-6s %-6s %s" % (arch, envv or '""',
                                             "PASS" if good else "FAIL",
                                             "开" if ok else "关",
                                             (g["reasons"][0][:60]
                                              if g["reasons"] else "(通过，无拒绝理由)")))

    print("\n=== 环境变量钳制（interval / lowrank）===")
    clamps: List[Tuple[str, str, Any, Any]] = []
    with env_set(**{_ENV_STEP: "deepcache"}):
        for raw, field, expect in [("1", "interval", 2), ("999", "interval", 20),
                                   ("abc", "interval", 3), ("0.01", "lowrank", 0.05),
                                   ("0.99", "lowrank", 0.9)]:
            with env_set(**{"SHIGUANG_STEP_CACHE_INTERVAL": raw
                            if field == "interval" else None,
                            _ENV_LOWRANK: raw if field == "lowrank" else None}):
                g = cache_gate(arch="sdxl", preset="fast", component="step_cache")
            got = g["params"].get(field) if g["ok"] else None
            good = got == expect
            all_pass = all_pass and good
            clamps.append({"field": field, "raw": raw, "expect": expect,
                           "got": got, "pass": good})
            print("  %-9s raw=%-6s 期望=%-6s 实际=%-6s %s" % (
                field, raw, expect, got, "PASS" if good else "FAIL"))

    print("\n=== 缓存键敏感性（少一个字段就是「换 LoRA 出旧图」级 bug）===")
    base_kw = dict(arch="sdxl", model_id="sdxl-t2i", prompt=PROMPTS[0],
                   negative_prompt=NEG, lora_set="", max_length=77)
    k0 = make_cache_key(**base_kw)  # type: ignore[arg-type]
    key_cases = [
        ("同参数（必须同键）", dict(base_kw), k0, True),
        ("换 prompt", dict(base_kw, prompt=PROMPTS[1]), k0, False),
        ("换 negative", dict(base_kw, negative_prompt="ugly"), k0, False),
        ("换 LoRA 集", dict(base_kw, lora_set="lcm"), k0, False),
        ("换 max_length", dict(base_kw, max_length=77 + 1), k0, False),
        ("换 model_id", dict(base_kw, model_id="sd15-t2i"), k0, False),
    ]
    for name, kw, ref, same in key_cases:
        k = make_cache_key(**kw)  # type: ignore[arg-type]
        good = (k == ref) == same
        all_pass = all_pass and good
        print("  %-16s %s" % (name, "PASS" if good else "FAIL"))

    print("\n门控反例表总判：%s" % ("ALL PASS" if all_pass else "有 FAIL（见上）"))
    path = write_json("gate_%s" % _ts(), {
        "phase": "gate", "cuda": cuda_ctx(), "all_pass": all_pass,
        "rows": rows, "clamps": clamps,
        "whitelists": {"step_archs": sorted(STEP_CACHE_ARCHS),
                       "step_presets": sorted(STEP_CACHE_PRESETS),
                       "encoder_archs": sorted(ENCODER_CACHE_ARCHS)},
    })
    print("JSON: %s" % path)
    return 0 if all_pass else 1


# ══════════════════════════════ 子命令：step ══════════════════════════════

def cmd_step(args: argparse.Namespace) -> int:
    """DeepCache A/B：off/on 交替 n 轮，同 prompt 同 seed（按轮配对）。"""
    tag = "step_%s_%s_%s" % (args.model, args.preset, _ts())
    setup_env(args.promote, tag)
    tap = install_log_tap()
    print("[bench] step A/B model=%s preset=%s n=%d promote=%s" % (
        args.model, args.preset, args.n, args.promote))
    gpu_usable("step")
    eng, li = load_engine(args.model)
    print("[bench] load %s" % li)
    data: Dict[str, Any] = {"phase": "step", "model": args.model,
                            "preset": args.preset, "n": args.n,
                            "promote": args.promote, "cuda": cuda_ctx(),
                            "interval": args.interval or "(生产默认)",
                            "branch": args.branch or "(生产默认)",
                            "load": li, "prompt": PROMPTS[0]}
    if not li["ok"]:
        data["error"] = "load failed"
        print("[bench] 加载失败：%s" % li["message"])
        write_json(tag, data)
        return 2

    bench_dir = os.path.join(_ensure_out(), tag)
    os.makedirs(bench_dir, exist_ok=True)

    # 预热（不计时）：SDXL fast 首跑触发 LCM-LoRA 装卸（~1-2min），必须挡在正赛外
    n_warm = 2 if (args.preset == "fast" and args.model == "sdxl-t2i") else 1
    for i in range(n_warm):
        r = eng.generate(args.model, prompt=PROMPTS[0], negative_prompt=NEG,
                         seed=SEED, preset=args.preset,
                         out_path=os.path.join(bench_dir, "warm%d.png" % i))
        print("[bench] warmup %d ok=%s mode=%s" % (i, r.get("ok"), r.get("memory_mode")))

    arms: Dict[str, List[Dict[str, Any]]] = {"off": [], "on": []}
    for rep in range(args.n):
        seed = SEED + rep
        for arm in ("off", "on"):
            step_env = "deepcache" if arm == "on" else None
            on_env: Dict[str, Optional[str]] = {_ENV_STEP: step_env}
            if arm == "on" and args.interval:
                on_env[_ENV_INTERVAL] = str(args.interval)
            if arm == "on" and args.branch:
                on_env[_ENV_BRANCH] = str(args.branch)
            with env_set(**on_env):
                rec = timed_generate(
                    eng, tap, model_id=args.model, prompt=PROMPTS[0], seed=seed,
                    preset=args.preset,
                    out_path=os.path.join(bench_dir, "%s_r%d.png" % (arm, rep)))
            rec["arm"] = arm
            rec["rep"] = rep
            rec["seed"] = seed
            arms[arm].append(rec)
            st = rec["parsed"]["step_tel"]
            print("[bench] rep=%d %-3s wall=%6.2fs peak=%7.1fMB mode=%s%s tel=%s" % (
                rep, arm, rec["wall_s"], rec["peak_mb"], rec["mode"],
                " 污染!" if rec["contaminated"] else "",
                ("full=%d reuse=%d hits=%d skip=%.2f cached=%.1fMB" % (
                    st["full"], st["reuse"], st["hits"], st["skip"], st["cached_mb"]))
                if st else "无遥测（未挂载）"))

    # 汇总（中位数抗单点噪声；被并发污染的次数不计入）
    summary: Dict[str, Any] = {}
    for arm in ("off", "on"):
        runs = [r for r in arms[arm] if r["ok"] and not r.get("contaminated")]
        contam = [r for r in arms[arm] if r.get("contaminated")]
        if not runs:
            summary[arm] = {"n_ok": 0, "n_contaminated": len(contam)}
            continue
        summary[arm] = {
            "n_ok": len(runs),
            "n_contaminated": len(contam),
            "wall_med": med([r["wall_s"] for r in runs]),
            "peak_med": med([r["peak_mb"] for r in runs]),
            "peak_max": max(r["peak_mb"] for r in runs),
            "modes": sorted({str(r["mode"]) for r in runs}),
        }
    if summary.get("off", {}).get("n_ok") and summary.get("on", {}).get("n_ok"):
        o = summary["off"]["wall_med"]
        n = summary["on"]["wall_med"]
        summary["speedup"] = round(o / n, 3) if n else 0.0
        summary["delta_pct"] = round((n - o) / o * 100, 1)
        summary["peak_delta_mb"] = round(
            summary["on"]["peak_med"] - summary["off"]["peak_med"], 1)

    # 画质三件套（CLIP 需先卸载让位）
    pairs = [(r["out"], PROMPTS[0]) for arm in ("off", "on") for r in arms[arm]
             if r.get("ok") and os.path.isfile(r.get("out", ""))]
    unload_for_clip(eng)
    clip = clip_score_all(pairs)
    for arm in ("off", "on"):
        for r in arms[arm]:
            if r.get("ok") and os.path.isfile(r.get("out", "")):
                q = image_quality(r["out"])
                q["clip"] = clip.get(r["out"])
                r["quality"] = q
    if clip:
        for arm in ("off", "on"):
            vals = [r["quality"]["clip"] for r in arms[arm]
                    if r.get("quality") and r["quality"].get("clip") is not None]
            laps = [r["quality"]["laplacian"] for r in arms[arm] if r.get("quality")]
            faces = [r["quality"]["faces"] for r in arms[arm] if r.get("quality")]
            if arm in summary and vals:
                summary[arm]["clip_mean"] = round(sum(vals) / len(vals), 3)
                summary[arm]["lap_mean"] = round(sum(laps) / len(laps), 1)
                summary[arm]["faces_mean"] = round(sum(faces) / len(faces), 2)
        if (summary.get("off", {}).get("clip_mean")
                and summary.get("on", {}).get("clip_mean")):
            summary["clip_rel_pct"] = round(
                summary["on"]["clip_mean"] / summary["off"]["clip_mean"] * 100, 1)

    data.update({"arms": arms, "summary": summary})
    path = write_json(tag, data)
    print("\n=== step A/B 汇总（%s / %s）===" % (args.model, args.preset))
    print("  off: wall中位 %ss · 峰 %sMB · CLIP %s" % (
        summary.get("off", {}).get("wall_med"), summary.get("off", {}).get("peak_med"),
        summary.get("off", {}).get("clip_mean")))
    print("  on : wall中位 %ss · 峰 %sMB · CLIP %s" % (
        summary.get("on", {}).get("wall_med"), summary.get("on", {}).get("peak_med"),
        summary.get("on", {}).get("clip_mean")))
    print("  端到端加速 %s×（%s%%）· 峰显存差 %sMB · CLIP 相对 %s%%" % (
        summary.get("speedup"), summary.get("delta_pct"),
        summary.get("peak_delta_mb"), summary.get("clip_rel_pct")))
    print("JSON: %s" % path)
    return 0


# ══════════════════════════════ 子命令：encoder ══════════════════════════════

def cmd_encoder(args: argparse.Namespace) -> int:
    """编码器缓存：连抽 A/B + 编码段冷热直测 + 像素一致性断言。"""
    tag = "encoder_%s_%s" % (args.model, _ts())
    setup_env("0", tag)
    tap = install_log_tap()
    print("[bench] encoder A/B model=%s draws=%d" % (args.model, args.draws))
    gpu_usable("encoder")
    eng, li = load_engine(args.model)
    data: Dict[str, Any] = {"phase": "encoder", "model": args.model,
                            "draws": args.draws, "cuda": cuda_ctx(), "load": li,
                            "prompt": PROMPTS[0]}
    if not li["ok"]:
        data["error"] = "load failed"
        write_json(tag, data)
        return 2
    arch = "sdxl" if "sdxl" in args.model else "sd15"

    from app.core.neural.inference_cache import (
        encoder_cache, encode_prompt_embeds, make_cache_key)

    pipe = eng._pipe
    dev = getattr(pipe, "_execution_device", None)
    tok = getattr(pipe, "tokenizer", None)
    max_len = int(getattr(tok, "model_max_length", 0) or 77)

    # ── ① 编码段冷热直测（绕过 generate，直量原语）──
    seg: Dict[str, Any] = {"cold_s": [], "warm_s": [], "errors": []}
    key = make_cache_key(arch=arch, model_id=args.model, prompt=PROMPTS[0],
                         negative_prompt=NEG, lora_set="", max_length=max_len)
    for _i in range(3):
        encoder_cache().clear()
        t0 = time.time()
        embeds, why = encode_prompt_embeds(pipe, arch=arch, prompt=PROMPTS[0],
                                           negative_prompt=NEG, do_cfg=True,
                                           device=dev)
        seg["cold_s"].append(round(time.time() - t0, 3))
        if embeds is None:
            seg["errors"].append("cold: %s" % why)
            continue
        encoder_cache().put(key, embeds)
        for _j in range(3):
            t0 = time.time()
            got = encoder_cache().get(key, device=dev)
            seg["warm_s"].append(round(time.time() - t0, 4))
            if got is None:
                seg["errors"].append("warm: get 返回 None")
    seg["cold_med"] = med(seg["cold_s"])
    seg["warm_med"] = med(seg["warm_s"])
    seg["speedup"] = (round(seg["cold_med"] / seg["warm_med"], 1)
                      if seg["warm_med"] else 0.0)
    data["segment"] = seg
    print("[bench] 编码段直测：冷 %ss（n=%d）vs 暖 %ss（n=%d）⇒ %s×" % (
        seg["cold_med"], len(seg["cold_s"]), seg["warm_med"],
        len(seg["warm_s"]), seg["speedup"]))

    bench_dir = os.path.join(_ensure_out(), tag)
    os.makedirs(bench_dir, exist_ok=True)

    # ── ② 端到端连抽 A/B（off×N → on×N，同 prompt/seed）──
    with env_set(**{_ENV_ENCODER: None}):
        warm = eng.generate(args.model, prompt=PROMPTS[0], negative_prompt=NEG,
                            seed=SEED, preset="final",
                            out_path=os.path.join(bench_dir, "warm.png"))
        print("[bench] warmup ok=%s" % warm.get("ok"))
        runs_off: List[Dict[str, Any]] = []
        for i in range(args.draws):
            rec = timed_generate(eng, tap, model_id=args.model, prompt=PROMPTS[0],
                                 seed=SEED, preset="final",
                                 out_path=os.path.join(bench_dir, "off_%d.png" % i))
            rec["draw"] = i
            runs_off.append(rec)
            print("[bench] off draw=%d wall=%6.2fs peak=%7.1fMB flags=%s" % (
                i, rec["wall_s"], rec["peak_mb"], rec["parsed"]["flags"]))
    encoder_cache().clear()
    with env_set(**{_ENV_ENCODER: "1"}):
        runs_on: List[Dict[str, Any]] = []
        for i in range(args.draws):
            rec = timed_generate(eng, tap, model_id=args.model, prompt=PROMPTS[0],
                                 seed=SEED, preset="final",
                                 out_path=os.path.join(bench_dir, "on_%d.png" % i))
            rec["draw"] = i
            runs_on.append(rec)
            print("[bench] on  draw=%d wall=%6.2fs peak=%7.1fMB enc=%s" % (
                i, rec["wall_s"], rec["peak_mb"], rec["parsed"]["enc"]))

    # ── ③ 像素一致性断言：off[i] 与 on[i+1]（同 seed）必须逐字节相同 ──
    ident: List[Dict[str, Any]] = []
    for i in range(min(len(runs_off), len(runs_on) - 1)):
        a = runs_off[i].get("sha")
        b = runs_on[i + 1].get("sha")
        ident.append({"off": i, "on": i + 1, "same": bool(a and a == b)})
    data["identity"] = ident
    data["identity_all"] = all(x["same"] for x in ident) if ident else None

    summary: Dict[str, Any] = {}
    for name, runs in (("off", runs_off), ("on", runs_on)):
        ok_runs = [r for r in runs if r["ok"] and not r.get("contaminated")]
        summary[name] = {
            "n_ok": len(ok_runs),
            "n_contaminated": len([r for r in runs if r.get("contaminated")]),
            "wall_med": med([r["wall_s"] for r in ok_runs]),
            "wall_first": ok_runs[0]["wall_s"] if ok_runs else None,
            "peak_med": med([r["peak_mb"] for r in ok_runs]),
        }
    if summary["off"]["n_ok"] and summary["on"]["n_ok"]:
        # on 的第 2..N 张才是命中态（第 1 张 miss 要写入）
        hits = [r for r in runs_on if "hit" in r["parsed"]["enc"]]
        summary["hit_wall_med"] = med([r["wall_s"] for r in hits]) if hits else None
        summary["hit_saving_s"] = (round(summary["off"]["wall_med"]
                                         - summary["hit_wall_med"], 2)
                                   if summary.get("hit_wall_med") else None)
        summary["hit_saving_pct"] = (round(
            (summary["off"]["wall_med"] - summary["hit_wall_med"])
            / summary["off"]["wall_med"] * 100, 1)
            if summary.get("hit_wall_med") else None)
    data.update({"runs_off": runs_off, "runs_on": runs_on, "summary": summary,
                 "enc_states_on": [r["parsed"]["enc"] for r in runs_on]})
    path = write_json(tag, data)
    print("\n=== encoder A/B 汇总（%s）===" % args.model)
    print("  off 连抽中位 %ss · on 命中连抽中位 %ss · 省 %s%%" % (
        summary["off"]["wall_med"], summary.get("hit_wall_med"),
        summary.get("hit_saving_pct")))
    print("  编码段：冷 %ss → 暖 %ss（%s×）· 像素一致性：%s" % (
        seg["cold_med"], seg["warm_med"], seg["speedup"],
        "全同" if data["identity_all"] else "有差异（见 JSON）"))
    print("JSON: %s" % path)
    return 0


# ══════════════════════════════ 子命令：lowrank ══════════════════════════════

def cmd_lowrank(args: argparse.Namespace) -> int:
    """低秩三档 × 基线：同 seed 同 prompt，耗时/峰显存/cached_bytes/画质。"""
    tag = "lowrank_%s_%s" % (args.model, _ts())
    setup_env("0", tag)
    tap = install_log_tap()
    ratios = [float(x) for x in args.ratios.split(",") if x.strip()]
    print("[bench] lowrank model=%s preset=%s ratios=%s" % (
        args.model, args.preset, ratios))
    gpu_usable("lowrank")
    eng, li = load_engine(args.model)
    data: Dict[str, Any] = {"phase": "lowrank", "model": args.model,
                            "preset": args.preset, "ratios": ratios,
                            "cuda": cuda_ctx(), "load": li}
    if not li["ok"]:
        data["error"] = "load failed"
        write_json(tag, data)
        return 2

    bench_dir = os.path.join(_ensure_out(), tag)
    os.makedirs(bench_dir, exist_ok=True)
    with env_set(**{_ENV_STEP: "deepcache"}):
        warm = eng.generate(args.model, prompt=PROMPTS[0], negative_prompt=NEG,
                            seed=SEED, preset=args.preset,
                            out_path=os.path.join(bench_dir, "warm.png"))
        print("[bench] warmup(deepcache) ok=%s" % warm.get("ok"))

    configs: Dict[str, List[Dict[str, Any]]] = {}
    for ratio in ratios:
        lr_env = str(ratio) if ratio > 0 else None
        with env_set(**{_ENV_STEP: "deepcache", _ENV_LOWRANK: lr_env}):
            runs: List[Dict[str, Any]] = []
            for pi, prompt in enumerate(PROMPTS[:args.prompts]):
                for si, seed in enumerate([SEED, SEED + 1]):
                    out = os.path.join(bench_dir, "r%s_p%d_s%d.png" % (
                        str(ratio).replace(".", ""), pi, si))
                    rec = timed_generate(eng, tap, model_id=args.model, prompt=prompt,
                                         seed=seed, preset=args.preset, out_path=out)
                    rec.update({"ratio": ratio, "prompt": prompt, "seed": seed})
                    runs.append(rec)
                    st = rec["parsed"]["step_tel"]
                    print("[bench] ratio=%-6s p%d s%d wall=%6.2fs peak=%7.1fMB%s "
                          "cached=%sMB calib=%s" % (
                              ratio, pi, si, rec["wall_s"], rec["peak_mb"],
                              " 污染!" if rec["contaminated"] else "",
                              st["cached_mb"] if st else "?",
                              rec["parsed"]["lowrank"] or "无"))
        configs[str(ratio)] = runs

    # 画质三件套
    pairs = [(r["out"], r["prompt"]) for runs in configs.values() for r in runs
             if r.get("ok") and os.path.isfile(r.get("out", ""))]
    unload_for_clip(eng)
    clip = clip_score_all(pairs)
    for runs in configs.values():
        for r in runs:
            if r.get("ok") and os.path.isfile(r.get("out", "")):
                q = image_quality(r["out"])
                q["clip"] = clip.get(r["out"])
                r["quality"] = q

    per_cfg: Dict[str, Any] = {}
    for ratio_s, runs in configs.items():
        ok_runs = [r for r in runs if r["ok"] and not r.get("contaminated")]
        if not ok_runs:
            per_cfg[ratio_s] = {"n_ok": 0,
                                "n_contaminated": len([r for r in runs
                                                       if r.get("contaminated")])}
            continue
        tels = [r["parsed"]["step_tel"] for r in ok_runs if r["parsed"]["step_tel"]]
        calibs = [c for r in ok_runs for c in r["parsed"]["lowrank"]]
        clips = [r["quality"]["clip"] for r in ok_runs
                 if r.get("quality") and r["quality"].get("clip") is not None]
        per_cfg[ratio_s] = {
            "n_ok": len(ok_runs),
            "n_contaminated": len([r for r in runs if r.get("contaminated")]),
            "wall_med": med([r["wall_s"] for r in ok_runs]),
            "peak_med": med([r["peak_mb"] for r in ok_runs]),
            "cached_mb_med": med([t["cached_mb"] for t in tels]) if tels else None,
            "clip_mean": round(sum(clips) / len(clips), 3) if clips else None,
            "lap_mean": round(sum(r["quality"]["laplacian"] for r in ok_runs
                                  if r.get("quality")) / max(1, len(ok_runs)), 1),
            "calib": calibs[0] if calibs else None,
        }
    base = per_cfg.get(str(ratios[0]), {})
    for _ratio_s, cfg in per_cfg.items():
        if base.get("clip_mean") and cfg.get("clip_mean"):
            cfg["clip_rel_pct"] = round(cfg["clip_mean"] / base["clip_mean"] * 100, 1)
        if base.get("cached_mb_med") and cfg.get("cached_mb_med"):
            cfg["cached_rel_pct"] = round(
                cfg["cached_mb_med"] / base["cached_mb_med"] * 100, 1)
    data.update({"runs": configs, "per_config": per_cfg})
    path = write_json(tag, data)
    print("\n=== lowrank 汇总（%s / %s）===" % (args.model, args.preset))
    print("  %-8s %8s %9s %10s %8s %8s %s" % (
        "ratio", "wall中位", "峰MB", "cachedMB", "CLIP", "CLIP%", "校准"))
    for ratio_s, cfg in per_cfg.items():
        print("  %-8s %8s %9s %10s %8s %8s %s" % (
            ratio_s, cfg.get("wall_med"), cfg.get("peak_med"),
            cfg.get("cached_mb_med"), cfg.get("clip_mean"),
            cfg.get("clip_rel_pct"),
            ("C=%d r=%d e=%.3f" % (cfg["calib"]["C"], cfg["calib"]["r"],
                                   cfg["calib"]["energy"])) if cfg.get("calib") else "-"))
    print("JSON: %s" % path)
    return 0


# ══════════════════════════════ 子命令：fallback ══════════════════════════════

def cmd_fallback(args: argparse.Namespace) -> int:
    """回退路径：mock 注入缓存层故障 + final 档拒例——出图必须不受影响。"""
    from unittest import mock

    tag = "fallback_%s_%s" % (args.model, _ts())
    setup_env("0", tag)
    tap = install_log_tap()
    print("[bench] fallback 验证 model=%s" % args.model)
    gpu_usable("fallback")
    eng, li = load_engine(args.model)
    data: Dict[str, Any] = {"phase": "fallback", "model": args.model,
                            "cuda": cuda_ctx(), "load": li}
    if not li["ok"]:
        data["error"] = "load failed"
        write_json(tag, data)
        return 2
    import app.core.neural.inference_cache as ic

    bench_dir = os.path.join(_ensure_out(), tag)
    os.makedirs(bench_dir, exist_ok=True)
    checks: Dict[str, bool] = {}

    # ① 编码器缓存故障注入（门开）：必须 fallback 回 prompt 原路径且出图成功
    def _boom_cache() -> Any:
        raise RuntimeError("bench mock: encoder_cache 故障注入")

    with mock.patch.object(ic, "encoder_cache", _boom_cache):
        with env_set(**{_ENV_ENCODER: "1"}):
            rec = timed_generate(eng, tap, model_id=args.model, prompt=PROMPTS[0],
                                 seed=SEED, preset="final",
                                 out_path=os.path.join(bench_dir, "fb_enc.png"))
    checks["encoder_mock_still_ok"] = bool(rec["ok"])
    checks["encoder_mock_fallback_flag"] = "enc_fallback" in rec["parsed"]["flags"]
    checks["encoder_mock_no_hit"] = not rec["parsed"]["enc"]
    print("[bench] ① encoder 故障注入：ok=%s flags=%s enc=%s" % (
        rec["ok"], rec["parsed"]["flags"], rec["parsed"]["enc"]))

    # ② 步缓存 attach 故障注入（门开）：必须按不启用继续且出图成功
    class _BoomSC:
        def attach(self, *_a: Any, **_k: Any) -> Dict[str, Any]:
            raise RuntimeError("bench mock: StepFeatureCache.attach 故障注入")

        def activate(self) -> None:
            pass

        def detach(self) -> Dict[str, Any]:
            return {}

    with mock.patch.object(ic, "StepFeatureCache", _BoomSC):
        with env_set(**{_ENV_STEP: "deepcache"}):
            rec2 = timed_generate(eng, tap, model_id=args.model, prompt=PROMPTS[0],
                                  seed=SEED, preset="fast",
                                  out_path=os.path.join(bench_dir, "fb_step.png"))
    checks["step_mock_still_ok"] = bool(rec2["ok"])
    checks["step_mock_attach_fail_flag"] = "step_attach_fail" in rec2["parsed"]["flags"]
    print("[bench] ② step attach 故障注入：ok=%s flags=%s" % (
        rec2["ok"], rec2["parsed"]["flags"]))

    # ③ final 档 + 环境开：门控必须拒（final 永不开），且出图成功
    with env_set(**{_ENV_STEP: "deepcache"}):
        rec3 = timed_generate(eng, tap, model_id=args.model, prompt=PROMPTS[0],
                              seed=SEED, preset="final",
                              out_path=os.path.join(bench_dir, "fb_final.png"))
    checks["final_gate_rejected"] = "step_off" in rec3["parsed"]["flags"]
    checks["final_still_ok"] = bool(rec3["ok"])
    checks["final_no_telemetry"] = rec3["parsed"]["step_tel"] is None
    print("[bench] ③ final 档门控拒例：ok=%s flags=%s tel=%s" % (
        rec3["ok"], rec3["parsed"]["flags"], rec3["parsed"]["step_tel"]))

    # ④ 恢复后同参复跑：步缓存必须能重新挂上（证明 mock 没留下半挂起状态）
    with env_set(**{_ENV_STEP: "deepcache"}):
        rec4 = timed_generate(eng, tap, model_id=args.model, prompt=PROMPTS[0],
                              seed=SEED, preset="fast",
                              out_path=os.path.join(bench_dir, "fb_restore.png"))
    checks["restore_reattached"] = "step_on" in rec4["parsed"]["flags"]
    checks["restore_telemetry"] = rec4["parsed"]["step_tel"] is not None
    print("[bench] ④ mock 拆除后重跑：ok=%s flags=%s tel=%s" % (
        rec4["ok"], rec4["parsed"]["flags"], rec4["parsed"]["step_tel"] is not None))

    data.update({"runs": {"encoder_mock": rec, "step_mock": rec2,
                          "final_gate": rec3, "restore": rec4},
                 "checks": checks, "all_pass": all(checks.values())})
    path = write_json(tag, data)
    print("\n=== fallback 判定 ===")
    for k, v in checks.items():
        print("  %-28s %s" % (k, "PASS" if v else "FAIL"))
    print("总判：%s" % ("ALL PASS" if all(checks.values()) else "有 FAIL"))
    print("JSON: %s" % path)
    return 0 if all(checks.values()) else 1


# ══════════════════════════════ 子命令：recycle ══════════════════════════════

def cmd_recycle(args: argparse.Namespace) -> int:
    """卸载序列标定（设计稿 §5.1「块池」行）：load/unload 循环治碎片死亡。

    背景（2026-10-24 实测教训）：SD1.5 整卡常驻 → unload → 再 load SDXL 曾因显存
    碎片换页卡死 >22min。V4.47.0 把「先 gc 断引用 → synchronize → empty_cache」
    收口为 `release_vram_sequence()`（unload 内调用）。本子命令就是回归标定：
    每循环 = load → 4 步快跑（制造瞬时分配churn）→ unload，量每次耗时与
    卸载后空闲显存——后者不单调下降 = 碎片没有累积。
    """
    tag = "recycle_%s_%s" % (args.model, _ts())
    setup_env("0", tag)
    print("[bench] recycle model=%s cycles=%d" % (args.model, args.cycles))
    gpu_usable("recycle")
    data: Dict[str, Any] = {"phase": "recycle", "model": args.model,
                            "cycles": args.cycles, "cuda": cuda_ctx()}
    import app.core.neural.diffusers_image as DIF

    eng = DIF.get_diffusers_image_engine()
    import torch

    _free0, total = torch.cuda.mem_get_info()
    data["baseline_free_gb"] = round(_free0 / 1024 ** 3, 2)
    cycles: List[Dict[str, Any]] = []
    for i in range(args.cycles):
        t0 = time.time()
        lr = eng.load(args.model)
        load_s = time.time() - t0
        free_after_load, _ = torch.cuda.mem_get_info()
        gen_ok = None
        if lr.get("ok"):
            r = eng.generate(args.model, prompt=PROMPTS[0], negative_prompt=NEG,
                             seed=SEED, steps=4, cfg=7.5, preset="",
                             out_path=os.path.join(_ensure_out(), tag,
                                                   "cyc%d.png" % i))
            gen_ok = bool(r.get("ok"))
        t1 = time.time()
        eng.unload()
        unload_s = time.time() - t1
        free_after_unload, _ = torch.cuda.mem_get_info()
        rec = {"cycle": i, "load_ok": bool(lr.get("ok")), "gen_ok": gen_ok,
               "load_s": round(load_s, 1), "unload_s": round(unload_s, 1),
               "free_after_load_gb": round(free_after_load / 1024 ** 3, 2),
               "free_after_unload_gb": round(free_after_unload / 1024 ** 3, 2)}
        cycles.append(rec)
        print("[bench] cycle=%d load=%.1fs unload=%.1fs gen_ok=%s "
              "卸载后空闲 %.2fGB" % (i, load_s, unload_s, gen_ok,
                                    rec["free_after_unload_gb"]))
    frees = [c["free_after_unload_gb"] for c in cycles if c["load_ok"]]
    loads = [c["load_s"] for c in cycles if c["load_ok"]]
    verdict = {
        "all_load_ok": all(c["load_ok"] for c in cycles),
        "all_gen_ok": all(c["gen_ok"] for c in cycles),
        "max_load_s": max(loads) if loads else None,
        "load_under_60s": bool(loads) and max(loads) < 60.0,
        "free_last": frees[-1] if frees else None,
        "free_first": frees[0] if frees else None,
        "free_decline_gb": (round(frees[0] - frees[-1], 2)
                            if len(frees) >= 2 else None),
        "no_fragmentation_accum": bool(len(frees) >= 2
                                       and (frees[0] - frees[-1]) < 0.5),
    }
    data.update({"cycles": cycles, "verdict": verdict})
    path = write_json(tag, data)
    print("\n=== recycle 判定 ===")
    for k, v in verdict.items():
        print("  %-24s %s" % (k, v))
    print("JSON: %s" % path)
    return 0 if all(verdict.values()) else 1


def cmd_quality(args: Any) -> int:
    """离线补画质分：对已存图目录重跑 Laplacian/人脸/CLIP，不碰 GPU 生成。

    用途：某阶段生成成功但画质段崩了（如 cv2 缺级联文件）时的无损补救；
    CLIP 默认走 CPU，避免与在跑的标定链抢卡。
    """
    d = args.dir
    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    if not pngs:
        print("[bench] 目录无 PNG：%s" % d)
        return 1
    clip = clip_score_all([(p, args.prompt) for p in pngs], device="cpu")
    out: Dict[str, Any] = {}
    for p in pngs:
        q = image_quality(p)
        q["clip"] = clip.get(p)
        out[os.path.basename(p)] = q
        print("[bench] %-14s lap=%8.1f faces=%3d clip=%s" % (
            os.path.basename(p), q["laplacian"], q["faces"], q["clip"]))
    data = {"dir": d, "prompt": args.prompt, "quality": out}
    path = write_json("quality_" + os.path.basename(d.rstrip("/\\")), data)
    print("JSON: %s" % path)
    return 0


def cmd_waitgpu(args: Any) -> int:
    """等到「没有另一个标定在算 + 显存宽裕」再放行（跨会话同机抢卡的唯一防线）。

    2026-10-25 实测：并行会话同机跑 SDXL 标定，两条 6.5GB 管线挤 8GB ⇒
    墙钟出现 12× 异常值（175s vs 14s）且显存被抢到 117MB ⇒ 无报错挂死。
    本命令只在"对手标定进程为空 且 空闲显存 ≥ 阈值"时返回 0，否则等到超时返 4。
    """
    import time

    deadline = time.time() + float(args.timeout)
    while True:
        rivals = [f for f in gpu_foreign_procs() if f.get("kind") == "bench"]
        snap = gpu_snapshot()
        free = snap["free_gb"]
        if not rivals and free is not None and free >= float(args.min_free_gb):
            print("[bench] GPU 可用：空闲 %sGB，无对手标定" % free)
            return 0
        if time.time() > deadline:
            print("[bench] 等不到空闲 GPU（对手标定 %d 个 · 空闲 %sGB · 需 ≥%sGB）"
                  % (len(rivals), free, args.min_free_gb))
            return 4
        print("[bench] 等 GPU：对手标定 %d 个 · 空闲 %sGB（需 ≥%sGB）"
              % (len(rivals), free, args.min_free_gb))
        time.sleep(30)


# ══════════════════════════════ main ══════════════════════════════

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="P0 缓存三件套真机标定")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gate", help="纯函数反例表（无 GPU）")

    p_step = sub.add_parser("step", help="DeepCache A/B")
    p_step.add_argument("--model", default="sdxl-t2i")
    p_step.add_argument("--preset", default="fast")
    p_step.add_argument("--n", type=int, default=3)
    p_step.add_argument("--promote", default="0", choices=["0", "1"])
    p_step.add_argument("--interval", default="",
                        help="覆盖 SHIGUANG_STEP_CACHE_INTERVAL（因果定位用）")
    p_step.add_argument("--branch", default="",
                        help="覆盖 SHIGUANG_STEP_CACHE_BRANCH（跳过的 up_block 起点）")

    p_enc = sub.add_parser("encoder", help="编码器缓存 A/B")
    p_enc.add_argument("--model", default="sdxl-t2i")
    p_enc.add_argument("--draws", type=int, default=4)

    p_lr = sub.add_parser("lowrank", help="低秩三档对比")
    p_lr.add_argument("--model", default="sdxl-t2i")
    p_lr.add_argument("--preset", default="high")
    p_lr.add_argument("--ratios", default="0,0.125,0.25,0.5")
    p_lr.add_argument("--prompts", type=int, default=2)

    p_fb = sub.add_parser("fallback", help="回退路径验证")
    p_fb.add_argument("--model", default="sd15-t2i")

    p_rc = sub.add_parser("recycle", help="卸载序列 load/unload 循环标定")
    p_rc.add_argument("--model", default="sdxl-t2i")
    p_rc.add_argument("--cycles", type=int, default=5)

    p_q = sub.add_parser("quality", help="离线补画质（CLIP 走 CPU，不抢卡）")
    p_q.add_argument("--dir", required=True, help="已存 PNG 的目录")
    p_q.add_argument("--prompt", required=True, help="该批图对应的提示词")

    p_w = sub.add_parser("waitgpu", help="等到没有对手标定且显存宽裕")
    p_w.add_argument("--timeout", type=float, default=900.0)
    p_w.add_argument("--min-free-gb", type=float, default=4.0)

    args = ap.parse_args(argv)
    handlers = {"gate": cmd_gate, "step": cmd_step, "encoder": cmd_encoder,
                "lowrank": cmd_lowrank, "fallback": cmd_fallback,
                "recycle": cmd_recycle, "quality": cmd_quality,
                "waitgpu": cmd_waitgpu}
    t0 = time.time()
    try:
        rc = handlers[args.cmd](args)
    except RuntimeError as e:
        # 目前唯一主动 raise 的场景 = assert_gpu_free 检测到并发占卡
        print("[bench] 拒绝执行（rc=4）：%s" % e)
        return 4
    print("[bench] %s 完成，用时 %.1fs，rc=%d" % (args.cmd, time.time() - t0, rc))
    return rc


if __name__ == "__main__":
    sys.exit(main())
