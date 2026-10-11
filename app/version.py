__version__ = "4.41.21"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 21,
    "codename": "小白意图入口（画布 0.3.20）",
    "release_date": "2026-10-11",
    "description": (
        "V4.41.20: 生成/入轨 浮层化 — 治「左侧栏最底下的「生成 / 入轨」高频入口放最深处、"
        "用户要滚半天找不到」（用户截图反馈）。\n"
        "\n【方案 C 落地】顶 navbar 在 💬 Agent 前加 🚀 生成/入轨 主入口；原侧栏块整段删除（137 行）；"
        "新建 GeneratePanel 浮层（5 号面板，与 history/lighting/director 并列，"
        "可拖动 / 双模式定位 / z 顺序数组 / 最小化到 dock / 头舵 ✕ 同源）；"
        "\n【自给自足】GeneratePanel 不吃 props：自己 Promise.all 拉 listImageModels/listVideoModels/listAudioModels，"
        "4 个 localStorage 键 shiguang-canvas:model:image|video|compare|compare-video 与原侧栏共享 — "
        "两边读同一个值，切回旧 UI 不丢选择；App→CanvasShell→Overlays→Panel 4 层 prop 污染归零。"
        "\n【9 个回调注入】App.tsx 一次 useInjectGenerateActions(9 个回调) 写入 zustand generateActionsStore，"
        "浮层 mount 时取 — 替代原 21 行 useEffect。"
        "\n【CanvasShell 瘦身】删 12 个 props + 12 个解构 + App.tsx 12 行 prop 传递 = 净减 26 行；"
        "音乐模型选择器保留（节点选中面板用到，未受影响）。"
        "\n【门禁】tsc 37=基线 0 新增 · vitest 291/291 · vite build 7.7s · frozen_zone_guard --update 重锁 85 锁点 · "
        "SIZE App.tsx 2006 → 1993 ✓ · CANVASDUAL 0 新分叉 0 新缺失（11 文件同步）。"
        "\n上一版 V4.41.19「AI 画布重组」见 docs/CHANGELOG.md。"
    ),
}
