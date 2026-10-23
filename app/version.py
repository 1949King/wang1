__version__ = "4.46.11"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 11,
    "codename": "修本地视频 fps 写死 24（各族按原生帧率编码，时长不再被压缩）",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.11：用户选「C：排查其它视频族的帧格式问题」。排查挖出的不是帧格式，\n"
        "而是一个更严重的既有 bug —— 编码帧率写死 24，导致除 minimax 外所有族\n"
        "输出视频播放过快、时长被压缩。ffprobe 实证后修复。\n"
        "\n【① 发现的 bug（静态审查 + ffprobe 实证）】\n"
        "_save_video_frames 把 fps 写死 24.0，但各族生成时 num_frames 都是按\n"
        "自己的原生帧率算的：minimax=24、wan/cogvideox/hunyuan/mochi=16、\n"
        "ltx=25、svd=7。⇒ 只有 minimax 恰好对得上，其余族「帧数按 A 帧率算、\n"
        "编码按 24 帧率写」⇒ 时长被压缩、播放过快。\n"
        "真机证据（V4.46.10 那轮 SVD 产物）：请求 duration=1s（7 帧 @7fps），\n"
        "ffprobe 实测 r_frame_rate=24/1、duration=0.29s ⇒ 快 3.4 倍。\n"
        "为什么一直没被发现：与帧格式 bug 同因 —— 视频族的真编码链路从没被测试\n"
        "覆盖过（并行会话 V4.46.6 测试明确「不加载模型」）。\n"
        "\n【② 修复】\n"
        "_save_video_frames 新增 fps 参数（默认 24 保持兼容）；7 个 _infer_* 各自定义\n"
        "_native_fps（取自本族算 num_frames 用的同一个系数，让编码器与帧数计算自洽，\n"
        "不是猜模型）并在 return 时传入。cv2 分支用 float fps、imageio 分支用 int。\n"
        "\n【③ 验证（决定性）】\n"
        "· 单测 test_save_video_frames_respects_fps：同 7 帧，fps=7 应≈1.0s、fps=24 应≈0.29s，\n"
        "  用 ffprobe 实测断言（ffprobe 不可用则 skip，不假绿）。3 passed。\n"
        "· 端到端真机：SVD duration=1 重生成 → ffprobe r_frame_rate=7/1、duration=1.000s\n"
        "  ✅（修复前 24fps/0.29s）。\n"
        "· 全量 pytest 1944 passed；run_all_checks 107 项；frozen_zone_guard 106 锁。\n"
        "\n【④ 顺带修测试自己的 bug】\n"
        "新加的 fps 测试首跑被 skip：第二个输出写到不存在的子目录，cv2 静默写失败\n"
        "（返回 ok=True 却没文件）⇒ ffprobe 读不到。补 mkdir + 断言文件真实落盘。\n"
        "这暴露 cv2.VideoWriter 的坑：目录不存在时不报错、只产不出文件。\n"
        "\n【遗留（诚实）】\n"
        "· 帧格式本身（PIL vs numpy）：minimax/wan 等族的 raw_frames 归一化路径\n"
        "  已能处理（list/cpu tensor 分支），但只有 SVD 被真机跑过，其余族仍未经端到端\n"
        "  生成验证（权重不在盘）；_native_fps 是按各族 num_frames 系数定的，若某族\n"
        "  实际原生帧率与其 num_frames 计算不符，需真机跑过才能发现（现有信息下自洽）。\n"
        "· 常驻复用（V4.46.10 的 pipe cache）仍只接了 SVD，其余族未接。\n"
        "\n【上一版 V4.46.10『视频侧用法感知·SVD 常驻复用 -39%』见 docs/CHANGELOG.md。】"
    ),
}
