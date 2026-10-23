__version__ = "4.46.8"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 8,
    "codename": "质量档位（final/high/fast）+ LCM-LoRA 安全装载 · 实测标定",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.8：用户要求「不要为省时间牺牲太多画质，要能到 SD 引擎 90%~95% 的质量，\n"
        "同时只花 40%~50% 的时间」。本版把这件事**量化、标定、做成档位**。\n"
        "\n【① 先说硬结论（都实测）】\n"
        "· SDXL fp16 加载后显存空闲 = **0.00GB**（8GB 卡被权重占满）⇒ offload 是强必需，\n"
        "  整卡直载 + attention slicing 也装不下（脚本有显存预检，直接如实报「装不下」）。\n"
        "· 批量摊薄固定开销也走不通：1024² 批量 N=2 在 8GB 上换页卡死（>8min），\n"
        "  开 attention slicing + vae tiling 仍然卡死 ⇒ **本机只剩「降步数」一条路**。\n"
        "· 耗时构成：固定开销 6.2~7.4s（文本编码 2.24s + 模块搬运 + VAE 解码），\n"
        "  占单张 25s 的 28% ⇒ 这决定了「降到 50%」的理论下限。\n"
        "\n【② 实测标定（SDXL 1024² · 4060 8GB · offload；基线 20步 cfg7.5 = 24.99s）】\n"
        "  LCM 8 步 cfg1.0 : 12.84s（51%）· CLIP 对齐 29.33 vs 基线 29.68（≈99%）\n"
        "  LCM 12 步 cfg1.0: 13.92~14.88s（56~60%）· CLIP 28.82（≈97%）\n"
        "  DPM++ 2M 12 步  : 17.84s（71%）· CLIP 28.94（97.5%）\n"
        "  10 步 cfg7.5    : 15.91s（64%）· CLIP 29.24（98.5%）\n"
        "  ★ 诚实提醒：CLIP 只测「图文语义对齐」，测不出 LCM 的**发虚/细节丢失**。\n"
        "  目视结论：LCM 4~8 步适合草稿/抽卡，DPM++ 12 步接近满质量但只到 71%。\n"
        "\n【③ 落地：质量档位】diffusers_image.QUALITY_PRESETS\n"
        "  final = 20 步（不动，满质量）· high = DPM++ 12 步 · fast = LCM 8 步(SDXL)/DPM++ 8 步(SD15)\n"
        "  generate(..., preset='fast'|'high'|'final')；未知档位一律退回 final（宁慢不糊）。\n"
        "\n【④ LCM 安全装载（三个坑都实测过，写进代码注释与测试）】\n"
        "  ① offload 管线上直接 load_lora_weights → 卡死 >7min\n"
        "  ② 整卡跑 1024² → SDXL 权重占满 8GB，换页卡死\n"
        "  ③ fuse_lora() 要复制 6.5GB 权重 → 8GB 卡必卡\n"
        "  正确顺序：卸 offload → 整卡装载 LoRA(2.3s) → **不 fuse** → 重开 offload。\n"
        "  缺 peft / 缺权重 / 非 SDXL 架构 ⇒ 一律 ok=False 并给原因，绝不静默降级。\n"
        "\n【⑤ 验证】新增 test_quality_presets.py 8 例（档位表自洽/未知回落/LCM 诚实失败/\n"
        "无管线安全）；全量 pytest 与门禁见 CHANGELOG。新增依赖 peft 0.21.2（已装；\n"
        "pip 默认源会卡，用清华镜像 4.1MB/s）。\n"
        "\n【遗留（诚实）】① LCM 的 fast 档在**目视**上未达 90% 画质（CLIP 达标但发虚）；\n"
        "② Hyper-SD（少步质量更好）ModelScope 无镜像、HF 被墙，本机拿不到；\n"
        "③ SD1.5 版 LCM-LoRA 同样无镜像，故 SD1.5 的 fast 走 DPM++ 8 步（实测 1.55s≈49%）。\n"
        "\n【上一版 V4.46.7『可移植推理底座』见 docs/CHANGELOG.md。】"
    ),
}
