__version__ = "4.42.2"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 42,
    "patch": 2,
    "codename": "快捷键可视化（画布 0.3.22）",
    "release_date": "2026-10-11",
    "description": (
        "V4.42.2: 快捷键参考面板可视化重做（用户原话『图片里面反馈的就是可视化不足』）——\n"
        "\n【ShortcutSettings 弹窗】新建 vendor/shiguang-canvas/src/components/settings/ShortcutSettings.tsx（388 行）"
        "+ shortcut-settings.css（174 行），自包含 Modal 不依赖第三方组件。\n"
        "对比 AI-Canvas-tauri 24 行原版（每行只有一个 <div>+<kbd> 平铺），改进 4 处：\n"
        "① 4 分组卡片（编辑 / 节点创建 / 视图与导航 / 系统与资源）\n"
        "② 拟物键盘（圆角 + 渐变 + 上下投影 + 组合键真实排布，非『Ctrl+Z』字符串）\n"
        "③ 每行右侧触发预览 SVG（Ctrl+C = 两节点复制动效、Delete = trashcan、Ctrl+Shift+T = ☀↔☾）\n"
        "④ 顶部搜索实时过滤 + 显示『N/17 匹配』计数\n"
        "全部沿用 styles.css 的 [data-theme] 变量，主题切换实时生效。\n"
        "\n【触发入口】AppNav 顶栏在 theme-btn 左边加 [?] 按钮（与 ☀/☾ 视觉对齐，"
        "鼠标悬停提示『Ctrl+Shift+K』）+ useKeyboardShortcuts.ts 加 Ctrl+Shift+K 触发。\n"
        "快捷键序列设计：K = 命令面板 / Shift+K = 快捷键参考 = 同源 K 形成语义序列。\n"
        "Esc 关闭弹窗（与系统其它弹窗统一）。\n"
        "\n【冻结区纪律 canvas-magnetic-intent】本轮解冻改了 3 个登记文件 + 新建 2 个非冻结区文件：\n"
        "改：styles.css（+.ic-shortcut-btn 样式块，沿用 [data-theme] 分层）/ AppNav.tsx（+onOpenShortcuts prop + [?] 按钮）"
        "/ CanvasShell.tsx（+ShortcutSettings 渲染 + shortcutOpen 状态 + import）。\n"
        "新建：components/settings/ShortcutSettings.tsx + components/settings/shortcut-settings.css（均不在冻结区清单，新建不冲突）。\n"
        "useKeyboardShortcuts.ts 不在冻结区 files 清单（grep 验证），自由修改。\n"
        "frozen_zone_guard --update 重锁 → 85 locks intact。\n"
        "\n【CANVASDUAL 双库同步】cp 6 文件到 vendor/AI-Canvas-tauri/src/libtv/（含新建 components/settings/ 目录）"
        "→ check_canvas_dual_repo.py 0 新增漂移。\n"
        "\n【门禁】tsc 67 行错误全在 Stage3D.tsx/riggedHumanoid.ts（存量冻结区 stage3d-core），新文件 0 错误；\n"
        "vite build 6.23s / rc=0（main bundle 832.10 → 846.59 kB / +14.49 kB 是 ShortcutSettings 全量打入，"
        "后续可拆 lazy 优化 chunk）；vitest 仍 296/296（无新增测试文件）。\n"
        "\n【HTML 原型】docs/_reports/2026-10-11-快捷键可视化方案.html（35 KB · 单文件零依赖）"
        "= 用户拍板前的可视化方案（4 分组 + 拟物键帽 + 触发预览 + 搜索 + 主题切换 + 对比视图）。\n"
        "\n上一版 V4.42.1『通知中心面板 + 反馈通道』见 docs/CHANGELOG.md。"
    ),
}