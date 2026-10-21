__version__ = "4.46.4"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 4,
    "codename": "数字人口型成片管线（诚实档）+ 捏脸漂移盲区收口",
    "release_date": "2026-10-22",
    "description": (
        "V4.46.4：完善捏脸与数字人节点（用户指令），全在非冻结区。\n"
        "\n【① 数字人「口型成片」从写死拒绝变成真管线】\n"
        "旧状：DigitalHumanNode 的「口型成片」按钮是写死的拒绝文案，后端零端点。\n"
        "新增：digital_human_talking.py（合成核心）+ POST /host/digital-human/\n"
        "talking-video（独立 mixin，canvas_routes_post.py 已 1967/2000 行）。\n"
        "三级诚实降级：still_video（静态形象+配音→含音视频轨 mp4，产物恒标\n"
        "mouth_moved=False）→ unavailable（缺什么报什么 + lipsync_note 转告真引擎\n"
        "状态）。安全边界：媒体引用只收 dataURL / inbox 文件名，**拒绝任意绝对路径**\n"
        "（防借 ffmpeg 读磁盘任意文件）；失败清理半成品不假成功。\n"
        "前端 digitalHumanTalking.ts 客户端（bridge.ts 已 1897 行 ⇒ 独立模块 + 登记\n"
        "路由契约 CLIENTS）；后端 12 例 + 前端 6 例 + 真桥 E2E（真 ffmpeg 产物\n"
        "ffprobe 验双轨 / 绝对路径注入 400 / 缺输入 400）全过。\n"
        "\n【② 捏脸漂移盲区收口】character_anchor 的 ANCHOR_TRAITS 不含 face_params\n"
        "⇒ 用户改捏脸后漂移检测看不见、带旧锚批量生成。已补入锚定字段（只参与\n"
        "指纹/漂移比对，不进 render_anchor_prompt——文字化仍由 _face_params_to_text\n"
        "单一入口）；守卫 CHARANCHOR 41 例含新断言全过。\n"
        "\n【③ 顺手】路由 mixin 守卫补登 roughcut/code_video/digital_human 三个漏网\n"
        "mixin（cs.* 盲区）；清 3 处未使用导入（ruff 减债）。\n"
        "\n【遗留（需授权/后续刀）】DigitalHumanNode UI 按钮接线在冻结文件\n"
        "mediaExtraNodes.tsx（canvas-magnetic-intent）⇒ 需「解冻 canvas-magnetic-intent」\n"
        "一行接线；真·口型同步需装 MuseTalk/LatentSync（video_lipsync 已留接口）；\n"
        "Agent 能力目录暂未注册该端点（先给画布用，验证后再开）。\n"
        "\n【验证】run_all_checks 100 项全绿（DOCNUM 端点 102/106 回正）；pytest\n"
        "1,815（+12）；vitest 618（+6）；tsc 37=基线；frozen_zone_guard 106 锁完整\n"
        "（文档旧写 107 已按实测回正）；dist 已重建。\n"
        "\n【上一版 V4.46.3『用户反馈双修』见 docs/CHANGELOG.md。】"
    ),
}
