# 17 — 参考视频驱动生视频（模式 A / B）设计

> 制定日：2026-08-26
> 目标：让 3D 导演台的「动作」可被控制，喂给视频生成模型出片。
> 硬边界：不推翻现有 `generate_video_via_host` 链路；不假成功；最小侵入。

## 一、背景与结论

漫剧刚需：走路、走位、对话正反打、动作片段剪辑拼接、个别坏帧修正、切换机位。核心诉求是把「参考视频里的动作」变成可控、可编辑的生成条件。

两种模式做成**开关**（用户在 3D 导演台二选一）：

| 模式 | 链路 | 适合 | 代价 |
|------|------|------|------|
| **A · 动作参考**（对标 LibTV/TapNow） | 参考视频直接作 motion-ref 条件送模型 | 原地完整舞蹈、快速出片 | 空间/机位/局部动作不可控 |
| **B · 姿态解析到 3D 白模**（自研差异化） | 视频→关键点→IK 白模时序→录制白模视频→送模型 | 走位、剪辑动作、换机位、修帧 | 需整套姿态子系统 |

**共同收口**：模式 B 录制的白模预览视频，本质也是一个 `reference_video`，复用模式 A 的「参考视频条件通道」。

## 二、现状核实（代码事实）

- 后端 `generate_video_via_host`（[canvas_aigc.py](../../app/core/canvas_aigc.py)）仅支持 `reference_image` / `first_frame` / `last_frame` 三类 **image 条件**；分支覆盖 CogVideoX 首尾帧、硅基流动 Wan、可灵 Kling、MiniMax Hailuo、通用 OpenAI 兼容、`local/` 本地推理。
- `/host/generate-video`（[canvas_server.py](../../app/core/canvas_server.py)）只透传 image 字段。
- 前端 `generateVideoViaHost`（[bridge.ts](../../vendor/shiguang-canvas/src/bridge.ts)）同步只传 image 字段。
- 模型池 capability 仅 `image`/`video`/`audio`（[model_config.py](../../app/modules/lego/model_config.py)），无「视频运动参考」标记；可灵已列 `kling-v1.6-i2v`（图生视频）。
- 3D 导演台已有 motion 子系统：[Stage3D.tsx](../../vendor/shiguang-canvas/src/Stage3D.tsx) 的 `pose/motion/route` tab、BVH 导出；[stage3dControlNet.ts](../../vendor/shiguang-canvas/src/stage3dControlNet.ts) 的 OpenPose 骨架导出。参考视频可上传/预览，但**未驱动骨骼、未喂生成模型**。

## 三、模式 A 如何处理（后端只有 image 条件）

模式 A 不是「给现有模型加个参数」——当前**没有任何已接模型支持视频运动参考输入**。分三步，都不阻塞、不假成功：

1. **一等字段**：`reference_video` 升格为贯穿桥接的字段（bridge → server → generate_video_via_host → 具体模型分支）。
2. **能力探测**：channel/model 增加 `video_motion` capability 标记；传入 `reference_video` 但模型无此能力时，诚实返回「当前模型不支持视频运动参考」。
3. **真模型接入**：单独接一个支持 motion-ref 的模型（可灵/即梦进阶款，或 Wan-Fun 类 motion 控制），接完点亮。

## 四、第一刀（竖切起点）：参考视频条件通道

```
3D 导演台 上传/选择参考视频 → bridge → 后端落 inbox → 能力探测 → 诚实返回
```

这是模式 A/B 的**公共前置**，今天即可独立验证（上传→落盘→探测→状态反馈），不碰姿态子进程与 IK 重活。

### 4.1 后端改动

- `generate_video_via_host` 增加 `reference_video: str = ""` 参数：非空时先落 inbox（复用 `_canvas_inbox_dir()` 与 `/inbox_file/` URL 规则），把视频 URL/路径纳入返回与后续模型分支上下文。
- 能力探测：新增轻量 `_probe_video_motion_support(channel_id, model)`，读模型池该模型的 capability 是否含 `video_motion`；当前全池缺失 → 返回 `{"ok": False, "message": "当前渠道/模型不支持视频运动参考，请改用图片条件或模式 B", "supports_motion_ref": False}`。
- `/host/generate-video` 端点透传 `reference_video`。

### 4.2 前端改动

- `bridge.ts` `generateVideoViaHost` 增加 `reference_video?` 字段并透传。
- 3D 导演台动作面板新增「参考视频」槽 + 模式开关（A/B）；上传走既有 `/host/upload-asset`，生成时把 inbox 引用作为 `reference_video` 传回。

### 4.3 验收

上传参考视频 → 生成 → 后端标识 `supports_motion_ref=False` 并诚实报错（不写假片）；日志含落盘路径与 URL。

