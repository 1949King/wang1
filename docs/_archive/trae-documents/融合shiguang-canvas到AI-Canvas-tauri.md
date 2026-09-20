# 融合 shiguang-canvas 能力到 AI-Canvas-tauri Tauri 壳 · 实施方案

## 一、Context（为什么做这件事）

拾光剪影项目目前同时存在两个画布：

| 画布 | 路径 | 形态 | 状态 |
|------|------|------|------|
| **现在的画布（自研）** | `vendor/shiguang-canvas/` | 嵌入式 React + Vite，由 Qt WebEngine 加载 | 默认主路径，运行中 |
| **之前的画布（参考）** | `vendor/AI-Canvas-tauri/` | 独立 Tauri 2 + React 19 + ReactFlow 12 桌面应用 | 克隆保留，未嵌入 |

**用户决策**：把现在 shiguang-canvas 的能力并入 Tauri 壳（AI-Canvas-tauri），让独立 Tauri 桌面应用取代 WebEngine 嵌入方式成为新主前端；保留 Python 后端（canvas_server.py 端口 18765）；AI-Canvas-tauri 原有节点系统与 shiguang-canvas 节点系统**并存**，用户可切换。

**预期结果**：
- 启动 Qt 主程序 → 自动拉起 Tauri 应用进程 → Tauri 应用通过 fetch http://127.0.0.1:18765/host/* 调用 Python 后端获得所有 AI 能力、剪辑时间线联动、模型池同步
- 用户可在 Tauri 应用内切换"AI Canvas 原生节点"和"LibTV（shiguang）节点"两套画布
- 保留 `SHIGUANG_CANVAS_ENGINE=webengine` 回退路径，原 WebEngine + shiguang-canvas 静态服务不删除

## 二、关键事实与决策依据

### 2.1 shiguang-canvas 与 Python 后端的耦合点（保留 Python 后端的核心原因）

`vendor/shiguang-canvas/src/bridge.ts` 通过 ~30 个 `/host/*` endpoint 调用 `app/core/canvas_server.py`，涵盖：
- AI 模型代理：`/host/generate-image`、`/host/generate-video`、`/host/generate-audio`、`/host/generate-music`、`/host/image-models`、`/host/video-models` 等
- ComfyUI 工作流：`/host/comfyui/run`、`/host/comfyui/status`
- 姿态解析（模式 B 子进程）：`/host/pose-extract`（BlazePose 关键点 JSON）
- 剧本合规：`/host/compliance-check`
- Agent 会话：`/host/agent/chat`、`/host/agent/session`、`/host/agent/start`、`/host/agent/reply`、`/host/agent/events`（SSE）
- 剪辑时间线联动：`/host/timeline-snapshot`、`/editor_outbox`、`/ingest`、`/push_from_editor`
- 模型池同步：`/host/providers`、`/host/ai-config-patch`
- Prompt 库代理：`/host/prompt-fetch`、`/host/prompt-bundled`、`/host/prompt-image`
- 批量视频生成：`/host/video-batch`、`/host/video-concat`

→ Python 后端是 Tauri 应用获取所有 AI 能力和剪辑时间线联动的**唯一接口**，保留它即保留全部能力。

### 2.2 AI-Canvas-tauri 已有能力（保留不动的部分）

**Rust 后端**（`src-tauri/src/`）：`secret_store`（凭据）、`mcp_bridge`（MCP loopback）、`onnx`（DirectML 推理 worker）、`comfyui`、`director_desk_runtime`、`assistant_web`、`provider_docs`、`file_transfer`、`clipboard`、`project_archive`、`path_policy`（路径校验）

**React 前端**：19-slice Zustand 状态、对话 Agent（Plan/B/C 模式 + Tool Registry + Policy Engine）、子智能体、IndexedDB v17、Tailwind 样式、自己的节点系统（`ai-text`、`ai-image`、`ai-video`、`ai-audio`、`ai-animation`、`ai-panorama`、`ai-markdown`、`ai-storyboard`、`ai-shotlist`、`ai-director`）

→ 与 shiguang-canvas 节点系统**并存**，通过视图模式切换器路由。

### 2.3 当前 WebEngine 嵌入链路（待改造为 Tauri 进程拉起）

