# 19 — AI 画布设计概论 · 功能全景 · 优化建议

> 性质：**评审文档**（2026-09-13 首次全量盘点，含实测数据）。
> 与设计提案的区别：`14-canvas-strategy.md` 讲「要不要自研」，`16-aigc-canvas-gap.md` 讲「向谁借鉴」，
> 本文档讲「**现在这东西到底是什么、哪里该动**」。
> 关联：[17-canvas-magnetic-invariants.md](17-canvas-magnetic-invariants.md)（磁吸不变量）·
> [08-frozen-zones.md](08-frozen-zones.md)（改前必看：画布有两个冻结区）·
> [18-codebase-health-2026-09.md](18-codebase-health-2026-09.md)（全库体检数据）

## 零、结论先行

| 维度 | 评分 | 判读 |
|---|---|---|
| 设计完整度 | **9.0** | 理念、铁律、不变量、三版对比都写透了，远好于多数个人项目 |
| 功能广度 | **8.5** | 21 种节点 + 磁吸 + 小白模式 + 插件 + 3D 导演台，覆盖度接近商业产品 |
| 工程健康 | **5.5** | 72 处 `as any`、40 个 tsc 存量错误、`store.ts` 2310 行/159 action |
| 可维护性 | **5.0** | 4 个超大文件 + 单函数 2000 行路由链，是全库「可维护 6.0」洼地的主要来源之一 |
| **双库一致性** | **4.0** | **当前最大风险**：16 个文件已分叉，副库缺整个小白模式 |

**一句话**：画布**不缺设计和功能，缺的是「别让它继续烂下去」的机制**。
最该做的三件事：① 给双库加自动漂移校验（止血）② 修画布角色→提示词字段不一致（静默错误）
③ 把 `canvas_server.py` 的 47 端点 if 链改成路由表（顺手且不在冻结区）。

---

## 一、设计概论

### 1.1 要解决什么问题

把「一句话 → 一条能播的片」这条链路**可视化编排**；把传统 NLE 的「素材进时间线」**前移到分镜设计**，
消除**导演意图**与**剪辑结果**之间的断档。

### 1.2 核心理念

> **「剪辑宿主里的乐高导演台——用积木的直觉，做分镜的专业」**

- **骨架**：导演台 + 入轨闭环 + 诚实失败
- **血肉**：磁吸 + 可玩性五维度 + AI 作为可见协作者 + 层叠混血

**北极星**：竖切可重复——乐高式搭分镜 → 生成选中/批量 → 一键入轨精剪。
Agent 只做「确认后执行」的遥控器，**不默认一键成片**。

### 1.3 写在文档里的硬边界

| 原则 | 含义 |
|---|---|
| 不换真相源 | `_clips` 唯一；入轨走 `canvas_bridge → MATERIAL_TO_TIMELINE`，带 `canvas_node_id` round-trip |
| 不嵌商业产品 | 抄 LibTV/TapNow 的逻辑，不整仓嵌入；不换壳（Wails/Tauri/tldraw/Dify） |
| 诚实失败 | 无模型不假成功，不写假图/假视频/假口型 |
| 空间关系即语义 | 卡片的位置/邻接本身表达叙事关系（磁吸判据、Bond 咬合都源于此） |
| 磁吸柔性连接可逆 | 软连接（SoftConnection）可固化为正式 edge |
| 没有错误连接，只有风险不同的连接 | 不阻止用户连线，只提示风险 |
| AI 是可见协作者 | 不是黑箱自动执行 |
| 画布发散、时间轴收敛 | 两侧职责不互相侵蚀 |

### 1.4 三版演进与最终选择

| 版本 | 思路 | 体验 / 落地 / 战略 |
|---|---|---|
| v1 融合版 | 磁吸画布 × 导演台对半融合 | 45 / 75 / 50 |
| v2 积木架构 | 磁吸内核 + 拾光集成层，拆壳即独立产品 | 80 / 55 / **95** |
| **v3 导演台磁吸版（选用）** | 骨架不动 + 磁吸血肉 | **95 / 85 / 75** |

