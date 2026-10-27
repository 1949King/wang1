# -*- coding: utf-8 -*-
"""守卫 ⑰：推理栈钉版一致性（P0 · 2026-10-28）。

守什么
======
架构文档 §9 第 1 条原话：「`requirements.txt` 没有 diffusers / torch ⇒
**"钉版"只是口头，换机重装必漂**」。

这道守卫把"钉版"从口头变成可执行的事，查三件：

1. **必须钉的包真的在文件里，且用 `==` 精确版本**（不用 `>=` 糊过去）。
2. **两个清单不许各自为政**：`requirements.txt` 与 `app/requirements.txt`
   （文件自称"与 app 对齐"）里的推理栈 pin 必须逐条相等 ——
   否则"按哪个装"就成了运气。
3. **装着的版本 == 钉的版本**（本机有装才查；CI 无 GPU 自然跳过）。
   不一致就红：这意味着**文档说 A、实际跑 B**，正是这条缺口的原始病症。
   torch 家族一并查 —— 它的 pin 写在文件头的 CUDA 安装命令里（不在 `-r` 行），
   走的取值路径不同，故单独露一条反例证明这条路径也真会红。
   合法的升级路径是「升级 → 重跑验收 → 改 pin 一起提交」，不是静默漂移。

反例自证：`--selfcheck` 造四个反例（缺 pin / 两清单打架 / 推理栈漂移 / torch 漂移），
全部在内存注入，不动盘上任何文件。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

#: 必须钉的推理栈（pip 名 → import 名）。
#: torch 单独列：它必须走 CUDA 源，故只要求"在文件里以 == 出现"，见 REQUIRED_CUDA_PINS。
REQUIRED_PINS = {
    "diffusers": "diffusers",
    "accelerate": "accelerate",
    "safetensors": "safetensors",
    "transformers": "transformers",
    "diffsynth-engine": "diffsynth_engine",
}
#: torch 家族：必须钉，但由文件头的 CUDA 命令钉（不放进 pip -r 行，避免被 CPU 源覆盖）
REQUIRED_CUDA_PINS = ("torch", "torchvision", "torchaudio")

FILES = ("requirements.txt", os.path.join("app", "requirements.txt"))

_PIN_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([0-9][^\s#]*)")


def _cuda_pins(rel: str) -> dict:
    """从文件**正文任意位置**抠 torch 家族的 pin（它们写在 CUDA 安装命令里，
    不在 `pip install -r` 行，所以 `_parse` 抓不到）。

    用 lookahead 而非普通搜索，防止 `torch` 命中 `torchvision==...` 的前缀。
    """
    out = {}
    try:
        with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return out
    for name in REQUIRED_CUDA_PINS:
        m = re.search(re.escape(name) + r"\s*==\s*([0-9][^\s#^\\]*)", text)
        if m:
            out[name] = m.group(1).rstrip(",;")
    return out


def _parse(rel: str) -> dict:
    """解析出 {pip名: 版本}。只认 `==` 精确钉版；`>=` 一律不算。"""
    path = os.path.join(ROOT, rel)
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.lstrip().startswith("#"):
                    continue
                m = _PIN_RE.match(line)
                if m:
                    out[m.group(1).lower()] = m.group(2)
    except FileNotFoundError:
        out["__missing__"] = ""
    return out


def _installed(import_name: str):
    """已装版本；没装返回 None（只读元数据，不 import 重库）。"""
    try:
        import importlib.metadata as md
    except Exception:
        return None
    for name in (import_name, import_name.replace("_", "-")):
        try:
            return md.version(name)
        except Exception:
            continue
    return None


def _check(pins=None, files=FILES) -> list:
    bad = []
    parsed = {rel: (_parse(rel) if pins is None else pins.get(rel, {})) for rel in files}

    for rel, table in parsed.items():
        if "__missing__" in table:
            bad.append("%s 不存在（钉版无从谈起）" % rel)
            continue
        for pip_name in REQUIRED_PINS:
            if pip_name.lower() not in table:
                bad.append("%s 缺少 `%s==x.y.z` 精确钉版（>= 不算钉版）" % (rel, pip_name))
        # torch 家族：允许出现在 CUDA 注释命令里，但必须带 ==
        text = ""
        try:
            with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            pass
        for name in REQUIRED_CUDA_PINS:
            if not re.search(re.escape(name) + r"\s*==\s*[0-9]", text):
                bad.append("%s 里 %s 没有精确版本（CUDA 安装命令须写 %s==x.y.z）"
                           % (rel, name, name))

    # ② 两个清单不许各自为政
    a, b = (parsed.get(FILES[0], {}), parsed.get(FILES[1], {}))
    for pip_name in REQUIRED_PINS:
        key = pip_name.lower()
        if key in a and key in b and a[key] != b[key]:
            bad.append("两份清单打架：%s = %s（根）vs %s（app）" % (pip_name, a[key], b[key]))

    # ③ 装着的 == 钉的（本机有才查）
    #    推理栈 + torch 家族一起查：torch 恰恰是最容易漂的那一行，
    #    只查文件不查实机，等于把「文档说 A、机器跑 B」留在外面。
    targets = dict(REQUIRED_PINS)
    for name in REQUIRED_CUDA_PINS:
        targets[name] = name
    cuda_a = _cuda_pins(FILES[0])
    cuda_b = _cuda_pins(FILES[1])

    for pip_name, _import_name in targets.items():
        pinned = a.get(pip_name.lower()) or b.get(pip_name.lower())
        if not pinned and pip_name in REQUIRED_CUDA_PINS:
            pinned = cuda_a.get(pip_name) or cuda_b.get(pip_name)
        if not pinned:
            continue
        got = _installed(pip_name)
        if got is None:
            continue                      # 没装 ⇒ 不归这道守卫管（装不装是 setup 的事）
        if got.split("+")[0] != pinned.split("+")[0]:
            bad.append("版本漂移：%s 钉的是 %s，实际装着 %s ⇒ 文档与实际不一致"
                       "（升级请连同 pin 一起改并重跑验收）" % (pip_name, pinned, got))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="推理栈钉版一致性守卫")
    ap.add_argument("--selfcheck", action="store_true",
                    help="注入假的已装版本，验证不一致分支真会红")
    args = ap.parse_args()

    print("推理栈钉版：")
    for rel in FILES:
        table = _parse(rel)
        picked = {k: v for k, v in table.items() if k in
                  {p.lower() for p in REQUIRED_PINS}}
        picked.update(_cuda_pins(rel))
        print("  · %-24s %s" % (rel, picked or "（无推理栈 pin）"))

    if args.selfcheck:
        # 三条判据各造一个反例，全部在内存里注入，**不动盘上任何文件**。
        # 只证一条也算半截假绿：别人把另外两条改坏了，自证不会察觉。
        base = _parse(FILES[0])
        base_app = _parse(FILES[1])

        def _case(label, bad, needle):
            hit = [b for b in bad if needle in b]
            if hit:
                print("  ✓ %s → %s" % (label, hit[0]))
                return True
            print("  ✗ %s → 没报（该判据是摆设）" % label)
            return False

        ok = True

        # ① 缺 pin：从根清单里抠掉 diffusers
        cut = {k: v for k, v in base.items() if k != "diffusers"}
        ok &= _case("缺 pin", _check(pins={FILES[0]: cut, FILES[1]: base_app}),
                    "缺少 `diffusers")

        # ② 两份清单打架：app 侧 diffusers 写成别的版本
        clash = dict(base_app, diffusers="0.99.0")
        ok &= _case("两清单打架", _check(pins={FILES[0]: base, FILES[1]: clash}),
                    "两份清单打架")

        # ③ 版本漂移（推理栈）：打桩已装版本
        orig = _installed
        try:
            globals()["_installed"] = lambda name: (
                "0.99.0" if str(name).lower() == "diffusers" else orig(name))
            bad = _check(pins={FILES[0]: base, FILES[1]: base_app})
        finally:
            globals()["_installed"] = orig
        ok &= _case("版本漂移·推理栈", bad, "diffusers 钉的是")

        # ④ 版本漂移（torch 家族）：它走 `_cuda_pins` 另一条取值路径，必须单独证一次，
        #    否则这条路径坏了没人知道（torch 恰是最容易漂的一行）。
        try:
            globals()["_installed"] = lambda name: (
                "9.9.9" if str(name).lower() == "torch" else orig(name))
            bad = _check(pins={FILES[0]: base, FILES[1]: base_app})
        finally:
            globals()["_installed"] = orig
        ok &= _case("版本漂移·torch", bad, "torch 钉的是")

        print("✓ 自证通过：三条判据 + torch 取值路径都会红"
              if ok else "✗ 自证失败：有判据不会红 ⇒ 守卫是摆设")
        return 0 if ok else 1

    bad = _check()
    if bad:
        print("✗ 钉版不一致 %d 条：" % len(bad))
        for b in bad:
            print("   - %s" % b)
        return 1
    print("OK 钉版一致（文件间一致 + 与实际安装一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
