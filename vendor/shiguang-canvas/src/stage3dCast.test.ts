/**
 * 缺口①「角色库 → 3D 导演台」单测。
 *
 * 覆盖三类东西：
 *   A. 纯映射函数（体型/发型/配色）—— 重点是**确定性**：同一个角色每次必须得到同一个结果。
 *      这是用户反复强调的红线「拒绝随机效果」在代码层的落点。
 *   B. `applyPendingCast` 的副作用编排 —— 本仓库 vitest 是 `environment: "node"`
 *      （无 DOM / 无 RTL / 无 react-test-renderer），写在 `useEffect` 里的代码一行都测不到，
 *      所以编排被刻意从 hook 抽出成纯函数，由这里直接喂假 deps。
 *   C. **源级接线守卫** —— 有两类缺陷编译器抓不到、运行期也不报错：
 *      ① `useStage3dCast()` 被放到 `const pushUndo` **之前** ⇒ TDZ ReferenceError（一渲染就崩）；
 *      ② Python 的 `HUMAN_VARIANT_OPTIONS` 与画布 `HUMAN_PRESETS` 的 key 不再逐字相同
 *         ⇒ 导演台 `HUMAN_PRESETS[variant]` 取到 undefined，**静默退回兜底推断**
 *         （角色库明明选了「儿童」，导演台却给个成年男体，且不报任何错）。
 *      这两条都落成断言。参考既有先例：`_verify/check_char_prompt_block.mjs` 也是源级硬值校验。
 *
 * 源文件用 Vite 的 `?raw` 导入（而不是 `node:fs`）：本包没装 `@types/node`，
 * 用 node 内建模块会直接给 tsc 添 3 处新错误、破坏「零新增」的棘轮基线。
 * `?raw` 的类型由 `src/vite-env.d.ts`（vite/client）提供，零配置零依赖。
 */
import { describe, expect, it } from "vitest";
import riggedHumanoidSource from "./riggedHumanoid.ts?raw";
import stage3dSource from "./Stage3D.tsx?raw";
import shellSource from "./CanvasShell.tsx?raw";
import type { StageActor } from "./Stage3D";
import { HUMAN_PRESETS } from "./riggedHumanoid";
import {
  CAST_COLORS,
  VARIANT_SCALE,
  applyPendingCast,
  castActorFromCharacter,
  colorForCharacter,
  hairStyleFromCharacter,
  isHumanVariant,
  variantFromCharacter,
  type Stage3dCastDeps,
} from "./stage3dCast";

// ---------------------------------------------------------------- A. 纯映射

describe("isHumanVariant", () => {
  it("接受 HUMAN_PRESETS 的全部 key", () => {
    for (const key of Object.keys(HUMAN_PRESETS)) {
      expect(isHumanVariant(key)).toBe(true);
    }
    expect(Object.keys(HUMAN_PRESETS).length).toBe(5);
  });

  it("拒绝空串 / 未知值 / 非字符串", () => {
    expect(isHumanVariant("")).toBe(false);
    expect(isHumanVariant("male")).toBe(false); // 少后缀，形近但不合法
    expect(isHumanVariant("MALE_STD")).toBe(false); // 大小写必须精确
    expect(isHumanVariant(undefined)).toBe(false);
    expect(isHumanVariant(null)).toBe(false);
    expect(isHumanVariant(5)).toBe(false);
  });
});

describe("variantFromCharacter", () => {
  it("显式 human_variant 优先于性别/年龄段推断", () => {
    // 女性 + 儿童年龄段，但显式写了 male_heavy ⇒ 以显式字段为准
    expect(
      variantFromCharacter({ gender: "女", age_range: "儿童", human_variant: "male_heavy" }),
    ).toBe("male_heavy");
  });

  it("年龄段含 儿童/幼/少/小/孩 ⇒ child", () => {
    expect(variantFromCharacter({ age_range: "儿童" })).toBe("child");
    expect(variantFromCharacter({ age_range: "少年" })).toBe("child");
    expect(variantFromCharacter({ age_range: "幼年" })).toBe("child");
    expect(variantFromCharacter({ age_range: "小孩" })).toBe("child");
    // 老年人**不是**儿童
    expect(variantFromCharacter({ age_range: "老年" })).toBe("male_std");
  });

  it("女性 ⇒ female_std，其余 ⇒ male_std", () => {
    expect(variantFromCharacter({ gender: "女" })).toBe("female_std");
    expect(variantFromCharacter({ gender: "男" })).toBe("male_std");
  });

  it("空对象 / undefined 不抛错，落到 male_std", () => {
    expect(variantFromCharacter({})).toBe("male_std");
    expect(variantFromCharacter(undefined as never)).toBe("male_std");
  });

  it("脏 human_variant 退回推断（而不是把 undefined 漏出去）", () => {
    expect(variantFromCharacter({ gender: "女", human_variant: "bogus" })).toBe("female_std");
  });

  it("确定性：连算 200 次结果恒定", () => {
    const c = { id: "c1", name: "张三", gender: "男", age_range: "青年" };
    const first = variantFromCharacter(c);
    for (let i = 0; i < 200; i++) expect(variantFromCharacter(c)).toBe(first);
  });
});

