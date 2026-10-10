__version__ = "4.41.18"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 18,
    "codename": "AgentOS S1 窗口管理（画布 0.3.17）",
    "release_date": "2026-10-10",
    "description": (
        "V4.41.18: AgentOS 演进第一刀「窗口管理」（画布 0.3.16 → 0.3.17「窗口管理」）。"
        "解决真实痛点：4 面板此前全部固定叠在底部同一坐标（bottom:58px 居中），同开必互相覆盖。"
        "\n【① 可拖动】拖 header 移动（抓起即置顶），位置归一化 (x,y)∈[0,1]² "
        "localStorage 持久化（同桌宠 usePetDrag 范式，换窗口尺寸按比例落位）；"
        "双模式定位——未拖过保持 CSS 底部居中，拖过 5px 阈值那一刻用 getBoundingClientRect "
        "换算切 JS 内联定位（left/top+transform:none+bottom:auto 一次写全），零跳动；"
        "拖拽逐帧直写 el.style 零重渲染，React style 只持 zIndex。"
        "\n【② 点击置顶】z = 47 + 层叠序（顺序数组派生，非计数器）——4 面板恒在 47..50，"
        "轮转置顶永不撞车无需重整；竞争者 fab(60)/agent-panel(70)/lightbox(9000) 全在安全距离。"
        "\n【③ 最小化到 dock】面板「—」收起，dock 右侧出现恢复图标"
        "（与工具板同源图标 ⏱▤💡🎬，点击恢复到存储位置）；最小化不持久化（刷新还原），"
        "open=false 时 subscribe 联动自动清 minimized+层叠序（无死状态）；"
        "最小化时快捷键=关闭（开关灯语义一致）。"
        "\n【边界纪律】DOCK_RESERVE=64 底部 clamp——面板拖不进 dock 带，"
        "maxHeight 动态钳制防内容长高越界；上沿 INSET=8。"
        "\n【门禁】tsc 37=基线 · vitest 291/291（+17 窗口管理用例）· "
        "run_all_checks 75 全绿 · 双库无漂移。"
        "\n上一版 V4.41.17「图库灯箱与相机跟随」见 docs/CHANGELOG.md。"
    ),
}
