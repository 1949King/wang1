# -*- coding: utf-8 -*-
"""剪辑侧补全回归：语法校验 + 花字预设 + 曲线编辑器导入（只读）"""
import sys, os, ast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "app"))

FILES = [
    "app/plugins/transition_circle.py",
    "app/plugins/transition_vert.py",
    "app/plugins/transition_horz.py",
    "app/plugins/transition_cover.py",
    "app/plugins/transition_reveal.py",
    "app/plugins/transition_smooth.py",
    "app/core/transition_plugin_registry.py",
    "app/core/subtitle_manager.py",
    "app/modules/lego/editor_subtitle_panel.py",
    "app/modules/lego/editor_ui_builder_mixin.py",
    "app/modules/lego/editor_module.py",
    "app/modules/lego/keyframe_curve_editor.py",
]

bad = []
for rel in FILES:
    p = os.path.join(ROOT, rel)
    try:
        with open(p, "r", encoding="utf-8") as f:
            ast.parse(f.read())
        print(f"语法 OK: {rel}")
    except Exception as e:
        bad.append(rel)
        print(f"语法 FAIL: {rel} -> {e}")

# 花字预设
from core.subtitle_manager import SubtitleManager
sm = SubtitleManager()
presets = ["pop_yellow", "pop_white_red", "neon_pink", "neon_cyan",
           "big_white", "handwrite", "gold", "comic_impact"]
missing = [p for p in presets if p not in sm.subtitle_styles]
print(f"花字预设: {len(sm.subtitle_styles)} 个样式, 缺失={missing or '无'}")
print(f"样式总数 = {len(sm.subtitle_styles)} (期望 12)")

# 曲线编辑器导入（触发 keyframe_animation，不碰 config_manager）
try:
    from core.keyframe_animation import EasingType, InterpolationType
    print(f"keyframe_animation 导入 OK，缓动类型 {len(EasingType)} 种")
except Exception as e:
    print(f"keyframe_animation 导入 FAIL: {e}")

print("ALL OK" if not bad and not missing else "HAS FAIL")
sys.exit(0 if not bad and not missing else 1)
