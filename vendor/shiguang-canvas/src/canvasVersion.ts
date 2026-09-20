/**
 * 画布版本号 — 单一事实来源
 *
 * 画布（vendor/shiguang-canvas）是独立子项目，**版本线独立于主程序**：
 *   - 主程序版本 = `app/version.py`（如 4.30.0），Qt6 侧边栏显示
 *   - 画布版本   = 本文件（如 0.2.0），画布导航栏右上角显示（`AppNav` 的 `.ic-nav-ver`）
 *
 * 两者**刻意不同步**：画布可以单独迭代交互/视图，不必等主程序发版。
 *
 * ⚠️ 2026-09-19 起本文件是唯一来源：
 *   历史上版本号被硬编码在三处（`package.json` / `CanvasShell.tsx` / `AppNav.tsx`），
 *   从项目建立起一直停在 `v0.1.0`、历经 V4.21~V4.30 十余轮画布改动从未维护过，
 *   导致界面显示的版本与实际功能严重脱节。禁止再在组件里内联版本字符串。
 *
 * 维护规则（改画布功能时同步做）：
 *   1. 改本文件的 `CANVAS_VERSION`
 *   2. 同步 `package.json` 的 `version`（去掉前缀 v）
 *   3. 在 `docs/CHANGELOG.md` 的画布段落里记一笔
 */

/** 画布语义化版本（不带 v 前缀，便于与 package.json 对齐） */
export const CANVAS_VERSION = "0.3.0";

/** 画布版本显示串（带 v 前缀，供导航栏渲染） */
export const CANVAS_VERSION_LABEL = `v${CANVAS_VERSION}`;

/** 版本代号：跟随本版主题命名，便于口头指代 */
export const CANVAS_VERSION_CODENAME = "白模动作录制";

/** 导航栏版本号的 tooltip 文案 */
export const CANVAS_VERSION_TITLE = `拾光导演台 · ${CANVAS_VERSION_CODENAME}`;
