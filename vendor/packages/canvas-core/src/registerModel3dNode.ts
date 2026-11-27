/**
 * 3D 模型节点动态注册（T5 图片转3D，2026-11-20）。
 *
 * registerBuiltinNodes.ts 在冻结区（canvas-magnetic-intent）⇒ 不改它；
 * 本文件独立注册 "builtin:model3d"，App.tsx 在 registerBuiltinNodes() 后调用。
 * defaultMetadata 经 defaultDataForRegistryType 自动生成 data（kind/title/status），
 * NodePalette 读 registry 自动出现「3D模型」入口，CanvasShell/store 零改动。
 */
import { registerNodeDefinitions } from "./plugins/node-registry";
import { Model3dNode } from "./model3dNode";

export function registerModel3dNode(): void {
  registerNodeDefinitions(
    [
      {
        type: "model3d",
        title: "3D模型",
        icon: "🧊",
        description: "图片转3D · 深度重建 2.5D GLB 网格（本地 Depth-Anything-V2，权重自取）",
        defaultSize: { width: 300, height: 340 },
        Component: Model3dNode,
        hasSourceHandle: true,
        defaultMetadata: { kind: "model3d", title: "3D模型", status: "idle" },
      },
    ],
    "builtin:model3d",
  );
}
