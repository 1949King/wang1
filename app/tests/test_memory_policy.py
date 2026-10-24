"""app/tests/test_memory_policy.py — 显存策略收口回归（2026-10-02，W1）。

锁定的纪律：
  ① **实测基线不漂** —— SVD 的显存下限估计必须贴合 2026-10-01 本机实测
     （5 帧 4.66GB / 8 帧 5.58GB / 10 帧 6.20GB；不 offload 5 帧 5.84 / 10 帧 7.70）；
  ② **SVD 永远 model_offload**（结论经两次反转发定稿，别凭直觉改回 whole_gpu）；
  ③ **决策必须可见** —— reasons 永不为空（同 R9 精神：不允许静默决策）；
  ④ **诚实能力边界** —— layer_disk_offload 是预告，绝不返回；
     layer_cpu_offload（刀2 落地）只给**显式声明 supported_modes** 的引擎；
  ⑤ **零重依赖** —— 本模块顶层不得 import torch / diffusers（pytest 组合场景血泪）。

注：所有用例都**注入显存值**（free/total），不在测试里真探测 —— 保证任何机器上确定性。
"""
import ast
import inspect
import pathlib

import pytest

from app.core.neural import memory_policy as MP


def _pick(mid, frames=0, free=6.0, total=8.0, **kw):
    """统一注入显存，保证确定性（本机真有 8GB 卡，不注入会随占用波动）。"""
    return MP.pick_memory_policy(
        mid, frames=frames, free_vram_gb=free, total_vram_gb=total, **kw)


# ─────────────────── ① 实测基线（2026-10-01 本机数字）───────────────────

def test_floor_estimate_matches_measured_offload():
    """★ offload 下限估计必须贴合实测：5f 4.66 / 8f 5.58 / 10f 6.20（±0.1GB）。"""
    for frames, measured in ((5, 4.66), (8, 5.58), (10, 6.20)):
        est = MP.estimate_floor_gb("svd-xt-i2v", frames, MP.MODE_MODEL_OFFLOAD)
        assert est is not None
        assert abs(est - measured) <= 0.10, (frames, est, measured)


def test_floor_estimate_matches_measured_whole_gpu():
    """不 offload 的危险路径同样留数：5f 5.84 / 10f 7.70（±0.1GB）。"""
    for frames, measured in ((5, 5.84), (10, 7.70)):
        est = MP.estimate_floor_gb("svd-xt-i2v", frames, MP.MODE_WHOLE_GPU)
        assert est is not None
        assert abs(est - measured) <= 0.10, (frames, est, measured)


def test_floor_estimate_honest_none_without_evidence():
    """无实测、无参数量 ⇒ 返回 None（**不编数字**）。"""
    assert MP.estimate_floor_gb("__unknown__", 10, MP.MODE_MODEL_OFFLOAD) is None
    # 有参数量时可粗估（fp16 ≈ 2B/参 × 1.3 开销）
    assert MP.estimate_floor_gb("__unknown__", 10, MP.MODE_MODEL_OFFLOAD,
                                params_b=5.0) == round(5.0 * 2 * 1.3, 2)


# ─────────────────── ② SVD 定稿结论（两次反转后锁死）───────────────────

def test_svd_always_offload_all_frame_counts():
    """★ SVD 全帧数都 offload（关 offload 10 帧实测 >600s 分页卡死）。

    注意「都 offload」≠「都 model_offload」：超出实测安全域的帧数
    （25 帧外推 ≈10.85GB > 8GB×95%）**应该**升级 sequential ——
    这是策略在干活，不是漂移（升级仍属 offload，见下一条）。
    """
    for fr in (0, 2, 5, 6, 8, 10):          # 实测安全域内
        pol = _pick("svd-xt-i2v", frames=fr)
        assert pol["mode"] == MP.MODE_MODEL_OFFLOAD, (fr, pol)
        assert pol["offload"] is True, (fr, pol)
    for fr in (25, 60):                     # 超实测安全域 ⇒ 升级 sequential
        pol = _pick("svd-xt-i2v", frames=fr)
        assert pol["mode"] == MP.MODE_SEQUENTIAL_OFFLOAD, (fr, pol)
        assert pol["offload"] is True, (fr, pol)


