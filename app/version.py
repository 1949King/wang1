__version__ = "4.43.22"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 22,
    "codename": "画布三修：角色节点接线 + Agent 桌宠跨画布 + #185 崩溃根因",
    "release_date": "2026-10-14",
    "description": (
        "V4.43.20：修复「电影级灯位面板与 3D 导演台零数据流」的孤儿缺口"
        "（用户授权解冻 stage3d-core + canvas-magnetic-intent）。\n"
        "\n【问题（读码实测，非猜测）】\n"
        "· lightingPresets.ts（24 主光位 + 9 轮廓光）在 Stage3D.tsx **0 引用**；\n"
        "· 它的消费者只有 LightingPanel.tsx / lighting.test.ts，而面板 apply() 只写提示词；\n"
        "· Stage3D.tsx 自己另有一套 LIGHT_PRESETS（4 档死预设），物理上只有 hemi + dir 两盏灯。\n"
        "⇒ 用户在面板选 24 个方位之一，3D 预览纹丝不动、只能盲选。\n"
        "  这正是 zone8 不变量点名的反模式：同一语义被两条链路各写一遍。\n"
        "\n【做法：接一条单通道（照抄 stage3dApplySeq / stage3dCastSeq 正统模式）】\n"
        "· 新增 stage3dLighting.ts（326 行）作为**唯一映射通道**：\n"
        "  lightPosition 球坐标→笛卡尔（0°=镜头=世界 +Z、顺时针；度→弧度）/ kelvinToRgb\n"
        "  （Tanner Helland 近似，纯算术可测）/ lightStateFor 快照 / applyLightingToApi 副作用 /\n"
        "  useStage3dLighting 消费端（先 consume 再 apply）。\n"
        "· 映射：主光 → dir（位置/颜色/强度）、环境 → hemi、轮廓光 → 新增 lamp。\n"
        "· 轮廓灯由 WeakMap<Scene, DirectionalLight[]> 惰性持有（≤2 盏、castShadow=false）\n"
        "  ⇒ apiRef 类型零改动。\n"
        "· 「双侧轮廓」真给 2 盏（120° + 240°，用户拍板不取巧）。\n"
        "\n【优先级（核心：两个 effect 绝不打架）】\n"
        "· Stage3D.tsx 的 lightPreset effect 加守卫 `stage3dLightingSeq === 0`：\n"
        "  未介入（seq=0）时 preset 完全生效（现状不变）；介入后（seq>0）preset 让位，\n"
        "  只保留 bg/fog/地面。⇒ 两 effect 顺序无关、幂等（逻辑互斥，非侥幸）。\n"
        "· 「移除灯位」投递 null ⇒ 恢复 lightPreset，不留残灯、不撒谎。\n"
        "\n【冻结区纪律（stage3d-core 12 → 14 文件 / 全库 91 → 93 锁点）】\n"
        "· 备份（主库 6 + 副库 4）→ 写新文件 → 接线（store ≤5 行 / Stage3D ≤12 行）\n"
        "  → frozen_zones.json 字符串手术（禁 json.dump，zone7 reason 5425 字符）\n"
        "  → --update 重锁 → 复跑 OK frozen zones intact (93 locks)。\n"
        "· 顺手修正 .cursor/rules/frozen-zones.mdc 既有的 90 vs 91 漂移（现统一 93）。\n"
        "· 未动：端口 18765/3011/3010、GLB 加载与 bodyFigureUrl、骨骼绑定、姿势应用、\n"
        "  材质渲染、画布预热时机、角色库 schema、磁吸任何阈值。\n"
        "\n【验证】\n"
        "· tsc 主库 38 → 38 逐文件一致（21 riggedHumanoid + 16 Stage3D + 1 infinite-compat）；\n"
        "  新文件 0 错误；副库 tsc -p tsconfig.app.json 同为 38（防 project references 假绿）。\n"
        "· vitest 26 → 27 文件 / 361 → 406 例全绿（新增 stage3dLighting.test.ts 45 例）。\n"
        "· vite build rc=0 且产物实测含 stage3d-rim-light 字面量（不是只看返回码）。\n"
        "· 新增 _verify/check_stage3d_lighting.mjs（真 three 场景端到端 43 项全过，已登记进\n"
        "  run_all_checks 的 LIGHT3D）—— 补 vitest node 环境测不到的 useEffect 部分。\n"
        "· **7 条反例逐条喂坏版本**确认守卫真会红（sin/cos 对调 / 删守卫 / consume 挪后 /\n"
        "  hook 提前 / 删轮廓 azimuth / kelvin 恒白 / 忘初始化 store）—— 守卫不是摆设。\n"
        "\n【已知未做】\n"
        "· 「头部捏脸」卡片（表情/发饰/妆容）是独立一刀，本次不碰。\n"
        "· 3D 场景灯位实体可视化（把 24 个灯画成场景里的可见体块）另立刀。\n"
        "\n【上一版 V4.43.19『LibTV 对标补强刀3：画布前端接线』见 docs/CHANGELOG.md。】"
    ),
}