### 4.4 实施记录（2026-08-26 · 第一刀已落地）

| 层 | 文件 | 改动 |
|----|------|------|
| 后端 | `canvas_aigc.py` | 新增 `_normalize_reference_video()`（data URL 落 inbox / inbox URL 校验 / 本地路径复制进 inbox）+ `_probe_video_motion_support()`（读模型池 `capability == video_motion`）；`generate_video_via_host` 增加 `reference_video` 参数与门禁分支（分支优先级 0），本地管线与无能力渠道均诚实失败并返回 `supports_motion_ref=False` + 已保存的 `reference_video_url/path` |
| 后端 | `canvas_server.py` | `/host/generate-video` 透传 `reference_video`（兼容 `referenceVideo`） |
| 前端 | `bridge.ts` | `generateVideoViaHost` 增加 `reference_video` 字段与 `supports_motion_ref` 返回类型 |
| 前端 | `Stage3D.tsx` | 动作 tab 新增「参考视频驱动（模式 A）」区块：`uploadAssetToHost` 上传→inbox URL 挂载/移除；`exportFirstLastFrames` 把 `referenceVideoUrl` 带入导出 meta |
| 前端 | `App.tsx` | 3D 导演台首尾帧生成调用透传 `reference_video`，状态栏显示「含动作参考视频（motion-ref）」 |

验证：`py_compile` 通过；行为测试确认（探测诚实失败 / 文件不存在诚实失败 / local 渠道诚实失败）；`npm run build` 通过（2.85s）；`stability_gate` clean（397/400）；`frozen_zone_guard` 已 `--update` 固化（52 locks，含 Stage3D.tsx 本次授权改动）。

## 五、后续竖切（估算顺序，不一次做完）

| 刀 | 内容 | 出口验收 | 状态 |
|----|------|---------|------|
| 1 | 参考视频条件通道（§四） | 上传→落盘→探测→诚实反馈 | ✅ 已完成（2026-08-26） |
| 2 | 模式 B 姿态解析子进程 | 视频→BlazePose 关键点 JSON 落盘，进程退出释放显存 | ✅ 已完成（2026-08-26，见 §5.1） |
| 3 | 关键点→白模 IK 时序 | 3D 导演台逐帧驱动 + OpenPose 逐帧可视化；可拖拽修坏帧 | ✅ **已完成**（2026-09-20 核实，见 §5.2；本表此前误记「待开工」） |
| 4 | 录制白模视频→作 reference_video 送生成 | 复用 §四通道；走位/机位/动作拼接可控 | 待开工 ← **当前真正的下一刀** |
| 5 | 模式 A 真模型接入 | 接 motion-ref 模型，点亮 `video_motion` 能力 | 半做：通道与能力探测已就位，尚无模型支持（见 §5.3） |

> ⚠️ **2026-09-20 状态订正**：本表原记「刀 3 待开工」，但代码核实显示刀 3 **早已落地**。
> 起因是把 §五 表格当成了权威 —— 表格是 2026-08-26 写的，之后代码推进了、文档没跟上。
> **教训：这张表只是索引，不是事实；每一项动手前必须回代码核实。**

### 5.2 第三刀实施记录（关键点 → 白模 IK 时序）

**核实日 2026-09-20**（代码早已存在，本次补记）：

| 层 | 文件 | 实现 |
|----|------|------|
| 新增（纯函数） | `vendor/shiguang-canvas/src/stage3dPoseRetarget.ts`（336 行） | 头注释即写明「模式 B 第三刀」。导出：`PoseFrame` / `PoseTrack` / `COCO18_SKELETON` / `COCO18_CN` / `KP_VIS_THRESHOLD=0.4` / `parsePoseTrack` / **`solveFramePose`（单帧 COCO18+BlazePose z → 25 关节角）** / `lerpJointPose`（坏帧插值） / `solveFrameRoot`（根位移） / `findStandHipY`（站立基线） / `isFrameEmpty` |
| 骨架侧 | `vendor/shiguang-canvas/src/riggedHumanoid.ts:2192` | 新增 `applyPoseResolved(root, resolvedPose)` —— 本节所依赖的驱动接口（**该文件在 `stage3d-core` 冻结区，当时走了解冻→改动→重锁**） |
| UI/状态 | `vendor/shiguang-canvas/src/Stage3D.tsx` | `loadPoseTrack(url)`（:3198）· `togglePoseDrive()`（:3219，选中 actor 逐帧跟随）· `solvePoseForFrame()`（:3104，带 `poseSolvedCacheRef` 缓存）· `applyPoseFrameToActor()`（:3131）· **`togglePoseBadFrame(i)`（:3281，手动标记/取消坏帧）** · 坏帧自动向两侧找好帧插值（:3116-3123）· `recordPoseKeyframe()`（:3414）· 关键点编辑模式 `poseEditOn`（叠加小窗可拖拽修正，:815） |

