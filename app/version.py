__version__ = "4.46.3"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 3,
    "codename": "用户反馈双修：Agent 铺卡确定性网格 + 密钥保存诚实失败",
    "release_date": "2026-10-21",
    "description": (
        "V4.46.3：修用户实锤的两个问题（截图 + 复现步骤），全在非冻结区。\n"
        "\n【① Agent 铺画布工作流混乱】截图实锤：Agent 一次铺一批卡全叠在一起。\n"
        "根因：store.addNode 无坐标时用 Math.random() 在 120~440×80~320 小盒子里撒点\n"
        "（store.ts 属冻结区 canvas-magnetic-intent 不可改），而 AgentPanel 在 Agent 没传\n"
        "x/y 时正好传 undefined ⇒ 一批卡全挤同一小盒子互相叠压。\n"
        "修法（非冻结侧绕开）：新增 canvasSlot.ts 确定性网格槽位（5 列 × 300/230 间距，\n"
        "从左上逐槽扫、跳过被现有节点占据的槽、满 500 槽确定性对角兜底、绝不回退随机）；\n"
        "AgentPanel 两处铺卡点（executeRemoteTask addNode / /add 本地指令）都改为先取空槽。\n"
        "用户手动拖过的卡占住自己的槽 ⇒ 新卡绕开不压。7 例 vitest 锁死（含「批量 12 张互不\n"
        "重叠」用户场景回归）。\n"
        "\n【② 保存 API Key 后重启显示未配置（密钥静默丢失）】\n"
        "根因链（日志实锤）：SecureStorage.set 写盘失败只 logger.error 不返回状态 ⇒\n"
        "cloud_api.save_configs 无条件先给渠道写 \"encrypted\" 标记 ⇒ UI 无条件弹「✅ 已保存」\n"
        "⇒ 下次启动按 encrypted 去安全存储取回空 ⇒ 密钥凭空消失且全程无人报错。\n"
        "（本次触发条件：程序被沙箱环境启动，写 secrets.enc 被 Permission denied；\n"
        "  但任何磁盘满/权限/安全软件拦截都会踩同一坑，是独立的真缺陷。）\n"
        "修法：SecureStorage.set/delete/clear 返回落盘成败；save_configs 对写失败的渠道\n"
        "**绝不写 encrypted 标记**（如实标空）并抛 RuntimeError 带可操作文案；两处 UI\n"
        "（model_card 保存 / model_management 保存全部）接住异常改弹「保存失败」+ 状态标红；\n"
        "休眠同族路径 ConfigManager.save_config 一并改（写失败不标 ***SECURE***）。\n"
        "4 例 pytest 锁死：失败不标记 / 部分成功各标各的 / 成功路径行为不变 / set 返回 bool。\n"
        "\n【验证】run_all_checks 100 项全绿；pytest 1,803 passed（+4）；画布 vitest 612\n"
        "（+7）；tsc 37=基线；ruff 存量棘轮通过（改动文件零新增）；frozen_zone_guard\n"
        "107 锁完整（本刀零冻结区）；dist 已重建。\n"
        "\n【遗留（不掩盖）】① 若 Agent 显式传 x/y 仍按传入值落点（尊重模型意图）；\n"
        "② store.ts 里用户手动「添加节点」的随机撒点仍在冻结区，未动；\n"
        "③ 用户本次丢失的 Key 无法找回（从未落盘），需重填一次——重填后若再遇写盘失败，\n"
        "  现在会当场弹「保存失败」而不是谎报成功。\n"
        "\n【上一版 V4.46.2『Agent 全能力可达』见 docs/CHANGELOG.md。】"
    ),
}