describe("hairStyleFromCharacter", () => {
  it("儿童圆头 / 女体长发 / 其余短发", () => {
    expect(hairStyleFromCharacter({ age_range: "儿童" })).toBe("round");
    expect(hairStyleFromCharacter({ gender: "女" })).toBe("long");
    expect(hairStyleFromCharacter({ gender: "男" })).toBe("short");
  });

  it("发型跟体型走：显式 child + 性别女 ⇒ 圆头（体型优先）", () => {
    expect(hairStyleFromCharacter({ gender: "女", human_variant: "child" })).toBe("round");
  });
});

describe("colorForCharacter", () => {
  it("同一 id ⇒ 同一色；确定性", () => {
    const c = { id: "char_abc" };
    const first = colorForCharacter(c);
    for (let i = 0; i < 100; i++) expect(colorForCharacter(c)).toBe(first);
  });

  it("id 优先于 name（改名不该变色）", () => {
    expect(colorForCharacter({ id: "x1", name: "旧名" })).toBe(
      colorForCharacter({ id: "x1", name: "新名" }),
    );
  });

  it("无 id 时退到 name，两者都没有时退到 anon（仍合法）", () => {
    expect(colorForCharacter({ name: "李四" })).toBe(colorForCharacter({ name: "李四" }));
    const anon = colorForCharacter({});
    expect(anon).toBe(colorForCharacter({ name: "" }));
    expect(CAST_COLORS as readonly string[]).toContain(anon);
  });

  it("配色恒在池内，且不同角色并非全同色", () => {
    const ids = Array.from({ length: 40 }, (_, i) => `char_${i}`);
    const colors = ids.map((id) => colorForCharacter({ id }));
    for (const c of colors) expect(CAST_COLORS as readonly string[]).toContain(c);
    expect(new Set(colors).size).toBeGreaterThan(1);
  });
});

describe("castActorFromCharacter", () => {
  it("产出合法 actor：kind / variant / hairStyle / scale 对齐 HUMAN_PRESETS", () => {
    const a = castActorFromCharacter({ id: "c1", name: "小明", age_range: "儿童" });
    expect(a.kind).toBe("actor");
    expect(a.name).toBe("小明");
    expect(a.variant).toBe("child");
    expect(a.hairStyle).toBe("round");
    // 体型缩放必须跟着体型走 —— 否则「儿童」会是个巨人。
    // 注意用的是 VARIANT_SCALE 而不是 HUMAN_PRESETS.child.heightScale（后者被 Stage3D 覆盖，见下）。
    expect(a.scale).toBe(VARIANT_SCALE.child);
    expect(a.scale).toBeLessThan(VARIANT_SCALE.male_std);
    expect(a.pose).toBeTruthy();
    expect(a.rotationY).toBe(0);
  });

  it("匿名人偶有兜底名字，不产生空名", () => {
    expect(castActorFromCharacter({}).name).toBe("角色");
    expect(castActorFromCharacter({ name: "" }).name).toBe("角色");
  });

  it("index 只影响初始摆位，不影响身份（体型/配色保持一致）", () => {
    const c = { id: "c9", name: "甲", gender: "女" };
    const a0 = castActorFromCharacter(c, { index: 0 });
    const a3 = castActorFromCharacter(c, { index: 3 });
    expect(a0.position).toEqual([-1, 0, 0]);
    // 3*0.9-1 = 1.7000000000000002（浮点），不能按字面 1.7 比
    expect(a3.position[0]).toBeCloseTo(1.7, 10);
    expect(a3.position[1]).toBe(0);
    expect(a3.position[2]).toBe(0);
    expect(a3.color).toBe(a0.color);
    expect(a3.variant).toBe(a0.variant);
  });

  it("每次产出 id 唯一（同角色连投两次不会撞 id）", () => {
    const ids = new Set(
      Array.from({ length: 50 }, () => castActorFromCharacter({ id: "c1", name: "甲" }).id),
    );
    expect(ids.size).toBe(50);
  });
});

// ------------------------------------------------- B. 副作用编排（hook 内核）

function makeDeps(initial: StageActor[] = []) {
  const calls = { pushUndo: 0, setActors: 0, selected: [] as string[], modes: [] as string[], status: [] as string[] };
  const deps: Stage3dCastDeps = {
    actors: initial,
    setActors: (updater) => {
      calls.setActors++;
      deps.actors = updater(deps.actors);
    },
    setSelectedId: (id) => {
      calls.selected.push(id);
    },
    setSceneMode: (m) => {
      calls.modes.push(m);
    },
    onStatus: (m) => {
      calls.status.push(m);
    },
    pushUndo: () => {
      calls.pushUndo++;
    },
  };
  return { deps, calls };
}

