# -*- coding: utf-8 -*-
"""CFG 组合测试 —— P2 · 2026-10-28。

## 这里锁的是"写反了也能出图"的两件事

① **chunk 顺序必须是 `(uncond, text)`**。写反成 `(text, uncond)` 不会报错，
   只会得到负向引导：cfg 越大越难看，而第一反应一定是"模型有问题"。
   测试用可分辨的数值（uncond=1、text=3）来断言方向，而不是只断言"形状对"。

② **`scale <= 1` 必须原样返回**。多做一次 `uncond + 1*(text-uncond)` 数学上等于 text，
   但浮点上不相等；更要紧的是 `chunk(2)` 在 batch=1 时会炸，
   兜底吞掉后就变成"看起来没引导" —— 所以要断言"连 chunk 都没做"。

## `rescale_noise_cfg` 与上游逐值对照

自研实现只有与上游**逐位相等**才有资格叫"重实现"，否则就是"另一套算法"。
因此这里直接 import 上游 `diffusers.guiders.guider_utils.rescale_noise_cfg` 做对照
（这是本项目少见地允许 import 上游实现的地方：**对照物**可以来自上游，
**被替换物**不能 —— C3 说的是后者）。

⚠ 这个 import 链会拉进 `transformers → sentencepiece` 的 C 扩展，**必须在收集期**
完成（见下方 `_UPSTREAM_RESCALE` 注释）：用例执行期进程里有 `cache_system` 的
后台线程，那时加载该扩展实测会 access violation，整进程段错误。

唯一的**故意偏离**：`std_cfg` 为 0 时我们 clamp 到 eps，上游会产生 nan。
这条偏离写在下面的 `test_rescale_survives_constant_input` 里，是显式选择而非漏改。
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from app.core.neural.kernel import cfg as CFG

#: 上游对照物**在子进程里跑**，不在本进程 import diffusers。
#:
#: 为什么：`diffusers.guiders.guider_utils` 的 import 链会拉进
#: `transformers → sentencepiece` 的 C 扩展。本进程里只要已经起过
#: `app/core/cache_system.py` 的后台线程（全量套件跑起来必然有），加载它就会
#: **access violation —— 整进程段错误**，pytest 连"失败"都报不出来（实测 exit=139）。
#: 放到执行期也一样崩，放到收集期也一样崩：崩溃条件不是"单线程还是多线程"，
#: 而是"进程里有没有活线程"。所以在子进程里取对照值 —— 那里永远是干净的。
_UPSTREAM_CODE = r"""
import json
import torch
from diffusers.guiders.guider_utils import rescale_noise_cfg as f

