# -*- coding: utf-8 -*-
"""资产中间表示守卫（刀2 · asset_hub，2026-10-23）

D2 缺口：「同一角色跨镜复用有 **唯一来源**」不成立。根因（刀0/刀2 取证）：
画布产物入轨载荷只有 6 个程序性字段（`stage3dArtifacts.ts:125-133`），
无身份 / 无版本 / 血缘只 4/6 键（`editorIngress.ts:92-101` 丢了 channel/reference）。

断言：
  ① 身份确定性：同一 path+source 派生同一 asset_id（**不用随机 uuid / 内置 hash**）
  ② 六键铁律：lineage 只收 `glue.schema.GENERATION_KEYS`，**不扩容**
  ③ 不猜不造假：缺 path ⇒ 空 asset_id ⇒ 拒绝落账；落账失败如实 False
  ④ 唯一存储：asset_hub **不得自建存储**（必须委托 gen_task_registry）
  ④ 覆盖率诚实：空样本 coverage=None（不把「没测」说成 0）
  ⑤ 接线在册：`/ingest_path` 在**入轨之前**落账，且失败不拦链路
  ⑥ 与母版分工：asset_hub 只**引用** master_id，不复制 AssetMaster 字段
  ⑦ 双加载免疫：is_asset_ref 用结构判定（本仓库存在 app.core / core 两套导入）

用法（项目根执行）：python _verify/check_asset_hub.py
退出码 0 = 通过；1 = 有漂移。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HUB_REL = "app/core/asset_hub.py"
ROUTE_REL = "app/core/canvas_routes_post.py"
REGISTRY_REL = "app/core/gen_task_registry.py"

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def _code_only(rel: str) -> str:
    """剥掉注释与字符串字面量，只留会执行的代码。

    本守卫首跑三连误报，根因都是**文档字符串里的说明词**被当成代码：
    docstring 里写着「不用随机 uuid」「不用内置 hash()」「canonical+variants」，
    全文 grep 就会把说明判成违规。故先 tokenize 再判定。
    """
    import tokenize

    kept = []
    try:
        with open(os.path.join(ROOT, rel), "rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                if tok.type in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                                tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER):
                    continue
                kept.append(tok.string)
    except (tokenize.TokenError, OSError, SyntaxError) as exc:
        raise AssertionError(f"{rel} 无法分词（语法错误？）：{exc!r}") from exc
    return " ".join(kept)


# ── ① 身份确定性 ──────────────────────────────────────────────────────

def check_identity() -> None:
    from app.core.asset_hub import derive_asset_id

    a = derive_asset_id("D:/m/out.mp4", source="s")
    b = derive_asset_id("D:/m/out.mp4", source="s")
    if not a or a != b:
        _fail(f"① asset_id 不确定（跨调用不一致）：{a!r} vs {b!r}")
    if not a.startswith("ast_"):
        _fail(f"① asset_id 前缀不是 ast_：{a!r}")
    # 大小写/斜杠归一
    if derive_asset_id("D:\\M\\OUT.MP4", source="s") != a:
        _fail("① 路径大小写/分隔符未归一（同一文件会派生两个身份）")
    # 不同 source 必须不同
    if derive_asset_id("D:/m/out.mp4", source="other") == a:
        _fail("① 不同 source 派生同一 id（出处不可区分）")
    # 空路径必须空 id（不造无主身份）
    if derive_asset_id("") != "" or derive_asset_id("   ") != "":
        _fail("① 空路径竟派生出 id（会造无主记录）")

    src = _code_only(HUB_REL)
    if "uuid" in src:
        _fail("① asset_hub 使用 uuid（身份必须由路径确定性派生，否则重放不幂等）")
    if "hash(" in src.replace("hashlib.", ""):
        _fail("① asset_hub 使用内置 hash()（带进程随机盐，跨进程不稳定）")


# ── ② 六键铁律 ────────────────────────────────────────────────────────

def check_six_key_whitelist() -> None:
    from app.core.asset_hub import asset_ref_from_ingest
    from app.core.glue.schema import GENERATION_KEYS

    ref = asset_ref_from_ingest({"path": "a", "generation": {
        "prompt": "p", "seed": 1, "model": "m", "channel": "c",
        "character_id": "ch", "reference": "r",
        "smuggled": "x", "duration": 9,
    }})
    if set(ref.lineage) - set(GENERATION_KEYS):
        _fail(f"② lineage 出现白名单外的键：{sorted(set(ref.lineage) - set(GENERATION_KEYS))}")
    missing = [k for k in GENERATION_KEYS if k not in ref.lineage]
    if missing:
        _fail(f"② 六键未被完整保留：缺 {missing}（前端丢 channel/reference 的缺口未补上）")


# ── ③ 不猜不造假 ──────────────────────────────────────────────────────

def check_no_fabrication() -> None:
    from app.core.asset_hub import AssetRef, asset_ref_from_ingest, remember_ingest

    empty = asset_ref_from_ingest({})
    if empty.asset_id or empty.path:
        _fail("③ 空载荷竟产出身份（不猜纪律被破坏）")
    if remember_ingest(empty) is not False:
        _fail("③ 无主资产竟落账成功（会造无主记录）")

    class Boom:
        def record_asset(self, *a, **k):
            raise RuntimeError("boom")

    class NoneStore:
        def record_asset(self, *a, **k):
            return None

    ref = asset_ref_from_ingest({"path": "D:/a.mp4"})
    if remember_ingest(ref, store=Boom()) is not False:
        _fail("③ record_asset 抛异常时未如实返回 False（谎报成功）")
    if remember_ingest(ref, store=NoneStore()) is not False:
        _fail("③ record_asset 返回 None 时未如实返回 False")
    if remember_ingest(ref, store=object()) is not False:
        _fail("③ store 无 record_asset 时未如实返回 False")

    # 缺字段保持缺失，不补默认值
    bare = asset_ref_from_ingest({"path": "D:/a.mp4"})
    if bare.lineage != {} or bare.title != "" or bare.master_id != "":
        _fail("③ 缺字段被补了默认值（应保持缺失）")
    if bare.kind != "unknown":
        _fail(f"③ 未识别 kind 未落到 unknown：{bare.kind!r}")


# ── ④ 唯一存储（不得自建） ────────────────────────────────────────────

def check_single_store() -> None:
    src = _code_only(HUB_REL)
    # 只许委托，不许自带落盘
    banned = ("json.dump", "json.load", "open(", "Path(", "sqlite3", "os.makedirs")
    for token in banned:
        if token in src:
            _fail(f"④ asset_hub 出现自建存储痕迹 `{token}`（应委托 gen_task_registry）")
    if "gen_task_registry" not in src:
        _fail("④ asset_hub 未委托 gen_task_registry（资产真相源被绕过）")
    # 真相源必须仍提供那三个能力（门面依赖的上游契约）
    reg = _read(REGISTRY_REL)
    for name in ("def record_asset", "def get_asset", "def resolve_lineage"):
        if name not in reg:
            _fail(f"④ gen_task_registry 上游契约缺失：{name}")


# ── ④b 覆盖率诚实 ─────────────────────────────────────────────────────

def check_coverage_honesty() -> None:
    from app.core.asset_hub import AssetRef, asset_ref_from_ingest, lineage_coverage

    empty = lineage_coverage([])
    if empty["coverage"] is not None:
        _fail(f"④ 空样本的 coverage 不是 None（把「没测」说成 {empty['coverage']}）")
    if empty["total"] != 0:
        _fail("④ 空样本 total 不是 0")

    full = asset_ref_from_ingest({"path": "a", "generation": {
        "prompt": "p", "seed": 1, "model": "m",
        "channel": "c", "character_id": "ch", "reference": "r"}})
    half = asset_ref_from_ingest({"path": "b", "generation": {"prompt": "p"}})
    got = lineage_coverage([full, half])
    if got["total"] != 2 or got["complete"] != 1 or got["coverage"] != 0.5:
        _fail(f"④ 覆盖率算错：{got}")
    # attacker: 空 ref 不得计入分母
    with_empty = lineage_coverage([full, AssetRef(asset_id="", path="")])
    if with_empty["total"] != 1:
        _fail("④ 空 ref 被计入覆盖率分母")


# ── ⑤ 接线在册 ────────────────────────────────────────────────────────

def check_routing_wired() -> None:
    src = _read(ROUTE_REL)
    if "asset_hub" not in src:
        _fail("⑤ /ingest_path 未接 asset_hub（中间过程仍是裸路径）")
        return
    idx_ingest = src.find('@_route_post("/ingest_path")')
    idx_next = src.find('@_route_post("/push_from_editor")')
    body = src[idx_ingest:idx_next] if idx_next > idx_ingest else src[idx_ingest:]
    if "asset_ref_from_ingest" not in body:
        _fail("⑤ 处理器未归一 AssetRef")
    if "remember_ingest" not in body:
        _fail("⑤ 处理器未落账")
    idx_ref = body.find("asset_ref_from_ingest")
    idx_call = body.find("cs.ingest_local_file(")
    if idx_call < 0 or (idx_ref >= 0 and idx_ref > idx_call):
        _fail("⑤ 落账发生在入轨之后（必须在入轨之前，否则首帧就已无身份）")
    # 诚实降级：落账失败不得拦住入轨
    if "except Exception" not in body:
        _fail("⑤ 落账无异常兜底（资产层故障会把入轨链路一起炸掉）")


# ── ⑥ 与母版分工 ──────────────────────────────────────────────────────

def check_master_boundary() -> None:
    src = _code_only(HUB_REL)
    for token in ("AssetMaster", "AssetVariant", "canonical"):
        if token in src:
            _fail(f"⑥ asset_hub 复制了母版模型结构 `{token}`（应只引用 master_id）")
    if "master_id" not in src:
        _fail("⑥ asset_hub 无 master_id 引用位（与母版完全脱钩）")


# ── ⑦ 双加载免疫 ──────────────────────────────────────────────────────

def check_dual_import_safety() -> None:
    from app.core.asset_hub import AssetRef, is_asset_ref, remember_ingest

    if not is_asset_ref(AssetRef(asset_id="x", path="y")):
        _fail("⑦ is_asset_ref 判定不了本模块的 AssetRef")
    if is_asset_ref({"asset_id": "x", "path": "y"}):
        _fail("⑦ is_asset_ref 把普通 dict 误判为资产引用")
    if is_asset_ref("junk"):
        _fail("⑦ is_asset_ref 把字符串误判为资产引用")
    # remember_ingest 也须用同一判定（否则双加载下静默返回 False）
    src = _read(HUB_REL)
    start = src.find("def remember_ingest")
    end = src.find("def lineage_of_clip", start)
    body = src[start:end] if end > start else ""
    if "isinstance(ref, AssetRef)" in body:
        _fail("⑦ remember_ingest 仍用 isinstance（双加载下会误拒合法 AssetRef）")


def main() -> int:
    check_identity()
    check_six_key_whitelist()
    check_no_fabrication()
    check_single_store()
    check_coverage_honesty()
    check_routing_wired()
    check_master_boundary()
    check_dual_import_safety()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  资产中间表示：身份确定性/六键铁律/不猜不造假/唯一存储(委托registry)/"
          "覆盖率诚实/入轨前接线/母版分工/双加载免疫")
    return 0


if __name__ == "__main__":
    sys.exit(main())
