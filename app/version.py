__version__ = "4.43.11"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 11,
    "codename": "热修：设置打不开（V4.43.9 回归 —— switch_to_module 不认 nav_hidden 模块）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.11：热修 V4.43.9 引入的「设置打不开」回归\n"
        "\n【用户反馈原话】「就是设置呃首页中的最顶上的设置图标的功能打不开，以及登录里面的\n"
        "设置也打不开，为什么？切换主题正常，帮助文档正常，意见反馈也正常，就是登录里面打\n"
        "不开。」\n"
        "\n【根因（V4.43.9 引入）】\n"
        "· V4.43.9 把 `_show_settings()` 改成 `switch_to_module(\"settings\")`。\n"
        "· 而 `switch_to_module` 内部只是 `_nav_bar.select_module()`，后者实现为：\n"
        "      def select_module(self, module_id):\n"
        "          if module_id in self._buttons:      # ← 只认导航栏里的模块\n"
        "              self._on_button_clicked(module_id)\n"
        "          # 否则什么都不做\n"
        "· settings 自 V4.43.2 起 `nav_hidden=True`、**不在导航栏** ⇒ 不在 `_buttons`\n"
        "  ⇒ 点击 ⚙ / 用户中心「设置」**毫无反应，且日志不报错**（典型静默失败）。\n"
        "· 这也解释了用户观察到的「help / 意见反馈正常、唯独设置打不开」——\n"
        "  前者都在导航栏里。\n"
        "\n【修复】\n"
        "· `_show_settings` 改走官方模块加载路径：\n"
        "      info = self._modules.get(\"settings\")\n"
        "      if not info.instance: self._perform_module_load(\"settings\")\n"
        "      else:                 self._activate_module(\"settings\", info)\n"
        "  `_perform_module_load` 已内含「建 widget → 连接 settings_changed →\n"
        "  set_module_widget 建 tab → _activate_module 切 tab」，**完全不依赖导航栏**。\n"
        "· 仍保持 V4.43.9 的意图：页内呈现、不产生独立窗口。\n"
        "\n【验证（实测，非推断）】\n"
        "· 新建真 `MainWindow()`，打印：settings 在 `_modules`=True、\n"
        "  在导航栏 `_buttons`=False；调用 `_show_settings()` 后\n"
        "  tab 从 `[0] 🏠 首页` → `[1] ⚙️ 设置`，settings 实例已创建。\n"
        "  见 `.workbuddy/tmp/verify_settings_open.py`（SUMMARY: PASS）。\n"
        "· 门禁：ruff 棘轮零新增 / frozen_zone 85 locks intact / 规模守卫无新增 /\n"
        "  stability 250 / SCOPE 0 命中。\n"
        "\n【教训（写进纪律）】\n"
        "· **`switch_to_module()` 不能用于任何 nav_hidden 模块** —— 它经 `select_module`\n"
        "  只匹配导航栏按钮，对隐藏模块静默无效。要打开隐藏模块必须走\n"
        "  `_perform_module_load` / `_activate_module`。\n"
        "· 「没反应且日志无异常」是静默失败的典型特征 —— 查 `if ... in self._buttons`\n"
        "  这类前置守卫比看日志更快。\n"
        "\n【上一版 V4.43.10『画布太阳系背景求真』见 docs/CHANGELOG.md。】"
    ),
}
