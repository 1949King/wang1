"""局部重绘（Inpaint Retry）
====================================
生成抽卡闭环九层系统 · P4「局部重绘策略」
（方案：`docs/_reports/2026-09-27-生成抽卡闭环方案.md` §四 P4。）

**要解决的问题**：抽到一张「90% 完好 + 一角糊了」的图，现在的做法是**整张重抽**——
既花钱，又赌运气（重抽可能整张都不如原图）。正解是**只修坏区**。

链路（全部纯函数 + 可注入，便于单测）：

```
locate_bad_regions（gen_critic 逐格评）→ build_mask（白=待修）
      → inpaint_via_host（现有入口，不新增引擎）
      → composite（**坏区外像素 bit-exact 取自原图**）
      → 复评（score_image 前后对比）
```

**「原满意区域像素不变」是硬承诺**：inpaint 端点返回的是**整图**，直接用它
等于整张被洗过一遍。所以必须合成——只把蒙版区取新图，其余像素逐字节保留原图
（由 `composite` 保证，测试用 `np.array_equal` 钉死）。

**成本纪律（重要）**：检测是自动的（免费，本地算），但**修复必须显式触发**——
inpaint 要走一次云端 API（花钱）。因此生成链路只回传 `repair_plan`
（坏区 + 是否需要修），**不自动修**；由 Agent/用户决定是否花这次钱。

纪律：纯逻辑 + 惰性导入重依赖；异常不抛出（返回 ok=False 与原因）。
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:  # 与 gen_critic 同款：极端环境下解码时才失败
    cv2 = None  # type: ignore

DEFAULT_GRID = 4          # 坏区检测网格
DEFAULT_THRESHOLD = 0.35  # 低于此的格判为坏区（与 gen_critic 默认一致）
DEFAULT_PAD = 8           # 蒙版外扩（给重绘留过渡带）
MASK_INPAINT_VALUE = 255  # 白 = 待修复（cv2.inpaint / edits 端点惯例）


def _imdecode(image: Any) -> Optional[np.ndarray]:
    """与 gen_critic 同款解码（含中文路径 open()+imdecode 绕行）。"""
    if isinstance(image, np.ndarray):
        return image if image.size else None
    if cv2 is None:
        return None
    try:
        if isinstance(image, (bytes, bytearray)):
            return cv2.imdecode(np.frombuffer(bytes(image), dtype=np.uint8),
                                cv2.IMREAD_UNCHANGED)
        if isinstance(image, str):
            s = image.strip()
            if s.startswith("data:") and "," in s:
                payload = "".join(s.split(",", 1)[1].split())
                return cv2.imdecode(
                    np.frombuffer(base64.b64decode(payload), dtype=np.uint8),
                    cv2.IMREAD_UNCHANGED)
            if s and len(s) < 1024:
                with open(s, "rb") as fp:
                    buf = np.frombuffer(fp.read(), dtype=np.uint8)
                return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED) if buf.size else None
    except Exception:
        logger.debug("[inpaint_retry] 解码失败", exc_info=True)
    return None


def _to_data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG 编码失败")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def _clamp_box(box: Tuple[int, int, int, int], w: int, h: int,
               pad: int) -> Tuple[int, int, int, int]:
    x, y, bw, bh = (int(v) for v in box)
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + bw + pad)
    y1 = min(h, y + bh + pad)
    return x0, y0, x1, y1


def build_mask(image: Any, boxes: List[Dict[str, Any]], *,
               pad: int = DEFAULT_PAD) -> str:
    """按坏区生成蒙版 PNG data URL：白=待修复、黑=保留。失败抛 ValueError。"""
    img = _imdecode(image)
    if img is None:
        raise ValueError("蒙版生成失败：原图无法解码")
    h, w = int(img.shape[0]), int(img.shape[1])
    mask = np.zeros((h, w), dtype=np.uint8)
    for b in boxes or []:
        box = b.get("box") if isinstance(b, dict) else b
        try:
            x0, y0, x1, y1 = _clamp_box(box, w, h, pad)
        except Exception:
            continue
        mask[y0:y1, x0:x1] = MASK_INPAINT_VALUE
    return _to_data_url(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))


def composite(original: Any, inpainted: Any, boxes: List[Dict[str, Any]], *,
              pad: int = DEFAULT_PAD) -> str:
    """**只把坏区**取重绘图，其余像素逐字节保留原图（P4 的硬承诺）。

    重绘图尺寸与不一致时会先 resize 到原图尺寸（端点有时返回不同分辨率）；
    尺寸一致时不 resize，避免无谓的重采样。
    """
    src = _imdecode(original)
    dst = _imdecode(inpainted)
    if src is None:
        raise ValueError("合成失败：原图无法解码")
    if dst is None:
        raise ValueError("合成失败：重绘图无法解码")
    h, w = int(src.shape[0]), int(src.shape[1])
    if dst.shape[:2] != (h, w):
        dst = cv2.resize(dst, (w, h), interpolation=cv2.INTER_LANCZOS4)
    if dst.ndim == 2:
        dst = cv2.cvtColor(dst, cv2.COLOR_GRAY2BGR)
    if src.ndim == 2:
        src = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    if dst.shape[2] == 4:
        dst = dst[:, :, :3]
    if src.shape[2] == 4:
        src = src[:, :, :3]
    out = src.copy()
    for b in boxes or []:
        box = b.get("box") if isinstance(b, dict) else b
        try:
            x0, y0, x1, y1 = _clamp_box(box, w, h, pad)
        except Exception:
            continue
        out[y0:y1, x0:x1] = dst[y0:y1, x0:x1]  # 坏区取新图，其余保持 src
    return _to_data_url(out)


def plan_repair(image: Any, *, grid: int = DEFAULT_GRID,
                threshold: float = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """只看不修：返回 ``{"needs_repair": bool, "boxes": [...], "count": int}``。

    生成链路用它回传 ``repair_plan``（免费）——花不花这次 inpaint 的钱由人定。
    """
    try:
        from app.core.ai.gen_critic import locate_bad_regions

        boxes = locate_bad_regions(image, grid=grid, threshold=threshold)
    except Exception:
        logger.debug("[inpaint_retry] 坏区检测失败（按无需修复处理）", exc_info=True)
        boxes = []
    return {"needs_repair": bool(boxes), "boxes": boxes, "count": len(boxes)}


def repair_image(image: Any, *, prompt: str, model: str = "", channel_id: str = "",
                 size: str = "", grid: int = DEFAULT_GRID,
                 threshold: float = DEFAULT_THRESHOLD, pad: int = DEFAULT_PAD,
                 inpaint_fn: Optional[Callable[..., Dict[str, Any]]] = None
                 ) -> Dict[str, Any]:
    """定位坏区 → 蒙版 → 局部重绘 → 合成 → 前后复评。

    返回 ``{"ok", "repaired", "image_data_url", "boxes", "before_score",
    "after_score", "used", "message"}``。
    - 无坏区 ⇒ ``ok=True, repaired=False``（**不发任何请求**，不烧钱）
    - inpaint 失败 ⇒ ``ok=False``（**诚实失败，不伪造图**；是否整张重抽由调用方定）
    - ``inpaint_fn`` 可注入（测试不真调网络）；默认惰性拿 ``inpaint_via_host``
    """
    plan = plan_repair(image, grid=grid, threshold=threshold)
    if not plan["needs_repair"]:
        return {"ok": True, "repaired": False, "boxes": [],
                "message": "无坏区，无需局部重绘"}

    boxes = plan["boxes"]
    try:
        mask_url = build_mask(image, boxes, pad=pad)
    except Exception as e:
        return {"ok": False, "repaired": False, "boxes": boxes,
                "message": f"蒙版生成失败: {e}"}

    if inpaint_fn is None:
        try:
            from app.core.canvas_aigc import inpaint_via_host as inpaint_fn  # type: ignore
        except Exception as e:
            return {"ok": False, "repaired": False, "boxes": boxes,
                    "message": f"inpaint 入口不可用: {e}"}

    try:
        res = inpaint_fn(prompt=prompt, image=image, mask=mask_url,
                         model=model, channel_id=channel_id, size=size)
    except Exception as e:
        logger.debug("[inpaint_retry] inpaint 调用异常", exc_info=True)
        return {"ok": False, "repaired": False, "boxes": boxes,
                "message": f"inpaint 调用异常: {e}"}

    if not isinstance(res, dict) or not res.get("ok"):
        return {"ok": False, "repaired": False, "boxes": boxes,
                "message": str((res or {}).get("message") or "inpaint 失败")}

    src_url = res.get("image_data_url") or res.get("image_url") or ""
    try:
        merged = composite(image, src_url, boxes, pad=pad)
    except Exception as e:
        return {"ok": False, "repaired": False, "boxes": boxes,
                "message": f"合成失败: {e}"}

    def _score(u: str) -> Optional[float]:
        try:
            from app.core.ai.gen_critic import score_image

            return float(score_image(u).get("score", 0.5))
        except Exception:
            return None

    return {
        "ok": True,
        "repaired": True,
        "image_data_url": merged,
        "boxes": boxes,
        "before_score": _score(image),
        "after_score": _score(merged),
        "used": "inpaint",
        "channel_id": res.get("channel_id") or channel_id,
        "message": f"局部重绘完成（{len(boxes)} 个坏区；坏区外像素保持原样）",
    }
