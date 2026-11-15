# -*- coding: utf-8 -*-
"""本地模型总览 + 缺失模型的拉取通道。

    python scripts/check_models.py                 # 【默认】只显示本机已拥有的
    python scripts/check_models.py --all           # 全部（含缺失，用于排障）
    python scripts/check_models.py --missing       # 只看缺失的 + 各自怎么拿
    python scripts/check_models.py --pull wan22-ti2v-5b        # 真下载（先预检硬件）
    python scripts/check_models.py --pull all --yes            # 下载所有「有源且硬件够」的
    python scripts/check_models.py --json

## 为什么默认只显示已有的

需求原话：「有的展示出来，没有的不展示」。排障时用 `--all` 看全景。

## 判定与下载都不在这里重新发明

| 事情 | 真源 |
|---|---|
| 权重在不在盘 / 后端 / 验证态 | `model_family.status()` |
| 能不能用 + 原因 | `model_family.resolve()` |
| 磁盘体积 | 视频 `local_video_infer._scan_local_models()`；图像 `DiffsynthImageEngine.local_dir()/downloaded_bytes()` |
| 下载源（repo / 体积 / 显存 / 内存） | `video_gen.VIDEO_MODELS`、`diffsynth_image.IMAGE_MODELS` |
| 真正下载 | `VideoGenEngine.pull()` / `DiffsynthImageEngine.pull()`（ModelScope `snapshot_download`）|

## 三种「没有」要分清（别混成一句话）

1. **有下载源、本机没下** → 可以直接 `--pull`。
2. **有源但硬件不够**（如 Wan2.2 要 20GB 内存，本机 15.3GB）→ 能下不能跑，默认不替你下。
3. **连下载源都没登记**（cogvideox / hunyuan / ltx / mochi / minimax_h3 只有推理代码，
   `VIDEO_MODELS` 里没有它们的 repo）→ **拉不了**，不是不肯拉，是无处可拉。

第 3 类要接进来，得先在 `VIDEO_MODELS` 里登记 repo/体积/显存/内存四项，属「接入新模型」的活。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CAP_ORDER = ["image", "video", "audio", "music", "llm"]
CAP_LABEL = {"image": "生图", "video": "生视频", "audio": "语音", "music": "音乐", "llm": "对话"}


# ── 硬件 ───────────────────────────────────────────────────────────────────
def _hw() -> dict:
    out = {"ram_gb": None, "ram_free_gb": None, "disk_free_gb": None}
    try:
        import psutil

        vm = psutil.virtual_memory()
        out["ram_gb"] = round(vm.total / 1024**3, 1)
        out["ram_free_gb"] = round(vm.available / 1024**3, 1)
    except Exception:
        pass
    try:
        out["disk_free_gb"] = round(shutil.disk_usage(ROOT).free / 1024**3, 1)
    except Exception:
        pass
    return out


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
    """族 → (磁盘目录, GB)。复用各引擎自己的目录解析。"""
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
            fam = str(mid).split("-")[0]
            d = os.path.join(ROOT, DiffsynthImageEngine.local_dir(mid))
            if os.path.isdir(d):
                out.setdefault(
                    fam, (os.path.abspath(d), DiffsynthImageEngine.downloaded_bytes(mid) / 1024**3)
                )
    except Exception:
        pass
    return out


# ── 可下载目录（只有登记了下载源的才在）────────────────────────────────────
def _catalog() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        from app.core.neural import video_gen as vg

        for m in vg.available_models():
            spec = vg.VIDEO_MODELS.get(m["id"]) or {}
            out[m["id"]] = {
                "kind": "video",
                "family": m["id"].split("-")[0].rstrip("0123456789"),
                "label": m.get("label") or m["id"],
                "repo": spec.get("repo") or "",
                "gb": m.get("download_gb"),
                "vram": m.get("vram_gb"),
                "ram": m.get("ram_gb"),
                "source": "魔搭 ModelScope",
                "downloaded": bool(vg.VideoGenEngine.is_downloaded(m["id"])),
            }
    except Exception:
        pass
    try:
        from app.core.neural.diffsynth_image import IMAGE_MODELS, DiffsynthImageEngine

        for mid, spec in IMAGE_MODELS.items():
            out[mid] = {
                "kind": "image",
                "family": str(mid).split("-")[0],
                "label": spec.get("label") or mid,
                "repo": spec.get("ms_repo") or "",
                "gb": spec.get("size_gb"),
                "vram": spec.get("vram_gb"),
                "ram": spec.get("ram_gb"),
                "source": "魔搭 ModelScope",
                "downloaded": bool(DiffsynthImageEngine.is_downloaded(mid)),
            }
    except Exception:
        pass
    return out


# ── 采集 ───────────────────────────────────────────────────────────────────
def collect(capabilities: list[str] | None, show_all: bool) -> tuple[dict, list[dict], dict]:
    from app.core.neural import model_family as MF

    status = MF.status()
    weights = _weight_dirs()
    cat = _catalog()
    rows: list[dict] = []
    for f in status.get("families") or []:
        cap = f.get("capability") or ""
        if capabilities and cap not in capabilities:
            continue
        if not show_all and not f.get("weights"):
            continue  # 默认：只显示本机已有的
        res = MF.resolve(f.get("family") or "")
        d = weights.get(f.get("family") or "")
        cand = [mid for mid, c in cat.items() if c["family"] == f.get("family")]
        rows.append(
            {
                **f,
                "resolvable": bool(res.get("ok")),
                "reasons": list(res.get("reasons") or []),
                "backend_in_use": res.get("backend") or "",
                "disk_gb": round(d[1], 1) if d else None,
                "disk_dir": d[0] if d else "",
                "pullable": bool(cand),
                "pull_id": cand[0] if cand else "",
            }
        )
    rows.sort(
        key=lambda r: (
            CAP_ORDER.index(r["capability"]) if r["capability"] in CAP_ORDER else 99,
            not r["weights"],
            r["family"],
        )
    )
    return status, rows, cat


def _mark(ok: bool) -> str:
    return "有" if ok else "无"


def render_owned(rows: list[dict], hw: dict) -> str:
    lines = ["=" * 92]
    lines.append(f"本机已有的本地模型  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 92)
    lines.append(f"{'能力':<7}{'族':<14}{'磁盘':>9}  {'后端':<8}{'验证态':<14}{'可用'}")
    lines.append("-" * 92)
    for r in rows:
        backs = r.get("backends") or {}
        ok_n = sum(1 for v in backs.values() if v)
        back_txt = f"{ok_n}/{len(backs)}" if backs else "-"
        disk = f"{r['disk_gb']} GB" if r.get("disk_gb") else "-"
        lines.append(
            f"{CAP_LABEL.get(r['capability'], r['capability']):<7}"
            f"{r['family']:<14}{disk:>9}  {back_txt:<8}{r['verification']:<14}"
            f"{'✓' if r['resolvable'] else '✗'}"
        )
    lines.append("-" * 92)
    lines.append(
        f"共 {len(rows)} 个：可用 {sum(1 for r in rows if r['resolvable'])}；"
        f"内存 {hw.get('ram_gb')}GB（可用 {hw.get('ram_free_gb')}GB）；"
        f"磁盘余 {hw.get('disk_free_gb')}GB"
    )
    bad = [r for r in rows if not r["resolvable"]]
    if bad:
        lines.append("")
        lines.append("—— 有权重但不可用 ——")
        for r in bad:
            lines.append(f"  · {r['family']}: {'；'.join(r['reasons']) or '（无原因）'}")
    lines.append("")
    lines.append("要看本机还没有的（连怎么下载）：加 --missing    ·    看全部族：加 --all")
    return "\n".join(lines)


def render_missing(cat: dict, hw: dict, rows: list[dict]) -> str:
    lines = ["=" * 92]
    lines.append(f"本机还没有的模型（下载源 + 硬件是否够）  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 92)
    lines.append(
        f"本机：内存 {hw.get('ram_gb')}GB（可用 {hw.get('ram_free_gb')}GB），"
        f"磁盘余 {hw.get('disk_free_gb')}GB"
    )
    lines.append("")
    lines.append(f"{'模型 id':<18}{'来源':<14}{'体积':>8}  {'需内存':>7}  {'需显存':>7}  结论")
    lines.append("-" * 92)
    pullable: list[str] = []
    for mid, c in sorted(cat.items(), key=lambda kv: (kv[1]["kind"], kv[0])):
        if c["downloaded"]:
            continue
        gb, ram, vram = c.get("gb"), c.get("ram"), c.get("vram")
        disk_ok = (hw.get("disk_free_gb") or 0) >= (gb or 0) * 1.05
        ram_ok = (hw.get("ram_gb") or 0) >= (ram or 0)
        verdict = []
        if not disk_ok:
            verdict.append("磁盘不够·不能下")
        elif not ram_ok:
            verdict.append("磁盘够，但内存不够·下了跑不动")
        else:
            verdict.append("可下载")
            pullable.append(mid)
        lines.append(
            f"{mid:<18}{c['source']:<14}"
            f"{(f'{gb}GB') if gb else '-':>8}  {(f'{ram}GB') if ram else '-':>7}  "
            f"{(f'{vram}GB') if vram else '-':>7}  {'；'.join(verdict)}"
        )
    lines.append("-" * 92)

    no_src = [r["family"] for r in rows if not r["weights"] and not r["pullable"]]
    if no_src:
        lines.append("")
        lines.append("—— 有推理代码、但**没有登记下载源**的族（当前拉不了）——")
        lines.append(f"  {', '.join(no_src)}")
        lines.append("  原因：VIDEO_MODELS 里没有它们的 repo/体积/显存/内存四项，只有 _infer_* 代码。")
        lines.append("  要接进来得先登记下载源（属「接入新模型」），或手动把权重放到 app/models/cache/<repo>/。")

    if pullable:
        lines.append("")
        lines.append("—— 可以直接拉取的（硬件够）——")
        for mid in pullable:
            lines.append(f"  python scripts/check_models.py --pull {mid}")
        lines.append("  或一次拉完：python scripts/check_models.py --pull all --yes")

    # 手动放权重：从 GitHub / HuggingFace / 任意社区下的完整文件也能用
    try:
        from app.core.local_video_infer import MODEL_KEYWORD_MAP

        lines.append("")
        lines.append("—— 手动放权重（GitHub 原版 / 社区剪枝调优版都行）——")
        lines.append("  放到 app/models/cache/<目录名>/，**目录名必须含下列关键词之一**才会被认出：")
        for kind, kws in MODEL_KEYWORD_MAP.items():
            lines.append(f"    {kind:<12}{' / '.join(kws)}")
        lines.append("  目录内必须是 diffusers 格式（含 model_index.json 或 config.json）且真有权重文件；")
        lines.append("  只有 1KB 索引的空壳会被跳过（避免「明明下过却加载失败」）。放好后重跑本脚本即可。")
    except Exception as e:
        lines.append(f"  （关键词表读取失败：{type(e).__name__}: {e}）")

    # Ollama：只服务文本模型，拉不了扩散模型 —— 用户提到过，这里如实报现状
    lines.append("")
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as resp:
            names = [
                str(m.get("name"))
                for m in (json.loads(resp.read().decode("utf-8")).get("models") or [])
            ]
        lines.append("—— Ollama（只管文本/对话模型，拉不了生图/生视频）——")
        lines.append(f"  运行中，已装 {len(names)} 个：{', '.join(names[:6]) or '（空）'}")
        if len(names) > 6:
            lines.append(f"  ……另有 {len(names) - 6} 个")
    except Exception:
        lines.append("—— Ollama：未运行或未安装（且它只服务文本模型，与生图/生视频无关）——")
    return "\n".join(lines)


def render_all(rows: list[dict]) -> str:
    lines = ["=" * 92]
    lines.append(f"本地模型全量视图（含本机没有的）  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 92)
    lines.append(
        f"{'能力':<7}{'族':<14}{'权重':<5}{'磁盘':>9}  {'后端':<8}{'验证态':<14}{'可用':<6}可拉取"
    )
    lines.append("-" * 92)
    for r in rows:
        backs = r.get("backends") or {}
        ok_n = sum(1 for v in backs.values() if v)
        back_txt = f"{ok_n}/{len(backs)}" if backs else "-"
        disk = f"{r['disk_gb']} GB" if r.get("disk_gb") else "-"
        lines.append(
            f"{CAP_LABEL.get(r['capability'], r['capability']):<7}{r['family']:<14}"
            f"{_mark(bool(r['weights'])):<6}{disk:>9}  {back_txt:<8}{r['verification']:<14}"
            f"{('✓' if r['resolvable'] else '✗'):<6}{'是' if r['pullable'] else '否'}"
        )
    lines.append("-" * 92)
    lines.append(
        f"合计 {len(rows)} 族：可用 {sum(1 for r in rows if r['resolvable'])}"
        f" / 权重在盘 {sum(1 for r in rows if r['weights'])}"
        f" / 已验证 {sum(1 for r in rows if r['verification'] == 'verified')}"
    )
    lines.append("")
    lines.append("加点看：--missing 看缺什么/怎么下  ·  默认（不加参数）只看已有的")
    return "\n".join(lines)


# ── 拉取 ───────────────────────────────────────────────────────────────────
def do_pull(target: str, yes: bool) -> int:
    from app.core.neural.diffsynth_image import DiffsynthImageEngine, IMAGE_MODELS
    from app.core.neural.video_gen import VIDEO_MODELS, VideoGenEngine

    cat = _catalog()
    hw = _hw()

    if target == "all":
        todo = []
        for mid, c in cat.items():
            if c["downloaded"]:
                continue
            if (hw.get("ram_gb") or 0) < (c.get("ram") or 0):
                print(f"跳过 {mid}：需内存 {c.get('ram')}GB > 本机 {hw.get('ram_gb')}GB，下了也跑不动")
                continue
            if (hw.get("disk_free_gb") or 0) < (c.get("gb") or 0) * 1.05:
                print(f"跳过 {mid}：磁盘余量不足")
                continue
            todo.append(mid)
        if not todo:
            print("没有「有源且硬件够」的缺失模型可拉。")
            return 0
    else:
        if target not in cat:
            print(f"未知模型 id：{target}", file=sys.stderr)
            print(f"可选：{', '.join(sorted(cat))}", file=sys.stderr)
            return 2
        c = cat[target]
        if c["downloaded"]:
            print(f"{target} 已在本机，无需下载。")
            return 0
        if (hw.get("ram_gb") or 0) < (c.get("ram") or 0):
            print(
                f"⚠ {target} 需内存 {c.get('ram')}GB，本机只有 {hw.get('ram_gb')}GB"
                " —— 能下，但大概率跑不动。"
            )
            if not yes:
                print("  真要下载请加 --yes（会占磁盘）。")
                return 1
        if (hw.get("disk_free_gb") or 0) < (c.get("gb") or 0) * 1.05:
            print(
                f"磁盘余量不足：需约 {c.get('gb')}GB，仅剩 {hw.get('disk_free_gb')}GB",
                file=sys.stderr,
            )
            return 1
        todo = [target]

    plan = [(mid, cat[mid]) for mid in todo]
    total = sum((c.get("gb") or 0) for _, c in plan)
    print(f"将下载 {len(plan)} 个模型，合计约 {total:.1f}GB")
    for mid, c in plan:
        print(f"  · {mid:<18}{c['source']}  {c.get('repo')}")
    if not yes:
        print("\n这只是计划。确认后加 --yes 执行。")
        return 0

    rc = 0
    for mid, _c in plan:
        print(f"\n=== 下载 {mid} ===", flush=True)
        try:
            if mid in IMAGE_MODELS:
                res = DiffsynthImageEngine().pull(
                    mid, progress_cb=lambda s: print("   ", s, flush=True)
                )
            elif mid in VIDEO_MODELS:
                res = VideoGenEngine().pull(
                    mid, progress_cb=lambda s: print("   ", s, flush=True)
                )
            else:
                print(f"  无法路由到下载引擎：{mid}")
                rc = 1
                continue
        except Exception as e:
            print(f"  异常：{type(e).__name__}: {e}")
            rc = 1
            continue
        print(f"  {'✓' if res.get('ok') else '✗'} {res.get('message')}")
        if not res.get("ok"):
            rc = 1
    print("\n下载结束后用 `python scripts/check_models.py` 复核。")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="本地模型总览 + 缺失模型拉取")
    ap.add_argument("--capability", default="", help="只看某类能力：image,video")
    ap.add_argument("--all", action="store_true", help="显示全部族（含本机没有的）")
    ap.add_argument("--missing", action="store_true", help="只看本机还没有的 + 怎么下载")
    ap.add_argument("--pull", default="", metavar="MODEL_ID|all", help="下载指定模型（先预检硬件）")
    ap.add_argument("--yes", action="store_true", help="配合 --pull：真正执行（否则只打印计划）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.pull:
        return do_pull(args.pull, args.yes)

    caps = [c.strip() for c in (args.capability or "").split(",") if c.strip()] or None
    try:
        status, rows, cat = collect(caps, show_all=(args.all or args.missing))
    except Exception as e:
        print(f"采集失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2

    hw = _hw()
    if args.json:
        print(
            json.dumps(
                {"status": status, "rows": rows, "hardware": hw}, ensure_ascii=False, indent=2
            )
        )
        return 0

    if args.missing:
        print(render_missing(cat, hw, rows))
    elif args.all:
        print(render_all(rows))
    else:
        print(render_owned(rows, hw))

    return 0 if any(r["resolvable"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
