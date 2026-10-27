# -*- coding: utf-8 -*-
"""P0 推理缓存三件套单测（V4.47.0）—— 无 GPU 依赖（假 UNet / 假 pipe / CPU 张量）。

覆盖 app/core/neural/inference_cache.py 五组件 + 两处引擎接线：
  · StepFeatureCache：全/复用步循环、短路命中、detach 还原、返回契约
  · LowRankFeatureCache：采样/校准/投影/重建/吸收式折叠（数学正确性）
  · EncoderOutputCache：LRU 双闸、驻留决策、键构造
  · VramBlockPool：size-class 复用、字节账、零拷贝视图往返
  · cache_gate：档位矩阵（含反例：final 永不开 / 白名单外 arch 不开）
  · 接线：diffusers_image._t2i_image 的 off/hit/miss/fallback 四态
  · 接线：卸载序列收口（local_video_pipe_cache 改调 release_vram_sequence）

反例纪律（项目传统）：每个「必须拒绝」的分支都有断言——门禁不是永远绿的摆设。
"""

import weakref

import pytest

torch = pytest.importorskip("torch")


# ────────────────────── 假 UNet（diffusers 尾部结构同构）──────────────────────
C, H, W = 8, 4, 4


class _FakeBlock(torch.nn.Module):
    """up_block 替身：记录调用次数（短路 ⇒ 调用次数不涨）。

    必须是 nn.Module：attach 依赖 `register_forward_pre_hook`（挂 unet 上）与
    `block.forward = wrapped` 实例属性替换（nn.Module.__call__ 查实例 dict 优先）。
    """

    def __init__(self, cin, cout):
        super().__init__()
        self.conv = torch.nn.Conv2d(cin, cout, 1)
        self.calls = 0

    def forward(self, x):
        self.calls += 1
        return self.conv(x)


class _FakeUNet(torch.nn.Module):
    """与 diffusers UNet2DConditionModel 同构的尾部：
    conv_norm_out(GroupNorm)→conv_act(SiLU)→conv_out（源码 :1227-1229 已核实）。
    """

    def __init__(self, n_up=3, with_norm=True):
        super().__init__()
        self.up_blocks = torch.nn.ModuleList([_FakeBlock(C, C) for _ in range(n_up)])
        self.conv_norm_out = torch.nn.GroupNorm(4, C) if with_norm else None
        self.conv_act = torch.nn.SiLU() if with_norm else None
        self.conv_out = torch.nn.Conv2d(C, 2, 1)

    def forward(self, x):
        for b in self.up_blocks:
            x = b(x)
        if self.conv_norm_out is not None:
            x = self.conv_norm_out(x)
            x = self.conv_act(x)
        return self.conv_out(x)


class _FakePipe:
    def __init__(self, unet):
        self.unet = unet


from app.core.neural.inference_cache import (
    EncoderOutputCache,
    LowRankFeatureCache,
    StepFeatureCache,
    VramBlockPool,
    cache_gate,
    make_cache_key,
)


# ══════════════════════════════════════════════════════════════════════
# 1. StepFeatureCache
# ══════════════════════════════════════════════════════════════════════

