# -*- coding: utf-8 -*-
"""app/tests/test_reference_breakdown.py — 逐帧拉片 L1 回归（2026-10-06）。

★ 诚实边界（本模块的红线）
=======================
L1 只给**算得出来的东西**：切点、时长、关键帧、由像素统计的运动量/亮度/对比度。
**景别 / 运镜 / 光线基调不推断**（表里留空）—— 硬猜就是编造，那是本项目禁止的。

本测试覆盖三类：
  ① 纯函数（用**真机采到的 ffmpeg 输出样例**验证解析）；
  ② 真机端到端（造一部有硬切的测试片，跑完整链路）；
  ③ ★ **一条纪律回归**：跑完不许在**项目根**留下临时帧
     （实测踩过：`tempfile.gettempdir()` 在本沙箱回退到 cwd ⇒ `_rb_a_*.jpg` 掉进仓库根）。
"""
import glob
import os
import subprocess

import pytest

from app.core import reference_breakdown as rb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 真机采到的 ffmpeg `select=gt(scene,..),metadata=print` 输出样例（原样保留）
REAL_SAMPLE = """[Parsed_metadata_1 @ 0000021d55e7ce00] frame:0    pts:20480   pts_time:2
[Parsed_metadata_1 @ 0000021d55e7ce00] lavfi.scene_score=0.400000
[Parsed_metadata_1 @ 0000021d55e7ce00] frame:10   pts:40960   pts_time:4
[Parsed_metadata_1 @ 0000021d55e7ce00] lavfi.scene_score=0.512345
"""


# ─────────────────────── ① 纯函数 ───────────────────────

def test_parse_real_ffmpeg_sample():
    pts = rb.parse_scene_points(REAL_SAMPLE)
    assert [p["time"] for p in pts] == [2.0, 4.0]
    assert pts[0]["score"] == pytest.approx(0.4)
    assert pts[1]["score"] == pytest.approx(0.512345)


def test_parse_ignores_noise_and_sorts():
    txt = ("garbage line\n"
           "frame:5 pts_time:3\nlavfi.scene_score=0.9\n"
           "frame:1 pts_time:1\nlavfi.scene_score=0.5\n")
    assert [p["time"] for p in rb.parse_scene_points(txt)] == [1.0, 3.0]


def test_parse_empty():
    assert rb.parse_scene_points("") == []
    assert rb.parse_scene_points("[nothing here]") == []


def test_merge_short_shots_basic():
    shots = rb.merge_short_shots([1.0, 2.0], 3.0)
    assert [s["index"] for s in shots] == [1, 2, 3]
    assert shots[0]["start"] == 0.0 and shots[0]["end"] == 1.0
    assert shots[-1]["end"] == 3.0
    assert all(s["duration"] > 0 for s in shots)


def test_merge_short_shots_merges_flash():
    """短于 min_shot 的段应**并入前一段**（闪帧不该独自成镜）。

    语义澄清（我第一版期望写错了）：合并后**下一段本来就从 1.1 开始**，
    所以正确断言是「第 1 段的终点被撑到 1.1」+「没有任何一段短于 min_shot」，
    而不是「1.1 不能出现在起点里」。
    """
    shots = rb.merge_short_shots([1.0, 1.1, 2.0], 3.0, min_shot=0.4)
    assert shots[0]["end"] == pytest.approx(1.1), "0.1 秒的闪帧没被并进前一段"
    assert all(s["duration"] >= 0.4 for s in shots), f"仍有过短段: {shots}"


def test_merge_short_shots_degenerate():
    # 没有时长信息 ⇒ 无法成段
    assert rb.merge_short_shots([], 0.0) == []
    # 单切点 + 有时长 ⇒ 正常产出 1 段（0 → 1.0）
    one = rb.merge_short_shots([1.0], 1.0)
    assert len(one) == 1 and one[0]["duration"] == pytest.approx(1.0)


