/**
 * 画布端口模型（类型槽位） + 连接校验 —— ComfyUI 视角的「类型化插座」
 *
 * ══════════════════════════════════════════════════════════════════
 * 一、为什么需要它（现状问题）
 * ══════════════════════════════════════════════════════════════════
 * 当前画布：每个节点恒 1 个 target 手柄（左）+ 1 个 source 手柄（右），
 * **没有任何类型**；`onConnect` 无条件 `addEdge`（store.ts:637-656）；
 * 全库**不存在 `isValidConnection`**（Grep 零命中）。
 * ⇒ 连错了没有任何反馈 —— 只是线换了个颜色（`EDGE_STYLE_BY_TYPE`）。
 *
 * ══════════════════════════════════════════════════════════════════
 * 二、「链」的三种含义（本模块的服务对象）
 * ══════════════════════════════════════════════════════════════════
 *  ① 关系链 relation  —— A 与 B 有关系（视觉/组织）。**当前边只有这一层。**
 *  ② 数据链 dataflow  —— A 的**输出**成为 B 的**输入**（有类型契约）。
 *  ③ 执行链 execution —— 按拓扑序跑（`canvas_workflow_runner.py`）。
 *
 * **定义：画布的「链」= 有向无环的数据依赖图（DAG）+ 每条边的类型契约。**
 * 执行链是它的一个视图；关系链是它的一个退化子集。
 *
 * ══════════════════════════════════════════════════════════════════
 * 三、一条边到底传什么？（关键设计决策）
 * ══════════════════════════════════════════════════════════════════
 * **两者都要，但必须分成两种边**：
 *
 *  · `data` 边（数据流）—— 参与执行；**必须通过端口类型校验**；**必须无环**。
 *    判据：source 的**产物**能成为 target 的**输入**。
 *  · `associate` 边（关联）—— 仅语义/组织（编组、便签）；**不参与执行**；
 *    **不做类型校验**；**允许成环**。
 *
 * 为什么不能只用一种：ComfyUI 的图**纯粹是数据流**，所以它只需要前者；
 * 但拾光剪影的画布**同时承担「组织/编排」职责**（编组、便签、把卡片摆在一起），
 * 这些不是数据流。若强行统一，要么「编组关系被当成非法连接」，
 * 要么「非法数据流被放行」—— 两者都错。
 *
 * ══════════════════════════════════════════════════════════════════
 * 四、为什么是「类型槽位」而不是 ComfyUI 的「命名端口」
 * ══════════════════════════════════════════════════════════════════
 * ComfyUI 需要命名端口，是因为它要区分**同类型的多个输入**
 * （positive / negative conditioning **都是** CONDITIONING 类型，
 *  不命名就分不清哪个是正/负）。
 *
 * 拾光剪影的节点按**类型**就能区分：
 *   shot  要「提示词 + 参考图」          → text + image
 *   video 要「首帧 + 参考视频 + 提示词 + 音频」 → image + video + text + audio
 * ⇒ **不需要命名**。类型槽位表达力足够，实现代价低得多
 *   （不用改节点 UI 布局，不用给每个端口起名、排序、写 tooltip）。
 *
 * ══════════════════════════════════════════════════════════════════
 * 五、演进路线（三阶段）
 * ══════════════════════════════════════════════════════════════════
 *  阶段 1（本模块，**零冻结**）：类型表 + 纯函数校验 + 后端镜像 + 守卫。
 *                              **不动任何 UI**（不碰注释里的「冻结区」文件）。
 *  阶段 2（需解冻 canvas-magnetic-intent）：CanvasShell 挂 `isValidConnection`
 *                              （拒绝非法连接 + 提示原因）；nodes.tsx 手柄按类型上色。
 *  阶段 3（需解冻）：多手柄渲染（每个类型一个手柄）+ 连接数量约束可视化。
 *
 * ⚠️ 唯一真源：本文件的 `NODE_PORTS` 表。
 *    后端镜像 `app/core/canvas_port_model.py` 必须与本表一致，
 *    由 `_verify/check_port_model.py` 静态比对（防漂移）。
 */
import type { NodeData } from "./stores/node-factory";

/** 端口数据类型。`any` 为通配（编组等容器用）。 */
export type PortType =
  | "text"
  | "image"
  | "video"
  | "audio"
  | "music"
  | "scene3d"
  | "grid"
  | "any";

/**
 * 端口槽位：**按类型计数**，不按名字。
 * `accepts: { text: 2 }` = 最多接受 2 条 text 入边。
 * 计数为 `Infinity` 时表示不限（用大数 99 表达，便于静态比对）。
 */
export type NodePorts = {
  accepts: Partial<Record<PortType, number>>;
  produces: Partial<Record<PortType, number>>;
};

/** 边的两种语义（见文件头 §三）。 */
export type EdgeKind = "data" | "associate";

/** 多输入上限的「不限」表示（用具体大数而非 Infinity，便于后端镜像与静态比对）。 */
export const UNBOUNDED = 99;

