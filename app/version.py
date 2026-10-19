__version__ = "4.45.0"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 45,
    "patch": 0,
    "codename": "「代码 × 扩散」渲染引擎刀（Chromium frame(t)）",
    "release_date": "2026-10-19",
    "description": (
        "V4.45.0：「代码 × 扩散」渲染引擎落地（V4.44 契约刀的下一刀）。一条权威路径：\n"
        "compile → security → resolve → page_builder → render_worker(Chromium) → audio_graph →\n"
        "ffmpeg 编码 → ffprobe 校验 → publish_to_inbox → QC。**不做第二条纯素材快速路径**（先对后快）。\n"
        "\n【新增】\n"
        "① security.py（260 行）：HTML 自包含 19 条禁用规则、html/asset 路径 jail（realpath 防\n"
        "   .. / 盘符 / 软链）、HTML 单文件/总数/总字节与成片帧数限额、渲染边界文字层铁律再确认；\n"
        "② page_builder.py（369 行）：compiled → 自包含时间线页面，叠层/fit/iframe srcdoc/确定性时钟\n"
        "   （performance.now / Date.now / rAF / CSS 动画冻结 / Math.random 按 t 播种）；实测 file:// 下\n"
        "   父页面读 iframe.contentWindow 抛 SecurityError ⇒ 时钟与文字 rect 走 postMessage；\n"
        "③ render_worker.py（263 行）：无 Qt 子进程，page.route 运行时网络兜底 + 逐帧 __sgSeek +\n"
        "   PNG/sha256 manifest + progress.json；失败写 worker_error.json 并非零退出；\n"
        "④ render_host.py（438 行）：编排/音频/编码/ffprobe 校验/发布/QC；失败带 stage 与 work_dir；\n"
        "⑤ audio_graph.py（107 行）：atrim/atempo 链（0.25~4）/volume/adelay/amix+apad 纯函数；\n"
        "⑥ video_critic.py（145 行）：同 t 双乱序 sha256、文字安全区（data-sg-text）、平色 warning；\n"
        "   响度 EBU R128 显式 not_wired（不假装测过）；\n"
        "⑦ 能力 pipeline.code_video_render（file_write / 免费 / action=dangerous 需确认）三处注册。\n"
        "\n【验证】\n"
        "· pytest code_video 五件套 111 例（110 passed / 1 skip：契约 23 · 安检 47 · 页面 8 ·\n"
        "  音频 7 · 质检 12 · 编排 13）；\n"
        "· 真渲染冒烟：360×640/24fps/0.5s HTML 镜头 → mp4，QC 双乱序+文字安全区 pass，\n"
        "  ffprobe 宽高/帧率/时长一致；10 帧×2 次逐帧 sha256 一致（同机确定性）；540×960 约 30ms/帧；\n"
        "· check_code_video（扩展 B/E/F）+ check_code_video_render 全绿；frozen_zone_guard 107 锁完整；\n"
        "· 全量 run_all_checks 95 项（CODEVIDEO + CODEVIDEORENDER 入册）。\n"
        "\n【明确不做（V4.46 画布刀）】\n"
        "· 不接画布节点/端点/SSE 进度；不生成镜头 HTML（llm_html.py）；不做纯素材快速路径（V4.45.5）。\n"
        "\n【上一版 V4.44.0『契约刀』见 docs/CHANGELOG.md。】"
    ),
}
