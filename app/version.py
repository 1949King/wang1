__version__ = "4.43.9"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 9,
    "codename": "设置改回页内模块（方案 A：不再弹独立窗口）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.9：设置从「独立弹窗」改回「主界面内的页面」\n"
        "\n【用户反馈原话】「为什么顶部里面设登录的设置功能打开的是单独的一个窗口，而不是\n"
        "和项目整体挂钩的？」→ 用户选定方案 **A（变回页内模块）**\n"
        "\n【改动】\n"
        "· `main_window._show_settings()` 反转优先级：此前**先弹** `SettingsDialog`\n"
        "  （QDialog 独立窗口），失败才回落页内；现改为**直接**\n"
        "  `switch_to_module(\"settings\")` —— 点顶栏 ⚙ / 用户中心「设置」行，内容区切到\n"
        "  页内设置页，不再产生任何独立窗口。\n"
        "· `SettingsDialog` 退化为历史实现（保留代码以便一行回滚），设置**内容与页内模块\n"
        "  同源**（`build_appearance_top_block` 等共用），无数据差异。\n"
        "\n【为什么当初是弹窗】\n"
        "· V4.43.1 为对齐 AI Canvas 设置截图的形态，把 ⚙ 做成模态弹窗；V4.43.2 又把设置\n"
        "  从左侧导航撤出 ⇒ 只剩弹窗一条路，于是「设置 = 独立窗口」。本轮按用户裁定\n"
        "  改回页内（用户中心「设置」行同步生效，两处同源）。\n"
        "\n【验证】\n"
        "· `SettingsModule()` 离屏创建 OK（sizeHint 632×477），确认不从 `settings_module`\n"
        "  import `SettingsDialog`（页内模块自洽）。\n"
        "· ruff 存量棘轮 166 文件零新增 / frozen_zone 85 locks intact / 规模守卫无新增 /\n"
        "  stability 250 / SCOPE 0 命中 / run_all_checks 全绿 / pre-commit 11 道全过。\n"
        "\n【上一版 V4.43.8『解冻 stage3d-core 修工具栏可读性』见 docs/CHANGELOG.md。】"
    ),
}
