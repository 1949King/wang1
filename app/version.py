__version__ = "4.41.17"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 17,
    "codename": "图库灯箱与相机跟随（画布 0.3.16）",
    "release_date": "2026-10-10",
    "description": (
        "V4.41.17: 工具板二轮优化（画布 0.3.15 → 0.3.16「图库灯箱与相机跟随」）。"
        "\n【A1 图库大图预览】缩略图 hover 出现 ⤢ 角标，点击进 lightbox 全屏查看："
        "←→ 在产物间切换、Esc/点遮罩关闭、底部 caption 显示类型/标题/序号；"
        "与「点击缩略图选中节点」两个动作分离（角标 stopPropagation）。"
        "\n【A2 图库类型筛选】全部/图片/视频三个 tab（复用 .oh-tabs 视觉家族），"
        "tab 上带计数，空态分文案。"
        "\n【B5 预览相机跟随】CanvasOverlays 每步派发 sg-preview-focus 事件，"
        "CanvasShell（冻结区已授权，唯一新增 11 行监听器）fitView 到当前节点"
        "（duration 420ms、maxZoom 1.15 防单节点放过大）—— 修复「节点跑到视窗外白高亮」。"
        "\n【A3】撤销/重做 title 动态步数（开板时读 getGraphPast/Future）。"
        "\n【A4】⚡工具按钮播放中显示「⌕预览 n/总」，不开板也能看进度。"
        "\n【门禁】tsc 37=基线 · vitest 274/274 · run_all_checks 75 全绿 · 双库无漂移。"
        "\n上一版 V4.41.16「工具补全」见 docs/CHANGELOG.md。"
    ),
}
