/**
 * infinite-canvas 插件生态兼容层
 *
 * - 接受 CanvasPlugin（id / nodes / setup）
 * - 支持 infinite 风格节点定义（Content + defaultMetadata + hasSourceHandle）
 * - 将 Content 包装为 React Flow Component
 */
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import React, { useCallback, useMemo } from "react";
import { useCanvasStore } from "../store";
import { getNodeDefinition } from "./node-registry";
import type { CanvasNodeDefinition, CanvasPlugin } from "./types";
import { getPluginRuntime } from "./plugin-runtime";

export type InfiniteStyleNodeDef = CanvasNodeDefinition & {
  defaultMetadata?: Record<string, unknown>;
  hasSourceHandle?: boolean;
  Content?: React.ComponentType<{ ctx: ShiguangNodeContext }>;
  Panel?: React.ComponentType<{ ctx: ShiguangNodeContext; onClose: () => void }>;
};

export type ShiguangNodeContext = {
  node: { id: string; type: string; data: Record<string, unknown> };
  isSelected: boolean;
  updateMetadata: (patch: Record<string, unknown>) => void;
  updateNode: (patch: { title?: string; width?: number; height?: number }) => void;
  getNodes: () => Node[];
  emit: (event: string, payload?: unknown) => void;
  on: (event: string, handler: (payload: unknown) => void) => () => void;
  ai: NonNullable<ReturnType<typeof getPluginRuntime>["ai"]>;
};

function useNodeContext(
  props: NodeProps<Node<Record<string, unknown>>>,
  def: InfiniteStyleNodeDef,
): ShiguangNodeContext {
  const { id, data, selected, type } = props;
  const updateNodeData = useCanvasStore((s) => s.updateNodeData);
  const nodes = useCanvasStore((s) => s.nodes);
  const rt = getPluginRuntime();

  const updateMetadata = useCallback(
    (patch: Record<string, unknown>) => {
      updateNodeData(id, patch);
    },
    [id, updateNodeData],
  );

  const updateNode = useCallback(
    (patch: { title?: string; width?: number; height?: number }) => {
      const meta: Record<string, unknown> = {};
      if (patch.title != null) meta.title = patch.title;
      if (Object.keys(meta).length) updateNodeData(id, meta);
      if (patch.width != null || patch.height != null) {
        useCanvasStore.setState({
          nodes: nodes.map((n) =>
            n.id === id
              ? {
                  ...n,
                  style: {
                    ...n.style,
                    ...(patch.width != null ? { width: patch.width } : {}),
                    ...(patch.height != null ? { height: patch.height } : {}),
                  },
                }
              : n,
          ),
        });
      }
    },
    [id, nodes, updateNodeData],
  );

  return useMemo(
    () => ({
      node: { id, type: type || def.type, data: data || {} },
      isSelected: !!selected,
      updateMetadata,
      updateNode,
      getNodes: () => useCanvasStore.getState().nodes,
      emit: rt.emit,
      on: rt.on,
      ai: rt.ai || {
        generateImage: async (opts: { prompt: string; model: string; size: string; channel_id: string; reference_image: string; quality: string }) => [],
        generateVideo: async (opts: { prompt: string; model: string; duration: number; quality: string }) => "",
        generateText: async () => "",
        listModels: () => [],
        defaultModel: () => "",
      },
    }),
    [id, type, data, selected, def.type, updateMetadata, updateNode, rt],
  );
}

function wrapContentComponent(def: InfiniteStyleNodeDef): CanvasNodeDefinition["Component"] {
  const Content = def.Content!;
  function Wrapped(props: NodeProps<Node<Record<string, unknown>>>) {
    const ctx = useNodeContext(props, def);
    const showSource = def.hasSourceHandle !== false;
    return (
      <div className={`sg-node plugin-node ${def.type.replace(/:/g, "_")}`}>
        <Handle type="target" position={Position.Left} />
        <Content ctx={ctx} />
        {showSource ? <Handle type="source" position={Position.Right} /> : null}
      </div>
    );
  }
  return Wrapped;
}

function adaptNodeDefinition(raw: InfiniteStyleNodeDef): CanvasNodeDefinition {
  let Component = raw.Component;
  if (!Component && raw.Content) {
    Component = wrapContentComponent(raw);
  }
  if (!Component) {
    Component = function FallbackPluginNode() {
      return (
        <div className="sg-node plugin-node">
          <Handle type="target" position={Position.Left} />
          <div className="head">{raw.title}</div>
          <div className="meta">插件节点缺少 Component/Content</div>
          <Handle type="source" position={Position.Right} />
        </div>
      );
    };
  }
  return {
    type: raw.type,
    title: raw.title,
    icon: raw.icon,
    description: raw.description,
    defaultSize: raw.defaultSize || { width: 340, height: 240 },
    Component,
    showInCreateMenu: raw.showInCreateMenu !== false,
  };
}

/** 规范化 infinite / 拾光 插件导出 */
export function normalizeInfinitePlugin(exported: unknown): CanvasPlugin {
  const rt = getPluginRuntime();
  let plugin: CanvasPlugin;
  if (typeof exported === "function") {
    plugin = (exported as (runtime: unknown) => CanvasPlugin)(rt);
  } else {
    plugin = exported as CanvasPlugin;
  }
  if (!plugin?.id || !Array.isArray(plugin.nodes) || !plugin.nodes.length) {
    throw new Error("插件缺少 id 或 nodes[]");
  }
  if (plugin.minAppVersion) {
    console.info(
      `[plugin] ${plugin.id} minAppVersion=${plugin.minAppVersion} host=${rt.version}`,
    );
  }
  const nodes = plugin.nodes.map((n) => adaptNodeDefinition(n as InfiniteStyleNodeDef));
  const setup = plugin.setup
    ? () => {
        const app = {
          version: rt.version,
          emit: rt.emit,
          on: rt.on,
          injectCSS: rt.injectCSS,
        };
        return plugin.setup!(app as Parameters<NonNullable<CanvasPlugin["setup"]>>[0]);
      }
    : undefined;
  return { ...plugin, nodes, setup };
}

/** 从注册表创建插件节点默认 data */
export function defaultDataForRegistryType(type: string): Record<string, unknown> {
  const def = getNodeDefinition(type) as InfiniteStyleNodeDef | undefined;
  const meta = def?.defaultMetadata || {};
  return {
    kind: type,
    title: def?.title || type,
    content: String(meta.content ?? ""),
    prompt: String(meta.prompt ?? meta.content ?? ""),
    text: String(meta.content ?? meta.prompt ?? ""),
    generationMode: meta.generationMode ?? "image",
    status: meta.status ?? "idle",
    ...meta,
  };
}
