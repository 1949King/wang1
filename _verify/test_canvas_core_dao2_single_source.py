# -*- coding: utf-8 -*-
"""刀2 单一真源抽取回归测试（LibTV 对标补强，2026-10-12）

覆盖（不依赖 LLM/网络 —— AIEngine 用 stub 替换，行为等价验证）：
  A. script_writer.write_script：LLM 正常路径（stub）→ script/fallback=False；
     LLM 空 回报 → 模板降级 fallback=True 如实标注。
  B. DirectorSkill._generate_script 薄委托：用户自带剧本直通；LLM 路径变量同步。
  C. director_timeline.apply_storyboard_to_timeline 四场景
     （与 test_director_timeline_apply.py 同断言语义，直测引擎函数）：
     C1 有素材+有订阅者 → applied=True，载荷=分镜数，source 标签如实
     C2 目录不存在 → applied=False
     C3 目录无视频 → applied=False
     C4 有素材无订阅者 → applied=False（不发事件，防静默丢失）
  D. DirectorSkill._apply_to_timeline 薄委托：变量 timeline_applied/note 如实回写。
  E. 目录两行新能力登记（effect/paid 与设计一致）。

运行：python _verify/test_canvas_core_dao2_single_source.py
产物：_verify/out_libtv_dao2.json
"""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 临时目录钉到项目内 .workbuddy/tmp：沙箱拦截系统 Temp 写入（同 test_director_timeline_apply）
try:
    _SG_TMP = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".workbuddy", "tmp")
    os.makedirs(_SG_TMP, exist_ok=True)
    tempfile.tempdir = _SG_TMP
except OSError:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_libtv_dao2.json")

results = {"cases": {}, "assertions": []}


def check(name, cond, detail=""):
    results["assertions"].append(
        {"name": name, "ok": bool(cond), "detail": str(detail)[:300]})
    return bool(cond)


# ── A/B：script_writer + DirectorSkill._generate_script ─────────────
# 先把 app.core.ai_engine 换成 stub（write_script 在函数体内 import，时机可控）：
#   不 import 真模块 ⇒ 不触发云端配置探测/解密，测试离线确定性。
class _StubEngine:
    MODE = "llm"

    def chat_with_fallback(self, messages, template=None):
        if _StubEngine.MODE == "llm":
            yield "【场景1】LLM 测试剧本：一段测试内容。"
        else:
            yield ""


_fake_ai = types.ModuleType("app.core.ai_engine")
_fake_ai.AIEngine = _StubEngine
sys.modules["app.core.ai_engine"] = _fake_ai

from app.core.ai.script_writer import write_script

res_a1 = write_script("测试主题")
check("A1.llm_path", res_a1.get("script", "").startswith("【场景1")
      and res_a1.get("fallback") is False and res_a1.get("source") == "llm",
      res_a1)

_StubEngine.MODE = "empty"
res_a2 = write_script("测试主题")
check("A2.template_fallback_honest", res_a2.get("fallback") is True
      and res_a2.get("source") == "template"
      and "测试主题" in res_a2.get("script", ""),
      {k: (v[:30] if isinstance(v, str) else v) for k, v in res_a2.items()})

from app.modules.lego.director_skill import DirectorSkill


class _FakeContext:
    def __init__(self, inputs):
        self._in = inputs
        self.vars = {}

    def get_input(self, k, d=None):
        return self._in.get(k, d)

    def get_variable(self, k, d=None):
        return self.vars.get(k, d)

    def set_variable(self, k, v):
        self.vars[k] = v


_StubEngine.MODE = "llm"
skill = DirectorSkill()
ctx_b1 = _FakeContext({"script": "用户自带剧本内容"})
sr_b1 = skill._generate_script(ctx_b1)
check("B1.user_script_passthrough",
      ctx_b1.vars.get("script") == "用户自带剧本内容"
      and sr_b1.output.get("source") == "user", sr_b1.output)

ctx_b2 = _FakeContext({"topic": "代理主题", "source_dir": "D:/x", "use_blender": True})
sr_b2 = skill._generate_script(ctx_b2)
check("B2.llm_vars_sync",
      ctx_b2.vars.get("script", "").startswith("【场景1")
      and ctx_b2.vars.get("topic") == "代理主题"
      and ctx_b2.vars.get("script_is_template") is False
      and ctx_b2.vars.get("_source_dir") == "D:/x"
      and ctx_b2.vars.get("_use_blender") is True, ctx_b2.vars)

