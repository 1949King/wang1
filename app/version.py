__version__ = "4.47.1"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 47,
    "patch": 1,
    "codename": "补丁：主题切换收敛为单一机制，修复设置页浅底浅字",
    "release_date": "2026-11-27",
    "description": (
        "V4.47.1 补丁（2026-11-27）：主题切换收敛为单一机制（只由 ThemeManager\n"
        "驱动，所有入口统一回调各模块），修复标题栏主题按钮后设置页「浅底浅字」、\n"
        "分组标题发浅、切回深色留白框、主题下拉框不同步。\n"
        "\n【以下为 V4.47.0 基线说明】\n"
        "V4.47.0：把 DeepSeek 三项推理理念（MLA 低秩压缩 / PagedAttention 块池与前缀\n"
        "缓存 / MoE 按需卸载）移植进自研 diffusers 栈，全部收敛在单一新文件\n"
        "app/core/neural/inference_cache.py，主引擎只做薄接线。设计依据：\n"
        "docs/_reports/2026-10-24-DeepSeek推理理念移植至diffusers栈设计方案.md。\n"
        "\n【五组件】\n"
        "① StepFeatureCache（DeepCache 移植）：up_blocks 实例级 forward 包裹 + 步间\n"
        "   特征缓存，interval/branch_id 可调；第 1 步必全量 ⇒ 误差不跨缓存周期累积；\n"
        "   detach 全还原（漏一个 = 下次 generate 双倍短路，单测锁死）。\n"
        "② LowRankFeatureCache（MLA 移植）：缓存特征低秩（svd_lowrank）+ 重建。\n"
        "   **实测修正设计稿**：真实 U-Net 尾部有 GroupNorm（conv_norm_out），秩投影\n"
        "   过不了归一化 ⇒ 吸收式折叠只对 conv_norm_out is None 变体生效；真实\n"
        "   SD/SDXL/SVD 走「压缩存储 + 复用步一次重建」，零解压税留给无 norm 结构。\n"
        "③ EncoderOutputCache（前缀缓存对应物）：文本编码输出 LRU 双闸（条数+字节），\n"
        "   键含 arch/model_id/prompt/negative/lora_set/max_length（少一个字段 = 换\n"
        "   LoRA 出旧图级 bug）；VRAM 感知驻留（宽裕驻 GPU、吃紧驻 CPU）。\n"
        "④ VramBlockPool：固定块 size-class 池 + 字节账 + 零拷贝 view 往返。\n"
        "⑤ release_vram_sequence：卸载序列单一真源（先断引用 → gc → synchronize →\n"
        "   empty_cache → ipc best-effort），治 2026-10-22 实测的 SD1.5→SDXL 重载\n"
        "   碎片卡死 >22min。\n"
        "\n【接线（薄层）】diffusers_image 新增 _t2i_image 四态 off/hit/miss/fallback\n"
        "（门控不用异常做控制流——稳定性门禁红线：except 块体仅含 pass 属吞异常）；\n"
        "video_gen 增 _attach/_detach_step_cache 门控挂载 + 遥测；local_video_pipe_cache\n"
        "的 _dispose/_gc_release 双真源拆错位（引用未断时 empty_cache 空转）收口为\n"
        "_release_vram。\n"
        "\n【门控纪律】默认关、显式开（SHIGUANG_STEP_CACHE=deepcache /\n"
        "SHIGUANG_ENCODER_CACHE=1）；arch 白名单 sd15/sdxl/svd（wan 等 DiT 不进——\n"
        "FBCache 是另一条探针，不冒充）；final/best 永不开；任何一步失败诚实回退。\n"
        "\n【验证】test_inference_cache.py 45/45 passed（无 GPU 依赖，假 UNet/假 pipe/\n"
        "CPU 张量，反例纪律）；ruff 全绿 · precommit 14 道 · stability 251/251 ·\n"
        "neural 区不在冻结区（新文件无登记负担）。真机标定（offload 净收益/编码耗时差/\n"
        "低秩三档画质）属下一轮（n≥3 + 反例 + 回退路径），验证前默认关不变。\n"
        "生效面诚实说明：diffsynth_engine 0.7.0 在装 ⇒ 日常生成默认走主引擎，本套件\n"
        "服务 builtin 兜底段与显式选自研（execution_decider「自研」switch）。\n"
        "\n【上一版 V4.46.26『画布黑屏真凶 + 插件假产物』见 docs/CHANGELOG.md】"
    ),
}
