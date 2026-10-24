"""抽卡选优编排（Best-of-N）
================================
把已通电的零件串成闭环的**最后一环**：一次生成 n 张 → 逐张评分 → 取最高 → 全量入账。

为什么单独一个模块
------------------
`canvas_aigc.py` 已顶到单文件规模守卫容差（新增即破门禁）；且本编排是**纯调用编排、
零 HTTP、零重依赖**，独立出来才能被单测直接调用（不起服务、不 mock 网络）。

零件来源（全部已存在，本模块**不重复实现**）
--------------------------------------------
| 环节 | 模块 | 说明 |
|---|---|---|
| 生成 | `canvas_aigc.generate_image_openai_compatible` | 自带 seed 贯通；**收尾已自动调 `feed_draw_ledger`** |
| 评分 | `ai/gen_critic.score_image` | 代理分（5 指标加权 + 崩图闸门），`is_proxy` 恒 True |
| 账本 | `ai/draw_book.record_draw` | 由 `feed_draw_ledger` 在生成收尾写入（代理桶 + best_seed 竞争） |
| 坏区体检 | `ai/inpaint_retry.plan_repair` | 由 `feed_draw_ledger` 附带在结果里（**只报不修，免费**） |

⚠️ **绝不重复记账**：n 张在各自的生成收尾已入账（含代理桶与 best_seed），本模块
只做「评分比较 + 排序 + 返回最优」，**不再调 `feed_draw_ledger` / `record_draw`**
（重复入账会把同一张图重复计样本，污染账本的 EMA 与新鲜度）。

红线
----
1. **代理分不冒充真值**：选优依据是 `proxy_score`，返回恒带 `is_proxy=True` 与白话说明——
   它只用于「筛掉可证伪的坏」（糊、崩、比例错），**不宣称审美判断**。
2. **诚实失败**：全部失败 ⇒ `ok=False` + 逐张原因；部分失败 ⇒ 用成功的选优，
   并**如实报出失败张数与原因**（不掩盖、不补位假图）。
3. **不自动下载、不改路由**（与生成链路同纪律）。
4. **种子可复现**：给了 `base_seed` ⇒ 第 i 张用 `base_seed + i`（互不相同且可复现）；
   没给 ⇒ 由生成层逐张随机，响应里**逐张回传实际 seed**（账本只记渠道真收到的种子）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 单次选优的张数上限：每张都是一次真实云端调用（花钱），不设上限会失控。
# 4 张是本项目的前端叠卡默认（App.tsx count 1~4），6 张留一点余量。
MAX_N = 6
DEFAULT_N = 4


def clamp_n(n: Any) -> tuple:
    """``(n, note)``：把请求张数钳到 [1, MAX_N]；越界时 note 说明（诚实告知，不静默截断）。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = DEFAULT_N
    if v < 1:
        return 1, f"请求张数 {v} 非法 ⇒ 按 1 张处理"
    if v > MAX_N:
        return MAX_N, f"请求张数 {v} 超过单次上限 {MAX_N} ⇒ 按 {MAX_N} 张处理"
    return v, ""


