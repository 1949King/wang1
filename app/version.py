__version__ = "4.43.2"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 2,
    "codename": "设置收口 + 画布背景预设（画布 0.3.23）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.2：设置入口收口 + 画布背景预设做真\n"
        "\n【① 设置从左侧导航撤出（用户裁定）】\n"
        "用户原话「为什么不把设置模块的功能全都移到…设置去，这样把侧边栏那个直接取消掉」。\n"
        "· 先纠正前提：登录窗口（login_window.py 916 行）**没有任何设置**，只有登录/注册/设备管理；\n"
        "  另有 modules.py:1234 `_show_login_dialog`「登录信息与设置」是**死代码**（定义 1 次、全库零调用）。\n"
        "· 真正有设置的入口是 3 处：左侧导航「设置」/ 顶栏 ⚙ / 用户中心 👤 里的 ⚙ 设置行。\n"
        "· 本轮按用户选择收口：**取消左侧导航「设置」**，保留顶栏 ⚙ + 用户中心 👤（都开模态弹窗）。\n"
        "· 实现：`module_registry.ModuleDefinition` 新增 `nav_hidden` 字段；settings 条目设 `nav_hidden: True`；\n"
        "  `main_window.register_module_lazy` 跳过导航注册（**仍注册、仍可 switch_to_module**，即弹窗失败可回落）。\n"
        "\n【② 画布背景预设 —— 移植开源 backgroundOptions.ts（用户裁定「做真」）】\n"
        "· 开源 AI Canvas 的「外观预设」= 画布背景主题（`components/backgrounds/backgroundOptions.ts`：\n"
        "  默认暗色 / 太阳系 / 星云 / 米白浅色 / 磨砂暖光 / 自定义图片）。\n"
        "  我们此前 4 个预设只有「深色/浅色」真生效，太阳系/磨砂曝光是**视觉占位**。\n"
        "· 本轮：新建 `vendor/shiguang-canvas/src/canvasBackgrounds.ts`（非冻结文件），\n"
        "  **运行时注入 `<style>` + `html[data-canvas-bg]` 属性**实现 6 个背景；\n"
        "  `main.tsx` 接线 `initCanvasBackground()`；主题复用既有 `useCanvasStore.setTheme`。\n"
        "· **冻结区只动 1 个文件（canvasVersion.ts 版本号）** —— styles.css / store.ts / CanvasShell.tsx\n"
        "  一字未改（协作对象替换思路，见 frozen-zone-release 技能「换协作对象 ≫ 解冻」）。\n"
        "· PyQt 侧：`canvas_routes_get.py`（非冻结）新增 `GET /host/canvas-settings`；\n"
        "  画布每 2.5s 轮询，按 **revision 号**增量应用（只在设置真变过时生效，不覆盖画布内本地主题切换）。\n"
        "· 单一真相源 = `data/canvas_appearance.json`（选 JSON 非 QSettings：沙箱/无注册表写权限环境也能落盘）。\n"
        "· 4 个预设全部落地为真实画布背景：深色→default / 浅色→off-white / 太阳系→solar-system /\n"
        "  磨砂曝光→frosted-glass；主题模式（深/浅/跟随系统）同步下发画布主题。\n"
        "\n【回答用户提问「可以从外部导入其他样式的外观吗」】\n"
        "· 开源 AI Canvas 本身**不支持导入外部样式包**，只有「自定义背景图」（上传一张图）。\n"
        "· 我们的 `导入/导出/保存预设` 按钮目前仍是空壳（只打日志）。**可以做成真的**：把外观配置\n"
        "  （主题 + 预设 + 画布背景 + 节点配色）序列化 JSON 导出/导入 —— 留待下一轮。\n"
        "\n【门禁】ruff 棘轮 0 新增违规；规模守卫通过；frozen_zone_guard 85 locks intact（重锁后复跑确认）；\n"
        "画布三件套 tsc 37 处=存量基线（riggedHumanoid 21 + Stage3D 16，新文件 0 错误）/ vitest 296/296 /\n"
        "vite build rc=0（main 846.59→849.56 kB）；双库 check_canvas_dual_repo 0 新增漂移（副库 tsc rc=0）。\n"
        "\n【上一版 V4.43.1『设置模块对齐 AI Canvas』见 docs/CHANGELOG.md。」"
    ),
}
