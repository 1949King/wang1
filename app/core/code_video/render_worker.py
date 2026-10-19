# -*- coding: utf-8 -*-
"""渲染子进程 worker（V4.45 · 2026-10-19）

**主进程不 import 本模块**（与 `_otio_worker.py` 同纪律）：Chromium/Playwright 可能拖入
与 Qt 冲突的运行时；渲染统一在无 Qt 子进程里做。

用法::

    python -m app.core.code_video.render_worker --job <job.json>
    python -m app.core.code_video.render_worker --check

job.json::

    {
      "page_path": "…/timeline.html",
      "out_dir": "…/frames",
      "fps": 30, "width": 1080, "height": 1920,
      "start_frame": 0, "end_frame": 90,
      "sample_ts": [0.5, 1.5],          // 可选：质检采样模式（只渲染这些 t）
      "progress_path": "…/progress.json",
      "tmp_dir": "…/tmp"                // 可选：Chromium 临时目录（沙箱环境必需）
    }

产物：
    * 逐帧 PNG（`frame_%06d.png`）或采样 PNG（`sample_%03d.png`）
    * `worker_manifest.json`：每帧 {index,t,file,sha256,ms,text_rects}
    * `progress.json`（若给路径）：{stage, frame, total, elapsed_s}
    * 失败：`worker_error.json` + 非零退出（**不产出半成品冒充成功**）

确定性：页面时钟由 page_builder 注入（Math.random 按 t 播种、CSS 动画冻结）；
本 worker 只负责「seek → 等两帧 → 截图」，不引入任何时间相关逻辑。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 只允许这些 scheme 的请求通过（运行时兜底；静态闸在 security.py）
_ALLOWED_PREFIXES = ("file:", "data:", "about:", "blob:")


def _atomic_write_json(path: str, payload: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _prepare_tmp(job: Dict[str, Any]) -> None:
    """把 Chromium 临时目录钉到 job 指定位置（Windows 沙箱下默认 Temp 可能不可写）。"""
    tmp = str(job.get("tmp_dir") or "").strip()
    if not tmp:
        return
    os.makedirs(tmp, exist_ok=True)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = tmp


def _check() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # 诚实报告安装缺失
        print(json.dumps({"ok": False, "error": f"playwright 不可用：{exc}"}, ensure_ascii=False))  # stability-gate: allow-print（worker stdout 即主进程返回通道）
        return 2
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
        print(json.dumps({"ok": True, "chromium": path}, ensure_ascii=False))  # stability-gate: allow-print（stdout 返回通道）
        return 0
    except Exception as exc:  # Chromium 探测失败也如实报告
        print(json.dumps({"ok": False, "error": f"Chromium 不可用：{exc}"}, ensure_ascii=False))  # stability-gate: allow-print（stdout 返回通道）
        return 2


def _launch(playwright: Any):
    return playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-gpu",
            "--hide-scrollbars",
            "--mute-audio",
            "--allow-file-access-from-files",
            "--force-color-profile=srgb",
            "--font-render-hinting=none",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ],
    )


def _install_network_guard(page: Any) -> List[str]:
    blocked: List[str] = []

    def handler(route):
        url = route.request.url or ""
        if url.startswith(_ALLOWED_PREFIXES):
            route.continue_()
            return
        blocked.append(url)
        route.abort()

    page.route("**/*", handler)
    return blocked


def _seek(page: Any, t: float) -> None:
    page.evaluate("(t) => window.__sgSeek(t)", t)
    # postMessage 的 textRects 与 seeked 相邻入队；让消息队列跑完再读
    page.evaluate("() => new Promise((res) => setTimeout(res, 0))")


def _text_rects(page: Any) -> List[Dict[str, Any]]:
    try:
        return page.evaluate("() => window.__sgTextRects || []")
    except Exception:  # QC 数据缺失不该炸掉渲染
        return []


def run_job(job: Dict[str, Any]) -> int:
    page_path = str(job.get("page_path") or "")
    out_dir = str(job.get("out_dir") or "")
    fps = int(job.get("fps") or 0)
    width = int(job.get("width") or 0)
    height = int(job.get("height") or 0)
    start = int(job.get("start_frame") or 0)
    end = int(job.get("end_frame") or 0)
    sample_ts = job.get("sample_ts")
    progress_path = str(job.get("progress_path") or "")
    timeout_ms = int(job.get("frame_timeout_ms") or 10000)

    if not os.path.isfile(page_path):
        raise RuntimeError(f"page_path 不存在：{page_path}")
    if not out_dir:
        raise RuntimeError("out_dir 必填")
    if fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("fps/width/height 必须是正数")
    os.makedirs(out_dir, exist_ok=True)

    from playwright.sync_api import sync_playwright

    total = len(sample_ts) if isinstance(sample_ts, list) and sample_ts else max(end - start, 0)
    started = time.time()
    manifest: Dict[str, Any] = {"frames": [], "blocked_requests": [], "errors": []}

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            manifest["blocked_requests"] = _install_network_guard(page)
            page.goto("file:///" + page_path.replace("\\", "/"), wait_until="load", timeout=30000)
            page.wait_for_function("window.__sgReady !== undefined", timeout=15000)
            page.evaluate("() => window.__sgReady")

            if isinstance(sample_ts, list) and sample_ts:
                for idx, raw_t in enumerate(sample_ts):
                    t = float(raw_t)
                    _seek(page, t)
                    name = f"sample_{idx:03d}.png"
                    path = os.path.join(out_dir, name)
                    t0 = time.time()
                    page.screenshot(path=path, type="png", timeout=timeout_ms,
                                    animations="disabled")
                    manifest["frames"].append({
                        "index": idx, "t": round(t, 6), "file": name,
                        "sha256": _sha256_file(path),
                        "ms": round((time.time() - t0) * 1000.0, 1),
                        "text_rects": _text_rects(page),
                    })
                    if progress_path:
                        _atomic_write_json(progress_path, {
                            "stage": "render", "frame": idx + 1, "total": total,
                            "elapsed_s": round(time.time() - started, 2),
                        })
            else:
                if end <= start:
                    raise RuntimeError("end_frame 必须大于 start_frame")
                for i in range(start, end):
                    t = i / float(fps)
                    _seek(page, t)
                    name = f"frame_{i:06d}.png"
                    path = os.path.join(out_dir, name)
                    t0 = time.time()
                    page.screenshot(path=path, type="png", timeout=timeout_ms,
                                    animations="disabled")
                    manifest["frames"].append({
                        "index": i, "t": round(t, 6), "file": name,
                        "sha256": _sha256_file(path),
                        "ms": round((time.time() - t0) * 1000.0, 1),
                        "text_rects": _text_rects(page),
                    })
                    if progress_path and (i - start) % 10 == 0:
                        _atomic_write_json(progress_path, {
                            "stage": "render", "frame": i - start + 1, "total": total,
                            "elapsed_s": round(time.time() - started, 2),
                        })
        finally:
            browser.close()

    manifest["elapsed_s"] = round(time.time() - started, 2)
    _atomic_write_json(os.path.join(out_dir, "worker_manifest.json"), manifest)
    if progress_path:
        _atomic_write_json(progress_path, {
            "stage": "done", "frame": total, "total": total,
            "elapsed_s": manifest["elapsed_s"],
        })
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="code_video 渲染 worker（无 Qt 子进程）")
    parser.add_argument("--job", default="", help="job JSON 路径")
    parser.add_argument("--check", action="store_true", help="只检查 Playwright/Chromium")
    args = parser.parse_args(argv)

    if args.check:
        return _check()
    if not args.job:
        print(json.dumps({"ok": False, "error": "缺少 --job"}, ensure_ascii=False))  # stability-gate: allow-print（stdout 返回通道）
        return 2

    try:
        with open(args.job, "r", encoding="utf-8") as fh:
            job = json.load(fh)
        _prepare_tmp(job)
        return run_job(job)
    except Exception as exc:  # 子进程必须把失败如实交回主进程
        detail = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(limit=6),
        }
        try:
            out_dir = str((locals().get("job") or {}).get("out_dir") or "")
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
                _atomic_write_json(os.path.join(out_dir, "worker_error.json"), detail)
        except OSError:
            logger.debug("worker_error.json 写入失败", exc_info=True)
        print(json.dumps(detail, ensure_ascii=False))  # stability-gate: allow-print（stdout 返回通道）
        return 2


if __name__ == "__main__":
    sys.exit(main())
