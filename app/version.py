__version__ = "4.43.13"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 13,
    "codename": "自动保存恢复提示重做（只在崩溃后弹 + 只弹一次 + 过期过滤）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.13：修「每次一开程序就弹恢复自动保存」\n"
        "\n【用户反馈原话】「每次一开程序它就给我弹出来提示我有之前的视频，问我是否要恢复，\n"
        "每次一打开就要。」（截图：发现 autosave/latest.timeline，修改时间 **2026-08-11**）\n"
        "\n【调研：各平台做法（官方文档）】\n"
        "· Adobe Premiere：只有 `quit unexpectedly`（异常退出）才弹；**dismiss 后不再弹**\n"
        "  （原文 \"won't appear again … the next time the application launches\"）。\n"
        "· Microsoft Office：**正常保存 / 正常关闭时删除** AutoRecover 文件 ⇒ 重启不打扰。\n"
        "· Final Cut Pro / DaVinci Resolve：无弹窗（Library 自动备份 / Project Manager 手动取）。\n"
        "· NightOS crashsave 规范：启动写 `awake` 标记 → **正常退出即删** → 残留即判崩溃。\n"
        "⇒ **业界共识 = 正常关闭要清理恢复数据，只有崩溃残留才提示。**\n"
        "\n【我们此前的三处缺陷】\n"
        "· ① **关闭时没有任何清理逻辑**（closeEvent / os.remove(autosave…) / 运行标记 一个都没有）\n"
        "  ⇒ autosave 永远留着 ⇒ 每次启动都弹；\n"
        "· ② `_autosave_prompted` 只是**内存变量**，进程重启即归零；\n"
        "· ③ 无「是否崩溃残留」判断 ⇒ 弹的是上次**正常保存**的副本。\n"
        "\n【修复（拆出独立模块，守规模基线）】\n"
        "· 新增 `app/modules/lego/autosave_recovery.py`（134 行，纯逻辑无 Qt 依赖、可单测）：\n"
        "  `begin_session()` 判定上次是否异常退出并写本次运行标记；`take_pending()` 过滤\n"
        "  「存档缺失 / 过期 / 已问过」；`mark_clean_exit()` 经 `atexit` 在**正常退出**时\n"
        "  删除标记（强杀/崩溃不触发 ⇒ 残留 ⇒ 正确判为崩溃）；`remember_prompted()` 记录\n"
        "  已询问版本。\n"
        "· `editor_module._maybe_restore_autosave()` 精简为**薄调用**（30 余行），\n"
        "  并删除临时的 `_mark_autosave_clean_exit`（已迁入新模块）。\n"
        "· **为什么拆**：原实现直接写在 editor_module 里会让该文件 9717 → 9803（+86，\n"
        "  容差仅 30）触发规模守卫；拆分后为 **9717 → 9740（+23，达标）** —— 这正是守卫\n"
        "  指引的「拆模块」正当解法。\n"
        "\n【验证（五场景实测）】\n"
        "      ① 全新启动（无存档）              → 不提示 ✅\n"
        "      ② **正常关闭后重启（有存档）**    → **不提示** ✅ ← 用户核心痛点\n"
        "      ③ 崩溃残留 + 新存档               → **提示** ✅ ← 该弹时才弹\n"
        "      ④ 已问过同一版本                  → 不提示 ✅\n"
        "      ⑤ 崩溃残留但存档过期 30 天        → 不提示 ✅\n"
        "  脚本 `.workbuddy/tmp/verify_autosave.py` → SUMMARY: ALL PASS。\n"
        "· 门禁：ruff 棘轮零新增 / 规模守卫**通过**（+23 ≤ 容差 30）/ frozen_zone 85 locks /\n"
        "  stability 250 / SCOPE 0 命中。\n"
        "\n【附带处置】\n"
        "· 现存那个 2026-08-11 的僵尸存档已改名为 `autosave/latest.timeline.bak_20260811`\n"
        "  （**保留备份、不删**），不会再被匹配、也不会再弹。\n"
        "\n【上一版 V4.43.12『通知中心补全主题样式』见 docs/CHANGELOG.md。】"
    ),
}