class TestStepFeatureCache:
    def test_full_reuse_cycle_and_shortcircuit(self):
        """10 步 interval=3 ⇒ 全量 4 / 复用 6；复用步 up_block 真算次数不涨。"""
        unet = _FakeUNet()
        cache = StepFeatureCache()
        rep = cache.attach(_FakePipe(unet), arch="sd15", interval=3, branch_id=0)
        assert rep["ok"], rep
        cache.activate()
        before = [b.calls for b in unet.up_blocks]
        x = torch.randn(1, C, H, W)
        for _ in range(10):
            out = unet(x)
            assert out.shape == (1, 2, H, W)
        st = cache.stats()
        assert (st["full_steps"], st["reuse_steps"]) == (4, 6), st
        # 每个 block 只在全量步真算（+4），复用步 6 次全部短路
        for i, b in enumerate(unet.up_blocks):
            assert b.calls == before[i] + 4, (i, b.calls)
        assert st["reuse_hits"] == 18 and st["reuse_fallbacks"] == 0, st
        assert st["skip_ratio"] == pytest.approx(0.6), st
        cache.detach()

    def test_detach_restores_forward(self):
        """detach 后 block.forward 必须还原（漏一个 = 下次 generate 双倍短路）。"""
        unet = _FakeUNet()
        cache = StepFeatureCache()
        cache.attach(_FakePipe(unet), arch="sd15", interval=2)
        cache.activate()
        x = torch.randn(1, C, H, W)
        unet(x)
        cache.detach()
        calls = [b.calls for b in unet.up_blocks]
        unet(x)
        for b in unet.up_blocks:
            assert b.calls == calls[0] + 1
        # 再 attach/detach 一轮，确认无残留包裹（双倍短路会让 calls 只 +0/+2）
        c2 = StepFeatureCache()
        c2.attach(_FakePipe(unet), arch="sd15", interval=2)
        c2.activate()
        unet(x)
        st = c2.detach()
        assert st["full_steps"] == 1 and st["reuse_steps"] == 0, st

    def test_branch_id_keeps_lower_blocks_computed(self):
        """branch_id=1 ⇒ 第 0 个 block 复用步也真算（只有 idx≥branch 短路）。"""
        unet = _FakeUNet()
        cache = StepFeatureCache()
        cache.attach(_FakePipe(unet), arch="sd15", interval=2, branch_id=1)
        cache.activate()
        x = torch.randn(1, C, H, W)
        for _ in range(4):      # 步 1,3 全量；步 2,4 复用
            unet(x)
        st = cache.stats()
        assert st["reuse_hits"] == 4, st      # 2 个复用步 × 2 个块（idx 1,2）
        assert unet.up_blocks[0].calls == 4   # block0 步步真算
        assert unet.up_blocks[1].calls == 2   # block1 只全量步算
        cache.detach()

    def test_attach_rejects_bad_structure(self):
        """反例：interval<2 / branch 越界 / 无 up_blocks ⇒ ok=False 且不半挂起。"""
        bad = StepFeatureCache().attach(_FakePipe(_FakeUNet()), arch="sd15", interval=1)
        assert not bad["ok"] and "interval" in bad["reasons"][0]

        c = StepFeatureCache()
        r = c.attach(_FakePipe(_FakeUNet()), arch="sd15", interval=3, branch_id=99)
        assert not r["ok"] and "越界" in r["reasons"][0]
        assert c._wrapped == [] and c._step_hook is None, "拒绝后不得留半挂起状态"

        class _NoUp:
            unet = object()

        r2 = StepFeatureCache().attach(_NoUp(), arch="sd15", interval=3)
        assert not r2["ok"] and "up_blocks" in r2["reasons"][0]

    def test_not_activated_passes_through(self):
        """attach 后未 activate ⇒ 全量放行、零缓存（activate 前语义=原管线）。"""
        unet = _FakeUNet()
        cache = StepFeatureCache()
        cache.attach(_FakePipe(unet), arch="sd15", interval=3)
        x = torch.randn(1, C, H, W)
        for _ in range(4):
            unet(x)
        st = cache.stats()
        assert st["cached_slots"] == 0 and st["full_steps"] == 0, st
        assert all(b.calls == 4 for b in unet.up_blocks)
        cache.detach()

    def test_first_step_is_always_full(self):
        """第 1 步必全量 ⇒ 复用步不可能缓存缺失（reuse_fallbacks 恒 0）。"""
        unet = _FakeUNet()
        cache = StepFeatureCache()
        cache.attach(_FakePipe(unet), arch="sd15", interval=5)
        cache.activate()
        x = torch.randn(1, C, H, W)
        for _ in range(7):
            unet(x)
        st = cache.stats()
        assert st["reuse_fallbacks"] == 0, st
        cache.detach()


# ══════════════════════════════════════════════════════════════════════
# 2. LowRankFeatureCache
# ══════════════════════════════════════════════════════════════════════

