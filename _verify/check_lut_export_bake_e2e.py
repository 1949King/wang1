# -*- coding: utf-8 -*-
"""LUT 导出烘焙 · 真机端到端验证（刀 A3 第 3 项，2026-10-05）。

（2026-10-05 入库：改导出链必须真跑 ffmpeg。ffmpeg 缺失时**优雅跳过**（exit 0），
不把「环境缺件」误报成「实现坏了」。）

改导出链必须真跑 ffmpeg（项目纪律：改导出/渲染后验证 FFmpeg fallback）。
本脚本**真调 ffmpeg**：
  ① 生成一段纯色测试视频（不用外部素材）
  ② 造一个「把红色通道拉满」的 .cube（效果明显、便于断言）
  ③ 走**生产函数** `map_filter_to_vf` 生成 vf → `apply_video_filter` 烘焙
  ④ 用 ffmpeg 取输出帧的像素，断言：命令成功 + 像素**真的被 LUT 改了**
  ⑤ 再验强度 0.7 的混合分支（像素变化量应显著小于全强度）

用法：python .workbuddy/tmp/verify_lut_bake.py
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FFMPEG = os.path.join(ROOT, "thirdparty", "ffmpeg", "bin", "ffmpeg.exe")
if not os.path.isfile(FFMPEG):
    import shutil as _sh
    FFMPEG = _sh.which("ffmpeg") or ""


def _run(cmd):
    return subprocess.run(cmd, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def _avg_rgb(path):
    """取视频中间一帧的平均 RGB（窄小的 2x2 输出便于解析）。"""
    out = path + ".png"
    r = _run([FFMPEG, "-y", "-ss", "0.3", "-i", path, "-vframes", "1",
              "-vf", "scale=1:1", "-f", "image2", out])
    if r.returncode != 0:
        raise RuntimeError("取帧失败: " + r.stderr.decode("utf-8", "ignore")[-300:])
    from PIL import Image
    # 输出 PNG 用 ffmpeg 之外的方式读，避免依赖 numpy
    return Image.open(out).convert("RGB").getpixel((0, 0))


def _write_identity_bias_cube(path, size=2):
    """写一个「R 通道拉满、G/B 减半」的 .cube —— 单色视频上效果极明显。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write('TITLE "verify_bake"\n')
        f.write(f"LUT_3D_SIZE {size}\n")
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    rr = min(1.0, r / (size - 1) * 1.0 + 0.35)
                    gg = (g / (size - 1)) * 0.5
                    bb = (b / (size - 1)) * 0.5
                    f.write(f"{rr:.4f} {gg:.4f} {bb:.4f}\n")


def main():
    if not FFMPEG or not os.path.isfile(FFMPEG):
        print("SKIP 未找到 ffmpeg（第三方运行时缺失）⇒ 跳过真机验证（不算失败）")
        return 0
    from app.modules.lego.video_processor import map_filter_to_vf, apply_video_filter

    tmp = tempfile.mkdtemp(prefix="lutbake_")
    src = os.path.join(tmp, "src.mp4")
    cube = os.path.join(tmp, "bias.cube")
    _write_identity_bias_cube(cube)

    r = _run([FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=1:r=10",
              "-pix_fmt", "yuv420p", src])
    if r.returncode != 0:
        print("✗ 造源视频失败:", r.stderr.decode("utf-8", "ignore")[-300:])
        return 1
    base = _avg_rgb(src)
    print(f"源视频平均 RGB = {base}")

    results = {}
    for label, intens in (("full", 1.0), ("mix70", 0.7)):
        vf = map_filter_to_vf("", 0.7, {"lut": cube, "lut_intensity": intens})
        print(f"\n[{label}] vf = {vf}")
        dst = os.path.join(tmp, f"{label}.mp4")
        ok = apply_video_filter(src, dst, vf, FFMPEG)
        if not ok:
            print(f"✗ {label}: ffmpeg 烘焙失败")
            return 1
        rgb = _avg_rgb(dst)
        results[label] = rgb
        print(f"[{label}] 输出平均 RGB = {rgb}")

    full, mix70 = results["full"], results["mix70"]
    d_full = sum(abs(a - b) for a, b in zip(base, full, strict=False))
    d_mix = sum(abs(a - b) for a, b in zip(base, mix70, strict=False))
    print(f"\n变化量：全强度 {d_full} · 70% {d_mix}")

    ok1 = d_full > 20            # LUT 真的生效（命令成功且画面变了）
    ok2 = 0 < d_mix < d_full     # 强度混合真的生效（变化介于 0 与全强度之间）
    ok3 = len(full) >= 3
    out = len(results) == 2
    print(f"① LUT 生效（变化量 {d_full} > 20）: {ok1}")
    print(f"② 强度混合生效（0 < {d_mix} < {d_full}）: {ok2}")
    print(f"③ 输出可解析: {ok3}")
    print(f"LUT-BAKE-VERDICT {'PASS' if (ok1 and ok2 and ok3 and out) else 'FAIL'}")
    return 0 if (ok1 and ok2 and ok3 and out) else 1


if __name__ == "__main__":
    sys.exit(main())
