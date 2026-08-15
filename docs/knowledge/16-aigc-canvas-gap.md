# 16 — 主流 AIGC 画布借鉴对照（执行索引）

> 源清单：用户 2026-08-08「LibTV / ComfyUI / TapNow / 即梦 / InvokeAI / Krea / Runway」  
> 策略：抄能力不换壳；AIGC 走模型广场 → `/host/generate-image` / `/host/generate-video`。

## 共性五件事 → 拾光状态

| # | 优秀画布都在做 | 拾光导演台 |
|---|---------------|-----------|
| 1 | 节点编排 + 连线上下文 | ✅ React Flow；生成时汇聚上游剧本/提示词 |
| 2 | 角色/素材一致性调度 | ✅ `@角色` / `@素材` / `@节点标题` + 三视图 |
| 3 | 分镜拆解 / 宫格 | ✅ 拉片 + 9/25 宫格 |
| 4 | 简化表单 / 模板复用 | ✅ 本地模板（App 表单页已移除，改用右侧检视器） |
| 5 | 一键产出并回流剪辑 | ✅ 生成选中 / 批量 / **全部入轨**（时长→静图短视频） |

## 清单条目状态

| 优先级 | 功能 | 状态 |
|--------|------|------|
| ⭐⭐⭐ | **社区提示词库** | ✅ 顶栏/侧栏/素材库；**bundled 离线约 3600+**（7×yukkcat + StimQQ + NeXra + 拾光包）；`/host/prompt-bundled` + 静态 public 回退；预览/收藏 |
| ⭐⭐⭐ | 首尾帧控制 | ✅ 槽位 + img2img（失败降级） |
| ⭐⭐⭐ | 一键拉片分镜 | ✅ `/host/storyboard-breakdown` |
| ⭐⭐⭐ | App 模式 | ⚠️ 轻量「表单」视图（隐藏连线，右侧编辑） |
| ⭐⭐⭐ | 工作流模板 | ✅ 本地 20 条（非社区） |
| ⭐⭐⭐ | AIGC→生成选中 | ✅ 模型下拉 + 占位兜底 |
| ⭐⭐ | @语法素材调度 | ✅ `@角色`/`@素材`/`@标题` |
| ⭐⭐ | 角色三视图 | ✅ |
| ⭐⭐ | 循环变体批量 | ✅ 表情/服装/背景×3 |
| ⭐⭐ | 智能多帧运镜 | ✅ 视频创作台 + **画布视频节点真生成**（`/host/generate-video`；无模型诚实失败） |
| ⭐⭐ | Form Builder 防呆 | ⚠️ 简化表单模式（顶栏「表单」） |
| ⭐⭐ | 多角度机位预览 | ✅ 水平/俯仰/焦段/运镜 + **5 机位叠卡** |
| ⭐⭐ | 双模型 A/B 对比 | ✅ 图/视频同 prompt 双模型 → 叠卡 |
| ⭐⭐ | 分镜时间条 | ✅ 顶栏「分镜条」横向镜头条 |
| ⭐⭐ | 工作流 Skill 导出/导入 | ✅ `shiguang-canvas/skill/v1` JSON |
| ⭐⭐ | TTS 生音频 | ✅ `/host/audio-models` + 模型下拉；云端 `/audio/speech`（OpenAI 等）→ 失败降级 VoiceGenerator |
| ⭐ | 实时预览 / 涂鸦生视频 | 明确不做（本窗口） |
| — | 全部发送到剪辑 + duration | ✅ P3.1 |
| — | 参考图重绘 | ✅ 含**蒙版局部重绘**（`/host/inpaint`） |
| ⭐⭐ | 3D 导演台（轻量） | ✅ 体素骨骼人·关节摆姿·**单人/群像模板**·正面=+Z·机位·FOV·截图 |
| — | UI 对齐 LibTV/infinite 简洁风 | ✅ 顶栏 + 折叠面板 |
| — | 生图工作台真页 | ✅ 提示词/模型/参考图/结果/存资产/进画布/入轨 |
| — | 视频创作台真页 | ✅ 同上；无模型不假成功 |
| — | 模型管理 ↔ 画布 | ✅ `/host/ai-config-patch` + **保存 Key 自动同步** |
| — | 画布连接 Agent | ✅ 项目 Agent 对话 + 画布 MCP `:17371` 分离 |
| — | 对话 Agent → 画布 | ✅ `canvas.open` / `canvas.sync_models`；画布可调 `/host/tools` |
| — | AI-Canvas-tauri 对齐节点 | ✅ **分镜表 `shotlist`** · **交互宫格 `storyboard`** · **Markdown**；Agent 增 `queryNodes`/`bindShotlistFrame`/`fillStoryboardCell`/undo·redo |
| — | 画布共享模型/拓展 | ✅ `/host/chat-models` · `/host/tools` · `/host/tools/run` |

