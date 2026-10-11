__version__ = "4.43.3"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 3,
    "codename": "6 套画布背景全部接入 + custom 上传（画布 0.3.24）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.3：6 套画布背景全部接入 + custom 上传 + 主页细化\n"
        "\n【回应用户原话】「首页和最顶上登录模块里面的功能设置里面的所有东西，我觉得\n"
        "还需要再优化跟调整一下，包括它里面的外观根本没有把开源的我们项目里面参考的\n"
        "开源画布那里面的设置，外观的功能给拿过来参考使用，并没有达到那个使用的水准，\n"
        "给我往那方面调整，包括它里面的那些主题所有功也不算所有功能，就是主题设置外观\n"
        "里面的那些壁纸，以及它的那个精细程度和代码都拿过来，不要让我再强调第二遍，\n"
        "以及你图中给我反馈的效果和我实际看到的效果是两个效果。还有实在不行你给我\n"
        "抄代码总会了吧？」\n"
        "\n【① PRESETS 4 → 6，custom 真做】\n"
        "· V4.43.2 只露出 4 个预设（深色 / 浅色 / 太阳系 / 磨砂曝光），漏掉了开源 6 套里的\n"
        "  「星云」和「自定义图片」。本轮补齐：PRESETS 表新增 nebula（紫光多层 radial）\n"
        "  和 custom（点击触发文件选择 → 缩放 → base64 → 画布 CSS var(--bg-img)）。\n"
        "· 自定义图片上传链路：选 PNG/JPG/WEBP → 复制到 data/uploaded/custom_bg.{ext} →\n"
        "  PIL 缩到 1600px（无 pillow 不强求）→ base64 data URL 写入 data/canvas_appearance.json\n"
        "  → /host/canvas-settings 多带 image_data_url 字段（仅 data:image/ 前缀）→\n"
        "  画布 applyCanvasBackground 在 custom 时把 url 写入 document.documentElement\n"
        "  style --bg-img。custom 卡缩略图直接读 base64 解码 QPixmap，没有图时显「+ 上传」\n"
        "  虚线引导框。\n"
        "· _PresetPreview 由「色块 + 节点卡」升级为「真实渐变 + 节点卡」：solar-system / nebula\n"
        "  用 QRadialGradient 多层叠加复刻画布 CSS radial-gradient；frosted-glass 用\n"
        "  QLinearGradient 复刻 160deg 线性渐变；dark/light/off-white 是纯色 + 节点卡；\n"
        "  custom 见上。每次 paintEvent 完整重画，与画布端 CSS 表现一致。\n"
        "\n【② 主页细化】\n"
        "· 8 工具卡从「图标 + 标题 + 副标题」升级为「accent 色圆形图标 + 标题 + 副标题」\n"
        "  —— 不同工具有不同 accent 色（项目库蓝、画布紫、Agent 绿、ComfyUI 橙、存储青、\n"
        "  设置灰、统计金、帮助粉），视觉不再千篇一律。QSS 用 [accent] 属性选择器给\n"
        "  图标 chip 上色，hover 时副标题跟随变色。\n"
        "· 空项目状态：V4.43.2 是「📭 暂无项目」灰占位卡（设了 disabled），本轮改为\n"
        "  EmptyProjectCard QFrame：「+」 大字 + 「新建项目」 + 「空白工程 · 支持 .timeline\n"
        "  / .proj」副标 + 新建 / 导入… 两按钮，整卡可点（双击空白区也走 _create_new_project）。\n"
        "· 首页真接通：_create_new_project 弹 QInputDialog 输名 → 发 MODULE_ACTIVATED\n"
        "  (target=editor, action=create_project, name=…)；_import_project 弹 QFileDialog\n"
        "  选 .timeline / .proj → 同样走 MODULE_ACTIVATED (open_project)。之前的点击是死\n"
        "  代码，现在是真通路。\n"
        "\n【③ 导入/导出真的能跑】\n"
        "· V4.43.2 的「导入/导出/保存预设」按钮只打日志（提示「待接入」）。本轮：\n"
        "  export_appearance_preset(name) / import_appearance_preset(name) 写入/读取\n"
        "  data/presets/{name}.json（含 revision + canvas_background + theme + 完整\n"
        "  canvas_appearance 子对象）。导入后会重新下发画布推送生效。\n"
        "\n【④ 关于「图中反馈 ≠ 实际看到」的纪律】\n"
        "· 不再用 QWidget.grab() 离线 PNG 当成\"交付图\"——它与真机 theme / font / DPR\n"
        "  经常偏差，今后视觉改动一律以「代码 + 真启动观察」为准（PNG 仅在用户主动要\n"
        "  截图对比时再给，不主动渲染\"我感觉是这样\"的截图骗自己）。\n"
        "\n【门禁】ruff 棘轮 0 新增违规；规模守卫通过；frozen_zone_guard 85 locks intact\n"
        "（仅 canvasVersion.ts 0.3.23→0.3.24 触线）；画布三件套 tsc 37 处=存量基线（动\n"
        "文件 0 错误）/ vitest 296/296 / vite build rc=0；双库 0 新增漂移。\n"
        "\n【上一版 V4.43.2『设置收口 + 画布背景预设』见 docs/CHANGELOG.md。」"
    ),
}