class TestLowRankFeatureCache:
    def test_project_reconstruct_roundtrip_energy(self):
        """低秩重建数学恒等：秩亏输入（仅前 4 通道非零）⇒ top-4 子空间精确重建。

        用秩亏输入而不是随机输入：随机数据的误差是统计量（随 seed 漂），
        秩亏数据的误差是数学恒等（≈0）——恒等断言比阈值断言强。
        """
        torch.manual_seed(0)
        h = torch.zeros(1, C, H, W)
        h[:, :4] = torch.randn(1, 4, H, W)
        lr = LowRankFeatureCache(rank_ratio=0.5)
        for _ in range(3):
            assert lr.add_sample(h)
        assert lr.samples_enough()
        rep = lr.calibrate()
        assert rep["ok"] and rep["rank"] == C // 2, rep
        m = lr.project(h)
        assert m.shape == (1, C // 2, H, W), m.shape
        back = lr.reconstruct(m)
        err = ((back - h).norm() / h.norm()).item()
        assert err < 1e-4, err     # 秩亏 ⇒ 精确（数学恒等，非统计）
        st = lr.stats()
        assert st["compress_ratio"] == 2.0, st
        assert st["energy"] == pytest.approx(1.0, abs=1e-3), st

    def test_lowrank_error_bounded_on_full_rank(self):
        """满秩随机输入：低秩重建误差有界且不爆表（证明压缩真发生、不发散）。"""
        torch.manual_seed(1)
        h = torch.randn(1, C, H, W)
        lr = LowRankFeatureCache(rank_ratio=0.5)
        for _ in range(3):
            lr.add_sample(h)
        lr.calibrate()
        err = ((lr.reconstruct(lr.project(h)) - h).norm() / h.norm()).item()
        # 4/8 秩对随机数据 ~0.5：下界 0 证「真压缩了」，上界 0.7 证「没发散」
        assert 0.0 < err < 0.7, err

    def test_energy_is_not_identically_one(self):
        """★ energy 遥测必须**随秩变化**，恒等 1.0 的口径是失效遥测。

        回归背景（2026-10-25）：旧口径 `sum(S[:r])/sum(S)`，而
        `svd_lowrank(G, q=r)` 只返回 r 个奇异值 ⇒ 分子分母恒等 ⇒ energy
        永远是 1.0，标定台的「energy ≥ 0.99」验收变成永远绿的摆设。
        修正后 energy = Σ_{i<r} λ_i / trace(G)（full-rank 谱能量占比）。

        本测试用**满秩**随机输入（秩亏输入下新旧口径都是 1.0 ⇒ 抓不到 bug）：
          · 秩 r=C/2 ⇒ 保留部分能量 ⇒ energy 必须 < 1
          · 秩越大 ⇒ 保留能量单调不减 ⇒ 能量曲线必须真的动
        """
        torch.manual_seed(2)
        h = torch.randn(1, C, H, W)
        energies = []
        for ratio in (0.125, 0.25, 0.5, 0.9):
            lr = LowRankFeatureCache(rank_ratio=ratio)
            for _ in range(3):
                lr.add_sample(h)
            rep = lr.calibrate()
            assert rep["ok"], rep
            energies.append(rep["energy"])
        # 满秩随机输入：任何 r < C 的子空间都丢能量 ⇒ 第一个必须 < 1
        assert energies[0] < 1.0, energies
        # 单调不减（保留方向越多 ⇒ 能量占比越高）
        assert energies == sorted(energies), energies
        # 保留能量占比落在合理区间（满秩随机谱衰减平缓，不该是 0 或 1）
        assert all(0.0 < e <= 1.0 for e in energies), energies

    def test_energy_matches_manual_spectrum(self):
        """energy 口径对账：与手工算的 top-r 谱能量占比一致（口径不被悄悄改）。"""
        torch.manual_seed(3)
        h = torch.randn(1, C, H, W)
        lr = LowRankFeatureCache(rank_ratio=0.5)
        for _ in range(3):
            lr.add_sample(h)
        rep = lr.calibrate()
        assert rep["ok"], rep
        # 手工：Gram 的完整特征谱（对称半正定 ⇒ 特征值=奇异值）
        x = h.reshape(-1, C, H * W)[0].to(torch.float32)
        gram = x @ x.t()
        eigs = torch.linalg.eigvalsh(gram).flip(0).clamp(min=0.0)
        r = C // 2
        expect = float(eigs[:r].sum() / eigs.sum())
        assert rep["energy"] == pytest.approx(expect, abs=0.02), (rep, expect)

    def test_calibrate_idempotent_and_insufficient(self):
        """样本不足 ⇒ 不校准（ok=False 留痕）；已校准 ⇒ 幂等跳过。"""
        lr = LowRankFeatureCache()
        r0 = lr.calibrate()
        assert not r0["ok"] and "样本不足" in r0["reason"]
        torch.manual_seed(1)
        h = torch.randn(1, C, H, W)
        lr.add_sample(h)
        lr.add_sample(h)
        assert not lr.samples_enough()
        r1 = lr.calibrate()
        assert not r1["ok"]
        lr.add_sample(h)
        r2 = lr.calibrate()
        assert r2["ok"]
        r3 = lr.calibrate()
        assert r3["ok"] and "幂等" in r3["reason"]

    def test_bad_rank_ratio_rejected(self):
        """反例：rank_ratio 越界 ⇒ 直接 ValueError（不猜、不静默夹）。"""
        with pytest.raises(ValueError):
            LowRankFeatureCache(rank_ratio=0.01)
        with pytest.raises(ValueError):
            LowRankFeatureCache(rank_ratio=0.95)

    def test_fold_into_math_matches_direct_conv(self):
        """吸收式折叠数值正确性：fold(conv_out)(Uᵀh) == conv_out(h)。

        h 取秩亏（仅前 4 通道非零）⇒ r=4 子空间精确覆盖 ⇒ 数学恒等（≈0）。
        下标写反的 einsum 会 RuntimeError 或给出 O(1) 误差——1e-4 阈值两头都诛。
        """
        import torch.nn as nn

        torch.manual_seed(2)
        conv = nn.Conv2d(C, 3, 3, padding=1)
        lr = LowRankFeatureCache(rank_ratio=0.5)
        h = torch.zeros(1, C, H, W)
        h[:, :4] = torch.randn(1, 4, H, W)
        for _ in range(3):
            lr.add_sample(h)
        assert lr.calibrate()["ok"]
        new_conv, why = lr.fold_into(conv)
        assert new_conv is not None, why
        assert new_conv.in_channels == C // 2, new_conv
        m = lr.project(h)
        rel = ((new_conv(m) - conv(h)).norm() / conv(h).norm()).item()
        assert rel < 1e-4, "折叠改变数值 = 数学错（rel=%.6f）" % rel

    def test_fold_into_rejects_uncalibrated_and_mismatch(self):
        """反例：未校准 / 通道不符 ⇒ (None, 原因)，调用方走重建路径。"""
        import torch.nn as nn

        lr = LowRankFeatureCache()
        conv = nn.Conv2d(C, 3, 1)
        new_conv, why = lr.fold_into(conv)
        assert new_conv is None and "未校准" in why
        torch.manual_seed(3)
        h = torch.randn(1, C, H, W)
        for _ in range(3):
            lr.add_sample(h)
        lr.calibrate()
        wrong = nn.Conv2d(C + 4, 3, 1)                 # 输入通道 != 校准通道
        new_conv2, why2 = lr.fold_into(wrong)
        assert new_conv2 is None and "结构不符" in why2

    def test_absorbed_mode_folds_and_downstream_gets_projection(self):
        """ absorbed 变体（无 GroupNorm）：校准即折叠，全量步下游拿到 M（r 通道）。"""
        unet = _FakeUNet(with_norm=False)
        cache = StepFeatureCache()
        lr = LowRankFeatureCache(rank_ratio=0.25)
        rep = cache.attach(_FakePipe(unet), arch="sd15", interval=3, lowrank=lr)
        assert rep["ok"] and "吸收式" in rep["reasons"][-1], rep
        cache.activate()
        x = torch.randn(1, C, H, W)
        for _ in range(10):                            # 第 3 个全量步校准+折叠
            out = unet(x)
            assert out.shape == (1, 2, H, W), out.shape   # 尾部通道不崩
        st = cache.stats()
        assert st["folded"] is True, st
        assert unet.conv_out.in_channels == C // 4, unet.conv_out
        assert st["lowrank"]["reconstruct_calls"] == 0, "折叠后零解压税"
        cache.detach()

    def test_reconstruct_mode_when_norm_present(self):
        """有 GroupNorm（真实 SD/SDXL/SVD）⇒ 不折叠，复用步走重建路径。"""
        unet = _FakeUNet(with_norm=True)
        cache = StepFeatureCache()
        lr = LowRankFeatureCache(rank_ratio=0.25)
        cache.attach(_FakePipe(unet), arch="sd15", interval=2, lowrank=lr)
        cache.activate()
        x = torch.randn(1, C, H, W)
        for _ in range(6):
            out = unet(x)
            assert out.shape == (1, 2, H, W), out.shape
        st = cache.stats()
        assert st["absorbed"] is False and st["folded"] is False, st
        assert st["lowrank"]["reconstruct_calls"] > 0, st
        assert unet.conv_out.in_channels == C, "真实结构 conv_out 不许被换"
        cache.detach()


# ══════════════════════════════════════════════════════════════════════
# 3. EncoderOutputCache
# ══════════════════════════════════════════════════════════════════════

class TestEncoderOutputCache:
    def test_key_contains_all_variables(self):
        """键必须随任一变量变化（少一个字段 = 换 LoRA 出旧图级 bug）。"""
        base = dict(arch="sd15", model_id="m", prompt="p", negative_prompt="n")
        k0 = make_cache_key(**base)
        assert k0 == make_cache_key(**base)                      # 确定性
        assert k0 != make_cache_key(**dict(base, prompt="p2"))    # prompt
        assert k0 != make_cache_key(**dict(base, negative_prompt="n2"))
        assert k0 != make_cache_key(**dict(base, model_id="m2"))
        assert k0 != make_cache_key(**dict(base, arch="sdxl"))
        assert k0 != make_cache_key(**dict(base, lora_set="l"))
        assert k0 != make_cache_key(**dict(base, max_length=77 + 1))

    def test_lru_eviction_by_entries(self):
        """双闸之条数：超 max_entries ⇒ 淘汰最旧，命中率留痕。"""
        cache = EncoderOutputCache(max_entries=3)
        for i in range(5):
            cache.put("k%d" % i, {"prompt_embeds": torch.zeros(1, 2)})
        assert cache.stats()["entries"] == 3
        assert cache.stats()["evictions"] == 2
        assert cache.get("k0") is None and cache.get("k4") is not None

    def test_lru_eviction_by_bytes(self):
        """双闸之字节：超 max_bytes ⇒ 按字节淘汰。"""
        cache = EncoderOutputCache(max_entries=100, max_bytes=4096)
        for i in range(5):     # 每条 1024B ⇒ 第 5 条 put 后超 4096
            cache.put("b%d" % i, {"prompt_embeds": torch.zeros(256)})
        assert cache.stats()["bytes"] <= 4096, cache.stats()
        assert cache.stats()["evictions"] >= 1

    def test_get_refreshes_lru_order(self):
        """命中会刷新 LRU 次序（老键被反复命中 ⇒ 不被淘汰）。"""
        cache = EncoderOutputCache(max_entries=2)
        cache.put("a", {"prompt_embeds": torch.zeros(1)})
        cache.put("b", {"prompt_embeds": torch.zeros(1)})
        assert cache.get("a") is not None          # a 刷新成最新
        cache.put("c", {"prompt_embeds": torch.zeros(1)})   # 淘汰最旧的 b
        assert cache.get("b") is None and cache.get("a") is not None

    def test_residency_prefers_gpu_when_room(self, monkeypatch):
        """显存宽裕 ⇒ 驻 GPU；探测失败/吃紧 ⇒ 保守驻 CPU。"""
        cache = EncoderOutputCache()
        monkeypatch.setattr("app.core.neural.memory_policy.probe_vram",
                            lambda: {"free_gb": 8.0})
        assert cache._pick_residency(1024) == "cuda"
        monkeypatch.setattr("app.core.neural.memory_policy.probe_vram",
                            lambda: {"free_gb": 0.5})
        assert cache._pick_residency(1024) == "cpu"
        monkeypatch.setattr("app.core.neural.memory_policy.probe_vram",
                            lambda: None)
        assert cache._pick_residency(1024) == "cpu"

    def test_clear_and_stats(self):
        cache = EncoderOutputCache()
        cache.put("x", {"prompt_embeds": torch.zeros(1)})
        cache.get("x")
        cache.get("y")      # miss
        st = cache.stats()
        assert (st["hits"], st["misses"], st["puts"]) == (1, 1, 1), st
        assert cache.clear() == 1
        assert cache.stats()["entries"] == 0


# ══════════════════════════════════════════════════════════════════════
# 4. VramBlockPool
# ══════════════════════════════════════════════════════════════════════

class TestVramBlockPool:
    def test_roundtrip_zero_copy_view(self):
        """store_tree → as_tree 字节级一致（view 零拷贝）。"""
        pool = VramBlockPool(device="cpu")
        tree = (torch.randn(1, C, H, W), torch.randn(1, C, H, W) + 3.0)
        h = pool.store_tree(tree)
        assert h is not None
        back = h.as_tree(tree)
        for a, b in zip(tree, back, strict=True):
            assert torch.equal(a, b)
        pool.release(h)

    def test_size_class_reuse_and_freed_reset(self):
        """同 size-class 二次 acquire 复用旧块（命中），且 _freed 必须复位。"""
        pool = VramBlockPool(device="cpu")
        h1 = pool.acquire(1000)
        pool.release(h1)
        h2 = pool.acquire(2000)      # 同桶（1MB 级）⇒ 复用 h1 缓冲
        assert h2 is h1
        h2.copy_from(torch.zeros(2000, dtype=torch.uint8))    # 不抛「已 release」
        st = pool.stats()
        assert st["hits"] == 1 and st["acquires"] == 2, st
        pool.release(h2)

    def test_acquire_rejects_non_positive(self):
        pool = VramBlockPool(device="cpu")
        with pytest.raises(ValueError):
            pool.acquire(0)

    def test_fallback_oversize_not_bucketed(self, monkeypatch):
        """>1GB 精确定尺寸不进桶（fallback 计数）——monkeypatch 阈值免真分配 1GB。"""
        import app.core.neural.inference_cache as IC

        monkeypatch.setattr(IC, "_MAX_CLASS", 4096)
        pool = VramBlockPool(device="cpu")
        h = pool.acquire(4097)
        assert h.n_bytes == 4097 and h.capacity == 4097
        assert pool.stats()["fallbacks"] == 1
        pool.release(h)
        assert pool.stats()["free_classes"] == 0, "fallback 块不进桶（容量漂移混合源）"

    def test_release_updates_byte_accounting(self):
        pool = VramBlockPool(device="cpu")
        h = pool.acquire(4096)
        assert pool.stats()["live_bytes"] == 4096
        pool.release(h)
        assert pool.stats()["live_bytes"] == 0


# ══════════════════════════════════════════════════════════════════════
# 5. cache_gate 档位矩阵
# ══════════════════════════════════════════════════════════════════════

class TestCacheGate:
    def test_step_cache_default_off(self, monkeypatch):
        """默认关（决策点 C）：环境变量空 ⇒ ok=False 且理由可见。"""
        monkeypatch.delenv("SHIGUANG_STEP_CACHE", raising=False)
        g = cache_gate(arch="sd15", preset="fast", component="step_cache")
        assert not g["ok"]
        assert any("默认关" in r for r in g["reasons"])

    def test_step_cache_on_whitelisted(self, monkeypatch):
        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "deepcache")
        g = cache_gate(arch="sdxl", preset="fast", component="step_cache")
        assert g["ok"] and g["params"]["interval"] >= 2
        g2 = cache_gate(arch="svd", preset="preview", component="step_cache")
        assert g2["ok"]

    def test_step_cache_final_preset_never_on(self, monkeypatch):
        """反例：final/best 永不开（抽卡对细节敏感，LCM 偏软是前车之鉴）。"""
        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "deepcache")
        for p in ("final", "best", "balanced", ""):
            g = cache_gate(arch="sd15", preset=p, component="step_cache")
            assert not g["ok"], p
            assert any("白名单" in r for r in g["reasons"]), p

    def test_step_cache_unknown_arch_rejected(self, monkeypatch):
        """反例：未结构核实的 arch（wan 等 DiT）不进表——FBCache 是另一条探针。"""
        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "deepcache")
        g = cache_gate(arch="wan", preset="fast", component="step_cache")
        assert not g["ok"] and any("白名单" in r for r in g["reasons"])

    def test_encoder_cache_gate(self, monkeypatch):
        monkeypatch.delenv("SHIGUANG_ENCODER_CACHE", raising=False)
        g = cache_gate(arch="sd15", component="encoder_cache")
        assert not g["ok"] and any("默认关" in r for r in g["reasons"])
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        assert cache_gate(arch="sd15", component="encoder_cache")["ok"]
        # 反例：svd 无公开 encode_prompt ⇒ 白名单外
        assert not cache_gate(arch="svd", component="encoder_cache")["ok"]


