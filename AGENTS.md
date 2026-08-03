# AGENTS.md — 拾光剪影

本仓库给编码 Agent 的入口说明。

## 先读

| 优先级 | 路径 |
|--------|------|
| 1 | [`docs/knowledge/INDEX.md`](docs/knowledge/INDEX.md) |
| 2 | [`docs/knowledge/08-frozen-zones.md`](docs/knowledge/08-frozen-zones.md)（**已修好功能锁死**） |
| 3 | [`CONTEXT.md`](CONTEXT.md) |
| 4 | [`docs/P0_CAPCUT_ALIGN.md`](docs/P0_CAPCUT_ALIGN.md)（剪辑对齐范围） |
| 5 | [`.workbuddy/memory/MEMORY.md`](.workbuddy/memory/MEMORY.md)（长期记忆） |

## 冻结区

未获用户「解冻 \<zone-id\>」前，禁止改 `frozen_zones.json` 所列符号与 `FROZEN:*` 标记块。

```bash
python scripts/frozen_zone_guard.py          # 检查
python scripts/frozen_zone_guard.py --update # 解冻改完后重写基线
```

## 活路径

见知识库 INDEX「活路径」一节（主路径 + 抽出副路径 + 拓展/闭环）。剪辑改动优先这批文件，勿误入未接线的 `AppState` / 孤儿 `ExportRenderer`。注意注册表 id 为 **`extensions`**（非旧 `plugins`）。

## 同步知识库

```bash
python scripts/sync_knowledge.py
```

会刷新 `docs/knowledge/sources/MANIFEST.md` 与 `docs/knowledge/catalog.json`。
