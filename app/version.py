__version__ = "4.46.7"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 7,
    "codename": "可移植推理底座（设备画像 / 后端注册 / 引擎遥测）+ 批量出图复用编码",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.7：用户指令「要为后面适配其他设备着想，而不是光适配现在的 4060」。\n"
        "把原本「按这台卡调好的参数」升级成「按设备能力位分派」。\n"
        "（注：V4.46.6『视频侧真本地双路 + 画布算力滑块』由并行会话落地，只加 CHANGELOG\n"
        "条目未改 version.py；本版在其之上做可移植底座，故版本号顺延到 4.46.7。）\n"
        "\n【① 设备画像 device_profile（新）】\n"
        "探测 vendor/arch/vram/能力位(fp16/bf16/fp8/int4/sdpa)/可选库(triton/xformers/\n"
        "torchao/nunchaku/diffsynth/diffusers)；支持 CUDA / ROCm / Apple MPS / CPU 四路。\n"
        "关键设计：`usable.fp8` = 硬件能力位 AND torchao 已装（缺一不可）；不认识的架构\n"
        "一律按不支持处理（不编造）。`SHIGUANG_DEVICE_PROFILE` 可注入假画像，测试无需\n"
        "第二台机器即可覆盖 5 类硬件；结果缓存 data/device_profile.json。\n"
        "\n【② 后端注册表 backend_registry（新）】\n"
        "diffsynth / diffusers / nunchaku / tensorrt 各自**声明**支持的架构、精度、最小\n"
        "显存与所需库；决策器只从注册表查候选 ⇒ 装不上的后端表现为「不在册」，而不是\n"
        "运行到一半报错。换设备/换依赖时无需改代码分支。\n"
        "\n【③ 引擎遥测 engine_telemetry（新，EPLB 对应物）】\n"
        "按 (设备指纹, 引擎, 模型架构) 记「首图耗时 / 稳态耗时 / 失败率」，EMA 平滑，落盘\n"
        "data/engine_telemetry.json。决策器按「失败率→首图→稳态」选栈；证据 n≥3 才用，\n"
        "否则退回保守默认。这直接消除「SDXL 首图 diffsynth 415s / diffusers 35s」被固定\n"
        "优先级稳定复现的问题。\n"
        "\n【④ 批量出图复用文本编码（KV cache 对应物）】\n"
        "diffusers_image.generate_batch()：同 prompt 出 N 张改用 `num_images_per_prompt`，\n"
        "文本编码只做一次（交给库内部正确处理 SD1.5 单编码器 / SDXL 双编码器 + pooled\n"
        "embeds；不手工拼 prompt_embeds 以免随版本漂移）。generate()/generate_batch()\n"
        "都把真实耗时写进遥测。\n"
        "\n【⑤ 决策器输出扩展】\n"
        "plan()/status() 新增 device / accelerators / engine_reasons；加速器只在\n"
        "「硬件支持 + 库已装 + 后端声明」三者同时满足时声明，绝不虚报。\n"
        "\n【实测依据】SD1.5 512²/20步：整卡 3.08s vs offload 4.17s（-26%）；步数\n"
        "20→4 步 3.17s→0.99s；SDXL 1024²/20步：diffusers 23.3s、diffsynth 稳态 20.6s\n"
        "但首图 415s。\n"
        "\n【验证】新增 test_device_portability.py 11 例（假设备注入覆盖 apple/amd/cpu/\n"
        "hopper + fp8 双条件）+ 既有 12 例裁定测试；全量 pytest 与 107 项门禁见 CHANGELOG。\n"
        "\n【遗留（诚实）】① 后处理重叠（DualPipe 对应物）未做；② FP8 只完成可用性判定\n"
        "与声明，未真正量化推理（torchao 未安装/未验证精度）；③ 守卫\n"
        "check_device_portability 未加（会改变体检项数，留待下一刀统一）。\n"
        "\n【上一版 V4.46.6『视频侧真本地双路』见 docs/CHANGELOG.md。】"
    ),
}
