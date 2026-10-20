__version__ = "4.46.2"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 2,
    "codename": "Agent 全能力可达 · 捏脸枚举漂移守卫 · 虚拟形象全景",
    "release_date": "2026-10-20",
    "description": (
        "V4.46.2：接上「模型看不见的能力」+ 给「捏脸静默丢特征」的暗坑装上守卫，"
        "并整理《虚拟形象体系全景》。全在非冻结区（补 8 个中文标签才需解冻，见文末）。\n"
        "\n【① Agent 全能力可达】上一轮核查实锤：126 能力全部已注册可执行，但对话中的"
        "LLM 只被白名单 ~45 action + 画布 34 本地 action 限制 ⇒ 精剪审计/闸门/配方/codeVideo"
        "渲染/一致性守护等第二三波能力「注册了但模型看不见」。\n"
        "· canvas 无关的对话面：help block 增「[全能力目录]」一行（126 capability_id 按前缀"
        "  分组，真源 CAPABILITY_ROWS，非 dispatcher.list_capabilities——后者首次 invoke 前为空），"
        "  封闭语义「严格只使用」放开为「优先白名单，可用目录 id」；add_clip/import_media 禁令保留。\n"
        "· 执行闸（ai_agent_panel，非冻结）：白名单不过时试 _capability_passthrough——"
        "  仅当 action 是「目录里真实存在」的 capability_id 才直通 dispatcher；未知 id/blocked"
        "  名单照旧拒绝。闸门未削：写类仍被 B 勾选拦截、dispatcher 内 policy 按 mode 把关。\n"
        "· 勾选分区（suggest_checklist）：partition_agent_commands 加可选 extra_reads（默认 None"
        "  行为逐字节等价）；只读直通能力（catalog effect=read）免弹勾选，不误当写操作。\n"
        "· 诚实边界：画布 fast 路径 canvas_tools 走 SSE→前端 executeRemoteTask（node action），"
        "  不注入后端 capability_id（否则前端不认、无回执），故只列前端本地 action；后端全能力"
        "  可达走剪辑面板/绑定 editor 的对话这条真通道。\n"
        "\n【② 捏脸枚举镜像漂移守卫 FACEENUM】实测（复核 3D/角色库/捏脸三份调研 + 独立复跑）："
        "canvas_bridge._FACE_*_LABELS 比 faceParams.ts 白名单少 8 个 A 类值（眉 round/short、"
        "眼 cat/sleepy、唇 pouty/sharp、发饰 glasses/flower_crown）；这些值可经发饰下拉直接选、"
        "或「随机」按钮 roll 出并落库，但 _face_params_to_text 走 .get(...,\"\") ⇒ 该特征在"
        "生图提示词里**静默消失**，旧守卫只查「名字在册」不查取值。新增基线棘轮守卫"
        "check_face_enum_mirror.py（纯静态：正则解析 TS 白名单 ↔ AST 取 Python dict keys）："
        "8 项登记为存量、任何新增漂移/镜像越权 exit 1；负向已验证「清空基线即报警」。\n"
        "\n【③ 虚拟形象体系全景.md】六条线（角色库/捏脸/3D 人偶/数字人/口型双引擎/一致性守护）"
        "综述，每条带文件:行实证，含 12 条缺口清单与下一步；三份并行调研交叉复核，"
        "「未投产」类绝对化断言经 grep 独立核实后修正为可核验口径。\n"
        "\n【仍需解冻才能做（不假装已修）】补齐那 8 个中文标签要改 canvas_bridge.py，它是"
        "stage3d-core 冻结文件——本刀只交付「防复发」的守卫；真正修掉 8 个已存在的暗值"
        "需用户「解冻 stage3d-core」（可与「捏脸挂载进 3D 导演台」合并同一次解冻）。\n"
        "\n【验证】run_all_checks 99 项全绿（FACEENUM 入册）；pytest 1,795 passed（+6 直通行为锁）；"
        "check_action_wiring 7 项；frozen_zone_guard 107 锁完整（本刀零冻结区）；ruff 存量棘轮通过"
        "（改动文件零新增违规）。\n"
        "\n【上一版 V4.46.1『安全底座三刀』见 docs/CHANGELOG.md。】"
    ),
}
