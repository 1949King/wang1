# -*- coding: utf-8 -*-
"""三向一致手工核对：catalog <-> dispatcher <-> 对话面 action（守卫只覆盖前两者）。
本轮核对四个守护能力：tts_polish / character_anchor / expression_clamp / prop_consistency。
"""
import sys
import traceback

sys.path.insert(0, r"D:\拾光剪影")

PAIRS = [
    ("pipeline.tts_polish", "tts_polish"),
    ("pipeline.character_anchor", "character_anchor"),
    ("pipeline.expression_clamp", "expression_clamp"),
    ("pipeline.prop_consistency", "prop_consistency"),
]

try:
    import app.core.agent_capability_catalog as cat
    import app.core.agent_action_registry as reg

    ids = set(cat.registered_capability_ids())
    handlers = set()
    try:
        from app.core.capability_dispatcher import CapabilityDispatcher
        from app.core.capability_handlers import register_builtin_handlers

        d = CapabilityDispatcher()
        register_builtin_handlers(d)
        handlers = set(getattr(d, "_handlers", {}).keys())
        print("dispatcher_ok: True")
        print("catalog_consistency_empty:", cat.verify_catalog_consistency(handlers) == [])
    except Exception:
        print("dispatcher_ok: False")
        traceback.print_exc()

    for cap, act in PAIRS:
        print(f"--- {cap} ---")
        print("  catalog_has:", cap in ids)
        print("  dispatcher_has:", cap in handlers)
        print("  action_map_has:", act in reg.ACTION_TO_CAPABILITY)
        print("  maps_to_cap:", reg.ACTION_TO_CAPABILITY.get(act) == cap)
        print("  allowed_has:", act in reg.get_allowed_actions())
        print("  prompt_line_has:", act in reg.build_agent_actions_prompt_line())
        print("  help_block_has:", act in reg.build_agent_actions_help_block())
except Exception:
    traceback.print_exc()