- `d:\拾光剪影\main_qt6.py` → Qt 主程序入口
- `d:\拾光剪影\app\main_qt6.py` → 启动 QApplication、主窗口、canvas_bridge、canvas 静态服务（3011）
- `d:\拾光剪影\app\core\canvas_runtime.py` → `_runtime_singleton` 单例，`_start_static_server` 用 Python ThreadingHTTPServer 加载 `vendor/shiguang-canvas/dist/`，端口 3011
- `d:\拾光剪影\app\core\canvas_server.py` → HTTP 服务端口 18765，`/inject.js` 端点写入 `window.__SHIGUANG_BRIDGE_TOKEN` 与 localStorage
- `d:\拾光剪影\app\modules\lego\main_window.py` → QWebEngineView 加载 `http://127.0.0.1:3011`，订阅 `PROVIDER_ACTIVATED` 信号同步画布模型

## 三、实施步骤（最小侵入、可回退）

### Phase A：Tauri 应用拉起改造（不动前端代码）

**目标**：让 Qt 主程序能拉起 AI-Canvas-tauri 应用进程，并让 Tauri 应用拿到 bridge token。

**关键修改**：

1. **`app/core/canvas_runtime.py`**（不删原代码，新增分支）
   - 新增 `TAURI_BINARY_PATH` 常量、`_start_tauri_process()` 方法
   - `CanvasRuntime` 增加 `engine: "shiguang" | "tauri"` 选择
   - `active_canvas_engine()` 读取环境变量 `SHIGUANG_CANVAS_ENGINE`，默认仍 `shiguang`
   - `ensure_started()` 在 engine=tauri 时调用 `_start_tauri_process`，通过环境变量 `SHIGUANG_BRIDGE_TOKEN=<token>` 与 `SHIGUANG_BRIDGE_URL=http://127.0.0.1:18765` 注入
   - 保留 `_start_static_server`、`_start_vite` 作为 webengine fallback

2. **`d:\拾光剪影\app\main_qt6.py`**（最小改动）
   - 启动链中 canvas_runtime 拉起前，把 `canvas_server.session_token()` 写入 `.bridge_token`（已存在）并设置环境变量
   - 不修改 QWebEngineView 加载逻辑，但通过环境变量切换：
     - `SHIGUANG_CANVAS_ENGINE=tauri` → 启动 Tauri 应用进程，QWebEngineView 不嵌入（或显示 placeholder）
     - `SHIGUANG_CANVAS_ENGINE=shiguang`（默认） → 走原 WebEngine + 静态服务路径

3. **`vendor/AI-Canvas-tauri/src/bridgeHost.ts`**（新增，对接 Python 后端）
   - 提供 `bridgeToken()`、`authHeaders()`、`fetchJsonViaHost()` 等 helper（参考 shiguang 的 `bridge.ts`）
   - 在 Tauri 环境下从环境变量读取 token（通过 Rust command `get_bridge_token` 暴露）
   - 暴露统一 `BRIDGE_URL = "http://127.0.0.1:18765"`

4. **`vendor/AI-Canvas-tauri/src-tauri/src/lib.rs`**（新增 command）
   - 新增 `#[tauri::command] get_bridge_token() -> String` 读取环境变量 `SHIGUANG_BRIDGE_TOKEN`
   - 新增 `#[tauri::command] get_bridge_url() -> String` 读取环境变量 `SHIGUANG_BRIDGE_URL`，默认 `http://127.0.0.1:18765`
   - 不修改现有 `mcp_bridge`、`secret_store` 等模块

5. **`vendor/AI-Canvas-tauri/src-tauri/tauri.conf.json`**（安全配置微调）
   - `app.security.csp` 加白名单 `connect-src http://127.0.0.1:18765 http://localhost:18765`，让 Tauri 前端能 fetch Python 后端
   - 不放松 assetProtocol scope，保持 `$APPDATA/**`

### Phase B：shiguang-canvas 前端代码并入 Tauri 壳（不动 Tauri 原有节点系统）

**目标**：把 shiguang-canvas 的全部 React/TS 文件迁入 AI-Canvas-tauri，作为独立视图模式挂载。

**关键修改**：

1. **新建目录 `vendor/AI-Canvas-tauri/src/libtv/`**（不与现有 `src/` 冲突）
   - 复制 `vendor/shiguang-canvas/src/` 下所有文件到此处，保持文件结构
   - 包含：`CanvasShell.tsx`、`Stage3D.tsx`、`AgentPanel.tsx`、`store.ts`、`nodes.tsx`、`registerBuiltinNodes.ts`、`bridge.ts`、`mediaExtraNodes.tsx`、`storyNodes.tsx`、`shotCamera.ts`、`riggedHumanoid.ts`、`stage3dControlNet.ts`、`stage3dPoseRetarget.ts`、`promptLibrary.ts`、`promptTaxonomy.ts`、`PromptLibraryPanel.tsx`、`PluginManagerPanel.tsx`、`projectZip.ts`、`workflowSkill.ts`、`CommandPalette.tsx`、`ConfirmDialog.tsx`、`MaskEditDialog.tsx`、`StageImportModal.tsx`、`StudioPages.tsx`、`VideoStudio.tsx`、`ImageStudio.tsx`、`HomeLanding.tsx`、`LibTvChrome.tsx`、`AppNav.tsx`、`AppErrorBoundary.tsx`、`imageTools.ts`、`localLibrary.ts`、`infiniteCoreNodes.ts`、`NodePalette.tsx`、`WorkspaceCanvasMenus.tsx`、`PromptCoverImage.tsx`、`PromptPreviewDialog.tsx`、`components/canvas/`、`stores/`、`plugins/`、`hooks/`、`utils/`

