# -*- coding: utf-8 -*-
"""端到端回归：真起一个 canvas bridge 服务，用 HTTP 打关键端点（不是静态分析）。

不是静态分析 —— 这是「前面的工作」的真实验证：
  A. V4.14.4 路由表：/host/plugins/install|toggle|uninstall 之前是死代码（永远 404），
     现在必须真能装上、能改状态、能卸掉。
  B. V4.14.4 回落：路由表未命中时老 if 链必须照常工作（POST /host/tauri-closing）。
  C. V4.14.5 /host/characters 必须带 prompt 字段（含 visual 组全部 4 字段）。
  D. 未鉴权必须 401（别因为加了路由表就把鉴权绕过去）。
"""
import ast
import io
import json
import os
import sys
import tempfile
import time
import types
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROBE_ID = "e2e-probe"   # 测试用插件 id，finally 里强制清理
PORT = 18999
BASE = f"http://127.0.0.1:{PORT}"

# ── PySide6 在本沙箱不可用，给 /host/characters 打一个桩 ─────────────
# 只替换 CharacterStore，CHARACTER_FIELD_SCHEMA 从源码 AST 取真值，保证测得是真的。
tree = ast.parse(io.open(
    os.path.join(ROOT, "app", "modules", "lego", "character_management_module.py"),
    encoding="utf-8").read())
REAL_SCHEMA = None
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "CHARACTER_FIELD_SCHEMA":
        REAL_SCHEMA = ast.literal_eval(node.value)

stub = types.ModuleType("app.modules.lego.character_management_module")
stub.CHARACTER_FIELD_SCHEMA = REAL_SCHEMA


class _FakeStore:
    def all(self):
        return [{
            "id": "c_test", "name": "沈砚", "gender": "男", "age_range": "青年",
            "role_type": "主角", "tags": ["清冷"],
            "appearance": "白衣长发", "temperament": "清冷疏离",
            "memory_anchors": "左眼眼罩", "personality": "寡言",
            "core_desire": "不该进提示词",
        }]


stub.CharacterStore = _FakeStore
sys.modules.setdefault("app.modules.lego.character_management_module", stub)

import app.core.canvas_bridge as cb  # 先导入，避开循环导入
import app.core.canvas_server as cs

# 临时目录钉到项目内 .workbuddy/tmp（2026-09-28）：沙箱拦截系统 Temp 写入 ⇒
# tempfile.gettempdir() 回退到 cwd（项目根），直接单跑本脚本会把临时目录漏进仓库根。
# 规范入口 run_all_checks 已用 TMPDIR 传递；此处覆盖「直接单跑」路径。
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if "__file__" in globals() else os.getcwd(),
        ".workbuddy", "tmp",
    )
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

# 校验只读化：把画布插件清单重定向到临时目录。
# 直接跑生产路径会写 ~/.video_editor_cache/canvas_plugins.json（用户真实插件清单），
# 既污染环境，又在受限沙箱里 Permission denied 让 install/toggle/uninstall 假失败。
_TMP_PLUGINS_DIR = tempfile.mkdtemp(prefix="canvas_plugins_e2e_")
cb._CANVAS_PLUGINS_JSON = os.path.join(_TMP_PLUGINS_DIR, "canvas_plugins.json")

TOKEN = cs._SESSION_TOKEN

fails = []