## infinite-canvas → 自研导演台 迁移清单

> 备用引擎：[basketikun/infinite-canvas](https://github.com/basketikun/infinite-canvas)（MIT）。拾光默认 **不整仓嵌入**，按能力逐项迁入 `vendor/shiguang-canvas`。

| 优先级 | infinite 能力 | 来源/实现 | 自研状态 | 下一步 |
|--------|---------------|-----------|----------|--------|
| **P0** | **提示词库** | GitHub `yukkcat/image-prompts` + stimQQ + NeXra JSON + 本地包 | ✅ `promptLibrary.ts` · `promptTaxonomy.ts` · 侧栏面板 | 可继续加自定义 raw 源 |
| P0 | 渠道 / 模型配置 | `infinite-canvas:ai_config_store` | ✅ 模型管理 + `__shiguangSyncModels` | per-model 自定义 script（见 P2） |
| P0 | 生图 / 生视频 / TTS | 浏览器直连 OpenAI API | ✅ `/host/generate-*` 代理（避 CORS） | — |
| P1 | 节点类型 Image/Text/Config/Video/Audio/Group | React 内置 + registry | ✅ infinite 六核心 + 拾光 shot/script/prompt/generator | Config 参数锁定 UI 深化 |
| P1 | 插件节点 URL 安装 | `plugin-loader` + `infinite-compat` SDK | ✅ normalizeInfinitePlugin · 本地 index.json · 插件管理面板 | 与 Qt `/host/plugins` 目录打通 |
| P1 | 画布助手 / Agent-IM | workbench agent + canvas-agent | ✅ AgentPanel + project-agent | Codex Skill 列表（infinite `use-agent-skill-store`） |
| P2 | 模型 custom script | `ChannelModel.script` | ❌ | 中转站非 OpenAI 路由适配 |
| P2 | WebDAV 工程同步 | `webdav-sync.ts` | 明确不做 | — |
| P2 | 浏览器直连 Key（无 bridge） | standalone 模式 | 明确不做（拾光必须走 bridge） | — |
| P3 | 整仓切换 infinite 引擎 | `SHIGUANG_CANVAS_ENGINE=infinite` | ⚠️ 备选保留 | 仅回归对比，非主路径 |

## AI-Canvas-tauri → 自研导演台

> 参考仓：[Tenney95/AI-Canvas-tauri](https://github.com/Tenney95/AI-Canvas-tauri)（对照克隆可放 `vendor/AI-Canvas-tauri`，已 gitignore）。**不整仓嵌入 Tauri**。

| 能力 | 状态 |
|------|------|
| 分镜表 `shotlist` | ✅ 可编辑表 + 绑定画面 + 展开为镜头节点 |
| 交互宫格 `storyboard` | ✅ 绑源图 / 2–5 宫格 / 单格或全部拖出 |
| Markdown | ✅ 编辑/预览 |
| Agent canvas_* | ✅ query / select / duplicate / group / undo·redo / bindShotlistFrame / fillStoryboardCell |
| 3D 导演台节点 `director` | ✅ 内嵌 Stage3D；截图回写节点 + 另存镜头卡 |
| 逐帧动画 `animation` | ✅ Sprite Sheet · 占位表 · AI 生成 · 播放预览 |
| 全景 `panorama` | ✅ 等距柱状环视（轻量，不接 XiaoLuo） |
| 画布笔记 `note` | ✅ 文字 / 矩形 / 椭圆 / 箭头 |
| 源文件 `source` | ✅ 本地图/视频/音频/文本入口 |
| 嵌套 NLE / Comfy 宿主 / Dreamina / ONNX | ❌ 明确不做（本窗口） |

## 明确不做（仍有效）

WebDAV、整仓嵌入 infinite-canvas、浏览器直连 API Key（拾光内）、完整 IK/GLB 角色、Krea 实时、完整接入 libtv-skills 云会话（当前为自研 Agent-IM + 项目 Agent）、**Tauri 壳 / Dreamina 登录态 / 嵌套视频剪辑器 / 完整 ComfyUI 宿主**。

## 本波改动文件

- `vendor/shiguang-canvas`：`promptLibrary.ts` · `promptTaxonomy.ts` · `PromptLibraryPanel.tsx` · `public/prompts/*.json` · `infiniteCoreNodes.ts` · `infinite-compat.ts` · `text`/`config` 节点 · `PluginManagerPanel` · `NodePalette` 插件合并 · `plugin-loader` normalize · `plugin-runtime` AI SDK · `onlyRenderVisibleElements`
- 既有：`CanvasShell` · `App` · `bridge.ts` · `styles.css`
- 既有：`shotCamera.ts` / `workflowSkill.ts` / `canvas_bridge.py` 等
