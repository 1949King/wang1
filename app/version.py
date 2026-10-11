__version__ = "4.42.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 42,
    "patch": 0,
    "codename": "用户中心面板（顶 navbar 4 按钮）",
    "release_date": "2026-10-11",
    "description": (
        "V4.42.0: 顶 navbar Trae IDE 化 — 把「消息 / 主题 / 设置 / 帮助 / 反馈 / 检查更新 / 退出登录」"
        "统一上移到项目最顶上（main_window.py:797 headerBar），替代原「登录 / 激活」两个冷按钮。\n"
        "\n【落点】用户二轮反馈后明确：这是 PyQt6 主程序顶 navbar 改造，**非画布模块**。"
        "画布是项目里的一个模块，不能替代产品级个人中心。\n"
        "\n【方案落地】新建 app/modules/lego/user_center_panel.py（402 行 QFrame + QPoint Popup）"
        "— Trae IDE 风格 6 段下拉面板：① 头部·身份（首字母圆形头像 + 昵称 + VIP/普通徽章）"
        "② 通知中心·入口（未读徽章 + 检查更新）"
        "③ 设置（按用户要求置顶）"
        "④ 主题·帮助·反馈"
        "⑤ 退出登录（置底降级）"
        "⑥ 自动关闭（点击外部 / focusOut / ESC）。\n"
        "\n【headerBar 改造】main_window.py 右侧从「登录 + 激活」2 个按钮改为"
        "「🔔 通知 + 🎨 主题 + ⚙ 设置 + 👤 用户中心」4 个按钮（+19 行），"
        "通知/用户中心都触发 UserCenterPanel popup_below，主题按钮直接 toggle dark/light，"
        "设置按钮直接 _show_settings；11 个业务信号通过 pyqtSignal 接 main_window 既有方法"
        "（_on_login_clicked / _on_activate_clicked / _show_settings / _toggle_theme / "
        "_show_help / _on_feedback_clicked / _on_check_update_clicked / _on_logout_completed / "
        "_on_notifications_clicked / _on_register_clicked）。\n"
        "\n【信号复用】UserCenterPanel 不直接 import 任何业务模块（login_window / settings_module / "
        "update_manager 等），仅持有引用 + 发信号；main_window 在 _wire_user_center_signals 里接线。"
        "这样面板类零业务耦合，可独立单测。\n"
        "\n【主题同步】UserCenterPanel setProperty('theme', ...) + 属性选择器响应；"
        "main_window._on_theme_changed 触发 panel.on_theme_changed() 保持一致；"
        "ThemeManager.get_current_theme() 容错兜底，默认 'dark'。\n"
        "\n【纪律】零冻结区触碰（main_window.py 与 user_center_panel.py 均非冻结）；"
        "零 CANVASDUAL 影响（纯 Python 改动）；零新增 ruff 违规（新文件 All checks passed，"
        "main_window.py 12 项 = 基线 12）；sizeratchet 1653 行 ≤ 2000 阈值。"
        "画布版本不动（独立版本号）。\n"
        "\n【门禁】ruff 166 文件零新增违规 · sizeratchet 通过 · run_all_checks 75/75 全过"
        "（含 CANVASDUAL / WFEXEC / PORTMODEL / ENHANCE / LOCALMODEL / VIDEOGEN / "
        "QTSTG / POWERON / EGRESS）。\n"
        "\n上一版 V4.41.21「小白意图入口（P0）」见 docs/CHANGELOG.md。"
    ),
}