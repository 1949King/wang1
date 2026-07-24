# 拾光剪影 — 项目长期记忆（核心事实）

## 一、产品北极星闭环（原始意图，所有优化的终极标尺）

用户最初的产品意图是一条 **7 阶段自动闭环**，而非单点剪辑工具：
1. **AI 精剪辑** → editor_module（已建，待优化）
2. **人工修改** → editor UI（已建）
3. **AI 生成文案/话题/标题** → copywriting 模块（已建）
4. **发布到视频平台** → account 模块·自动发布（已建，默认关）
5. **获取播放/点赞/评论数据** → account_analyzer.py（已建，采集）
6. **AI 给出优化建议** → viral_optimization_engine.generate_optimization_suggestions（**已建真引擎**，未接入 UI 闭环）
7. **下一步选题走向** → viral_optimization_engine.analyze_viral_genes / 短剧筛选 drama（已建）

**关键判断**：7 个阶段代码都已存在，但彼此割裂成孤岛，未连成端到端闭环。
最大缺口不是"缺功能"，而是"5→6→7→1 的反馈回路未接线"。

**优先级地基原则（用户明确）**：剪辑模块是地基、是重点使用的功能；AI 功能是给剪辑辅助的。没有完整剪辑编辑能力，AI 精剪和后续闭环都无从谈起。
→ 顺序锁定：**先剪辑（稳→快→全→可维护），后 AI 闭环**。剪辑地基 4 层（从下往上）：
  ①敢动：清创（删死代码 + 36 吞异常改日志）——都发生在 editor_module.py 内部 **【已完成】**
  ②不卡：GPU 预览管线（QVideoSink+OpenGL，解决滤镜卡顿）← 下一步
  ③完整：接线 core 已有功能（keyframe_animation/speed_ramping/waveform/lut_loader/mask_system）
  ④可维护：拆 editor_module 上帝类为 6 模块
  顶层：AI 闭环（account 发布默认开 + viral_engine 接入 + 反馈回路 5→6→7→1）

## 二、代码健康度基线（2026-07-22 审查；清创后更新）

- editor_module.py：8517 → **7468 行**（第①层清创已执行，备份 .workbuddy/backup/editor_module.py.bak-2026-07-22）
- 死代码：~~1300 行~~ **已删 1049 行**（6 个零调用旧 UI 方法；原区间内 5 个活方法已保留——AI页 4 process + 导出页 _create_params_tab。规律：活的用 `_make_` 前缀、死的用 `_create_` 前缀）
- 吞异常：~~36 处~~ **已全部改 logger.warning**（统一文案"操作异常（已忽略）: %s"，可全局搜索）
- GPU 预览空转（gpu_acceleration._render_with_cuda 仅 asarray→asnumpy），滤镜卡顿根因；导出 nvenc 正常 ← 第②层待做
- **纠正**：gpu_render.py 不是"两份都孤儿"——modules/render/ 那份被 render_manager 用在导出路径（保留）；lego/render/ 那份挂在死分支（render_performance_optimizer 无外部调用方）
- 7 特效插件（action/comedy/dark_tone/gold_rush/highlight/soft_light/horror）结构逐字复制，可合并为参数化插件

## 三、用户工作习惯与偏好

- 核电管工转 AIGC；简体中文；指令极简（"开始""继续"）；偏好先看结论再展开
- 讲解要"小白模式"：比喻 + 逐行；结构化表格 + 进度报告
- 迭代模式：开始规划→确认"开始"执行→收汇总说"继续"
- 拒绝随机效果；前端动画与后端引擎逻辑必须强绑定
- 偏好彻底清理（一次性删过期文件，不选择性保留）
- 情绪化表达不满时不回怼，专业耐心推进
