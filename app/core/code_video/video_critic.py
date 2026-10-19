# -*- coding: utf-8 -*-
"""渲染质检（V4.45 · 2026-10-19）

三项 V4.45 必做，全部「只报测到的」：
1. **同 t 双乱序**：同一批 t 按正序/倒序各渲染一次，逐 t 比 PNG sha256；
   不一致 ⇒ fail（说明时钟未劫持 / Math.random 未播种 / 帧间状态泄漏）。
2. **文字安全区**：读 worker manifest 的 `text_rects`，按 `qc.text_safe_area` 判定；
   没有 `data-sg-text` 元素 ⇒ `not_wired` 并说明原因（不假装通过）。
3. **平色帧**：PIL 可用则算灰度方差；低方差 ⇒ warning（黑场也可能是创作意图）。

响度（EBU R128）V4.45 不做：显式 `not_wired`，不假装测过。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def choose_sample_ts(compiled: Dict[str, Any], count: int = 5) -> List[float]:
    """在成片时长内均匀取 count 个采样点（取每个区间的中点，避开边界）。"""
    canvas = compiled.get("canvas") or {}
    try:
        duration = float(canvas.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0 or count <= 0:
        return []
    return [round(duration * (i + 0.5) / count, 3) for i in range(count)]


def _check(name: str, status: str, detail: str) -> Dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def compare_dual_shuffle(
    manifest_a: Dict[str, Any], manifest_b: Dict[str, Any]
) -> Dict[str, str]:
    """同 t 双乱序比对：按 t 建索引，逐帧 sha256 必须一致。"""
    def _index(m: Dict[str, Any]) -> Dict[float, str]:
        out: Dict[float, str] = {}
        for f in m.get("frames") or []:
            out[round(float(f.get("t", -1)), 3)] = str(f.get("sha256") or "")
        return out

    ia, ib = _index(manifest_a), _index(manifest_b)
    if not ia or not ib:
        return _check("dual_shuffle", "fail", "采样帧为空，无法比对")
    missing = sorted(set(ia) ^ set(ib))
    if missing:
        return _check(
            "dual_shuffle", "fail", f"两次渲染的 t 集合不一致：{missing[:6]}"
        )
    bad = [f"{t}s" for t in sorted(ia) if ia[t] != ib[t]]
    if bad:
        return _check(
            "dual_shuffle",
            "fail",
            f"{len(bad)}/{len(ia)} 个 t 画出不同画面（罪魁：{', '.join(bad[:5])}）"
            "——检查时钟劫持 / Math.random 播种 / 帧间状态",
        )
    return _check("dual_shuffle", "pass", f"{len(ia)}/{len(ia)} 个 t 两次一致")


def text_safe_area_check(
    manifest: Dict[str, Any],
    width: int,
    height: int,
    safe_area: Optional[List[float]] = None,
) -> Dict[str, str]:
    """文字层是否落在安全区内（rect 由 iframe 经 postMessage 回传）。

    `safe_area` = [left, top, right, bottom] 的**比例**；缺省四边各留 5%。
    """
    if safe_area and len(safe_area) == 4:
        left, top, right, bottom = (float(x) for x in safe_area)
    else:
        left, top, right, bottom = 0.05, 0.05, 0.05, 0.05
    frames = manifest.get("frames") or []
    rects: List[Dict[str, Any]] = []
    for f in frames:
        rects.extend(f.get("text_rects") or [])
    if not rects:
        return _check(
            "text_safe_area",
            "not_wired",
            "未检测到 data-sg-text 元素（文字层未声明安全区锚点，拒绝假通过）",
        )
    min_x, max_x = left * width, (1.0 - right) * width
    min_y, max_y = top * height, (1.0 - bottom) * height
    bad: List[str] = []
    for r in rects:
        try:
            x, y = float(r.get("x") or 0), float(r.get("y") or 0)
            w, h = float(r.get("width") or 0), float(r.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        if x < min_x - 0.5 or y < min_y - 0.5 or x + w > max_x + 0.5 or y + h > max_y + 0.5:
            bad.append(str(r.get("text") or "?")[:20])
    if bad:
        return _check(
            "text_safe_area",
            "fail",
            f"{len(bad)} 个文字元素越出安全区（示例：{', '.join(bad[:3])}）",
        )
    return _check("text_safe_area", "pass", f"{len(rects)} 个文字元素均在安全区内")


def flat_frame_check(
    image_paths: List[str], *, variance_threshold: float = 2.0
) -> Dict[str, str]:
    """平色/黑场检测（warning，不判失败）。PIL 缺失 ⇒ not_wired。"""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return _check("flat_frame", "not_wired", "PIL 未安装，无法计算帧方差")
    if not image_paths:
        return _check("flat_frame", "not_wired", "没有可检测的采样帧")
    flat: List[str] = []
    for path in image_paths:
        try:
            with Image.open(path) as img:
                var = float(ImageStat.Stat(img.convert("L")).var[0])
        except (OSError, ValueError):
            continue
        if var < variance_threshold:
            flat.append(f"{path.rsplit('/', 1)[-1]}(var={var:.2f})")
    if flat:
        return _check(
            "flat_frame",
            "warning",
            f"{len(flat)}/{len(image_paths)} 帧接近平色（可能是黑场/空画面）：{', '.join(flat[:3])}",
        )
    return _check("flat_frame", "pass", f"{len(image_paths)} 帧方差正常")


def build_report(checks: List[Dict[str, str]]) -> Tuple[Dict[str, Any], List[str]]:
    """汇总 QC：任何 fail ⇒ ok=False；warning/not_wired 进 warnings。"""
    warnings = [
        f"{c['name']}: {c['detail']}"
        for c in checks
        if c.get("status") in ("warning", "not_wired")
    ]
    ok = not any(c.get("status") == "fail" for c in checks)
    return {"ok": ok, "checks": checks}, warnings
