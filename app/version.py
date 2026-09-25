"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.9"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 9,
    "codename": "优秀三件事②：基础调色全量 LUT 化",
    "release_date": "2026-09-26",
    "description": (
        "V4.39.9: 代码评价报告「距离优秀只差三件事」之第二件事落地——"
        "预览调色链（_apply_effects / _apply_effects_sync）逐点运算折叠为 256 项"
        "查找表，1080p 实测加速 2.31x（含饱和度）/ 3.61x（无饱和度），"
        "与旧链逐像素平价（≤1 LSB）。"
        "★ 条件化 LUT 架构（宁可慢，不可偏）：路径①饱和度/色相均未启用时"
        " 全链折叠为单表——输入恒为 uint8 无中间值损失，无条件 ≤1 LSB；"
        " 路径②亮度/对比度保持浮点（保护饱和度灰度耦合的无界中间值），"
        " 曝光/伽马/高光/阴影段由 _lut_entry_safe 门控（F(0)≤0 且 F(255)≥255"
        " 才 LUT，否则整段浮点回退）。"
        "★ 锐化整帧化：逐通道 filter2D 循环 → 单次整帧调用（多通道卷积"
        " 通道间独立，测试验证逐位一致）。"
        "★ 暗角遮罩模块级缓存（≤8 项，与帧内容无关），消除逐帧 ogrid+sqrt。"
        "★ 顺带修复两个潜在生产缺陷（均有测试记录）：负中间值经分数次幂"
        " 伽马产生 NaN → astype(uint8) 垃圾黑像素（LUT 入口裁剪后输出"
        " 定义的 0）；锐化 float→uint8 截断回绕（整帧路径行为一致）。"
        "★ 发现死参数：color_params 被 _normalize_effects 先行扁平化，"
        " 色温读取点恒为空——全应用零消费者，如实记录、未擅自接线。"
        "★ 测试：新增 app/tests/test_preview_lut.py 14 项（工人/同步两路"
        " 平价、锐化逐位、恒等、NaN 修复文档化、128 阈值间断带量化"
        " [固有非缺陷：0.73% 对抗噪声像素，带外 ≤2 LSB]、暗角公式平价、"
        " 1080p 基准断言新<旧），全绿；全量 358/358（连跑 4 次）。"
        "★ 顺带修复存量抖动用例 test_safe_import.py::test_attribute_missing"
        "_tries_alternate_path：替代路径 core.editor_scheduler 命中缓存时"
        " 属性完好导致 DID NOT RAISE（哈希种子/导入序相关），现预导入双路径"
        " 一并摘属性 + 结束还原 + 断言两路径均被尝试；并清理该文件 2 个及"
        " preview_manager.py 4 个存量死 import（grep 核实零引用）。"
    ),
}
