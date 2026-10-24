"""app/tests/test_lut_export_bake.py — LUT 导出烘焙回归（刀 A3 第 3 项，2026-10-05）。

**修的 bug**：`map_filter_to_vf` 此前**完全不处理 `lut` 键** ⇒ LUT 只在预览生效、
导出**静默丢失**（「预览≠导出」，最难查的一类）。现在映射到 ffmpeg 原生 `lut3d`，
并按要求复刻预览端的强度混合语义。

**与预览的等价性依据**（`app/core/gl_filter_widget.py`）：
  片元着色器最后一步 `col = mix(col, applyLut2D(col), clamp(u_lut_intensity, 0, 1))`
  ⇒ ① LUT 必须在**链尾**（后于 eq/色温/锐度/滤镜分类）；
     ② 强度 < 1 是「原图与 LUT 结果的线性混合」，对应 ffmpeg `split + lut3d + blend`。
"""
import pathlib

import pytest

from app.modules.lego.lut_filter import build_lut_vf, escape_lut_path
from app.modules.lego.video_processor import map_filter_to_vf

SRC = (pathlib.Path(__file__).resolve().parents[2]
       / "app" / "modules" / "lego" / "video_processor.py").read_text(encoding="utf-8")


@pytest.fixture()
def lut_file(tmp_path):
    """造一个真实存在的 .cube 文件（函数会做 isfile 校验）。"""
    p = tmp_path / "my_look.cube"
    p.write_text("TITLE \"t\"\nLUT_3D_SIZE 2\n", encoding="utf-8")
    return str(p)


# ─────────────────────── ① 基本烘焙 ───────────────────────

def test_build_lut_vf_direct_api(lut_file):
    """新模块 `lut_filter.build_lut_vf` 的直测（它是导出的公开映射入口）。"""
    assert build_lut_vf({}) == ""                       # 无键 ⇒ 空串
    assert build_lut_vf({"lut": ""}) == ""
    vf = build_lut_vf({"lut": lut_file, "lut_intensity": 1.0})
    assert vf.startswith("lut3d=file='") and vf.endswith("'")
    assert build_lut_vf({"lut": lut_file, "lut_intensity": 0.5}).startswith("split[")


def test_full_intensity_uses_lut3d(lut_file):
    vf = map_filter_to_vf("", 0.7, {"lut": lut_file, "lut_intensity": 1.0})
    assert "lut3d=file=" in vf
    assert "blend=" not in vf          # 全强度不需要混合
    assert vf.startswith("lut3d=")     # 无其它参数 ⇒ LUT 就是唯一一环


def test_partial_intensity_mixes_like_preview(lut_file):
    """强度 0.7 ⇒ 复刻 mix(col, mapped, 0.7)：split + lut3d + blend all_opacity=0.700。"""
    vf = map_filter_to_vf("", 0.7, {"lut": lut_file, "lut_intensity": 0.7})
    assert "split[lutbase][lutin]" in vf
    assert "lut3d=file=" in vf
    assert "blend=all_mode=normal:all_opacity=0.700" in vf


def test_zero_intensity_adds_nothing(lut_file):
    """强度 0 等价于不套 LUT（预览 mix 0% 也是原图）⇒ 不得加 lut3d。"""
    vf = map_filter_to_vf("", 0.7, {"lut": lut_file, "lut_intensity": 0.0})
    assert "lut3d" not in vf


def test_missing_intensity_defaults_to_full(lut_file):
    """只给 lut 不给强度 ⇒ 按全强度（与「导入即整体套用」的直觉一致）。"""
    vf = map_filter_to_vf("", 0.7, {"lut": lut_file})
    assert "lut3d=file=" in vf and "blend=" not in vf


def test_illegal_intensity_does_not_raise(lut_file):
    for bad in ("abc", [], {}):
        vf = map_filter_to_vf("", 0.7, {"lut": lut_file, "lut_intensity": bad})
        assert "lut3d=file=" in vf   # 非法值按全强度兜底，不炸


def test_intensity_clamped(lut_file):
    vf = map_filter_to_vf("", 0.7, {"lut": lut_file, "lut_intensity": 5.0})
    assert "blend=" not in vf        # >1 钳到 1 ⇒ 全强度
    vf2 = map_filter_to_vf("", 0.7, {"lut": lut_file, "lut_intensity": -3})
    assert "lut3d" not in vf2        # <0 钳到 0 ⇒ 不加


