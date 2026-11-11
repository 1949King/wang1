# GGUF 量化栈（2026-11-01，`app/core/neural/`）— 从 MEMORY.md 拆出

- 三个文件：`gguf_quants_torch.py`（内核，8 类）+ `gguf_loader.py`（读取 + LDM→diffusers）+ `gguf_lazy.py`（逐层懒反量化）。
- 🔴 **已接进生产路径**：`DiffusersImageEngine.request_gguf(path)` / 环境变量 `SHIGUANG_GGUF` → `load()` 内装填。真机验收 686 层 / Q8_0 / 装填 20.9s / 出图 4.0s（512²·20 步）；路径不存在 ⇒ `ok=False` 写明路径（**不静默退回 fp16 假装量化**）。GGUF 与 fp8 互斥，GGUF 优先。
- 🔴 **numpy 反量化不可用**（约 50 M元素/s ⇒ 全 SDXL UNet 30 步 11.4 分钟），必须用 torch GPU 版（快 606×）。
- 🔴 **GGML 以 ne[0] 为最内维** ⇒ 读时 `reshape(ggml序)` 后必须 `permute` 回来；**只 reshape 不 permute = 形状对、元素串位、安静 load 成功、画出噪点**。
- 🔴 **`convert_ldm_unet_checkpoint` 期望输入带 `model.diffusion_model.` 前缀**（内部 `key.startswith(LDM_UNET_KEY)`）；提前剥 ⇒ 空字典 ⇒ 误判「架构不匹配」。方向是**补齐**。
- 内核已逐元素对齐 numpy 权威实现（F32/F16/BF16/Q4_0/Q5_0/Q8_0/Q4_K/Q6_K 全 rel=0）；gguf-py 的 K-quant **正向量化未实现** ⇒ 对照用「自打包字节 → 官方 numpy 反解 vs torch 反解」。
- 显存账（SDXL UNet 2.39G 参数）：fp16 4.78GB → Q8_0 2.54 / Q6_K 1.96 / Q4_K 1.34GB。**eager 只省硬盘**；lazy 实测 SD1.5 峰值 2.81→**1.07GB（省 62%）**、慢 2.63×、与 eager **逐位相同**。
- 🔴 **PSNR 量不了扩散量化**：不用量化、只给 fp16 加 0.4% 噪声，同 seed PSNR 仅 **14.12dB**（比 GGUF Q8_0 的 17.14 更低）⇒ 十几 dB 是扩散去噪的固有放大。判量化看**低频(8×) PSNR**（`is_admissible_diffusion`，门槛 20dB）+ 肉眼。gguf_q4_k 缺低频证据 ⇒ 登记不启用。
- 🔴 **FP8 在本机真可用，别再引「无加速」旧结论**：真因是 torchao 0.16.0 的 cpp extensions 没编译，不是 CUBLAS 不支持 sm89。降到 **torchao 0.12.0** 后出图**快 10%**、显存 **-9.6%**（只量化 nn.Linear）。
- 🔴 **SageAttention Windows 需三件套**（triton-windows + MSVC + CUDA Toolkit 的 `cuda.h`，本机**没有** cuda.h，`torch/cuda.h` 不能替代）；PyPI 包是纯 Triton 实现。**门槛过高 ⇒ 不进主路径**。
- 🔴 **`from app.core import sub as x` 会绕过 `sys.modules`**：包上已有该属性时 `_handle_fromlist` 直接取属性 ⇒ 测试 monkeypatch 不生效还静默用真模块。要可替换就写 `from app.core.sub import name`。
