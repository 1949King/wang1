__version__ = "4.43.5"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 5,
    "codename": "热修：外观卡动画节点 QColor 非法重载崩溃（真机渲染才暴露）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.5：热修 V4.43.4 的运行时崩溃（QColor 非法重载）\n"
        "\n【怎么发现的 —— 静态门禁全绿却真机崩】\n"
        "· V4.43.4 提交时 11 道门禁全过（ruff / frozen_zone / 规模守卫 / stability / tsc /\n"
        "  vitest / 双库 …），offscreen 启动也跑了 4 次全绿。但**真机启动（带显示器）后\n"
        "  10 秒开始疯狂刷屏 CRITICAL**：\n"
        "    File \"settings_widgets.py\", line 950, in _paint_animation_node\n"
        "      p.setBrush(QBrush(QColor(\"#ffffff\" if not is_light else \"#1a1a26\", 80)))\n"
        "    TypeError: arguments did not match any overloaded call:\n"
        "      QColor(name: str): too many arguments\n"
        "· 根因：**PyQt6 的 QColor 没有 `(name: str, alpha: int)` 这个重载**。合法写法只有\n"
        "  `QColor(name)` 单参（alpha 默认 255）或 `QColor(r,g,b,alpha)` 四整数。\n"
        "· 为什么门禁抓不到：① ruff 不做类型检查；② AST scope 扫的是「未定义名字」，\n"
        "  QColor 是已导入的合法名字；③ 没有单测覆盖 paintEvent 的运行时绘制；\n"
        "  ④ **offscreen 模式下设置对话框没被打开 ⇒ _PresetPreview.paintEvent 根本不触发**，\n"
        "  所以 offscreen 启动 4 次都没暴露。**只有真机（有 display）渲染才崩。**\n"
        "\n【修复】\n"
        "· 改用本文件已存在的 `_rgb(hexv, alpha)` helper（内部走 QColor(name) + setAlpha()）：\n"
        "    p.setBrush(QBrush(_rgb(\"#ffffff\" if not is_light else \"#1a1a26\", 80)))\n"
        "· 全项目用 AST 扫描 `QColor(<str>, ...)` 反模式 → **0 命中**（修复后已无同类）。\n"
        "\n【验证】\n"
        "· 修复后真机重启：30 秒运行 **0 个 TypeError / 0 个 paintEvent 崩溃**（对比修复前\n"
        "  10 秒即刷屏）。且能看到后续正常日志：canvas bridge 18765 / 静态服务 3011 /\n"
        "  WebEngineView created。\n"
        "· 门禁：ruff 存量棘轮 166 文件零新增（1 个收敛）/ frozen_zone 85 locks intact /\n"
        "  规模守卫无新增债务 / stability 250 无新增 / SCOPE 0 命中。\n"
        "\n【永久纪律（教训）】\n"
        "· **静态门禁全绿 ≠ 运行时没崩**。凡是自绘控件（QPainter/QColor/QPen）的改动，\n"
        "  交付前**必须真机启动**（不能只 offscreen），并且**打开那个界面**让 paintEvent\n"
        "  真的跑一遍。offscreen 会掩盖一切绘制类崩溃。\n"
        "· 记入 `docs/CHANGELOG.md` V4.43.5 与工作日志（2026-10-11）。\n"
        "\n【上一版 V4.43.4『外观页 1:1 复刻开源 2×2 大卡墙』见 docs/CHANGELOG.md。】"
    ),
}
