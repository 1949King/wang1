# -*- coding: utf-8 -*-
"""三向一致手工核对：catalog <-> dispatcher <-> 对话面 action（守卫只覆盖前两者）。
一次性脚本，跑完即删。
"""
import sys
import traceback

sys.path.insert(0, r"D:\拾光剪影")

CAP = "pipeline.tts_polish"
ACT = "tts_polish"

try:
    import app.core.agent_capability_catalog as cat
    import app.core.agent_action_registry as reg

    ids = set(cat.registered_capability_ids())
    print("1_catalog_has_cap:", CAP in ids)

    try:
        from app.core.capability_dispatcher import CapabilityDispatcher
        from app.core.capability_handlers import register_builtin_handlers

        d = CapabilityDispatcher()
        register_builtin_handlers(d)
        handlers = set(getattr(d, "_handlers", {}).keys())
        print("2_dispatcher_has_cap:", CAP in handlers)
        print("3_catalog_consistency_empty:", cat.verify_catalog_consistency(handlers) == [])
    except Exception:
        print("2_dispatcher_has_cap: SKIP(err)")
        traceback.print_exc()

    print("4_action_map_has:", ACT in reg.ACTION_TO_CAPABILITY)
    print("5_action_maps_to_cap:", reg.ACTION_TO_CAPABILITY.get(ACT) == CAP)
    print("6_allowed_actions_has:", ACT in reg.get_allowed_actions())
    print("7_prompt_line_has:", ACT in reg.build_agent_actions_prompt_line())
    print("8_help_block_has:", "tts_polish" in reg.build_agent_actions_help_block())
except Exception:
    traceback.print_exc()
