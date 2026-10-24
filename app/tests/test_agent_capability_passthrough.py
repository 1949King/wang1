# -*- coding: utf-8 -*-
"""Agent 全能力可达刀行为锁（V4.46.2）。

锁三件事：
1. 裸 capability_id 直通判定：只认「目录里真实存在」的 id；
2. 只读直通能力不误进 B 勾选分区（partition extra_reads）；
3. 全能力目录清单进 help block（模型看得见 126 个 id，不再只见 45）。
"""
import pytest

from app.core.agent_action_registry import (
    build_agent_actions_help_block,
    build_catalog_capabilities_line,
)
from app.modules.lego.ai_agent_panel import (
    _AGENT_ALLOWED_ACTIONS,
    _capability_passthrough,
    is_readonly_capability,
)
from app.modules.lego.suggest_checklist import partition_agent_commands


class _Cmd:
    def __init__(self, action):
        self.action = action


def test_passthrough_accepts_registered_capability():
    assert _capability_passthrough("editor.precision_audit") == "editor.precision_audit"


def test_passthrough_rejects_unknown_and_legacy_actions():
    assert _capability_passthrough("editor.not_a_real_capability") == ""
    assert _capability_passthrough("add_clip") == ""          # 无点分前缀
    assert _capability_passthrough("editor.evil_prefix_guess") == ""  # 有前缀但未注册
    assert _capability_passthrough("") == ""


def test_readonly_capability_judgement():
    assert is_readonly_capability("editor.precision_audit") is True
    assert is_readonly_capability("editor.precision_align_apply") is False  # 写类
    assert is_readonly_capability("ripple_delete_range") is False  # 老 action 不受影响


def test_partition_extra_reads_moves_readonly_caps_out_of_confirm():
    cmds = [_Cmd("ripple_delete_range"), _Cmd("editor.precision_audit")]
    reads, writes = partition_agent_commands(cmds, extra_reads=is_readonly_capability)
    assert [c.action for c in reads] == ["editor.precision_audit"]
    assert [c.action for c in writes] == ["ripple_delete_range"]
    # 不传 extra_reads ⇒ 行为与旧版逐字节等价（能力直通会被当写，保守正确）
    r0, w0 = partition_agent_commands(cmds)
    assert [c.action for c in w0] == ["ripple_delete_range", "editor.precision_audit"]


def test_catalog_line_covers_full_capability_dir():
    line = build_catalog_capabilities_line()
    assert line, "清单生成失败（catalog 结构变了？守卫会静默降级，这里必须报警）"
    from app.core.agent_capability_catalog import registered_capability_ids

    for cid in registered_capability_ids():
        assert cid in line, f"清单漏了 {cid}"


def test_help_block_opens_capability_door_keeps_bans():
    hb = build_agent_actions_help_block()
    assert "[全能力目录]" in hb
    assert "禁止生成 add_clip / import_media" in hb       # 禁令仍在
    assert not hb.startswith("严格只使用下列 action")       # 封闭语义已放开
    # 45 白名单未缩：原有常用 action 全在
    for a in _AGENT_ALLOWED_ACTIONS:
        assert a in hb
