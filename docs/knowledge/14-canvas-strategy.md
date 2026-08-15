# 14 — 自研导演台画布策略（替代 infinite-canvas）

> 目标：体感接近 LibTV / TapNow 的 **节点无限画布 + 分镜工作流**，可嵌入拾光剪影。  
> 实现：`vendor/shiguang-canvas`（默认引擎）。

## 参考（抄逻辑，不整仓嵌入）

| 项目 | 用途 |
|------|------|
| Tapnow-Studio / libtv 复刻 | 节点类型、连线、九宫格、工程结构 |
| @xyflow/react | 节点工作流底座（MIT） |
| infinite-canvas | bridge 协议、模型同步；现为备选引擎 |
| tldraw | **未引入**；标注/画笔需求明确后再评估 |

## 硬边界

- 不换 `_clips` 真相源；成片入轨仍走 `canvas_bridge` → `MATERIAL_TO_TIMELINE`
- 不把商业 LibTV/TapNow 嵌进 EXE（帮助中心仅外链备选）
- MVP 生图可为占位图；真实 AIGC 接模型广场渠道（后续）

## 切换引擎

```text
SHIGUANG_CANVAS_ENGINE=shiguang   # 默认
SHIGUANG_CANVAS_ENGINE=infinite   # 旧画布
```

端口：自研 dev/静态 `3010` / `3011`；infinite `3000` / `3001`。

## 首开性能（P0 · 2026-08-13）

| 层 | 做法 |
|----|------|
| Qt 宿主 | 进模块先出壳；`_load_canvas` 时再 `_ensure_web_view()` |
| 引擎 | 默认锁 `shiguang`；infinite 确认默认「否」 |
| 前端 | Studio / Agent / 提示词库 / 插件 / 蒙版 `lazy()`；3D 已 `lazy(Stage3D)` |
| 不做 | 进模块不自动拉 Agent（npx）；不默认 infinite |

## MVP 已有

剧本/镜头/提示词/图/视频节点 · 连线 · 九/二十五宫格 · 本地工程 · 同步模型池 · 发送到剪辑  
**「生成选中节点」→ `/host/generate-image`**（模型广场 AIGC；失败占位兜底）

### 迭代（2026-08-12）

| 能力 | 说明 |
|------|------|
| 首尾帧槽 | 镜头/视频节点本地上传参考图；生成时写入提示词约束（尚未走 img2img） |
| 一键拉片 | `POST /host/storyboard-breakdown` → LLM 分镜表 → 画布镜头节点（失败启发式） |
| 工作流模板 | 浏览器本地最多 20 条模板保存/加载/删除 |

## 借鉴清单对照

完整表见 [`16-aigc-canvas-gap.md`](16-aigc-canvas-gap.md)。

### 体验迭代（2026-08-12 续）

| 能力 | 说明 |
|------|------|
| 节点增删 | 右键 / 双击 / `/` 搜索面板 / 侧栏拖放 / Delete |
| 剪贴板 | Ctrl+C/V、Ctrl+D、Ctrl+A；连线可随节点复制 |
| 撤销重做 | Ctrl+Z / Ctrl+Y；拖拽节点前入栈 |
| 框选导航 | 左键框选 · 中键/空格平移 · 网格吸附 · F 适配视野 |
| 浮动工具条 | 选中后：生成 / 复制 / 对齐 / 入轨 / 删除 |
| **指令面板** | 画布 / 3D 导演台 **Ctrl+K**（或 `/`、`?`）搜索执行；画布另有 Ctrl+G 编组、Ctrl+Enter 生成、Ctrl+E 入轨；3D 有 V/R/S、J、N 加角色、C 截图、1–9 姿势 |
| 侧栏折叠 | 顶栏一键折叠左右栏放大画布 |
| 自动保存 | 工程防抖写入 localStorage（静默） |
| Dummy13 / BodyKun 关节素模 | 3D 导演台内置可动人偶：GLTFLoader 加载 `bodykun.glb` / `bodychan.glb`，保留 15 骨 JointPose；点选可见网格；**拉手/脚带动整条肢体（IK）**，单人与群像同一套；旋转环微调；Alt 移整人；正面=+Z |
| **LibTV 空画布复刻** | 四卡空态 + 顶栏/底栏；右键「添加节点/资源」（导演台 NEW / 拉片 / 上传） |
| **LibTV 3D 导演台** | 左图标栏画幅/角色/机位；AI 识图导入（本地参考层）；底栏场景描述 |
| Agent 状态 | 顶栏 chip +「连接 Agent」按钮；宿主按钮变「Agent 已连接」；明确是 :17371 工具通道 |
| 蒙版局部重绘 | `MaskEditDialog` → `/host/inpaint`（edits 优先，img2img 降级；失败诚实） |
| 多图叠卡 | `images[]` + `primaryImageId`；节点卡叠层徽章 |
| 工程 ZIP | STORE ZIP 导入导出（`projectZip.ts`） |
| 图工具 | 裁剪 9:16 / 宫格拆分 / 本地放大 / 旋转 |
| 生成器节点 | `generator`：mode×count，走宿主生成 |
| 编组 | React Flow `parentId` 编组 |
| 节点列表 | 左侧定位/适配视野 |
| 音频节点 | 上传入轨；TTS `/host/generate-audio` 诚实桩 |
| **AI-Canvas-tauri 对齐** | `markdown` / `shotlist` / `storyboard`；补 `director`（自研 Stage3D 节点）· `animation` · `panorama` · `note` · `source` |
| 画布 Agent 面板 | **Agent-IM 快路径**（默认 `canvas_fast`，不依赖先开剪辑）；SSE `chat.delta` 流式显示；经 `/host/project-agent/chat` |
| 参考视频片段 | 左侧「+参考视频」或节点「参考视频」槽；宿主 `/host/upload-asset` → `/inbox_file/` |

### 已对齐（含 P1–P4 + UI/3D + 体验）

宫格 · 拉片 · 模板 · AIGC 生成选中/批量 · 首尾帧 img2img · @角色/@素材 · 三视图 · 变体循环 · 上游提示汇聚 · 全部入轨+时长 · 分镜导出 · 参考重绘 · **视频节点真生成**
**UI 简洁化** · **3D 导演台** · **ComfyUI 向节点编排体验**

### 后置

蒙版局部重绘 · Form 参数锁定 · 涂鸦生视频 · Krea 实时 · 社区模板云 · 3D 关节精调 / 720° 全景 · Canvas Agent