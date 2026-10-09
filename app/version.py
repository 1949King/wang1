__version__ = "4.41.16"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 16,
    "codename": "工具补全（图库/时序预览/撤销重做 · 画布 0.3.15）",
    "release_date": "2026-10-10",
    "description": (
        "V4.41.16: 工具板三个占位功能补全为真功能（画布 0.3.14 → 0.3.15「工具补全」）。"
        "\n【① 图库】此前只弹统计文字 → 新建 GalleryPanel：画布全部有产物的"
        "图片/视频节点缩略图网格（视频用首帧），点击缩略图选中对应节点（画布高亮"
        "+检查器联动），最新产物排前；空态有引导文案。"
        "\n【② 时序预览】此前只 fitView+提示 → 新建 previewPlayer.ts（Kahn 分层"
        "拓扑排序纯函数，同层按画布位置 y 主 x 辅，环不丢弃按位置序附尾），"
        "CanvasOverlays 按拓扑序每 900ms 高亮一个节点并写状态栏进度"
        "「时序预览 n/总」，播完自动停、再点即停；7 例 vitest 锁排序行为。"
        "\n【③ 撤销/重做】「历史栈」占位（只报步数）→ 拆成 ↶撤销/↷重做真按钮，"
        "直连 store.undoGraph/redoGraph（与 Ctrl+Z/Y 同源）。"
        "\n【纪律】全部零冻结区：onPreview/onGallery/onHistory props 保留签名"
        "不再调用（CanvasShell 零改动）；面板外壳复用 .oh-panel 视觉家族。"
        "\n【门禁】tsc 37=基线 · vitest 274/274（+7）· run_all_checks 75 全绿 · 双库无漂移。"
        "\n上一版 V4.41.15「横向工具板」见 docs/CHANGELOG.md。"
    ),
}
