# 画布桥接层 / 双库 / 视频黑框 / 缺口现状 — 从 MEMORY.md 拆出

## 桥接层与双库

- 新增 `/host/*` 端点必须用 `@_route_get`/`@_route_post` 注册进路由表（写在 return 之后 = 死代码，AST 检测）。
- 双库同步是人工动作：主库 `vendor/shiguang-canvas/src/` ↔ 副库 `vendor/AI-Canvas-tauri/src/libtv/`；验证 `check_canvas_dual_repo.py`（禁 `--update`）。
- **副库 tsc 假绿**：`tsconfig.json` 是 project references（files: []）恒报 0 错 ⇒ 用 `tsc -p tsconfig.app.json --noEmit`。副库 vitest v4 不接受 `--reporter=basic`。
- 画布测试：不能引用包外相对路径（`?raw` 解析到 vendor/app/）；vitest 无 jsdom ⇒ useEffect 零覆盖，须抽纯函数；`include` 只收 `*.test.ts`。
- Agent 触达前端唯一通道 = `make_agent_event()` + `broadcast_agent_event()`（SSE）。

## 视频黑框（2026-11-02 真机实测）

- 🔴 **画布 Qt WebEngine 没有 H.264/AAC**：`canPlayType('video/mp4; codecs="avc1.42E01E"')` 空串、`<video>` 报 `error.code=4`，**而自家成片正是 h264/avc1** ⇒ `nodes.tsx` / `codeVideoNode.tsx` 的 `<video>` 预览对 mp4 是黑的，`drawImage(video)` 也拿不到像素。webm/VP9 正常，`#t=0.1` 片段定位能画出帧。⇒ 任何「视频缩略图/封面」必须**后端 ffmpeg 抽帧**（`POST /host/team/poster` 复用 `canvas_shot_vision._grab_frame`，timeout ≤20s 压画布桥 30s 上限）。
- 🔴 **黑框处理范式（0.3.42）**：`useVideoBad()` + `<VideoUnplayable>`（`videoFallback.ts(x)`），**只靠 `<video onError>` 触发、禁超前 `canPlayType` 预判**（WebM 能播，预判会误伤）；替身封面优先级 = 显式封面 > 首帧 > 尾帧且**跳过 `blob:`**。体积基线只锁 `CanvasShell.tsx`/`styles.css`/`Stage3D.tsx`/`riggedHumanoid.ts`/`store.ts`，`nodes.tsx` 等可自由改。

## 缺口现状（2026-10-23 全库实测）

活路径 =「剪辑精剪 + AI 画布」；核心工具 = **阶段契约**（输入/输出/责任人/验收/失败语义）。已落地抽卡闭环 + 编剧端（缺长篇体系）。

- **真缺口**：① `asset_master.py` 纯模型零 import；② `aesthetic_gate.py` 零调用方 + 全库无 revision/409/ETag 乐观锁（写入口靠 `glue/policies.py:122-146` 登记册 + `check_timeline_write_surface.py` 棘轮；`agent_policy.py:185-189 can_auto_retry` 无调用方）；③ `script_doc.py` 缺 UI/存储/分集；④ `draw_book.recommend()` 的 best_seed 无消费方（回流只到 `guard_pipeline.py:166-185`）；⑤ `idea_card.py` 纯模型。
- 画布外观走 `data/canvas_appearance.json` + `GET /host/canvas-settings`（非 QSettings）。