def test_svd_policy_carries_tuned_chunk_and_fp16():
    """SVD 策略必须带实测调优值：chunk=1（比 2 快约 6 倍）、fp16。"""
    pol = _pick("svd-xt-i2v", frames=10)
    assert pol["decode_chunk_size"] == 1
    assert pol["quant"] == "fp16"
    assert abs(pol["floor_gb"] - 6.20) <= 0.10


def test_svd_policy_mentions_measured_reversal():
    """SVD 决策理由里必须留实测定稿依据（防后人凭直觉改回去）。"""
    pol = _pick("svd-xt-i2v", frames=5)
    joined = " ".join(pol["reasons"])
    assert "实测" in joined or "offload" in joined


# ─────────────────── ③ 决策可见性（reasons 永不为空）───────────────────

@pytest.mark.parametrize("mid,frames", [
    ("svd-xt-i2v", 0), ("svd-xt-i2v", 10),
    ("wan22-ti2v-5b", 5), ("__unknown__", 5),
])
def test_reasons_never_empty(mid, frames):
    pol = _pick(mid, frames=frames)
    assert pol["reasons"], f"{mid}@{frames} 的决策没有理由"
    assert all(isinstance(r, str) and r for r in pol["reasons"])


def test_vram_visibility_in_policy():
    """决策时看到的显存必须回传（排查时不用猜当时看到几 GB）。"""
    pol = _pick("svd-xt-i2v", frames=5, free=6.5, total=8.0)
    assert pol["free_vram_gb"] == 6.5
    assert pol["total_vram_gb"] == 8.0


# ─────────────────── ④ 模式边界与诚实能力 ───────────────────

