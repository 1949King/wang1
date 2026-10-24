__version__ = "4.46.14"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 14,
    "codename": "统一推理引擎 M1 · 模型族注册表（协议层落地）",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.14：用户拍板「把三条线合并成一条，做支持市面模型的统一引擎」。本刀交付\n"
        "统一引擎路线的 M1（协议层）：设计稿 + model_family.py + 测试 + 守卫入册。\n"
        "\n【① 侦察修正：不是三条线，是四条线（全部 file:line 实测）】\n"
        "  ① diffsynth_image（图像主选）② diffusers_image（图像备选）\n"
        "  ③ local_video_infer（手写 7 族，仅 svd 真机跑过）④ video_gen（SVD·diffsynth 通道）\n"
        "  病根：SVD 在 ③④ 各一份实现（双轨漂移）；③ 的 6 个未验证族在 UI「看起来可选」；\n"
        "  选路逻辑三处重复；能力宣称无准入校验。\n"
        "\n【② 新模块 app/core/neural/model_family.py（~250 行，纯 stdlib 顶层）】\n"
        "ModelFamilySpec 声明表（9 族）+ resolve()：族→后端的唯一裁定 =\n"
        "  声明 ∩ 后端健康（find_spec 级，不 import 重库）∩ 权重在盘（惰性探测）。\n"
        "协议级承诺：SVD 唯一归属 video_gen（TUNED 真源，③ 的 _infer_svd 记为历史双轨待 M3）；\n"
        "验证三态 verified/unverified/blocked（对齐 engine_registry 的 library-only 法条：\n"
        "unverified 不得进默认可选）；native_fps 上收 V4.46.11/12 实测纪律（svd=7 等）；\n"
        "查无族 ⇒ ok=False + 「先登记」原因（svd 漏登记误杀视频路径的同类错误成为显式结论）。\n"
        "与三个既有注册表分工写明：backend_registry=后端健康输入 / engine_registry=观测视图 /\n"
        "本表=调度协议真源，字段正交不硬合。\n"
        "\n【③ 守卫 _verify/check_model_family.py 入册 108→109（8 项含 3 自检）】\n"
        "A 后端 id 可解析（AST，防 svd 类漏登记）· B native_fps 与执行代码 num_frames 系数\n"
        "自洽（复用 V4.46.12 成熟做法）· C 默认可选纯净 · D 反例自检（拼错/不自洽必抓、正例放行）。\n"
        "\n【④ 本轮实测否决清单（写进设计稿 §5，防止反复重议）】\n"
        "  FP8/torchao：装 0.7.0 实测 0/743 Linear 被量化、权重 4.78→4.78GB、白耗 228s，\n"
        "    且 float8_weight_only 源码注明 matmul 以原精度计算 ⇒ 对 SDXL 死路，已卸载\n"
        "    （防 usable.fp8 误报；卸载后判定回到 False，环境完好 torch 2.6.0+cu124）。\n"
        "  C++ 重构：profiler 实测 GPU kernel 占墙钟 97.6%（SD1.5 4步 983.8ms/1008ms），\n"
        "    CPU self 大头是 .item() 同步等待（换语言省不掉）⇒ 收益上限 <5%，否决。\n"
        "  DeepCache 官方包：SD1.5 2.22×（2.75→1.24s）、SDXL+offload 仅 1.27×（热噪声内），\n"
        "    U-Net 专属 ⇒ 对「通用引擎」目标泛化性低，缓做（设计稿 M5 后再议）。\n"
        "  TeaCache：官方支持列表无 SDXL/SD1.5（DiT 专用），排除维持。\n"
        "\n【⑤ 设计稿】docs/_reports/2026-10-24-统一推理引擎架构设计稿.md：\n"
        "M1 协议层（本刀）→ M2 后端收编 → M3 SVD 归一（动生产路径，带遥测回退）→\n"
        "M4 入口合一 → M5 新模型验收。每阶段独立可交付、旧签名全程不变。\n"
        "\n【验证】新增 10 例（test_model_family.py）全过；守卫 8 项全绿；\n"
        "全量 pytest 1967 passed；run_all_checks 109 项全绿；frozen_zone_guard 106 锁；\n"
        "ruff 棘轮零新增；DOCNUM 同步（接手速查卡/零基础 108→109）。\n"
        "\n【上一版 V4.46.13『常驻缓存的跨引擎内存礼貌』见 docs/CHANGELOG.md。】"
    ),
}
