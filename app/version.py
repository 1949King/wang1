__version__ = "4.46.16"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 16,
    "codename": "统一推理引擎 M3 · SVD 驻留合一 + 参数单源",
    "release_date": "2026-10-24",
    "description": (
        "V4.46.16：统一引擎路线 M3——消灭 SVD 双轨的真实病灶。侦察修正了设计稿的\n"
        "预设方案（「③ 委托 ④」），按实测事实选了更优的归一方向，先记在这里：\n"
        "\n【① 侦察：双轨的真实病灶不是「两份代码」，是「双驻留 + 双参数源」】\n"
        "③ local_video_infer._infer_svd 与 ④ video_gen.generate 都是 diffusers 实现，\n"
        "各有资产：③ 有进程级共享缓存（OOM 让位、实测复用 35.68s）+ 帧保存链；\n"
        "④ 有 TUNED 参数真源 + 质量/运动档位 + 蒸馏 CFG 语义。委托谁都会丢东西；\n"
        "而两条路径顺序使用会各持一份 4.2GB 管线（双驻留 8.4GB，15GB 机器直接压爆）。\n"
        "⇒ 正确归一 = 驻留合一（共享缓存）+ 参数单源（TUNED），两份代码都保留。\n"
        "\n【② 驻留合一】\n"
        "④ 的 load(svd-xt-i2v) 改走 local_video_pipe_cache.get_or_load —— 与 ③ 同 key\n"
        "（(svd, abspath) 二元组，两侧目录解析实测相等）⇒ 任一条先加载，另一条直接命中，\n"
        "全程只驻留一条管线。offload 实际状态随管线走（p._sg_offload_mode，命中时\n"
        "loader 不执行、不能误报 none）。load 返回值新增 pipe_source（hit/miss，可见性）。\n"
        "④ 的 unload()/OOM 必须连带 evict 共享缓存 —— 只断 self._pipe 而缓存还持着\n"
        "就是假卸载（V4.46.13 的 weakref 教训同款，这次用 cached_keys 断言锁死）。\n"
        "\n【③ 参数单源】\n"
        "③ 的生成参数（steps/chunk/motion/noise_aug/CFG）从硬编码字面量改为\n"
        "video_gen.tuned_for(svd-xt-i2v) 实读 —— 此前注释写「抄自 TUNED」但代码是\n"
        "第二真源，改表必漏此处。现在改 TUNED ⇒ 两条实现同步生效（测试用 monkeypatch\n"
        "改 motion_bucket_id=999 证明传导）。显式 steps 参数仍优先（档位入口不被吃掉）。\n"
        "③ 同步获得蒸馏 CFG 语义（distilled ⇒ cfg=1.0），与 ④ 对齐。\n"
        "\n【④ 测试 +4 例（test_video_residency_m3.py，零真权重）】\n"
        "跨实例共享命中（第二次 load 不再 from_pretrained、_pipe 同一对象）；\n"
        "unload 连带 evict（cached_keys 真放手）；参数随 TUNED 变（单源证明）；\n"
        "显式 steps 优先回归。既有 check_video_gen / VIDEOCHAIN 守卫全绿\n"
        "（③ 删字面量未破「CFG 不得关闭」「帧数↔fps 自洽」断言）。\n"
        "\n【验证】全量 pytest 1973 passed；run_all_checks 109 项全绿；frozen 106 锁；\n"
        "ruff 棘轮零新增；stability gate 无新增。\n"
        "\n【上一版 V4.46.15『统一推理引擎 M2 · 后端收编』见 docs/CHANGELOG.md。】"
    ),
}
