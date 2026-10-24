# vendor 前端资源

## shiguang-canvas（默认 · 自研）

路径：`vendor/shiguang-canvas`  
拾光导演台：LibTV 向节点无限画布（React Flow）。  
宿主通过 WebEngine 镶嵌，`canvas_bridge` 回流时间线。

```bash
cd vendor/shiguang-canvas
npm install
npm run build
```

回退旧画布：`SHIGUANG_CANVAS_ENGINE=infinite`

## AI-Canvas-tauri（参考 · 不嵌入）

源码：https://github.com/Tenney95/AI-Canvas-tauri  
对照用克隆到 `vendor/AI-Canvas-tauri`（已 gitignore）。抄能力不换壳：分镜表 / 交互宫格 / Markdown / 3D导演台节点 / 逐帧 / 全景 / 笔记 / 源文件 已迁入 `shiguang-canvas`。

## infinite-canvas（备选 · MIT）

源码：https://github.com/basketikun/infinite-canvas  
由 `scripts/setup_infinite_canvas.ps1` 克隆。请勿提交 `node_modules`。
