/**
 * storeIdempotent.ts — 画布 store 的「幂等写入」纯函数层（2026-10-14，React #185 根因修复）。
 *
 * 崩溃背景（生产模式 Qt WebEngine 频繁崩，ErrorBoundary 截到 Minified React error #185）
 * ============================
 *   #185 = Maximum update depth exceeded，成因是「effect 写 store → 重渲染 → 又写 store」成环：
 *
 *   CanvasShell.tsx  bondedSides = useMemo(() => bondedSidesMap(nodes), [nodes])
 *                    ↑ bondedSidesMap 每次都 const map = {} 新建对象 ⇒ 引用必变
 *   useEffect(() => setBondedSides(bondedSides), [bondedSides])   ← 必跑
 *     → store.setBondedSides 无任何守卫，set({bondedSides: map}) 无条件通知全 store
 *       → 订阅 bondedSides 的 NoviceCard 全部重渲染
 *         → xyflow 抛 dimensions change
 *           → onNodesChange 无条件 applyNodeChanges ⇒ 全新 nodes 数组
 *             → nodes 变 ⇒ 回到第一步 ⇒ 闭环。
 *
 * 修法（不改变任何可见行为，只把「空转写入」掐掉）
 * =================================================
 *   两个写入点各自加**内容级幂等守卫**：内容与当前值逐键相同 ⇒ 整个 set 都不执行，
 *   引用不变 ⇒ 订阅者不重渲染 ⇒ 闭环断开。
 *
 * 为什么单独成文件
 * =================
 *   ① store.ts 属**冻结区**（check_file_size 基线 2514 行、只减不增）——守卫逻辑落在这里
 *      会推高体积棘轮；独立成文件后 store.ts 只多 1 行 import + 几行调用。
 *   ② 本项目 vitest 是 **node 环境无 jsdom、useEffect 逻辑零覆盖**（既有纪律），
 *      判定逻辑抽成纯函数才能真正被测到——这正是本文件存在的理由。
 *
 * 语义红线：判定必须与被它替代的原表达式**逐字等价**，不允许引入行为差异。
 */
import type { SpatialDirection } from "./magnetic/types";

/** 咬合侧隐形表：nodeId → 需透明的贴合边方向（与 store.bondedSides 同形）。 */
export type BondedSidesMap = Record<string, SpatialDirection[]>;

/**
 * 咬合侧表内容相等（≠ 引用相等）。
 *
 * `bondedSidesMap` 每轮都新建对象，但内容通常完全一致 ⇒ 用内容判等替代引用判等，
 * 让 setBondedSides 能识别「空转」并跳过 set。
 *
 * 口径：key 数量相同 且 每个 key 的方向数组 join(",") 相同 ⇒ 相等。
 *   · 数组**顺序敏感**（addBondedSide 的 push 顺序由 bonds 遍历顺序决定，同输入必同序；
 *     真出现顺序差异时判为「不等」是保守方向——多写一次，绝不漏写）。
 *   · key 顺序无关（按 key 比，不按枚举序比）。
 */
export function bondedSidesEqual(
  a: BondedSidesMap | null | undefined,
  b: BondedSidesMap | null | undefined,
): boolean {
  const av = a ?? {};
  const bv = b ?? {};
  const ak = Object.keys(av);
  const bk = Object.keys(bv);
  if (ak.length !== bk.length) return false;
  for (const k of ak) {
    // key 数已相等，理论上 k 必在 bv 里；仍做 own-key 检查以拿到确定的类型收窄
    if (!Object.prototype.hasOwnProperty.call(bv, k)) return false;
    if (av[k].join(",") !== bv[k].join(",")) return false;
  }
  return true;
}

/**
 * patch 相对当前 data 是否为「空转」（展开后逐键值不变 ⇒ 可跳过 set）。
 *
 * 它替代的原表达式是 `{ ...n.data, ...patch }`，判定必须与之等价，两处细节：
 *
 *   1. **NaN**：按 `Object.is` 判而非 `===`。展开会真的写入 NaN，`===` 会把
 *      NaN→NaN 误判成「有变化」（只是白写一次，不算错），`Object.is` 才与展开语义同源。
 *   2. **undefined 值 ≠ 键缺失**：`{ ...data, k: undefined }` 会**显式新增** k 这个
 *      自有键，结果与「原本没有 k」不是同一个对象。所以 k 缺失时必须判为「有变化」。
 *      这里用 `hasOwnProperty` 而非 `k in data`：展开只复制**自有可枚举**键，
 *      原型链上的键不算已存在——用 `in` 会把「实际会新增键」误判成空转（那是漏写）。
 *      整体取保守侧：误判「有变化」只是多写一次（无害），误判「空转」会丢更新（是 bug）。
 */
export function nodeDataPatchIsNoop(
  data: Record<string, unknown> | null | undefined,
  patch: Record<string, unknown>,
): boolean {
  if (!patch) return true;
  const cur = data ?? {};
  for (const k of Object.keys(patch)) {
    const next = patch[k];
    if (!Object.is(cur[k], next)) return false;
    if (next === undefined && !Object.prototype.hasOwnProperty.call(cur, k)) return false;
  }
  return true;
}
