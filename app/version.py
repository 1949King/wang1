__version__ = "4.43.19"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 19,
    "codename": "LibTV 对标补强·刀3：画布前端接线（AI 增强 + AI 编剧）",
    "release_date": "2026-10-12",
    "description": (
        "V4.43.19：LibTV 对标补强第三刀 —— 前端接线（用户授权解冻 canvas-magnetic-intent）。\n"
        "刀1（V4.43.16 五引擎 Agent 能力）+ 刀2（V4.43.17 文本生剧本/落时间线）之后，\n"
        "本刀把能力接到**画布 UI**：7 项「引擎就绪、只差接线」自此 Agent 与人两个入口都能用。\n"
        "\n【画布新增（NoviceInspector 检查器，复用 .nv-loop-* 既有样式零 CSS 改动）】\n"
        "· 图像节点「AI 增强」：AI 超分 ×2（standard 档 ESPCN 不下载模型）+ AI 抠像（透明底）\n"
        "  → /host/canvas-enhance（与 canvas.ai_upscale / canvas.ai_matte 同一后端）。\n"
        "  如实回报实际引擎：degraded 必标注（⚠️ 降级：…），绝不把双三次插值说成 AI 超分。\n"
        "· 剧本节点「AI 编剧」：卡片标题当主题 → LLM 完整剧本 → /host/script-write\n"
        "  （与 pipeline.script_write 同一后端 script_writer.py 单一真源）。\n"
        "  **已有正文不覆盖**（想重写先清空）；模板降级如实标注。\n"
        "\n【关键决策】\n"
        "· 新逻辑独立成 `canvasEnhanceActions.ts`（与 canvasRepair.ts 同手法 ——\n"
        "  bridge.ts 2043/2046 仅 3 行余量 = 禁改）；**已登记进 canvas-magnetic-intent\n"
        "  的 files（33 → 34）**，受冻结保护。\n"
        "· 后端补 `POST /host/script-write`（非冻结区），canvas_routes_post.py 路由表 87 条。\n"
        "· 图像 URL 归一化：canvas-enhance 后端只认 data URL，前端 toEnhanceDataUrl\n"
        "  把 /inbox_file/… 节点图转 data URL 再发。\n"
        "\n【冻结区纪律（canvas-magnetic-intent 33 → 34 文件 / 全库 91 锁点）】\n"
        "· 备份 → 改 NoviceInspector.tsx（+AI 增强/AI 编剧 两块）+ canvasVersion.ts（三件套）\n"
        "  → frozen_zones.json 字符串手术（新文件登记 + reason 末尾追加解冻记录）\n"
        "  → --update 重锁 → 复跑 OK frozen zones intact (91 locks)。\n"
        "· 磁吸全部不变量不变：阈值 120/50/60/instant10、卡片 240×200、gap=-2、三段式阻力、\n"
        "  跟手浮起、单轴吸附、让位机制、Bond 判据、方向无语义、空间记忆配色。\n"
        "\n【验证】\n"
        "· tsc 主库 38 → 38 逐文件一致（21 riggedHumanoid + 16 Stage3D + 1 infinite-compat，\n"
        "  我的文件 0 错误）；副库 tsc -p tsconfig.app.json 同为 38（防 project references 假绿）。\n"
        "· vitest 25 文件 340 例全绿；vite build rc=0 且产物实测含「AI 超分 ×2」与\n"
        "  /host/canvas-enhance 字面量（不是只看返回码）。\n"
        "· 渲染实测（4b 纪律）：临时探针页复刻检查器 DOM + 无头 Edge 截图亲眼确认 ——\n"
        "  两按钮全宽无裁切、消息行正常、与局部重绘按钮先例风格一致；探针页已删。\n"
        "· 双库同步：canvasEnhanceActions.ts（新）+ NoviceInspector.tsx 拷副库，\n"
        "  check_canvas_dual_repo 失败项 = 1（infinite-compat.tsx 既有分叉，与本刀零交集）。\n"
        "· 后端：ruff 通过 · 路由 AST 守卫 87 条一致 · 规模守卫通过 · 目录一致性 82↔82。\n"
        "\n【已知未做】\n"
        "· 画布「落轨按钮」（导演分镜 → 时间线）需要剪辑模块上下文（source_dir / 订阅者），\n"
        "  更贴合 Agent 面板入口（pipeline.director_apply_timeline 已可用），暂不做画布按钮。\n"
        "· 真缺口（剧本生产端深化 / 资产母版层 / 对外 Agent OpenAPI）另立刀。\n"
        "\n【上一版 V4.43.18『3D 产物直达时间线 + 角色库→导演台』见 docs/CHANGELOG.md。】"
    ),
}