torch.manual_seed(0)
a = torch.randn(2, 4, 16, 16)
b = torch.randn(2, 4, 16, 16)
const = torch.full((1, 4, 8, 8), 0.5)
out = {str(r): f(a, b, guidance_rescale=r).flatten().tolist() for r in (0.0, 0.3, 0.7)}
c = f(const, const, guidance_rescale=0.7)
print("RESULT:" + json.dumps({
    "values": out,
    "const_finite": bool(torch.isfinite(c).all()),
    "const_max": float(c.abs().max()),
}))
"""


def _upstream_reference() -> dict:
    """在干净子进程里取上游 `rescale_noise_cfg` 的输出（失败即红，不跳过）。"""
    import json
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "-c", _UPSTREAM_CODE],
                          capture_output=True, text=True, timeout=300)
    line = ""
    for ln in (proc.stdout or "").splitlines():
        if ln.startswith("RESULT:"):
            line = ln[len("RESULT:"):]
            break
    assert line, ("子进程没拿到对照值（rc=%s）\nstdout=%s\nstderr=%s"
                  % (proc.returncode, (proc.stdout or "")[-1500:],
                     (proc.stderr or "")[-1500:]))
    return json.loads(line)


@pytest.fixture(scope="module")
def upstream() -> dict:
    """模块级缓存：一个子进程够三次对照用（每次都要重装 torch 太贵）。"""
    return _upstream_reference()


# ══════════════════════════════════════════════════════════════════
# 基本形状 / 顺序
# ══════════════════════════════════════════════════════════════════

def test_cfg_order_constant_is_neg_pos():
    """契约字面值：`ParityContract.fields["cfg_order"]` 也写这个值，两处必须一致。"""
    assert CFG.CFG_ORDER == "neg_pos"


def test_chunk_order_is_uncond_then_text():
    """`cat([neg]*2)` 后 chunk(2) 的第一个是 uncond。

    造 uncond 全 1、text 全 3、scale=5 ⇒ 输出应全为 1 + 5*(3-1) = 11。
    若顺序反了会得到 3 + 5*(1-3) = -7 —— 数值方向完全相反，一眼可辨。
    """
    noise = torch.tensor([[1.0, 1.0], [3.0, 3.0]])
    out = CFG.combine(noise, mode="cat", scale=5.0)
    assert torch.allclose(out, torch.full((1, 2), 11.0)), out


def test_scale_one_returns_input_object_untouched():
    """scale ≤ 1 ⇒ 直接返回原对象（连 chunk 都不做，batch=1 也不会炸）。"""
    noise = torch.zeros(1, 4, 8, 8)
    out = CFG.combine(noise, mode="cat", scale=1.0)
    assert out is noise


def test_scale_below_one_also_skips():
    noise = torch.zeros(2, 4, 8, 8)
    assert CFG.combine(noise, mode="cat", scale=0.7) is noise


def test_mode_none_returns_input():
    noise = torch.zeros(2, 4, 8, 8)
    assert CFG.combine(noise, mode="none", scale=7.5) is noise


def test_mode_two_pass_defers_to_caller():
    """`two_pass` 在 combine 里只透传：真正组合由 `combine_two_pass` 做。"""
    noise = torch.randn(1, 4, 8, 8)
    assert CFG.combine(noise, mode="two_pass", scale=7.5) is noise


def test_combine_two_pass_matches_cat_math():
    uncond = torch.randn(1, 4, 8, 8)
    text = torch.randn(1, 4, 8, 8)
    cat = CFG.combine(torch.cat([uncond, text]), mode="cat", scale=6.0)
    two = CFG.combine_two_pass(uncond, text, scale=6.0)
    assert torch.equal(cat, two)


def test_combine_two_pass_scale_one_returns_text():
    uncond = torch.randn(1, 4, 8, 8)
    text = torch.randn(1, 4, 8, 8)
    assert CFG.combine_two_pass(uncond, text, scale=1.0) is text


# ══════════════════════════════════════════════════════════════════
# expand_for_guidance
# ══════════════════════════════════════════════════════════════════

def test_expand_replicates_same_latent():
    """CFG 复制的必须是**同一份**潜变量：差异只由条件承担。"""
    x = torch.randn(1, 4, 8, 8)
    out = CFG.expand_for_guidance(x, 2)
    assert out.shape == (2, 4, 8, 8)
    assert torch.equal(out[0], out[1])
    assert torch.equal(out[0], x[0])


def test_expand_multiplier_one_is_noop():
    x = torch.randn(1, 4, 8, 8)
    assert CFG.expand_for_guidance(x, 1) is x


def test_expand_keeps_grad_state_semantics():
    """复制不改变 requires_grad（推理态下为 False，展开后仍是 False）。"""
    x = torch.randn(1, 4, 8, 8)
    assert CFG.expand_for_guidance(x, 2).requires_grad is False


# ══════════════════════════════════════════════════════════════════
# rescale_noise_cfg vs 上游
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rescale", [0.0, 0.3, 0.7])
def test_rescale_matches_upstream_bitwise(rescale, upstream):
    """与上游**逐位相等**（对照值来自干净子进程，见上方说明）。

    断言用 `torch.equal` 而不是 `allclose`：1e-7 的差异说明"这不是同一套算术"，
    而"重实现"的全部资格就建立在"同一套算术"上。
    """
    torch.manual_seed(0)
    noise_cfg = torch.randn(2, 4, 16, 16)
    noise_text = torch.randn(2, 4, 16, 16)
    ours = CFG.rescale_noise_cfg(noise_cfg, noise_text, guidance_rescale=rescale)

    theirs = torch.tensor(upstream["values"][str(rescale)]).reshape(ours.shape)
    assert torch.equal(ours, theirs), "与上游不是逐位相等 ⇒ 不算重实现"


def test_rescale_survives_constant_input(upstream):
    """**故意偏离上游**：`std_cfg == 0` 时上游除以 0 得 nan，我们 clamp 到 eps。

    常数噪声预测在真实推理里不出现（那意味着整步预测恒定），但一旦出现，
    上游那条路会让**整张图变 nan**（全黑或全噪点），且不报错。
    我们选择"退化成不 rescale"而不是"污染整图"，并把这个差异写在这里。
    """
    const = torch.full((1, 4, 8, 8), 0.5)
    ours = CFG.rescale_noise_cfg(const, const, guidance_rescale=0.7)
    assert torch.isfinite(ours).all(), "常数输入不该产生 nan/inf"
    assert torch.allclose(ours, const)

    # 上游在同输入下**确实**会 nan（对照值同样来自子进程）——
    # 这条断言的作用是证明"偏离是必要的"，而不是给自己找台阶
    assert upstream["const_finite"] is False, \
        "上游在常数输入下没有产生 nan ⇒ 我们的偏离失去依据，应改回与上游一致"


def test_rescale_is_not_applied_when_zero():
    torch.manual_seed(1)
    noise_cfg = torch.randn(1, 4, 8, 8)
    noise_text = torch.randn(1, 4, 8, 8)
    out = CFG.rescale_noise_cfg(noise_cfg, noise_text, guidance_rescale=0.0)
    assert torch.allclose(out, noise_cfg), "rescale=0 时结果必须等于原始噪声"


def test_rescale_magnitude_direction():
    """rescale 在 (0,1) 之间应落在「原值」与「重标定值」之间（不是外推）。"""
    torch.manual_seed(2)
    noise_cfg = torch.randn(1, 4, 8, 8) * 3.0
    noise_text = torch.randn(1, 4, 8, 8)
    full = CFG.rescale_noise_cfg(noise_cfg, noise_text, guidance_rescale=1.0)
    half = CFG.rescale_noise_cfg(noise_cfg, noise_text, guidance_rescale=0.5)
    assert torch.allclose(half, 0.5 * full + 0.5 * noise_cfg, atol=1e-6)
