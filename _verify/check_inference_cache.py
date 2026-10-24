# -*- coding: utf-8 -*-
"""P0 推理缓存三件套（inference_cache.py）结构不变量自包含验证。

为什么不直接用 app/tests/test_inference_cache.py？
    沙箱环境里 pytest 启动链会调用 wmic.exe 做平台探测，被安全策略拦截。
    本脚本用标准库 + AST 覆盖**同一批不变量**的静态侧，可在受限环境快速自检。

与 pytest 套件的分工（两者同步维护，勿重叠）：
    · app/tests/test_inference_cache.py（.venv312 + torch）覆盖**行为**：
      真假 UNet 前向、短路/还原、低秩往返、LRU/池字节账、门控矩阵、引擎接线。
    · 本脚本覆盖**不变量**：公开件在册、默认关纪律（组件不许自开）、
      make_cache_key 六字段敏感性、卸载序列三处收口 + 单一定义、
      generate 的 attach↔finally-detach 成对、行数棘轮。
    每个 AST 检查都配**反例自检**（构造必然违规的最小源码，检查器必须报错）——
    防「永远绿的摆设」（2026-10-19 dual-repo 大小写不匹配但退出码 0 的教训）。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_inference_cache.py
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IC_PATH = os.path.join(ROOT, "app", "core", "neural", "inference_cache.py")
DI_PATH = os.path.join(ROOT, "app", "core", "neural", "diffusers_image.py")
VG_PATH = os.path.join(ROOT, "app", "core", "neural", "video_gen.py")
VPC_PATH = os.path.join(ROOT, "app", "core", "local_video_pipe_cache.py")
TEST_PATH = os.path.join(ROOT, "app", "tests", "test_inference_cache.py")

# 行数棘轮（只许涨不许跌；大涨时在这里登记新基线）
IC_MIN_LINES = 1080
TEST_MIN_LINES = 778

# 五组件公开件（类/函数/常量）——少任何一个 = P0 交付物残缺
REQUIRED_PUBLIC = (
    "StepFeatureCache", "LowRankFeatureCache", "EncoderOutputCache",
    "VramBlockPool", "BlockHandle",
    "cache_gate", "make_cache_key", "encoder_cache", "default_pool",
    "release_vram_sequence", "encode_prompt_embeds", "pipe_call_with_embeds",
    "STEP_CACHE_ARCHS", "STEP_CACHE_PRESETS", "ENCODER_CACHE_ARCHS",
)

# 卸载序列三处收口（2026-10-24 实测教训的单一真源消费方）
RELEASE_WIRING_FILES = (VPC_PATH, DI_PATH, VG_PATH)

# generate 的 attach↔finally-detach 成对（两引擎）
GENERATE_PAIR_FILES = (DI_PATH, VG_PATH)

# 组件环境变量全集（门控矩阵用；跑完还原）
ENV_KEYS = ("SHIGUANG_STEP_CACHE", "SHIGUANG_ENCODER_CACHE",
            "SHIGUANG_STEP_CACHE_INTERVAL", "SHIGUANG_STEP_CACHE_BRANCH",
            "SHIGUANG_STEP_CACHE_LOWRANK", "SHIGUANG_CACHE_POOL")

failures: list = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def _parse(path: str) -> ast.AST:
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


# ══════════════════════════════════════════════════════════════════
# 检查器（全部吃 AST，返回问题列表——真实文件期望 0，反例期望 ≥1）
# ══════════════════════════════════════════════════════════════════

def _problems_public_api(tree: ast.AST) -> list:
    """顶层公开件在册。"""
    have = set()
    for node in tree.body:                      # type: ignore[attr-defined]
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            have.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    have.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            have.add(node.target.id)      # 带注解的模块常量（frozenset: frozenset = ...）
    return ["缺少公开件 %s" % n for n in REQUIRED_PUBLIC if n not in have]


def _problems_no_env_write(tree: ast.AST) -> list:
    """组件不许自己开自己：全模块零 os.environ 写入（只读）。"""
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if (isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Attribute)
                        and t.value.attr == "environ"):
                    bad.append("os.environ 写入（第 %d 行）" % node.lineno)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
                and node.func.attr in ("setdefault", "putenv")):
            bad.append("os.environ.%s（第 %d 行）" % (node.func.attr, node.lineno))
    return bad


def _problems_release_wiring(tree: ast.AST) -> list:
    """import release_vram_sequence 且真的调用（只 import 不调 = 死接线）。"""
    imported = any(
        isinstance(n, ast.ImportFrom) and n.module
        and n.module.endswith("inference_cache")
        and any(a.name == "release_vram_sequence" for a in n.names)
        for n in ast.walk(tree))
    called = any(
        isinstance(n, ast.Call)
        and ((isinstance(n.func, ast.Name) and n.func.id == "release_vram_sequence")
             or (isinstance(n.func, ast.Attribute)
                 and n.func.attr == "release_vram_sequence"))
        for n in ast.walk(tree))
    problems = []
    if not imported:
        problems.append("未 import release_vram_sequence")
    if not called:
        problems.append("import 了但从未调用（死接线）")
    return problems


def _problems_generate_pair(tree: ast.AST) -> list:
    """generate 内 attach 调用 ↔ finally 内 detach 调用成对，且变量名对应。

    形态（两引擎一致，2026-10-25 实测）：
        step_cache = self._attach_step_cache(...)   # try 之前
        try: ... finally: self._detach_step_cache(step_cache)
    detach 必须在 finalbody——try 体抛异常时也要还原 forward
    （漏还原 = 下次 generate 双倍短路）。
    """
    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "generate"):
            continue
        attach_var = None
        for n in ast.walk(node):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                    and isinstance(n.value.func, ast.Attribute)
                    and n.value.func.attr.endswith("attach_step_cache")
                    and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)):
                attach_var = n.targets[0].id
        if attach_var is None:
            problems.append("generate 无 attach_step_cache 调用（变量未捕获）")
            continue
        ok_pair = False
        for n in ast.walk(node):
            if not isinstance(n, ast.Try):
                continue
            for stmt in n.finalbody:
                for c in ast.walk(stmt):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                            and c.func.attr == "_detach_step_cache"
                            and c.args and isinstance(c.args[0], ast.Name)
                            and c.args[0].id == attach_var):
                        ok_pair = True
        if not ok_pair:
            problems.append(
                "generate 有 attach（%s）但 finally 里没有对应的 _detach_step_cache"
                % attach_var)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "generate"
               for n in ast.walk(tree)):
        problems.append("文件里没有 generate 函数（配对检查空转）")
    return problems


def _self_test_checkers() -> None:
    """反例自检：每个检查器喂必然违规的最小源码，必须报错。

    防摆设——2026-10-19 的教训：dual-repo 的 filter 大小写不匹配，
    pnpm 退出码 0 ⇒ 门禁长期假绿。检查器本身必须是可失败的。
    """
    good_pair = (
        "def generate(self):\n"
        "    step_cache = self._attach_step_cache('svd', 'fast')\n"
        "    try:\n"
        "        return self._pipe()\n"
        "    finally:\n"
        "        self._detach_step_cache(step_cache)\n"
    )
    check(not _problems_generate_pair(ast.parse(good_pair)),
          "自检失败：合规 generate 被判违规（检查器过严）")
    for label, src in (
        ("attach 后无 finally detach",
         "def generate(self):\n    sc = self._attach_step_cache('svd', 'fast')\n"
         "    try:\n        return self._pipe()\n    except Exception:\n        pass\n"),
        ("detach 在 try 体而非 finally",
         "def generate(self):\n    sc = self._attach_step_cache('svd', 'fast')\n"
         "    try:\n        self._detach_step_cache(sc)\n        return 1\n"
         "    finally:\n        pass\n"),
        ("detach 变量与 attach 不对应",
         "def generate(self):\n    sc = self._attach_step_cache('svd', 'fast')\n"
         "    try:\n        return 1\n    finally:\n        self._detach_step_cache(other)\n"),
    ):
        probs = _problems_generate_pair(ast.parse(src))
        check(bool(probs), "自检失败：反例「%s」未被配对检查器抓获" % label)

    wired = ("from app.core.neural.inference_cache import release_vram_sequence\n"
             "def f():\n    release_vram_sequence()\n")
    check(not _problems_release_wiring(ast.parse(wired)),
          "自检失败：合规接线被判违规")
    for label, src in (
        ("只 import 不调用", "from app.core.neural.inference_cache import release_vram_sequence\n"),
        ("只调用不 import", "def f():\n    release_vram_sequence()\n"),
    ):
        probs = _problems_release_wiring(ast.parse(src))
        check(bool(probs), "自检失败：反例「%s」未被接线检查器抓获" % label)

    clean = "import os\nX = 1\n"
    check(not _problems_no_env_write(ast.parse(clean)),
          "自检失败：无 env 写入的合规模块被判违规")
    for label, src in (
        ("下标赋值", "import os\nos.environ['SHIGUANG_STEP_CACHE'] = 'deepcache'\n"),
        ("setdefault", "import os\nos.environ.setdefault('SHIGUANG_STEP_CACHE', '1')\n"),
    ):
        probs = _problems_no_env_write(ast.parse(src))
        check(bool(probs), "自检失败：反例「%s」未被 env 写入检查器抓获" % label)

    full = "class StepFeatureCache:\n    pass\n" + "def cache_gate():\n    pass\n"
    check(_problems_public_api(ast.parse(full)),
          "自检失败：缺公开件的反例未被公开件检查器抓获")


# ══════════════════════════════════════════════════════════════════
# 模块加载（按路径，绕开 app/__init__ 的硬件探测链）
# ══════════════════════════════════════════════════════════════════

_spec = importlib.util.spec_from_file_location("_ic_guard", IC_PATH)
ic = importlib.util.module_from_spec(_spec)
sys.modules["_ic_guard"] = ic
_spec.loader.exec_module(ic)                      # type: ignore[union-attr]


def _gate(component: str, arch: str, preset: str, env: dict) -> dict:
    """在受控 env 下调 cache_gate（跑完无条件还原，防污染同进程后续检查）。"""
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    try:
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = v
        return ic.cache_gate(arch=arch, preset=preset, component=component)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── [1] 门控矩阵：步缓存（默认关是硬纪律）─────────────────────────
STEP_ARCHS = ("sd15", "sdxl", "svd", "wan", "")
STEP_PRESETS = ("fast", "high", "preview", "balanced", "final", "best", "")
for envv in ("", "off", "0", "none", "garbage", "DEEPCACHE!"):
    for a in STEP_ARCHS:
        for p in STEP_PRESETS:
            g = _gate("step_cache", a, p, {"SHIGUANG_STEP_CACHE": envv})
            check(not g["ok"],
                  "步缓存 env=%r arch=%r preset=%r 应保持关闭" % (envv, a, p))
            check(bool(g["reasons"]),
                  "步缓存关闭时 reasons 不得为空（决策可见）：env=%r arch=%r" % (envv, a))
for envv in ("deepcache", "auto", "DeepCache"):
    for a in STEP_ARCHS:
        for p in STEP_PRESETS:
            g = _gate("step_cache", a, p, {"SHIGUANG_STEP_CACHE": envv})
            want = a in ("sd15", "sdxl", "svd") and p in ("fast", "high", "preview")
            check(g["ok"] == want,
                  "步缓存 env=%r arch=%r preset=%r 应 %s" % (envv, a, p, "开" if want else "关"))
            if want:
                prm = g["params"]
                check(set(prm) == {"interval", "branch_id", "lowrank", "pool"},
                      "开启时 params 四键齐备：%s" % sorted(prm))
                check(2 <= prm["interval"] <= 20, "interval 越界：%r" % prm["interval"])
                check(0 <= prm["branch_id"] <= 8, "branch_id 越界：%r" % prm["branch_id"])
                check(prm["lowrank"] == 0.0, "lowrank 默认应为 0.0（不建低秩）：%r" % prm["lowrank"])
                check(prm["pool"] is False, "pool 默认应为 False")
                check(not g["reasons"] or "门控通过" in g["reasons"][-1],
                      "开启时 reasons 末条应为通过说明")
            else:
                check(bool(g["reasons"]), "关闭时 reasons 不得为空")
                check(g["params"] == {}, "关闭时 params 应为空")

# 参数夹紧
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_STEP_CACHE_INTERVAL": "7"})
check(g["params"]["interval"] == 7, "interval=7 应透传")
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_STEP_CACHE_INTERVAL": "1"})
check(g["params"]["interval"] == 2, "interval=1 应夹紧到 2")
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_STEP_CACHE_INTERVAL": "99"})
check(g["params"]["interval"] == 20, "interval=99 应夹紧到 20")
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_STEP_CACHE_INTERVAL": "abc"})
check(g["params"]["interval"] == 3, "interval 非数字应回落默认 3")
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_STEP_CACHE_LOWRANK": "0.25"})
check(abs(g["params"]["lowrank"] - 0.25) < 1e-9, "lowrank=0.25 应透传")
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_STEP_CACHE_LOWRANK": "0.01"})
check(abs(g["params"]["lowrank"] - 0.05) < 1e-9, "lowrank=0.01 应夹紧到 0.05")
g = _gate("step_cache", "sd15", "fast",
          {"SHIGUANG_STEP_CACHE": "deepcache", "SHIGUANG_CACHE_POOL": "1"})
check(g["params"]["pool"] is True, "pool=1 应开启")

# ── [2] 门控矩阵：编码器缓存 ──
for a in ("sd15", "sdxl", "svd", "wan", ""):
    for envv in ("", "0", "false"):
        g = _gate("encoder_cache", a, "fast", {"SHIGUANG_ENCODER_CACHE": envv})
        check(not g["ok"], "编码器缓存 env=%r arch=%r 应默认关" % (envv, a))
        check(bool(g["reasons"]), "编码器缓存关闭时 reasons 不得为空")
    for envv in ("1", "true", "on"):
        g = _gate("encoder_cache", a, "fast", {"SHIGUANG_ENCODER_CACHE": envv})
        want = a in ("sd15", "sdxl")
        check(g["ok"] == want,
              "编码器缓存 env=%r arch=%r 应 %s" % (envv, a, "开" if want else "关"))

# ── [3] make_cache_key 六字段敏感性（少一个字段 = 换 LoRA 出旧图级 bug）──
base_kw = dict(arch="sd15", model_id="m1", prompt="a cat",
               negative_prompt="blurry", lora_set="", max_length=77)
k0 = ic.make_cache_key(**base_kw)
check(len(k0) == 24 and all(c in "0123456789abcdef" for c in k0),
      "缓存键应为 24 位十六进制：%r" % k0)
check(ic.make_cache_key(**base_kw) == k0, "同输入键必须稳定")
for field, val in (("arch", "sdxl"), ("model_id", "m2"), ("prompt", "a dog"),
                   ("negative_prompt", "clean"), ("lora_set", "lora-x"),
                   ("max_length", 77 + 1)):
    kw = dict(base_kw)
    kw[field] = val
    check(ic.make_cache_key(**kw) != k0,
          "改动字段 %r 后键必须变化（否则换参出旧缓存）" % field)

# ── [4] 静态不变量（AST）────────────────────────────────────────
ic_tree = _parse(IC_PATH)
for p in _problems_public_api(ic_tree):
    failures.append("inference_cache.py: " + p)
for p in _problems_no_env_write(ic_tree):
    failures.append("inference_cache.py: " + p)

n_defs = 0
for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "app")):
    for fn in files:
        if not fn.endswith(".py"):
            continue
        fp = os.path.join(dirpath, fn)
        try:
            t = _parse(fp)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(t):
            if isinstance(node, ast.FunctionDef) and node.name == "release_vram_sequence":
                n_defs += 1
check(n_defs == 1,
      "release_vram_sequence 必须唯一定义于 inference_cache.py（实际 %d 处）" % n_defs)

for path in RELEASE_WIRING_FILES:
    label = os.path.basename(path)
    if not os.path.isfile(path):
        failures.append("收口文件缺失：%s" % label)
        continue
    for p in _problems_release_wiring(_parse(path)):
        failures.append("%s: %s" % (label, p))

for path in GENERATE_PAIR_FILES:
    label = os.path.basename(path)
    if not os.path.isfile(path):
        failures.append("配对文件缺失：%s" % label)
        continue
    for p in _problems_generate_pair(_parse(path)):
        failures.append("%s: %s" % (label, p))

# unload 清编码器缓存（diffusers_image）：键含 model_id，不清 = 卸载后驻留泄漏
di_tree = _parse(DI_PATH)
has_clear = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    and n.func.attr == "clear"
    and isinstance(n.func.value, ast.Call)
    and isinstance(n.func.value.func, ast.Name)
    and n.func.value.func.id == "encoder_cache"
    for n in ast.walk(di_tree))
check(has_clear, "diffusers_image 应含 encoder_cache().clear()（unload 清缓存）")

with open(IC_PATH, "r", encoding="utf-8") as f:
    ic_lines = sum(1 for _ in f)
check(ic_lines >= IC_MIN_LINES,
      "inference_cache.py 行数 %d < 基线 %d（大删减？）" % (ic_lines, IC_MIN_LINES))
check(os.path.isfile(TEST_PATH), "缺少 app/tests/test_inference_cache.py")
if os.path.isfile(TEST_PATH):
    with open(TEST_PATH, "r", encoding="utf-8") as f:
        t_lines = sum(1 for _ in f)
    check(t_lines >= TEST_MIN_LINES,
          "test_inference_cache.py 行数 %d < 基线 %d" % (t_lines, TEST_MIN_LINES))

# ── [5] 反例自检放最后（此时 failures 只应含真实文件的问题）────────
_before = len(failures)
_self_test_checkers()
check(len(failures) == _before,
      "反例自检自身产生了 %d 个新问题（检查器实现有 bug）" % (len(failures) - _before))

if failures:
    print("FAIL P0 推理缓存结构不变量有 %d 项不符：" % len(failures))
    for item in failures:
        print("  -", item)
    raise SystemExit(1)

print("OK P0 推理缓存三件套结构不变量全部通过")
print("  公开件 %d 项在册；卸载序列 %d 处收口；generate 配对 %d 处；"
      "行数 %d≥%d / 测试 %d≥%d"
      % (len(REQUIRED_PUBLIC), len(RELEASE_WIRING_FILES),
         len(GENERATE_PAIR_FILES), ic_lines, IC_MIN_LINES,
         t_lines if os.path.isfile(TEST_PATH) else 0, TEST_MIN_LINES))
