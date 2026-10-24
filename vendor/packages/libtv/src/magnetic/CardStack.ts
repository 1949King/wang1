/**
 * 卡片层叠系统 — 纯函数操作
 *
 * 层叠是节点的多版本管理：同一张卡片可以有多个生成版本，
 * 像叠卡片一样堆叠在一起，用户可以切换版本、对比差异、混合参数。
 *
 * 层叠数据挂在 node.data.stack 上，不影响节点顶层 schema，
 * 旧节点没有 stack 字段时视为空层叠（只有 1 个隐式版本）。
 */

import {
  type CardStackData,
  type CardLayer,
  type StackAction,
  EMPTY_STACK,
} from "./types";

let _layerIdCounter = 0;
function genLayerId(): string {
  _layerIdCounter += 1;
  return `layer_${Date.now()}_${_layerIdCounter}`;
}

/**
 * 确保节点有层叠数据 — 没有则初始化
 * 旧节点没有 stack 时，从现有 data 推断初始层
 */
export function ensureStack(nodeData: Record<string, unknown>): CardStackData {
  const stack = nodeData.stack as CardStackData | undefined;
  if (stack && stack.layers.length > 0) return stack;

  // 新建初始层（从当前节点数据快照）
  const initialLayer: CardLayer = {
    id: genLayerId(),
    version: 1,
    status: (nodeData.status as CardLayer["status"]) || "idle",
    params: { ...nodeData },
    resultUrl: (nodeData.imageUrl || nodeData.videoUrl) as string | undefined,
    createdAt: Date.now(),
    isActive: true,
  };

  return {
    layers: [initialLayer],
    activeLayerId: initialLayer.id,
  };
}

/** 层叠 reducer — 纯函数，返回新的层叠数据 */
export function stackReducer(stack: CardStackData, action: StackAction): CardStackData {
  switch (action.type) {
    case "push": {
      const newVersion = stack.layers.length > 0
        ? Math.max(...stack.layers.map((l) => l.version)) + 1
        : 1;
      const newLayer: CardLayer = {
        id: genLayerId(),
        version: newVersion,
        status: "generating",
        params: action.params,
        resultUrl: action.resultUrl,
        createdAt: Date.now(),
        isActive: true,
      };
      return {
        layers: [
          ...stack.layers.map((l) => ({ ...l, isActive: false })),
          newLayer,
        ],
        activeLayerId: newLayer.id,
      };
    }

    case "remove": {
      const layers = stack.layers.filter((l) => l.id !== action.layerId);
      if (layers.length === 0) return EMPTY_STACK;
      let activeLayerId = stack.activeLayerId;
      if (activeLayerId === action.layerId) {
        // 激活最近的一层
        const idx = stack.layers.findIndex((l) => l.id === action.layerId);
        const nextIdx = Math.max(0, idx - 1);
        activeLayerId = layers[Math.min(nextIdx, layers.length - 1)].id;
        layers.forEach((l) => { l.isActive = l.id === activeLayerId; });
      }
      return { layers, activeLayerId };
    }

    case "activate": {
      return {
        layers: stack.layers.map((l) => ({
          ...l,
          isActive: l.id === action.layerId,
        })),
        activeLayerId: action.layerId,
      };
    }

    case "swap": {
      const layers = [...stack.layers];
      [layers[action.indexA], layers[action.indexB]] =
        [layers[action.indexB], layers[action.indexA]];
      return { ...stack, layers };
    }

    case "hybrid": {
      const layerA = stack.layers.find((l) => l.id === action.layerIdA);
      const layerB = stack.layers.find((l) => l.id === action.layerIdB);
      if (!layerA || !layerB) return stack;

      // 参数加权融合
      const hybridParams: Record<string, unknown> = {};
      const allKeys = new Set([
        ...Object.keys(layerA.params),
        ...Object.keys(layerB.params),
      ]);
      for (const key of allKeys) {
        const valA = layerA.params[key];
        const valB = layerB.params[key];
        // 数字类型加权
        if (typeof valA === "number" && typeof valB === "number") {
          hybridParams[key] = valA * action.weightA + valB * (1 - action.weightA);
        } else if (typeof valA === "string" && typeof valB === "string") {
          // 字符串：取 A + 渐变标记 + B（提示词混血）
          hybridParams[key] = `${valA}\n\n[混血 ${Math.round(action.weightA * 100)}% / ${Math.round((1 - action.weightA) * 100)}%]\n\n${valB}`;
        } else {
          // 其他类型按权重选
          hybridParams[key] = action.weightA > 0.5 ? valA : valB;
        }
      }

      const newVersion = Math.max(...stack.layers.map((l) => l.version)) + 1;
      const newLayer: CardLayer = {
        id: genLayerId(),
        version: newVersion,
        status: "idle",
        params: hybridParams,
        createdAt: Date.now(),
        isActive: true,
      };

      return {
        layers: [
          ...stack.layers.map((l) => ({ ...l, isActive: false })),
          newLayer,
        ],
        activeLayerId: newLayer.id,
      };
    }

    case "set_status": {
      return {
        ...stack,
        layers: stack.layers.map((l) => {
          if (l.id !== action.layerId) return l;
          return {
            ...l,
            status: action.status,
            issues: action.issues !== undefined ? action.issues : l.issues,
            qualityScore: action.qualityScore !== undefined ? action.qualityScore : l.qualityScore,
          };
        }),
      };
    }

    default:
      return stack;
  }
}

/** 获取当前激活层 */
export function getActiveLayer(stack: CardStackData): CardLayer | null {
  return stack.layers.find((l) => l.id === stack.activeLayerId) || null;
}

/** 对比两层参数差异 */
export function diffLayers(
  layerA: CardLayer,
  layerB: CardLayer,
): Array<{ key: string; a: unknown; b: unknown; type: "added" | "removed" | "changed" }> {
  const diffs: Array<{ key: string; a: unknown; b: unknown; type: "added" | "removed" | "changed" }> = [];
  const allKeys = new Set([...Object.keys(layerA.params), ...Object.keys(layerB.params)]);

  for (const key of allKeys) {
    const a = layerA.params[key];
    const b = layerB.params[key];
    const hasA = key in layerA.params;
    const hasB = key in layerB.params;

    if (hasA && !hasB) {
      diffs.push({ key, a, b: undefined, type: "removed" });
    } else if (!hasA && hasB) {
      diffs.push({ key, a: undefined, b, type: "added" });
    } else if (JSON.stringify(a) !== JSON.stringify(b)) {
      diffs.push({ key, a, b, type: "changed" });
    }
  }

  return diffs;
}
