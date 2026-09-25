"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.39.8"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 39,
    "patch": 8,
    "codename": "优秀三件事①：画布生成异步化（generateForNode → runGeneration）",
    "release_date": "2026-09-26",
    "description": (
        "V4.39.8: 代码评价报告「距离优秀只差三件事」之第一件事落地——"
        "画布主生成路径从同步阻塞改为异步任务化（submit → 轮询 → 终态映射），"
        "可取消、有诚实进度。"
        "★ bridge.ts 接线层改造：generateImageViaHost / generateVideoViaHost"
        " 新增可选 awaitOpts（signal/onProgress/timeoutMs/maxAttempts），"
        "count==1 分支从同步 POST /host/generate-image 改走 runGeneration；"
        "count>1 批量循环自动继承。服务端 _GEN_PAYLOAD_KEYS 白名单与旧同步端点"
        "逐键一致（已核对 image 7 键 / video 10 键），_build_gen_callable 为"
        "保真搬运（画质换算 / NG 计数 / GFPGAN 预载 / 后处理注册全保留），"
        "GFPGAN 预载轮询块原样保留。不传 awaitOpts 的老调用点行为完全不变。"
        "★ 失败/取消语义映射：任务 failed → {ok:false, message:上游原文}；"
        "AbortError → {ok:false, message:'已取消'}，与旧返回形状兼容。"
        "★ App.tsx 诚实进度 + 取消：onGenerate 持 AbortController，"
        "onProgress 如实上报（progress 为 null 只显示「阶段 · 已用时 Ns」，"
        "绝不编造百分比；有真值才写节点 progress）；「中断」按钮复用为"
        "取消在飞任务（单节点 + 批量当前节点，后端任务一并取消）；"
        "已取消节点回 idle 不亮红。批量生成每个在飞节点同样可被取消。"
        "★ 测试：bridge.test.ts 新增 5 个异步接线用例（payload 键一致性/"
        "失败映射/取消映射/视频透传），10/10 绿；全套 8 文件 76 断言逐文件"
        "跑全绿；tsc 主库 37 冻结区基线零新增、副库 0 错；双库检查无新增漂移"
        "（bridge.test.ts 顺带收敛，副库缺失 7→6）。"
        "★ 双库同步：bridge.ts / App.tsx / bridge.test.ts 已逐字节同步至"
        " vendor/AI-Canvas-tauri/src/libtv/。"
        "注：canvasVersion.ts 整文件冻结，画布版本号三件套待解冻后补。"
    ),
}
