# 17 · 画布磁吸意图系统 · 设计不变量

> 适用范围：`vendor/shiguang-canvas/src/magnetic/` + `CanvasShell.tsx` + `styles.css`
> 冻结区：zone `canvas-magnetic-intent`（见 `frozen_zones.json`）
> 定稿：**2026-09-12**（V4.13.0「磁吸咬合」）

---

## 一、判据：边缘间隙，不是中心距 ⚠️

**这是本系统最容易被改错、也最容易「看起来像提示不够明显」的根因。**

| | 错误做法（V4.13.0 之前） | 正确做法 |
|---|---|---|
| 度量 | 两卡**中心**距 center-to-center | 两卡**外边缘**间隙 edge-gap |
| 并排紧贴（240×200 卡） | 中心距 = **240px** | gap = **0px** |
| 对上 strong 阈值 25px | ❌ 永远够不到 | ✅ 稳落 strong |

⇒ **并排贴合这个最常用动作，在旧判据下从设计上就不可能触发磁吸**，
只有「拖到卡片上重叠」才勉强有反应。用户感知到的「吸附没提示」，真相是**吸附压根没成立**。

实现：`MagneticEngine.computeMagnetic` 走 `rectOf(node)` + `edgeGap(a,b)`，
返回 `{ gap, gapX, gapY, overlapX, overlapY }`（`gap` 为外缘分离量，重叠时为 0）。

**通用教训**：凡是「距离阈值」配置，先确认它量的是中心距还是边缘距，
再核对**阈值量纲 vs 元素尺寸**是否自洽。

## 二、等级与方向

| 等级 | 判据 | 吸引力系数 |
|---|---|---|
| weak | `gap < 80` | 0.12 |
| medium | `gap < 50` | 0.24 |
| strong | `gap < 25` | 0.45 |

- 强度系数因判据换成**边缘距**（数值量级变大）而下调过：原 `0.15 / 0.35 / 0.70`。
- `getDirection(dx, dy, gap)` **只在 `gap ≤ 1`（真重叠）时才判 `stack`**，否则按四向方位——
  避免贴边被误判成层叠。
- 六向语义：左输入参考 / 右输出接续 / 上并行对照 / 下分支备选 / 前导演卡 / 后历史版本
  （前、后物理上都是重叠，统一由 `stack` 承载）。

## 三、Bond（咬合）= 几何推导的持久关系

- **定义**：`边距 ≤ bondTolerance(2px)` **且** `投影重叠 ≥ 40px`（`MIN_OVERLAP`）。
- **不落盘**。由几何推导 ⇒ **刷新页面后咬合关系自动恢复**，无持久化字段。
  这是「持久可见的吸附提示」能做到零状态管理的根本原因。
- `makeBond` 识别 **左 / 右 / 上 / 下** 四向贴合缝，**不含 stack 层叠**。
- `seam` 语义：`w=0` 表示竖缝（左右贴合），`h=0` 表示横缝（上下贴合），渲染层以此为中心线两侧铺开。
- `computeBonds(nodes)` 走 `SpatialIndex` **邻域查询**，不做全量两两比对。

## 四、拖拽手感：三段式（V4.13.0 起真正启用）

`stretchThreshold(30)` / `breakThreshold(50)` 两个配置**定义了很久却从未被任何代码读取**——
规格书写了「拉伸 30、断裂 50」，实现层是空头支票。V4.13.0 起在 `useMagneticDrag` 中落地：

| 阶段 | 拉力 | 表现 |
|---|---|---|
| 咬死 | ≤ 30px | 卡片**完全不动**，位移被压制 |
| 绷住 | 30 ~ 50px | 只跟动超出量的 **28%**（`bondGiveRatio`），越拉越沉 |
| 断裂 | ≥ 50px | 断开 + 邻居进 `mutedRef`（本次拖拽不再吸它）+ 断裂闪光 |

- 松手时**仍在咬合** → 150ms **平滑回位，不过冲**。
- 松手时**强吸附** → `animateNodeTo` 带 5px 过冲**落座**；落座后若形成咬合，再补一次吸附闪光。
- 磁吸偏移**累加在当前显示位置**上（非原始指针位置）⇒ 捕捉感从「瞬移」变为「被吸过去」。
- 位置写入统一走 `writeNodePos`（跳过无变化写入）+ `animateNodeTo`（rAF 弹簧动画，`animFrameRef` 保证可取消）。
- **小白模式 `snapToGrid = false`**：16px 量化会把拉扯变成阶梯跳，直接吃掉阻力感。

## 五、⚠️ React Flow v12 关键机制（做阻力必须知道）

`@xyflow/system` 的 `XYDrag` 执行顺序是：

```
先写位置进 store  →  再调 onNodeDrag / onNodeDragStop
```

⇒ **在回调里覆盖位置必然生效**。这正是「粘住不动」「只让出 28%」「松手回位」能实现的原理。
**若按相反假设（以为回调先于写库）写代码，实现会完全失效。**

## 六、视觉提示（「成功」必须看得见）

- `SnapSeam.tsx`：每条咬合**常驻**渲染 `色带 + 白色芯线 + 文字胶囊`。
  - 文字随阶段切：`已吸附` → `拉伸中` → `即将断开`
  - 颜色随应变：语义色 → 琥珀 `#fbbf24` → 红 `#f87171`
  - 应变越大缝越**细**（视觉上被「拉薄」）
  - zIndex 13，位于 `MagneticLines` 之前
