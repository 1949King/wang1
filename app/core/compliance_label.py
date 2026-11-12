# -*- coding: utf-8 -*-
"""AI 生成内容标识（G1 · 2026-11-12）—— 角标 + 元数据。

## 为什么必须做

《微短剧发展管理办法》（2026-09-01 施行）明确：**使用 AI 生成、制作的微短剧，
必须在每一集的明显位置添加提示标识**。这既是合规义务，也是 B 端客户的采购问句。

## 两种形态一起做（用户选定 C 方案）

1. **角标**：画面内叠加"本片含 AI 生成内容"（位置/透明度/时长可配）；
2. **元数据**：写入容器 metadata（comment / ai_generated / record_no / credits），
   便于平台与审核侧机器读取。

只写元数据可能不够"明显"，只打角标又不可机器校验 ⇒ 两者都做。

## 设计纪律

- **绝不二次损坏成品**：先写到临时文件，成功才替换原文件；失败保留原片并返回原因。
- **可配置**：`app/config/compliance_label.json`（不存在则用默认值）。
- **可关闭但默认开启**：合规项默认 `enabled=true`；关闭需显式改配置。
- **不依赖新库**：PIL 已在依赖里；ffmpeg 复用项目既有查找逻辑。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 默认配置（合规项默认开启）
DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "text": "本片含 AI 生成内容",
    "position": "bottom-right",     # top-left | top-right | bottom-left | bottom-right
    "opacity": 0.55,
    "margin_ratio": 0.03,           # 边距 = 短边 * margin_ratio
    "font_size_ratio": 0.035,       # 字号 = 短边 * font_size_ratio
    "show_seconds": 8.0,            # 0 = 全片常驻
    "metadata": {
        "comment": "本片含 AI 生成内容（依据《微短剧发展管理办法》提示标识要求）",
        "ai_generated": "true",
        "record_no": "",            # 备案号
        "credits": "",              # 署名
    },
}

#: 配置路径（相对仓库根）
CONFIG_REL = os.path.join("app", "config", "compliance_label.json")

_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")


def _root() -> str:
    # app/core/compliance_label.py → 上三级 = 仓库根
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def config_path() -> str:
    return os.path.join(_root(), CONFIG_REL)


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """读配置：文件缺失/坏掉都回落默认值（合规标识不能因为配置错误而消失）。"""
    p = path or config_path()
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k == "metadata" and isinstance(v, dict):
                        cfg["metadata"].update(v)
                    else:
                        cfg[k] = v
    except Exception:  # stability-gate: allow-swallow（配置坏了必须回落默认，不能中断导出）
        logger.warning("[compliance] 配置读取失败，使用默认值: %s", p, exc_info=True)
    if str(cfg.get("position") or "") not in _POSITIONS:
        cfg["position"] = DEFAULTS["position"]
    return cfg


def save_config(cfg: Dict[str, Any], path: Optional[str] = None) -> str:
    p = path or config_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    merged = load_config(p)
    for k, v in (cfg or {}).items():
        if k == "metadata" and isinstance(v, dict):
            merged["metadata"].update(v)
        else:
            merged[k] = v
    with open(p, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return p


# ── 位置计算（纯函数，便于单测）────────────────────────────────


def position_xy(w: int, h: int, position: str, margin_ratio: float,
                text_w: int, text_h: int) -> Tuple[int, int]:
    """按短边比例算边距，返回角标左上角坐标。"""
    short = min(int(w or 0), int(h or 0)) or 0
    m = max(0, int(round(short * float(margin_ratio or 0))))
    pos = position if position in _POSITIONS else DEFAULTS["position"]
    x = m if "left" in pos else max(0, int(w) - int(text_w) - m)
    y = m if "top" in pos else max(0, int(h) - int(text_h) - m)
    return x, y


def metadata_args(cfg: Optional[Dict[str, Any]] = None) -> List[str]:
    """ffmpeg 元数据参数（机器可读，便于平台/审核侧识别）。"""
    c = cfg or load_config()
    md = c.get("metadata") or {}
    args: List[str] = []
    pairs = [
        ("comment", md.get("comment") or ""),
        ("ai_generated", md.get("ai_generated") or "true"),
        ("ai_label_text", c.get("text") or ""),
        ("record_no", md.get("record_no") or ""),
        ("credits", md.get("credits") or ""),
        ("ai_label_policy", "微短剧发展管理办法 §AI 生成标识"),
    ]
    for k, v in pairs:
        args += ["-metadata", f"{k}={v}"]
    return args


# ── 角标 PNG ────────────────────────────────────────────────


def _font_candidates() -> List[str]:
    return [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]


def _load_font(size: int):
    from PIL import ImageFont

    for p in _font_candidates():
        try:
            if os.path.isfile(p):
                return ImageFont.truetype(p, size)
        except Exception:  # stability-gate: allow-swallow（字体不可用换下一个候选）
            continue
    return ImageFont.load_default()


def build_overlay_png(text: str, video_w: int, video_h: int, position: str,
                      opacity: float, margin_ratio: float,
                      font_size_ratio: float) -> Optional[str]:
    """生成带文字的 RGBA 角标 PNG（返回临时文件路径）。

    用 PNG 叠加而不是 ffmpeg drawtext：drawtext 对中文字体路径依赖强，跨机器易坏；
    PIL 画图 + overlay 滤镜更稳。
    """
    try:
        from PIL import Image, ImageDraw

        w, h = int(video_w or 0), int(video_h or 0)
        if w <= 0 or h <= 0:
            return None
        short = min(w, h)
        size = max(12, int(short * float(font_size_ratio or DEFAULTS["font_size_ratio"])))
        font = _load_font(size)
        pad = max(6, int(size * 0.45))
        bbox = font.getbbox(text) or (0, 0, len(text) * size, size)
        tw, th = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        img_w, img_h = tw + pad * 2, th + pad * 2
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        alpha = max(0, min(255, int(round(255 * float(opacity or DEFAULTS["opacity"])))))
        # 半透明底 + 白字，浅色/深色画面都看得清
        draw.rectangle([0, 0, img_w - 1, img_h - 1], fill=(0, 0, 0, int(alpha * 0.65)))
        draw.text((pad - int(bbox[0]), pad - int(bbox[1])), text,
                  font=font, fill=(255, 255, 255, alpha))
        x, y = position_xy(w, h, position, margin_ratio, img_w, img_h)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(img, (x, y))
        fd, out = tempfile.mkstemp(prefix="sg_ai_label_", suffix=".png")
        os.close(fd)
        canvas.save(out, format="PNG")
        return out
    except Exception:  # stability-gate: allow-swallow（画不出角标就只写元数据，绝不阻断导出）
        logger.warning("[compliance] 角标 PNG 生成失败，将仅写元数据", exc_info=True)
        return None


# ── ffmpeg ─────────────────────────────────────────────────


def find_ffmpeg() -> str:
    """复用项目既有查找逻辑；找不到返回空串。"""
    try:
        from app.core.render_manager import FFmpegTool

        p = FFmpegTool.find_ffmpeg()
        return p if p and os.path.isfile(p) else ""
    except Exception:  # stability-gate: allow-swallow（找不到 ffmpeg 时走降级路径）
        pass
    exe = shutil.which("ffmpeg")
    return exe or ""


def probe_size(video: str) -> Tuple[int, int]:
    """用 ffmpeg 的 stderr 解析分辨率（不依赖 ffprobe）。"""
    ff = find_ffmpeg()
    if not ff:
        return 0, 0
    try:
        r = subprocess.run([ff, "-hide_banner", "-i", video],
                           capture_output=True, text=True, timeout=30)
        text = (r.stderr or "") + (r.stdout or "")
        import re

        m = re.search(r",\s*(\d{2,5})x(\d{2,5})[\s,]", text)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:  # stability-gate: allow-swallow（探测失败 = 只写元数据）
        logger.debug("[compliance] 分辨率探测失败", exc_info=True)
    return 0, 0


def apply_ai_label_inplace(video_path: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """给成片加角标 + 元数据（原地替换，失败保留原片）。

    返回 `{applied: bool, reason: str, mode: "overlay+metadata"|"metadata"}`。
    """
    c = cfg or load_config()
    out: Dict[str, Any] = {"applied": False, "reason": "", "mode": ""}
    if not c.get("enabled", True):
        out["reason"] = "未启用（配置 enabled=false）"
        return out
    src = str(video_path or "")
    if not src or not os.path.isfile(src):
        out["reason"] = "文件不存在"
        return out
    ff = find_ffmpeg()
    if not ff:
        out["reason"] = "未找到 ffmpeg，无法写入标识"
        return out

    tmp_out = src + ".ai_label.tmp" + (os.path.splitext(src)[1] or ".mp4")
    overlay = None
    try:
        w, h = probe_size(src)
        if w > 0 and h > 0:
            overlay = build_overlay_png(
                str(c.get("text") or DEFAULTS["text"]), w, h,
                str(c.get("position") or DEFAULTS["position"]),
                float(c.get("opacity") or DEFAULTS["opacity"]),
                float(c.get("margin_ratio") or DEFAULTS["margin_ratio"]),
                float(c.get("font_size_ratio") or DEFAULTS["font_size_ratio"]),
            )
        cmd = [ff, "-y", "-hide_banner", "-i", src]
        if overlay:
            cmd += ["-i", overlay]
            show = float(c.get("show_seconds") or 0)
            enable = "" if show <= 0 else f":enable='lte(t,{show:g})'"
            cmd += ["-filter_complex", f"[0:v][1:v]overlay=0:0:format=auto{enable}[v]",
                    "-map", "[v]", "-map", "0:a?", "-c:a", "copy"]
        else:
            cmd += ["-map", "0:v", "-map", "0:a?", "-c", "copy"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd += metadata_args(c)
        cmd.append(tmp_out)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not os.path.isfile(tmp_out) or os.path.getsize(tmp_out) < 1024:
            out["reason"] = "ffmpeg 写入失败：" + (r.stderr or "")[-200:]
            return out
        os.replace(tmp_out, src)
        out.update({"applied": True, "mode": "overlay+metadata" if overlay else "metadata"})
        return out
    except Exception as e:  # stability-gate: allow-swallow（标识失败不能毁掉导出成品）
        out["reason"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        for p in (tmp_out, overlay):
            try:
                if p and os.path.isfile(p):
                    os.remove(p)
            except OSError:  # stability-gate: allow-swallow（临时文件清理失败不影响结果）
                logger.debug("[compliance] 临时文件清理失败 %s", p)