选择理由（原话）：「投入产出比最高：落地风险可控（基于现有架构），体验提升最大，差异化竞争力最强」。
v2 战略价值更高但「架构改动最大、需同时维护两条产品线」。已落地：MVP → 第二阶段 → 第三波。

### 1.5 与 PyQt6 宿主的分工

| 侧 | 职责 |
|---|---|
| **宿主 Python** | `_clips` 真相源；`canvas_bridge/runtime/server/aigc/agent_runtime` 提供 HTTP + SSE（**端口 18765**）；真实 AIGC 调用、落盘、入轨 |
| **前端画布** | React 19 + Zustand + @xyflow/react + Three.js；只做交互与意图表达；磁吸层**纯叠加、不侵入节点内部、不落盘** |
| **约定边界** | `bridge.ts` 是唯一环境耦合点；两侧仅通过 `/host/*` 增量接口扩展；画布预热只能在模块可见时触发 |

### 1.6 双库关系（重要）

- `vendor/shiguang-canvas` = **主库 / 事实源 / 默认引擎**
- `vendor/AI-Canvas-tauri/src/libtv` = **副库**（Tauri 宿主中的「拾光导演台」视图）

当前靠 **5 个数据契约文件 Windows 硬链接共享 inode**（templates / schema-migrations / history-store /
project-storage / migrations）维持单一事实源——因为 rolldown-vite 在 Windows 有盘符 `is_absolute` bug，
vite alias 不可用。目标方案是抽成 `@shiguang/libtv` + pnpm workspace（`P0-1-双库抽包迁移方案.md`），
**Phase 0-b/1/2/3 均未开始**。

---

## 二、功能全景

### 2.1 节点类型（21 种 kind）

| kind | 用途 |
|---|---|
| `shot` | 分镜头卡（景别/时长/运镜/角色绑定/补帧） |
| `script` | 剧本卡，分镜上游 |
| `image` / `video` | 图片（多版本 stack） / 视频（画质档/运动幅度/首尾帧权重） |
| `prompt` / `text` / `config` | 上游文本汇聚 → 模型输入 / 可复用文本 / 生成配置锁模型 |
| `generator` | 汇聚上游批量生成（拾光扩展） |
| `group` | 编组容器 |
| `audio` / `music` | TTS 音频 / Suno 原创音乐 |
| `markdown` / `shotlist` / `storyboard` | 文档 / 可编辑镜号表 / 交互宫格分镜 |
| `director` / `directorCard` | 3D 导演台（截图回写本节点）/ 剧本自动拆镜 |
| `digitalHuman` | 数字人（形象 + 台词 TTS） |
| `animation` / `panorama` / `note` / `source` | 逐帧 Sprite / 全景 / 画布笔记 / 本地素材入口 |

连线类型由 `inferEdgeType()` 按 source/target kind 推断为 prompt/image/video/audio/data 五类。
`templates.ts` 提供 5 套模板（竖屏短剧 3 场 / 产品卖点 3 镜 / 情绪板 / MV 七拍 / 快速生图卡）。

### 2.2 状态与数据流（`store.ts` 2310 行）

zustand `create<Store>()`，**未用 persist 中间件**，手写 localStorage。

| 切片 | 内容 |
|---|---|
| 图 | nodes / edges / selectedId / dirtyVersion |
| 视图 | viewMode / canvasLayoutMode(flow·simple·storyboard) / magneticMode / showGrid / smoothLine / editorTier |
| 项目 | activeProjectId / activeCanvasId / dramaTitle / episode / ProjectBundle |
| 角色 | characters[] + `refreshCharacters`（GET `/host/characters`） |
| 3D | stage3d 快照 / stage3dApplySeq / pendingStage3dCameras |
| 导演台 | directorTargetNodeId |

共 **159 个 action**（代表性：`addNode` / `addRegistryNode` / `applyStoryboard` /
`breakdownDirectorCard` / `addCaptureToCanvas` / `pushLayer·hybridLayers` / `reviewNode` /
`undoGraph·redoGraph` / `saveProject·loadProject` / `bindCharacterToShot` / `applyStage3dCameraPlan`）。