- **吸附 / 断裂各触发一次性白光扩散闪烁**（`sg-seam-flash` + 扩散环），播完即散。
- `SnapSlotHighlight`：强槽厚 **9px**（原 5）+ 白芯线 + 「松手即吸附」胶囊；
  透明度 weak 0.55 / medium 0.85 / strong 1.0；strong/hint 走 CSS 动画 `sg-slot-strong`、`sg-slot-hint`。
- 相关 keyframes：`sg-seam-band-active`、`sg-seam-pill-pulse`、`sg-seam-flash`、`sg-seam-flash-ring`。

## 七、`BOND_COLORS` 语义色

| 键 | 值 | 用途 |
|---|---|---|
| `stretching` | `#fbbf24` | 拉伸中 |
| `strained` | `#f87171` | 即将断开 |
| `snapFlash` | `#4ade80` | 吸附成功闪光 |
| `breakFlash` | `#f87171` | 断裂闪光 |
| `highlight` | `#ffffff` | 白色芯线 |

## 八、改动须知

- 本页内容与 `frozen_zones.json` 的 zone `canvas-magnetic-intent` 一一对应，**未解冻勿改**。
- ✅ `magnetic/bonds.ts`、`magnetic/SnapSeam.tsx` 已于 2026-09-13 解冻时**补登记**进该 zone 的 `files`（早期版本的「尚未登记」提示已失效）。
- ⚠️ 全文出现「240×200」处一律理解为 **DOM 实尺寸固定值**（不是「最小尺寸」）——见下节。

---

## 九、2026-09-23 修订：卡片尺寸统一 + 顶边对齐（V4.38.6 / 画布 0.3.1）

用户反馈两条缺陷，均为既有实现问题，同轮修复：

### 9.1 卡片大小不统一（修复：minHeight → 固定 height）

| 项 | 修复前 | 修复后 |
|---|---|---|
| `CARD_GEOMETRY`（`novice/types.ts`） | `minHeight: 200` | **`height: 200`**（固定） |
| `NoviceCard.tsx` 内联 | `minHeight: CARD_GEOMETRY.minHeight` | `height: CARD_GEOMETRY.height`（并移除 body 内联 `minHeight`） |
| `.nv-card-body` | `flex:1`（可被内容撑高） | `+ min-height:0; overflow:hidden` |
| `.nv-card-hint` / `.nv-card-meta` | flex 默认（**可收缩**，被压扁裁字） | `flex: 0 0 auto`（meta 另加单行省略号） |
| `.nv-card-thumb img/video` | `height: 96px` | `height:100%; max-height:72px` + 容器 `flex:1 1 auto; min-height:24px`（弹性收缩） |
| `.nv-card-text` | `-webkit-line-clamp: 3` | `2`（无图）／`1`（有图，`:has` 规则） |
| 有缩略图时 | 四层内容全显示 | **提示语折叠** + 正文 1 行（见下） |

**实测根因**：正文区内容叠加（hint ≈31 + 缩略图 96 + 正文 3 行 ≈72 + meta ≈17 + padding/gap）≈ **306px**，
而空卡只有 200px ⇒ 同屏卡片高矮差超过 100px。这同时**违反了冻结不变量「DOM 实尺寸必须 240×200（磁吸落位基准）」**
——所以本次修复是**恢复**不变量，而非放宽它。

**渲染实测（Edge 无头截图 + `getBoundingClientRect`）进一步证明**：卡片固定 200 后，
正文区可用高度只有 **106px**（200 − header 40 − footer 32 − border 2 − padding 20），
而「提示语 31 + 缩略图下限 40 + 正文 2 行 44 + 元信息 17 + 间隙 16」需 **148px**
⇒ 四层内容在 200px 内**数学上装不下**（实测裁切 45px）。
故有图时按信息价值收敛：**提示语（新手引导文案）折叠 + 正文收 1 行**，
缩略图获得 ≈51px 可见高度。收敛后复测：4 种形态全部 240.0×200.0、正文区裁切 **0px**。
证据图：`docs/_reports/2026-09-23-画布卡片尺寸实测.png`。

### 9.2 最上端吸附没对齐（修复：top/bottom 改为顶边对齐）

- 修复前：`getSnapPosition` 的 `top`/`bottom` 分支 `x: keepX`（= 拖拽卡当前 x，2026-09-18 单轴吸附裁定）。
- 表现：上下吸附后 y 贴住了，两卡**左右边缘各在各自位置**，不成列 —— 用户观感就是「上端那条缝没对齐」。
- 修复后：`top`/`bottom` 的 `x` 取 **`targetPos.x`**（顶边对齐成列）。水平位移受磁吸范围约束
  （edge-gap < `weakDistance` 120px），不产生「瞬移」观感。
- **`left`/`right` 的单轴语义保持不变**（`y` 仍取拖拽当前位置）——2026-09-18 修掉的那个真实 bug
  （横吸时 y 被拽走一整卡高）不在本次修订范围内。

### 9.3 本次未动的部分（仍在保护）

磁吸阈值 120/50/60/instant10、落位 `gap=-2`、阻力三段式（30/50/0.28）、跟手浮起、
松手落座动画、整列让位、Bond 判据（2px/40px）、圆角 16、大圆角色块与选中态、交互分级。

### 9.4 验证记录

vitest 8 文件 **76 例全绿**（含修订后的顶边对齐断言）；`tsc` 37 处错误
（= `Stage3D.tsx` 16 + `riggedHumanoid.ts` 21，文档基线；本次改动文件 0 命中）；
`vite build` 成功；画布版本 0.3.0 → **0.3.1** 并同步副库；双库无新增漂移；守卫 **85 locks intact**。
