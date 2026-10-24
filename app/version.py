__version__ = "4.46.26"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 46,
    "patch": 26,
    "codename": "画布链路两处断裂：WebEngine 预检空 argv + 插件假产物",
    "release_date": "2026-10-25",
    "description": (
        "V4.46.26：AI 画布整块黑屏 +「画布页面加载失败（请点刷新或启动画布）」的\n"
        "根因定位并修掉；同一轮把真机日志暴露的「内置插件全部装不上」也一并修了。\n"
        "\n【断裂①：预检脚本自己崩（黑屏真凶）】\n"
        "_verify/probe_webengine.py 用 QApplication([]) 传空 argv。Qt 6.11 的 Chromium\n"
        "因此报「Argument list is empty, the program name is not passed to\n"
        "QCoreApplication. base::CommandLine cannot be properly initialized.」并\n"
        "fail-fast：空 argv ⇒ exit 127(0xC0000409)；[\\\"probe\\\"] ⇒ exit 0(loadFinished=True)。\n"
        "⇒ 探针恒判「不可用」→ main_qt6 置 SHIGUANG_NO_WEBENGINE=1 → 应用内画布被\n"
        "永久禁用。上一版「QtWebEngine 版本混装」结论只是当时环境叠加的巧合。\n"
        "修：探针 argv 一律非空 + 失败原因写 stderr；main_qt6 捕获 stderr 落\n"
        "data/startup.log（区分超时/崩溃/真不可用）+ SHIGUANG_FORCE_WEBENGINE=1 逃生\n"
        "开关 + 主 QApplication argv 非空兜底；新增 AST 回归锁。\n"
        "\n【断裂②：插件注册表指向不存在的产物】\n"
        "4 条官方插件声明 /plugins/*.js 但 public/ 与 dist/ 都没有对应文件；静态服务\n"
        "的 SPA 兜底把缺文件改写成 index.html（200 + HTML，不是 404）⇒ 前端当 ESM\n"
        "import ⇒ Unexpected token '<'；2 条社区插件指向不存在的 cdn.shiguang.io。\n"
        "且这些 url 早被写进用户缓存 canvas_plugins.json ⇒ 只改代码不清缓存用户照旧报错。\n"
        "修：4 个真实 bundle（sticky-note/markdown/svg-viewer/timeline-embed，零 import、\n"
        "React 取 rt.React、SVG 走 sandbox iframe 防 XSS、时间线读 /host/timeline-snapshot）\n"
        "+ index.json；registry 删死地址并修正 timeline-embed 描述（原本吹「双向跳转」）；\n"
        "manifest 读取时清理死地址条目并回写（缓存迁移）。\n"
        "\n【真机验收（非静态检查）】\n"
        "① canvas WebEngineView created in 206ms → canvas page loadFinished ok\n"
        "   url=http://127.0.0.1:3011?token=…，console 镜像出现前端 JS 日志（页面真执行）；\n"
        "② 03:52 实跑：清理 2 条死地址 → 4 个 bundle 全 200 → 零 sync install failed\n"
        "   （03:08 那轮是 6 条）→ GET /host/timeline-snapshot 200（插件组件真挂载跑起来）。\n"
        "门禁：ruff 全绿 · frozen 106 锁 · stability 251/251 无新增 · doc_consistency 0 阻断 ·\n"
        "定向 pytest 13 passed（webengine 7 + plugin assets 6，均反例验证过牙齿）。\n"
        "\n【上一版 V4.46.18『统一推理引擎 M5 · Wan2.1 真机验收』见 docs/CHANGELOG.md】"
    ),
}
