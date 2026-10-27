# -*- coding: utf-8 -*-
"""守卫 ⑱：内核三条硬线 + 契约完整性（P2 · 2026-10-28）。

守什么
======
`docs/design/推理引擎架构设计.md` §3 的三条硬线，逐条变成一个可执行判据：

| 硬线 | 大意 | 本条守卫怎么查 |
|---|---|---|
| **H1** | `loop.py` 不知道自己在跑哪个族 | `loop.py` 的**代码**里不许出现族名 / 组件名 / 条件张量名 |
| **H2** | 适配器不许自己写 for-step | `adapters/` 与内核其余文件的代码里不许出现 `enumerate(timesteps)` 形态 |
| **H3** | `engine.py` 之外，内核层顶层不 import torch | AST 取模块级 import；其余文件只许在函数内 import |

为什么这些必须是守卫而不是注释：三条硬线全是"**改坏了也不会报错**"的那类规矩。
`loop.py` 里写一句 `if family == "sdxl"` 照样跑得通、图也出得来，
只是 C3（上游可替换）当场失效 —— 而失效这件事，只有下次换上游时才会痛。

## 另外两条（不是硬线，但同属"填了才准入"）

④ **caps 自洽 + parity 基线填完**：新族准入的最低门槛（规范 §5.2）。
   把适配器真 import 进来问一遍 —— 静态扫字面量会漏掉"从变量算出来的 caps"。
⑤ **`verified` 必须有证据**：声明 `VERIFIED` 而 `kernel_evidence.json` 里没有
   `passed=true` 的记录 = 自己给自己发证书。这条是验收协议里最容易被"顺手改一下"
   绕过的一条，所以由机器盯着。

反例自证：`--selfcheck` 用内存里的假源码造五个反例（H1 / H2 / H3 / caps / 证据），
不动盘上任何文件。只证一条等于半截假绿。
"""
from __future__ import annotations

import argparse
import ast

import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KERNEL_DIR = os.path.join("app", "core", "neural", "kernel")
LOOP_FILE = os.path.join(KERNEL_DIR, "loop.py")
ADAPTER_DIR = os.path.join(KERNEL_DIR, "adapters")
ENGINE_FILE = os.path.join(KERNEL_DIR, "engine.py")
EVIDENCE_FILE = os.path.join("docs", "knowledge", "kernel_evidence.json")

#: H1：`loop.py` 代码里不许出现的标识符（族名 / 组件名 / 条件张量名）
LOOP_FORBIDDEN = (
    "sd15", "sdxl", "svd", "wan",
    "unet", "vae", "transformer", "text_encoder", "scheduler",
    "prompt_embeds", "pooled", "add_time_ids", "vae_scale_factor",
)

#: H2：步进循环的"指纹"形态（出现在 `loop.py` 之外即为越界）
STEP_LOOP_HINT = "enumerate"