2. **`vendor/AI-Canvas-tauri/src/libtv/bridge.ts`**（改造）
   - 移除原 `bridgeToken()` 中对 `window.__SHIGUANG_BRIDGE_TOKEN` 的依赖
   - 改为调用 `@tauri-apps/api/core` 的 `invoke('get_bridge_token')` 拿 token，并 cache
   - `BRIDGE` 改为 `invoke('get_bridge_url')` 异步获取，或直接 `http://127.0.0.1:18765` 硬编码（开发期更简单）
   - 保留所有 `/host/*` endpoint 调用不变（Python 后端不动）
   - 移除 `installInjectScript()`（Tauri 不需要 inject.js，token 走环境变量）

3. **`vendor/AI-Canvas-tauri/src/libtv/store.ts`**（保持原状）
   - 不动 store 结构，作为 LibTV 视图的独立 store
   - 与 Tauri 自己的 `useAppStore` 并存，不强制合并

4. **`vendor/AI-Canvas-tauri/src/libtv/styles.css`**（独立样式）
   - 保持 shiguang-canvas 的 styles.css 不动
   - 在 `index.css` 通过 `@import` 条件加载，仅 LibTV 视图生效
   - 通过 `data-view="libtv"` 属性切换样式作用域，避免与 Tailwind 全局冲突

5. **`vendor/AI-Canvas-tauri/src/App.tsx`**（增加视图切换器）
   - 不删除原有 Header / Sidebar / Canvas / NodeMenu / SettingsPanel / Titlebar 装配
   - 在根组件外层增加 `<ViewModeSwitcher>`：通过 `localStorage.canvas_view_mode = "aic" | "libtv"` 持久化
   - 切到 `libtv` 时挂载 `libtv/App.tsx` 的 `CanvasShell`（shiguang 的外壳）
   - 切到 `aic` 时走原 App 装配
   - 默认仍 `aic`，避免破坏现有用户

6. **`vendor/AI-Canvas-tauri/src/libtv/App.tsx`**（新增入口，包装原 shiguang App）
   - 复用 shiguang 原有 App 入口逻辑，只把 `import "./bridge"` 改为 `import "./bridge-host-adapter"` 桥接
   - 不依赖 `installInjectScript`、`__shiguangPluginSync` 等 WebEngine 专属钩子（用 Tauri invoke 重写）

7. **资源文件迁移**
   - `vendor/shiguang-canvas/public/prompts/` 复制到 `vendor/AI-Canvas-tauri/public/prompts/`
   - `vendor/shiguang-canvas/public/models/` 复制到 `vendor/AI-Canvas-tauri/public/models/`
   - `vendor/shiguang-canvas/models-src/` 复制到 `vendor/AI-Canvas-tauri/models-src/`
   - 不删除 shiguang-canvas 原文件，作为 webengine fallback 备份

### Phase C：Tauri 应用关闭与 Qt 主程序联动

**目标**：Tauri 应用关闭时通知 Qt 主程序，避免孤儿进程。

**关键修改**：

1. **`vendor/AI-Canvas-tauri/src-tauri/src/lib.rs`**（监听窗口关闭）
   - 在 `tauri::Builder::default()` 链中 `on_window_event` 监听 `WindowEvent::CloseRequested`
   - 关闭前 fetch `http://127.0.0.1:18765/host/tauri-closing` 通知 Python 后端
   - Python 后端收到通知后通过 EventBus 通知 Qt 主窗口（已有事件总线）

2. **`app/core/canvas_server.py`**（新增端点）
   - 新增 `POST /host/tauri-closing`：接收 Tauri 关闭事件，触发 `EventBus.publish("CANVAS_TAURI_CLOSED")`
   - 不修改其他端点

