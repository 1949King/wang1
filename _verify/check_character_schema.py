# -*- coding: utf-8 -*-
"""角色库字段「五处同步」一致性检查。

背景
----
一个角色字段横跨 6 个地方：
    ① app/modules/lego/character_management_module.py  CHARACTER_FIELD_SCHEMA
    ② app/core/canvas_bridge.py                        build_character_prompt（仅 visual 组）
    ③ app/core/canvas_server.py + canvas_routes_get.py /host/characters（按 schema 派生 + 下发 prompt；A4 后端点在 _routes_get）
    ④ vendor/packages/canvas-core/src/stores/node-factory.ts
    ⑤ vendor/AI-Canvas-tauri/src/libtv/stores/node-factory.ts
    ⑥ 两个 store.ts 的「角色设定块 → prompt」拼装（必须消费 ③ 下发的 prompt）
    ⑦ character_management_module.py 的 HUMAN_VARIANT_OPTIONS ↔ 画布 riggedHumanoid.ts 的
       HUMAN_PRESETS：体型预设值必须**逐字相同**，否则「角色库 → 3D 导演台」查不到预设、
       静默退回兜底推断（角色库选了「儿童」，导演台给成年男体，不报错）。2026-10-12 加入。
    ⑧ character_management_module.py 的 enum 字段必须有控件且**五处读写都接线**
       （生成器只认 text/string 时，enum 字段会「标题看得见、值填不了」）。2026-10-12 加入。

任何一处漏改都**不会报错**，只会表现为「填了不生效」或「前端看不到」。
本脚本把这条链路变成可自动验证的。

⑥ 的由来（2026-09-13 修的真实缺陷）：
    store.ts 里只拼 `target.appearance`，于是用户在角色库填的
    「气质倾向 / 标志性符号 / 性格特征」三个 visual 字段**一个字都进不了生图提示词**；
    同时删除正则锚在 `^`、追加却在末尾 ⇒ 重复绑定越绑越长、解绑还删不掉。
    现在改为直接用服务端拼好的 prompt（唯一真相源），前端不再自己拼字段。
    行为侧由 `_verify/check_char_prompt_block.mjs`（Node）实测。

用法（项目根执行）
--------------
    .venv312\\Scripts\\python.exe _verify/check_character_schema.py

退出码 0 = 通过；1 = 有漂移，并打印具体位置。
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MODULE = os.path.join(ROOT, "app", "modules", "lego", "character_management_module.py")
BRIDGE = os.path.join(ROOT, "app", "core", "canvas_bridge.py")
# ③ /host/characters 端点于 V4.40.4（A4 路由拆分）从 canvas_server.py 迁到
# canvas_routes_get.py —— 两文件都扫，任一命中即算派生到位（防再次迁移造成盲区）。
SERVER = os.path.join(ROOT, "app", "core", "canvas_server.py")
SERVER_ROUTES = os.path.join(ROOT, "app", "core", "canvas_routes_get.py")
# P0-1 Phase 2（2026-10-18）：tauri 侧 libtv 副本已删除，两宿主共用真源包，只扫一处。
FRONTENDS = [
    os.path.join(ROOT, "vendor", "packages", "canvas-core", "src", "stores", "node-factory.ts"),
]
# ⑥ 画布提示词拼装（真源包，web/tauri 双宿主共用）
STORES = [
    os.path.join(ROOT, "vendor", "packages", "canvas-core", "src", "store.ts"),
]

problems: list[str] = []


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _literal(name: str):
    """静态取模块级字面量，避免 import PyQt6。"""
    tree = ast.parse(read(MODULE))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise RuntimeError(f"未找到模块级常量 {name}")


def main() -> int:
    schema = _literal("CHARACTER_FIELD_SCHEMA")
    groups = [g for g, _ in _literal("CHARACTER_FIELD_GROUPS")]
    valid = set(groups)

    # ---- ① schema 自身结构 ----
    seen: set[str] = set()
    for field in schema:
        if len(field) != 5:
            problems.append(f"schema 项不是 5 元组: {field!r}")
            continue
        key, _label, _type, _required, group = field
        if key in seen:
            problems.append(f"字段 key 重复: {key}")
        seen.add(key)
        if group not in valid:
            problems.append(f"字段 {key} 的分组 {group!r} 不在 CHARACTER_FIELD_GROUPS 内")

    visual = [f[0] for f in schema if len(f) == 5 and f[4] == "visual"]

    # ---- ② visual 组必须被 build_character_prompt 消费 ----
    match = re.search(r"def build_character_prompt.*?(?=\ndef )", read(BRIDGE), re.S)
    if not match:
        problems.append("canvas_bridge.py 未找到 build_character_prompt")
        bridge_body = ""
    else:
        bridge_body = match.group(0)
    for key in visual:
        if f'"{key}"' not in bridge_body:
            problems.append(f"visual 字段 {key} 未被 build_character_prompt 读取（进不了提示词）")

    # ---- ③ HTTP 端点必须按 schema 派生，并下发拼好的 prompt ----
    # A4 后端点已迁 canvas_routes_get.py，两文件合并扫描（命中其一即可）。
    server_src = read(SERVER) + "\n" + (
        read(SERVER_ROUTES) if os.path.isfile(SERVER_ROUTES) else ""
    )
    if "CHARACTER_FIELD_SCHEMA" not in server_src:
        problems.append("canvas_server.py/canvas_routes_get.py 的 /host/characters 未按 CHARACTER_FIELD_SCHEMA 派生，新增字段会漏传")
    if "build_character_prompt" not in server_src:
        problems.append(
            "canvas_server.py/canvas_routes_get.py 的 /host/characters 未下发 build_character_prompt(c)，"
            "前端只能自己拼字段（会漏 visual 组）"
        )

    # ---- ④⑤ 两个前端包的 CharacterEntry ----
    for fe in FRONTENDS:
        if not os.path.isfile(fe):
            problems.append(f"前端文件缺失: {os.path.relpath(fe, ROOT)}")
            continue
        m = re.search(r"export type CharacterEntry\s*=\s*\{(.*?)\n\};", read(fe), re.S)
        if not m:
            problems.append(f"{os.path.relpath(fe, ROOT)} 未找到 CharacterEntry 类型定义")
            continue
        entry = m.group(1)
        for field in schema:
            key = field[0]
            if not re.search(rf"^\s*{re.escape(key)}\??\s*:", entry, re.M):
                problems.append(f"{os.path.relpath(fe, ROOT)} 的 CharacterEntry 缺字段 {key}")
        # 派生字段：服务端下发的拼装结果
        if not re.search(r"^\s*prompt\??\s*:", entry, re.M):
            problems.append(f"{os.path.relpath(fe, ROOT)} 的 CharacterEntry 缺派生字段 prompt")

    # ---- ⑥ 画布拼装必须消费服务端 prompt，不许退化回只拼 appearance ----
    for st in STORES:
        rel = os.path.relpath(st, ROOT)
        if not os.path.isfile(st):
            problems.append(f"store 文件缺失: {rel}")
            continue
        s = read(st)
        if re.search(r"\[角色外貌: \$\{target\.appearance\}\]", s):
            problems.append(f"{rel} 仍在用旧写法只拼 target.appearance（visual 组字段会丢）")
        if "charPromptBlock(target.prompt)" not in s:
            problems.append(f"{rel} 未消费服务端下发的 target.prompt")
        if "function applyCharBlock" not in s:
            problems.append(f"{rel} 缺少 applyCharBlock，角色设定块增删不幂等")

    # ---- ⑦ 3D 导演台体型预设：Python 选项表必须与画布 HUMAN_PRESETS 的 key 逐字一致 ----
    # 由来（2026-10-12，缺口①「角色库 → 3D 导演台」）：human_variant 是角色库交给导演台的
    # 体型字段，值要拿去查画布侧的 HUMAN_PRESETS[variant]。两边一旦不逐字相同，导演台
    # 查不到预设、**静默退回兜底推断**（角色库明明选了「儿童」，导演台给个成年男体，不报错）。
    variants = _literal("HUMAN_VARIANT_OPTIONS")
    py_values = [v for v, _label in variants]
    rigged = os.path.join(ROOT, "vendor", "packages", "canvas-core", "src", "riggedHumanoid.ts")
    if not os.path.isfile(rigged):
        problems.append("vendor/packages/canvas-core/src/riggedHumanoid.ts 缺失，无法校验体型预设镜像")
    else:
        m = re.search(r"export const HUMAN_PRESETS[^\n]*\{(.*?)\n\};", read(rigged), re.S)
        if not m:
            problems.append("riggedHumanoid.ts 未找到 HUMAN_PRESETS")
        else:
            ts_keys = re.findall(r'^\s*id:\s*"([^"]+)"', m.group(1), re.M)
            if py_values[:1] != [""]:
                problems.append(
                    f"HUMAN_VARIANT_OPTIONS 首项应为「未指定」空值，实际 {py_values[:1]!r}"
                )
            if py_values[1:] != ts_keys:
                problems.append(
                    "HUMAN_VARIANT_OPTIONS 与画布 HUMAN_PRESETS 的 key 不一致"
                    f"（py={py_values[1:]!r} vs ts={ts_keys!r}）⇒ 导演台会静默退回兜底推断"
                )
            if not ts_keys:
                problems.append("HUMAN_PRESETS 里没抽到任何 id，检查本脚本的正则是否过期")

    # ---- ⑧ enum 字段必须真有控件、真能被保存（否则「填了不可用」静默失效） ----
    # 由来（2026-10-12）：动态表单生成器原本只认 text/string，新增 enum 字段会
    # 「标题看得见、值填不了」，保存后永远是空 —— 与本文件开头说的「填了不生效」同一类缺陷。
    header_keys = _literal("_HEADER_FIELD_KEYS")
    enum_fields = [f[0] for f in schema if len(f) == 5 and f[2] == "enum" and f[0] not in header_keys]
    module_src = read(MODULE)
    # _ENUM_SOURCES 的值引用了另一个常量（HUMAN_VARIANT_OPTIONS），literal_eval 解不了
    # ⇒ 这里只取它的键名（键名本身就是字面量，够用）。
    m_src = re.search(r"^_ENUM_SOURCES\s*(?::[^=]+)?=\s*\{(.*?)^\}", module_src, re.S | re.M)
    src_keys = re.findall(r'"(\w+)"\s*:', m_src.group(1)) if m_src else []
    if not m_src:
        problems.append("未找到 _ENUM_SOURCES 定义（enum 字段的可选值来源表）")
    for key in enum_fields:
        if key not in src_keys:
            problems.append(
                f"enum 字段 {key} 不在 _ENUM_SOURCES 里 ⇒ 滚动表单里拿不到控件（会「填了不可用」）"
            )
    if 'f[2] in ("text", "string", "enum")' not in module_src:
        problems.append("动态表单生成器没有把 enum 纳入控件分支 ⇒ enum 字段会没有控件")
    wiring = {
        "建下拉框": r"self\._enum_combos\[key\] = combo",
        "提交时取值": r"for key, combo in self\._enum_combos\.items\(\):\s*\n\s*data\[key\]",
        "载入时回填": r"for key, combo in self\._enum_combos\.items\(\):\s*\n\s*idx = combo\.findData",
        "清空时复位": r"for combo in self\._enum_combos\.values\(\):\s*\n\s*combo\.setCurrentIndex\(0\)",
        "启用态联动": r"\*self\._enum_combos\.values\(\),",
    }
    for label, pat in wiring.items():
        if not re.search(pat, module_src):
            problems.append(f"enum 下拉框的「{label}」未接线（只加控件不读写 ⇒ 填了不生效）")

    if problems:
        print("FAIL 角色库字段存在漂移：")
        for p in problems:
            print("  -", p)
        return 1

    print(
        f"OK 角色库字段六处同步 "
        f"(fields={len(schema)}, visual={len(visual)}, groups={len(groups)}, "
        f"enum={len(enum_fields)}, variants={len(py_values) - 1})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
