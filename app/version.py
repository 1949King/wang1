__version__ = "4.43.4"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 4,
    "codename": "外观页 1:1 复刻开源 2×2 大卡墙（音频/视频/动画/3D 导演台）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.4：外观页 1:1 复刻开源 2×2 卡墙 + 4 类节点中央预览\n"
        "\n【回应用户原话】「我要的是完全复刻这个样子的效果。你把那个开源代码库 AI 画布\n"
        "那个给我拷下来，自己去一行一行对照。」+ 截图（深色/浅色/太阳系/磨砂曝光 2×2\n"
        "卡墙 + 顶部大预览）。\n"
        "\n【事实先纠】fork vendor/AI-Canvas-tauri 实际**没有「外观预设 2×2 卡墙」独立 UI**\n"
        "（SettingsPanel.tsx 7 tab：general/files/api/storage/comfyui/shortcuts/mcp，\n"
        "不含「外观」）。截图是拾光剪影自己的视觉设计稿，但视觉风格确实借鉴 AI Canvas。\n"
        "本轮复刻 = 开源视觉风格 + 我们画布自己的 4 类节点内容。\n"
        "\n【① PRESETS 6 → 4，改回 2×2】\n"
        "· V4.43.3 扩到 6（深/浅/太阳系/星云/磨砂曝光/custom），但截图里只有 4 张卡。本\n"
        "  轮改回 4：深色（audio）/ 浅色（video）/ 太阳系（animation）/ 磨砂曝光（director）。\n"
        "· PRESETS 表加 2 个字段 `(node_kind, chip_text)` → PresetCard 据此在中央渲染\n"
        "  不同的节点卡（音频波形 / 视频输入框 / 动画文本 / 3D 导演台）。\n"
        "· nebula / custom 仍是画布端 CANVAS_BACKGROUNDS 中的合法背景，custom 上传通路\n"
        "  完整保留（export_appearance_preset / _image_to_base64 / _save_custom_image_to_disk\n"
        "  / _load_current_image_b64 / push_canvas_appearance 全部还在）。\n"
        "\n【② _PresetPreview 完全重写，按 node_kind dispatch 渲染】\n"
        "· 整张卡结构：① 真实画布背景渐变（与画布端 CSS 一一对应：solar-system 3 层\n"
        "  radial / dark 双层 radial 行星蓝晕 / light 米白点阵 / frosted-glass 160°\n"
        "  线性 + 点阵）；② 顶部行 icon + chip_text + #序号；③ 中央节点卡（按 node_kind\n"
        "  渲染音频波形/视频输入/动画文本/3D 导演台 4 套）。\n"
        "· 新增 _paint_dot_grid(p, w, h, color) helper 给浅色卡背景绘制极小点阵。\n"
        "\n【③ AppearancePreview 大预览区背景 = 真实画布渐变（动态切换）】\n"
        "· 加 set_preset_id(preset_id) 切换背景：dark=行星蓝晕 / solar-system=多色 /\n"
        "  light=米白点阵 / frosted-glass=160° 渐变+点阵。文字色/边框/卡片底色自动按当前\n"
        "  preset 深浅切换（大预览区是独立视觉容器，不依赖主程序 theme_manager）。\n"
        "· 右下「当前主题」圆点改为紫光大圆环 + 中央小白点（截图视觉，与预设卡中心\n"
        "  圆环对齐）。左节点卡标题右加绿色小圆点。\n"
        "\n【④ 关键事实】\n"
        "· 第二次用户提醒「完全复刻」 ⇒ 之前 V4.43.3 误解了用户意图（以为 6 个预设是\n"
        "  好事）。这次严格按截图视觉（4 个 + 2×2 + 4 类节点）1:1 实现。\n"
        "· 节点内容不是孤立装饰：每张预设卡的中央 = 我们画布 4 类核心节点的迷你预览\n"
        "  （音频/视频/动画/3D 导演台），这是拾光剪影独有的设计 —— fork 没有。\n"
        "\n【门禁】ruff 棘轮 0 新增违规；规模守卫通过；frozen_zone_guard 85 locks intact\n"
        "（V4.43.4 未改画布，0 触线）；tsc 37 处=存量基线（动文件 0 错误）/ vitest\n"
        "296/296 / vite build rc=0；双库 0 新增漂移。\n"
        "\n【上一版 V4.43.3『6 套画布背景全部接入 + custom 上传』见 docs/CHANGELOG.md。」"
    ),
}