describe("applyPendingCast", () => {
  it("空请求 = 什么都不做（不 pushUndo、不改选中、不改状态栏）", () => {
    const { deps, calls } = makeDeps();
    expect(applyPendingCast(deps, null)).toBe(false);
    expect(applyPendingCast(deps, undefined)).toBe(false);
    expect(calls).toMatchObject({ pushUndo: 0, setActors: 0, status: [] });
  });

  it("投递一次 = 追加一人 + 选中他 + 切群像 + 记一次 undo + 报状态", () => {
    const { deps, calls } = makeDeps();
    expect(applyPendingCast(deps, { id: "c1", name: "小明", age_range: "儿童" })).toBe(true);
    expect(calls.pushUndo).toBe(1);
    expect(deps.actors.length).toBe(1);
    expect(deps.actors[0].name).toBe("小明");
    expect(calls.selected).toEqual([deps.actors[0].id]);
    expect(calls.modes).toEqual(["group"]);
    expect(calls.status.length).toBe(1);
    expect(calls.status[0]).toContain("小明");
    expect(calls.status[0]).toContain(HUMAN_PRESETS.child.label);
  });

  it("连投两次 = 两人，第二次的初始摆位按现有数量递增（不与第一人重叠）", () => {
    const { deps, calls } = makeDeps();
    applyPendingCast(deps, { id: "c1", name: "甲" });
    applyPendingCast(deps, { id: "c2", name: "乙" });
    expect(deps.actors.length).toBe(2);
    expect(deps.actors[0].position[0]).not.toBe(deps.actors[1].position[0]);
    expect(calls.pushUndo).toBe(2);
  });

  it("已有场景不会被清空（是追加不是替换）", () => {
    const existing = castActorFromCharacter({ id: "old", name: "原有" });
    const { deps } = makeDeps([existing]);
    applyPendingCast(deps, { id: "c1", name: "新人" });
    expect(deps.actors.map((a) => a.name)).toEqual(["原有", "新人"]);
  });
});

// ------------------------------------------------------- C. 源级接线守卫

describe("接线守卫（源级）", () => {
  const stage3d = stage3dSource;
  const shell = shellSource;

  it("Stage3D 真的 import 并调用了消费端与面板", () => {
    expect(stage3d).toContain('from "./stage3dCast"');
    expect(stage3d).toContain("useStage3dCast(");
    expect(stage3d).toContain("<Stage3dCastPanel");
  });

  it("useStage3dCast 必须在 const pushUndo 之后调用（否则 TDZ，一渲染就 ReferenceError）", () => {
    const call = stage3d.indexOf("useStage3dCast(");
    const def = stage3d.indexOf("const pushUndo = ");
    expect(def).toBeGreaterThan(-1);
    expect(call).toBeGreaterThan(def);
  });

  it("CanvasShell 角色下拉旁有投递入口", () => {
    expect(shell).toContain("requestStage3dCast(c)");
    expect(shell).toContain("s.requestStage3dCast");
  });

  it("VARIANT_SCALE 必须与 ACTOR_PRESETS 的朴素预设一致（否则同一体型两种身高）", () => {
    // 抓 ACTOR_PRESETS 的单行条目：{ id, label, scale, color, variant, ... }
    const entries = [
      ...stage3d.matchAll(
        /\{\s*id:\s*"([^"]+)",\s*label:\s*"([^"]+)",\s*scale:\s*([\d.]+),\s*color:\s*"[^"]+",\s*variant:\s*"(\w+)"/g,
      ),
    ].map((m) => ({ scale: Number(m[3]), variant: m[4] }));
    if (entries.length < 5) {
      throw new Error("ACTOR_PRESETS 解析失败（源码格式可能被重排，请同步本测试的正则）");
    }
    // 每个体型取**首次出现**的取值 = 该体型的朴素预设按钮
    const plain: Record<string, number> = {};
    for (const e of entries) if (!(e.variant in plain)) plain[e.variant] = e.scale;
    for (const v of Object.keys(HUMAN_PRESETS)) {
      expect(plain[v], `ACTOR_PRESETS 里没有体型 ${v} 的预设`).toBeDefined();
      expect((VARIANT_SCALE as Record<string, number>)[v], `体型 ${v} 的缩放与预设按钮不一致`).toBe(
        plain[v],
      );
    }
  });

  it("已知耦合：Stage3D 用 actor.scale 覆盖了 makeRiggedHumanoid 内部的 heightScale", () => {
    // VARIANT_SCALE 的注释断言「heightScale 被覆盖」⇒ 若哪天取消了这个覆盖，
    // heightScale 会重新生效、本表取值必须重新核对。这条断言就是那个提醒。
    expect(stage3d).toContain("obj.scale.setScalar(safeScale)");
    expect(riggedHumanoidSource).toContain("root.scale.setScalar(P.heightScale)");
  });

  // 注：涉及 Python 侧（character_management_module.py）的断言**刻意不在这里**。
  // 原因：副库的对应目录是 src/libtv/，本文件被同步过去后 `../../../app/...` 会解析到
  // vendor/app/ 而失效 ⇒ 跨仓不成立。那些断言已移到它们天然的家：
  // _verify/check_character_schema.py（SCHEMA 门禁，逐仓库根执行、无相对路径问题）。
});
