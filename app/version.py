__version__ = "4.46.18"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 18,
    "codename": "统一推理引擎 M5 · Wan2.1 真机验收（登记即接入跑通）",
    "release_date": "2026-10-25",
    "description": (
        "V4.46.18：统一引擎路线收官刀——用真实新模型（Wan2.1-T2V-1.3B，26.95GB，\n"
        "ModelScope 通道）验收「登记即接入」协议。结论：协议成立，但验收过程暴露并\n"
        "修掉了 ③ 手写族从未跑过的四个坑（这正是它们此前 unverified 的价值）。\n"
        "\n【① 真机验收产物】\n"
        "17 帧 480² 20 步 = 58.5s（offload，8GB 卡），ffprobe 1.0625s = 17/16（fps 语义正确），\n"
        "帧间差 32.4（真运动），目视：橙猫草地上走、语义与 prompt 一致、画质干净。\n"
        "wan 族 verification 升 VERIFIED，实测数据（58.5s/两阶段/仅 T2V）写进登记 note。\n"
        "\n【② 修掉的四个坑（_infer_wan 此前从未真跑过）】\n"
        "1. 类名 WanVideoPipeline 在 diffusers 0.40 根本不存在（真名 WanPipeline）；\n"
        "   同查同修 LTXVideoPipeline ⇒ LTXPipeline。守卫新增 E 项：PIPELINE_CLASS_MAP\n"
        "   全部类名必须 dir(diffusers) 真实存在（反向验证过牙齿：假名必被抓）。\n"
        "2. num_frames 必须 4k+1（时序 VAE 4× 压缩）——原 int(duration*16) 给 16/32/80\n"
        "   全不合法 ⇒ 新增 _wan_num_frames（就近取 4k+1）。\n"
        "3. 宽高必须被 16 整除（patch_size 2 × VAE 8×）——488 被 check_inputs 拒 ⇒\n"
        "   新增 _wan_div_size（向下取整到 16 倍数）。\n"
        "4. RAM 墙：全家桶 bf16 ≈16.4GB > 本机 15.29GB，一次 from_pretrained 必被硬杀\n"
        "   （实测加载后可用仅剩 1.00GB）；且 WanPipeline.from_pretrained 不支持\n"
        "   device_map（实测只认 balanced/cuda/cpu）⇒ 生产路径改两阶段：\n"
        "   UMT5 模型级 device_map 分层编码（编完即释放，embeds 仅 0.83MB）→\n"
        "   无编码器管线（text_encoder=None）只载 transformer+vae 生成。\n"
        "\n【③ 花屏根因（本轮最贵的发现）】\n"
        "前两版产物是噪声（绿块/彩斑）。逐层排除（embeds 数值健康 → scheduler 配置正确\n"
        "→ dtype 改 bf16 仍噪）后读官方 _get_t5_prompt_embeds 源码定位：embeds 必须复刻\n"
        "官方契约——裁到真实长度 + 补【精确零】到 512。分开编码再 zero-pad 到 53 是错的：\n"
        "padding 位算出的非零垃圾会污染 cross-attn 条件（1 步前向对照实测：垃圾 pad 与\n"
        "官方形状输出差 0.265，比全零还远）。修后立刻出猫。教训：传 prompt_embeds 走\n"
        "捷径时，契约必须逐位复刻官方，不能近似。\n"
        "\n【④ I2V 诚实拒绝】盘上只有 T2V 权重（无 image encoder）⇒ _infer_wan 收到\n"
        "reference_image 时在任何重导入之前就明确拒绝并说明缺什么（fail fast + 0xC0000005\n"
        "纪律：测试里绝不触发 diffusers lazy 面，拒绝路径用假模块占位验证过不 import）。\n"
        "\n【⑤ 权重管理】ModelScope 通道 26.95GB 落盘 app/models/cache/ 下\n"
        "Wan-AI_Wan2.1-T2V-1.3B-Diffusers（已 gitignore）；归位到项目约定目录后\n"
        "_scan_local_models 自动发现（kind=wan），注册表 weight_probe 同步生效。\n"
        "\n【验证】新增 6 例（test_wan_m5.py）；全量 pytest 1984 passed；run_all_checks\n"
        "109 项全绿（守卫 E 项新增）；frozen 106 锁；ruff 棘轮零新增。\n"
        "\n【上一版 V4.46.17『统一推理引擎 M4 · 入口合一』见 docs/CHANGELOG.md。】"
    ),
}