def _read(rel: str) -> str:
    try:
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _idents_and_strings(text: str) -> set:
    """源码里出现过的**标识符 + 字符串字面量里的词**（docstring 除外）。

    为什么不是"全文扫字面量"，也不是"只看代码 token"：

      · 只看代码 token（把字符串整类丢掉）会漏掉 `if family == "sdxl"` ——
        族名在代码里**几乎总是**写成字符串，这等于把 H1 放空。
      · 全文扫又会撞上 docstring：`loop.py` 的说明里就写着 "SD1.5 / SDXL"，
        一进来就假红，最后必然被 `# noqa` 掉。

    所以按 AST 取：Name / Attribute / 参数名 / 关键字参数名 / 非 docstring 的字符串
    字面量，全部拆词小写。docstring 是 `Module/ClassDef/FunctionDef` 体里的第一个
    字符串表达式，按位置排除。
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # 解析失败就退回全文词表：宁可假红让人来看，也不要静默放行
        import re

        return {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text)}

    import re

    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                            ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))

    words = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            words.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            words.add(node.attr.lower())
        elif isinstance(node, ast.arg):
            words.add(node.arg.lower())
        elif isinstance(node, ast.keyword) and node.arg:
            words.add(node.arg.lower())
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            words.add(node.name.lower())
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in doc_ids):
            words.update(w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*",
                                                       node.value))
    return words


def _top_level_imports(text: str) -> list:
    """模块级 `import` / `from ... import` 的目标名（不含函数内的）。"""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    names = []
    for node in tree.body:                     # 只看模块体，不进函数/类
        if isinstance(node, ast.Import):
            names.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split(".")[0])
    return names


def _kernel_files() -> list:
    """内核层所有 .py（相对路径，已排序）。"""
    out = []
    for base, _dirs, files in os.walk(os.path.join(ROOT, KERNEL_DIR)):
        for name in sorted(files):
            if name.endswith(".py"):
                out.append(os.path.relpath(os.path.join(base, name), ROOT))
    return sorted(out)


def _adapter_files() -> list:
    return [f for f in _kernel_files() if os.sep + "adapters" + os.sep in f]


def _check_sources(sources: dict) -> list:
    """核心判据。`sources` = {相对路径: 源码}，便于自证时注入假源码。"""
    bad = []

    # ── H1：loop.py 代码里没有族名 / 组件名 ──────────────────────
    loop_src = sources.get(LOOP_FILE, "")
    if not loop_src:
        bad.append("H1：找不到 %s" % LOOP_FILE)
    else:
        words = _idents_and_strings(loop_src)
        for word in LOOP_FORBIDDEN:
            if word in words:
                bad.append("H1：loop.py 代码里出现 %r ⇒ 循环知道了自己跑的是哪个族/哪个组件"
                           "（C3 当场失效）" % word)

    # ── H2：步进循环只能出现在 loop.py ──────────────────────────
    for rel, src in sorted(sources.items()):
        if rel == LOOP_FILE:
            continue
        words = _idents_and_strings(src)
        # 两个条件同时成立才算越界：单独用 enumerate 很常见（遍历文件/配置），
        # 只有"遍历时间轴"才是自写步进循环。
        if STEP_LOOP_HINT in words and "timesteps" in words:
            bad.append("H2：%s 里同时出现 enumerate 与 timesteps ⇒ "
                       "像是一处自写的步进循环（只允许在 loop.py）" % rel)

    # ── H3：engine.py 之外，模块级不 import torch ───────────────
    for rel, src in sorted(sources.items()):
        if rel == ENGINE_FILE:
            continue
        for name in _top_level_imports(src):
            if name == "torch":
                bad.append("H3：%s 顶层 import torch ⇒ 契约/守卫/诊断被迫依赖 2GB 依赖"
                           "（只允许 %s 顶层 import）" % (rel, ENGINE_FILE))
                break

    return bad


def _check_runtime_contracts(evidence_override=None) -> list:
    """④⑤：真 import 适配器问 caps / parity / verified 证据。

    `evidence_override` 只给自证用：不给时读盘上的证据台账。
    """
    bad = []
    try:
        from app.core.neural.kernel import engine as K
        from app.core.neural.kernel.contracts import VERIFIED, baseline_for
    except Exception as e:                    # pragma: no cover
        return ["无法 import 内核（%s: %s）" % (type(e).__name__, e)]

    evidence = evidence_override
    if evidence is None:
        evidence = {}
        raw = _read(EVIDENCE_FILE)
        if raw:
            try:
                evidence = json.loads(raw).get("families", {})
            except (ValueError, AttributeError):
                bad.append("⑤：%s 不是合法 JSON，证据无从核对" % EVIDENCE_FILE)

    for fam in K.supported_families():
        ad = K.adapter_for(fam)
        for v in ad.caps.violations():
            bad.append("④：族 %s 的 caps 不自洽 —— %s" % (fam, v))
        # 基线按**族的潜变量阶数**取：视频族（rank=5）的条件/引导/解码语义与图像族
        # 没有重叠，用图像清单校验它等于要求适配器填一堆无意义的键，
        # 最后必然是"为了过守卫填个 True" —— 那比没有守卫更糟。
        baseline = baseline_for(ad.caps)
        missing = ad.parity.missing(baseline)
        if missing:
            bad.append("④：族 %s 的 parity 漏填 %s（新族准入必须先填完，规范 §5.2）"
                       % (fam, ", ".join(missing)))
        if ad.caps.verified == VERIFIED:
            rec = evidence.get(fam) or {}
            if not rec.get("passed"):
                bad.append("⑤：族 %s 声明 verified 但 %s 里没有 passed=true 的验收记录 ⇒ "
                           "自己给自己发证书" % (fam, EVIDENCE_FILE))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="内核三条硬线 + 契约完整性守卫")
    ap.add_argument("--selfcheck", action="store_true",
                    help="注入假源码/假证据，验证每条判据真会红")
    args = ap.parse_args()

    files = _kernel_files()
    sources = {rel: _read(rel) for rel in files}

    print("内核契约守卫：")
    print("  · 扫描 %d 个内核文件（H1/H2/H3）" % len(sources))
    try:
        from app.core.neural.kernel import engine as K

        print("  · 内置族 %s" % (K.supported_families(),))
        for fam in K.supported_families():
            ad = K.adapter_for(fam)
            print("    - %-6s verified=%-10s parity=%d 项  %s"
                  % (fam, ad.caps.verified, len(ad.parity.fields),
                     "caps 自洽" if not ad.caps.violations() else "caps 异常"))
    except Exception as e:
        print("  · ⚠ 无法 import 内核：%s" % e)

    bad = _check_sources(sources) + _check_runtime_contracts()

    if args.selfcheck:
        ok = True

        def _case(label, got, needle):
            nonlocal ok
            hit = [g for g in got if needle in g]
            if hit:
                print("  ✓ %s → %s" % (label, hit[0][:90]))
            else:
                print("  ✗ %s → 没报（该判据是摆设）" % label)
                ok = False

        # ① H1：往 loop.py 的代码里塞一个族名
        leak = dict(sources)
        leak[LOOP_FILE] = (sources.get(LOOP_FILE, "")
                           + "\n\ndef _leak(family):\n    return family == 'sdxl'\n")
        _case("H1 族名泄漏", _check_sources(leak), "H1")

        # ② H2：往一个适配器里塞自写步进循环
        ad_files = _adapter_files()
        if ad_files:
            leak2 = dict(sources)
            leak2[ad_files[-1]] = (sources.get(ad_files[-1], "")
                                   + "\n\ndef _loop(self, timesteps):\n"
                                     "    for i, t in enumerate(timesteps):\n"
                                     "        return i, t\n")
            _case("H2 自写步进", _check_sources(leak2), "H2")
        else:
            print("  ✗ H2 → 找不到适配器文件，无法自证")
            ok = False

        # ③ H3：把 torch 提到模块级
        leak3 = dict(sources)
        target = [f for f in sources if f != ENGINE_FILE and f.endswith("latents.py")]
        if target:
            leak3[target[0]] = "import torch\n" + sources[target[0]]
            _case("H3 顶层 import torch", _check_sources(leak3), "H3")
        else:
            print("  ✗ H3 → 找不到可注入的文件")
            ok = False

        # ④ caps 不自洽：临时改一个 adapter 的 caps
        try:
            from app.core.neural.kernel import engine as K

            orig = K._ADAPTERS.get("sd15")
            if orig is not None:
                K._ADAPTERS["sd15"] = lambda: _BrokenCapsAdapter()
                got = _check_runtime_contracts()
                K._ADAPTERS["sd15"] = orig
                _case("④ caps 不自洽", got, "④")
            else:
                print("  ✗ ④ → 没有 sd15 适配器")
                ok = False
        except Exception as e:
            print("  ✗ ④ 自证失败：%s" % e)
            ok = False

        # ⑤ verified 无证据：把 sd15 标成 verified，但证据台账**强制为空**
        try:
            from app.core.neural.kernel import engine as K

            orig_cls = K._ADAPTERS.get("sd15")
            K._ADAPTERS["sd15"] = lambda: _VerifiedNoEvidenceAdapter()
            # 证据强制为空：盘上此时可能真有一条 sd15 通过记录，
            # 用真实台账自证会"因为恰好有证据而不报"，那就不是自证。
            got = _check_runtime_contracts(evidence_override={})
            if orig_cls is not None:
                K._ADAPTERS["sd15"] = orig_cls
            _case("⑤ verified 无证据", got, "⑤")
        except Exception as e:
            print("  ✗ ⑤ 自证失败：%s" % e)
            ok = False

        # ⑥ 视频族基线按阶数分派：给一个 rank=5 但只填了**图像**清单的适配器
        #    ⇒ 必须报"漏填 noise_aug_before_vae"等视频专属项。
        #    这条防的是"基线分派写错、视频族被按图像清单校验"的假绿。
        try:
            from app.core.neural.kernel import engine as K

            orig_cls = K._ADAPTERS.get("sd15")
            K._ADAPTERS["sd15"] = lambda: _VideoCapsImageParityAdapter()
            got = _check_runtime_contracts(evidence_override={})
            if orig_cls is not None:
                K._ADAPTERS["sd15"] = orig_cls
            _case("⑥ 视频族漏填视频基线", got, "noise_aug_before_vae")
        except Exception as e:
            print("  ✗ ⑥ 自证失败：%s" % e)
            ok = False

        if not ok:
            print("  ✗ 自证未通过 —— 有判据是摆设")
            return 1
        print("  ✓ 六条判据全部真会红（非摆设）")

    if bad:
        print("\n✗ 内核契约守卫未通过：")
        for b in bad:
            print("  - %s" % b)
        return 1
    print("\n✓ 内核契约守卫通过（H1/H2/H3 + caps + parity + 证据）")
    return 0


class _BrokenCapsAdapter:
    """自证专用：caps 跨字段不自洽（cat 但乘数 1）。"""

    def __init__(self) -> None:
        from app.core.neural.kernel.adapters.sd15 import SD15Adapter
        from app.core.neural.kernel.contracts import AdapterCaps

        base = SD15Adapter()
        base.caps = AdapterCaps(cfg_mode="cat", cfg_batch_multiplier=1)
        self.family = "sd15"
        self.caps = base.caps
        self.parity = base.parity


class _VerifiedNoEvidenceAdapter:
    """自证专用：声明 verified，但证据台账里没有这一族。"""

    def __init__(self) -> None:
        from app.core.neural.kernel.adapters.sd15 import SD15Adapter
        from app.core.neural.kernel.contracts import VERIFIED

        base = SD15Adapter()
        caps = base.caps
        # dataclass 是 frozen，用 replace 造一个新的
        import dataclasses

        self.family = "sd15"
        self.caps = dataclasses.replace(caps, verified=VERIFIED)
        self.parity = base.parity


class _VideoCapsImageParityAdapter:
    """自证专用：caps 是视频族（rank=5），parity 却只填了图像清单。

    基线分派若写成"永远用 BASE_PARITY_FIELDS"，这个适配器会被判绿 ——
    而它的 `noise_aug_before_vae`（随机数消耗顺序）根本没验过。
    这条反例专门盯住那种假绿。
    """

    def __init__(self) -> None:
        import dataclasses

        from app.core.neural.kernel.adapters.sd15 import SD15Adapter
        from app.core.neural.kernel.contracts import AdapterCaps

        base = SD15Adapter()
        self.family = "sd15"
        self.caps = dataclasses.replace(
            AdapterCaps(cfg_mode="none", cfg_batch_multiplier=1),
            latent_rank=5, vae_decode="chunked_temporal")
        self.parity = base.parity        # 只有图像族那些键


if __name__ == "__main__":
    sys.exit(main())