- **撤销**：`stores/history-store.ts`，模块级 `graphPast/graphFuture/clipboard`，存 `GraphSnap`
- **持久化**：`project-storage.ts`（localStorage + bundle）· `persist-media.ts`（dataURL → 宿主 inbox 引用，规避配额）· `schema-migrations.ts`（V1→V2→V3）

### 2.3 磁吸系统（`src/magnetic/` 15 文件）

| 文件 | 职责 |
|---|---|
| `types.ts` | 类型中枢：MagneticLevel / SpatialDirection / CARD_SIZE / 语义映射 |
| `MagneticEngine.ts` | **计算核心**（无 React）：距离→等级、方向→语义、吸附坐标 |
| `SpatialIndex.ts` | Grid Hash 空间索引，O(n²) → 近似 O(候选) |
| `SpatialAnalyzer.ts` | 识别 sequence/parallel/loop/branch/cluster/free + 自动排布 |
| `bonds.ts` | 咬合检测（几何推导、**不落盘**），磁吸的静态结果态 |
| `SoftConnection.ts` | 强吸附时生成「潜在血缘」虚线，可固化为正式 edge |
| `CardStack.ts` | 卡片多版本层叠纯函数（挂 `node.data.stack`） |
| `useMagneticDrag.ts` | **入口 Hook**：包 RF drag 三事件，磁吸→咬合阻力(30/50px)→落座回弹 |
| `MagneticLines` / `SnapSeam` / `SnapSlotHighlight` / `SoftConnectionLines` | 4 个可视化层 |
| `StackBadge` / `StatusBadge` / `FloatingToolbar` | 3 个浮层 UI（版本切换 / 状态灯 / 快捷操作含「一键整理布局」） |

串联：`CanvasShell.tsx`(3187 行) → `useMagneticDrag` → 4 个可视化子组件，通过 ReactFlow `children`
绝对定位渲染，**不侵入节点组件**。

### 2.4 小白模式（`src/novice/`）

`types.ts`（规格常量 + L1/L2/L3 参数分层 + 意图胶囊）· `NoviceCard.tsx`（纯矩形卡面）·
`NoviceInspector.tsx`（参数降维）· `index.ts`（`buildNoviceNodeTypes()`）。

**切换不重建画布**：复用同一 ReactFlow 实例与同一份 nodes/edges，只把内置节点换成 NoviceCard，
插件节点（`key.includes(":")`）保留原渲染器。开关在 `AppNav.tsx`，写
`localStorage["shiguang-canvas:tier:v1"]` 并强制 `magneticMode:true`。

### 2.5 插件机制（`src/plugins/`）

独立 JS bundle（external react/@xyflow），**Blob URL + dynamic `import()`** 加载。

`node-registry.ts`（注册表中枢 zustand Map）· `plugin-loader.ts`（fetch→Blob→import→activate）·
`plugin-store.ts`（localStorage 持久化）· `plugin-runtime.ts`（注入宿主 React/AI 能力，避免重复打包）·
`event-bus.ts`（零依赖）· `infinite-compat.tsx` · `examples/sticky-note.tsx`。

### 2.6 Agent 与宿主通信

- **`bridge.ts`(1616 行)**：`http://127.0.0.1:18765`；token 三级回退
  （`window.__SHIGUANG_BRIDGE_TOKEN` → localStorage → URL `?token=`）
- **SSE 仅一处**：`subscribeAgentEvents()` → `/host/agent/events`，带自动重连
- **`AgentPanel.tsx`(1461 行)**：Agent-IM 侧栏，对话 + 工具调用（`/host/tools`、`/host/tools/run`）
  + 会话控制 + 分镜拆解
- **配套**：`workflowSkill.ts`（画布导出成 `shiguang-canvas/skill/v1` 供 Agent 复现工作流）·
  `promptLibrary.ts`(615 行) · `promptTaxonomy.ts`(395 行，含 sfw/mature/nsfw 成熟度映射)

