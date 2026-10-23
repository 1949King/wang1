__version__ = "4.46.10"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 10,
    "codename": "视频侧用法感知（SVD 管线常驻复用 -39%）+ 修 SVD 出片必崩的既有 bug",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.10：用户指令「视频侧同样做用法感知策略」。做完，并顺带挖出一个\n"
        "让 SVD 本地出片此前**必崩**的既有 bug（真机验证暴露）。\n"
        "\n【① 视频侧用法感知 = 进程级管线常驻（不是图像侧的整卡热提升）】\n"
        "SVD 实测「offload 全程不亏、不能整卡」（V4.46.0 血泪调优，本刀一个参数没动），\n"
        "所以它的固定开销**不在搬运，而在每次 from_pretrained 重载 4.2GB 权重**。\n"
        "新增 app/core/local_video_pipe_cache.py：按 (kind, model_path) 把已就绪的\n"
        "pipeline 缓存在进程内（LRU 上限 1，可环境变量放宽），第二次起直接复用。\n"
        "真机实测（SVD i2v · 4060 8GB · 1s/7帧/8步）：\n"
        "  第1次 58.73s（miss：加载+推理）· 第2次 35.68s（hit：只推理）⇒ 省 23.05s（39%）\n"
        "OOM 时自动 evict 缓存（下次重载干净管线），只认 OOM、其它异常原样上抛。\n"
        "\n【② 修既有 bug：SVD 本地出片此前必崩（真机暴露）】\n"
        "_save_video_frames 在 cv2 分支先读 frames[0].shape 取尺寸，但 SVD 的\n"
        "result.frames[0] 是 PIL.Image（无 .shape）⇒ 只要装了 cv2（本项目装了），\n"
        "SVD 出片就抛 'Image' object has no attribute 'shape'，且下面能处理 PIL 的\n"
        "imageio 分支永远走不到。修复：取尺寸前先 np.array(frames[0]) 归一化。\n"
        "为什么一直没被发现：并行会话 V4.46.6 的测试只测 resolve_image_path（明确\n"
        "「不加载模型、不联网」），从没覆盖真编码链路 —— 典型「测试没打到的主路径」。\n"
        "补两条回归锁 test_local_video_save_frames.py：PIL 帧 + numpy 帧都能出真 mp4。\n"
        "\n【③ 可观测】_infer_svd 结果新增 pipe_source（hit/miss），供排障与后续遥测。\n"
        "\n【验证】新增 test_local_video_pipe_cache.py 6 例（命中/未命中/LRU/失败不缓存/\n"
        "evict/status/并发只加载一次）+ test_local_video_save_frames.py 2 例；并行会话的\n"
        "test_local_video_first_frame.py 4 例仍全过（改动没打破）；真机验证见上。\n"
        "全量 pytest 与 107 项门禁见 CHANGELOG。\n"
        "\n【遗留（诚实）】① 缓存只在进程内，重启即失效（桌面应用可接受）；\n"
        "② LRU 上限默认 1，多模型交替用会反复重载（如需可调 SHIGUANG_VIDEO_PIPE_CACHE_MAX）；\n"
        "③ 只给 SVD 接了缓存，其它 i2v/t2v 族（wan/cogvideox/…）尚未接（它们各有权重路径，\n"
        "接入方式相同但需逐个验证，未做）。"
        "\n【上一版 V4.46.9『用法感知显存策略·图像侧』见 docs/CHANGELOG.md。】"
    ),
}