# ══════════════════════════════════════════════════════════════════════
# 6. 引擎接线：diffusers_image._t2i_image 四态
# ══════════════════════════════════════════════════════════════════════

class _FakeResult:
    def __init__(self, tag):
        self.images = [tag]


class _FakeGenPipe:
    """最小 diffusers pipeline 替身：只实现编码器缓存路径用到的面。"""

    def __init__(self, arch="sd15"):
        import torch.nn as nn

        self.arch = arch
        self.tokenizer = nn.Identity()      # 占位；model_max_length 由 property 提供
        self._execution_device = "cpu"
        self.encode_calls = 0
        self.call_kw = None
        self.fail_encode = False

    @property
    def _tok(self):
        class _T:
            model_max_length = 77
        return _T()

    def encode_prompt(self, **kw):
        self.encode_calls += 1
        if self.fail_encode:
            raise RuntimeError("编码器炸了")
        if self.arch == "sdxl":
            return (torch.randn(1, 4, 4), torch.randn(1, 4, 4),
                    torch.randn(1, 4), torch.randn(1, 4))
        return torch.randn(1, 4, 4), torch.randn(1, 4, 4)

    def __call__(self, **kw):
        self.call_kw = kw
        return _FakeResult(kw)


@pytest.fixture()
def _fresh_encoder_cache():
    from app.core.neural.inference_cache import encoder_cache

    encoder_cache().clear()
    yield encoder_cache()
    encoder_cache().clear()


