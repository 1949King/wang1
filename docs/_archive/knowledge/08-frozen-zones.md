# 08 — 冻结区（已修好功能锁死）

> **目的**：防止后续改动回退已验证的音画/变换/插件能力。  
> **机器校验**：`python scripts/frozen_zone_guard.py`

## 清单

机器可读：[`frozen_zones.json`](frozen_zones.json)  
哈希基线：[`frozen_zones.hashes.json`](frozen_zones.hashes.json)（由 guard `--update` 生成）

| zone-id | 标题 | 锁点 |
|---------|------|------|
| `playback-av` | 时间线播放 · 音画同步（2026-08-07 解冻接 speed_ramp 后已重锁） | 17 |
| `exit-media` | 关程序停声 · 防幽灵音频 | 6 |
| `clip-transform` | 归一化变换模型 | 2 |
| `transform-bake` | 变换关键帧导出 bake | 6 |
| `canvas-transform` | 预览画布变换交互 | 7 |
| `plugin-host-ui` | 插件宿主常驻 UI 入口（短剧筛选功能已卸，宿主打开/关闭仍冻结） | 4 |
| `plugin-store-catalog` | 插件商店真实目录 | 3 |
| `stage3d-core` | 3D导演台 · 模型渲染与桥接（2026-08-20 冻结；2026-09-13 两次解冻后重锁） | 7 |
| `canvas-magnetic-intent` | 画布磁吸意图系统 · 导演卡 + L1 参数（2026-09-12 冻结；2026-09-13 解冻后重锁） | 30 |

共 **9** 个 zone、**82** 个锁点（与 `frozen_zones.json` / `frozen_zones.hashes.json` 一致；JSON 中 id 为 `plugin-host-ui` 而非旧名 `drama-finder-ui`）。

> 磁吸系统的设计语义（边缘隙判据 / Bond / 阻力三段式 / React Flow v12 机制）见 [`17-canvas-magnetic-invariants.md`](17-canvas-magnetic-invariants.md)。
> `frozen_zones.json` 各 zone 的 `invariants` 字段是「改动时必须满足的语义条件」；哈希只保证「没被偷偷改」，两者需一起看。

### 宿主漂移备注（2026-08-19）

- 冻结符号只覆盖 `plugins_module.py` 的 `_plugin_offers_widget_ui` / `_ensure_plugin_initialized` / `_open_plugin_ui`。
- 运行时主入口仍是 **`extensions_module._open_drama_finder`**；`drama_ui.py` 现为占位页，不在冻结符号表。
- 商店目录冻结仍约束「只上架 `app/plugins` 真实项」；卸空后目录仍在，勿删 `drama-finder` / `account-ops` 条目。

## 最近解冻记录

### 2026-09-13 · `stage3d-core`（用户授权）

- 改动：`app/modules/lego/character_management_module.py` 仅改**画布预热时机**——
  无条件 `QTimer.singleShot(200, self._bootstrap)` → `_bootstrap_if_visible()` + `showEvent()` + `_booted` 幂等。
- 未动：`canvas_bridge` 端口 18765、`canvas_runtime` 端口 3011/3010、GLB 路径与材质、`_ensure_bridge` / `_load_canvas`。
- 已把「预热只能在可见时触发」写入该 zone 的 `invariants`，防止日后回退。

### 2026-09-13 · `canvas-magnetic-intent`（用户授权）

- 改动：磁吸等级判据 **中心距 → 边缘间隙 edge-gap**（原判据下并排贴合永不触发）；
  新增 `magnetic/bonds.ts`（Bond 咬合，几何推导不落盘）与 `magnetic/SnapSeam.tsx`（咬合缝 + 三态 + 白光闪烁）；
  `useMagneticDrag` 落地阻力三段式（≤30px 不动 / 30~50px 只让出 28% / ≥50px 断裂）。
- 保留：全部阈值数值（80/50/25、过冲 5、回弹 200ms、拉伸 30、断裂 50）、六向语义、
  导演卡拆解、L1 四档画质与默认参数、`isReference` 隐藏规则、`.react-flow.zoomed-out`。
- 新登记：`magnetic/bonds.ts`、`magnetic/SnapSeam.tsx`，以及此前未入册的 `novice/*`（6 个文件）。
- 未纳入：`AppNav.tsx` / `StudioPages.tsx` / `WorkspaceCanvasMenus.tsx`（档位切换 UI，非磁吸语义核心）。

### 2026-09-13 · `stage3d-core` + `canvas-magnetic-intent`（用户授权 · 角色库人格字段）

