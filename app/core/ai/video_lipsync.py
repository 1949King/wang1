# -*- coding: utf-8 -*-
"""真人视频级对口型（video lip-sync）—— 把真人视频的嘴型重画成匹配新音频（2026-10-09，刀 T3）。

⚠️ 与已有 `app/core/lip_sync.py` 的边界（**别重复造**）
====================================================
| 模块 | 层次 | 产物 |
|---|---|---|
| `lip_sync.py`（已有，816 行） | 嘴型**参数动画** | 音频 → blendshape/viseme 权重，驱动 **3D 数字人 / 卡通** |
| 本模块 | **真人视频级**对口型 | MuseTalk / LatentSync 扩散模型，重画**真人视频**嘴型匹配新音频 |

两者是不同层次的产物，短剧主流是真人实拍素材 ⇒ 本模块补的正是这块空白。

诚实降级链（本模块的红线）
==========================
对口型是**重生成类**操作，模型/算力不满足时**绝不能假装同步了**。三级降级，逐级诚实：

    ① video_sync    真人视频对口型（MuseTalk → LatentSync）
    ② dub_only      只换音、不換口型（产物**必须**标 `is_ai_redub=True`）
    ③ subtitle_only 纯配音 + 叠字幕（口型与画面完全不动）

`decide_path()` 是**纯函数**，把「引擎可用性 + 是否真人素材」映射成上面三级之一；
它可被单测直接覆盖 —— 这是"降级不撒谎"的机器化表达。

模型与引擎（后装，与 funasr / CosyVoice 统一安装）
================================================
· 首选 MuseTalk（消费级显卡 6G+、实时）；质量天花板 LatentSync 1.5（16G+）。
· 引擎未装时 `sync_video()` **诚实失败**（`{ok: False, available: False, reason}`），
  不返回假视频、不把「只换音」冒充成「已对口型」。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 三级降级路径（decide_path 的合法取值）
PATH_VIDEO_SYNC = "video_sync"
PATH_DUB_ONLY = "dub_only"
PATH_SUBTITLE_ONLY = "subtitle_only"

# 偏好顺序：MuseTalk 优先（低显存），LatentSync 兜底（高质量）
PREFERRED_ENGINES = ["musetalk", "latentsync"]


@dataclass
class LipSyncVideoRequest:
    """一次真人视频对口型请求。"""
    video_path: str
    audio_path: str
    # 可选人脸框（x,y,w,h 归一化到 0~1）；None = 全图自动检测
    face_region: Optional[List[float]] = None
    # 是否已知是真人素材（None = 未知，交给 decide_path 判断）
    is_real_person: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LipSyncResult:
    """对口型/降级结果（诚实标记）。"""
    ok: bool
    path: str                 # video_sync / dub_only / subtitle_only
    output_video: str = ""
    is_ai_redub: bool = False  # 是否为「AI 重配」（换音/对口型都必须标，沿用诚实原则）
    reason: str = ""           # 不可用/降级原因
    engine: str = ""           # 实际引擎（空 = 未用引擎）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── 能力检测（只检测依赖，不下载模型）────────────────────────────

def video_lipsync_available() -> bool:
    """真人视频对口型引擎是否可 import。"""
    for mod in PREFERRED_ENGINES:
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


def unavailable_reason() -> str:
    """诚实报告为什么不可用。"""
    if video_lipsync_available():
        return "对口型引擎已安装，但模型可能未下载；首次调用会拉取模型，请保证网络与磁盘。"
    return ("缺少本地真人视频对口型引擎（MuseTalk / LatentSync）。"
            "安装后即可把真人视频嘴型重画成匹配新音频。"
            "在装好之前，本功能**诚实降级**为「只换音不換口型」或「纯配音叠字幕」，不会冒充已同步。")


def decide_path(*, engine_available: bool, is_real_person: bool = True) -> str:
    """**纯函数**：决定走哪条降级路径。

    规则：
      · 引擎可用 且 真人素材 ⇒ `video_sync`（真对口型）
      · 引擎不可用 但 真人素材 ⇒ `dub_only`（只换音，标 AI 重配）
      · 非真人素材（3D/卡通）⇒ 不适用本模块 —— 交给已有的 `lip_sync.py`（blendshape）
        这里返回 `dub_only` 作为**兜底**（至少换音），但调用方应优先走 lip_sync.py。
    """
    if engine_available and is_real_person:
        return PATH_VIDEO_SYNC
    return PATH_DUB_ONLY


def sync_video(request: LipSyncVideoRequest) -> LipSyncResult:
    """主入口：真人视频对口型（**诚实失败 + 三级降级**）。

    引擎未装 ⇒ 直接落到 `dub_only` 并如实说明；引擎在位 ⇒ 后续刀接真模型。
    """
    eng_ok = video_lipsync_available()
    path = decide_path(engine_available=eng_ok,
                       is_real_person=request.is_real_person is not False)
    if path == PATH_VIDEO_SYNC:
        # 引擎在库但未接线（后续刀实现真推理）⇒ 诚实说明，不假成功
        return LipSyncResult(ok=False, path=path, is_ai_redub=True,
                             engine="", reason="引擎在库但尚未接线（后续刀实现真推理）")
    # dub_only：只换音不換口型 —— 诚实标注 AI 重配
    return LipSyncResult(ok=False, path=path, is_ai_redub=True,
                         reason=unavailable_reason())