def test_layer_disk_offload_is_planned_not_returned():
    """★ 绝不返回 layer_disk_offload（mmap 磁盘流式仍未实现，明说还没做，不假装有）。
    即使引擎声明四档全支持、登记占用顶爆，也只到 sequential，不出 layer_disk。"""
    for fr in (0, 5, 10, 25, 60):
        pol = _pick("svd-xt-i2v", frames=fr)
        assert pol["mode"] in MP.ACTIVE_MODES
        assert pol["mode"] != MP.MODE_LAYER_DISK_OFFLOAD
        assert MP.MODE_LAYER_DISK_OFFLOAD in pol["planned_modes"]
    # 声明全能力 + 登记 16GB（超 95%）⇒ sequential，仍不是 layer_disk
    pol = _pick("__big__", frames=0, registered_vram_gb=16.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_SEQUENTIAL_OFFLOAD
    assert MP.MODE_LAYER_DISK_OFFLOAD in pol["planned_modes"]


# ─────────────── ④' layer_cpu_offload（刀2 新档，2026-10-03）───────────────

def test_layer_cpu_in_active_but_not_legacy():
    """★ 模式常量契约：layer_cpu 已 ACTIVE；layer_disk 仍 PLANNED；
    旧调用方（不声明 supported_modes）兼容层**不含** layer_cpu。"""
    assert MP.MODE_LAYER_CPU_OFFLOAD in MP.ACTIVE_MODES
    assert MP.MODE_LAYER_DISK_OFFLOAD in MP.PLANNED_MODES
    assert MP.MODE_LAYER_DISK_OFFLOAD not in MP.ACTIVE_MODES
    assert MP.MODE_LAYER_CPU_OFFLOAD not in MP._LEGACY_MODES


def test_layer_cpu_requires_explicit_supported_modes():
    """★ 能力声明门禁：登记 7.0GB on 8GB（SDXL 场景）——
    不声明 supported_modes ⇒ 兼容旧行为 model_offload（绝不静默给 layer）；
    声明 ACTIVE_MODES ⇒ layer_cpu_offload。"""
    pol_legacy = _pick("sdxl-t2i", frames=0, registered_vram_gb=7.0, total=8.0)
    assert pol_legacy["mode"] == MP.MODE_MODEL_OFFLOAD, pol_legacy
    pol = _pick("sdxl-t2i", frames=0, registered_vram_gb=7.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_LAYER_CPU_OFFLOAD, pol
    assert pol["offload"] is True
    assert any("layer_cpu_offload" in r for r in pol["reasons"])


def test_layer_cpu_floor_is_honest_none():
    """★ layer 档 floor 暂无实测依据 ⇒ None（不拿 params_b 粗估 ——
    「全量驻留」语义对逐层卸载不成立；刀2-4 实测后补登记）。"""
    pol = _pick("sdxl-t2i", frames=0, registered_vram_gb=7.0, total=8.0,
                params_b=3.5, supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_LAYER_CPU_OFFLOAD
    assert pol["floor_gb"] is None


def test_layer_cpu_not_triggered_below_mid_water():
    """★ 中间水位线下不触发：SD1.5 登记 3.0GB ≤ 8×0.6=4.8 ⇒ 仍 model_offload
    （刀1 M1/M2 基线不受影响，即使声明了全能力）。"""
    pol = _pick("sd15-t2i", frames=0, registered_vram_gb=3.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_MODEL_OFFLOAD


def test_sequential_still_wins_over_layer_above_high_water():
    """★ 95% 高水位优先：登记 8.0GB on 8GB 且声明全能力 ⇒ 仍 sequential
    （layer 是中间档，不抢 sequential 的极端场景）。"""
    pol = _pick("wan22-ti2v-5b", frames=5, registered_vram_gb=8.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_SEQUENTIAL_OFFLOAD


# ─────────────── ④'' prefer_mode（刀2 四档实测产物，2026-10-03）───────────────

def test_sdxl_measured_floor_registered():
    """★ SDXL 四档实测下限登记（20 步 1024² fp16，bench_sdxl_modes.py）：
    model 5.21GB / sequential 3.76GB（图像 frames=0 ⇒ 下限=base）。"""
    assert abs(MP.estimate_floor_gb("sdxl-t2i", 0, MP.MODE_MODEL_OFFLOAD) - 5.21) < 1e-6
    assert abs(MP.estimate_floor_gb("sdxl-t2i", 0, MP.MODE_SEQUENTIAL_OFFLOAD) - 3.76) < 1e-6


def test_prefer_mode_honored_when_declared():
    """★ 调优表实测指定 prefer_mode 且引擎声明支持 ⇒ 采纳（分支 0 优先于水位分支）。
    SDXL 场景：prefer model（R2/R3 受控两轮：5.21GB/27.9s 定稿），
    即使登记 vram 落 layer 区间也走 model_offload。"""
    tuned = {"offload": True, "decode_chunk_size": 1, "prefer_mode": "model_offload"}
    pol = _pick("sdxl-t2i", frames=0, tuned=tuned, registered_vram_gb=7.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_MODEL_OFFLOAD, pol
    assert abs(pol["floor_gb"] - 5.21) < 1e-6      # 实测下限，不是编的数字
    assert any("prefer_mode" in r for r in pol["reasons"])


def test_prefer_mode_ignored_when_engine_not_declared():
    """★ prefer_mode 但引擎**未声明**该档 ⇒ 忽略并走常规分支（诚实降级，理由可见）。
    例：prefer layer_cpu 但 supported_modes 只有旧三档 ⇒ 落回 model_offload。"""
    tuned = {"offload": True, "decode_chunk_size": 1, "prefer_mode": "layer_cpu_offload"}
    pol = _pick("sdxl-t2i", frames=0, tuned=tuned, registered_vram_gb=7.0, total=8.0)
    assert pol["mode"] == MP.MODE_MODEL_OFFLOAD, pol
    assert any("忽略" in r for r in pol["reasons"])


def test_prefer_mode_never_bypasses_whole_gpu_safety():
    """★ prefer_mode=whole_gpu 不被采纳（whole_gpu 只能走分支 1 的双条件检查，
    绝不许用 prefer 绕过 15% 余量线）。"""
    tuned = {"offload": True, "decode_chunk_size": 1, "prefer_mode": "whole_gpu"}
    pol = _pick("sdxl-t2i", frames=0, tuned=tuned, registered_vram_gb=7.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] != MP.MODE_WHOLE_GPU


def test_prefer_mode_planned_is_honestly_ignored():
    """★ prefer 一个 PLANNED 档（layer_disk_offload）⇒ 明说「还没做」并忽略。"""
    tuned = {"offload": True, "decode_chunk_size": 1, "prefer_mode": "layer_disk_offload"}
    pol = _pick("sd15-t2i", frames=0, tuned=tuned, registered_vram_gb=3.0, total=8.0,
                supported_modes=MP.ACTIVE_MODES)
    assert pol["mode"] == MP.MODE_MODEL_OFFLOAD
    assert any("尚未实现" in r or "忽略" in r for r in pol["reasons"])


def test_whole_gpu_only_when_tuned_says_so_and_fits():
    """whole_gpu 双条件：调优表 offload=False **且**下限留出 15% 余量。"""
    tuned_whole = {"offload": False, "decode_chunk_size": 2}
    # 余量够：5 帧下限 5.83GB ≤ 8×0.85=6.8 ⇒ 允许 whole_gpu
    pol = _pick("svd-xt-i2v", frames=5, tuned=tuned_whole)
    assert pol["mode"] == MP.MODE_WHOLE_GPU
    assert pol["offload"] is False
    # 余量不够：10 帧下限 7.68GB > 6.8 ⇒ **诚实改判** model_offload（宁慢勿炸）
    pol2 = _pick("svd-xt-i2v", frames=10, tuned=tuned_whole)
    assert pol2["mode"] == MP.MODE_MODEL_OFFLOAD
    assert pol2["offload"] is True
    assert any("改判" in r for r in pol2["reasons"])


def test_sequential_escalation_by_registered_vram():
    """登记 vram 超 95% 水位线 ⇒ 升级 sequential（例：Wan 登记 8.0GB on 8GB 卡）。"""
    pol = _pick("wan22-ti2v-5b", frames=5, registered_vram_gb=8.0, total=8.0)
    assert pol["mode"] == MP.MODE_SEQUENTIAL_OFFLOAD
    assert pol["offload"] is True          # sequential 也是 offload 的一种
    assert any("sequential" in r for r in pol["reasons"])


def test_sequential_escalation_by_floor_extrapolation():
    """按帧数外推超水位 ⇒ 升级 sequential（SVD 60 帧 ≈21.7GB 远超 8GB）。"""
    pol = _pick("svd-xt-i2v", frames=60, total=8.0)
    assert pol["mode"] == MP.MODE_SEQUENTIAL_OFFLOAD
    assert pol["floor_gb"] > 8.0


def test_unregistered_model_conservative():
    """未登记模型：保守 model_offload + chunk=2（与 video_gen 兜底默认一致）。"""
    pol = _pick("__unknown__", frames=5)
    assert pol["mode"] == MP.MODE_MODEL_OFFLOAD
    assert pol["offload"] is True
    assert pol["decode_chunk_size"] == 2
    assert pol["floor_gb"] is None         # 无实测依据不编数字


# ─────────────────── ⑤ 零重依赖（pytest 组合场景血泪）───────────────────

def test_module_does_not_import_torch_or_diffusers_at_top_level():
    """★ 顶层不得 import torch/diffusers（探测必须在函数内、且只做 find_spec+torch）。"""
    src = pathlib.Path(MP.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:  # 只看顶层语句
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) \
                else [node.module or ""]
            for m in mods:
                assert not m.split(".")[0] in ("torch", "diffusers"), \
                    f"顶层 import 了重依赖: {m}"


def test_probe_uses_find_spec_not_diffusers():
    """probe_vram 源码：find_spec 在前，且**没有 import diffusers 语句**。

    ★ 必须用 AST 查真实 import 节点，不能用裸 substring ——
    docstring 里写「绝不 import diffusers」也会命中 substring（本用例踩过）。
    """
    src = inspect.getsource(MP.probe_vram)
    assert "find_spec" in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "diffusers" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "diffusers"


# ─────────────────── 与 video_gen 的收口关系 ───────────────────

def test_video_gen_should_offload_delegates_to_policy():
    """★ video_gen.should_offload 必须已是 memory_policy 的薄壳（收口完成）。"""
    from app.core.neural import video_gen as V
    src = inspect.getsource(V.should_offload)
    assert "pick_memory_policy" in src
    # 行为不变（既有测试也锁这个，这里再钉一次收口后的语义）
    for fr in (0, 5, 10, 25):
        assert V.should_offload("svd-xt-i2v", fr) is True
        assert V.should_offload("__unknown__", fr) is True


def test_video_gen_load_uses_policy_modes():
    """load() 必须消费 mode（model/sequential/whole_gpu），不再是裸 bool 判定。"""
    from app.core.neural import video_gen as V
    src = inspect.getsource(V.VideoGenEngine.load)
    assert "pick_memory_policy" in src
    assert "enable_sequential_cpu_offload" in src
    assert "enable_model_cpu_offload" in src
