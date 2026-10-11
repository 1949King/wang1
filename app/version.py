__version__ = "4.43.6"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 6,
    "codename": "画布白屏根治（Chromium --no-sandbox）+ 顶栏图标/底部按钮可读性",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.6：修「画布启动不了（白屏）」+ 首页三处看不清（用户截图圈定）\n"
        "\n【用户反馈原话】「图一中三个地方我圈了，用红线圈的地方你自己看一下，根本就看不清\n"
        "里面的内容，然后图二画布启动不了，你给我说解释一下什么情况。」\n"
        "\n【① 画布白屏 → 根治（本次最重要）】\n"
        "· 根因：QtWebEngine 内置 Chromium 在本机**沙箱起不来** → 进画布只有壳。\n"
        "  证据链：① 全库 grep `QTWEBENGINE_CHROMIUM_FLAGS` 在主程序侧**零设置**；\n"
        "  ② 前端状态行原话「画布页面加载完成（遭遇 断网）」；③ 启动日志\n"
        "  `canvas page loadFinished FAIL, retrying once`。\n"
        "· **决定性对照实验**（不依赖画布服务，直接加载 data: URL）：\n"
        "      不加 flags        → loadFinished ok=False\n"
        "      加 --no-sandbox   → loadFinished ok=True\n"
        "  ⇒ 确认与 3011/18765 服务无关，是沙箱层问题（与 2026-10-06 定案一致）。\n"
        "· 修复：`app/main_qt6.py` **模块顶层**（早于任何 QtWebEngine 导入）追加\n"
        "  `--no-sandbox` 到 QTWEBENGINE_CHROMIUM_FLAGS（追加而非覆盖，保留用户自定义\n"
        "  的其它 flags；已含则不重复加）。\n"
        "\n【② 顶栏 4 按钮看不清】\n"
        "· 根因：`#headerBarIconBtn` 的 QSS **根本不存在**（theme_manager 只有 #headerBar）。\n"
        "  三个图标按钮（🔔 通知 / 🎨 主题 / ⚙ 设置）因此走 Qt 默认样式，在深色底上发暗。\n"
        "· 修复：theme_manager 补 `#headerBarIconBtn`（+hover/+pressed）：透明底、\n"
        "  `text_primary` 前景、hover 时 accent 高亮 + 边框。\n"
        "\n【③ 底部 ComfyUI / MCP 卡的「设置」被压成「设」】\n"
        "· 根因：`home_sub_widgets.py` 里「⚙ 设置」按钮用了 `#toolBtn` —— 那是**圆形图标\n"
        "  按钮**（QSS 死锁 `max-width/max-height: 36px`），带文字必然被截断。\n"
        "· 修复：两处改用 `#ghostBtn`（自适应宽度，padding 6px 14px，与本卡「启动」按钮协调）。\n"
        "\n【验证】\n"
        "· 对照实验：data: URL 无 flags=Fail / 有 --no-sandbox=Ok（见上）。\n"
        "· 真机启动：banner 正常，主题切换正常，0 崩溃。\n"
        "· 门禁：ruff 棘轮 166 文件零新增 / frozen_zone 85 locks intact / 规模守卫无新增 /\n"
        "  stability 250 / SCOPE 0 命中 / run_all_checks 全绿 / pre-commit 11 道全过。\n"
        "\n【纪律延续】\n"
        "· V4.43.5 教训（静态门禁全绿 ≠ 运行时没崩）继续适用：UI / 绘制类改动一律真机启动\n"
        "  + 打开该界面才叫验证过。本版三处修复均按此标准。\n"
        "\n【上一版 V4.43.5『热修 QColor 非法重载崩溃』见 docs/CHANGELOG.md。】"
    ),
}
