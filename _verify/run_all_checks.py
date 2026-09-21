# -*- coding: utf-8 -*-
"""一键跑全部回归校验（按依赖/风险排序，任一项失败即非零退出）。

用法：
    python _verify/run_all_checks.py

说明：沙箱下 pytest 启动链会触发硬件探测被拦截，故本项目的校验脚本都是
「自包含可执行」的（直接 python 跑，不依赖 pytest）。
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _node() -> str:
    """定位 node：优先 PATH，其次托管版本（前端校验脚本是 .mjs，只能 node 跑）。"""
    found = shutil.which("node")
    if found:
        return found
    candidate = os.path.join(
        os.path.expanduser("~"), ".workbuddy", "binaries", "node",
        "versions", "22.22.2-3", "node.exe",
    )
    if os.path.isfile(candidate):
        return candidate
    return ""


CHECKS = [
    ("GUARD", "scripts/frozen_zone_guard.py", "冻结区"),
    ("SCHEMA", "_verify/check_character_schema.py", "角色字段五处同步"),
    ("PROMPT", "_verify/check_character_prompt.py", "字段流向"),
    ("MEMMODEL", "_verify/check_memory_model.py", "记忆衰减模型"),
    ("MEMSTR", "_verify/check_memory_strength.py", "记忆强度机制"),
    ("BRAINROUTE", "_verify/check_brain_routing.py", "大脑路由（学习回路）"),
    ("WRITECAP", "_verify/check_editor_write_capabilities.py", "Agent 写能力门槛 ≥8"),
    ("AGENTMAP", "_verify/check_agent_action_mapping.py", "Agent 动作表一致性"),
    ("CHARBLOCK", "_verify/check_char_prompt_block.mjs", "角色设定块幂等（Node）"),
    ("STORYMEM", "_verify/check_storyboard_memory.py", "分镜记忆规划（模型换算）"),
    ("GENJOBS", "_verify/check_generation_jobs.py", "生成任务表（异步/进度/取消/并发）"),
    ("PROJSNAP", "_verify/check_project_snapshot.py", "工程级快照（序列化/diff/回滚/直导）"),
    ("MAGLEVELS", "_verify/check_magnetic_levels.mjs", "磁吸等级 / 强度（前端纯函数）"),
    ("STAGE3D", "_verify/check_stage3d_scene.mjs", "3D 场景快照（Stage3D 配套）"),
    ("POSECACHE", "_verify/check_pose_thumb_cache.mjs", "数字人姿势元数据 + 缩略图 LRU"),
    ("STORYAPPLY", "_verify/check_storyboard_apply.py", "分镜记忆回灌（apply 落回 _clips）"),
    ("CANVASROUTES", "_verify/check_canvas_routes.py", "画布端点契约 + 不可达路由"),
    ("CANVASE2E", "_verify/check_canvas_bridge_e2e.py", "画布端点端到端（起真服务）"),
    ("CANVASDUAL", "_verify/check_canvas_dual_repo.py", "画布双库漂移"),
    ("COMFYIMP", "_verify/check_comfy_workflow_importer.py", "ComfyUI workflow 导入器（UI→graph 透传）"),
    ("AESPACK", "_verify/check_aesthetic_pack.py", "美学预设包（落盘/套用/写真相源）"),
    ("PROACTIVE", "_verify/check_proactive_suggestions.py", "Agent 主动建议引擎"),
    # ── 生成守护族（V4.33.x 引入，此前未登记进一键回归）──
    ("GUARDBASE", "_verify/check_guard_base.py", "守护共享基座"),
    ("TTSGUARD", "_verify/check_tts_guard.py", "TTS 多音字守护"),
    ("CHARANCHOR", "_verify/check_character_anchor.py", "角色跨镜头锚定"),
    ("EXPGUARD", "_verify/check_expression_guard.py", "表情幅度守护"),
    ("PROPGUARD", "_verify/check_prop_guard.py", "道具结构守护"),
    ("GUARDS", "_verify/check_guards.py", "守护门面（plan/negative 合并）"),
    ("GUARDPIPE", "_verify/check_guard_pipeline.py", "守护管线适配层"),
    ("GUARDINTEG", "_verify/check_guard_integration.py", "守护管线接线"),
    ("ACTIONWIRE", "_verify/check_action_wiring.py", "Agent 动作四点接线"),
    ("CTXBUDGET", "_verify/check_context_budget.py", "上下文预算（模型自适应）"),
    ("AGENTLOOPCTX", "_verify/check_agent_loop_context.py", "Agent 循环窗口压缩"),
    # ── 鲸影对照三件套（V4.35.0 P0-1/2/3）──
    ("PROPCAPS", "_verify/check_provider_caps.py", "能力声明 + 自动路由"),
    ("PROVIDERPOOL", "_verify/check_provider_pool.py", "额度池调度"),
    ("SCOREBOOK", "_verify/check_score_book.py", "评分回写闭环"),
    # ── 报价 + 健康（V4.36.0 P1-1/P1-2）──
    ("QUOTEHEALTH", "_verify/check_quote_health.py", "生成前报价 + 渠道健康"),
    ("PIPEJOBS", "_verify/check_pipeline_jobs.py", "管线异步任务（submit/status/cancel）"),
    ("SCOPE", "_verify/scan_nameerror_scope.py", "AST 作用域扫描（NameError 类硬缺陷）"),
    ("UNDOFB", "_verify/check_undo_feedback_llm_health.py", "撤销反馈回路 + LLM 降级指标"),
]

failed = []
for tag, rel, desc in CHECKS:
    path = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.exists(path):
        print(f"== {tag} == 缺失脚本 {rel}")
        failed.append(tag)
        continue
    if rel.endswith(".mjs"):
        runner = _node()
        if not runner:
            print(f"== {tag} == 找不到 node，跳过")
            failed.append(tag)
            continue
    else:
        runner = sys.executable
    proc = subprocess.run([runner, path], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    # 只看关键行：OK / ✗ / Traceback
    keep = [ln for ln in out.splitlines()
            if ln.strip().startswith(("OK", "✗", "Traceback", "Error", "error:"))
            or "frozen zones" in ln or "失败" in ln]
    print(f"== {tag} ({desc}) == exit={proc.returncode}")
    for ln in keep[-4:]:
        print("   ", ln.strip())
    if proc.returncode != 0:
        failed.append(tag)

print()
if failed:
    print(f"✗ 失败项: {', '.join(failed)}")
    sys.exit(1)
print(f"✓ 全部通过：{len(CHECKS)} 项")
