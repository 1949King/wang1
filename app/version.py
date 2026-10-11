__version__ = "4.43.10"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 43,
    "patch": 10,
    "codename": "画布太阳系背景求真：8 张真实行星素材 + 80s 轮播 + 星场漂移",
    "release_date": "2026-10-11",
    "description": (
        "V4.43.10：照搬 AI Canvas 的行星素材 + 动效（用户裁定「要」）\n"
        "\n【用户反馈原话】「我记得我们参考的那个 AI 画布的开源项目里面的主题是动态效果的，\n"
        "是一个比较好的一个效果的，你给我做出来的为什么是这样？…同样的地方同样的功能，\n"
        "为什么别人能做成这样，你给我做出来却是一个屎山一样的东西？」→ 用户裁定「要」\n"
        "（照搬行星素材 + 动效）。\n"
        "\n【此前为什么差】\n"
        "· 开源 `SolarSystemBackground.tsx`：**8 张真实行星照片**（水/金/地/火/木/土/天/海\n"
        "  PNG）+ `setInterval` **每 80 秒轮播** + 行星淡入/缩放 1.2s；`backgrounds.css`\n"
        "  的星场 `animation: stars-shift 60s linear infinite` 缓慢漂移。\n"
        "· 我们 `canvasBackgrounds.ts`（V4.43.2）只有**几层 CSS radial-gradient**、静态。\n"
        "  ⇒ 差距是「没搬素材、没做动效」，不是能力不可及。\n"
        "\n【本轮改动（零解冻）】\n"
        "· 复制 8 张行星 PNG → `vendor/shiguang-canvas/src/assets/images/bg/`（**新建文件**，\n"
        "  不在冻结清单）。\n"
        "· `canvasBackgrounds.ts` 重写：① 静态 import 8 张图（Vite 构建时解析）；\n"
        "  ② 惰性建背景层 `#sg-solar-layer`（星场 + 8 个 `<figure>`）；③ CSS 复刻开源的\n"
        "  星场 14 点 + `sg-stars-shift` 60s 漂移、行星 `is-active` 淡入/缩放 1.2s、\n"
        "  容器 `opacity .13 / bottom -70%`；④ `applyCanvasBackground` 按背景 id 挂/卸该层，\n"
        "  太阳系时起 80s 轮播（幂等，beforeunload 清理）。\n"
        "· **未动** `styles.css` / `store.ts` / `CanvasShell.tsx`（冻结区）—— 仍走\n"
        "  「运行时注入 + 自建 DOM 层」的零解冻路线。\n"
        "\n【双库同步（frozen-zone-release 5b/5c）】\n"
        "· 同步 `canvasBackgrounds.ts` + **整条依赖链**（8 张素材）到副库\n"
        "  `vendor/AI-Canvas-tauri/src/libtv/`（副库原本无 assets 目录）。\n"
        "· 副库 tsc 实测 **0 错误**；`check_canvas_dual_repo` 复跑 **OK 无新增漂移**。\n"
        "\n【验证】\n"
        "· tsc 主库 **37 处 = 基线**（Stage3D 16 + riggedHumanoid 21，零新增）\n"
        "· vitest **296/296** · vite build **rc=0** · 8 张行星素材**全部进 dist**\n"
        "  （`1_mercury-*.png` … `8_neptune-*.png`）\n"
        "· frozen_zone_guard **85 locks intact**（未动任何冻结文件）\n"
        "\n【已知未做（待用户授权）】\n"
        "· 画布版本号 `canvasVersion.ts` 0.3.24 → 0.3.25 **未升** —— 该文件在冻结区\n"
        "  `canvas-magnetic-intent`，本轮授权范围仅 `character_management_module.py`，\n"
        "  故**未擅自改动**。待用户授权解冻后补升（三件套：canvasVersion.ts →\n"
        "  package.json → CHANGELOG）。\n"
        "\n【上一版 V4.43.9『设置改回页内模块』见 docs/CHANGELOG.md。】"
    ),
}
