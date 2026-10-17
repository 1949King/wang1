/**
 * 缺口① · 角色库 → 3D 导演台（2026-10-12，用户授权解冻 stage3d-core + canvas-magnetic-intent）
 * ==========================================================================================
 * 在此之前 **3D 导演台与角色库完全没有连线**（`grep characters` 在 `Stage3D.tsx` = 0 命中）：
 * 角色库里写好了姓名/性别/年龄段，到了导演台还得手点「添加角色」再从 9 个固定预设里挑体型，
 * 两边的角色身份对不上（名字、配色、体型）。
 *
 * 本模块把这条线接上，走的是**项目已有的正统通道**——照抄「AI 分镜机位 → Stage3D」那套
 * `stage3dApplySeq` / `pendingStage3dCameras` / `consumeStage3dCameraPlan`（`store.ts`）：
 *   角色库 UI → `requestStage3dCast(角色)` → `stage3dCastSeq+1` → Stage3D 侧的
 *   `useStage3dCast()` 消费一次 → 在场景里生成对应体型的人偶。
 * 为什么必须经 store 而不是直接互调：两者分属不同组件树（角色库在 Python/Qt 侧与画布节点里，
 * 导演台在 Stage3D 里），**唯一共同的、可测的会合点是 store**。
 *
 * 三条设计红线：
 *   1. **不许随机**（用户反复强调）：同一个角色每次投递必须得到**同一个体型、同一个配色**
 *      —— 体型来自 `human_variant` 字段（缺省按性别/年龄段**确定性**兜底），配色由 id 哈希决定。
 *   2. **体型的唯一真相源是 `human_variant`**（角色库字段，见 `CHARACTER_FIELD_SCHEMA`），
 *      本模块只做「字段 → 导演台 `HumanVariant`」的映射，不自己另造一套体型枚举。
 *   3. 人偶的几何/材质一律复用 `makeRiggedHumanoid` 那条既有链（`HUMAN_PRESETS[variant]`），
 *      **不在这里新建 Mesh** —— 否则会绕过 stage3d-core 的「GLB 材质不得覆盖」不变量。
 */
import { useEffect, useRef } from "react";
import { HUMAN_PRESETS, type HairStyle, type HumanVariant } from "./riggedHumanoid";
import { defaultPose } from "./stage3dPoseLibrary";
import { useCanvasStore } from "./store";
import type { StageActor } from "./Stage3D";

/** 角色库侧只需要这几个字段（结构化子集 ⇒ 单测不必构造完整 CharacterEntry） */
export type CastSource = {
  id?: string;
  name?: string;
  gender?: string;
  age_range?: string;
  human_variant?: string;
};

const HUMAN_VARIANT_SET = new Set<string>(Object.keys(HUMAN_PRESETS));

/** 「角色库的体型预设」是否合法（防脏数据把 `HUMAN_PRESETS[...]` 读成 undefined） */
export function isHumanVariant(v: unknown): v is HumanVariant {
  return typeof v === "string" && HUMAN_VARIANT_SET.has(v);
}

/**
 * 角色 → 导演台体型预设。
 *
 * 优先用显式字段 `human_variant`；老角色（建库时还没有这个字段）按
 * **性别 + 年龄段确定性兜底**——老人物、女体、儿童各有明确判据，
 * **绝不随机**（随机会让同一角色每次进导演台变一次身材）。
 */
export function variantFromCharacter(c: CastSource): HumanVariant {
  if (isHumanVariant(c?.human_variant)) return c.human_variant;
  const age = String(c?.age_range || "");
  if (/儿童|幼|少|小|孩/.test(age)) return "child";
  if (String(c?.gender || "") === "女") return "female_std";
  return "male_std";
}

/** 发型：女体马尾、其余短发；儿童用圆头（与 `ACTOR_PRESETS` 里的既有搭配一致） */
export function hairStyleFromCharacter(c: CastSource): HairStyle {
  if (variantFromCharacter(c) === "child") return "round";
  return String(c?.gender || "") === "女" ? "long" : "short";
}

/** 角色配色池（与导演台既有色调一致；同一角色恒定取同一色） */
export const CAST_COLORS = [
  "#f1f5f9", "#f472b6", "#1d4ed8", "#eab308",
  "#a855f7", "#22c55e", "#334155", "#ef4444",
] as const;

/**
 * 体型 → 导演台整体缩放（`StageActor.scale`）。
 *
 * ⚠️ 这里**不能**用 `HUMAN_PRESETS[variant].heightScale`（读码实测，2026-10-12）：
 *   · `riggedHumanoid.ts:1334` 在 `makeRiggedHumanoid()` 内部设了 `root.scale = heightScale`；
 *   · 但 `Stage3D.tsx:1489` 紧接着对**同一个对象**执行 `obj.scale.setScalar(a.scale)`
 *     ⇒ 内部那次赋值**被覆盖**，`heightScale`（儿童 0.74）对导演台里的人偶是**失效值**。
 *   · 若照 heightScale 写，从角色库投出来的「儿童」会是 0.74，而预设按钮给的是 0.58
 *     ⇒ 同一个体型两种身高（正是本项目反复出现的「同一概念两套取值」漂移）。
 * 故本表复刻 `Stage3D.tsx::ACTOR_PRESETS` 中每个体型的朴素预设取值，由单测锁死一致。
 */