- 改动：`character_management_module.py` 的 `CHARACTER_FIELD_SCHEMA` 由 10 字段扩到 **20 字段**
  （新增 10 个人格字段），并从「硬编码 5 个控件」改为**按分组动态渲染 UI**；
  `canvas_bridge.build_character_prompt` 消费新增的 `temperament` / `memory_anchors`；
  `node-factory.ts` 的 `CharacterEntry` 同步补字段（两个前端包各自一份）。
- 未动：端口 18765 / 3011 / 3010、GLB 路径与材质、`_ensure_bridge` / `_load_canvas` / 预热时机；
  磁吸阈值与六向语义、`qualityTier` 四档、卡片生成默认参数。
- **有意的行为变更**：`build_character_prompt` 中 `personality` 的前缀由「气质:」改为「性格:」——
  新增的 `temperament` 已占用「气质」语义，两词并存会互相稀释。老角色不含新字段，
  除此前缀外提示词输出不变（已由 `_verify/check_character_prompt.py` 断言向后兼容）。
- 新增回归脚本：`_verify/check_character_schema.py`（**六处**同步静态校验，V4.14.5 由五处扩到六处）、
  `_verify/check_character_prompt.py`（字段流向 + 向后兼容）。
- 未纳入 zone：`app/core/canvas_server.py`（不在任何 zone 内，其 `/host/characters` 已改为按 schema 派生）。

## 解冻记录 2026-09-13 #2 · `canvas-magnetic-intent`（V4.14.5）

**原因**：P0-2 —— 画布绑定角色时只把 `appearance` 拼进提示词，
`build_character_prompt` 用到的另外 3 个 visual 字段（`temperament` / `memory_anchors` /
`personality`）**一个字都进不去**，静默失效。

**改动文件**（仅 2 个，均在 zone 内）：
`vendor/shiguang-canvas/src/store.ts`、`vendor/shiguang-canvas/src/stores/node-factory.ts`。
（Tauri 副库同段代码不在 zone 内，同步改了。）

**不变量核对**：该 zone 的 17 条不变量全部关于磁吸（阈值 80/50/25、edge-gap 判据、
Bond 几何、阻力三段式、SnapSeam 三态、`snapToGrid=false` 等）。
改动严格局限在角色绑定区块（`bindCharacterToShot` / `unbindCharacterFromShot` /
`syncCharacterToShot` + 3 个新增模块级函数），**未触碰任何磁吸代码** —— 已用逐行 diff 核对。

**锁回来的结果**：`--update` 后 `OK frozen zones intact (82 locks)`。

## 解冻记录 2026-09-13 #3 · `canvas-magnetic-intent`（V4.14.6）

**原因**：P1-3 —— 分镜表要加「观众记忆类型」列，`ShotlistRow` /
`createShotlistRow` 定义在 `stores/node-factory.ts`（zone 内）。

**改动文件**（仅 1 个，zone 内）：`vendor/shiguang-canvas/src/stores/node-factory.ts`。
（`storyNodes.tsx`、`bridge.ts` 不在 zone 内；Tauri 副库同段代码同步改了。）

**不变量核对**：只新增了 `MemoryType` 类型、 `ShotlistRow.memoryType?` 可选字段、
以及 `createShotlistRow` 的默认值 `memoryType: "meaning"`。
`node-factory.ts` 里没有任何磁吸逻辑（阈值/Bond/阻力等都在
`MagneticEngine.ts`、`bonds.ts`、`useMagneticDrag.ts`），**不变量不受影响**。
已用 `git diff` 核对改动范围。

**附**：本次顺手修了 `ShotlistRow` 的 doc 注释被新类型块顶掉的问题。

**锁回来的结果**：`--update` 后 `OK frozen zones intact (82 locks)`。

## 解冻流程（仅当用户明确要求）

1. 用户说：「解冻 <zone-id>」等
2. 先核对改动是否违反该 zone 的 `invariants`（**不要盲目重写基线**）
3. 若新增了配套文件，一并补进 `frozen_zones.json` 的 `files`，否则日后不被守门
4. 修改对应代码
5. `python scripts/frozen_zone_guard.py --update`
6. `python scripts/frozen_zone_guard.py` 必须输出 `OK frozen zones intact`

## Agent / 人

- Cursor 规则：[`.cursor/rules/frozen-zones.mdc`](../../.cursor/rules/frozen-zones.mdc)
- 编码规则摘要见 [`07-coding-rules.md`](07-coding-rules.md)
