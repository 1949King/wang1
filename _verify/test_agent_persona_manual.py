# -*- coding: utf-8 -*-
"""知心秘书（agent_persona + memory_store 召回）隔离验证。

用临时存储路径 + 清空内存态，避免污染真实 data/agent_memory.jsonl。
"""
import os
import sys
import tempfile

sys.path.insert(0, r"D:\拾光剪影")

import app.core.memory_store as ms

# ── 隔离：临时存储 + 清空内存态 ──
tmp = os.path.join(tempfile.gettempdir(), "persona_test_memory.jsonl")
if os.path.exists(tmp):
    os.remove(tmp)
ms._STORAGE_PATH = tmp
ms.memory_store._entries = ms.OrderedDict()

import app.core.agent_persona as ap

# ── 1. 默认态（lite + 无称呼）──
assert ap.get_nickname() == "", f"初始应无称呼，实得: {ap.get_nickname()!r}"
assert ap.is_persona_enabled() is False, "默认应关闭（lite）"
assert ap.has_persona_choice() is False, "默认应未做过选择"

hint = ap.build_persona_hint()
assert "语气提示" in hint, f"lite 档应含语气提示: {hint[:40]!r}"
assert ap.PERSONA_BLOCK not in hint, "lite 档不应含完整人格"
assert len(hint) < 200, f"lite 档应轻量，实际长度 {len(hint)}"

# ── 2. 自定义称呼 ──
assert ap.set_nickname("老王") is True, "set_nickname 应成功"
assert ap.get_nickname() == "老王", f"应读回老王，实得 {ap.get_nickname()!r}"
hint2 = ap.build_persona_hint()
assert "老王" in hint2, "lite 档也应注入称呼"

# 空称呼无效
assert ap.set_nickname("   ") is False, "空称呼应返回 False"

# ── 3. 开启完整档 ──
assert ap.set_persona(True) is True
assert ap.is_persona_enabled() is True, "开启后应返回 True"
assert ap.has_persona_choice() is True
hint3 = ap.build_persona_hint()
assert ap.PERSONA_BLOCK in hint3, "full 档应含完整人格"
assert "老王" in hint3, "full 档应含称呼"

g = ap.build_greeting()
assert "老王" in g, f"问候应含称呼: {g!r}"

# ── 4. 关闭后回 lite ──
assert ap.set_persona(False) is True
assert ap.is_persona_enabled() is False, "关闭后应回 lite"
assert ap.PERSONA_BLOCK not in ap.build_persona_hint(), "关闭后不应含完整人格"

# ── 5. get_agent_context 偏好召回 ──
ms.memory_store.record(
    category="user_preference",
    content={"key": "auto_note", "text": "我习惯先粗剪再精剪"},
    tags=["preference", "auto"], score=0.55,
)
ms.memory_store.record(
    category="user_preference",
    content={"key": "auto_note", "text": "我不喜欢随机效果"},
    tags=["preference", "auto"], score=0.55,
)

ctx_off = ms.memory_store.get_agent_context(top_k=5, include_preferences=False)
ctx_on = ms.memory_store.get_agent_context(top_k=5, include_preferences=True)
assert "用户偏好" not in ctx_off, "关闭时不应召回偏好"
assert "用户偏好" in ctx_on, "开启时应召回偏好"
assert "我不喜欢随机效果" in ctx_on, "应含偏好原文"
assert "agent_nickname" not in ctx_on, "称呼应被排除（单独注入）"

# ── 6. 偏好信号词检测（等价逻辑验证，不 import Qt mixin）──
markers = ap._PREFERENCE_MARKERS if hasattr(ap, "_PREFERENCE_MARKERS") else None
# 信号词定义在 mixin 里，这里直接验证核心判断逻辑
_markers = (
    "我喜欢", "我习惯", "我偏好", "我一般", "我通常", "我比较", "我更",
    "我不喜欢", "我讨厌", "我烦", "以后", "下次", "尽量", "最好",
)
def hit(t):
    return len(t.strip()) >= 4 and len(t.strip()) <= 80 and any(m in t for m in _markers)

assert hit("我习惯先粗剪再精剪") is True
assert hit("以后别加转场") is True
assert hit("把第一段剪掉") is False, "无信号词不应命中"
assert hit("好") is False, "太短不应命中"

# 清理临时文件
if os.path.exists(tmp):
    os.remove(tmp)

print("ALL_PERSONA_TESTS_OK")