3. **`app/modules/lego/main_window.py`**（订阅事件）
   - 订阅 `CANVAS_TAURI_CLOSED` 事件，在槽函数中：
     - 同步画布最后状态（通过 `/host/timeline-snapshot` 拉一次）
     - 关闭 Tauri 进程句柄（`canvas_runtime.stop()` 适配）
     - 提示用户画布已关闭

### Phase D：环境变量与回退路径

**目标**：保证 WebEngine 路径仍可用，不破坏现状。

**关键修改**：

1. **环境变量契约**
   - `SHIGUANG_CANVAS_ENGINE` = `tauri` | `shiguang`（默认）
   - `SHIGUANG_BRIDGE_TOKEN` = canvas_server 的 session token（启动 Tauri 时由 Qt 主程序注入）
   - `SHIGUANG_BRIDGE_URL` = `http://127.0.0.1:18765`

2. **回退路径**
   - 不删除 `vendor/shiguang-canvas/`，作为 webengine fallback
   - 不删除 `canvas_runtime.py` 的 `_start_static_server`、`_start_vite`
   - 不删除 `canvas_server.py` 的 `/inject.js` 端点
   - 不删除 `main_window.py` 的 QWebEngineView 加载逻辑

## 四、关键文件清单（按优先级）

### A. 必改文件（核心改造）

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app/core/canvas_runtime.py` | 新增方法 | 增加 `_start_tauri_process`、`engine` 字段，保留原 WebEngine 逻辑 |
| `app/main_qt6.py` | 最小改动 | 启动链注入环境变量，不重排顺序 |
| `app/core/canvas_server.py` | 新增端点 | `POST /host/tauri-closing`，保留所有现有端点 |
| `app/modules/lego/main_window.py` | 最小改动 | 订阅 `CANVAS_TAURI_CLOSED` 事件，不删 QWebEngineView |
| `vendor/AI-Canvas-tauri/src-tauri/tauri.conf.json` | csp 放行 | 加 `connect-src` 白名单 18765 |
| `vendor/AI-Canvas-tauri/src-tauri/src/lib.rs` | 新增 command | `get_bridge_token`、`get_bridge_url`、`on_window_event` 监听 |
| `vendor/AI-Canvas-tauri/src/App.tsx` | 增加切换器 | 顶层 `<ViewModeSwitcher>`，原装配不动 |
| `vendor/AI-Canvas-tauri/src/libtv/`（新目录） | 复制 + 改造 | 复制 shiguang 全部 src，改造 bridge.ts、App.tsx |

### B. 资源文件（复制）

| 来源 | 目标 | 说明 |
|------|------|------|
| `vendor/shiguang-canvas/public/prompts/` | `vendor/AI-Canvas-tauri/public/prompts/` | Prompt 库静态资源 |
| `vendor/shiguang-canvas/public/models/` | `vendor/AI-Canvas-tauri/public/models/` | 模型静态资源 |
| `vendor/shiguang-canvas/models-src/` | `vendor/AI-Canvas-tauri/models-src/` | 3D 模型源 |

### C. 不动文件（保持原样作为 fallback）

- `vendor/shiguang-canvas/src/*`（保留，作为 webengine fallback）
- `vendor/shiguang-canvas/dist/`（保留，给 webengine 路径用）
- `vendor/shiguang-canvas/package.json`、`vite.config.ts`
- `app/core/canvas_bridge.py`、`canvas_aigc.py`、`canvas_agent_runtime.py`（Python 后端能力保留）
- `vendor/AI-Canvas-tauri/src/components/`、`src/services/`、`src/store/`、`src/hooks/`、`src/types/`（Tauri 原有能力保留）

## 五、验证方案

### 5.1 编译验证

```powershell
# Python 后端
python -m py_compile d:\拾光剪影\app\core\canvas_runtime.py
python -m py_compile d:\拾光剪影\app\core\canvas_server.py
python -m py_compile d:\拾光剪影\app\main_qt6.py
python -m py_compile d:\拾光剪影\app\modules\lego\main_window.py

# 前端
cd d:\拾光剪影\vendor\AI-Canvas-tauri
npm install
npm run typecheck
npm run build

# Rust
cd src-tauri
cargo check --lib
```

### 5.2 端到端验证

1. **WebEngine 路径不破坏**（回归）
   - 设 `SHIGUANG_CANVAS_ENGINE=shiguang`，启动 Qt 主程序
   - 验证 QWebEngineView 加载 shiguang-canvas dist 正常
   - 验证 AI 生成、剪辑时间线联动正常

2. **Tauri 路径新功能**
   - 设 `SHIGUANG_CANVAS_ENGINE=tauri`，启动 Qt 主程序
   - 验证 Tauri 应用进程被拉起
   - 验证 Tauri 应用 fetch http://127.0.0.1:18765/host/image-models 通
   - 验证 AI 生成（图像/视频）成功
   - 验证剪辑时间线联动（`timeline-snapshot`、`editor_outbox`）正常
   - 验证 Tauri 应用关闭后 Qt 主程序收到通知
   - 验证 ViewModeSwitcher 能在两套节点系统间切换

3. **持久化与回退**
   - 关闭 Tauri 应用后切换回 webengine 路径，验证不报错
   - 重启 Qt 主程序，验证 token 重新注入

### 5.3 行为测试要点

- Tauri 应用拉起失败时 Qt 主程序是否优雅降级到 webengine
- Tauri 应用崩溃后是否自动重启或切换 webengine
- 两套 store 状态切换时是否清空前一视图状态
- Tauri 应用关闭未通知 Python 时 Qt 主程序的兜底超时

## 六、风险点与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| Tauri 进程与 Qt 主程序父子关系在 Windows 下不稳定 | 中 | Tauri 不被拉起 | 用 `subprocess.Popen` 独立进程 + 端口探活 + Qt 主程序定期 poll |
| shiguang 的 styles.css 与 Tailwind 全局冲突 | 中 | 样式错乱 | 用 `data-view="libtv"` 属性 scope 隔离 |
| 两套 store 切换时状态污染 | 低 | 数据错乱 | ViewModeSwitcher 卸载前一视图组件，强制重新挂载 |
| bridge token 在 Tauri 环境泄漏 | 低 | 安全风险 | token 走环境变量不落盘，Tauri 应用退出即失效 |
| Tauri 应用打包后路径与开发期不一致 | 中 | 资源加载失败 | 用 `tauri::path::app_data_dir()` + `resource_root()` 适配 |
| shiguang-canvas 升级后 libtv/ 副本同步成本 | 中 | 长期维护负担 | 用 npm script 或 git submodule 同步策略，后续考虑 monorepo |

## 七、交付检查清单（按 .trae/rules/2.md 第十一章）

- [ ] 只修改了需求相关文件（canvas_runtime、main_qt6、canvas_server、main_window、AI-Canvas-tauri 配置 + libtv 目录）
- [ ] 保持 PyQt6 分层和现有命名风格
- [ ] 保留旧逻辑或 fallback（SHIGUANG_CANVAS_ENGINE=shiguang 回退路径）
- [ ] 处理空值、异常、重复点击、文件不存在（Tauri 拉起失败、token 缺失、端口占用）
- [ ] 运行了合适的验证命令（py_compile、npm typecheck、npm build、cargo check）
- [ ] 说明了验证结果和残余风险
- [ ] 没有泄露密钥、没有执行破坏性命令、没有覆盖用户改动

## 八、残余风险与未决问题

1. **Tauri 应用二进制路径定位**：开发期用 `cargo run`，打包后用安装目录的 .exe。需要在 `canvas_runtime.py` 的 `_start_tauri_process` 中根据 `sys._MEIPASS` 或 `SHIGUANG_TAURI_BIN` 环境变量定位
2. **Tauri 应用首次启动延迟**：首次构建可能 30-60s，需要在 Qt 主程序显示启动进度
3. **shiguang-canvas 的 inject.js 注入逻辑**：Tauri 不需要，但 shiguang 原 App.tsx 调用了 `installInjectScript()`，需要在 libtv/App.tsx 中跳过
4. **EventBus 跨进程**：当前 `EventBus` 是 Qt 进程内事件总线，Tauri 关闭事件通过 HTTP 进入 Python 后端，再通过 EventBus 通知 Qt 主程序，链路较长但稳定
5. **ViewModeSwitcher 默认值**：建议默认 `aic`（保留 AI-Canvas-tauri 原体验），用户主动切到 `libtv`，避免破坏现有用户习惯

## 九、执行顺序建议

1. **Phase A 先行**（Tauri 应用拉起 + bridge token 注入 + Python 后端不动）
   - 验证 Tauri 应用能 fetch http://127.0.0.1:18765/host/health 通
   - 验证 Qt 主程序能拉起/关闭 Tauri 应用
2. **Phase B 跟进**（shiguang 前端代码并入 libtv/）
   - 验证 ViewModeSwitcher 能切换
   - 验证 libtv 视图能完成 AI 生成
3. **Phase C 收尾**（关闭联动）
   - 验证 Tauri 关闭通知 Qt 主程序
4. **Phase D 全程**（环境变量与回退路径）
   - 验证 webengine fallback 不破坏

每 Phase 完成后运行 `python scripts/frozen_zone_guard.py`，避免触碰冻结区。