# ── C：director_timeline.apply_storyboard_to_timeline 四场景 ────────
from app.modules.lego.core import EventBus, EventType
from app.core.ai.director_timeline import apply_storyboard_to_timeline

media_dir = tempfile.mkdtemp(prefix="dao2_media_")
for i in range(2):
    with open(os.path.join(media_dir, f"shot{i}.mp4"), "wb") as fh:
        fh.write(b"\x00" * 16)
empty_dir = tempfile.mkdtemp(prefix="dao2_empty_")

STORYBOARD = [{"id": 1, "description": "开场远景"}, {"id": 2, "description": "主体特写"},
              {"id": 3, "description": "收尾定格"}]
received = []
bus = EventBus.get_instance()
_listener = lambda e: received.append(e.data)
bus.on(EventType.MATERIAL_TO_TIMELINE, _listener)

res_c1 = apply_storyboard_to_timeline(media_dir, STORYBOARD, source_tag="dao2_test")
check("C1.applied", res_c1.get("applied") is True, res_c1)
check("C1.clips_match_shots", res_c1.get("clips") == 3, res_c1)
check("C1.event_payload",
      len(received) == 1 and received[0].get("source") == "dao2_test"
      and len(received[0].get("clips", [])) == 3
      and all(os.path.exists(c.get("path", "")) for c in received[0].get("clips", [])),
      received[:1])
# 分镜 3 个 > 素材 2 个 ⇒ 循环复用
check("C1.cyclic_mapping",
      len({c["path"] for c in received[0]["clips"]}) == 2, received[0]["clips"])

res_c2 = apply_storyboard_to_timeline("D:/不存在目录xyz", STORYBOARD)
check("C2.dir_missing", res_c2.get("applied") is False
      and "素材目录不存在" in str(res_c2.get("reason")), res_c2)

res_c3 = apply_storyboard_to_timeline(empty_dir, STORYBOARD)
check("C3.no_media", res_c3.get("applied") is False
      and "没有可用视频文件" in str(res_c3.get("reason")), res_c3)

bus.off(EventType.MATERIAL_TO_TIMELINE, _listener)
res_c4 = apply_storyboard_to_timeline(media_dir, STORYBOARD)
check("C4.no_listener_honest", res_c4.get("applied") is False
      and "剪辑模块未打开" in str(res_c4.get("reason"))
      and len(received) == 1,  # 4 场景不发新事件
      res_c4)

# ── D：DirectorSkill._apply_to_timeline 薄委托变量回写 ────────────────
bus.on(EventType.MATERIAL_TO_TIMELINE, _listener)
try:
    ctx_d = _FakeContext({})
    ctx_d.vars["_source_dir"] = media_dir
    ctx_d.vars["storyboard"] = STORYBOARD
    sr_d = skill._apply_to_timeline(ctx_d)
    check("D.vars_written", ctx_d.vars.get("timeline_applied") is True
          and "3 段素材" in str(ctx_d.vars.get("timeline_apply_note"))
          and sr_d.output.get("applied") is True, ctx_d.vars)

    ctx_d2 = _FakeContext({})
    ctx_d2.vars["_source_dir"] = "D:/不存在目录xyz"
    ctx_d2.vars["storyboard"] = STORYBOARD
    skill._apply_to_timeline(ctx_d2)
    check("D.skip_vars_written", ctx_d2.vars.get("timeline_applied") is False
          and "素材目录不存在" in str(ctx_d2.vars.get("timeline_apply_note")),
          ctx_d2.vars)
finally:
    bus.off(EventType.MATERIAL_TO_TIMELINE, _listener)

# ── E：目录登记（effect/paid 与设计一致）────────────────────────────
from app.core.agent_capability_catalog import capability_effect_paid

effects = capability_effect_paid()
check("E.script_write_row", effects.get("pipeline.script_write") == ("read", True),
      effects.get("pipeline.script_write"))
check("E.director_apply_row",
      effects.get("pipeline.director_apply_timeline") == ("canvas_write", False),
      effects.get("pipeline.director_apply_timeline"))

results["cases"] = {
    "A1_source": res_a1.get("source"),
    "A2_source": res_a2.get("source"),
    "C1_note": res_c1.get("note"),
    "C4_reason": res_c4.get("reason"),
}
ok_all = all(a["ok"] for a in results["assertions"])
results["ALL_PASS"] = ok_all

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

print("ALL_PASS" if ok_all else "FAIL")
for a in results["assertions"]:
    print(("PASS " if a["ok"] else "FAIL ") + a["name"] + " :: " + a["detail"])
sys.exit(0 if ok_all else 1)
