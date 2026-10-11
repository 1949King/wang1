__version__ = "4.43.8"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 8,
    "codename": "解冻 stage3d-core：角色工具栏去内联硬编码色（可读性）",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.8：用户授权解冻 stage3d-core，修角色管理工具栏可读性\n"
        "\n【用户裁定】「解冻 character_management_module.py」（明确授权）\n"
        "\n【病根】\n"
        "· `character_management_module._build_ui()` 的顶部工具栏用了**内联硬编码**深色：\n"
        "      title.setStyleSheet(\"…color:#fff;\")            → 浅色主题下白字白底不可见\n"
        "      hint.setStyleSheet(\"color:#888;…\")             → 浅色下过淡\n"
        "      _char_combo.setStyleSheet(\"QComboBox{background:#1a1a1a;color:#eee;…}\")\n"
        "      _interp_check.setStyleSheet(\"color:#ccc;\")\n"
        "· **内联样式优先级高于全局 QSS** ⇒ ① 深色主题下与工具栏背景几乎同色、文字发暗\n"
        "  （用户截图圈出的「看不清」）；② 浅色主题下变黑框 / 白字白底，完全不可用。\n"
        "\n【修复（改动范围：仅样式）】\n"
        "· title → `setObjectName(\"titleLabel\")`，去掉 color，颜色交全局 QSS\n"
        "· hint  → `setObjectName(\"hintLabel\")`，去掉 color\n"
        "· _char_combo → 删掉整段内联样式，走全局 `QComboBox[theme]`\n"
        "· _interp_check → 去掉 color，走全局 `QCheckBox[theme]`\n"
        "\n【纪律（frozen-zone-release 流程严格执行）】\n"
        "· 归属一次列全：本次只 `character_management_module.py` 在锁内（stage3d-core），\n"
        "  `app/version.py` / `CHANGELOG.md` / `frozen_zones.json` / 现行技术文档均在锁外。\n"
        "· 流程：基线校验 OK → 备份 .bak → 改 → ruff/AST 校验 → `--update` 重锁（85 项）→\n"
        "  复跑确认 `OK frozen zones intact` → `frozen_zones.json` 的 stage3d-core.reason 追加\n"
        "  解冻记录 + `updated` 改 2026-10-11 → 现行技术文档 §5 加不变量 → 清理 .bak。\n"
        "· **未动** GLB 加载 / 骨骼绑定 / 姿势应用 / 材质渲染 / 端口值(18765·3011·3010) /\n"
        "  画布预热时机 / 角色库 CHARACTER_FIELD_SCHEMA。\n"
        "· 改动核实：`git diff --numstat` = **+11/-6，全部落在样式行**。\n"
        "\n【验证】\n"
        "· ruff 存量棘轮 166 文件零新增 · AST 语法 OK · frozen_zone 85 locks intact ·\n"
        "  真机启动正常。\n"
        "\n【上一版 V4.43.7『主题切换 repolish + 预设点击穿透』见 docs/CHANGELOG.md。】"
    ),
}