def check(name, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + name + (("  " + detail) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def req(method, path, body=None, token=True, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        r.add_header("X-Shiguang-Token", TOKEN)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


srv = cs.CanvasBridgeServer("127.0.0.1", PORT)
print(f"启动 bridge @ {BASE} ...")
if not srv.start():
    print("✗ 启动失败")
    sys.exit(1)
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/health", timeout=1)
        break
    except Exception:
        time.sleep(0.1)

try:
    print("\n[A] V4.14.4 路由表：三个曾死的插件端点")
    code, js = req("POST", "/host/plugins/install", {
        "id": PROBE_ID, "name": "E2E探针", "version": "0.0.1", "nodes": ["shot"]})
    check("install 不再是 404", code == 200, f"code={code} body={js}")
    check("install 返回插件对象", isinstance(js, dict) and js.get("plugin", {}).get("id") == PROBE_ID, str(js)[:120])

    code, js = req("GET", "/host/plugins")
    plist = js.get("plugins") if isinstance(js, dict) else None
    hit = [p for p in (plist or []) if p.get("id") == PROBE_ID]
    check("GET /host/plugins 能查到刚装的", bool(hit), f"plugins={plist}")

    code, js = req("POST", "/host/plugins/toggle", {"id": "e2e-probe", "enabled": False})
    check("toggle 生效", code == 200 and js.get("enabled") is False, f"code={code} body={js}")

    code, js = req("POST", "/host/plugins/uninstall", {"id": PROBE_ID})
    check("uninstall 生效", code == 200 and js.get("ok") is True, f"code={code} body={js}")

    code, js = req("GET", "/host/plugins")
    plist = js.get("plugins") if isinstance(js, dict) else []
    check("卸载后确实没了", not [p for p in (plist or []) if p.get("id") == PROBE_ID], str(plist)[:160])

    print("\n[B] 路由表未命中必须回落老 if 链")
    code, js = req("POST", "/host/tauri-closing")
    check("老链端点 /host/tauri-closing 仍可用", code == 200, f"code={code} body={str(js)[:120]}")
    code, js = req("POST", "/host/definitely-not-exist")
    check("不存在的端点回 404", code == 404, f"code={code}")

    print("\n[C] V4.14.5 /host/characters 必须下发 prompt")
    code, js = req("GET", "/host/characters")
    ok = isinstance(js, list) and js and isinstance(js[0], dict)
    check("返回角色数组", ok, f"code={code} body={str(js)[:160]}")
    if ok:
        c = js[0]
        check("带 prompt 字段", "prompt" in c, f"keys={sorted(c)[:30]}")
        p = str(c.get("prompt") or "")
        for f in ("白衣长发", "清冷疏离", "左眼眼罩", "寡言"):
            check(f"prompt 含 visual 字段值「{f}」", f in p, p)
        check("inner 字段不进 prompt", "不该进提示词" not in p, p)
        check("schema 字段都在响应里", all(k in c for k, *_ in REAL_SCHEMA),
              f"缺={[k for k, *_ in REAL_SCHEMA if k not in c]}")
        print(f"     prompt = {p}")

    print("\n[E] V4.14.6 分镜记忆规划端点")
    body = {"rows": [
        {"id": "a", "memoryType": "detail", "duration": 3},
        {"id": "b", "memoryType": "meaning", "duration": 3},
        {"id": "c", "memoryType": "emotion", "duration": 3},
    ]}
    code, js = req("POST", "/host/storyboard-memory-plan", body)
    check("端点可达", code == 200, f"code={code} body={str(js)[:200]}")
    if code == 200 and isinstance(js, dict):
        by = {r["id"]: r for r in js.get("rows") or []}
        check("返回三行", len(by) == 3, str(js)[:200])
        check("保留率顺序 细节<意义<情绪",
              by["a"]["retention"] < by["b"]["retention"] < by["c"]["retention"],
              str({k: v["retention"] for k, v in by.items()}))
        check("细节让位 / 情绪拿时长",
              by["a"]["suggestedDuration"] < 3 < by["c"]["suggestedDuration"],
              str({k: v["suggestedDuration"] for k, v in by.items()}))
        check("总时长守恒 ≈ 9", abs(js.get("totalSuggested", 0) - 9.0) < 0.35,
              str(js.get("totalSuggested")))
    code, js = req("POST", "/host/storyboard-memory-plan", {"rows": "不是数组"})
    check("rows 非数组 → 400", code == 400, f"code={code}")
    code, js = req("POST", "/host/storyboard-memory-plan", {"rows": [], "t_hours": "x"})
    check("t_hours 非法 → 400", code == 400, f"code={code}")
    code, _ = req("POST", "/host/storyboard-memory-plan", {"rows": []}, token=False)
    check("无 token → 401", code == 401, f"code={code}")

    print("\n[D] 鉴权不能被路由表绕过")
    code, _ = req("POST", "/host/plugins/install", {"id": "x"}, token=False)
    check("无 token → 401", code == 401, f"code={code}")
    code, _ = req("POST", "/host/plugins/toggle", {"id": "x"}, token=False)
    check("toggle 无 token → 401", code == 401, f"code={code}")
    code, _ = req("POST", "/host/plugins/uninstall", {"id": "x"}, token=False)
    check("uninstall 无 token → 401", code == 401, f"code={code}")

    print("\n[F] V4.15.1 工程级快照端点（未注册 provider 时的诚实语义）")
    code, js = req("GET", "/host/project-snapshot/export")
    check("export 可达 200", code == 200, f"code={code} body={str(js)[:160]}")
    if code == 200 and isinstance(js, dict):
        check("export 返回 timeline", isinstance(js.get("timeline"), dict), str(js)[:160])
        check("export 未注册 provider 时 clips 为空数组", js.get("timeline", {}).get("clips") == [], str(js)[:160])
    code, js = req("POST", "/host/project-snapshot/import", {"clips": [{"id": "x", "path": "a.mp4", "start_time": 0, "duration": 3}]})
    # 沙箱无 writer 注册 → 诚实失败（ok:false），绝不假成功
    check("import 未注册 writer 诚实返回 ok:false", code == 500 and js.get("ok") is False, f"code={code} body={str(js)[:160]}")
    code, js = req("POST", "/host/project-snapshot/import", {"clips": "不是数组"})
    check("import clips 非数组 → 400", code == 400, f"code={code}")
    code, js = req("GET", "/host/project-snapshot/history")
    check("history 可达 200", code == 200 and isinstance(js.get("snapshots"), list), f"code={code} body={str(js)[:160]}")
    code, js = req("POST", "/host/project-snapshot/restore", {"snapshot_id": "不存在的快照"})
    check("restore 快照不存在 → 404", code == 404, f"code={code}")
    code, _ = req("GET", "/host/project-snapshot/export", token=False)
    check("export 无 token → 401", code == 401, f"code={code}")

    print("\n[G] V4.15.2 分镜记忆回灌校验：apply=true 落回 _clips")
    g_rows = [
        {"id": "a", "memoryType": "detail", "duration": 3},
        {"id": "b", "memoryType": "meaning", "duration": 3},
        {"id": "c", "memoryType": "emotion", "duration": 3},
    ]
    # 纯 plan（apply 不传）应只回 plan 字段，不应有 applied 字段
    code, js = req("POST", "/host/storyboard-memory-plan", {"rows": g_rows})
    check("纯 plan 端点 200", code == 200, f"code={code}")
    if code == 200 and isinstance(js, dict):
        check("纯 plan 必含 rows 字段（向后兼容）", isinstance(js.get("rows"), list), str(js)[:160])
        check("纯 plan 不应含 applied", "applied" not in js, str(js)[:160])
    # apply=true 但沙箱无 provider/writer → 端点应**走完 apply 分支**并诚实返回
    code, js = req("POST", "/host/storyboard-memory-plan", {"rows": g_rows, "apply": True})
    check("apply=true 端点 200（端点本身不炸）", code == 200, f"code={code}")
    if code == 200 and isinstance(js, dict):
        check("apply=true 必含 applied 字段", "applied" in js, str(js)[:160])
        applied = js.get("applied") or {}
        check("applied 字段 ok:false（沙箱无 writer 注册）", applied.get("ok") is False, str(applied))
        check("applied 字段 message 可读", isinstance(applied.get("message"), str) and bool(applied.get("message")), str(applied))
    # apply=true 但 rows=[] → 不应炸，applied 字段仍存在
    code, js = req("POST", "/host/storyboard-memory-plan", {"rows": [], "apply": True})
    check("apply=true + rows=[] 仍 200", code == 200, f"code={code}")
finally:
    # 强制清理：install 会往真实插件清单里写数据，无论断言成败都必须抹掉，
    # 否则回归跑多了会在用户磁盘上攒垃圾。
    try:
        req("POST", "/host/plugins/uninstall", {"id": PROBE_ID})
    except Exception:
        pass
    srv.stop()

print()
if fails:
    print(f"✗ {len(fails)} 项失败: {fails}")
    sys.exit(1)
print("OK 端点端到端全部通过")
