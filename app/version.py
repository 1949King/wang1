"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.40.2"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 2,
    "codename": "整改 P1③：needs_log 静默异常补日志",
    "release_date": "2026-09-26",
    "description": (
        "V4.40.2: 实测整改方案 P1 第三项落地——check_glue_contract 判定的"
        " needs_log 静默 except 25 处全部处置：22 处补 logger.debug(...,"
        " exc_info=True)（14 文件，含 LLM 响应三级降级解析、提示词缓存读写、"
        " Provider 配置读取、导出代理路径检查、烘焙临时文件清理等状态机/"
        " 资源路径），3 处位于冻结区（canvas_bridge L144、"
        " character_management L793/847）转入待解冻队列。"
        "★ 5 文件补 logger 定义（editor_preview_ux/editor_timeline_tools/"
        " deformity_repair_skill/model_config/test_render_fallback）。"
        "★ 增量门禁拦下即清：15 文件存量 ruff 120 处全清——F401 死 import"
        " ×96（限定规则安全 --fix + 全量测试验证零破坏）、F811 函数内冗余"
        " re-import ×8（copywriting，顶部已有）、F841 死变量 ×7（逐个定性："
        " 有副作用的保留调用去赋值，纯死的删行）、F541/B009/RUF100/PIE810/"
        " B905 若干；canvas_runtime 可用性探测 import 加 noqa 保留"
        " （find_spec 会跳过模块初始化，行为不等价）。"
        "★ 纪律事件：P1-③ 中途误改 character_management_module.py"
        " （stage3d-core 整文件锁），守卫报漂移后立即全量回滚，"
        " 该文件 2 处 needs_log 转入待解冻队列。"
        "★ 稳定性门禁 269→249（清除 20 项存量静默）。"
        "★ 测试 383/383；ruff 15 文件全净；冻结区 85；粘合层 18/0；"
        " 双库无漂移。——至此整改 P1 全部落地（①②=V4.40.1，③=本版）。"
    ),
}
