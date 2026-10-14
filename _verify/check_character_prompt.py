# -*- coding: utf-8 -*-
"""验证 build_character_prompt 的字段流向与向后兼容。

三个断言：
  1. visual 组新字段（气质倾向 / 标志性符号）确实进入提示词
  2. 老角色（只有旧字段）的输出不含新字段前缀 —— 向后兼容，不改变既有行为
  3. inner 组字段（核心欲望等）**不**进提示词 —— 防止画面描述被内在人格污染

实现说明：不 import canvas_bridge（其 import 链会触发硬件探测，且带副作用），
改为用 ast 抽出 build_character_prompt 单个函数节点后单独 exec。

用法（项目根执行）：
    .venv312\\Scripts\\python.exe _verify/check_character_prompt.py
"""

from __future__ import annotations

import ast
import os
import sys
import typing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "app", "core", "canvas_bridge.py")


# build_character_prompt 调用了同模块的 _face_params_to_text（及其依赖的
# _face_num / _face_hex_hue_name / _FACE_*_LABELS），单抽目标函数会 NameError；
# 按「目标函数 + 下划线助手闭包」一并抽取，仍不 import 整个模块（无副作用）。
_FACE_HELPERS = ("_face_params_to_text", "_face_num", "_face_hex_hue_name")


def _face_label_tables(tree: ast.AST) -> tuple:
    """抽出 _FACE_*_LABELS 之类的模块级常量表（build_character_prompt 的间接依赖）。"""
    return tuple(
        n.targets[0].id for n in tree.body
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id.startswith("_FACE_")
    )


def load_target_function():
    """静态抽取目标函数 + 其私有依赖，避免 import 整个模块带来的副作用。"""
    with open(BRIDGE, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    wanted = {"build_character_prompt", *_FACE_HELPERS, *_face_label_tables(tree)}
    picked = [n for n in tree.body
              if (isinstance(n, ast.FunctionDef) and n.name in wanted)
              or (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in wanted)]
    names = set()
    for n in picked:
        if isinstance(n, ast.FunctionDef):
            names.add(n.name)
        else:
            names.add(n.targets[0].id)
    if "build_character_prompt" not in names:
        raise SystemExit("未在 canvas_bridge.py 找到 build_character_prompt")
    module = ast.Module(body=picked, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Dict": typing.Dict,
        "Any": typing.Any,
        "List": typing.List,
        "Optional": typing.Optional,
        "colorsys": __import__("colorsys"),
        "json": __import__("json"),
    }
    exec(compile(module, BRIDGE, "exec"), namespace)  # noqa: S102
    return namespace["build_character_prompt"]


build_character_prompt = load_target_function()
failures: list[str] = []

# ---- 1. 完整角色：visual 组字段必须出现 ----
full = build_character_prompt({
    "name": "林晚",
    "gender": "女",
    "age_range": "青年",
    "tags": ["清冷", "隐忍"],
    "appearance": "长发及腰，素色长裙",
    "temperament": "清冷疏离",
    "memory_anchors": "银质发夹",
    "personality": "外冷内热，嘴硬心软",
    "core_desire": "找回被抹去的记忆",
    "values": "亲情高于一切",
})
for token in ("外貌:", "气质倾向:", "标志性符号:", "性格:"):
    if token not in full:
        failures.append(f"完整角色提示词缺少 {token}\n    实际: {full}")

# ---- 2. 老角色：只有旧字段时，不应出现新前缀 ----
legacy = build_character_prompt({
    "name": "旧角色",
    "gender": "男",
    "appearance": "短发，黑色风衣",
    "personality": "暴躁",
    "background": "退役军官",
})
for token in ("气质倾向:", "标志性符号:"):
    if token in legacy:
        failures.append(f"老角色提示词被注入了空的新字段 {token}\n    实际: {legacy}")

# ---- 3. inner 组不进提示词 ----
for token in ("核心欲望", "找回被抹去的记忆", "价值排序", "亲情高于一切"):
    if token in full:
        failures.append(f"inner 组内容泄漏进提示词: {token}\n    实际: {full}")

# ---- 4. 空角色不应崩 ----
try:
    if build_character_prompt(None) != "":
        failures.append("build_character_prompt(None) 应返回空串")
except Exception as exc:  # noqa: BLE001
    failures.append(f"build_character_prompt(None) 抛异常: {exc!r}")

if failures:
    print("FAIL build_character_prompt 行为不符预期：")
    for item in failures:
        print("  -", item)
    raise SystemExit(1)

print("OK build_character_prompt 字段流向正确")
print("  完整角色 →", full)
print("  老角色   →", legacy)
