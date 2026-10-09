__version__ = "4.41.15"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 15,
    "codename": "横向工具板（画布底部 C 方案重做）",
    "release_date": "2026-10-10",
    "description": (
        "V4.41.15: 画布底部工具栏 C 方案重做（画布 0.3.13 → 0.3.14「横向工具板」）。"
        "\n【问题】用户实测截图定性：底部三套控件叠加（dock 一行 13 个无文字图标"
        " + 右下 ov-bar 4 胶囊 + ReactFlow 自带 Controls），缩放 3 处重复、"
        "历史 2 处重复，「排列混乱重叠、根本不知道是哪些」。"
        "\n【改】① LibTvBottomDock 重写：dock 收敛为 4 按钮"
        "（资产 / +添加 / ⊙缩放聚焦 / ⚡工具），其余全部收进「⚡工具」向上的"
        "横向工具板（视图/节点/数据/帮助 4 组并排、组内横排、图标+文字常显）；"
        "props 签名一字不动（冻结区 CanvasShell 零接口变更）。"
        "② 新建 toolboxStore.ts（zustand）：历史/灯位/导演指导/上游引用开关跨组件共享，"
        "工具板按钮与 CanvasOverlays 面板渲染同源；快捷键 Ctrl+H/L/D 改写 store 行为不变。"
        "③ 退役 ov-bar 浮层（CanvasOverlays -92 行、删 overlayBar.css），"
        "Agent 打开的让位/折叠逻辑随之消亡（dock 由 CanvasShell 布局管）。"
        "④ 删 ReactFlow <Controls />（CanvasShell 冻结区已授权改动，缩放走滚轮 + dock 聚焦）。"
        "⑤ 新样式全在独立 LibTvChrome.css（ltd-* 类名，styles.css 冻结区零触碰）。"
        "\n【门禁】tsc 37=基线、vitest 267/267、run_all_checks、双库校验全绿。"
        "\n上一版 V4.41.14「桌宠隐藏态」见 docs/CHANGELOG.md。"
    ),
}
