__version__ = "4.44.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 44,
    "patch": 0,
    "codename": "「代码 × 扩散」混合视频契约刀（CodeVideoSpec）",
    "release_date": "2026-10-19",
    "description": (
        "V4.44.0：立项「代码 × 扩散」混合视频管线（行业 2026 主流最佳实践：扩散管画面、"
        "代码管文字/版式/动效，两条路线在 CodeVideoSpec 汇合）。本刀只落地**契约层**：\n"
        "① app/core/code_video/spec.py（678 行，零重依赖可独立 import）：CodeVideoSpec "
        "dataclass 族 + validate_spec（结构）+ compile_spec（语义校验 + limits 硬钳 + "
        "归一化）+ from_storyboard（分镜表→草案）；asset://（扩散素材）与 html://（代码镜头）"
        "混排，文字层铁律（kind∈{text,subtitle} 必须 html://——视频内文字不可靠是扩散模型"
        "公认短板），limits 硬钳 60s/12clip/1080×1920/fps∈{24,30}，asset 路径禁越界，"
        "params 只收标量/标量列表且丢弃显式报错（不静默修正），lineage 经 glue "
        "normalize_generation 六键同源清洗；② pipeline.code_video_plan 能力（计划态）："
        "分镜表→spec 草案→契约编译，无输入/编译不过 ⇒ success=False 诚实失败（绝不把烂草案"
        "包装成计划态）；code_video_render 留到 V4.45 渲染引擎落地时同批注册；\n"
        "③ 三处注册（能力目录 CAPABILITY_ROWS / register_builtin_handlers / "
        "_AGENT_ACTION_ROWS 别名 + help_block 参数文案），目录↔注册双向守卫 0 问题。\n"
        "\n【验证】\n"
        "· pytest 23 例契约测试全绿（round-trip/文字层铁律/limits 钳制/params 白名单/\n"
        "  from_storyboard 缺时长不猜/handler 三条失败路径）；\n"
        "· check_code_video 门禁全绿（零依赖断言/三处注册一致/六键同源/行为冒烟/行数棘轮）；\n"
        "· check_capability_catalog OK；check_action_wiring ALL PASS (7)；\n"
        "· frozen_zone_guard OK 107 locks（本轮零冻结区改动）；ruff 本轮文件全过；\n"
        "· CLI round-trip：3 镜头分镜 → spec(1788B JSON) → from_dict → compile OK，\n"
        "  混合 source 实证（html://title.html + asset://shot_*.mp4 + html://subtitle.html）。\n"
        "\n【明确不做（防 scope 蔓延）】\n"
        "· 本刀不渲染、不起沙箱、不碰画布节点（V4.45 引擎刀 / V4.46 画布刀）；\n"
        "· 不注册 code_video_render 空壳（目录↔注册守卫禁止空登记占位）。\n"
        "\n【上一版 V4.43.23『3D 群像根因修复 + 配方卡』见 docs/CHANGELOG.md。】"
    ),
}
