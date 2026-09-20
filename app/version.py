"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.37.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 37,
    "patch": 0,
    "codename": "异步任务模型 · submit / status / cancel",
    "release_date": "2026-09-21",
    "description": (
        "V4.37.0: 按升级任务清单落地 P1-3 异步任务模型——全链路执行从"
        "「一发不可取消的阻塞调用」升级为「可查询、可取消的后台任务」。"
        "★ 复用而非重建：新模块 app/core/ai/pipeline_jobs.py 把全链路包成任务，"
        "任务表直接复用 canvas_gen_jobs（画布生图/生视频/生音频同一张表），"
        "Agent 与画布统一任务视图；状态机/协作式取消/诚实进度/并发限流零重复造。"
        "★ 取消穿透到生成深处：取消令牌走线程局部（gen-jobs 绑定），"
        "client.generate 在入口/provider 尝试间/占位段间逐段检查，"
        "pipeline.execute 在场景间/回溯重试间检查；client/orchestrator/dispatcher"
        "三处 catch-all 补 except GenCancelled: raise 放行（取消是控制流不是失败）；"
        "正在跑的单段不打断（诚实降级），取消后结果一律丢弃不落盘。"
        "★ 进度上报零签名改动：StageReporter 同样线程局部注入，管线深处经"
        "pipeline_stage/pipeline_progress 上报真实信号（生成 i/N），不伪造平滑百分比。"
        "★ Agent 三能力四处接线：pipeline.submit（危险动作，生成线花钱需确认）/ "
        "pipeline.job_status（单查+列表+队列统计，done 附完整结果=fetch 语义）/ "
        "pipeline.job_cancel（排队真取消，运行中段间生效）。"
        "★ 面板任务化：全链路按钮改走 submit+QTimer 轮询，新增「⏹ 取消」按钮"
        "（仅任务运行期可见）；预览等待不再是假失败（done+paused，安静收尾等确认续跑）；"
        "单任务守卫防重复启动；终态统一回 _on_full_pipeline_done（口径不变）。"
        "★ 诚实语义：全链路失败时任务层丢弃详细 output、只保留 error（与旧路径口径"
        "一致）；max_attempts 恒 1——管线级自动重试=双倍花钱，重试交给段内回溯+额度池换号。"
        "验证：check_pipeline_jobs 39 项全过（含取消穿透两层深度、终态幂等、"
        "四处接线）；run_all_checks 38 项除已知历史项（GUARD/styles.css 基线漂移，"
        "待决策）外全通过。"
    ),
}
