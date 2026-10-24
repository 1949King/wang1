"""
app.core.neural — 神经网络推理模块集
====================================
提供统一的神经网络模型加载与推理能力。

子模块:
  - neural_engine.py:    统一推理后端 (ONNX + PyTorch)
  - super_resolution.py: 超分辨率 (RealESRGAN/ESPCN)
  - style_transfer.py:   风格迁移 (VGG/MosaicStyleTransfer)
  - background_replace.py: 背景替换 (MODNet/U2Net)
  - inpainting.py:       AI 修复 (LaMa)
"""
