# -*- coding: utf-8 -*-
"""本地开源视频模型「族的下载源」登记表。

## 为什么单独一个文件

`neural/video_gen.py` 的 `VIDEO_MODELS` 只登记了 **3 个能跑通的模型**
（svd / wan2.2 / wan2.1），因为它们带 `pipeline` 类名 + 已验证的显存策略。
`local_video_infer.py` 能通过 `PIPELINE_CLASS_MAP` 加载 cogvideox / hunyuan /
ltx / mochi / minimax_h3 五族，但**从没有登记过下载源** ⇒ 用户问「怎么拉」时
只能答「拉不了」，说不出为什么。

本表补的就是这一块：**只登记能核实的事实**（repo 是否存在、真实体积多大、
是不是 diffusers 格式），不登记「大概能跑」这种话。

## 数据来源与口径（2026-11-15 实测）

- repo 是否存在：`GET https://www.modelscope.cn/api/v1/models/<owner>/<name>` 返回 200
- 体积：`GET .../repo/files?Revision=master&Recursive=True` 逐文件 `Size` 求和
  - `full_repo_gb` = 整仓全部文件（含 media/、13B 单文件等**下载时不该要**的东西）
  - `subset_gb` = 只取 diffusers 标准子目录（`model_index.json` / `scheduler` /
    `tokenizer` / `text_encoder` / `transformer` / `vae`）后的体积，**这才是下载量**
- `ram_gb` 是**估算**（`subset_gb × 1.3` 取整，给激活值和 offload 余量），
  **不是实测**。真跑过之后必须换成实测值并去掉 `estimated` 标记。

## 三条别踩的线

1. **minimax_h3 没有开放权重**：`MiniMax/MiniMax-Hailuo`、`MiniMax/MiniMaxH3`、
   `AI-ModelScope/MiniMax-H3`、`MiniMax/MiniMax-Hailuo-02` 全部 404。
   `PIPELINE_CLASS_MAP` 里的 `MiniMaxH3ModularPipeline` 是给**已拿到权重的人**用的，
   不是「能下载」的意思。
2. **hunyuan 的 ModelScope 仓不是 diffusers 格式**：`Tencent-Hunyuan/HunyuanVideo`
   里是 `hunyuan-video-t2v-720p/transformers/mp_rank_00_model_states.pt`，
   没有 `model_index.json` ⇒ `HunyuanVideoPipeline.from_pretrained()` 直接失败。
   要能一键下载必须先转 diffusers 布局，属另一件事 ⇒ 本表 `pull=False`。
3. **ltx / mochi 的整仓体积包含大量用不上的东西**（LTX 236.7GB 里只有 26.5GB 是
   diffusers 子集；Mochi 124.3GB 里有些是重复的 bf16 分片）
   ⇒ pull 必须带 `allow_patterns`，不能整仓拖。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 下载时只取这些顶层路径（diffusers 标准布局 + 根配置）
DIFFUSERS_PATTERNS: List[str] = [
    "model_index.json",
    "scheduler/*",
    "tokenizer/*",
    "text_encoder/*",
    "transformer/*",
    "vae/*",
]

LOCAL_FAMILY_MODELS: Dict[str, Dict[str, Any]] = {
    "cogvideox-2b": {
        "kind": "cogvideox",
        "label": "CogVideoX-2B（文生视频，本表里最轻的一档）",
        "repo": "ZhipuAI/CogVideoX-2b",
        "pipeline": "CogVideoXPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 12.8,
        "subset_gb": 12.8,
        "vram_gb": 8.0,
        "ram_gb": 17,
        "license": "Apache-2.0",
        "pull": True,
        "note": "diffusers 布局完整，可一键下载；权重 12.8GB ≈ 本机内存上限，能不能跑要实测",
    },
    "cogvideox-5b": {
        "kind": "cogvideox",
        "label": "CogVideoX-5B（质量更好，内存要求翻倍）",
        "repo": "ZhipuAI/CogVideoX-5b",
        "pipeline": "CogVideoXPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 20.1,
        "subset_gb": 20.1,
        "vram_gb": 8.0,
        "ram_gb": 26,
        "license": "CogVideoX 自定义许可（非商用限制，先读 LICENSE）",
        "pull": True,
        "note": "权重 20.1GB > 本机 15.3GB 内存，纯 offload 也装不下",
    },
    "ltx-video-13b": {
        "kind": "ltx",
        "label": "LTX-Video 13B（diffusers 主干）",
        "repo": "Lightricks/LTX-Video",
        "pipeline": "LTXPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 236.7,
        "subset_gb": 26.5,
        "vram_gb": 12.0,
        "ram_gb": 35,
        "license": "LTX 自定义许可（先读 LICENSE）",
        "pull": True,
        "note": "整仓 236.7GB 里 210GB 是 13B 单文件权重和 media/，必须按子集拉",
    },
    "ltx-video-095": {
        "kind": "ltx",
        "label": "LTX-Video 0.9.5（diffusers 主干）",
        "repo": "Lightricks/LTX-Video-0.9.5",
        "pipeline": "LTXPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 23.9,
        "subset_gb": 23.6,
        "vram_gb": 12.0,
        "ram_gb": 31,
        "license": "LTX 自定义许可（先读 LICENSE）",
        "pull": True,
        "note": "体积比 13B 那版小一点，但仍超过本机内存",
    },
    "mochi-1-preview": {
        "kind": "mochi",
        "label": "Mochi 1 preview（10B，开源里较大的一档）",
        "repo": "genmo/mochi-1-preview",
        "pipeline": "MochiPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 124.3,
        "subset_gb": 85.2,
        "vram_gb": 24.0,
        "ram_gb": 111,
        "license": "Apache-2.0",
        "pull": True,
        "note": "子集 85.2GB：本机磁盘够，内存差一个数量级",
    },
    "hunyuan-video": {
        "kind": "hunyuan",
        "label": "HunyuanVideo 13B（原版布局，需先转 diffusers）",
        "repo": "Tencent-Hunyuan/HunyuanVideo",
        "pipeline": "HunyuanVideoPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 37.1,
        "subset_gb": 0.0,  # 非 diffusers 布局 ⇒ 没有可用的子集
        "vram_gb": 24.0,
        "ram_gb": 48,
        "license": "腾讯混元社区许可（先读 LICENSE）",
        "pull": False,
        "no_pull_reason": (
            "ModelScope 仓是原版布局（hunyuan-video-t2v-720p/transformers/"
            "mp_rank_00_model_states.pt），没有 model_index.json，"
            "HunyuanVideoPipeline.from_pretrained() 会直接失败；"
            "要一键下载得先做布局转换"
        ),
        "note": "权重 37.1GB，且格式不符",
    },
    "minimax-h3": {
        "kind": "minimax_h3",
        "label": "MiniMax H3 / Hailuo（**无开放权重**）",
        "repo": "",
        "pipeline": "MiniMaxH3ModularPipeline",
        "modes": ["t2v"],
        "full_repo_gb": 0.0,
        "subset_gb": 0.0,
        "vram_gb": 0.0,
        "ram_gb": 0,
        "license": "闭源，仅 API",
        "pull": False,
        "no_pull_reason": (
            "ModelScope 上 MiniMax/MiniMax-Hailuo、MiniMax/MiniMaxH3、"
            "AI-ModelScope/MiniMax-H3、MiniMax/MiniMax-Hailuo-02 全部 404；"
            "官方只有 API，没有放出权重 ⇒ 本地这条路不存在，不是没适配"
        ),
        "note": "PIPELINE_CLASS_MAP 里那一项只对「已自行拿到权重」的人有意义",
    },
}

# 体积与 repo 的核实日期。改表时必须同步改这里，否则测试会拦。
CATALOG_MEASURED_AT = "2026-11-15"
CATALOG_MEASURED_FROM = "modelscope.cn /repo/files?Revision=master&Recursive=True"


def pullable_ids() -> List[str]:
    """能一键下载的 id（`pull=True` 且有 repo）。"""
    return [
        mid
        for mid, spec in LOCAL_FAMILY_MODELS.items()
        if spec.get("pull") and spec.get("repo")
    ]


def spec_of(model_id: str) -> Optional[Dict[str, Any]]:
    return LOCAL_FAMILY_MODELS.get(model_id)


def public_list() -> List[Dict[str, Any]]:
    """给 UI / 检查器用的扁平列表（含不可下载项与原因，别静默吞）。"""
    out: List[Dict[str, Any]] = []
    for mid, spec in LOCAL_FAMILY_MODELS.items():
        out.append(
            {
                "id": mid,
                "kind": spec["kind"],
                "label": spec["label"],
                "repo": spec.get("repo") or "",
                "download_gb": spec.get("subset_gb") or 0.0,
                "full_repo_gb": spec.get("full_repo_gb") or 0.0,
                "vram_gb": spec.get("vram_gb") or 0.0,
                "ram_gb": spec.get("ram_gb") or 0,
                "license": spec.get("license") or "",
                "pullable": bool(spec.get("pull") and spec.get("repo")),
                "no_pull_reason": spec.get("no_pull_reason") or "",
                "note": spec.get("note") or "",
                "measured_at": CATALOG_MEASURED_AT,
                "ram_gb_estimated": True,
            }
        )
    return out


def download(model_id: str, progress_cb=None) -> Dict[str, Any]:
    """下载某个族模型到 `app/models/cache/<repo 去斜杠>/`。**异常绝不外抛。**

    落盘目录名含族关键词（如 `ZhipuAI_CogVideoX-2b`），
    `local_video_infer._scan_local_models()` 才能认出来 —— 这是刻意对齐的。
    """
    spec = LOCAL_FAMILY_MODELS.get(model_id)
    if not spec:
        return {
            "ok": False,
            "model_id": model_id,
            "message": f"未知 id（可选：{', '.join(LOCAL_FAMILY_MODELS)}）",
        }
    if not spec.get("pull") or not spec.get("repo"):
        return {
            "ok": False,
            "model_id": model_id,
            "message": spec.get("no_pull_reason") or "该模型不提供一键下载",
        }
    try:
        from app.core.neural_engine import get_neural_engine

        eng = get_neural_engine()
        path = eng.download_snapshot(
            spec["repo"],
            allow_patterns=DIFFUSERS_PATTERNS,
            progress_cb=progress_cb,
            max_workers=4,
        )
    except Exception as e:  # 下载入口必须诚实失败，绝不外抛
        return {
            "ok": False,
            "model_id": model_id,
            "message": f"下载异常：{type(e).__name__}: {e}",
        }
    if not path:
        return {
            "ok": False,
            "model_id": model_id,
            "message": "HF 与 ModelScope 都失败（网络或仓库权限）",
        }
    return {
        "ok": True,
        "model_id": model_id,
        "path": path,
        "message": f"已下载到 {path}",
    }