export const VARIANT_SCALE: Record<HumanVariant, number> = {
  male_std: 1,
  female_std: 0.96,
  male_thin: 1,
  male_heavy: 1.05,
  child: 0.58,
};

/** 稳定哈希（同 id/名字 ⇒ 同色；不依赖 Math.random） */
function stableHash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

/** 角色 → 人偶配色（确定性） */
export function colorForCharacter(c: CastSource): string {
  const key = String(c?.id || "") || String(c?.name || "") || "anon";
  return CAST_COLORS[stableHash(key) % CAST_COLORS.length];
}

/** 与 Stage3D 模块级 `uid()` 同构（这里另写一份，避免值级循环 import） */
function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * 由角色库条目构造一个导演台人偶（纯函数，可直接单测）。
 * `index` 只用于初始摆位（与「添加角色」预设的排布公式一致），不影响身份。
 */
export function castActorFromCharacter(c: CastSource, opts: { index?: number } = {}): StageActor {
  const variant = variantFromCharacter(c);
  return {
    id: uid("actor"),
    name: String(c?.name || "角色"),
    kind: "actor",
    color: colorForCharacter(c),
    position: [(opts.index ?? 0) * 0.9 - 1, 0, 0],
    rotationY: 0,
    // 体型缩放必须跟着体型走（儿童 0.58 ↔ 男标准 1.0），否则「儿童」会是巨人。
    // 用 VARIANT_SCALE 而非 heightScale —— 原因见该常量的注释（heightScale 被覆盖）。
    scale: VARIANT_SCALE[variant],
    pose: defaultPose(),
    variant,
    hairStyle: hairStyleFromCharacter(c),
  };
}

export type Stage3dCastDeps = {
  actors: StageActor[];
  setActors: (updater: (prev: StageActor[]) => StageActor[]) => void;
  setSelectedId: (id: string) => void;
  setSceneMode: (mode: "solo" | "group") => void;
  onStatus: (message: string) => void;
  pushUndo: () => void;
};

/**
 * 把一条「待投递角色」真正落成导演台人偶 —— 纯副作用编排，可脱离 React 单测。
 *
 * 为什么从 hook 里抽出来：本仓库 vitest 是 `environment: "node"`（无 DOM / 无 RTL），
 * 写在 `useEffect` 里的逻辑**一行都测不到**。抽出后这段编排由单测直接喂假 deps 验证。
 * 返回是否真的加了人（空请求返回 false）。
 */
export function applyPendingCast(
  deps: Stage3dCastDeps,
  pending: CastSource | null | undefined,
): boolean {
  if (!pending) return false;
  deps.pushUndo();
  const actor = castActorFromCharacter(pending, { index: deps.actors.length });
  deps.setActors((prev) => [...prev, actor]);
  deps.setSelectedId(actor.id);
  deps.setSceneMode("group");
  deps.onStatus(
    `已从角色库添加「${actor.name}」· ${HUMAN_PRESETS[variantFromCharacter(pending)].label}`,
  );
  return true;
}

/**
 * 消费「角色投递」请求（每次投递只添加一次人偶）。
 *
 * 依赖数组只放 `seq`：把 deps 收进 ref，否则每次 render 都会因对象新引用重跑 effect
 * （这正是既有「靠近即落座」那次翻车的同一类问题：用错依赖 ⇒ 每帧重建）。
 */
export function useStage3dCast(deps: Stage3dCastDeps): void {
  const seq = useCanvasStore((s) => s.stage3dCastSeq);
  const depsRef = useRef(deps);
  depsRef.current = deps;

  useEffect(() => {
    if (!seq) return;
    const st = useCanvasStore.getState();
    const pending = st.pendingStage3dCast;
    st.consumeStage3dCast(); // 先消费再处理：即便后续抛错也不会重复投递
    applyPendingCast(depsRef.current, pending);
  }, [seq]);
}

/**
 * 导演台「角色」页里的角色库入口。自读 store（不接 props）⇒ Stage3D 侧只需一行 JSX，
 * 这对 `Stage3D.tsx` 的规模守卫余量很关键。
 */
export function Stage3dCastPanel({ visible }: { visible: boolean }) {
  const characters = useCanvasStore((s) => s.characters);
  const refreshCharacters = useCanvasStore((s) => s.refreshCharacters);
  const requestStage3dCast = useCanvasStore((s) => s.requestStage3dCast);
  if (!visible) return null;

  return (
    <>
      <div className="section-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
        从角色库添加
        <button
          type="button"
          className="btn"
          style={{ padding: "2px 6px" }}
          onClick={() => void refreshCharacters()}
          title="从角色库刷新"
        >
          ↻
        </button>
      </div>
      {characters.length === 0 ? (
        <p className="muted tiny">
          角色库为空 —— 先在「角色库」里建角色（可设体型预设），再回来点这里的按钮
        </p>
      ) : (
        characters.map((c) => {
          const v = variantFromCharacter(c);
          return (
            <button
              key={c.id}
              type="button"
              className="btn"
              style={{ display: "block", width: "100%", marginBottom: 4, textAlign: "left" }}
              onClick={() => requestStage3dCast(c)}
              title={`体型预设：${HUMAN_PRESETS[v].label}${c.human_variant ? "" : "（按性别/年龄段兜底推断）"}`}
            >
              🎭 {c.name || "(未命名)"} · {HUMAN_PRESETS[v].label}
            </button>
          );
        })
      )}
    </>
  );
}