# ─────────────────────── ② 顺序：必须链尾 ───────────────────────

def test_lut_is_last_in_chain(lut_file):
    """LUT 必须是最后一环（预览着色器在最后 mix）——否则导出与预览不一致。"""
    cp = {"brightness": 0.1, "contrast": 1.2, "saturation": 1.2,
          "temperature": 20, "sharpen": 1.0,
          "lut": lut_file, "lut_intensity": 1.0}
    vf = map_filter_to_vf("复古", 0.8, cp)
    assert "lut3d=file=" in vf
    parts = vf.split(",")
    assert parts[-1].startswith("lut3d="), f"LUT 不在链尾: {parts[-1]!r}"
    assert "eq=" in vf and vf.index("eq=") < vf.index("lut3d=")


def test_no_lut_keeps_previous_behaviour():
    """回归：不带 lut 键时输出与修复前一致（不得因本次改动漂移）。"""
    vf = map_filter_to_vf("", 0.5, {"brightness": 0.2, "contrast": 1.1})
    assert "lut3d" not in vf
    assert vf.startswith("eq=")


# ─────────────────────── ③ 诚实失败：文件不存在 ───────────────────────

def test_missing_file_warns_and_skips(caplog, tmp_path):
    missing = str(tmp_path / "nope.cube")
    with caplog.at_level("WARNING"):
        vf = map_filter_to_vf("", 0.7, {"lut": missing, "lut_intensity": 1.0})
    assert "lut3d" not in vf
    assert any("LUT 文件不存在" in r.message for r in caplog.records), caplog.text


def test_empty_lut_value_ignored():
    for empty in ("", "   ", None):
        vf = map_filter_to_vf("", 0.7, {"lut": empty, "lut_intensity": 1.0})
        assert "lut3d" not in vf


# ─────────────────────── ④ 路径转义（Windows 盘符坑，真机实测校准）───────────────────────

def test_escape_windows_drive_colon_and_quote():
    """`D:\\luts\\a.cube` ⇒ `'D\\:/luts/a.cube'`。

    **单引号必须有**：实测「只转义冒号不加引号」时 ffmpeg 仍报
    `Error parsing filterchain`（变体表见 _escape_lut_path 的 docstring）。
    """
    assert escape_lut_path("D:\\luts\\a.cube") == "'D\\:/luts/a.cube'"


def test_escape_keeps_posix_path():
    assert escape_lut_path("/home/u/l.cube") == "'/home/u/l.cube'"


def test_escape_handles_embedded_quote():
    """路径含单引号按 ffmpeg 规则写成 `'\\''`（结束引号 + 转义 + 重开）。"""
    assert escape_lut_path("/a/b'c.cube") == "'/a/b'\\''c.cube'"


def test_escaped_path_used_in_vf(tmp_path):
    """生成的 vf 里必须是转义后的路径（否则 Windows 上必然失败）。"""
    p = tmp_path / "look.cube"
    p.write_text("x", encoding="utf-8")
    vf = map_filter_to_vf("", 0.7, {"lut": str(p), "lut_intensity": 1.0})
    assert "\\:" in vf                     # 盘符冒号已转义
    assert "lut3d=file='" in vf            # 有单引号包裹
    assert "\\\\" not in vf                # 不得残留反斜杠
    assert "lut3d=file=" in vf


# ─────────────────────── ⑤ 源码级锁 ───────────────────────

def test_source_order_lut_after_filter_category():
    """源码级：LUT 段必须在「滤镜分类」之后调用（保证链尾语义不被人挪走）。

    2026-10-05 拆模块后：映射实现在 `lut_filter.py`，`video_processor` 只调 `build_lut_vf(cp)`。
    """
    body = SRC.split("def map_filter_to_vf", 1)[1].split("def map_transition_to_xfade", 1)[0]
    assert body.index("_FILTER_CATEGORY_VF") < body.index("build_lut_vf(cp)")
    # 映射细节在独立模块里（本文件在规模守卫基线内，故拆模块是本项目的正解）
    lut_src = (pathlib.Path(__file__).resolve().parents[2]
               / "app" / "modules" / "lego" / "lut_filter.py").read_text(encoding="utf-8")
    assert "lut3d=file=" in lut_src
    assert "all_mode=normal:all_opacity=" in lut_src
    assert 'logger.warning("LUT 文件不存在' in lut_src
