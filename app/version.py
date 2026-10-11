__version__ = "4.41.19"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 19,
    "codename": "AI 画布重组（画布 0.3.18）",
    "release_date": "2026-10-11",
    "description": (
        "V4.41.19: AI 画布重组 —— 治「5 面板同屏 40+ 控件堆叠看着乱」"
        "（用户截图反馈，对标 8 款主流画布业界共识：左=库按类别分块 / 顶=全局单入口 / AI=单一入口）。"
        "\n【调研】8 款主流画布（Excalidraw/tldraw/Figma/Miro/MasterGo/TapNow/ComfyUI/剪映Hub）"
        "布局对比报告 docs/_reports/2026-10-11-AI画布布局调研与优化方案.md。"
        "\n【① 左 sidebar 5 大类】NodePalette.tsx 加 category 字段（创作/媒体/生成/空间/标注），"
        "CanvasShell 侧栏「添加节点」20+ 按钮平铺改分组折叠块（每组图标+计数），删除空类。"
        "\n【② Agent 入口 3→1】删右下 FAB 浮动按钮（与顶栏 💬 Agent、桌宠拾岚三重重复；"
        "桌宠 MutationObserver 本就在隐它，删本体后 no-op 无害）；保留顶栏 Agent + 桌宠 + 命令面板搜索项。"
        "\n【③ Ctrl+K 命令中枢 S5 雏形】命令面板 items 从 18 扩到 ~100："
        "节点分类直入（搜到即可加）+ Agent 工具直入（listProjectTools 一次拉 60 条，搜到跳 Agent 面板）。"
        "让 80% 的功能不需要直接暴露在界面上。"
        "\n【④ AgentPanel 工具 Tab 分组】80 行工具平铺改按 extension_type 自动分组折叠"
        "（数量多者优先，前 2 组默认展开，搜索时自动全展）；新建 agentPanel.css（styles.css 冻结区零增量）。"
        "\n【⑤ 4 tab 加图标】💬 对话 / 🧠 模型 / 🛠 工具 / 💰 预算；"
        "对话 Tab 模型选择包进可折叠块 sg-chat-section。"
        "\n【门禁】tsc 37=基线 0 新增 · vitest 291/291 · vite build 6.8s · "
        "frozen_zone_guard --update 重锁。"
        "\n上一版 V4.41.18「AgentOS S1 窗口管理」见 docs/CHANGELOG.md。"
    ),
}