/**
 * 端口类型兼容表：**产出类型 → 它可满足的其它接受类型**。
 *
 * 为什么要单独一张表，而不是把兼容类型都塞进 `NODE_PORTS.accepts`：
 *  - `NODE_PORTS` 描述**节点能力**（这个节点能吃几路什么输入）；
 *  - 本表描述**类型系统**（哪些类型本质上是同一类数据）。
 *  两者变更频率不同：新增节点不该动类型规则，新增类型才该动这里。
 *
 * 例：`music` 是音频流的一种 → 任何接受 `audio` 的槽位（如 video 的配乐位）
 * 也必须接受 `music`，否则「音乐接不进视频」这种明显合法连接会被误拦。
 */
export const PORT_COMPAT: Partial<Record<PortType, PortType[]>> = {
  music: ["audio"],
};

/**
 * ════════ 单一真源：节点端口表 ════════
 *
 * 格式（**机器可解析**，后端守卫按此格式抽取比对，请勿改排版）：
 *   `  kind: { accepts: { ... }, produces: { ... } },`
 *
 * 填表纪律：
 *  - `accepts` 只接受**真的会被消费**的类型。例：image 节点接受 text（提示词）
 *    与 image（参考图）；不接受 video（它不消费视频）。
 *  - `produces` 写**主产物**类型；附带产物（如 digitalHuman 同时出音频与图）都写。
 *  - 纯前端 / 容器节点 `accepts: {}` / `produces: {}`。
 */
export const NODE_PORTS: Record<NodeData["kind"], NodePorts> = {
  script: { accepts: {}, produces: { text: 1 } },
  prompt: { accepts: { text: 2 }, produces: { text: 1 } },
  text: { accepts: { text: 2 }, produces: { text: 1 } },
  config: { accepts: { text: 2 }, produces: { text: 1 } },
  note: { accepts: {}, produces: { text: 1 } },
  markdown: { accepts: { text: 2 }, produces: { text: 1 } },
  shot: { accepts: { text: 2, image: 1 }, produces: { image: 1 } },
  image: { accepts: { text: 2, image: 1 }, produces: { image: 1 } },
  video: { accepts: { text: 1, image: 2, video: 1, audio: 1 }, produces: { video: 1 } },
  audio: { accepts: { text: 2 }, produces: { audio: 1 } },
  music: { accepts: { text: 2 }, produces: { music: 1 } },
  digitalHuman: { accepts: { text: 1, image: 1, audio: 1 }, produces: { audio: 1, image: 1 } },
  director: { accepts: {}, produces: { scene3d: 1, image: 1 } },
  directorCard: { accepts: { text: 2 }, produces: { text: 1, image: 1 } },
  storyboard: { accepts: { image: 1 }, produces: { grid: 1, image: 1 } },
  shotlist: { accepts: { video: 1, grid: 1 }, produces: { image: UNBOUNDED, text: 1 } },
  animation: { accepts: { text: 1, image: 1 }, produces: { image: UNBOUNDED, video: 1 } },
  panorama: { accepts: { text: 1 }, produces: { image: 1 } },
  generator: { accepts: { text: 3, image: 2, video: 1, audio: 1 }, produces: { text: 1, image: 1, video: 1, audio: 1 } },
  source: { accepts: {}, produces: { image: 1, video: 1, audio: 1 } },
  character: { accepts: {}, produces: { image: 1 } },
  group: { accepts: { any: UNBOUNDED }, produces: { any: 1 } },
};

/** 容错取值：未知 kind 视为「宽松」（不拦），避免新增节点类型时误报。 */
export function portsOf(kind: string): NodePorts {
  const p = (NODE_PORTS as Record<string, NodePorts | undefined>)[kind];
  return p || { accepts: { any: UNBOUNDED }, produces: { any: 1 } };
}

/**
 * 判断一条边是「数据流」还是「关联」。
 * 规则：**编组是组织容器** → 与它相连的边一律 associate（不参与执行、不做类型校验）。
 * 其余一律 data。
 */
export function edgeKindFor(sourceKind: string, targetKind: string): EdgeKind {
  if (sourceKind === "group" || targetKind === "group") return "associate";
  return "data";
}

export type ConnectVerdict = {
  ok: boolean;
  kind: EdgeKind;
  /** 命中的类型（ok=true 时有值） */
  via?: PortType;
  reason?: string;
};

/**
 * 校验一条连接：source 的某个输出类型，能否被 target 接受。
 *
 * **纯函数**，可被前端 `isValidConnection` 直接用作即时反馈，
 * 也可被后端在执行前复核。
 */