def test_frame_metrics_pure():
    import numpy as np
    dark = np.zeros((10, 10), dtype=np.uint8)
    bright = np.full((10, 10), 255, dtype=np.uint8)
    assert rb.frame_metrics(dark)["brightness"] == 0.0
    assert rb.frame_metrics(bright)["brightness"] == pytest.approx(1.0)
    # 纯色 ⇒ 对比度为 0（不造假对比度）
    assert rb.frame_metrics(bright)["contrast"] == 0.0


def test_motion_between_pure():
    import numpy as np
    a = np.zeros((8, 8), dtype=np.uint8)
    b = np.full((8, 8), 255, dtype=np.uint8)
    assert rb.motion_between(a, a) == 0.0
    assert rb.motion_between(a, b) == pytest.approx(1.0)
    assert rb.motion_between(a, np.zeros((4, 4), dtype=np.uint8)) == 0.0  # 形状不符 ⇒ 0，不炸


def test_shots_to_markdown_shape():
    md = rb.shots_to_markdown([
        {"index": 1, "start": 0.0, "duration": 1.5, "motion": 0.12,
         "brightness": 0.4, "contrast": 0.2, "keyframe": "/x/shot_001.jpg"},
        {"index": 2, "start": 1.5, "duration": 1.0},
    ])
    assert "| 镜号 |" in md
    assert "| 1 | 0.00 | 1.50 | 0.120 |" in md
    assert "shot_001.jpg" in md
    # 缺指标的项显示「—」，**不编数字**
    assert "| 2 | 1.50 | 1.00 | — |" in md


# ─────────────────────── ② 诚实边界：不许推断景别/运镜 ───────────────────────

def test_no_shot_size_or_camera_inference_in_source():
    import io as _io
    src = _io.open(os.path.join(ROOT, "app", "core", "reference_breakdown.py"),
                   encoding="utf-8").read()
    for banned in ("特写", "中景", "全景"):
        # 只允许出现在注释/说明里，不允许作为**赋值**写进结果
        assert f'"景别": "{banned}' not in src
        assert f"'景别': '{banned}" not in src


# ─────────────────────── ③ 真机端到端 ───────────────────────

def _make_test_video(path: str, colors=("red", "green", "blue")) -> bool:
    ff = rb._ffmpeg()
    if not ff:
        return False
    d = os.path.dirname(path)
    segs = []
    for i, c in enumerate(colors):
        p = os.path.join(d, f"seg{i}.mp4")
        subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c={c}:s=320x240:d=1:r=10", "-pix_fmt", "yuv420p", p],
                       check=True)
        segs.append(p)
    lst = os.path.join(d, "list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for p in segs:
            fh.write("file '%s'\n" % os.path.abspath(p).replace("\\", "/"))
    r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-c", "copy", path],
                       capture_output=True, text=True)
    return r.returncode == 0 and os.path.isfile(path)


@pytest.mark.skipif(not rb._ffmpeg(), reason="本机无 ffmpeg")
def test_e2e_shot_table_and_no_root_pollution(tmp_path):
    src = str(tmp_path / "in.mp4")
    if not _make_test_video(src):
        pytest.skip("测试片生成失败（环境限制）")

    out = str(tmp_path / "kf")
    res = rb.build_shot_table(src, out_dir=out, threshold=0.05)
    assert res.get("ok") is True
    assert res["count"] >= 2, "至少应检出 2 个镜头段"
    assert res["table_markdown"].startswith("| 镜号 |")
    # 关键帧真的落盘
    kfs = glob.glob(os.path.join(out, "*.jpg"))
    assert len(kfs) >= 2
    for s in res["shots"]:
        assert s["duration"] > 0
        # 指标要么是真实数字、要么留空；**不许编造**
        assert s.get("motion") is None or isinstance(s["motion"], float)
        assert s.get("brightness") is None or isinstance(s["brightness"], float)

    # ★ 纪律回归：项目根不得出现临时帧
    stray = glob.glob(os.path.join(ROOT, "_rb_*.jpg"))
    assert stray == [], f"临时帧落到了项目根：{stray}"
