# -*- coding: utf-8 -*-
"""AI 精剪链路（§40.x）—— 只做接线，不重建既有能力。

设计依据
--------
现状诊断（2026-11-14）：
  · ``app/core/rough_cut_chain.py`` 已实现「提案 → 审核卡确认 → 写回 → compound 撤销」
    整条执行链，唯独第一环是**规则**排轨 + 水词/静音检测，不是看懂内容的模型。
  · ``app/core/text_frame_map.py`` 已实现字词/句 ↔ 帧的 SAFE_WORD 半开区间映射。
  · ``app/core/media_perception.py`` 已实现统一感知门面。
  · ``app/core/canvas_shot_vision.py`` 已实现按 start/end 抽帧 + 本地视觉模型解析。

⇒ 本包**不重写**上述任何一条链，只补三件它们之间缺的东西：
  1. ``intent``：意图/验收规格（决策目标函数 + 复核判据 + 记忆索引键）；
  2. ``semantic_table``：把感知结果收成**帧级可寻址**的语义镜头表（适配 A）；
  3. ``verify``：执行后按证据复核并回流记忆（适配 B）。

模型侧见 ``app/core/ai/vision_backends.py``（backend 抽象）与
``app/core/ai/editing_proposal_llm.py``（LLM 提案器，产出 rough_cut_chain 同形 proposal）。

铁律
----
· 一次决策 = 一个提案 = 一条 compound 撤销，复用既有 apply()，不另造事务层。
· 模型**永不直接输出帧号/时间坐标**，只输出 shot_id + 理由；坐标由 Python 侧
  从语义表编译，避免幻觉坐标改坏时间线。
· 默认全本地、云端视觉必须显式开关；任何失败诚实降级，绝不伪装成模型判断。
· 本包纯标准库（除可选延迟依赖），可离线单测，不 import Qt / 不碰冻结区。
"""
