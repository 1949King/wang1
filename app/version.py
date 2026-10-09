__version__ = "4.41.14"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 41,
    "patch": 14,
    "codename": "桌宠隐藏态（面板打开即消失）",
    "release_date": "2026-10-10",
    "description": (
        "V4.41.14: 修正桌宠与 Agent 面板的并存行为（画布 0.3.12 → 0.3.13）。"
        "\n【问题】点开桌宠后她只是缩成角落小头像（mini 形态），与参考开源画布的"
        "交互不一致 —— 用户期望：点开桌宠 = 桌宠变成对话窗口并**消失**，"
        "关闭对话 = 桌宠回来。"
        "\n【改】mini 语义从「缩小显示」改为「完全隐藏」：Agent 面板打开期间"
        "桌宠 display:none（DOM 保留，位置记忆 / 眨眼调度不中断），"
        "面板关闭即原位回归；同时移除 mini 裁剪样式与让位逻辑"
        "（usePetDrag 恒用 expanded 尺寸）。props 接口不变。"
        "\n上一版 V4.41.13「桌宠立绘化」见 docs/CHANGELOG.md。"
    ),
}
