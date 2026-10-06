"""生成品代理评分（Gen Critic）
====================================
生成抽卡闭环九层系统 · 第⑤层「多候选+选优」与账本通电的评分来源
（方案：`docs/_reports/2026-09-27-生成抽卡闭环方案.md` §3.2，2026-09-27 用户裁定执行）。

**红线（项目铁律「AI 打分禁当真值」）**：
本模块输出**恒带 ``is_proxy: True``**——它是「可测代理指标」的加权分，
不是审美客观分。任何下游（账本 EMA、路由 q̂、推荐 advice）都不得把它
当审美真值；它只负责把「崩图/糊图/尺寸错」这类**可证伪的坏**筛出来。

指标与权重（§3.2 裁定）：

| 指标 | 方法 | 权重 | 治什么 |
|---|---|---|---|
| 非崩图 | 灰度std / 极端像素占比 / 色彩直方图熵 | 0.35 | 生成失败、糊成一片、纯黑纯白 |
| 清晰度 | 拉普拉斯方差（灰度） | 0.25 | 糊图 |
| 尺寸达标 | 与请求 size 一致性 | 0.20 | 参数未生效 |
| 构图中心度 | 中心区 vs 全局灰度 std 比 | 0.10 | 大面积留白/空中心 |
| 生成成本信号 | 耗时 / 是否重试 | 0.10 | 抽卡效率 |

崩图闸门：非崩图分 < 0.2 时总分封顶 0.3（崩图一票否决，不让清晰度等指标
把崩图总分拉回中位）。

纪律：纯模块（不 import app 包）；只依赖 numpy + cv2（项目既有依赖，
见 preview_manager 的 filter2D 用法）；评分失败返回中性 0.5 并在
detail 标注 decode_error，**绝不抛出**（不能拖垮生成主链路）。
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:  # 极端精简环境下允许导入模块，解码时才报错
    cv2 = None  # type: ignore

# 权重（§3.2 裁定格）
_W_BROKEN = 0.35
_W_SHARP = 0.25
_W_SIZE = 0.20
_W_COMPOSE = 0.10
_W_COST = 0.10

# 阈值常数（代理启发值，非审美标准；调整需同步本注释与测试）
_STD_FLAT = 8.0        # 灰度 std 低于此 ≈ 单色/崩图
_STD_FULL = 30.0       # 灰度 std 达到此 ≈ 对比度正常
_EXTREME_BAD = 0.98    # 纯黑(<8)/纯白(>247) 像素占比高于此 ≈ 崩图
_ENTROPY_FULL = 6.0    # 4bit×3 色彩直方图熵达到此（bits）≈ 色彩丰富
_LAP_FULL = 250.0      # 拉普拉斯方差达到此 ≈ 清晰
_BROKEN_GATE = 0.2     # 非崩图分低于此 → 总分封顶 0.3
_BROKEN_CAP = 0.3
_COST_GOOD_MS = 15000.0   # 耗时 ≤15s 不扣分
_COST_BAD_MS = 120000.0   # 耗时 ≥120s 扣到底


def _decode(image: Any) -> Optional[np.ndarray]:
    """统一解码为 ndarray（HxW 灰度 或 HxWxC）。失败返回 None。

    支持：np.ndarray 直传 / bytes（PNG/JPG 编码）/ str（data URL 或文件路径）。
    """
    if isinstance(image, np.ndarray):
        return image if image.size else None
    if cv2 is None:
        return None
    try:
        if isinstance(image, (bytes, bytearray)):
            buf = np.frombuffer(bytes(image), dtype=np.uint8)
            return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        if isinstance(image, str):
            s = image.strip()
            if s.startswith("data:") and "," in s:
                payload = "".join(s.split(",", 1)[1].split())
                buf = np.frombuffer(base64.b64decode(payload), dtype=np.uint8)
                return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
            if s and len(s) < 1024:  # 文件路径
                # cv2.imread / np.fromfile 在 Windows 非 ASCII 路径（如
                # D:\拾光剪影）都会失败——Python open() 支持 Unicode 路径，
                # 读出字节再 imdecode（OpenCV 中文路径标准解法）
                with open(s, "rb") as fp:
                    buf = np.frombuffer(fp.read(), dtype=np.uint8)
                return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED) if buf.size else None
    except Exception:
        logger.debug("[gen_critic] 图像解码失败", exc_info=True)
    return None


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:  # BGRA → BGR
        img = img[:, :, :3]
    if cv2 is not None:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 无 cv2 兜底：标准亮度加权（通道序不影响评分的相对结论）
    return (0.114 * img[:, :, 0] + 0.587 * img[:, :, 1]
            + 0.299 * img[:, :, 2]).astype(np.uint8)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _score_non_broken(img: np.ndarray, gray: np.ndarray) -> Tuple[float, Dict[str, Any]]:
    """非崩图：灰度 std / 极端像素占比 / 色彩熵，三者取最弱（任一崩即崩）。"""
    std = float(gray.std())
    std_score = _clamp01((std - _STD_FLAT) / (_STD_FULL - _STD_FLAT))

    ext = float(((gray < 8) | (gray > 247)).mean())
    ext_score = _clamp01((_EXTREME_BAD - ext) / (_EXTREME_BAD - 0.5))

    if img.ndim == 3:
        q = (img >> 4).reshape(-1, img.shape[2])  # 4bit/通道
        keys = q[:, 0].astype(np.int32) * 256 + q[:, 1].astype(np.int32) * 16 \
            + q[:, 2].astype(np.int32)
    else:
        keys = (gray >> 4).reshape(-1).astype(np.int32)
    hist = np.bincount(keys, minlength=4096).astype(np.float64)
    p = hist[hist > 0] / keys.size
    entropy = float(-(p * np.log2(p)).sum())
    entropy_score = _clamp01(entropy / _ENTROPY_FULL)

    score = min(std_score, ext_score, entropy_score)
    return score, {"gray_std": round(std, 2), "extreme_ratio": round(ext, 4),
                   "entropy_bits": round(entropy, 2),
                   "std_score": round(std_score, 4),
                   "extreme_score": round(ext_score, 4),
                   "entropy_score": round(entropy_score, 4)}


def _score_sharpness(gray: np.ndarray) -> Tuple[float, Dict[str, Any]]:
    """清晰度：拉普拉斯方差（无 cv2 时用 numpy 四点卷积兜底）。"""
    g = gray.astype(np.float64)
    if cv2 is not None:
        lap = cv2.Laplacian(g, cv2.CV_64F)
    else:
        lap = (-4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1]
               + g[1:-1, :-2] + g[1:-1, 2:])
    var = float(lap.var())
    return _clamp01(var / _LAP_FULL), {"lap_var": round(var, 2)}


def _score_size(img: np.ndarray, expected_size: str) -> Tuple[float, Dict[str, Any]]:
    """尺寸达标：无期望不罚（1.0）；精确命中 1.0；比例对 0.7；其余 0.3。"""
    h, w = int(img.shape[0]), int(img.shape[1])
    m = re.match(r"^\s*(\d+)\s*[x×]\s*(\d+)\s*$", expected_size or "")
    if not m:
        return 1.0, {"width": w, "height": h, "expected": ""}
    ew, eh = int(m.group(1)), int(m.group(2))
    if (w, h) == (ew, eh):
        s = 1.0
    elif abs(w * eh - h * ew) <= max(ew, eh):  # 比例一致（±1 像素容差）
        s = 0.7
    else:
        s = 0.3
    return s, {"width": w, "height": h, "expected": f"{ew}x{eh}"}


def _score_composition(gray: np.ndarray) -> Tuple[float, Dict[str, Any]]:
    """构图中心度：中心 50% 区域 std / 全局 std，中心太空（<0.3）扣分。"""
    h, w = gray.shape
    cy, cx = h // 4, w // 4
    center = gray[cy:h - cy, cx:w - cx]
    if center.size == 0:
        return 0.5, {"center_std_ratio": None}
    whole_std = float(gray.std())
    if whole_std < 1e-6:
        return 0.5, {"center_std_ratio": None}  # 全图单色由崩图项负责，此处中立
    ratio = float(center.std()) / whole_std
    return _clamp01(ratio / 0.8), {"center_std_ratio": round(ratio, 3)}


def _score_cost(elapsed_ms: Optional[float], retried: bool) -> Tuple[float, Dict[str, Any]]:
    """成本信号：耗时线性扣分（15s 内不扣，120s 到底）；重试 ×0.8。无数据中立。"""
    if elapsed_ms is None:
        base = 1.0
    else:
        t = max(0.0, float(elapsed_ms))
        base = _clamp01(1.0 - (t - _COST_GOOD_MS) / (_COST_BAD_MS - _COST_GOOD_MS) * 0.7)
    if retried:
        base *= 0.8
    return _clamp01(base), {"elapsed_ms": elapsed_ms, "retried": bool(retried)}


# 格级"死区"判据（**刻意区别于整图判据**）：
# 整图用 std 判"崩"是对的（整张都平 = 崩）；但**格级不能用 std**——真实照片里
# 天空、墙面、皮肤这些格子本来就是低对比（std 可低到个位数），拿整图判据去筛
# 会把它们全标成坏区 ⇒ 白花钱去"修"本来没坏的地方。
# 格级的真问题是「这块地**死了**」：极端像素占比高（纯黑/纯白）或单一色阶支配
# （一两个 4bit 色桶占了大半）。这两条对低对比但仍有层次的区域是安全的。
# 三条判据的阈值都**刻意比整图宽得多**（整图 std 阈值是 8/30，格级"近乎常量"才
# 算死；单色支配要到 0.8 才算死）——实测教训：σ≈3.5 的天空格、单色桶占 50% 的
# 平滑区都**不是**坏区，拿紧阈值筛会让每次抽卡都"体检出"一堆坏区、白花钱去修。
_DEAD_FLAT_ZERO = 1.5    # 灰度 std ≤ 此 ⇒ 近乎常量（纯色/纯黑块）
_DEAD_FLAT_SAFE = 5.0    # ≥ 此 ⇒ 有层次（平滑天空也在此区间之上）
_DEAD_DOM_ZERO = 0.80    # 单一 4bit 色桶占比 ≥ 此 ⇒ 一片死色
_DEAD_DOM_SAFE = 0.55    # ≤ 此 ⇒ 纹理正常
_DEAD_EXT_ZERO = 0.55    # 纯黑(<8)/纯白(>247) 像素占比 ≥ 此 ⇒ 大半是死像素
_DEAD_EXT_SAFE = 0.30    # ≤ 此 ⇒ 正常（真实照片的深阴影/高光不会超过）


def _dead_tile_score(img: np.ndarray, gray: np.ndarray) -> Tuple[float, Dict[str, Any]]:
    """格级死区分（0=死、1=活）：min(常量度, 单色支配度, 极端像素度)。"""
    std = float(gray.std())
    flat_score = _clamp01((std - _DEAD_FLAT_ZERO) / (_DEAD_FLAT_SAFE - _DEAD_FLAT_ZERO))

    ext = float(((gray < 8) | (gray > 247)).mean())
    ext_score = _clamp01((_DEAD_EXT_ZERO - ext) / (_DEAD_EXT_ZERO - _DEAD_EXT_SAFE))

    if img.ndim == 3:
        q = (img >> 4).reshape(-1, img.shape[2])
        keys = (q[:, 0].astype(np.int32) * 256 + q[:, 1].astype(np.int32) * 16
                + q[:, 2].astype(np.int32))
    else:
        keys = (gray >> 4).reshape(-1).astype(np.int32)
    hist = np.bincount(keys, minlength=4096).astype(np.float64)
    dom = float(hist.max() / max(1.0, keys.size))
    dom_score = _clamp01((_DEAD_DOM_ZERO - dom) / (_DEAD_DOM_ZERO - _DEAD_DOM_SAFE))

    score = min(flat_score, ext_score, dom_score)
    return score, {"gray_std": round(std, 2), "extreme_ratio": round(ext, 4),
                   "dominance": round(dom, 4),
                   "flat_score": round(flat_score, 4),
                   "extreme_score": round(ext_score, 4),
                   "dominance_score": round(dom_score, 4)}


def locate_bad_regions(image: Any, *, grid: int = 4,
                       threshold: float = 0.35) -> list:
    """把图切成 ``grid×grid`` 逐格判「死区」，返回低于阈值的格（P4 局部重绘用）。

    返回 ``[{"box": (x, y, w, h), "score": float, ...detail}, ...]``
    （左上原点，像素坐标）；解码失败或无坏区返回空列表——**空列表 = 无需局部重绘**
    （调用方据此跳过，一次请求都不发）。

    为什么要格而不是整图分：整图 0.75 的图完全可能是「90% 完好 + 一角糊成一片」，
    整张重抽既贵又会把完好的部分重抽坏。逐格判是「只修坏区」的前提。

    判据用格级**死区**口径（见 ``_dead_tile_score`` 上方注释），不是整图口径——
    低对比的真实区域（天空/墙面）不会被误判。
    """
    img = _decode(image)
    if img is None or img.size == 0:
        return []
    try:
        g = max(2, int(grid))
        h, w = int(img.shape[0]), int(img.shape[1])
        th, tw = max(1, h // g), max(1, w // g)
        out = []
        for i in range(g):
            for j in range(g):
                y0, x0 = i * th, j * tw
                y1, x1 = (h if i == g - 1 else y0 + th), (w if j == g - 1 else x0 + tw)
                tile = img[y0:y1, x0:x1]
                if tile.size == 0:
                    continue
                score, detail = _dead_tile_score(tile, _to_gray(tile))
                if score < threshold:
                    out.append({"box": (int(x0), int(y0), int(x1 - x0), int(y1 - y0)),
                                "score": round(float(score), 4), **detail})
        return out
    except Exception:
        logger.debug("[gen_critic] 坏区定位失败（按无坏区处理）", exc_info=True)
        return []


def score_image(image: Any, *, expected_size: str = "",
                elapsed_ms: Optional[float] = None,
                retried: bool = False) -> Dict[str, Any]:
    """给一张生成图打代理分。

    返回：``{"score": 0~1, "detail": {...}, "is_proxy": True}``。
    **is_proxy 恒为 True**——代理指标，非审美真值（项目红线）。
    解码失败返回中性 0.5 + detail.decode_error，绝不抛出。
    """
    img = _decode(image)
    if img is None or img.size == 0:
        return {"score": 0.5,
                "detail": {"decode_error": "无法解码图像，回中性分"},
                "is_proxy": True}
    try:
        gray = _to_gray(img)
        broken, d_broken = _score_non_broken(img, gray)
        sharp, d_sharp = _score_sharpness(gray)
        size_s, d_size = _score_size(img, expected_size)
        compose, d_compose = _score_composition(gray)
        cost, d_cost = _score_cost(elapsed_ms, retried)

        total = (_W_BROKEN * broken + _W_SHARP * sharp + _W_SIZE * size_s
                 + _W_COMPOSE * compose + _W_COST * cost)
        gated = False
        if broken < _BROKEN_GATE:
            total = min(total, _BROKEN_CAP)
            gated = True
        return {
            "score": round(_clamp01(total), 4),
            "detail": {
                "non_broken": round(broken, 4), **d_broken,
                "sharpness": round(sharp, 4), **d_sharp,
                "size": round(size_s, 4), **d_size,
                "composition": round(compose, 4), **d_compose,
                "cost": round(cost, 4), **d_cost,
                "broken_gate_applied": gated,
                "weights": {"non_broken": _W_BROKEN, "sharpness": _W_SHARP,
                            "size": _W_SIZE, "composition": _W_COMPOSE,
                            "cost": _W_COST},
            },
            "is_proxy": True,
        }
    except Exception as e:
        logger.debug("[gen_critic] 评分失败，回中性分", exc_info=True)
        return {"score": 0.5,
                "detail": {"decode_error": f"评分异常: {e}"},
                "is_proxy": True}