### 2.7 3D 导演台

| 文件 | 行数 | 职责 |
|---|---|---|
| `Stage3D.tsx` | 4427 | 纯 three.js（无 R3F，为 Qt WebEngine 稳定）：关节素模 + 群像站位 + OrbitControls + Bloom |
| `riggedHumanoid.ts` | 3707 | 5 体型预设、15 关节 21 旋转角骨架、POSE/MOTION_PRESETS、GLTF 加载 |
| `stage3dPoseRetarget.ts` | | BlazePose 关键点逐帧重定向为 JointPose（含坏帧插值） |
| `stage3dControlNet.ts` | | 导出 Depth/Normal/OpenPose 三通道给 ComfyUI |
| `shotCamera.ts` | | 8 组机位预设 → 提示词片段 |

**3D↔2D 联动（单向 + 回写）**：DirectorNode 点击 → `directorTargetNodeId` → App 渲染 Stage3D →
截图 `addCaptureToCanvas()` 回写节点；反向 AI 机位计划 → `applyStage3dCameraPlan()` → 递增
`stage3dApplySeq` → Stage3D 消费 `pendingStage3dCameras`。

---

## 三、实测健康度（2026-09-13 复核）

| 指标 | 主库 shiguang-canvas | 副库 libtv |
|---|---|---|
| `src/**/*.{ts,tsx}` | 84 文件 / 33,730 行 | 77 文件 / 31,701 行 |
| `as any` | **72 次** | 72 次（完全一致 ⇒ 复制式同步，非共享） |

**`as any` Top5**：`stores/templates.ts` 28 · `CanvasShell.tsx` 17 · `AgentPanel.tsx` 12 ·
`storyNodes.tsx` 5 · `bridge.ts` 5

**超大文件**：`Stage3D.tsx` 4427 · `riggedHumanoid.ts` 3707 · `CanvasShell.tsx` 3187 ·
`store.ts` 2310 · `AgentPanel.tsx` 1461 · `bridge.ts` 1616

**宿主侧**：`canvas_server.py` **2400 行**，`/host/*` **端点 47 个**，全部平铺在
一条 `if path == "..."` 链里（第 321~2317 行，近 2000 行），**无路由表**。
其余：`canvas_aigc.py` 2414 · `canvas_bridge.py` 879 · `canvas_runtime.py` 611 · `canvas_agent_runtime.py` 416。

**双库分叉**：
- 副库**完全缺失** 7 个文件：`magnetic/bonds.ts`、`SnapSeam.tsx`、`SnapSlotHighlight.tsx`、
  **整个 `novice/`（4 文件）** ⇒ 副库无咬合缝、无六向槽位高亮、**无小白模式**
- 明显缩水：`useMagneticDrag.ts` −7.3KB（12.4K→5.1K，**阻力手感被裁**）、`types.ts` −4.1KB、
  `MagneticEngine.ts` −2.0KB、`CanvasShell.tsx` −3.2KB、`store.ts` −2.0KB
- 结论：**副库是主库的降级快照**，磁吸手感与小白模式是主库独有演进

**类型检查**：`tsc --noEmit` 存量 **40 错，全在冻结区文件**（`riggedHumanoid.ts` 21 ·
`Stage3D.tsx` 16 · `bridge.ts` 3）；vite build 不做类型检查所以不拦构建。

---

## 四、优化建议（按优先级）

### P0 — 止血（不做会持续恶化）