**出口验收逐条对账**：

| 验收项 | 结果 | 证据 |
|---|---|---|
| 3D 导演台逐帧驱动 | ✅ | `togglePoseDrive` + `applyPoseFrameToActor` + 逐帧前进/后退（:3264） |
| OpenPose 逐帧可视化 | ✅ | `COCO18_SKELETON` + `COCO18_CN` + `poseEditOn` 叠加小窗 |
| 可拖拽修坏帧 | ✅ | `togglePoseBadFrame` 标记 + `poseEditOn` 拖拽修正 + `lerpJointPose` 自动插值 |

**关键设计约定（后续改动勿破）**：
- 坐标约定（`stage3dPoseRetarget.ts:9-13`）：图像 x 右正 / y 下正；**角色左侧 = 图像右侧 = 世界 +X（镜像）**；BlazePose z 越小越近相机 → 世界 +Z 取 **-z**
- 角度约定与 `riggedHumanoid.JOINT_LABELS` 对齐：ShoulderX/HipX 正 = 前摆；lShoulderZ/lHipZ 正 = 外展，rShoulderZ/rHipZ 负 = 外展；肘/膝正 = 弯曲
- 关键点可信阈值 `KP_VIS_THRESHOLD = 0.4`，低于此值按缺失处理
- 缺失关节**沿用 prevPose**（保持动作连续），无 prev 则 0（中立）
- `parsePoseTrack` 结构不符返回 `null` —— **诚实失败，不猜数据**

### 5.3 第五刀现状（模式 A 真模型接入）

通道侧已全部就位（2026-09-20 核实）：
`canvas_aigc.py` 有 `reference_video` / `_probe_video_motion_support()` / `supports_motion_ref`；
`canvas_server.py`、`capability_handlers.py`、`bridge.ts`、`App.tsx` 均已贯通 `reference_video`。

**缺口只有一个**：模型池里**没有任何模型声明 `video_motion` 能力** ⇒ 走到门禁分支即诚实返回
「当前渠道/模型不支持视频运动参考」。**接上一个支持 motion-ref 的模型即可点亮。**

### 5.1 第二刀实施记录（2026-08-26 · 模式 B 姿态解析子进程）

| 层 | 文件 | 改动 |
|----|------|------|
| 新增 | `app/core/ai/pose_worker.py` | 独立子进程脚本（不 import app.*）：`--check` 依赖探测；`--video/--out` 逐帧 BlazePose 推理；输出 kps33（原始归一化坐标）+ coco18（OpenPose 18 映射，对齐 stage3dControlNet.ts 约定）；`--sample-step/--max-frames`（硬上限 900 帧）控制工作量；裸 print 零使用（stdout 单行 JSON 通信） |
| 新增 | `app/core/ai/pose_extract_service.py` | `PoseExtractService` 单例：`check_backend()` 子进程探测（结果缓存）；`extract()` 调度（CREATE_NO_WINDOW + timeout + 互斥锁，同时刻仅一个推理占 GPU）；结果 JSON 落 canvas inbox 返回 `/inbox_file/` URL；frozen（发布版）环境诚实降级 |
| 后端 | `canvas_server.py` | 新增 `POST /host/pose-extract`：复用 `_normalize_reference_video` 做 URL→本地路径；外链 URL 拒绝（仅本地/画布视频） |
| 前端 | `bridge.ts` | 新增 `poseExtractViaHost()` |
| 前端 | `Stage3D.tsx` | 动作 tab 新增「姿态解析（模式 B）」区块：挂载参考视频后可解析；`motionPoseData`（帧数/时长/fps/JSON URL）为第三刀直接输入；`poseBusy` 防重复点击 |
| 打包 | `ai_video_editor_local.spec` | datas 收录 `pose_worker.py`（纯脚本不被 import） |

诚实失败矩阵：mediapipe 缺失（返回 pip 安装指引）/ 发布版 frozen（返回开发环境说明）/ 视频不存在 / 视频无有效帧 / 子进程超时（提示缩短视频或降采样密度）/ 外链 URL 拒绝——全部不假成功。

## 六、显存与线程约束

- 姿态推理放独立子进程，推理完立即退出释放显存，不与 AI 画布视频生成抢显存。
- 模式 B 白模动画在 3D 导演台（前端 WebGL）内完成，不占后端 GPU。
- 任一环节失败保留 fallback（退回 image 条件），符合「可回退」铁律。

## 七、明确不做（本窗口）

完整骨架 IK/GLB 精调（沿用现有 15 骨）、口型驱动成片、内置商业 motion-ref 引擎、OpenPose 生产级多人姿态（仅单人漫剧角色够用）。