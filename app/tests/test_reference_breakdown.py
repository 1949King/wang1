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
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
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


# ─────────────────── L2 运镜推断（2026-10-09 通电，真机验证固化）───────────────────

def _structured_depth(seed: int = 0):
    """造一张有结构的深度图（左近右远斜坡 + 一块近物体 + 微噪）。"""
    import numpy as np
    h, w = 90, 160
    yy, xx = np.mgrid[0:h, 0:w].astype("float32")
    base = (xx / w) * 0.8
    base[30:60, 20:50] = 0.95
    base += np.random.RandomState(seed).rand(h, w).astype("float32") * 0.02
    return base


def _shift_img(img, dx, dy):
    import cv2
    import numpy as np
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]),
                          (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def _scale_img(img, s):
    import cv2
    h, w = img.shape
    return cv2.warpAffine(img, cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 0.0, s),
                          (w, h), borderMode=cv2.BORDER_REPLICATE)


def test_l2_static():
    b = _structured_depth()
    assert rb.infer_camera_move(b, b)["move"] == "static"


def test_l2_pan_direction_semantics():
    """方向语义：**内容右移 = 镜头左摇**（phaseCorrelate 给的是 b 相对 a 的位移）。

    这条测试是「方向写反」事故的回归 —— 首次实现把推拉方向写反了，
    且把方向的测试期望也写反了，靠真机验证才纠出来。
    """
    b = _structured_depth()
    assert rb.infer_camera_move(b, _shift_img(b, 12, 0))["move"] == "pan_left"
    assert rb.infer_camera_move(b, _shift_img(b, -12, 0))["move"] == "pan_right"


def test_l2_tilt_direction_semantics():
    b = _structured_depth()
    assert rb.infer_camera_move(b, _shift_img(b, 0, 8))["move"] == "tilt_up"
    assert rb.infer_camera_move(b, _shift_img(b, 0, -8))["move"] == "tilt_down"


def test_l2_dolly_direction_semantics():
    """best_scale 是「b 缩放多少能匹配 a」⇒ <1 表示 b 更大 ⇒ 画面变大 ⇒ **推近**。"""
    b = _structured_depth()
    assert rb.infer_camera_move(b, _scale_img(b, 1.11))["move"] == "dolly_in"
    assert rb.infer_camera_move(b, _scale_img(b, 0.90))["move"] == "dolly_out"


def test_l2_pan_beats_zoom_when_both_plausible():
    """★ 平移 12px 不得被缩放"抢走"（首次实现正是在这里误判）。

    旧实现用不同常数归一化平移与缩放 ⇒ 8% 横移被 11% 缩放压过。
    新实现改用「残差改善量」比较（谁更能解释差异）。
    """
    b = _structured_depth()
    r = rb.infer_camera_move(b, _shift_img(b, 12, 0))
    assert r["move"] == "pan_left", f"横移被误判为 {r['move']}（{r['reason']}）"


def test_l2_honest_on_flat_and_mismatched():
    import numpy as np
    assert rb.infer_camera_move(np.zeros((10, 10)), np.zeros((10, 10)))["move"] == "unknown"
    assert rb.infer_camera_move(np.zeros((10, 10)), np.zeros((8, 8)))["move"] == "unknown"


def test_l2_confidence_range():
    b = _structured_depth()
    r = rb.infer_camera_move(b, _shift_img(b, 12, 0))
    assert 0.0 <= r["confidence"] <= 1.0
    assert r["confidence"] > 0.5, "明显横移的置信度应较高"
    assert "reason" in r and r["reason"]


# ─────────────────── L2 置信度门槛（2026-10-09 诚实性）───────────────────

def test_camera_move_trusted_gate():
    """低置信度的运镜结论**不得**写进「运镜」字段（只留详情）。

    实测依据：构造的明确平移/缩放可达 0.94~1.0，而生成图案（非真实场景）只有 0.13
    ⇒ 用 0.4 分界能干净区分「可据以决策的结论」与「算法猜的」。
    """
    assert rb.camera_move_trusted("pan_left", 0.997) is True
    assert rb.camera_move_trusted("pan_left", 0.40) is True          # 边界含等号
    assert rb.camera_move_trusted("pan_left", 0.133) is False        # 实测低置信度
    assert rb.camera_move_trusted("pan_left", 0.399) is False


def test_camera_move_trusted_rejects_non_moves():
    for mv in ("", "unknown", "static"):
        assert rb.camera_move_trusted(mv, 1.0) is False, f"{mv} 不该被当成运镜结论"


def test_camera_move_trusted_handles_bad_confidence():
    assert rb.camera_move_trusted("pan_left", None) is False
    assert rb.camera_move_trusted("pan_left", "abc") is False


def test_min_confidence_constant_documented():
    assert 0.0 < rb.CAMERA_MOVE_MIN_CONFIDENCE < 1.0


# ─────────────────── 运镜词表映射（2026-10-14：CV 术语 → 中文影视词）───────────────────

def test_camera_move_zh_maps_all_real_moves():
    """五个有效运动都要有中文词（表里写英文用户看不懂）。"""
    assert rb.camera_move_zh("dolly_in") == "推"
    assert rb.camera_move_zh("dolly_out") == "拉"
    assert rb.camera_move_zh("pan_left") == "摇"
    assert rb.camera_move_zh("pan_right") == "摇"
    assert rb.camera_move_zh("tilt_up") == "摇"
    assert rb.camera_move_zh("tilt_down") == "摇"


def test_camera_move_zh_conservative_on_non_moves():
    """★ 诚实边界：static/unknown/空/未收录词**不许**映射成任何词（固定不是运镜结论）。"""
    for mv in ("", "static", "unknown", "dolly_sideways", "dolly_in_out", " Dolly_In_x"):
        assert rb.camera_move_zh(mv) == "", f"{mv!r} 不该映射出中文词"


def test_camera_move_zh_normalizes_case_and_space():
    """大小写/空格归一化：`"DOLLY_IN "` 是同一个词的脏写法，应命中而非误报空。"""
    assert rb.camera_move_zh("DOLLY_IN ") == "推"


# ─────────────────── 景别 enrich 边界（2026-10-14：云端视觉，默认关闭）───────────────────

def test_use_vision_default_off_no_vision_keys():
    """默认（use_vision=False）不调云端视觉：结果里**不得**出现 vision_* 键。"""
    import inspect
    sig = inspect.signature(rb.build_shot_table)
    assert sig.parameters["use_vision"].default is False
    assert sig.parameters["with_depth"].default is False


def test_apply_vision_enrich_honest_when_no_provider():
    """云端视觉不可用 → 如实回 message，shots **不动**（景别保持留空，不编）。"""
    shots = [{"index": 1, "start": 0.0, "end": 1.0, "景别": "", "运镜": ""}]
    info = rb._apply_vision_enrich(shots, video="", model="")
    assert info.get("vision_used") is False
    assert info.get("vision_message")
    assert shots[0]["景别"] == "", "无模型时景别必须保持留空（不许填默认值）"
    assert "vision" not in shots[0], "解析失败不该打 vision 标记"


def test_norm_choice_hits_wordlist_or_empty():
    """词表命中返回标准词；未命中返回空（**不返回默认词**，避免冒充视觉结论）。"""
    assert rb._norm_choice("近景（人物胸部以上）", rb._SHOT_SIZES) == "近景"
    assert rb._norm_choice("航拍大全景", rb._SHOT_SIZES) == "全景"
    assert rb._norm_choice("不知道", rb._SHOT_SIZES) == ""
    assert rb._norm_choice("", rb._SHOT_SIZES) == ""
