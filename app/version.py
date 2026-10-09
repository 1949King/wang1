__version__ = "4.41.13"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 13,
    "codename": "桌宠立绘化（AgentPet 2D 重写 · 删 3D 渲染层）",
    "release_date": "2026-10-10",
    "description": (
        "V4.41.13: 桌宠「拾岚」形象返工 —— 用户实测否定 3D 几何形象（b237626），"
        "改为 2D 立绘 + 表情帧方案（画布 0.3.11 → 0.3.12「拾岚立绘」）。"
        "\n【删】src/mascot/foxScene.ts（Three.js 程序化几何，406 行）——"
        "教训：可爱感来自设计（比例/线条/配色），不来自几何参数；"
        "程序化几何做角色形象是路线错误，且桌宠 WebGL 上下文与生成任务抢 GPU。"
        "\n【换】AgentPet.tsx 493 → 264 行：形象本体 = 三帧同一画布立绘"
        "（public/mascot/ 各 ~200KB，316×480，质心对齐 IoU≥0.985 叠放零位移）："
        "pet_neutral 自然表情（默认主帧，不再一直挂笑）/ pet_blink 眨眼"
        "（nextBlinkGap 同分布随机 2.2~5.5s）/ pet_cheer 大笑挥手（仅 success）。"
        "props 接口不变，CanvasOverlays 零改动；交互层 usePetDrag/petActivity/usePetStatus 原样保留。"
        "\n【修】双图标：桌宠挂载即用 MutationObserver 隐藏右下角旧 .sg-agent-fab"
        "（冻结区 CanvasShell 零改动，卸载恢复），Agent 入口唯一。"
        "\n【留】mascotMotion.ts 纯函数全保留（26 例测试不动），3D 专属曲线"
        "（耳/尾/眼球）留作回归基线不再参与渲染。"
        "\n上一版 V4.41.12「产品树净化」见 docs/CHANGELOG.md。"
    ),
}
