# -*- coding: utf-8 -*-
"""角色库字段「五处同步」一致性检查。

背景
----
一个角色字段横跨 6 个地方：
    ① app/modules/lego/character_management_module.py  CHARACTER_FIELD_SCHEMA
    ② app/core/canvas_bridge.py                        build_character_prompt（仅 visual 组）
    ③ app/core/canvas_server.py + canvas_routes_get.py /host/characters（按 schema 派生 + 下发 prompt；A4 后端点在 _routes_get）
    ④ vendor/shiguang-canvas/src/stores/node-factory.ts
    ⑤ vendor/AI-Canvas-tauri/src/libtv/stores/node-factory.ts
    ⑥ 两个 store.ts 的「角色设定块 → prompt」拼装（必须消费 ③ 下发的 prompt）

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
FRONTENDS = [
    os.path.join(ROOT, "vendor", "shiguang-canvas", "src", "stores", "node-factory.ts"),
    os.path.join(ROOT, "vendor", "AI-Canvas-tauri", "src", "libtv", "stores", "node-factory.ts"),
]
# ⑥ 画布提示词拼装（主库 + 副库）
STORES = [
    os.path.join(ROOT, "vendor", "shiguang-canvas", "src", "store.ts"),
    os.path.join(ROOT, "vendor", "AI-Canvas-tauri", "src", "libtv", "store.ts"),
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

    if problems:
        print("FAIL 角色库字段存在漂移：")
        for p in problems:
            print("  -", p)
        return 1

    print(
        f"OK 角色库字段六处同步 "
        f"(fields={len(schema)}, visual={len(visual)}, groups={len(groups)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
