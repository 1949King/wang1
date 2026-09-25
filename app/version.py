"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.40.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 0,
    "codename": "优秀三件事③：5 个真转场（ffmpeg 金标准对齐）",
    "release_date": "2026-09-26",
    "description": (
        "V4.40.0: 代码评价报告「距离优秀只差三件事」之第三件事（收官）落地——"
        "新增 5 个真转场插件：黑场/白场过渡、径向（时钟）擦除、对角擦除（4 方向）、"
        "翻页（带脊线阴影），预览与导出语义对齐。"
        "★ 金标准验证（不信文档，实测对齐）：抓 ffmpeg n9.0 vf_xfade.c 源码"
        " 推出公式 + fade 线性探针标定 P↔帧号 + 本机 ffmpeg 9.0 实际渲染逐像素"
        " 对比——radial/diag 预览公式与导出渲染 ≤4 LSB，注册 exact（导出走"
        " xfade 直出）；金标准测试常驻锁定 ≤6 LSB（radial + diag×4 方向）。"
        "★ 版本漂移诚实归类：fadeblack/fadewhite 的 n9.0 公式与本机二进制"
        " 实测不符（~13 LSB），改注册 bake（导出用预览同一份代码烘焙重叠窗"
        " ⇒ 预览==导出由构造保证，免疫版本漂移）；page 无 xfade 等价物同走"
        " bake，回退近似名在降级说明中如实标注。"
        "★ 反向映射锁定：ffmpeg diagtl/tr/bl/br 的命名角是「残留角」而非"
        " 「揭示起始角」（diagtl 的新画面从右下进入），插件 direction 到"
        " xfade 名做反转映射，注释+测试双重锁定。"
        "★ 注册表扩展：11 个中文标签（黑场/白场/径向/时钟擦除/对角/翻页…）、"
        " _PLUGIN_TO_XFADE、_DIAG_XFADE、_PAGE_XFADE、_EXPORT_FIDELITY、"
        " _KNOWN_XFADE 同步登记，映射表全员 ⊆ 本机 ffmpeg 实装 xfade 名单"
        " （测试硬编码 58 名核对）。"
        "★ 顺带修复存量地雷：根目录 core/__init__.py（初始提交遗留空包）在"
        " pytest 路径序下遮蔽 app/core，导致全部旧式 core.* 插件导入静默失败"
        " ——改为 __path__ 转发 shim，两种路径序均可解析。"
        "★ 踩坑记录：cv2.imread（4.11.0/Windows）打不开任何含中文的绝对路径"
        " （fopen 按 ANSI 解释），测试读取改 read_bytes+imdecode 绕过。"
        "★ 测试：新增 app/tests/test_transition_new_plugins.py 19 项全绿"
        " （注册发现/映射表核对/方向反转/精确度金标准/bake 架构/端点死区阴影）；"
        " 全量 377/377；ruff 全净；冻结区 85 锁；稳定性 269=269；"
        " 粘合层 18/0；双库无漂移。"
        "——至此评价报告「三件事」全部落地：① runGeneration(V4.39.8) "
        "② 调色 LUT(V4.39.9) ③ 真转场(V4.40.0)。"
    ),
}
