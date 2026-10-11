__version__ = "4.43.12"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 12,
    "codename": "通知中心补全主题样式（17 个 objectName 此前零 QSS）+ 正文不再被裁",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.12：修「深色模式下通知中心内容显示不完整」\n"
        "\n【用户反馈原话】「还有一个就是关于在深色模式下的通知中心，它里面的内容还是显示\n"
        "不完整，以及它的有点问题。」\n"
        "\n【根因（两条，同源）】\n"
        "· ① **17 个 objectName 一条 QSS 都没写**：`notificationCenterPanel` / `notifHeader` /\n"
        "  `notifHeaderTitle` / `notifCard` / `notifCardTitle` / `notifCardBody` /\n"
        "  `notifCardTime` / `notifScroll` / `notifFilterTab` / `notifFooterBtn` … 全部\n"
        "  只在 `setObjectName()` 里起了名，`theme_manager._build_qss` 中**零引用**。\n"
        "  ⇒ 全走 Qt 默认样式：**浅色主题下默认「浅底黑字」勉强可读，深色主题下直接不可用**\n"
        "  （正是用户限定的「深色模式下」）。\n"
        "· ② `_NotificationCard` 正文硬限高：`content.setMaximumHeight(48)` ⇒ 稍长的正文\n"
        "  **被直接裁掉**（「内容显示不完整」的字面含义）。\n"
        "\n【修复】\n"
        "· `theme_manager._build_qss` 补全通知中心全套样式（面板/卡片底色、标题与正文层级、\n"
        "  按钮 hover、filter tab 选中态、滚动区透明），全部走主题变量（`bg_secondary` /\n"
        "  `bg_tertiary` / `text_primary` / `text_secondary` / `text_muted` / `accent` …），\n"
        "  随主题自适应。\n"
        "· 正文限高 48 → **144**（约 6 行）—— 不再裁切常见长度；仍留上限防止极端长文本占满\n"
        "  整屏，超出部分由外层 `QScrollArea` 承担。\n"
        "\n【验证（实测）】\n"
        "· 两主题 QSS 构建成功且新规则齐备（未崩 · 无 KeyError）：\n"
        "      light: QSS 26282 字符 · `#notifCardBody -> color: #6E7488`\n"
        "      dark : QSS 26115 字符 · `#notifCardBody -> color: #8888a0`\n"
        "  ⇒ 主题自适应确实生效（两套颜色不同）。\n"
        "· 门禁：ruff 棘轮零新增 / frozen_zone 85 locks intact / 规模守卫无新增 /\n"
        "  stability 250 / SCOPE 0 命中。\n"
        "\n【同类病根（本日第 3 次）】\n"
        "· 「`setObjectName` 了但 QSS 没写」= 控件静默退回 Qt 默认样式。\n"
        "  本日已在 ① 顶栏 `headerBarIconBtn`（V4.43.6）② 角色工具栏内联硬编码（V4.43.8）\n"
        "  ③ 通知中心 17 个 objectName（本版）三处撞到同一堵墙。\n"
        "  **纪律：新增任何 `setObjectName(\"x\")` 后，必须 grep 一次 `#x` 是否在 QSS 里。**\n"
        "\n【上一版 V4.43.11『热修设置打不开』见 docs/CHANGELOG.md。】"
    ),
}