def _engine_with(pipe):
    from app.core.neural.diffusers_image import DiffusersImageEngine

    eng = DiffusersImageEngine()
    eng._pipe = pipe
    return eng


class TestT2iEncoderCacheWiring:
    def test_off_by_default(self, monkeypatch, _fresh_encoder_cache):
        """默认关 ⇒ 走 prompt 原路径（prompt= 在调用 kw 里），缓存零写入。"""
        monkeypatch.delenv("SHIGUANG_ENCODER_CACHE", raising=False)
        pipe = _FakeGenPipe()
        img, state = _engine_with(pipe)._t2i_image(
            prompt="p", negative_prompt="n", cfg=7.5, width=64, height=64,
            steps=5, generator=None, model_id="sd15-t2i", preset="fast")
        assert state == "off"
        assert "prompt" in pipe.call_kw and "prompt_embeds" not in pipe.call_kw
        assert pipe.encode_calls == 0
        assert _fresh_encoder_cache.stats()["puts"] == 0

    def test_miss_then_hit(self, monkeypatch, _fresh_encoder_cache):
        """开缓存：第一次 miss（编码一次+写缓存），第二次 hit（不再编码）。"""
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        pipe = _FakeGenPipe()
        eng = _engine_with(pipe)
        kw = dict(prompt="同一句", negative_prompt="", cfg=7.5, width=64,
                  height=64, steps=5, generator=None, model_id="sd15-t2i",
                  preset="fast")
        img1, s1 = eng._t2i_image(**kw)
        assert s1 == "miss" and pipe.encode_calls == 1
        assert "prompt_embeds" in pipe.call_kw
        img2, s2 = eng._t2i_image(**kw)
        assert s2 == "hit" and pipe.encode_calls == 1, "命中不得再编码"
        st = _fresh_encoder_cache.stats()
        assert (st["hits"], st["misses"], st["puts"]) == (1, 1, 1), st

    def test_hit_embeds_moved_to_execution_device(self, monkeypatch,
                                                  _fresh_encoder_cache):
        """命中时张量必须搬到 _execution_device（CPU 缓存 + GPU 执行不炸）。"""
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        pipe = _FakeGenPipe()
        pipe._execution_device = "cpu"
        eng = _engine_with(pipe)
        kw = dict(prompt="p", negative_prompt="", cfg=7.5, width=64, height=64,
                  steps=5, generator=None, model_id="sd15-t2i", preset="fast")
        eng._t2i_image(**kw)
        eng._t2i_image(**kw)
        assert pipe.call_kw["prompt_embeds"].device.type == "cpu"

    def test_key_varies_with_lora(self, monkeypatch, _fresh_encoder_cache):
        """键含 lora_set：换 LoRA 后同一 prompt 不得命中旧 embeds。"""
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        pipe = _FakeGenPipe()
        eng = _engine_with(pipe)
        base = dict(prompt="p", negative_prompt="", cfg=7.5, width=64,
                    height=64, steps=5, generator=None, model_id="sd15-t2i",
                    preset="fast")
        eng._t2i_image(**base)
        eng._lcm_lora = "/path/lcm.safetensors"
        img, state = eng._t2i_image(**base)
        assert state == "miss", "lora_set 变 ⇒ 必须 miss（否则换 LoRA 出旧 embeds）"
        assert pipe.encode_calls == 2

    def test_sdxl_pooled_four_pack(self, monkeypatch, _fresh_encoder_cache):
        """SDXL 必须带 pooled 四件套（缺一个 __call__ 当场炸）。"""
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        pipe = _FakeGenPipe(arch="sdxl")
        img, state = _engine_with(pipe)._t2i_image(
            prompt="p", negative_prompt="", cfg=7.5, width=64, height=64,
            steps=5, generator=None, model_id="sdxl-t2i", preset="fast")
        assert state == "miss"
        for k in ("prompt_embeds", "negative_prompt_embeds",
                  "pooled_prompt_embeds", "negative_pooled_prompt_embeds"):
            assert k in pipe.call_kw, k
        # 二次命中时 pooled 也必须在（缓存存的是四件套）
        img2, state2 = _engine_with(pipe)._t2i_image(
            prompt="p", negative_prompt="", cfg=7.5, width=64, height=64,
            steps=5, generator=None, model_id="sdxl-t2i", preset="fast")
        assert state2 == "hit" and "pooled_prompt_embeds" in pipe.call_kw

    def test_encode_failure_falls_back(self, monkeypatch, _fresh_encoder_cache):
        """反例：编码失败 ⇒ 诚实回退 prompt 原路径（fallback），不假装成功。"""
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        pipe = _FakeGenPipe()
        pipe.fail_encode = True
        img, state = _engine_with(pipe)._t2i_image(
            prompt="p", negative_prompt="", cfg=7.5, width=64, height=64,
            steps=5, generator=None, model_id="sd15-t2i", preset="fast")
        assert state == "fallback"
        assert "prompt" in pipe.call_kw, "回退后必须走原 prompt 路径"

    def test_unload_clears_encoder_cache(self, monkeypatch,
                                         _fresh_encoder_cache):
        """unload 必须清编码缓存（不清 = 卸载后 GPU/CPU 仍驻留编码张量）。"""
        monkeypatch.setenv("SHIGUANG_ENCODER_CACHE", "1")
        pipe = _FakeGenPipe()
        eng = _engine_with(pipe)
        eng._t2i_image(prompt="p", negative_prompt="", cfg=7.5, width=64,
                       height=64, steps=5, generator=None,
                       model_id="sd15-t2i", preset="fast")
        assert _fresh_encoder_cache.stats()["entries"] == 1
        eng.unload()
        assert _fresh_encoder_cache.stats()["entries"] == 0


