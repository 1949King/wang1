# -*- coding: utf-8 -*-
"""「这个模型去哪儿下载」——每行模型的社区入口。

## 为什么单独一个文件

`local_models_panel` 的表格只回答「有没有 / 能不能用」，不回答**「我没有的话去哪拿」**。
用户的诉求是：列表里已经适配过的模型，点一下就能去魔搭 / GitHub 这些社区**自己挑**
（官方全量版、社区剪枝量化版、不同精度版），而不是由程序替他决定下哪个。

所以这里只产出**链接数据**，不做任何下载动作：
程序内下载（`VideoGenEngine.pull()` 那套）仍然保留，作为「懒得挑」时的快捷路径。

## 口径：只给核实过的链接

`VERIFIED_AT` 那天逐个 probe 过，**返回 200 才写进来**：

| 站点 | 核实方式 |
|---|---|
| 魔搭 ModelScope | `GET /api/v1/models/<repo>` → 200 |
| GitHub | `GET https://github.com/<owner>/<name>` → 200 |

没核实过的一律不写。宁可少一个按钮，也不给一个点开是 404 的链接。

## 三个必须说清的事实（别让按钮暗示错东西）

1. **Ollama 不在这条链路上**。它只服务文本/对话模型，生图/生视频的扩散权重它拉不了，
   也没有任何扩散模型在 Ollama 库里。文本模型请走「模型广场」页的 Ollama。
2. **ComfyUI 自己不托管权重**。它是个前端工作流工具，模型照样来自魔搭 / HuggingFace /
   Civitai。所以「去 ComfyUI 下模型」实际上还是去这几个来源下，只是按 ComfyUI 的
   目录结构摆。本项目用的是 diffusers 目录结构，**摆法不一样**：
   ComfyUI 要 `models/checkpoints/xxx.safetensors` 单文件，
   本项目要 `app/models/cache/<目录名>/` 下的 diffusers 目录（含 `model_index.json`）。
   把 ComfyUI 用的单文件塞进本项目目录是**不会**被认出来的。
3. **GitHub 上多数仓库放的是代码，不是权重**。权重通常在 Releases 或另跳 HuggingFace /
   魔搭。按钮的 tooltip 已写明，免得用户点进 GitHub 找不到 .safetensors 就说「骗人」。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("AI短剧编辑器.core.neural.model_sources")

#: 链接核实日期。改链接必须同步改这里，否则测试会拦。
VERIFIED_AT = "2026-11-15"

MODELSCOPE_MODEL_URL = "https://www.modelscope.cn/models/%s"
GITHUB_REPO_URL = "https://github.com/%s"

#: 族 → GitHub 原版仓库（逐个 `GET github.com/...` 核实过 200）
_GITHUB_BY_FAMILY: Dict[str, str] = {
    "sd15": "CompVis/stable-diffusion",
    "sdxl": "Stability-AI/generative-models",
    "svd": "Stability-AI/generative-models",
    "wan": "Wan-Video/Wan2.1",
    "cogvideox": "THUDM/CogVideo",
    "ltx": "Lightricks/LTX-Video",
    "mochi": "genmoai/models",
    "hunyuan": "Tencent-Hunyuan/HunyuanVideo",
    # minimax_h3 没有开放权重，也就没有官方仓库可指
}

#: 按模型 id 细分的覆盖（同族不同版要指不同仓）
_GITHUB_BY_ID: Dict[str, str] = {
    "wan21-t2v-1.3b": "Wan-Video/Wan2.1",
    "wan22-ti2v-5b": "Wan-Video/Wan2.2",
}

#: 族 → 该族代表仓库（只用于「未接入下载器」那种没有具体 id 的行）
_REPRESENTATIVE_MS: Dict[str, str] = {
    "cogvideox": "ZhipuAI/CogVideoX-5b",
    "ltx": "Lightricks/LTX-Video",
    "mochi": "genmo/mochi-1-preview",
    "hunyuan": "Tencent-Hunyuan/HunyuanVideo",
}

_NOTE_MS = "官方/镜像仓；社区剪枝、fp8、GGUF 版多为**同族的独立仓库**，在魔搭搜族名可见"
_NOTE_GH = "原版仓库，权重多在 Releases 或另跳 HuggingFace / 魔搭，不一定有 .safetensors"


def _ms_repo_for(model_id: str, family: str) -> str:
    """模型 id → 魔搭仓库。**只认注册表里写的，不猜。**"""
    for mod, key, field in (
        ("app.core.neural.video_gen", "VIDEO_MODELS", "repo"),
        ("app.core.neural.diffsynth_image", "IMAGE_MODELS", "ms_repo"),
        ("app.core.neural.diffusers_image", "IMAGE_MODELS", "ms_repo"),
        ("app.core.neural.local_family_catalog", "LOCAL_FAMILY_MODELS", "repo"),
    ):
        try:
            mod_obj = __import__(mod, fromlist=["_"])
            spec = (getattr(mod_obj, key, {}) or {}).get(model_id) or {}
            if spec.get(field):
                return str(spec[field])
        except Exception:
            # 某个注册表不可用不影响其它来源，但要留下痕迹便于排查
            logger.debug("[model_sources] 读取 %s 失败（%s）", mod, model_id, exc_info=True)
    return _REPRESENTATIVE_MS.get(family, "")


def _github_for(model_id: str, family: str) -> str:
    if model_id in _GITHUB_BY_ID:
        return _GITHUB_BY_ID[model_id]
    return _GITHUB_BY_FAMILY.get(family, "")


def sources_for(model_id: str, family: str) -> List[Dict[str, str]]:
    """返回 ``[{name, url, note}]``，顺序固定：魔搭在前、GitHub 在后。

    两边都没有就返回空列表 —— **不要伪造一个「搜索页」链接充数**。
    """
    out: List[Dict[str, str]] = []
    ms = _ms_repo_for(model_id, family)
    if ms:
        out.append({
            "name": "魔搭 ModelScope",
            "url": MODELSCOPE_MODEL_URL % ms,
            "note": _NOTE_MS,
        })
    gh = _github_for(model_id, family)
    if gh:
        out.append({
            "name": "GitHub",
            "url": GITHUB_REPO_URL % gh,
            "note": _NOTE_GH,
        })
    return out


def attach_sources(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给 `local_models_view` 的行补上 `sources` 字段（原地改 + 返回）。"""
    for r in rows:
        mid = str(r.get("id") or "")
        # 未接入下载器的行 id 形如 "cogvideox（未接入下载器）"，取族名去查
        if "（" in mid:
            mid = ""
        try:
            r["sources"] = sources_for(mid, str(r.get("family") or ""))
        except Exception:
            r["sources"] = []
    return rows


def community_notes() -> str:
    """面板底部那行说明：把 Ollama / ComfyUI 的边界一次讲清，别让按钮暗示错东西。"""
    return (
        "「社区获取」会在浏览器打开对应仓库页面，由你自己挑官方版或社区剪枝/量化版。"
        "Ollama 只管文本/对话模型（见「模型广场」），拉不了扩散权重；"
        "ComfyUI 自己不托管权重（同样来自魔搭/HF），且它要单文件 checkpoints、"
        "本项目要 diffusers 目录，摆法不能混用。"
    )
