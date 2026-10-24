# -*- coding: utf-8 -*-
"""捏脸枚举镜像漂移守卫（V4.46.2，2026-10-20）

钉死一件事：`faceParams.ts` 是枚举唯一真相源，`canvas_bridge._FACE_*_LABELS`
是它的「枚举 id → 中文」镜像表。镜像缺项时，该特征在生图提示词里
`.get(..., "")` → **静默消失**（用户经「随机」roll 出猫眼/薄唇，或从发饰下拉
选眼镜 ⇒ 卡片正常、3D 正常，出图描述却没有它）。此前无任何守卫覆盖
（SCHEMA/PROMPT 只比体型预设，不做 face 枚举比对）。

【为什么是基线棘轮而不是直接硬断言 0】
补全 8 个中文标签要改 `canvas_bridge.py`，它是 `stage3d-core` 冻结文件 ——
未获「解冻 stage3d-core」不能动。故按 `_verify/check_file_size.py` 的
「存量冻结、只减不增」纪律：
  · 当前已知 8 项漂移登记为 BASELINE（exit 0，显式打印存量）；
  · 任何**新增**漂移（又加 A 类枚举没补表 / 镜像表越权野值）⇒ exit 1 立刻报警；
  · 解冻补全后存量收敛 ⇒ 打印下调提示，total==0 时守卫转防回归硬绿。

【2026-10-21 已转硬断言】用户授权解冻 `stage3d-core` 后 8 项已补全，
BASELINE 已清空 —— 此后任何漂移（新增枚举没补表 / 镜像表越权野值）一律 exit 1。

纯静态：正则解析 TS（不 build）、AST 取 Python 字面量（不 import，零副作用）。
"""
from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TS_PATH = os.path.join(ROOT, "vendor", "packages", "libtv", "src", "faceParams.ts")
PY_PATH = os.path.join(ROOT, "app", "core", "canvas_bridge.py")

# 已知存量漂移（解冻 canvas_bridge.py 补全后逐项下调；清空后守卫转防回归硬绿）
# 2026-10-21：8 项已在「stage3d-core 解冻（用户授权）」后补全 ⇒ 基线清空，
# 守卫转为「镜像表与 faceParams.ts 完全一致」的硬断言（total==0 恒绿）。
BASELINE: dict[str, set[str]] = {}

# faceParams.ts 字段 → canvas_bridge.py 镜像表名
FIELD_TO_TABLE = {
    "browStyle": "_FACE_BROW_LABELS",
    "eyeStyle": "_FACE_EYE_LABELS",
    "lipStyle": "_FACE_LIP_LABELS",
    "hairAccessory": "_FACE_ACCESSORY_LABELS",
}


def ts_enum_array(src: str, field: str) -> set:
    """从 `field: pickEnum<...>(src.field, ["a", "b", …], d.field)` 抓字符串数组字面量。

    normalize 与 randomFaceParams 的白名单逐字一致（faceParams.ts:301-306/393-395），
    取 pickEnum 这份即可代表「数据上能出现的全部合法值」。
    """
    m = re.search(rf"{field}:\s*pickEnum<\w+>\([^,]+,\s*\[([^\]]*)\]", src)
    if not m:
        raise RuntimeError(f"faceParams.ts 解析失败：{field} 的 pickEnum 白名单（格式变了？）")
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def ts_accessory_ids(src: str) -> set:
    """ACCESSORY_META 的顶层 key（发饰 normalize/random/FaceCard 三面同源）。"""
    m = re.search(r"export const ACCESSORY_META\b[\s\S]*?\n\};", src)
    if not m:
        raise RuntimeError("faceParams.ts 解析失败：ACCESSORY_META")
    keys = re.findall(r"^ {2}([a-z_]+):\s*\{", m.group(0), re.M)
    if not keys:
        raise RuntimeError("faceParams.ts 解析失败：ACCESSORY_META 顶层 key")
    return set(keys)


def py_table_keys(field: str) -> set:
    """AST 取 canvas_bridge.py 模块级 dict 字面量的 keys（不 import，零副作用）。"""
    tree = ast.parse(open(PY_PATH, encoding="utf-8").read())
    want = FIELD_TO_TABLE[field]
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == want for t in node.targets
        ):
            if not isinstance(node.value, ast.Dict):
                raise RuntimeError(f"{want} 不是 dict 字面量（改写方式使守卫失明？）")
            return {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise RuntimeError(f"canvas_bridge.py 未找到 {want}")


def main() -> int:
    ts_src = open(TS_PATH, encoding="utf-8").read()

    ts_sets = {
        "browStyle": ts_enum_array(ts_src, "browStyle"),
        "eyeStyle": ts_enum_array(ts_src, "eyeStyle"),
        "lipStyle": ts_enum_array(ts_src, "lipStyle"),
        # 发饰真相源 = ACCESSORY_META；"none" 不戴 ⇒ 无需中文标签（不进描述是正确行为）
        "hairAccessory": ts_accessory_ids(ts_src) - {"none"},
    }

    problems: list = []
    drift: dict = {}
    for field, tset in ts_sets.items():
        pset = py_table_keys(field)
        missing = tset - pset
        drift[field] = missing
        new = missing - BASELINE.get(field, set())
        for v in sorted(new):
            problems.append(
                f"新增漂移：{field} 的值 {v!r} 在 faceParams.ts 白名单里，"
                f"但 canvas_bridge {FIELD_TO_TABLE[field]} 没有中文标签 ⇒ 该特征会静默丢出提示词"
            )
        # 反向：镜像表不该有 TS 白名单不认的野值（防手滑造重复/过时值）
        for v in sorted(pset - tset):
            problems.append(
                f"镜像表越权：{FIELD_TO_TABLE[field]} 有 {v!r}，但 faceParams.ts 白名单不认它"
            )

    total = sum(len(v) for v in drift.values())
    baseline_total = sum(len(v) for v in BASELINE.values())
    print(
        f"[face 枚举镜像] TS 白名单合计 {sum(len(v) for v in ts_sets.values())} 项 · "
        f"当前漂移 {total} 项 · 基线存量 {baseline_total} 项"
    )
    for field in FIELD_TO_TABLE:
        if drift[field]:
            print(f"  · {field}: 缺中文标签 {sorted(drift[field])}")

    new_drift = {f: (drift[f] - BASELINE.get(f, set())) for f in FIELD_TO_TABLE}
    if any(new_drift.values()) or any(
        p.startswith("镜像表越权") for p in problems
    ):
        print("✗ 失败（基线之外的新漂移 / 镜像表越权）：")
        for p in problems:
            print("   -", p)
        return 1
    if total == 0:
        print("OK 捏脸枚举镜像零漂移（canvas_bridge.py 已全量补齐；守卫保留作防回归）")
        return 0
    hint = "（存量已收敛，记得把守卫 BASELINE 下调到实测值）" if total < baseline_total else ""
    print(
        f"OK 捏脸枚举镜像无新增漂移（存量 {total} 项已登记基线：需解冻 stage3d-core "
        f"补全 canvas_bridge.py 中文表）{hint}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