# ══════════════════════════════════════════════════════════════════════
# 8. 引擎接线：步缓存（P0-1）挂载/摘除
# ══════════════════════════════════════════════════════════════════════

class TestStepCacheWiring:
    def test_image_engine_attach_gate_matrix(self, monkeypatch):
        """门控矩阵经引擎 helper 落地：关/开/档位拒/arch 拒四态。"""
        from app.core.neural.diffusers_image import DiffusersImageEngine

        def _eng():
            e = DiffusersImageEngine()
            e._pipe = _FakePipe(_FakeUNet())
            return e

        monkeypatch.delenv("SHIGUANG_STEP_CACHE", raising=False)
        assert _eng()._maybe_attach_step_cache({"arch": "sd15"}, "fast") is None

        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "deepcache")
        sc = _eng()._maybe_attach_step_cache({"arch": "sd15"}, "fast")
        assert sc is not None and sc.stats()["attached"] is True
        assert sc.stats()["interval"] >= 2
        # 反例：final 档永不开；未知 arch 不开
        assert _eng()._maybe_attach_step_cache({"arch": "sd15"}, "final") is None
        assert _eng()._maybe_attach_step_cache({"arch": "wan"}, "fast") is None
        # 反例：无法识别的环境值按关处理
        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "turbo")
        assert _eng()._maybe_attach_step_cache({"arch": "sd15"}, "fast") is None

    def test_image_engine_detach_restores_after_generate_like_flow(self, monkeypatch):
        """端到端行为：attach→activate→多步前向→detach，forward 必须全还原。"""
        from app.core.neural.diffusers_image import DiffusersImageEngine

        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "deepcache")
        monkeypatch.setenv("SHIGUANG_STEP_CACHE_INTERVAL", "2")
        unet = _FakeUNet()
        eng = DiffusersImageEngine()
        eng._pipe = _FakePipe(unet)
        sc = eng._maybe_attach_step_cache({"arch": "sd15"}, "fast")
        assert sc is not None
        x = torch.randn(1, C, H, W)
        for _ in range(5):
            unet(x)
        st = sc.stats()
        assert st["full_steps"] == 3 and st["reuse_steps"] == 2, st
        eng._detach_step_cache(sc)
        calls = [b.calls for b in unet.up_blocks]
        unet(x)
        for i, b in enumerate(unet.up_blocks):
            assert b.calls == calls[i] + 1, "detach 后 forward 未还原（双倍短路隐患）"

    def test_image_engine_detach_none_is_noop(self):
        """未挂缓存时 _detach_step_cache(None) 必须静默通过（generate 常态路径）。"""
        from app.core.neural.diffusers_image import DiffusersImageEngine

        assert DiffusersImageEngine()._detach_step_cache(None) is None

    def test_video_engine_arch_derivation(self, monkeypatch):
        """视频侧 arch 由 pipeline 类名推导：SVD⇒svd（开）；空/DiT⇒拒。"""
        from app.core.neural.video_gen import VideoGenEngine

        def _eng():
            e = VideoGenEngine()
            e._pipe = _FakePipe(_FakeUNet())
            return e

        monkeypatch.setenv("SHIGUANG_STEP_CACHE", "deepcache")
        assert _eng()._attach_step_cache("svd", "preview") is not None
        assert _eng()._attach_step_cache("svd", "fast") is not None
        # 反例：默认档（空串）/balanced/best 不开；非 SVD arch 不开
        assert _eng()._attach_step_cache("svd", "") is None
        assert _eng()._attach_step_cache("svd", "balanced") is None
        assert _eng()._attach_step_cache("svd", "best") is None
        assert _eng()._attach_step_cache("", "preview") is None

    def test_generate_sources_have_attach_and_finally_detach(self):
        """接线证明（AST 级）：两条 generate 都必须 attach + finally detach。

        为什么查这个：忘了 finally = 异常路径下 forward 不还原，下一次 generate
        双倍短路——这是本组件最贵的回归模式，用源码断言锁死。
        """
        import inspect

        from app.core.neural import diffusers_image as DIF
        from app.core.neural import video_gen as VG

        for src_name, fn in (("diffusers_image.generate", DIF.DiffusersImageEngine.generate),
                             ("video_gen.generate", VG.VideoGenEngine.generate)):
            src = inspect.getsource(fn)
            assert "step_cache = " in src, f"{src_name} 未挂步缓存"
            assert "finally:" in src and "_detach_step_cache(step_cache)" in src, (
                f"{src_name} 缺 finally detach（异常路径会漏还原）")

