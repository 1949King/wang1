# -*- coding: utf-8 -*-
"""时间线字段写入面棘轮守卫（OTIO 全量迁移·刀4，CANONICAL）

背景：``EditorModule._clips`` 的**字段级**直写（``clip["k"] = v`` / ``clip.update(...)``）
历史上散落在 UI 回调、撤销重放、Agent 能力层等数十处。刀4 在 ``TimelineStore``
增补 ``set_fields`` / ``update_where`` 唯一字段写 API，并把存量直写逐个改走 API。

本守卫用 **AST 污点分析** 扫描 app/ 下「由 ``_clips`` 派生的 dict 变量」上的
原地写操作（下标赋值 / ``+=`` / ``.update(``），按文件计数并与基线 JSON 对比：

  * 棘轮**只减不增**：任一文件计数超过基线 → FAIL；基线外文件出现新直写 → FAIL；
  * 收拢达标后用 ``--update`` 重写基线留痕（同 frozen_zone_guard 纪律）。

豁免（不进扫描）：
  * app/core/timeline_store.py —— API 自身实现（锁内原地 update 是合法本体）；
  * app/modules/lego/clip_transform.py —— 冻结区 transform 唯一写入入口
    （normalize/apply_normalized，方案 §1.2；store API 只转发不另实现）；
  * app/tests/** —— 测试替身自管数据。

刀8（2026-10-19 形态 A）：timeline_widget.py 整文件豁免**已摘除**——widget 层字段写
全部收口经注入 store（set_store + _write_clip_fields 唯一写缝），基线清零固化。
并新增 PROJECTION 断言：镜像维护 API 化后，跨文件重绑 `X._clips = ...`（X 非 self，
如 `tw._clips =` / `timeline._clips =`）全 app 必须为 0，镜像维护只许 timeline_widget.py
内部（`self._clips = ...`）经 reset_clips_projection / sync_clips_projection 进行。

刀9（2026-10-19 真相源宣告收口）：棘轮升级为 **CANONICAL 硬断言**（只减不增 → 永不可回潮）：
  * ⑥ 字段直写**硬零**：基线 `{}` 固化后，任何文件出现计数即 FAIL（基线文件保留作清零留痕）；
  * ④ REBIND：`self._clips = ` 重绑全 app 仅 editor_module.py init 建列表一处（计数==1，不钉行号）；
    timeline_widget.py 为投影镜像自管（形态 A 允许）；其余文件出现即 FAIL；
  * ⑤ MUTATION：`_clips` 列表原地突变（append/extend/insert/pop/remove/clear/sort/reverse、
    `_clips[...] = `/`_clips[:] = ` 下标写）除 timeline_store 本体与 widget 镜像外全 app 硬零
    ——结构写唯一入口 = TimelineStore.add/remove_by_id/replace_all/clear（真相源切换收口钉死）。

用法（项目根执行）：
  .venv312\\Scripts\\python.exe _verify/check_timeline_write_surface.py           # 校验
  .venv312\\Scripts\\python.exe _verify/check_timeline_write_surface.py --update  # 重写基线
退出码 0 = 达标；1 = 棘轮回涨或接线漂移。
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)  # 校验模式需 import app.core.glue（同 check_timeline_store.py）
BASELINE = os.path.join(ROOT, "_verify", "timeline_write_surface_baseline.json")

SKIP_REL = {
    os.path.join("app", "core", "timeline_store.py"),
    os.path.join("app", "modules", "lego", "clip_transform.py"),
}
TESTS_PREFIX = os.path.join("app", "tests") + os.sep
# 行尾标记 `# ratchet-exempt`：理论兜底/不可达路径的豁免行（须注释说明理由）
EXEMPT_MARK = "# ratchet-exempt"
# 词边界匹配 _clips（避免 _clips_snapshot 等派生名误染）
_CLIPS_RE = re.compile(r"(?<!\w)_clips(?!\w)")

problems = []


def _fail(msg: str) -> None:
    problems.append(msg)


def _refs_clips(node: ast.AST) -> bool:
    """表达式源码是否引用 ``_clips``（真相源列表派生的粗略判据）。"""
    try:
        return bool(_CLIPS_RE.search(ast.unparse(node)))
    except Exception:
        return False


def _classify_value(node: ast.AST, clips: set, colls: set) -> str:
    """赋值右值分类：''（无关）/ 'clip'（片段 dict）/ 'coll'（片段容器）。"""
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                         ast.List, ast.Set, ast.Dict)):
        return "coll" if _refs_clips(node) else ""
    if isinstance(node, ast.Call):
        # next(...) / find_by_id 等返回单个 dict；list(...) 等返回容器
        fname = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else "")
        kind = "coll" if fname in ("list", "sorted", "tuple", "filter", "map") else "clip"
        return kind if _refs_clips(node) else ""
    if isinstance(node, ast.Subscript):
        base = node.value
        while isinstance(base, ast.Subscript):
            base = base.value
        if _refs_clips(node):
            return "clip"          # self._clips[i]
        if isinstance(base, ast.Name) and base.id in colls:
            return "clip"          # video_clips[0]
        return ""
    if isinstance(node, ast.Name):
        if node.id in clips:
            return "clip"
        if node.id in colls:
            return "coll"
        return ""
    if isinstance(node, ast.IfExp):
        kinds = {_classify_value(node.body, clips, colls),
                 _classify_value(node.orelse, clips, colls)}
        if "clip" in kinds:
            return "clip"
        return "coll" if "coll" in kinds else ""
    return ""


class _ScopeVisitor(ast.NodeVisitor):
    """单作用域（模块顶层或一个函数体）顺序污点扫描。

    近似数据流：赋值即重绑定（右值非 _clips 派生则清除污染）；
    ``for x in <引用 _clips 的表达式>`` 在循环体内令 x 成为 clip 污染；
    clip 变量的下标写 / ``.update()``、clip 容器的二级下标写 记为直写；
    容器自身的一级下标写（如 id→clip 索引表）属容器突变，不计。
    行尾带 ``# ratchet-exempt`` 的行豁免（须注释理由）。
    嵌套函数/Lambda 作用域由 _walk_scopes 单独扫描，避免重复计数。
    """

    def __init__(self, lines: list):
        self.clips: set = set()
        self.colls: set = set()
        self.lines = lines
        self.hits: list = []

    def visit_FunctionDef(self, node):
        return  # 嵌套作用域跳过（_walk_scopes 另行处理）

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def _exempt(self, lineno: int) -> bool:
        if 1 <= lineno <= len(self.lines):
            return EXEMPT_MARK in self.lines[lineno - 1]
        return False

    def _record(self, tgt: ast.AST, lineno: int, kind: str) -> None:
        if self._exempt(lineno):
            return
        depth = 0
        base = tgt
        while isinstance(base, ast.Subscript):
            depth += 1
            base = base.value
        if isinstance(base, ast.Attribute) and base.attr == "_clips":
            # self._clips[i]["k"] = v —— 直接下标写真相源
            self.hits.append((lineno, kind))
            return
        if not isinstance(base, ast.Name):
            return
        if base.id in self.clips:
            # clip 变量：任意深度下标写都是字段写
            self.hits.append((lineno, kind))
        elif base.id in self.colls and depth >= 2:
            # 容器元素的字段写：coll[i]["k"] = v
            self.hits.append((lineno, kind))

    def visit_Assign(self, node: ast.Assign) -> None:
        for tgt in node.targets:
            if isinstance(tgt, ast.Subscript):
                self._record(tgt, node.lineno, "subscript=")
                continue
            if isinstance(tgt, ast.Attribute):
                # 属性写（如 widget.clip_data = clip / self._current_clip = next(...)）
                # 不构成宿主名字的再绑定，否则 self/widget 会被误染成 clip
                continue
            names = [n.id for n in ast.walk(tgt) if isinstance(n, ast.Name)]
            kind = _classify_value(node.value, self.clips, self.colls)
            self.clips.difference_update(names)
            self.colls.difference_update(names)
            if kind == "clip":
                self.clips.update(names)
            elif kind == "coll":
                self.colls.update(names)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Subscript):
            self._record(node.target, node.lineno, "aug=")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        names = [n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)]
        loop_clip = _refs_clips(node.iter)
        saved_c = {n: (n in self.clips) for n in names}
        saved_k = {n: (n in self.colls) for n in names}
        self.clips.difference_update(names)
        self.colls.difference_update(names)
        if loop_clip:
            self.clips.update(names)
        for st in node.body + node.orelse:
            self.visit(st)
        self.clips.difference_update(names)
        self.colls.difference_update(names)
        for n, was in saved_c.items():
            if was:
                self.clips.add(n)
        for n, was in saved_k.items():
            if was:
                self.colls.add(n)
        # 不调 generic_visit：循环体已手动处理，避免重复计数

    def visit_Expr(self, node: ast.Expr) -> None:
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                and call.func.attr == "update":
            recv = call.func.value
            if isinstance(recv, ast.Name) and recv.id in self.clips \
                    and not self._exempt(node.lineno):
                self.hits.append((node.lineno, "update()"))
        self.generic_visit(node)


def _scan_scope(body: list, lines: list) -> list:
    v = _ScopeVisitor(lines)
    for st in body:
        v.visit(st)
    return v.hits


def _walk_scopes(tree: ast.AST, lines: list) -> list:
    """模块级与每个函数体分别做污点扫描（作用域隔离，避免同名误染）。"""
    hits = list(_scan_scope(tree.body, lines))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hits.extend(_scan_scope(node.body, lines))
    return hits


def scan_file(path: str, rel: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        return 0
    return len(_walk_scopes(tree, text.splitlines()))


def collect_counts() -> dict:
    counts = {}
    app_dir = os.path.join(ROOT, "app")
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            if rel in SKIP_REL or rel.startswith(TESTS_PREFIX):
                continue
            n = scan_file(full, rel)
            if n:
                counts[rel.replace("\\", "/")] = n
    return counts


# ── 接线在册（静态） ────────────────────────────────────────────────

def check_wiring() -> None:
    store_path = os.path.join(ROOT, "app", "core", "timeline_store.py")
    with open(store_path, "r", encoding="utf-8") as f:
        src = f.read()
    if "def set_fields(" not in src or "def update_where(" not in src:
        _fail("② 刀4 API 漂移：TimelineStore 缺少 set_fields/update_where")
    import re as _re
    if _re.search(r"^(import (?:PySide6|PyQt6|PyQt5)|from (?:PySide6|PyQt6|PyQt5))", src, _re.M):
        _fail("② timeline_store 顶层 import Qt（子进程红线）")
    from app.core.glue import policies
    for sym in ("set_fields", "update_where"):
        if not policies.is_declared_timeline_writer("app/core/timeline_store.py", sym):
            _fail(f"② glue 策略未登记字段写 API：{sym}")


def check_projection() -> None:
    """PROJECTION 断言（刀8 形态 A）：跨文件镜像重绑 `X._clips = ...`（X 非裸 self）硬零。

    镜像（TimelineWidget._clips）维护只许 timeline_widget.py 内部经
    reset_clips_projection / sync_clips_projection 进行；外部一律调 API，
    杜绝 `tw._clips =` / `self._timeline_widget._clips =` 式直绑回潮。
    """
    app_dir = os.path.join(ROOT, "app")
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            if rel.startswith(TESTS_PREFIX):
                continue
            try:
                with open(full, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=rel)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Attribute) and tgt.attr == "_clips" \
                                and not (isinstance(tgt.value, ast.Name)
                                         and tgt.value.id == "self"):
                            _fail(f"③ PROJECTION 跨文件镜像重绑：{rel}:{node.lineno} "
                                  f"（{ast.unparse(tgt)} = ...）——须改走 "
                                  f"reset_clips_projection/sync_clips_projection")


# ── CANONICAL 硬断言（刀9 真相源宣告收口） ──────────────────────────

#: 宿主行缓存唯一合法重绑文件（init 建列表一处，计数==1）
_EDITOR_REL = os.path.join("app", "modules", "lego", "editor_module.py")
#: 投影镜像自管文件（刀8 形态 A：reset/sync_clips_projection 内部维护，允许重绑/突变）
_WIDGET_REL = os.path.join("app", "modules", "lego", "timeline_widget.py")
#: store 本体豁免（合法原地突变实现层；现行为 _rows 命名，天然零命中，防御性登记）
_STORE_REL = os.path.join("app", "core", "timeline_store.py")
#: `_clips` 列表上的原地突变方法名（读型方法 index/count/copy 不计）
_MUT_METHODS = {"append", "extend", "insert", "pop", "remove", "clear", "sort", "reverse"}


def scan_canonical(path: str, rel: str) -> tuple:
    """单文件 AST 计数：``(self._clips = 重绑处数, _clips 原地突变处数)``。

    词边界沿用 ``_CLIPS_RE``：``new_clips``/``video_clips`` 等局部名与
    ``_clips_snapshot`` 等派生名均不误染；``getattr(x, "_clips", [])`` 读点
    不在 MUT_METHODS/下标写形态中，不误计。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=rel)
    except SyntaxError:
        return (0, 0)
    rebind = mutation = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in tgts:
                if isinstance(tgt, ast.Attribute) and tgt.attr == "_clips" \
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self":
                    rebind += 1
                elif isinstance(tgt, ast.Subscript) and _refs_clips(tgt):
                    mutation += 1
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr in _MUT_METHODS \
                    and _refs_clips(fn.value):
                mutation += 1
    return (rebind, mutation)