export function canConnect(sourceKind: string, targetKind: string): ConnectVerdict {
  const kind = edgeKindFor(sourceKind, targetKind);
  if (kind === "associate") {
    return { ok: true, kind, via: "any", reason: "编组关联（不参与数据流）" };
  }
  const src = portsOf(sourceKind);
  const dst = portsOf(targetKind);
  const outs = Object.keys(src.produces) as PortType[];
  // 任一侧是「通配」即放行：
  //  - target 接受 any（编组等容器）
  //  - source 产出 any（**未知 kind 的宽松兜底** —— 不误拦将来新增的节点类型）
  if ((dst.accepts.any ?? 0) > 0) return { ok: true, kind, via: "any" };
  if ((src.produces.any ?? 0) > 0) return { ok: true, kind, via: "any" };

  for (const t of outs) {
    if (t === "any") continue;
    if ((dst.accepts[t] ?? 0) > 0) return { ok: true, kind, via: t };
    // 类型兼容：produced 类型可通过 PORT_COMPAT 满足另一种接受类型
    for (const alt of PORT_COMPAT[t] || []) {
      if ((dst.accepts[alt] ?? 0) > 0) return { ok: true, kind, via: alt };
    }
  }
  const a = outs.filter((t) => t !== "any").join("/") || "无";
  const b = (Object.keys(dst.accepts) as PortType[]).filter((t) => t !== "any").join("/") || "无";
  return { ok: false, kind, reason: `${sourceKind} 产出「${a}」，而 ${targetKind} 只接受「${b}」` };
}

export type GraphProblem = {
  level: "error" | "warn";
  code: "type-mismatch" | "fan-in-exceeded" | "cycle" | "dangling";
  edgeId?: string;
  nodeId?: string;
  message: string;
};

type GNode = { id: string; type?: string; data?: { kind?: string } };
type GEdge = { id?: string; source: string; target: string };

function kindOf(n: GNode): string {
  return String(n?.data?.kind || n?.type || "");
}

/**
 * 校验整张图，返回问题列表（**不抛异常、不改图**）。
 * 供两处使用：前端「画布体检」面板；后端执行前复核。
 */
export function validateGraph(nodes: GNode[], edges: GEdge[]): GraphProblem[] {
  const problems: GraphProblem[] = [];
  const byId = new Map<string, GNode>();
  for (const n of nodes || []) if (n?.id) byId.set(String(n.id), n);

  const fanIn = new Map<string, Record<string, number>>();
  const dataEdges: Array<{ s: string; t: string; id?: string }> = [];

  for (const e of edges || []) {
    const s = String(e?.source || "");
    const t = String(e?.target || "");
    // 无端点的畸形边直接跳过：那不是「悬空引用」（引用了不存在的节点），
    // 而是数据错误。报成 dangling 只会给用户制造无法行动的噪声。
    if (!s || !t) continue;
    if (!byId.has(s) || !byId.has(t)) {
      problems.push({ level: "warn", code: "dangling", edgeId: e?.id, message: `悬空边被忽略：${s} → ${t}` });
      continue;
    }
    const sk = kindOf(byId.get(s)!);
    const tk = kindOf(byId.get(t)!);
    const v = canConnect(sk, tk);
    if (v.kind === "associate") continue;
    if (!v.ok) {
      problems.push({ level: "error", code: "type-mismatch", edgeId: e?.id, message: v.reason || "类型不匹配" });
      continue;
    }
    dataEdges.push({ s, t, id: e?.id });
    const rec = fanIn.get(t) || {};
    rec[v.via || "any"] = (rec[v.via || "any"] || 0) + 1;
    fanIn.set(t, rec);
  }

  for (const [nid, rec] of fanIn) {
    const dst = portsOf(kindOf(byId.get(nid)!));
    for (const [t, cnt] of Object.entries(rec)) {
      const cap = dst.accepts[t as PortType] ?? 0;
      if (t !== "any" && cnt > cap) {
        problems.push({
          level: "error", code: "fan-in-exceeded", nodeId: nid,
          message: `${kindOf(byId.get(nid)!)} 的 ${t} 输入超限：${cnt} > ${cap}`,
        });
      }
    }
  }

  for (const nid of detectCycle(dataEdges)) {
    problems.push({ level: "error", code: "cycle", nodeId: nid, message: `数据流成环：${nid}` });
  }
  return problems;
}

function detectCycle(edges: Array<{ s: string; t: string }>): string[] {
  const nodes = new Set<string>();
  const adj = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  for (const e of edges) {
    nodes.add(e.s);
    nodes.add(e.t);
    if (!adj.has(e.s)) adj.set(e.s, []);
    adj.get(e.s)!.push(e.t);
    indeg.set(e.t, (indeg.get(e.t) || 0) + 1);
    if (!indeg.has(e.s)) indeg.set(e.s, indeg.get(e.s) || 0);
  }
  const q: string[] = [];
  for (const n of nodes) if ((indeg.get(n) || 0) === 0) q.push(n);
  let seen = 0;
  while (q.length) {
    const n = q.shift()!;
    seen++;
    for (const m of adj.get(n) || []) {
      indeg.set(m, (indeg.get(m) || 0) - 1);
      if ((indeg.get(m) || 0) === 0) q.push(m);
    }
  }
  if (seen === nodes.size) return [];
  return [...nodes].filter((n) => (indeg.get(n) || 0) > 0).sort();
}

/** 端口类型的中文标签（UI 用）。 */
export const PORT_TYPE_LABEL: Record<PortType, string> = {
  text: "文本",
  image: "图像",
  video: "视频",
  audio: "音频",
  music: "音乐",
  scene3d: "3D 场景",
  grid: "宫格",
  any: "任意",
};
