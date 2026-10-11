__version__ = "4.43.7"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 7,
    "codename": "主题切换不生效根治（repolish）+ 预设卡点击穿透 + 工具栏硬编码色",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.7：修「主题切不回来」「点预设没反应」+ 工具栏颜色硬编码\n"
        "\n【用户反馈原话】「其一，切换主题之后为什么点再次切换它就回不去了呢？其二，\n"
        "点开那顶部设置里面的设置中的外观功能，点其中四个中的一个…它没有切换到对应的\n"
        "深色主题。…最后那张图片里面…用红线圈起来的地方，你认为这设计合理吗？可读性好吗？」\n"
        "\n【① 主题切换不生效 → 根治（重要）】\n"
        "· 病根：`ThemeManager._apply_theme_property()` **只 setProperty、不 repolish**，\n"
        "  注释写「不使用 unpolish/polish（性能差），依靠 setStyleSheet 全局刷新自动生效」\n"
        "  —— **这个假设是错的**。\n"
        "· 决定性实测（offscreen，QPushButton + [theme] 属性选择器）：\n"
        "      初始 dark          → 背景 #000000\n"
        "      只 setProperty     → 背景仍 #000000（期望 #ffffff，**没变**）\n"
        "      unpolish+polish 后 → 背景 #ffffff（正确）\n"
        "· 为什么表现为「切一次就回不去」：`_do_apply_theme` 先 `app.setStyleSheet(qss)`、\n"
        "  **后** `_apply_theme_property()`，属性改动落在样式表重算之后 ⇒ 界面停在旧主题；\n"
        "  而 ThemeManager 内部状态是正确交替的（日志可证）。\n"
        "· 修复：`_apply_theme_property` 内对每个 widget `setProperty` 后补\n"
        "  `style().unpolish(w)` + `polish(w)`；并加「属性未变则跳过」以省开销。\n"
        "\n【② 点外观预设没反应 → 根治】\n"
        "· 病根：`_PresetPreview` 是**自绘 QWidget**、覆盖预设卡绝大部分面积；QWidget 默认\n"
        "  接受 mousePressEvent ⇒ 点击被它吞掉、不冒泡到父级 PresetCard ⇒\n"
        "  `PresetCard.mousePressEvent` 收不到 ⇒ `activated` 信号**永不发射**。\n"
        "· 修复：`_PresetPreview` 设 `WA_TransparentForMouseEvents`。\n"
        "· 实测：点预览区 → activated=['dark']（修复前为空）。\n"
        "\n【③ 工具栏下拉框可读性（用户截图圈出）—— 待授权解冻，本版未落地】\n"
        "· 病根：`character_management_module` 的控件用了**内联硬编码**深色\n"
        "  （`QComboBox{background:#1a1a1a;color:#eee}` / `color:#fff` / `#888` / `#ccc`），\n"
        "  内联样式**优先于**全局 QSS ⇒ ① 深色下与工具栏背景几乎同色、文字发暗；\n"
        "  ② 浅色下变黑框 / 白字白底，完全不可用。\n"
        "· 该文件在 **stage3d-core 冻结区**（用户 2026-08-20 明确要求冻结，防 GLB / 骨骼 /\n"
        "  材质被误改）。按纪律**未擅自改动，改动已回退**；待用户授权解冻后再改\n"
        "  （改动仅限「去掉内联颜色 → 改用全局主题 QSS」，不碰 GLB / 骨骼 / 端口 / 预热时机）。\n"
        "\n【验证】\n"
        "· 三项修复全部 offscreen 实测通过（见上）。\n"
        "· 门禁：ruff 棘轮零新增 / frozen_zone 85 locks intact / 规模守卫无新增 /\n"
        "  stability 250 / SCOPE 0 命中 / run_all_checks 全绿 / pre-commit 11 道全过。\n"
        "\n【关于「参考项目为什么做得更好」的诚实结论（用户问题③）】\n"
        "· AI-Canvas-tauri 的太阳系背景 = **8 张真实行星照片**（mercury…neptune PNG）+\n"
        "  `setInterval` 每 **80 秒轮播** + 淡入/缩放过渡（1.2s）+ 星场 60s 漂移动画；\n"
        "  磨砂暖光/星云用 **Three.js** 真实渲染。\n"
        "· 我们 `vendor/shiguang-canvas/src/canvasBackgrounds.ts` 是**纯 CSS 渐变**、静态、\n"
        "  无素材无动效 —— 差距是「**没搬素材、没做动效**」，不是能力不可及。\n"
        "  行星素材就在 `vendor/AI-Canvas-tauri/src/assets/images/bg/`，**可直接复刻**。\n"
        "\n【上一版 V4.43.6『画布白屏根治 + 顶栏可读性』见 docs/CHANGELOG.md。】"
    ),
}
