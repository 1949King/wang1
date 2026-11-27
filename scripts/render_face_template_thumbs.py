# -*- coding: utf-8 -*-
"""捏脸模板缩略图渲染：把 8 套官方模板渲染成 128x160 卡片图（2026-10-21）。

用法
====
    python scripts/render_face_template_thumbs.py --dry-run
    python scripts/render_face_template_thumbs.py
    python scripts/render_face_template_thumbs.py --only fox-spirit --force

后端选择（按顺序）
==================
1. env SG_IMAGE_BASE_URL + SG_IMAGE_API_KEY（OpenAI 兼容 /images/generations）；
2. 应用内 AIEngine 的 image 适配器（ai_engine.generate_image）；
3. 都没有 -> 退出码 2，**不写任何文件**（诚实失败，不造假图）。

产物
====
vendor/shiguang-canvas/public/face-templates/<id>.png
vendor/shiguang-canvas/public/face-templates/manifest.json（sha256 / 尺寸 / 后端）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "vendor" / "shiguang-canvas" / "public" / "face-templates"
TS_PATH = ROOT / "vendor" / "packages" / "canvas-core" / "src" / "faceTemplates.ts"
W, H = 128, 160
STYLE = (
    "portrait headshot, front-facing, soft studio light, clean plain background, "
    "semi-realistic anime illustration, consistent character-sheet style"
)
NEG = (
    "lowres, blurry, text, watermark, extra fingers, deformed, side view, "
    "multiple faces, heavy shadow"
)

# 模板 id -> 外观描述（与 faceTemplates.ts 的 params 对应；只描述外观，不改结构）
PROMPTS = {
    "cold-elegant": "young woman, thin brows, cat-shaped eyes, sharp lips, blue eyes, "
    "pale skin, thin round glasses, cool detached expression",
    "gentle-sister": "young woman, soft round brows, almond eyes, plump lips, brown eyes, "
    "fair skin, single hairpin, warm gentle smile, subtle blush",
    "genki-girl": "young woman, arched brows, big eyes, cupid lips, amber eyes, "
    "bright skin, ribbon headband, cheerful smile, rosy blush",
    "classic-beauty": "young woman, round brows, almond eyes, small mouth, black eyes, "
    "fair skin, flower hair ornament, classical eastern elegance",
    "swordswoman": "young woman, sharp angled brows, narrow eyes, thin lips, gold eyes, "
    "wheat skin, no ornament, cold determined gaze, swordswoman vibe",
    "girl-next-door": "young woman, flat brows, round eyes, natural lips, hazel eyes, "
    "pale skin, small earrings, friendly casual look, light blush",
    "fox-spirit": "young woman, arched brows, cat eyes, pouty lips, violet left eye and "
    "gold right eye, pale skin, translucent veil, mysterious smile",
    "warrior": "young woman, thick brows, upturned eyes, wide lips, brown eyes, "
    "tanned skin, ornate tiara, commanding gaze, warrior princess",
}


def _template_ids() -> list[str]:
    src = TS_PATH.read_text(encoding="utf-8")
    ids = re.findall(r'id:\s*"([a-z0-9-]+)"', src)
    if not ids:
        raise SystemExit("无法从 faceTemplates.ts 解析模板 id（格式变了？）")
    return ids


def _postprocess(raw: bytes) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(raw)).convert("RGB")
    iw, ih = img.size
    target_ratio = W / H
    ratio = iw / ih
    if ratio > target_ratio:  # 太宽 -> 裁左右
        nw = int(ih * target_ratio)
        left = (iw - nw) // 2
        img = img.crop((left, 0, left + nw, ih))
    else:  # 太高 -> 裁上下（保留上方 40%，人脸通常偏上）
        nh = int(iw / target_ratio)
        top = int((ih - nh) * 0.35)
        img = img.crop((0, top, iw, top + nh))
    img = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _render_openai_compatible(prompt: str) -> bytes:
    import urllib.request

    base = os.environ.get("SG_IMAGE_BASE_URL", "").rstrip("/")
    key = os.environ.get("SG_IMAGE_API_KEY", "")
    model = os.environ.get("SG_IMAGE_MODEL", "gpt-image-1")
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": "768x960",
            "response_format": "b64_json",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/images/generations",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    item = (payload.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as resp:
            return resp.read()
    raise RuntimeError("生图接口未返回 b64_json/url")


def _render_ai_engine(prompt: str) -> bytes:
    from app.core.ai_engine import AIEngine

    engine = AIEngine()
    for result in engine.generate_image(
        prompt, negative_prompt=NEG, width=768, height=960
    ):
        if not isinstance(result, dict) or not result.get("success"):
            continue
        if result.get("b64_json"):
            return base64.b64decode(result["b64_json"])
        if result.get("image_path") and Path(result["image_path"]).is_file():
            return Path(result["image_path"]).read_bytes()
        if result.get("url"):
            import urllib.request

            with urllib.request.urlopen(result["url"], timeout=120) as resp:
                return resp.read()
    raise RuntimeError("AIEngine 图像适配器未返回可用结果")


def _pick_backend() -> tuple[str, callable] | None:
    if os.environ.get("SG_IMAGE_BASE_URL") and os.environ.get("SG_IMAGE_API_KEY"):
        return ("openai-compatible", _render_openai_compatible)
    try:
        from app.core.ai_engine import AIEngine

        if AIEngine().get_available_adapters("image"):
            return ("ai_engine", _render_ai_engine)
    except Exception:
        pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染捏脸模板缩略图")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不调模型")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的图")
    parser.add_argument("--only", default="", help="只渲染指定 id")
    args = parser.parse_args()

    ids = _template_ids()
    missing_prompts = [i for i in ids if i not in PROMPTS]
    if missing_prompts:
        print("缺提示词：" + ", ".join(missing_prompts))
        return 1
    if args.only:
        if args.only not in ids:
            print("未知模板 id：" + args.only)
            return 1
        ids = [args.only]

    if args.dry_run:
        for tid in ids:
            print("[dry-run] " + tid + " -> " + str(OUT_DIR / (tid + ".png")))
        print("共 " + str(len(ids)) + " 套；未调用模型、未写文件。")
        return 0

    backend = _pick_backend()
    if backend is None:
        print("未配置生图后端：请设置 SG_IMAGE_BASE_URL + SG_IMAGE_API_KEY，")
        print("或在应用内配置可用的图像适配器后重跑。")
        print("按纪律不生成占位图/假图；本次未写任何文件。")
        return 2
    backend_name, render = backend

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "manifest.json"
    manifest = {"generated_at": "", "backend": backend_name, "items": {}}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    ok = 0
    failed: list[str] = []
    for tid in ids:
        dest = OUT_DIR / (tid + ".png")
        if dest.is_file() and not args.force:
            print("[skip] " + tid + " 已存在（--force 覆盖）")
            ok += 1
            continue
        prompt = PROMPTS[tid] + ", " + STYLE
        try:
            raw = render(prompt)
            png = _postprocess(raw)
        except Exception as exc:  # 单张失败不中断其余
            print("[fail] " + tid + "：" + str(exc))
            failed.append(tid)
            continue
        dest.write_bytes(png)
        manifest["items"][tid] = {
            "file": dest.name,
            "sha256": hashlib.sha256(png).hexdigest(),
            "width": W,
            "height": H,
        }
        ok += 1
        print("[ok] " + tid + " -> " + dest.name)

    manifest["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    manifest["backend"] = backend_name
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    print("完成：" + str(ok) + " / " + str(len(ids)) + "；清单 " + str(manifest_path))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
