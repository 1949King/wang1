# -*- coding: utf-8 -*-
"""AssetMaster 母版模型守卫（WS-D D1，2026-10-23 刀0）

断言：
  ① 结构在册：MASTER_KINDS 四值 / MODEL_VERSION 存在 / AssetMaster+AssetVariant 字段齐
  ② 纯模型纪律：模块顶层**不 import PyQt6/requests/sqlite3**，无 print / 无文件 IO
  ③ 母版-变体继承：resolve_variant = canonical ⊕ overrides，且不改入参（深合并语义）
  ④ 不猜：kind 非法 / master_id 空 / 变体 master_id 不匹配 / 变体 id 重复 ⇒ 全部进 errors
  ⑤ stale 纪律：update_canonical 后变体全标 stale 且**不自动重生成**；
     clear_stale 对存在变体生效、对不存在返回 False（不静默成功）
  ⑥ 序列化往返：to_dict → from_dict → to_dict 恒等
  ⑦ 无第二套：全库不得出现第二份「母版」定义（AssetMaster 类只此一处）

用法（项目根执行）：python _verify/check_asset_master.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MODULE_REL = "app/core/asset_master.py"

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _src() -> str:
    with open(os.path.join(ROOT, MODULE_REL), "r", encoding="utf-8") as f:
        return f.read()


def _code_only() -> str:
    """去掉模块/行内注释与字符串字面量，只留真正会执行的代码。

    纯模型纪律查的是「有没有运行时依赖」，而文档字符串里正常会写
    「不 import PyQt6」这类**说明**——直接对源码全文 grep 会把说明当成
    依赖（本守卫首跑即误报）。故先剥注释与字符串，再做关键词判定。
    """
    import io
    import tokenize

    kept = []
    try:
        with open(os.path.join(ROOT, MODULE_REL), "rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                                tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER):
                    continue
                kept.append(tok.string)
    except (tokenize.TokenError, OSError, SyntaxError) as exc:
        raise AssertionError(f"源码无法分词（语法错误？）：{exc!r}") from exc
    return " ".join(kept)


# ── ① 结构在册 ────────────────────────────────────────────────────────

def check_surface() -> None:
    from app.core import asset_master as m

    if tuple(getattr(m, "MASTER_KINDS", ())) != ("character", "scene", "prop", "style"):
        _fail(f"① MASTER_KINDS 漂移：{getattr(m, 'MASTER_KINDS', None)!r}")
    if not getattr(m, "MODEL_VERSION", ""):
        _fail("① MODEL_VERSION 缺失（序列化无版本锚点）")
    for name in ("AssetMaster", "AssetVariant", "create_master", "add_variant",
                 "resolve_variant", "update_canonical", "clear_stale",
                 "validate_master", "deep_merge"):
        if not hasattr(m, name):
            _fail(f"① 公开件被删/改名：{name}")
    # 最小构造：字段齐才能承载「母版+变体」
    master = m.create_master("character", "甲")
    data = master.to_dict()
    for key in ("master_id", "kind", "name", "canonical", "variants",
                "version", "created_at", "updated_at", "stale_reason", "model_version"):
        if key not in data:
            _fail(f"① AssetMaster.to_dict 缺字段：{key}")


# ── ② 纯模型纪律 ──────────────────────────────────────────────────────

def check_purity() -> None:
    src = _code_only()
    banned = ("PyQt6", "requests", "sqlite3", "subprocess", "QApplication")
    for token in banned:
        if token in src:
            _fail(f"② 纯模型模块出现运行时依赖：{token}（应零 I/O、零 UI）")
    if "print" in src:
        _fail("② 纯模型模块出现 print（应用 logger 或静默，不用 print）")
    for token in ("open", "makedirs", "fsync"):
        if token in src:
            _fail(f"② 纯模型模块出现文件 IO：{token}")


# ── ③ 继承语义 ────────────────────────────────────────────────────────

def check_inheritance() -> None:
    from app.core.asset_master import add_variant, create_master, resolve_variant

    canonical = {"hair": "long", "look": {"color": "black", "style": "bob"}}
    master = create_master("character", "乙", dict(canonical))
    variant = add_variant(master, overrides={"look": {"color": "brown"}})
    resolved, errors = resolve_variant(master, variant.variant_id)
    if errors:
        _fail(f"③ 合法母版+变体竟报错：{errors}")
        return
    if resolved.get("hair") != "long":
        _fail("③ 未继承母版字段 hair（canonical 被丢弃）")
    if resolved.get("look", {}).get("color") != "brown":
        _fail("③ overrides 未覆盖母版 look.color")
    if resolved.get("look", {}).get("style") != "bob":
        _fail("③ 深合并丢失母版同层其它键 look.style（覆盖变成了整块替换）")
    # 不改入参
    if canonical["look"]["color"] != "black":
        _fail("③ resolve_variant 改动了母版 canonical 入参（应深拷贝）")
    # 身份锚点随解析带出
    if resolved.get("_master_id") != master.master_id or resolved.get("_kind") != "character":
        _fail("③ 解析结果缺身份锚点（_master_id / _kind）")


# ── ④ 不猜 ────────────────────────────────────────────────────────────

def check_no_guessing() -> None:
    from app.core.asset_master import AssetMaster, AssetVariant, add_variant, create_master, validate_master

    bad = AssetMaster(master_id="", kind="unknown", name="")
    errors = validate_master(bad)
    for token in ("master_id", "kind", "name"):
        if not any(token in e for e in errors):
            _fail(f"④ 非法母版未报 {token}（不猜纪律被破坏）")

    master = create_master("prop", "丙")
    add_variant(master, variant_id="dup")
    add_variant(master, variant_id="dup")
    if not any("重复" in e for e in validate_master(master)):
        _fail("④ 变体 id 重复未被报出")

    master2 = create_master("prop", "丁")
    master2.variants.append(AssetVariant(variant_id="v", master_id="other-master"))
    if not any("master_id" in e for e in validate_master(master2)):
        _fail("④ 变体 master_id 不匹配未被报出（血缘可静默错挂）")

    # 未知 kind 不硬塞：create_master 不校验（模型层不拦），但 validate 必须报
    odd = create_master("hologram", "戊")
    if not any("kind" in e for e in validate_master(odd)):
        _fail("④ 未知 kind 未进 errors（可能被静默接受）")


# ── ⑤ stale 纪律 ──────────────────────────────────────────────────────

def check_stale_discipline() -> None:
    from app.core.asset_master import add_variant, clear_stale, create_master, resolve_variant, update_canonical

    master = create_master("scene", "己", {"time": "day"})
    v1 = add_variant(master, variant_id="v1")
    v2 = add_variant(master, variant_id="v2")
    marked = update_canonical(master, {"time": "night"})
    if {v.variant_id for v in marked} != {"v1", "v2"}:
        _fail("⑤ update_canonical 未把全部既有变体标 stale")
    if not (v1.stale_reason and v2.stale_reason):
        _fail("⑤ 变体 stale_reason 为空（改了母版却不说旧产出已过时）")
    if master.version < 2:
        _fail("⑤ 母版 version 未递增（无法判断「哪版母版产出的」）")
    resolved, _ = resolve_variant(master, "v1")
    if not resolved.get("_stale_reason"):
        _fail("⑤ 解析结果未带 _stale_reason（下游无法如实提示）")
    if resolved.get("time") != "night":
        _fail("⑤ 母版更新后旧变体未生效新 canonical")
    # 不自动重生成：变体 media 必须原样保留（模型层不碰产物）
    if v1.media:
        _fail("⑤ 模型层竟改动了变体 media（应只标 stale，不重生成）")
    if clear_stale(master, "v1") is not True:
        _fail("⑤ clear_stale 对存在变体返回非 True")
    if v1.stale_reason != "":
        _fail("⑤ clear_stale 未清空 stale_reason")
    if clear_stale(master, "nope") is not False:
        _fail("⑤ clear_stale 对不存在变体未返回 False（静默成功＝说谎）")
    # 母版 stale 也要能带出
    master.stale_reason = "母版自身过期"
    resolved2, _ = resolve_variant(master, "v2")
    if not resolved2.get("_stale_reason"):
        _fail("⑤ 母版级 stale_reason 未透传")


# ── ⑥ 序列化往返 ──────────────────────────────────────────────────────

def check_roundtrip() -> None:
    from app.core.asset_master import AssetMaster, add_variant, create_master

    master = create_master("style", "庚", {"palette": {"neon": ["#f0f", "#0ff"]}})
    add_variant(master, overrides={"palette": {"neon": ["#f0f"]}}, seed=7, model="m", media=["a.png"])
    first = master.to_dict()
    second = AssetMaster.from_dict(first).to_dict()
    if first != second:
        _fail("⑥ to_dict → from_dict → to_dict 不恒等（序列化丢字段）")
    # 畸形输入不抛
    try:
        broken = AssetMaster.from_dict({"variants": "not-a-list"})
        if broken.variants != []:
            _fail("⑥ 畸形 variants 未落回空列表")
    except Exception as exc:  # noqa: BLE001 - 守卫要抓「抛异常」本身
        _fail(f"⑥ from_dict 对畸形输入抛异常：{exc!r}")


# ── ⑦ 无第二套母版定义 ────────────────────────────────────────────────

def check_single_source() -> None:
    hits = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "app")):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "temp", "node_modules", ".venv312")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            if os.path.abspath(full) == os.path.abspath(os.path.join(ROOT, MODULE_REL)):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except OSError:
                continue
            if "class AssetMaster" in text or "class AssetVariant" in text:
                hits.append(os.path.relpath(full, ROOT).replace("\\", "/"))
    if hits:
        _fail(f"⑦ 出现第二套母版定义（唯一真相源被破坏）：{hits}")


def main() -> int:
    check_surface()
    check_purity()
    check_inheritance()
    check_no_guessing()
    check_stale_discipline()
    check_roundtrip()
    check_single_source()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  AssetMaster 母版：结构在册/纯模型纪律/继承不动入参/不猜/stale不动产物/往返恒等/单一真相源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
