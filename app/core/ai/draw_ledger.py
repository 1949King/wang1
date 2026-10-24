"""抽卡闭环接线层（Draw Ledger Wiring）
====================================
生成抽卡闭环九层系统的**接线层**：P1 通电（真值分入库）+ P2 推荐回传。
（方案：`docs/_reports/2026-09-27-生成抽卡闭环方案.md` §3.3/§四 P1-P2。）

为什么单独一个模块（而不是塞进 canvas_aigc）：
  ① canvas_aigc.py 已顶到单文件规模守卫的容差上限，任何新增都会破门禁；
     把「种子归一化 + 评分入账 + 推荐查询」抽出来，canvas_aigc 反而变小；
  ② 接线逻辑要能被单测直接调用（不用起 HTTP、不用 mock requests）。

**红线与桶位纪律（本模块最重要的事）**：
- `draw_book` 收代理分（它的设计归宿，方案 §3.1）。
- `quality_prior` **只写 `kind="proxy"` 桶**——`route_mean()` 只读 `"quality"`
  （人工标签真值，见 sampling_review 的 prior_writer）与 `"default"`（可用性），
  **不读 proxy 桶** ⇒ 本批「通电」是**纯记录，零路由影响**，符合方案
  「观察期只记录、不改路由行为」的纪律。AI 打分永不冒充真值（项目红线）。
- proxy 桶攒够样本后是否启用（改 route_mean 考虑 proxy）是**后续独立决策**，
  不在本批自动发生。

纪律：异常绝不抛出（接线失败绝不能拖垮生成主链路）；重依赖（numpy/cv2 经
gen_critic）一律**函数内惰性导入**，避免拖慢画布桥冷启动。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SEED_MAX = 2**31 - 1


def normalize_seed(seed: Any) -> tuple:
    """``(seed_int, explicit)``：显式合法正整数 → 透传；缺省/非法 → 密码学随机。

    （P0a 种子贯通的核心判定；从 canvas_aigc 抽出，避免该文件继续膨胀。）
    """
    try:
        s = int(seed)
    except (TypeError, ValueError):
        s = 0
    if 0 < s <= _SEED_MAX:
        return s, True
    import secrets

    return secrets.randbelow(_SEED_MAX - 1) + 1, False


def feed_draw_ledger(result: Dict[str, Any], *, prompt: str, model: str,
                     size: str = "", channel_id: str = "",
                     seed: Optional[int] = None, seed_sent: bool = False,
                     elapsed_ms: Optional[float] = None,
                     retried: bool = False, kind: str = "image") -> None:
    """生成收尾的一次调用：**先查推荐（P2）→ 再评代理分入账（P1）**。

    两个动作塞进一个函数是有意的：
      ① 调用点只有一处（canvas_aigc 生成收尾），天然覆盖任务化与同步两条路径，
         避免每个调用方各写一遍推荐查询与落账；
      ② **先查后记** ⇒ 回传的推荐不含本次抽卡（等价于「生成前查」），
         这是 §3.3「生成前查，响应附」的意图。

    就地修改 ``result``：
      - ``recommendation``：账本命中时附上（无历史则**不带该字段**）；
      - ``proxy_score`` / ``proxy_detail`` / ``is_proxy``：代理分与红线标注。

    ``seed`` 只在 ``seed_sent=True`` 时入账（渠道没收到的种子无法复现，
    记进 best_seed 是假信息）。异常绝不抛出。
    """
    try:
        data_url = str(result.get("image_data_url") or "")
        if not data_url:
            return

        # ── P2 推荐回传：先查（此时本次尚未入账 ⇒ 推荐不被本次污染）──
        rec = lookup_recommendation(prompt, model, size=size, kind=kind)
        if rec:
            result["recommendation"] = rec

        # ── P1 通电：评代理分 → 账本 + 代理桶 + 回写响应字段 ──
        from app.core.ai.gen_critic import score_image

        scored = score_image(data_url, expected_size=size,
                             elapsed_ms=elapsed_ms, retried=retried)
        score = float(scored.get("score", 0.5))
        result["proxy_score"] = score
        result["proxy_detail"] = scored.get("detail")
        result["is_proxy"] = True

        # P4：免费附上「坏区体检报告」（本地算，几毫秒）。**只报不修**——
        # 修复要走云端 inpaint（花钱），必须由 Agent/用户显式触发。
        try:
            from app.core.ai.inpaint_retry import plan_repair

            result["repair_plan"] = plan_repair(data_url)
        except Exception:
            logger.debug("[draw_ledger] 坏区检测失败（不影响生成）", exc_info=True)

        try:
            from app.core.ai.draw_book import get_store as _draw_store

            _draw_store().record_draw(
                prompt, model, score,
                seed=(seed if (seed is not None and seed_sent) else None),
                size=size, kind=kind)
        except Exception:
            logger.debug("[draw_ledger] 账本落账失败（不影响生成）", exc_info=True)

        try:
            from app.core.ai.quality_prior import get_store as _qp_store

            # kind="proxy"：route_mean 不消费，观察期纯积累（见模块头纪律）
            _qp_store().record_outcome(
                str(channel_id or model or "unknown"), True,
                quality=score, kind="proxy")
        except Exception:
            logger.debug("[draw_ledger] 代理桶落账失败（不影响生成）", exc_info=True)
    except Exception:
        logger.debug("[draw_ledger] 通电失败（不影响生成）", exc_info=True)


def lookup_recommendation(prompt: str, model: str, *, size: str = "",
                          kind: str = "image") -> Optional[Dict[str, Any]]:
    """P2 推荐回传：生成**前**查历史（未受本次抽卡污染）。

    命中返回 ``{"key","mean","n","best_seed","best_score","size","advice"}``；
    无历史返回 None（调用方不得编造推荐字段）。异常绝不抛出。
    """
    try:
        from app.core.ai.draw_book import get_store

        return get_store().recommend(prompt, model, size=size, kind=kind)
    except Exception:
        logger.debug("[draw_ledger] 推荐查询失败（按无推荐处理）", exc_info=True)
        return None


def now_ms() -> float:
    """单调时钟毫秒（供生成耗时统计，测试可 monkeypatch）。"""
    return time.monotonic() * 1000.0


def feed_draw_ledger_local(result: Dict[str, Any], *, prompt: str, model_id: str,
                           engine: str = "", seed: Optional[int] = None,
                           elapsed_ms: Optional[float] = None) -> None:
    """本地生图收尾入账（P0b，2026-10-10）：本地引擎产物 → 闭环。

    为什么单独一个适配函数而不是让调用方各自拼：
      本地双栈引擎返回 ``image_path``/``image_url``（本地文件），而闭环接线层
      :func:`feed_draw_ledger` 只认 ``image_data_url``（gen_critic 要读像素）——
      这正是「本地生图在闭环外」的结构性原因（深潜复核发现，账本只记花钱的半边）。
      此处做一次 文件 → base64 data URL 的适配，两个调用方
      （``capability_handlers.local_generate_image`` 与 ``/host/local-image-generate`` 路由）
      共用，避免各写一遍。

    行为：
      - 就地写 ``result["image_data_url"]`` → 调 :func:`feed_draw_ledger`
        （推荐回传 / proxy_score / repair_plan / 账本落笔全走既有链路）→
        **移除临时 data URL**（本地产物按路径返回，响应不带巨型 base64）；
      - 记账模型名用 ``local/{engine}/{model_id}``（与云渠道 id 命名空间隔离；
        ``local/`` 前缀与 execution_decider 的本地约定一致）。

    纪律：与 feed_draw_ledger 相同——**异常绝不抛出**，入账失败不影响生成主链路。
    """
    try:
        import os as _os

        p = str(result.get("image_path") or "")
        if not p or not _os.path.isfile(p):
            return
        import base64

        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        result["image_data_url"] = f"data:image/png;base64,{b64}"
        try:
            feed_draw_ledger(
                result, prompt=prompt,
                model=f"local/{engine or 'local'}/{model_id}",
                size=f"{result.get('width') or 0}x{result.get('height') or 0}",
                channel_id="", seed=seed, seed_sent=True,
                elapsed_ms=elapsed_ms, kind="image",
            )
        finally:
            # 本地产物按路径返回；data URL 只是入账的临时载体，别留在响应里
            result.pop("image_data_url", None)
    except Exception:
        logger.debug("[draw_ledger] 本地生图入账失败（不影响生成）", exc_info=True)
