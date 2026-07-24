"""
app/core/ai - AI 智能剪辑模块
==============================
整合 FunClip / videocut-skills / 黄金3秒 / 三翻法 思路，
对接本项目已有的 Ollama 客户端 + Whisper 字幕 + ffmpeg 切片。

子模块:
  - prompt_templates: 8 套智能剪辑 Prompt 模板
  - llm_clipper:     LLM 智能裁剪引擎（Ollama → 时间段 → ffmpeg）
"""

# 延迟导入，避免循环依赖
# 在使用时通过 from app.core.ai.prompt_templates import ...
#               from app.core.ai.llm_clipper import ...