| # | 问题 | 证据 | 建议 | 风险 |
|---|---|---|---|---|
| **P0-1** | **双库漂移无自动校验** | 16 文件已分叉，副库缺整个 `novice/`，`as any` 分布一模一样说明靠复制 | 加 `_verify/check_canvas_dual_repo.py`：比对待同步文件清单的哈希/行数，纳入 `run_all_checks.py`。**先止血，再谈抽包** | 低（只加脚本） |
| **P0-2** | **画布角色→提示词字段不一致（静默）** | Python `build_character_prompt` 用 visual 组 4 字段；`store.ts::bindCharacterToShot/syncCharacterToShot`（约 2163/2209 行）**只拼 `[角色外貌: appearance]`** | 画布侧对齐同一字段集；「标志性符号」是跨集一致性锚点，当前在画布绑角色时**被丢掉** | 中：`store.ts` 在冻结区 `canvas-magnetic-intent`，需走解冻流程 |
| **P0-3** | **`inner` 组 8 字段零消费点** | `core_desire` / `values` 等只在 `node-factory.ts` 类型里出现 | 至少在角色卡可见（跨集一致性要查），否则是死字段 | 低（新增 UI） |

### P1 — 值得规划

| # | 问题 | 建议 | 风险 |
|---|---|---|---|
| **P1-1** | `canvas_server.py` 2400 行、47 端点平铺 if 链 | 改成**路由表**（`{path: handler}` 字典），加端点不再往 2000 行链里塞 | 低：**不在冻结区**，可直接改 |
| **P1-2** | `store.ts` 2310 行 / 159 action | 按切片拆（图 / 视图 / 项目 / 角色 / 3D / 导演台 / 磁吸） | 中：在冻结区，需解冻 |
| **P1-3** | 分镜表只有 `duration`，无情绪/记忆维度 | 后端算「观众记忆预估」，前端加一列。理论依据见 `app/core/ai/memory_model.py`（24h：细节 11.5% / 意义 61.9% / 情绪 82.5%）⇒ 细节镜头可剪碎、情绪锚点给足时长 | 低：`storyNodes.tsx` 不在冻结区 |
| **P1-4** | `as any` 72 处（templates 28 最多） | `NodeData` 联合类型已有 21 分支，模板数据没吃到类型。先清 `templates.ts` | 低 |

### P2 — 有空再做

| # | 建议 |
|---|---|
| P2-1 | `tsc --noEmit` 进 CI，采用**基线制**：存量 40 错列白名单冻结，只允许新文件零错误 |
| P2-2 | 画布 AgentPanel 接 `suggest_next`（画布 action 多为本地执行、失败信号弱，收益低于剪辑侧，排 P2） |
| P2-3 | 画布节点按「最近使用 / 绑定次数」下沉排序（对应系统侧记忆强度机制） |

### P3 — 文档漂移（顺手修）

- `项目全库架构解析与AI编辑指南.md` 称 `SpatialAnalyzer.ts` 是「无连线孤儿代码，要么接一键整理要么删」
  ——**实测已接线**（`FloatingToolbar.tsx:142` 的「一键整理布局」按钮调用
  `autoLayoutSequence/autoLayoutParallel`）。需回写。
- `17-canvas-magnetic-invariants.md` 曾提示 `bonds.ts`/`SnapSeam.tsx` 未进冻结区 `files`
  ——2026-09-13 已补入（该 zone 现 30 锁点）。

### 明确不做

- 嵌 Comfy 宿主 / 嵌套 NLE / Dreamina / ONNX（`16-aigc-canvas-gap.md` 已定 ❌）
- 把 `Stage3D.tsx` / `riggedHumanoid.ts` 当重构入口——在 `stage3d-core` 冻结区，只做边缘新增
- 为统一双库现在就抽 pnpm workspace——先跑 P0-1 拿到漂移清单再决定

---

## 五、与其他文档的关系

- 磁吸不变量与解冻注意：[17-canvas-magnetic-invariants.md](17-canvas-magnetic-invariants.md)
- 冻结区（画布两个 zone：`canvas-magnetic-intent` 30 文件、`stage3d-core` 7 文件）：[08-frozen-zones.md](08-frozen-zones.md)
- 自研策略与借鉴清单：[14-canvas-strategy.md](14-canvas-strategy.md) · [16-aigc-canvas-gap.md](16-aigc-canvas-gap.md)
- 全库体检数据：[18-codebase-health-2026-09.md](18-codebase-health-2026-09.md)
