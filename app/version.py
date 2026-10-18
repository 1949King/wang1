__version__ = "4.43.23"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 23,
    "codename": "3D 群像巨物根因修复 + 配方卡（Agent 自动铺卡）+ 画布 UI 收嘈",
    "release_date": "2026-10-19",
    "description": (
        "V4.43.23：① 修复「3D 群像第三个角色一只脚占满屏幕」——根因是"
        "SkeletonUtils.clone() 后 matrixWorld 未结算，Box3 量出 1/33 假尺寸 ⇒ 归一化"
        "算出 33× 补偿把 1.7m 模型放大成 56.5m（用户授权解冻 stage3d-core，7 轮定位，"
        "03:50 日志实证；applyBoneDelta 的 NaN 守卫保留为纵深防御）；② 新增配方卡"
        "（Recipe）：recipePure.ts 纯函数 LCS 中文匹配 + recipe.ts 存取应用 + "
        "RecipePanel.tsx 左栏面板 + recipeBridge.ts Agent 事件桥，后端 canvas.apply_recipe "
        "能力只广播 SSE、前端执行铺卡——Agent 从「只能给建议」升级为「能自动铺卡片」"
        "（用户授权解冻 canvas-magnetic-intent，42→48 文件 / 101→107 锁）；③ 画布 UI "
        "收嘈：导航改左侧 64px 竖排、形态切换归位画布顶栏（用户两次当面纠正）、Agent "
        "面板去噪、「送剪辑」提到 dock 一级。\n"
        "\n【验证】\n"
        "· vitest 37 文件 / 568 例全绿（recipePure 18 例新增）；tsc 存量 37 零新增；\n"
        "· 后端自检：canvas.apply_recipe 注册 + 目录双向对齐 0 问题；\n"
        "· frozen_zone_guard OK 107 locks；doc_consistency_gate 0 阻断；\n"
        "· run_all_checks 46 项过（CANVASDUAL 失败定性为沙箱 safe-delete turn 级计数\n"
        "  超阈的环境误报：web 主构建 ✓ 6.24s / tauri 完整构建退出码 0，产物已 mv 暂存）。\n"
        "\n【顺带修了一个「永远空跑」的门禁摆设】\n"
        "· check_canvas_dual_repo.py 的 tauri filter 大写 AI-Canvas-tauri 与实际包名\n"
        "  小写 ai-canvas-tauri 不匹配 ⇒ pnpm「No projects matched」但退出码 0 ⇒\n"
        "  该项长期假绿、从没真验证过 tauri 打包链路。已修。\n"
        "\n【上一版 V4.43.22『画布三修』见 docs/CHANGELOG.md。】"
    ),
}