# ══════════════════════════════════════════════════════════════════════
# 7. 卸载序列收口接线
# ══════════════════════════════════════════════════════════════════════

class TestReleaseSequenceWiring:
    def test_video_pipe_cache_uses_single_source(self):
        """local_video_pipe_cache 必须调 release_vram_sequence（勿再内联拆步骤）。"""
        import inspect

        import app.core.local_video_pipe_cache as VPC

        src = inspect.getsource(VPC._release_vram)
        assert "release_vram_sequence" in src
        assert not hasattr(VPC, "_gc_release"), "旧拆分函数必须已移除（双真源=漂移）"
        assert not hasattr(VPC, "_dispose"), "旧拆分函数必须已移除（双真源=漂移）"

    def test_video_pipe_cache_clear_still_collects(self):
        """收口后 weakref 语义不回归：clear 必须真回收。"""
        import gc

        import app.core.local_video_pipe_cache as VPC

        class _Fake:
            pass

        obj = _Fake()
        ref = weakref.ref(obj)
        VPC.get_or_load(("svd", "/m"), lambda: obj)
        obj = None
        assert VPC.clear() == 1
        gc.collect()
        assert ref() is None

    def test_release_vram_sequence_smoke(self):
        """真机冒烟（无 CUDA 也无妨）：返回结构完整、不炸。"""
        from app.core.neural.inference_cache import release_vram_sequence

        out = release_vram_sequence(collect=True)
        assert set(out) >= {"gc", "synced", "emptied", "ipc", "reason"}
        assert out["gc"] is True