def best_of_n(
    *,
    prompt: str,
    n: Any = DEFAULT_N,
    model: str = "",
    size: str = "",
    channel_id: str = "",
    reference_image: str = "",
    strength: float = 0.65,
    quality: str = "standard",
    aspect: str = "",
    base_seed: Optional[int] = None,
    kind: str = "image",
) -> Dict[str, Any]:
    """一次生成 n 张，按代理分选最优。**不重复记账**（生成收尾已自动入账）。

    返回（恒含 ``ok``）::

        {
          "ok": bool, "requested": n, "generated": k, "failed": f,
          "best": {index, seed, score, image_data_url, size, repair_plan, proxy_detail},
          "candidates": [ {index, seed, score, ok, image_data_url, repair_plan, message} ],
          "is_proxy": True, "advice": "...", "reasons": [...], "message": "..."
        }

    ``best`` 为 None 时 ``ok=False``（全失败）。异常绝不外抛。
    """
    reasons: List[str] = []
    cnt, note = clamp_n(n)
    if note:
        reasons.append(note)
    if not str(prompt or "").strip() and not str(reference_image or "").strip():
        return {"ok": False, "requested": cnt, "generated": 0, "failed": 0,
                "best": None, "candidates": [], "is_proxy": True,
                "advice": "", "reasons": reasons, "message": "需要 prompt（或 reference_image 走图生图）"}

    try:
        from app.core import canvas_aigc as aigc
    except Exception as e:  # pragma: no cover - 依赖缺失时诚实失败
        return {"ok": False, "requested": cnt, "generated": 0, "failed": 0,
                "best": None, "candidates": [], "is_proxy": True, "advice": "",
                "reasons": reasons, "message": f"生成模块不可用: {e}"}

    cands: List[Dict[str, Any]] = []
    for i in range(cnt):
        # 种子策略：有 base_seed ⇒ base_seed+i（可复现且互不相同）；否则 None 交给生成层随机
        seed_arg = (int(base_seed) + i) if base_seed is not None else None
        kw: Dict[str, Any] = {
            "prompt": prompt, "model": model, "size": size, "channel_id": channel_id,
            "reference_image": reference_image, "strength": strength,
            "quality": quality, "seed": seed_arg,
        }
        if aspect:
            kw["aspect"] = aspect
        try:
            res = aigc.generate_image_openai_compatible(**kw)
        except Exception as e:
            logger.debug("[draw_orchestrator] 第 %d 张生成异常", i + 1, exc_info=True)
            res = {"ok": False, "message": f"{type(e).__name__}: {e}"}

        # 代理分：生成收尾（feed_draw_ledger）已给 proxy_score；缺失时本地补算一次
        # （仅为当次排序用，**不再入账**）
        score = res.get("proxy_score")
        if res.get("ok") and score is None:
            try:
                from app.core.ai.gen_critic import score_image

                score = score_image(res.get("image_data_url", ""),
                                    expected_size=str(res.get("size") or size)).get("score")
            except Exception:
                logger.debug("[draw_orchestrator] 补算代理分失败", exc_info=True)
        cands.append({
            "index": i,
            "ok": bool(res.get("ok")),
            "seed": res.get("seed"),
            "seed_sent": bool(res.get("seed_sent")),
            "score": float(score) if isinstance(score, (int, float)) else None,
            "size": str(res.get("size") or size or ""),
            "image_data_url": str(res.get("image_data_url") or ""),
            "repair_plan": res.get("repair_plan"),
            "proxy_detail": res.get("proxy_detail"),
            "recommendation": res.get("recommendation"),
            "message": str(res.get("message") or ""),
        })

    ok_cands = [c for c in cands if c["ok"] and c["image_data_url"]]
    failed = [c for c in cands if not (c["ok"] and c["image_data_url"])]
    if failed:
        reasons.append(f"{len(failed)}/{cnt} 张失败：" + "；".join(
            str(c.get("message") or "未知原因")[:60] for c in failed[:3]))
    if not ok_cands:
        return {"ok": False, "requested": cnt, "generated": 0, "failed": len(failed),
                "best": None, "candidates": cands, "is_proxy": True, "advice": "",
                "reasons": reasons, "message": "全部生成失败（无任何可用候选）"}

    # 排序：代理分降序；无分的排最后（并在 advice 里说明）
    scored = [c for c in ok_cands if c["score"] is not None]
    unscored = [c for c in ok_cands if c["score"] is None]
    scored.sort(key=lambda c: c["score"], reverse=True)
    best = (scored or unscored)[0]
    if unscored:
        reasons.append(f"{len(unscored)} 张无代理分（按原顺序垫后，未被优先选中）")

    advice = "选优依据为**代理分**（几何/清晰度/崩图闸门），非审美真值，仅供参考"
    if best.get("repair_plan", {}).get("needs_repair") if isinstance(best.get("repair_plan"), dict) else False:
        advice += "；最优候选仍有局部坏区，可调 repair_image 局部重绘（只重画坏区，不重抽）"

    logger.info("[draw_orchestrator] best-of-%d 完成：成功 %d / 失败 %d，最优 index=%d score=%s",
                cnt, len(ok_cands), len(failed), best["index"], best.get("score"))
    return {
        "ok": True,
        "requested": cnt, "generated": len(ok_cands), "failed": len(failed),
        "api_calls": cnt,  # 成本透明：每次调用都是真实云端额度
        "best": best,
        "candidates": cands,
        "is_proxy": True,
        "advice": advice,
        "reasons": reasons,
        "message": (f"生成 {len(ok_cands)}/{cnt} 张，最优 index={best['index']}"
                    f"（代理分 {best.get('score')}）"),
    }
