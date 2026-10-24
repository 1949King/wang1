# 07 — 编码规则

与 [`CONTEXT.md`](../../CONTEXT.md) 一致，知识库侧补充实操细则。

## 命名

- 类：PascalCase · 函数/方法：snake_case · 私有：`_` 前缀 · 常量：UPPER_SNAKE

## 硬规则

1. 改前先读结构与活路径（见 INDEX）
2. 理解现有业务再加功能
3. **最小改动**，不破坏已有能力
4. 分层：UI 渲染 / core 算数据 / 主窗口调度
5. 对话框必须有 parent
6. 异常：校验输入、防重复点击、用户可见错误；吞异常至少 `logger.warning`

## 剪辑相关

- 真相源：`EditorModule._clips`
- 轨索引：用 `find_track_index_by_type`，禁止魔法数字 `track==1`
- 播放：墙钟 + 顺序解码；勿恢复 `+=0.033` 主时钟
- 联动音频：BGM 同步须过滤，避免与主视频播放器双开
- 扩展优先，遵循「最小入侵、最大兼容」；P0 文档写明的「不做」不要擅自开干

## 冻结区（锁死）

已验证能力见 [`08-frozen-zones.md`](08-frozen-zones.md) / [`frozen_zones.json`](frozen_zones.json)。

- **未解冻禁止改**对应符号与 `FROZEN:*` 标记块
- 校验：`python scripts/frozen_zone_guard.py`
- 解冻后重锁：`python scripts/frozen_zone_guard.py --update`

## 提交

- 仅在用户明确要求时 commit
- 不 fortuitously 提交 `.env`、凭证、auth.db-wal 等
