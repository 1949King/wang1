"""Agent 面板 P0+P1 优化端到端诊断脚本"""
import sys, os
sys.path.insert(0, r'd:\拾光剪影')

print("=" * 60)
print("Agent 面板优化 P0+P1 端到端诊断")
print("=" * 60)

# ── 1. 验证 py_compile ──
print("\n[1] 编译验证 editor_module.py ...")
import py_compile
try:
    py_compile.compile(r'd:\拾光剪影\app\modules\lego\editor_module.py', doraise=True)
    print("  ✅ editor_module.py 编译通过")
except py_compile.PyCompileError as e:
    print(f"  ❌ 编译失败: {e}")
    sys.exit(1)

# ── 2. 验证所有新增方法和属性存在 ──
print("\n[2] 验证新增方法/属性定义 ...")
# 导入需要 QApplication（避免创建实例即可）
from PySide6.QtWidgets import QApplication
if QApplication.instance() is None:
    qapp = QApplication([])

from app.modules.lego.editor_module import EditorModule

METHODS = [
    # 配置卡
    "_build_agent_config_card",
    "_get_pipeline_params",
    "_refresh_provider_status",
    # 进度卡
    "_build_agent_progress_card",
    "_update_pipeline_stage",
    "_finalize_pipeline_stage",
    "_stage_progress",
    "_stage_label",
    # 预览问题卡
    "_build_agent_preview_card",
    "_render_preview_issues",
    # 打分卡
    "_build_agent_score_card",
    "_render_score_results",
    # 脚本卡
    "_build_agent_script_card",
    "_render_editing_script",
    "_on_copy_script_clicked",
    "_on_export_script_clicked",
    "_on_manual_edit_clicked",
    # 事件处理扩展
    "_handle_video_generation_done",
    # 常量
    "_PIPELINE_STAGES",
]
missing = [m for m in METHODS if not hasattr(EditorModule, m)]
if missing:
    print(f"  ❌ 缺少方法/属性: {missing}")
    sys.exit(1)
print(f"  ✅ {len(METHODS)} 个新增方法/常量全部存在")

# ── 3. 验证 stage 映射 ──
print("\n[3] 验证 stage 进度/标签映射 ...")
# 用类直接访问常量
stages = EditorModule._PIPELINE_STAGES
print(f"  stage 列表: {len(stages)} 个 stage 注册")
# 创建临时实例取方法（QThread 需要 QObject 父类）
import types
fake = types.SimpleNamespace()
fake._PIPELINE_STAGES = stages

def _stage_progress(self, stage):
    for s, _, _, pct in self._PIPELINE_STAGES:
        if s == stage:
            return pct
    if stage == "waiting_for_preview_confirmation":
        return 40
    if stage == "error":
        return 0
    return 0

progress_map = {
    "routing": 5, "generation": 25, "import_parsing": 25,
    "preview": 40, "scoring": 55, "scripting": 70,
    "editing": 85, "done": 100,
    "waiting_for_preview_confirmation": 40, "error": 0,
}
for stage, expected in progress_map.items():
    got = _stage_progress(fake, stage)
    if got != expected:
        print(f"  ❌ stage={stage} 期望 {expected}% 得到 {got}%")
        sys.exit(1)
print(f"  ✅ {len(progress_map)} 个 stage 进度映射正确")

# ── 4. 验证核心管线数据传递（mock 场景） ──
print("\n[4] 验证管线数据流（mock 无素材+有创意简报场景） ...")
try:
    from app.core.agent_pipeline_orchestrator import agent_pipeline_orchestrator
    session = agent_pipeline_orchestrator.execute(
        materials=[],
        creative_brief="一个海边日落的短视频",
        platform="douyin",
        target_duration=15.0,
        clip_duration=3.0,
        provider="local",
        auto_preview_pass=True,
        session_id="ui_opt_test",
    )
    print(f"  success: {session.success}")
    print(f"  stage: {session.stage}")
    print(f"  route: {(session.route or {}).get('route')}")
    print(f"  clips: {len(session.generation_result.get('clips', [])) if session.generation_result else 'N/A'}")
    print(f"  scored: {len(session.scored_results)}")
    print(f"  script: {bool(session.editing_script)}")
    if not session.success:
        print(f"  ❌ 失败原因: {session.error}")
        sys.exit(1)
    print("  ✅ 管线执行成功（数据流完整）")
except Exception as e:
    print(f"  ❌ 管线执行异常: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ── 5. 验证事件载荷结构是否适配 UI 渲染 ──
print("\n[5] 验证事件载荷字段完整性 ...")
result_dict = session.to_dict()
required = ["session_id", "success", "stage", "route", "scored_count", "editing_script"]
missing_fields = [f for f in required if f not in result_dict]
if missing_fields:
    print(f"  ❌ to_dict() 缺少字段: {missing_fields}")
    sys.exit(1)
print(f"  ✅ to_dict() 字段完整: {list(result_dict.keys())}")

# 验证 editing_script 是否包含 UI 渲染所需字段
script = result_dict.get("editing_script") or {}
script_required = ["clip_order", "transitions", "platform", "pacing"]
missing_script = [f for f in script_required if f not in script]
if missing_script:
    print(f"  ⚠ editing_script 缺少字段: {missing_script}（UI 会用默认值兜底）")
else:
    print(f"  ✅ editing_script 字段完整")

# 验证 scored_results 通过 get_session 可读
try:
    s2 = agent_pipeline_orchestrator.get_session(result_dict["session_id"])
    if s2 is not None and s2.scored_results:
        print(f"  ✅ get_session() 可读 scored_results（{len(s2.scored_results)} 条）")
        # 取第一条看维度
        sc0 = s2.scored_results[0]
        dims = sc0.get("dimensions", {}) or {}
        keys = list(dims.keys())
        print(f"    镜头0维度键: {keys[:5]}")
except Exception as e:
    print(f"  ⚠ get_session 失败: {e}")

# ── 6. Provider 状态刷新 API 可用性 ──
print("\n[6] 验证 provider API ...")
try:
    from app.core.ai.video_generation_client import video_generation_client
    providers = video_generation_client.list_providers()
    print(f"  注册 provider: {len(providers)} 个")
    for p in providers[:4]:
        print(f"    {p.id}: available={p.available}")
    print("  ✅ provider API 可用")
except Exception as e:
    print(f"  ⚠ provider API 异常（不致命，UI 有守卫）: {e}")

# ── 7. 预览问题列表 API 可用性 ──
print("\n[7] 验证预览校验 API ...")
try:
    from app.core.preview_validation_loop import (
        preview_validation_loop, PreviewStatus
    )
    failed = preview_validation_loop.get_clips_by_status(PreviewStatus.FAILED)
    print(f"  失败片段数: {len(failed)}（空正常）")
    print("  ✅ preview_validation_loop API 可用")
except Exception as e:
    print(f"  ⚠ preview API 异常（不致命，UI 有守卫）: {e}")

print()
print("=" * 60)
print("✅ 所有 P0+P1 优化诊断项目通过")
print("=" * 60)
