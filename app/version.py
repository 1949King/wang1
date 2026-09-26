"""
拾光剪影 — 版本号管理
=======================

版本格式: MAJOR.MINOR.PATCH
- MAJOR: 架构级重构 (不兼容API变更)
- MINOR: 新模块/新功能 (向下兼容)
- PATCH: Bug修复/性能优化/小改进

变更日志见 docs/CHANGELOG.md
"""

__version__ = "4.40.5"

# 详细的版本元信息
VERSION_INFO = {
    "major": 4,
    "minor": 40,
    "patch": 5,
    "codename": "A4 路由巨石拆分完成（批次 2/3：POST 全迁）",
    "release_date": "2026-09-27",
    "description": (
        "V4.40.5: 评价报告架构债 #2「路由巨石」**拆解完成**——do_POST 29 个端点"
        "（约 1,040 行）迁出到新增 app/core/canvas_routes_post.py"
        " （CanvasPostRoutesMixin，1,183 行）。至此 canvas_server 的 if 链只剩"
        " **404 兜底 1 条**，GET/POST 端点全部走路由表。"
        "★ canvas_server.py **3,273 → 1,740 行（−47%）**，基线两次下调"
        " （3,273→2,757→1,740）；do_GET/do_POST 各剩约 10 行薄分发。"
        "★ 搬移手法：AST 辅助脚本（自动提取块、缩进 -4、给模块级符号裸引用"
        " 加 cs. 前缀、注入 cs = _cs()）——1,040 行机械搬移零手抄错误，"
        " 比手改可靠且可复查。"
        "★ **踩坑与加固（本版最重要的产出）**：A4 批次 1 时 ruff --fix 把"
        " 「迁出后 canvas_server 不再直接使用、但被 mixin 经 cs.xxx 引用」的"
        " import 当死代码删掉，导致 4 个符号失效（/host/plugins、/host/characters、"
        " /editor_outbox + build_host_ai_config_patch 影响的 5 个 *-models 端点）。"
        " 处置：① 两处 import 块加语句级 noqa + 说明；② 新增常驻守卫"
        " **`_verify/check_canvas_route_attrs.py`**（纯静态，校验 mixin 的"
        " 每个 cs.xxx 都能在 canvas_server 顶层绑定里找到），已注册 run_all_checks"
        " 并进 hook **第⑨道**（卡点 8 → 9）；③ 顺手修 mixin 的 Any 缺失与"
        " 冗余 import。另修一处误删：threading 被 F401 误判（实际在"
        " CanvasBridgeServer 用），已恢复。"
        "★ 验证：e2e 真起服务全过 · 路由契约 65 条不重叠 · 全量 383/383 ·"
        " ruff 全净 · 冻结区 85 · 稳定性 249≤269 · 粘合层 18/0 · 架构 0 警告 ·"
        " 双库无漂移 · 文件规模守卫通过。"
        " ——至此 A4（报告架构债 #2）收尾：路由巨石消失，加端点不再改千行方法。"
    ),
}
