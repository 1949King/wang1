"""优秀三件事③：5 个新真转场（黑场/白场/径向/对角/翻页）

- 插件预览数学单测（n9.0 vf_xfade.c 同款公式，C 截断对齐）
- 映射表单测：所有插件 → xfade 名 ∈ 本机 ffmpeg 真实清单；方向映射（含 diag 反向）
- 保真度计划单测：radial/diag=exact；fadeblack/fadewhite/page=bake
- ffmpeg 金标准对齐（无 ffmpeg 时 skip）：radial + diag 四向，预览 vs 真实 xfade ≤6 LSB
  （fadeblack/fadewhite 因本机 xfade 与 n9.0 源码有版本漂移而走 bake——
   bake 与预览同一代码路径，无需对齐；回退 xfade 已在 note 中声明为近似）
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.core import transition_plugin_registry as reg

REPO_ROOT = Path(__file__).resolve().parents[2]

H, W = 64, 64
A_FRAME = np.full((H, W, 3), (0, 0, 254), np.uint8)    # BGR 红（from）
B_FRAME = np.full((H, W, 3), (254, 0, 0), np.uint8)    # BGR 蓝（to）

NEW_PLUGINS = [
    "transition_fadeblack", "transition_fadewhite", "transition_radial",
    "transition_diag", "transition_page",
]

# 本机 ffmpeg 9.0 `ffmpeg -h filter=xfade` 实际清单（custom 除外）
FFMPEG_XFADE_NAMES = {
    "fade", "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "circlecrop", "rectcrop", "distance", "fadeblack", "fadewhite", "radial",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose", "vertopen", "vertclose", "horzopen", "horzclose",
    "dissolve", "pixelize", "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice", "hblur", "fadegrays",
    "wipetl", "wipetr", "wipebl", "wipebr", "squeezeh", "squeezev",
    "zoomin", "fadefast", "fadeslow", "hlwind", "hrwind", "vuwind", "vdwind",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
}


def _apply(pid, progress, **params):
    params.setdefault("easing", "linear")
    out = reg.apply_frames(pid, A_FRAME, B_FRAME, progress, params)
    assert out is not None, f"{pid} apply_frames 返回 None"
    return out


# ---------------- 注册与映射表 ----------------

def test_registry_discovers_new_plugins():
    ids = {i["id"] for i in reg.list_transitions()}
    for pid in NEW_PLUGINS:
        assert pid in ids, f"{pid} 未被注册表发现"


def test_mapping_table_all_plugins_resolve_to_real_xfade():
    """每个已注册保真度插件（含方向变体）都映射到本机 ffmpeg 真实存在的 xfade 名。"""
    directions = ["left", "right", "up", "down", "open", "close", "tl", "tr", "bl", "br"]
    for pid in reg._EXPORT_FIDELITY:
        for d in directions:
            name = reg.xfade_name_for_transition({"plugin_id": pid, "direction": d})
            assert name in FFMPEG_XFADE_NAMES, f"{pid}/{d} → 未知 xfade 名 {name}"
    assert reg._KNOWN_XFADE <= FFMPEG_XFADE_NAMES


def test_diag_direction_mapping_reversed_vs_ffmpeg_naming():
    """ffmpeg diag* 命名与 B 揭示起始角相反（金标准已验证），映射必须保持反向。"""
    assert reg.xfade_name_for_transition({"plugin_id": "transition_diag", "direction": "tl"}) == "diagbr"
    assert reg.xfade_name_for_transition({"plugin_id": "transition_diag", "direction": "tr"}) == "diagbl"
    assert reg.xfade_name_for_transition({"plugin_id": "transition_diag", "direction": "bl"}) == "diagtr"
    assert reg.xfade_name_for_transition({"plugin_id": "transition_diag", "direction": "br"}) == "diagtl"


def test_page_direction_fallback_mapping():
    assert reg.xfade_name_for_transition({"plugin_id": "transition_page", "direction": "left"}) == "coverleft"
    assert reg.xfade_name_for_transition({"plugin_id": "transition_page", "direction": "right"}) == "coverright"


def test_fidelity_plan_modes_and_notes():
    assert reg.export_fidelity_for_transition({"plugin_id": "transition_radial"})["mode"] == "exact"
    assert reg.export_fidelity_for_transition({"plugin_id": "transition_diag"})["mode"] == "exact"
    for pid in ("transition_fadeblack", "transition_fadewhite", "transition_page"):
        plan = reg.export_fidelity_for_transition({"plugin_id": pid})
        assert plan["mode"] == "bake", pid
        assert plan["note"], f"{pid} 缺少 bake 提示"
        assert reg.is_bakeable_transition({"plugin_id": pid})
    # exact 且无 note → 导出提示为空；bake → 提示非空
    assert reg.export_degradation_note({"plugin_id": "transition_radial"}) == ""
    assert reg.export_degradation_note({"plugin_id": "transition_page"})


def test_legacy_chinese_labels_resolve():
    assert reg.resolve_plugin_id("黑场过渡") == "transition_fadeblack"
    assert reg.resolve_plugin_id("白场") == "transition_fadewhite"
    assert reg.resolve_plugin_id("径向擦除") == "transition_radial"
    assert reg.resolve_plugin_id("对角擦除") == "transition_diag"
    assert reg.resolve_plugin_id("翻页") == "transition_page"


# ---------------- 预览数学（n9.0 公式） ----------------

def test_fadeblack_endpoints_and_midpoint():
    out0 = _apply("transition_fadeblack", 0.0)
    out1 = _apply("transition_fadeblack", 1.0)
    np.testing.assert_array_equal(out0, A_FRAME)
    np.testing.assert_array_equal(out1, B_FRAME)
    # P=0.5（q=0.5）：ss_a=0；ss_b=ss(0.2,1,0.5)，t=0.375 → 0.31640625
    # out = 0.5*0 + 0.5*(1-0.31640625)*B = 0.34179688*B → B 蓝通道 254*0.34179688≈86.8 → 截断 86
    mid = _apply("transition_fadeblack", 0.5)
    assert int(mid[0, 0, 0]) == 86
    assert int(mid[0, 0, 2]) == 0


def test_fadeblack_brightness_dip():
    m0 = float(_apply("transition_fadeblack", 0.0).mean())
    m_dip = float(_apply("transition_fadeblack", 0.35).mean())
    m_rec = float(_apply("transition_fadeblack", 0.9).mean())
    assert m_dip < m0 * 0.2, "中段应深度压黑"
    assert m_rec > m_dip * 3, "后段应从黑场恢复"


def test_fadewhite_endpoints_and_midpoint():
    np.testing.assert_array_equal(_apply("transition_fadewhite", 0.0), A_FRAME)
    np.testing.assert_array_equal(_apply("transition_fadewhite", 1.0), B_FRAME)
    # P=0.5：m1 = 255；m2 = 255*0.31640625 + B*0.68359375
    # out = 0.5*255 + 0.5*(80.58 + 173.63) = 127.5 + 127.1 = 254.6 → 蓝通道截断 254
    mid = _apply("transition_fadewhite", 0.5)
    assert int(mid[0, 0, 0]) == 254


def test_radial_dead_zone_and_clockwise():
    # P=0.1 处于死区（ffmpeg radial 约 P>0.227 才起现）→ 全 A
    np.testing.assert_array_equal(_apply("transition_radial", 0.1), A_FRAME)
    out = _apply("transition_radial", 0.5)
    cy, cx = H // 2, W // 2
    # 顺时针：12 点与 3 点方向已为 B，9 点与 6 点方向仍为 A
    assert out[4, cx, 0] > 200, "12 点方向应为 B"       # 上
    assert out[cy, W - 4, 0] > 200, "3 点方向应为 B"    # 右
    assert out[cy, 4, 2] > 200, "9 点方向应为 A"        # 左
    assert out[H - 4, cx, 2] > 200, "6 点方向应为 A"    # 下


def test_radial_endpoints():
    np.testing.assert_array_equal(_apply("transition_radial", 0.0), A_FRAME)
    out = _apply("transition_radial", 1.0)
    # ffmpeg radial 公式在 P=1 时 12 点左侧仍留一条 atan2 狭带（≈3% 角度区间，
    # 部分混合，与 xfade 渲染一致）——不断言全帧纯 B，只断言绝大多数像素到位
    frac_b = float((out[:, :, 0].astype(np.int16) > out[:, :, 2].astype(np.int16)).mean())
    assert frac_b > 0.9, f"P=1 蓝占比 {frac_b:.3f} 过低"


def test_diag_reveals_from_named_corner():
    out = _apply("transition_diag", 0.5, direction="tl")
    assert out[0, 0, 0] > 200, "tl：左上角应为 B"
    assert out[-1, -1, 2] > 200, "tl：右下角应为 A"
    out_br = _apply("transition_diag", 0.5, direction="br")
    assert out_br[-1, -1, 0] > 200, "br：右下角应为 B"
    assert out_br[0, 0, 2] > 200, "br：左上角应为 A"
    # 软渐变带：帧内同时存在纯 A、纯 B 与中间值
    vals = out.astype(np.int16)[:, :, 0] - out.astype(np.int16)[:, :, 2]
    assert (np.abs(vals) < 100).any(), "diag 应存在 smoothstep 软渐变带"


def test_diag_endpoints():
    np.testing.assert_array_equal(_apply("transition_diag", 0.0), A_FRAME)
    np.testing.assert_array_equal(_apply("transition_diag", 1.0), B_FRAME)


def test_page_reveal_direction_and_spine_shadow():
    out = _apply("transition_page", 0.6, direction="left")
    # direction=left：to 从右侧翻入，右缘为 B，左缘为 A
    assert out[:, -2:, 0].mean() > 200, "右缘应为 B"
    assert out[:, 0, 2].mean() > 200, "左缘应为 A"
    # 卷曲阴影：脊线（x≈0.4W）左侧邻近的 A 区域应比原 A 更暗
    spine_x = int(0.4 * W)
    shadow_zone = out[:, max(0, spine_x - 6):spine_x - 1, 2].astype(np.float32)
    assert shadow_zone.mean() < A_FRAME[:, :, 2].mean() * 0.9, "脊线附近应有压暗阴影"
    # 端点
    np.testing.assert_array_equal(_apply("transition_page", 0.0), A_FRAME)
    np.testing.assert_array_equal(_apply("transition_page", 1.0), B_FRAME)


# ---------------- ffmpeg 金标准对齐（exact 插件） ----------------

FFMPEG = shutil.which("ffmpeg")


def _render_xfade(transition: str, _tmp_path_unused=None) -> dict:
    """渲染 64x64 红→蓝 xfade（duration=1, offset=1, 10fps），返回 {P: frame}。

    帧编号 f(n) 的 P=(n-11)/10，已由 fade 线性探针标定（R+B=254 恒等）。
    注意：沙箱限制跨盘读写，渲染目录必须落在仓库内（不能用 pytest tmp_path）。
    """
    work = Path(tempfile.mkdtemp(prefix="xfade_gold_", dir=REPO_ROOT))
    try:
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:size=64x64:duration=3:rate=10",
            "-f", "lavfi", "-i", "color=c=blue:size=64x64:duration=3:rate=10",
            "-filter_complex",
            f"[0:v][1:v]xfade=transition={transition}:duration=1:offset=1,format=rgb24[v]",
            "-map", "[v]", str(work / "f%02d.png"),
        ]
        subprocess.run(cmd, check=True, timeout=120)
        frames = {}
        for n, p in [(12, 0.1), (13, 0.2), (16, 0.5), (19, 0.8), (20, 0.9)]:
            png = work / f"f{n:02d}.png"
            # cv2.imread 在 Windows 打不开任何含中文的绝对路径（本仓库根目录"拾光剪影"，
            # cv2 4.11.0 实测：fopen 按 ANSI 解释 UTF-8 字节序列 → 文件找不到），
            # 改用 read_bytes + imdecode 绕过（pathlib 走宽字符 API，Unicode 安全）。
            img = cv2.imdecode(np.frombuffer(png.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            assert img is not None and img.shape == (H, W, 3), f"读取 {transition} 第 {n} 帧失败"
            frames[p] = img
        return frames
    finally:
        shutil.rmtree(work, ignore_errors=True)


@pytest.mark.skipif(FFMPEG is None, reason="本机无 ffmpeg")
def test_gold_radial_matches_ffmpeg():
    frames = _render_xfade("radial")
    for p, img in frames.items():
        mine = _apply("transition_radial", p)
        diff = int(np.abs(img.astype(np.int16) - mine.astype(np.int16)).max())
        assert diff <= 6, f"radial P={p} 预览与导出偏差 {diff} LSB（金标准应 ≤6）"


@pytest.mark.skipif(FFMPEG is None, reason="本机无 ffmpeg")
@pytest.mark.parametrize("direction,xfade_name", [
    ("tl", "diagbr"), ("tr", "diagbl"), ("bl", "diagtr"), ("br", "diagtl"),
])
def test_gold_diag_matches_ffmpeg(direction, xfade_name):
    frames = _render_xfade(xfade_name)
    for p, img in frames.items():
        mine = _apply("transition_diag", p, direction=direction)
        diff = int(np.abs(img.astype(np.int16) - mine.astype(np.int16)).max())
        assert diff <= 6, f"diag/{direction} P={p} 预览与导出偏差 {diff} LSB（金标准应 ≤6）"
