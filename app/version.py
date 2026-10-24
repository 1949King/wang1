__version__ = "4.46.12"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 12,
    "codename": "本地视频编码链路守卫（帧数↔fps 自洽 + 真产物断言），把两轮教训变机器护栏",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.12：把 V4.46.10 / V4.46.11 连着挖出的两个「有提交、有测试、实际出片必坏」\n"
        "的 bug 固化成机器守卫 —— 不靠下一个人记得查。\n"
        "\n【根因（两个 bug 同一个病）】\n"
        "  · 暴露①：SVD 出片必崩 —— _save_video_frames 在 cv2 分支先读 frames[0].shape，\n"
        "    而 SVD 给的是 PIL.Image（V4.46.10 真机验证发现）。\n"
        "  · 暴露②：fps 写死 24，而各族 num_frames 按自己原生帧率算（SVD=7、wan=16…）\n"
        "    ⇒ 除 minimax 外所有族时长被压缩（SVD 实测快 3.4 倍，V4.46.11 修复）。\n"
        "  两者能潜伏至今的共同原因：视频族的真编码链路从没被测试覆盖过 —— 并行会话\n"
        "  V4.46.6 的测试文件头明确写「不加载模型、不联网」，只测 resolve_image_path。\n"
        "  功能看起来有测试，实际出片既崩又时长错。\n"
        "\n【新增守卫 _verify/check_local_video_encode_chain.py（纯 AST/正则，不碰 GPU）】\n"
        "  A 编码函数必须有 fps 形参（禁止写死帧率）；\n"
        "  B 每个 _infer_* 族：其 num_frames 乘数 K 必须与 _native_fps 相等，且调用编码时\n"
        "    必须传 fps=_native_fps —— 帧数怎么算 与 按什么帧率写 必须自洽（当前 7 族全过）；\n"
        "  C 编码链路测试必须有真产物断言（ffprobe/getsize）且必须断言 fps 改变时长\n"
        "    —— 防止有人把测试删回只测不加载模型那一层；\n"
        "  D 自检：守卫必须能抓出 4 类反例（缺 _native_fps / 未传参 / 不自洽 24vs7 /\n"
        "    有值却没传），且正例必须放行（不过严）。\n"
        "\n【入册】挂进 run_all_checks（tag=VIDEOCHAIN），体检 107 → 108 项。\n"
        "  项目注释早就写明：新守卫不挂进 run_all_checks = 看起来有守卫、实际没守卫\n"
        "  （arch_guard 空转、frontend_quality 纯摆设均是同病）—— 所以必须入册。\n"
        "  文档数字同步：接手速查卡 / 零基础学习路径 的「107 项」→「108 项」。\n"
        "  ★ 注意「107 把锁」（冻结区锁数）与「107 项」（体检数）是两个不同含义恰好\n"
        "    同数字，本次只改体检数，锁数不动。\n"
        "\n【验证】守卫 13 项检查全过（含 5 项自检）；DOCNUM 全绿；全量 pytest 1944 passed；\n"
        "run_all_checks 108 项全绿；ruff 棘轮零新增；frozen_zone_guard 106 锁。\n"
        "\n【附带发现（未修，报告用户）】接手速查卡/零基础文档里「1,765 例测试」也过时\n"
        "（现 1944），但 DOCNUM 不校验该数字，未擅自扩大改动范围。\n"
        "\n【上一版 V4.46.11『修本地视频 fps 写死 24』见 docs/CHANGELOG.md。】"
    ),
}
