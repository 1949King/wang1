# -*- coding: utf-8 -*-
"""本地模型总览：一次看清「生图 + 生视频」全部模型的状态。

    python scripts/check_models.py                 # 全部能力
    python scripts/check_models.py --capability image
    python scripts/check_models.py --json          # 给别的脚本吃

## 为什么需要它

`model_family.status()` 早就一次返回全部 9 个族，但没人把它摊开成一张人人看得懂的表 ——
于是排障时经常只查了视频那一半（`local_video_infer`），生图的另一半没人看，
看起来就像「检查一次只跑出一个生视频的」。

## 这个脚本只做展示，不做判定

判定一律调现成的三处真源，**绝不在这里另写一套**（否则又多一个漂移源）：
  · `model_family.status()`        —— 权重在不在盘、后端健不健康、验证态、备注
  · `model_family.resolve()`       —— 最终能不能用 + 为什么不能（reasons）
  · `model_family.weights_present()` —— 单个族的权重布尔（status 里已经含，仅排障用）

## 四种状态的含义（别混）

| 列 | 含义 |
|---|---|
| 权重 | 模型文件在不在硬盘上。不在 ⇒ 下载后才可能用 |
| 后端 | 承载它的推理栈（diffsynth / diffusers / video_gen / local_video_infer）是否可导入 |
| 验证态 | `verified` = 本机真机跑过且有产物；`unverified` = 有代码但没验收过 |
| 可用 | `resolve()` 的结论。**权重 + 后端 + 验证态三者都过才算可用** |

「权重在盘但不可用」通常只有两种原因：后端缺依赖，或该族标注 unverified 且被默认排除。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CAP_ORDER = ["image", "video", "audio", "music", "llm"]
CAP_LABEL = {
    "image": "生图",
    "video": "生视频",
    "audio": "语音",
    "music": "音乐",
    "llm": "对话",
}


def _dir_size_gb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total / 1024**3


def _weight_dirs() -> dict[str, tuple[str, float]]:
    """族 → (磁盘目录, GB)。**复用各引擎自己的目录解析**，不在这里另拼路径。

    · 视频 ③ 系（wan / cogvideox / …）：`local_video_infer._scan_local_models()` 给出的真实目录
    · 图像（sd15 / sdxl）：`DiffsynthImageEngine.local_dir()` + `downloaded_bytes()`
    """
    out: dict[str, tuple[str, float]] = {}

    try:
        from app.core.local_video_infer import _scan_local_models

        for m in _scan_local_models():
            p = os.path.abspath(getattr(m, "path", "") or "")
            if p and os.path.isdir(p):
                out.setdefault(m.kind, (p, _dir_size_gb(p)))
    except Exception:
        pass

    try:
        from app.core.neural.diffsynth_image import IMAGE_MODELS, DiffsynthImageEngine

        for mid in IMAGE_MODELS:
            # 族名 = 模型 id 的前缀（sd15-t2i → sd15）；推断不到就跳过，不要瞎猜
            fam = str(mid).split("-")[0]
            d = os.path.join(ROOT, DiffsynthImageEngine.local_dir(mid))
            if os.path.isdir(d):
                out.setdefault(fam, (os.path.abspath(d), DiffsynthImageEngine.downloaded_bytes(mid) / 1024**3))
    except Exception:
        pass

    return out


def collect(capabilities: list[str] | None) -> tuple[dict, list[dict]]:
    from app.core.neural import model_family as MF

    status = MF.status()
    weights = _weight_dirs()
    rows: list[dict] = []
    for f in status.get("families") or []:
        cap = f.get("capability") or ""
        if capabilities and cap not in capabilities:
            continue
        res = MF.resolve(f.get("family") or "")
        d = weights.get(f.get("family") or "")
        rows.append(
            {
                **f,
                "resolvable": bool(res.get("ok")),
                "reasons": list(res.get("reasons") or []),
                "backend_in_use": res.get("backend") or "",
                "disk_gb": round(d[1], 1) if d else None,
                "disk_dir": d[0] if d else "",
            }
        )
    rows.sort(key=lambda r: (CAP_ORDER.index(r["capability"]) if r["capability"] in CAP_ORDER else 99,
                             not r["weights"], r["family"]))
    return status, rows


def _mark(ok: bool) -> str:
    return "有" if ok else "无"


def render(status: dict, rows: list[dict]) -> str:
    lines: list[str] = []
    lines.append("=" * 96)
    lines.append(f"本地模型总览  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 96)
    head = f"{'能力':<7}{'族':<14}{'权重':<5}{'磁盘':>9}  {'后端(可用/声明)':<22}{'验证态':<11}{'可用'}"
    lines.append(head)
    lines.append("-" * 96)
    for r in rows:
        backs = r.get("backends") or {}
        ok_n = sum(1 for v in backs.values() if v)
        back_txt = f"{ok_n}/{len(backs)} 个可用" if backs else "-"
        disk = f"{r['disk_gb']} GB" if r.get("disk_gb") else "-"
        lines.append(
            f"{CAP_LABEL.get(r['capability'], r['capability']):<7}"
            f"{r['family']:<14}"
            f"{_mark(bool(r['weights'])):<6}"
            f"{disk:>9}  "
            f"{back_txt:<22}"
            f"{r['verification']:<13}"
            f"{'✓' if r['resolvable'] else '✗'}"
        )
    lines.append("-" * 96)
    lines.append(
        f"合计 {len(rows)} 族：可用 {sum(1 for r in rows if r['resolvable'])}"
        f" / 权重在盘 {sum(1 for r in rows if r['weights'])}"
        f" / 已验证 {sum(1 for r in rows if r['verification'] == 'verified')}"
    )

    bad = [r for r in rows if not r["resolvable"]]
    if bad:
        lines.append("")
        lines.append("—— 不可用的族，逐条原因 ——")
        for r in bad:
            why = "；".join(r["reasons"]) or "（resolve 未给出原因）"
            lines.append(f"  · {r['family']}（{CAP_LABEL.get(r['capability'], r['capability'])}）: {why}")

    by_cap: dict[str, list[int]] = {}
    for r in rows:
        by_cap.setdefault(r["capability"], []).append(1 if r["resolvable"] else 0)
    if by_cap:
        lines.append("")
        lines.append("—— 按能力汇总 ——")
        for cap in CAP_ORDER:
            if cap not in by_cap:
                continue
            v = by_cap[cap]
            lines.append(f"  · {CAP_LABEL[cap]:<6}{sum(v)} 可用 / 共 {len(v)} 族")

    lines.append("")
    lines.append("提示：权重在盘 ≠ 能用。生图缺 diffusers/torch 会显示后端不可用；")
    lines.append("      unverified 的族需显式选用，不进默认可选。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="本地模型总览（生图 + 生视频 + 其他能力）")
    ap.add_argument(
        "--capability",
        default="",
        help="只看某类能力，逗号分隔：image,video（默认全部）",
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    caps = [c.strip() for c in (args.capability or "").split(",") if c.strip()] or None
    try:
        status, rows = collect(caps)
    except Exception as e:
        print(f"采集失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"status": status, "rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(render(status, rows))

    return 0 if any(r["resolvable"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
