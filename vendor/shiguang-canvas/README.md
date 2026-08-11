# 拾光导演台（shiguang-canvas）

自研 **LibTV 向** 节点无限画布，用于替代（或并行）`vendor/infinite-canvas` 作为「AI 画布」主前端。

## 设计参考（只学不整仓搬）

| 来源 | 学什么 |
|------|--------|
| Tapnow-Studio / libtv 复刻 | 节点类型、连线、九宫格分镜、工程 JSON |
| React Flow (@xyflow/react) | 节点工作流底座（MIT） |
| infinite-canvas | bridge 入轨协议、模型池同步 |
| tldraw | 后续若要标注/画笔再评估，本 MVP 未引入 |

## 能力（MVP）

- 无限画布平移缩放、小地图
- 节点：剧本 / 镜头 / 提示词 / 图片 / 视频 + 连线
- 一键九宫格分镜
- 本地工程保存（localStorage）
- 对接 `canvas_bridge :18765`：同步模型池、发送到剪辑、prefs/角色

## 开发

```bash
cd vendor/shiguang-canvas
npm install
npm run dev     # http://127.0.0.1:3010
npm run build   # dist/ → 宿主静态秒开 :3011
```

宿主默认优先本画布（见 `app/core/canvas_runtime.py`）。回退 infinite-canvas：

```text
环境变量 SHIGUANG_CANVAS_ENGINE=infinite
```
