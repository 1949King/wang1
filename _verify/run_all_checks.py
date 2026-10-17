# -*- coding: utf-8 -*-
"""一键跑全部回归校验（按依赖/风险排序，任一项失败即非零退出）。

用法：
    python _verify/run_all_checks.py

跑哪个解释器：**自动优先项目 venv（.venv312）**，见 _python() 注释——
用系统 Python 跑会因缺 requirements.txt 里的依赖（如 pypinyin）误报失败。

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

# 把子进程的临时目录钉到项目内 .workbuddy/tmp（2026-09-27）：
# 沙箱拦截系统 Temp 写入 → tempfile 回退到 cwd（项目根），导致校验脚本把
# sg_*/cover_*/pip-* 等临时目录漏进仓库根。显式传 TMPDIR/TEMP/TMP 给子进程。
# .workbuddy/ 已在 .gitignore，落此处不会污染 git。
_TMP_BASE = os.path.join(ROOT, ".workbuddy", "tmp")
try:
    os.makedirs(_TMP_BASE, exist_ok=True)
except OSError:
    pass
_CHILD_ENV = dict(os.environ, TMPDIR=_TMP_BASE, TEMP=_TMP_BASE, TMP=_TMP_BASE)


def _python() -> str:
    """定位 python：**优先项目 venv**，其次当前解释器。

    为什么不能直接用 sys.executable（2026-10-05 血泪）：
    本机系统 Python 3.14 只装了 PyQt6，`pypinyin` / `psutil` 等 requirements.txt
    里的依赖都没有；用它跑校验会让 PINYIN / TTSGUARD 因「缺依赖」误报 FAIL，
    看起来像产品回归，其实是**跑错了解释器**。项目真实运行时是 .venv312
    （见「启动AI短剧编辑器.bat」回退链），校验必须跟它对齐。

    与 _node() 同一套路：优先项目内、其次 PATH、最后才是当前解释器。
    """
    for rel in ("venv312", ".venv312", "venv", ".venv"):
        for exe in ("Scripts/python.exe", "bin/python"):
            cand = os.path.join(ROOT, rel, exe.replace("/", os.sep))
            if os.path.isfile(cand):
                return cand
    return sys.executable


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
    ("YUECAP", "_verify/check_yue_capability.py", "YuE 能力四路接线 + 诚实失败纪律"),
    ("CHARBLOCK", "_verify/check_char_prompt_block.mjs", "角色设定块幂等（Node）"),
    ("STORYMEM", "_verify/check_storyboard_memory.py", "分镜记忆规划（模型换算）"),
    ("GENJOBS", "_verify/check_generation_jobs.py", "生成任务表（异步/进度/取消/并发）"),
    ("PROJSNAP", "_verify/check_project_snapshot.py", "工程级快照（序列化/diff/回滚/直导）"),
    ("MAGLEVELS", "_verify/check_magnetic_levels.mjs", "磁吸等级 / 强度（前端纯函数）"),
    ("STAGE3D", "_verify/check_stage3d_scene.mjs", "3D 场景快照（Stage3D 配套）"),
    ("POSECACHE", "_verify/check_pose_thumb_cache.mjs", "数字人姿势元数据 + 缩略图 LRU"),
    ("POSEDOF", "_verify/check_stage3d_pose_dof.mjs",
     "3D 姿势自由度（真 GLB 算关节世界坐标：内旋轴/前倾符号/自然垂手/万向节）"),
    ("LIGHT3D", "_verify/check_stage3d_lighting.mjs",
     "24 位灯位 → 3D 灯光（真 three 场景端到端：坐标系/色温/轮廓灯/优先级守卫）"),
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
    ("VIDEOEDIT", "_verify/check_video_edit_client.py",
     "指令式视频编辑：能力位/诚实拒绝/渠道顺序/失败保原镜"),
    # ── 报价 + 健康（V4.36.0 P1-1/P1-2）──
    ("QUOTEHEALTH", "_verify/check_quote_health.py", "生成前报价 + 渠道健康"),
    ("PIPEJOBS", "_verify/check_pipeline_jobs.py", "管线异步任务（submit/status/cancel）"),
    ("SCOPE", "_verify/scan_nameerror_scope.py", "AST 作用域扫描（NameError 类硬缺陷）"),
    ("UNDOFB", "_verify/check_undo_feedback_llm_health.py", "撤销反馈回路 + LLM 降级指标"),
    # ── 质量先验 + 收益选路（V4.37.4 规格书切片）──
    ("QPRIOR", "_verify/check_quality_prior_routing.py", "质量先验库 + 收益函数选路"),
    # ── 六级降级（V4.37.6 规格书切片③）──
    ("DEGRAD", "_verify/check_degradation.py", "六级降级体系 + L3 降质重试"),
    # ── PI 预算控制（V4.37.7 规格书切片④）──
    ("PACER", "_verify/check_budget_pacer.py", "PI 预算影子价格控制器"),
    # ── 六执行模式 + 可行集投影（V4.37.8 规格书切片⑤）──
    ("MODES", "_verify/check_execution_modes.py", "六种执行模式 + 可行集投影"),
    # ── A 模块分歧度探针（V4.37.9 规格书切片⑥）──
    ("PROBE", "_verify/check_divergence_probe.py", "A 模块分歧度探针"),
    # ── 融合器三分 + D 双路（V4.38.0 规格书切片⑦）──
    ("FUSION", "_verify/check_fusion.py", "置信度融合器三分 + D 双路执行体"),
    # ── L0 全局价格层 + 配额拍卖（V4.38.1 规格书切片⑧）──
    ("GPrice", "_verify/check_global_price.py", "L0 全局价格层 + 配额拍卖 + 观测门控"),
    # ── AI 辅助人工抽检子系统（V4.38.2 规格书切片⑨）──
    ("REVIEW", "_verify/check_sampling_review.py", "AI 辅助人工抽检子系统"),
    # ── 模块调度器 DAG（V4.38.3 规格书切片⑩）──
    ("MSCHED", "_verify/check_module_scheduler.py", "模块调度器 DAG 核心"),
    # ── 端到端仿真器（V4.38.4 规格书切片⑪）──
    ("SIM", "_verify/check_simulator.py", "端到端仿真器（零成本/可复现/故障注入）"),
    # ── 引擎接口规范 + 错误码（V4.38.5 规格书切片⑫）──
    ("EAPI", "_verify/check_engine_api.py", "引擎对外接口规范 + 错误码体系"),
    # ── 汉字注音字典 + 四处接线（V4.39.0）──
    ("PINYIN", "_verify/check_pinyin_dict.py", "汉字注音字典（离线确定性）+ 四处接线"),
    # ── 单文件规模守卫（V4.39.4）──
    ("SIZE", "_verify/check_file_size.py", "单文件规模守卫（存量冻结，只许减不许增）"),
    # ── clip↔画布生成参数血缘（智能时间线 P1，2026-10-17）──
    ("LINEAGE", "_verify/check_clip_lineage.py",
     "血缘契约：generation 抽取/盖章/索引 + 传输链与双库多处同步"),
    # ── 问题路由规则表（智能时间线 P1 / §6.9，2026-10-17）──
    ("ROUTER", "_verify/check_problem_routing.py",
     "问题路由判据：五维标记→segment_retake/video-edit/时间线内（纯函数+混合序列）"),
    # ── 小白闭环自动粗剪合链（§6.9-P2 方案 1，2026-10-17）──
    ("ROUGHCUT", "_verify/check_rough_cut_chain.py",
     "粗剪合链：确认后执行纪律/写回可撤销/别名回退/接线在册"),
    # ── 语义轨道原型（§6.9-P3 · 质量分/高光落 clip 元数据，2026-10-17）──
    ("SEMMETA", "_verify/check_clip_semantic.py",
     "clip 语义元数据：盖章契约/高光人工优先/found 区分/接线在册"),
    # ── 退出链路不变量（exit-media 冻结区的**语义**守卫，2026-10-11）──
    #    为什么需要：frozen_zone_guard 只比对哈希，能报「代码被改」却报不出
    #    「不变量被破」；实测有一次会话保存被插到 _stop_all_media_on_exit 之前，
    #    哈希报了漂移、不变量却静默失效。本项把三条不变量变成可执行断言。
    ("EXITMEDIA", "_verify/check_exit_media_invariant.py",
     "退出链路不变量（closeEvent 先停媒体 / cleanup release_source / mute+stop+清源）"),
    # ── 长对白 scrub 压测（报告 §6.1 补项，2026-09-27）──
    ("SCRUBPERF", "_verify/check_scrub_perf.py", "长对白 scrub 压测（命中查找层）"),
    # ── 路由 mixin 属性可解析性（A4 迁移踩坑后置守卫，2026-09-27）──
    ("ROUTEATTR", "_verify/check_canvas_route_attrs.py", "路由 mixin 的 cs.* 可解析"),
    # ── 抽卡账本（生成抽卡闭环 P3，2026-09-27）──
    ("GENLEDGER", "_verify/check_gen_ledger.py", "抽卡账本：往返/指纹/新鲜度/桶位隔离"),
    ("EDITUNDO", "_verify/check_editor_undo.py",
     "撤销覆盖（转场/贴纸）+ _apply_action 持锁 + 撤销栈互斥 + 孤儿已清"),
    ("LUTBAKE", "_verify/check_lut_export_bake_e2e.py",
     "LUT 导出烘焙真机验证（真跑 ffmpeg；ffmpeg 缺失时优雅跳过）"),
    ("PRELOAD", "_verify/check_preview_preload.py",
     "拖动静止后的定窗预载（接线/内存有界/防抖/死代码复活/冻结符号未动）"),
    ("OVERLAYS", "_verify/check_canvas_overlays.py",
     "画布浮层簇（接线/桌宠不随机动/状态真实驱动/形象资源轻量）"),
    ("COREIMP", "_verify/check_core_importable.py",
     "核心模块可导入性（version.py 语法 + import；防中文直引号事故）"),
    ("FIRSTRUN", "_verify/check_first_run_notice.py",
     "首启免责提示（入口接线/免责要点齐备/版本化重看/失败即显示/无内联样式）"),
    ("WINQUERY", "_verify/check_win_query.py",
     "WMI 统一（wmic 不再分散/指纹形状锁定/等价性测试在位）"),
    ("CANVASRUN", "_verify/check_canvas_run.py",
     "「运行到此处」接线（单一实现/默认只出计划/前端确认/契约登记）"),
    ("AGENTPOL", "_verify/check_agent_policy.py",
     "Agent 策略派生化（model-preload 双方法/单一真源/前端消费+保守兜底/端点真被调用）"),
    # ── 画布图执行 + 增量缓存接线（2026-09-28）──
    ("WFEXEC", "_verify/check_canvas_workflow.py", "画布图执行 + 增量缓存接线一致性"),
    # ── 画布端口模型（typed slots，前端真源 ↔ 后端镜像）（2026-09-28）──
    ("PORTMODEL", "_verify/check_port_model.py", "画布端口模型一致性 + 类型判据"),
    # ── 画布 selector 反模式（防 React #185 无限重渲染崩溃）（2026-10-14）──
    ("SELECTOR", "_verify/check_canvas_selectors.py", "画布 selector 新引用反模式（稳定引用 / useShallow）"),
    # ── 画布意图级增强层（能力升格成意图而非节点）（2026-09-30）──
    ("ENHANCE", "_verify/check_canvas_enhance.py", "意图级增强层：不泄漏模型名 + 诚实报告"),
    # ── 本地（Ollama）模型接线（2026-09-30）──
    ("LOCALMODEL", "_verify/check_local_model_wiring.py", "本地模型接线：画布可列出自部署模型"),
    # ── 本地视频生成接线（2026-10-01）──
    ("VIDEOGEN", "_verify/check_video_gen.py", "本地视频生成：镜像/免代理/Xet + 项目原生链路"),
    # ── pyqtSignal 参数类型（2026-10-09：ai_interpolation / highlight_preview 整模块 import 崩）──
    ("QTSTG", "_verify/check_qt_signal_types.py", "pyqtSignal 参数类型（防泛型别名致整模块 import 崩）"),
    # ── 素材不出域硬约束（2026-10-09）──
    ("POWERON", "_verify/check_poweron_e2e.py",
     "通电验证：换词重配五件套 / 拉片 / 重拍端点真可达（起真服务打 HTTP）"),
    ("EGRESS", "_verify/check_provider_egress.py", "素材不出域（SHIGUANG_NO_EGRESS 硬开关）"),
    # ── 配音听写回环验证（配音一致性方案 P1，2026-10-15）──
    ("DUBVERIFY", "_verify/check_dub_verify.py",
     "配音验证闭环（听写回环/字幕=音频/诚实降级 + 编排纯函数）"),
]

_py = _python()
print(f"# 校验解释器: {_py}"
      f"{'' if _py == sys.executable else '  （项目 venv，非当前解释器）'}")
print(f"# 当前解释器: {sys.executable}")
print(f"# 共 {len(CHECKS)} 项\n")

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
        runner = _python()
    proc = subprocess.run([runner, path], cwd=ROOT, env=_CHILD_ENV,
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
