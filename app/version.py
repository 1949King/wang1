__version__ = "4.42.1"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 42,
    "patch": 1,
    "codename": "通知中心面板 + 反馈通道",
    "release_date": "2026-10-11",
    "description": (
        "V4.42.1: 把 V4.42.0 的两处 status bar 占位换成真实组件——\n"
        "\n【通知中心面板 NotificationCenterPanel】新建 app/modules/lego/notification_center_panel.py（499 行 QFrame+Popup）"
        "挂在 headerBar 🔔 按钮下方弹出；6 段布局：头部（标题+全部已读+关闭）/ 过滤标签（全部/系统/更新/反馈/告警）"
        "/ 列表（QScrollArea + _NotificationCard，每条：级别图标+标题+正文+类型标签+时间+删除）"
        "/ 空状态 / 底部（清空全部+检查更新+意见反馈）。\n"
        "\n【数据契约 NotificationStore】新建 app/core/notification_store.py（336 行）"
        "单例 + JSON 持久化（user_data_dir/notifications.json）+ 线程安全 RLock；"
        "5 类 TYPE_SYSTEM/TYPE_UPDATE/feedback/alert/info，4 级 severity（info/success/warning/error）；"
        "deque(maxlen=500) FIFO 限额；callback 机制（add/mark_read/delete/clear 后通知 UI）。\n"
        "\n【反馈对话框 FeedbackDialog】新建 app/modules/lego/feedback_dialog.py（284 行 QDialog 模态）"
        "5 类（问题反馈/功能建议/Bug 报告/内容合规/其他）+ 3 级严重度（普通/重要/紧急）+ 选填邮箱 + 必填描述；"
        "提交路径：① 永远写 notification_store（type=feedback, level=severity）；"
        "② 选走 Webhook POST（QSettings.feedback/webhook_url，10 秒超时，失败不阻断）；"
        "③ 状态条兜底展示结果。\n"
        "\n【main_window 接线】替换 _on_notifications_clicked 占位 → _popup_notification_center 单例懒加载；"
        "替换 _on_feedback_clicked 占位 → _popup_feedback_dialog.exec()；"
        "_on_check_update_clicked 增加『开始检查更新』消息写入 notification_store 给用户视觉反馈；"
        "NotificationCenterPanel 内 feedback_requested/check_update_requested 信号回连 main_window 入口避免重复代码。\n"
        "\n【徽章源改造】UserCenterPanel._refresh_update_hint 从 update_manager.get_current_info() 改为"
        "notification_store().unread_count()；新增 refresh_unread_badge() 公开方法；"
        "main_window._refresh_user_badge 接 4 个信号（mark_all_read/clear_all/delete/item_clicked）"
        "双向同步。\n"
        "\n【纪律】零冻结区触碰（notification_center_panel/feedback_dialog/notification_store 均非冻结）；"
        "零 CANVASDUAL 影响（纯 Python 改动）；零新增 ruff 违规（3 新文件 All checks passed，"
        "user_center_panel.py 0 新增）；sizeratchet 通过（新文件 499+284+336 ≤ 2000）；"
        "main_window.py 12 项 = 基线 12（存量棘轮只减不增）。"
        "画布版本不动（独立版本号）。\n"
        "\n【门禁】ruff 166 文件零新增 · run_all_checks 75/75 全过 · size ratchet 通过。\n"
        "\n上一版 V4.42.0『用户中心面板（顶 navbar 4 按钮）』见 docs/CHANGELOG.md。"
    ),
}