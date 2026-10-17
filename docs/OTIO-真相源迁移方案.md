# OTIO 真相源迁移方案（立项 · 2026-10-18）

> 状态：**已立项，待分刀实施**。决策依据：§1.4 于 2026-10-18 用户拍板推翻「不重写时间线架构」，
> OTIO 全量迁移已确认；刀1-3（TimelineStore 收拢）已提交（4633686 / abfc97e / 01130c5）。
> 本方案是刀4+ 的执行蓝图。**迁移完成前 `EditorModule._clips` 仍是唯一真相源**（§3.2 不变）。

## 1. 硬约束（不可商量的三条）

1. **Qt 段错误红线**：`opentimelineio` 的 C 扩展在 PyQt6 之后加载必崩（`_otio_worker.py` 头注实证）。
   ⇒ **内存态真相源只能是项目自研 `timeline_dsl.Timeline`（纯 Python dataclass），
   OTIO 只作为交换边界文件格式存在**（读写走独立子进程，`otio_adapter` 现成）。
   本方案中「切换到 OTIO」一律指「切换到 DSL 类型化真相源 + OTIO 文件边界」，**主进程永不 import otio**。
2. **冻结区纪律**：`clip-transform` / `transform-bake` / `canvas-transform` 三 zone（frozen_zones.json）
   锁死变换写路径（normalize/apply_normalized 唯一写入真相）——DSL 化必须保留该契约，
   触碰即需用户「解冻 <zone-id>」；`timeline_widget.py` 内 FROZEN 标记块同律。
3. **可回退**：每一刀保留旧路径 fallback（旧工程文件可读、导出双通道），全量门禁 89 项 + INTEROP + frozen_zone_guard 绿方可合。

## 2. 现状盘点（2026-10-18 勘察实证）

| 层 | 现状 | 证据 |
|---|---|---|
| 结构写入 | ✅ 已收敛 `TimelineStore`（add/remove_by_id/replace_all/clear，adopt 同一 list、原地突变保同一性） | app/core/timeline_store.py:32-102 |
| 字段级写入 | ❌ 仍散落原地改 dict（属性/调色/裁剪等 UI 回调） | editor_module.py:1667-1725 等 |
| 序列化 | 快照 provider 交 `_clips_snapshot()` 浅拷贝，落盘仍是裸 dict 列表 | editor_module.py:442-449；project_snapshot.py:196-202 |
| 类型化视图 | ✅ `store.to_timeline()` canonical 出口（锁内快照 → `clips_to_timeline` 确定性构建 DSL） | timeline_store.py:106-129 |
| DSL↔OTIO | ✅ `otio_adapter` 双向映射（metadata 保留、source_range 还原），子进程 worker | otio_adapter.py:175-215/325-404；_otio_worker.py:37-64 |
| 消费端 | 🟡 刀3 部分改读 `store.to_timeline()`；导出面（editor_export.py:49-125）仍直读 `_clips` | — |
| 互操作 UI | ✅ 导入/导出接线 + 追加入轨 compound 可撤销 + INTEROP 守卫绿 | editor_export_panel.py:153-157 |

**结论**：strangler 已收拢「结构」，未收拢「字段写 / 持久化格式 / 导出消费」。真相源切换 = 把这三块从
「裸 dict 列表」升级为「DSL canonical」，`_clips` 最终降级为 store 内部行缓存。

## 3. 分刀计划（每刀独立可回退、独立门禁）

### 刀4 · 字段级写入收拢（P0，不触冻结区）
- `TimelineStore` 增 `set_fields(clip_id, **kv)` / `update_where()` 唯一字段写 API（锁内改 live dict，保持读点同一性）；
- 存量散落直写点逐个改走 API，新增守卫 **CANONICAL**（`_verify/check_timeline_write_surface.py`）：
  扫描 `_clips` 的 `["key"] = ` 直写模式，棘轮只减不增，新代码零直写；
- 成功标准：守卫棘轮达标 + 89 项绿 + 手工冒烟（调色/裁剪/属性面板改值可撤销）。

### 刀5 · 持久化走 DSL canonical（P0，不触冻结区）
- 工程保存改存 `store.to_timeline()` 的 DSL JSON（带 `schema_version` + `format: "timeline-dsl"`），
  字段级扩展键经 DSL `metadata` 保留（不丢 transform/volume/keyframe/semantic 等）；
- 加载：新格式 → `deserialize` 回 rows；旧格式裸 dict → 原路径 fallback（双读单写）；
- 成功标准：新旧工程文件双向可开（回归用例：旧档保存→新码加载→再保存→字段 diff=0）+ INTEROP 绿。

### 刀6 · 撤销栈走 DSL diff（P1）
- `_record_action` 的 clip 快照改存 DSL 段 diff（体积降、语义稳）；保留旧 action 格式兼容读取；
- 成功标准：撤销/重做全场景回归（compound 一条撤销、粗剪写回撤销、导入追加入轨撤销）。

### 刀7 · 导出/渲染消费 Timeline（P1）
- `editor_export.py` 直读 `_clips` 的收集逻辑改读 `store.to_timeline()`（含叠轨/独立音频/keyframe 补全），
  RenderManager/FFmpeg 管线入参不变；
- 成功标准：同工程导出产物与刀前逐帧一致（抽样 diff）+ 导出面板全格式冒烟。

### 刀8 · UI 投影（P2，**触 timeline_widget 冻结区，须解冻指令**）
- `timeline_widget` 渲染/拖拽改消费 Timeline 投影 + store 写回，`_clips` 外部直读清零；
- 解冻清单（动工前逐 zone 确认）：`clip-transform`、`transform-bake`、`canvas-transform` 关联符号是否需动 = 待勘察，
  timeline_widget 内 FROZEN 标记块 = 必触；
- 成功标准：交互回归（拖拽/切分/波纹删/多选移）+ frozen_zone_guard --update 重锁留痕。

### 刀9 · 真相源宣告切换（P2，收口）
- §3.2 文档改写：真相源 = `TimelineStore`（DSL canonical），`_clips` 降为行缓存；
- 守卫升级：CANONICAL 棘轮封死一切绕过 store 的列表突变。

## 4. 排期纪律与风险

- **优先级**：刀4/5 是「切换」的实质门槛，先做；刀8/9 触冻结区，未获解冻指令**不进实施**（只出勘察）。
- **每刀铁律**：py_compile/守卫自检 + 89 项全量门禁 + frozen_zone_guard + 双侧画布 build（涉前端时）绿方可提交；失败回滚本刀，不留半刀。
- **主要风险**：
  1. DSL metadata 往返丢字段（刀5 用「旧档→新码→再存→diff=0」回归卡死）；
  2. 字段写 API 化触碰 transform 冻结语义（刀4 明确：transform 系字段仍走 normalize/apply_normalized 唯一入口，store API 只做转发不做第二套实现）；
  3. 撤销格式换代兼容（刀6 双读）。
- **与 P0-1 关系**：双库抽包已收口（§6.7 全 ✅），本迁移只动主库 `app/`，与画布包无交集。

## 5. 解冻申请模板（刀8 前置）

```
解冻 clip-transform    # 仅当勘察确认需改其锁定符号时申请
解冻 transform-bake
解冻 canvas-transform
```
解冻后改动完成即 `python scripts/frozen_zone_guard.py --update` 重锁并在提交信息留痕。