def check_canonical() -> None:
    """④⑤ 真相源收口钉死：宿主行缓存重绑仅 init 一处；store/镜像外原地突变全 app 硬零。"""
    app_dir = os.path.join(ROOT, "app")
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            if rel.startswith(TESTS_PREFIX):
                continue
            rebind, mutation = scan_canonical(full, rel)
            norm = rel.replace("\\", "/")
            if rel == _EDITOR_REL:
                if rebind != 1:
                    _fail(f"④ REBIND：editor_module.py `self._clips =` 重绑 {rebind} 处"
                          f"（真相源收口后仅 init 建列表一处允许，其余须走 store API）")
            elif rel == _WIDGET_REL:
                pass  # 投影镜像自管（形态 A 设计内）
            elif rebind:
                _fail(f"④ REBIND：{norm} 出现 `self._clips =` 重绑 {rebind} 处"
                      f"（宿主行缓存只许 editor_module init 创建）")
            if mutation and rel not in (_WIDGET_REL, _STORE_REL):
                _fail(f"⑤ MUTATION：{norm} 对 `_clips` 原地突变 {mutation} 处"
                      f"（结构写唯一入口 = TimelineStore.add/remove_by_id/replace_all/clear）")


def main() -> int:
    update = "--update" in sys.argv
    counts = collect_counts()
    if update:
        with open(BASELINE, "w", encoding="utf-8") as f:
            json.dump(counts, f, ensure_ascii=False, indent=2, sort_keys=True)
        total = sum(counts.values())
        print(f"OK  棘轮基线已重写：{len(counts)} 文件 / {total} 处直写")
        return 0
    if not os.path.exists(BASELINE):
        _fail(f"① 基线缺失：{os.path.relpath(BASELINE, ROOT)}（刀8 清零留痕文件）")
    # 刀9：棘轮比较升级为硬断言——基线 {} 固化后任何计数即 FAIL
    if counts:
        _fail(f"⑥ 字段直写硬零破防：{counts}（字段写必须走 "
              f"TimelineStore.set_fields/update_where，transform 系走 normalize/apply_normalized）")
    check_wiring()
    check_projection()
    check_canonical()
    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1
    print("PASS  时间线写入面 CANONICAL 硬断言达标：字段直写=0 / 宿主重绑仅 init / "
          "store 外突变=0 / 跨文件镜像重绑=0（刀9 真相源收口）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
